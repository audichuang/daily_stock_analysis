# -*- coding: utf-8 -*-
"""境內基金查詢與基金持倉（帳本外）。

資料面：
- 基金清單與淨值讀 ``market`` schema（``market.fund_info``／``market.fund_nav``），由
  ``market_data.funds`` 每日從投信投顧公會入庫；查詢某檔時若歷史未涵蓋全期，當下從鉅亨補一次
  （補過的基金之後會被 ``daily`` 一併保鮮）。
- 前十大持股即時抓鉅亨、不入庫，失敗回空清單與錯誤碼，不影響其他欄位。

持倉面：``portfolio_fund_holdings``（應用庫）只存單位數與成本，市值一律以最新淨值現算，
並帶出淨值日讓呼叫端判斷新鮮度——拿不到淨值時市值回 ``None``，不用 0 冒充。
"""

from __future__ import annotations

import logging
import math
import numbers
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from src.storage import DatabaseManager, PortfolioFundHolding

logger = logging.getLogger(__name__)

# 歷史起點離成立日在這麼多天內，就當作已涵蓋全期（首筆淨值常晚於成立日幾週）
INCEPTION_GRACE_DAYS = 45
# 最新淨值日距今超過這麼多天就標 stale（基金假日不計價，連假約 9~10 天）
STALE_AFTER_DAYS = 10
MARKET_STATEMENT_TIMEOUT_MS = 5000

# 鍵名不用數字開頭：前端 camelcase-keys 對 "1w" 這類鍵的轉換不可靠
RETURN_PERIODS = (
    ("w1", 7), ("m1", 30), ("m3", 91), ("m6", 182), ("y1", 365), ("y3", 365 * 3), ("y5", 365 * 5),
)
# 歷史涵蓋最長報酬期間（近五年）就不必再補
FULL_HISTORY_DAYS = max(days for _, days in RETURN_PERIODS)
BENCHMARK_INDEX_ID = "TAIEX"


class FundUnavailableError(RuntimeError):
    """基金資料庫（market schema）不可用。"""


class FundNotFoundError(LookupError):
    """查無此基金。"""


@dataclass
class FundGateway:
    """market schema 與外部來源的接縫；測試換成假的。"""

    search: Callable[..., Any]
    info: Callable[..., Any]
    history: Callable[..., Any]
    latest_navs: Callable[..., Any]
    backfill: Callable[..., Any]
    top_holdings: Callable[..., Any]
    recent_navs: Optional[Callable[..., Any]] = None
    index_history: Optional[Callable[..., Any]] = None

    @classmethod
    def default(cls) -> "FundGateway":
        from market_data import funds, market_repo
        from market_data.db import get_engine

        def engine():
            return get_engine(statement_timeout_ms=MARKET_STATEMENT_TIMEOUT_MS)

        def top_holdings(fund_id: str):
            cnyes_id = funds.ensure_cnyes_id(get_engine(), fund_id)
            return funds.fetch_top_holdings(cnyes_id) if cnyes_id else None

        return cls(
            search=lambda q, limit: market_repo.fund_search(q, limit=limit, engine=engine()),
            info=lambda fund_id: market_repo.fund_info(fund_id, engine=engine()),
            history=lambda fund_id, start=None: market_repo.fund_nav_history(fund_id, start=start, engine=engine()),
            latest_navs=lambda ids: market_repo.fund_latest_navs(ids, engine=engine()),
            backfill=lambda fund_id: funds.backfill_history(get_engine(), fund_id),
            top_holdings=top_holdings,
            recent_navs=lambda ids: market_repo.fund_recent_navs(ids, engine=engine()),
            index_history=lambda index_id, start=None, end=None: market_repo.market_index_history(
                index_id, start=start, end=end, engine=engine()),
        )


def _clean(value: Any) -> Any:
    """DB／pandas 值 → JSON 安全的 Python 值：NaN／NaT → None，Decimal／numpy → float／int，Timestamp → date。"""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, datetime) or hasattr(value, "to_pydatetime"):
        try:
            return value.date()
        except (ValueError, TypeError):  # NaT
            return None
    if isinstance(value, date):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, (numbers.Real, Decimal)):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


def _row(record: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _clean(v) for k, v in record.items()}


def _records(df) -> List[Dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    return [_row(r) for r in df.to_dict("records")]


def _holdings_month(portfolio_date: Any) -> Optional[str]:
    """鉅亨 portfolioDate（epoch 秒）→ 台北時區的 ``YYYY-MM``；拿不到回 None。"""
    if isinstance(portfolio_date, bool) or not isinstance(portfolio_date, numbers.Real):
        return None
    try:
        return datetime.fromtimestamp(float(portfolio_date), ZoneInfo("Asia/Taipei")).strftime("%Y-%m")
    except (ValueError, OverflowError, OSError):
        return None


def _match_key(name: Any) -> str:
    return "".join(str(name or "").split()).casefold()


def nav_on_or_before(series: List[Dict[str, Any]], target: date) -> Optional[Dict[str, Any]]:
    """升序淨值序列中 ``target`` 當日或之前的最後一筆。"""
    found = None
    for point in series:
        if point["date"] > target:
            break
        found = point
    return found


_PERIOD_DAYS = dict(RETURN_PERIODS)
PERIOD_KEYS = tuple(_PERIOD_DAYS) + ("ytd",)


def period_base_target(last_date: date, key: str) -> date:
    """期間報酬的起點日：最新淨值日回推（ytd 是去年最後一天）；實際基準取這天當日或之前最後一筆。

    報酬卡（``compute_returns``）與走勢圖區間（``get_nav_history(period=)``）共用，兩邊才會是同一個基準日。"""
    if key == "ytd":
        return date(last_date.year, 1, 1) - timedelta(days=1)
    return last_date - timedelta(days=_PERIOD_DAYS[key])


def compute_returns(series: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """各期間報酬率（%）：以最新淨值日回推，起點取當日或之前最後一筆；期間不足的回 None。

    淨值未含配息（配息型級別的報酬會被低估），呼叫端要標示。"""
    out: Dict[str, Optional[float]] = {key: None for key, _ in RETURN_PERIODS}
    out["ytd"] = None
    if not series:
        return out
    last = series[-1]
    first_date = series[0]["date"]
    for key in PERIOD_KEYS:
        target = period_base_target(last["date"], key)
        if target < first_date:
            continue
        base = nav_on_or_before(series, target)
        if base and base["nav"]:
            out[key] = (last["nav"] / base["nav"] - 1) * 100
    return out


def compute_risk(series: List[Dict[str, Any]], days: int = 365) -> Dict[str, Optional[float]]:
    """近 ``days`` 天的最大回撤（%，負值）與年化波動率（%）；資料不足回 None。"""
    if len(series) < 20:
        return {"max_drawdown": None, "volatility": None}
    start = series[-1]["date"] - timedelta(days=days)
    window = [p for p in series if p["date"] >= start and p["nav"]]
    if len(window) < 20:
        return {"max_drawdown": None, "volatility": None}
    peak, worst = window[0]["nav"], 0.0
    for point in window:
        peak = max(peak, point["nav"])
        worst = min(worst, point["nav"] / peak - 1)
    rets = [b["nav"] / a["nav"] - 1 for a, b in zip(window, window[1:])]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
    return {"max_drawdown": worst * 100, "volatility": math.sqrt(var) * math.sqrt(252) * 100}


class FundService:
    def __init__(self, gateway: Optional[FundGateway] = None, db: Optional[DatabaseManager] = None):
        self._gateway = gateway
        self._db = db

    @property
    def gateway(self) -> FundGateway:
        if self._gateway is None:
            self._gateway = FundGateway.default()
        return self._gateway

    @property
    def db(self) -> DatabaseManager:
        if self._db is None:
            self._db = DatabaseManager.get_instance()
        return self._db

    def _market(self, fn: Callable[..., Any], *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (FundNotFoundError, FundUnavailableError):
            raise
        except Exception as exc:  # noqa: BLE001 - DB 連線/未遷移都歸為不可用
            logger.warning("fund market query failed: %s", exc)
            raise FundUnavailableError(str(exc)) from exc

    # ---- 查詢 ----

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        return _records(self._market(self.gateway.search, query, limit))

    def _info(self, fund_id: str) -> Dict[str, Any]:
        info = self._market(self.gateway.info, fund_id)
        if not info:
            raise FundNotFoundError(fund_id)
        return _row(info)

    def _series(self, fund_id: str, start: Optional[date] = None) -> List[Dict[str, Any]]:
        return [p for p in _records(self._market(self.gateway.history, fund_id, start=start))
                if p.get("date") is not None and p.get("nav") is not None]

    @staticmethod
    def _history_complete(info: Dict[str, Any], series: List[Dict[str, Any]]) -> bool:
        """歷史是否已涵蓋全期：起點早於最長報酬期間，或起點貼近成立日。

        不能看筆數：公會每天替約 4,400 檔各寫一筆，累積一個多月後沒補過的基金也會「夠多筆」，
        卻只有公會入庫以來的短歷史。也不能看有沒有鉅亨來源的列：``daily`` 對已有鉅亨對照的
        基金只補近 35 天，那些列不代表全期補過。"""
        if not series:
            return False
        first, last = series[0]["date"], series[-1]["date"]
        if first <= last - timedelta(days=FULL_HISTORY_DAYS):
            return True
        inception = info.get("inception_date")
        return isinstance(inception, date) and first <= inception + timedelta(days=INCEPTION_GRACE_DAYS)

    def _ensure_history(self, fund_id: str, info: Dict[str, Any], series: List[Dict[str, Any]]):
        """歷史未涵蓋全期時從鉅亨補一次；失敗只記警告，回傳 (series, 錯誤訊息)。"""
        if self._history_complete(info, series):
            return series, None
        try:
            self.gateway.backfill(fund_id)
        except Exception as exc:  # noqa: BLE001 - 非官方來源失敗不擋查詢
            logger.warning("fund history backfill failed for %s: %s", fund_id, exc)
            return series, str(exc)[:200]
        return self._series(fund_id), None

    def get_detail(self, fund_id: str, today: Optional[date] = None) -> Dict[str, Any]:
        info = self._info(fund_id)
        series, history_error = self._ensure_history(fund_id, info, self._series(fund_id))
        latest = series[-1] if series else None
        today = today or date.today()
        return {
            **info,
            "nav": latest["nav"] if latest else None,
            "nav_date": latest["date"] if latest else None,
            "nav_change": latest.get("change") if latest else None,
            "nav_change_pct": latest.get("change_pct") if latest else None,
            "nav_source": latest.get("source") if latest else None,
            "is_stale": bool(latest and (today - latest["date"]).days > STALE_AFTER_DAYS) if latest else True,
            "history_start": series[0]["date"] if series else None,
            "history_points": len(series),
            "history_error": history_error,
            "returns": compute_returns(series),
            "risk": compute_risk(series),
        }

    def get_nav_history(self, fund_id: str, days: Optional[int] = None,
                        period: Optional[str] = None, benchmark: Optional[str] = None) -> Dict[str, Any]:
        """``period``（m1…y5、ytd）：從報酬卡同一個基準點（``period_base_target`` 當日或之前最後一筆）起算，
        首尾相除就等於 ``returns[period]``；歷史不足一個期間時回全部。``days`` 是舊參數（以今天回推、
        取之後的第一筆），兩者都給時以 ``period`` 為準。"""
        self._info(fund_id)
        if period:
            points = self._series(fund_id)
            if points:
                base = nav_on_or_before(points, period_base_target(points[-1]["date"], period))
                if base is not None:
                    points = points[points.index(base):]
        else:
            start = date.today() - timedelta(days=days) if days else None
            points = self._series(fund_id, start=start)
        out = {"fund_id": fund_id,
               "points": [{"date": p["date"], "nav": p["nav"]} for p in points]}
        if benchmark == "taiex":
            out.update(self._benchmark_block(points))
        return out

    def _benchmark_block(self, points: List[Dict[str, Any]]) -> Dict[str, Any]:
        """與淨值同區間的加權指數收盤。指數查不到只影響比較線，不影響淨值本身。"""
        if not points:
            return {"benchmark": None, "benchmark_error": None}
        try:
            rows = _records(self.gateway.index_history(
                BENCHMARK_INDEX_ID, start=points[0]["date"], end=points[-1]["date"]))
        except Exception as exc:  # noqa: BLE001 - 比較線失敗不擋走勢圖
            logger.warning("fund benchmark history failed: %s", exc)
            return {"benchmark": None, "benchmark_error": "source_unavailable"}
        series = [{"date": r["date"], "close": r["close"]}
                  for r in rows if r.get("date") is not None and r.get("close") is not None]
        if not series:
            return {"benchmark": None, "benchmark_error": "no_data"}
        return {"benchmark": {"index_id": BENCHMARK_INDEX_ID, "points": series}, "benchmark_error": None}

    def get_top_holdings(self, fund_id: str) -> Dict[str, Any]:
        self._info(fund_id)
        try:
            items = self.gateway.top_holdings(fund_id)
        except Exception as exc:  # noqa: BLE001 - 非官方來源失敗不擋頁面
            logger.warning("fund top holdings failed for %s: %s", fund_id, exc)
            return {"fund_id": fund_id, "items": [], "error": "source_unavailable"}
        if items is None:
            return {"fund_id": fund_id, "items": [], "error": "not_mapped"}
        rows = [_row(i) for i in items]
        month = _holdings_month(rows[0].get("portfolio_date")) if rows else None
        ledger = self._ledger_symbols_by_name()
        overlap = []
        for row in rows:
            symbol = ledger.get(_match_key(row.get("name")))
            row["ledger_symbol"] = symbol
            if symbol:
                overlap.append({"symbol": symbol, "name": row.get("name"), "weight": row.get("weight")})
        return {"fund_id": fund_id, "items": rows, "error": None, "as_of_month": month, "overlap": overlap}

    def _ledger_symbols_by_name(self) -> Dict[str, str]:
        """帳本持股的「名稱鍵 → 代號」。只收名稱唯一對到一檔的，比對不到或同名多檔都不標。

        前十大持股只有名稱，沒有代號；海外持股的名稱多半對不上，寧可漏標也不猜。
        帳本查不到只少標記，不影響持股清單。"""
        from src.data.stock_index_loader import get_index_stock_name
        from src.repositories.portfolio_repo import PortfolioRepository

        try:
            identities = PortfolioRepository(self.db).list_cached_position_identities()
        except Exception as exc:  # noqa: BLE001 - 重疊標記是附加資訊
            logger.warning("fund overlap ledger lookup failed: %s", exc)
            return {}
        found: Dict[str, set] = {}
        for _, symbol in identities:
            key = _match_key(get_index_stock_name(symbol))
            if key:
                found.setdefault(key, set()).add(symbol)
        return {key: next(iter(symbols)) for key, symbols in found.items() if len(symbols) == 1}

    # ---- 持倉 ----

    @staticmethod
    def _holding_dict(h: PortfolioFundHolding) -> Dict[str, Any]:
        return {
            "id": h.id, "platform": h.platform, "fund_id": h.fund_id, "fund_name": h.fund_name,
            "units": h.units, "cost_total": h.cost_total, "currency": h.currency,
            "as_of": h.as_of, "note": h.note,
        }

    def list_holdings(self, today: Optional[date] = None) -> Dict[str, Any]:
        with self.db.get_session() as session:
            rows = [self._holding_dict(h) for h in
                    session.query(PortfolioFundHolding).order_by(PortfolioFundHolding.id).all()]
        navs: Dict[str, Any] = {}
        nav_error = None
        if rows:
            try:
                navs = self._market(self.gateway.latest_navs, sorted({r["fund_id"] for r in rows}))
            except FundUnavailableError as exc:
                nav_error = str(exc)[:200]
        recent = self._recent_navs(sorted({r["fund_id"] for r in rows})) if rows else {}
        today = today or date.today()
        totals: Dict[str, Dict[str, float]] = {}
        for r in rows:
            nav_info = navs.get(r["fund_id"])
            nav, nav_date = (nav_info if nav_info else (None, None))
            value = r["units"] * nav if nav is not None else None
            is_stale = nav_date is None or (today - nav_date).days > STALE_AFTER_DAYS
            nav_change_pct, day_pnl = self._day_change(r["units"], nav, nav_date, is_stale, recent.get(r["fund_id"]))
            r.update({
                "nav": nav, "nav_date": nav_date,
                "is_stale": is_stale,
                "nav_change_pct": nav_change_pct,
                "day_pnl": day_pnl,
                "market_value": value,
                "pnl": value - r["cost_total"] if value is not None else None,
                "pnl_pct": (value / r["cost_total"] - 1) * 100 if value is not None and r["cost_total"] else None,
            })
            bucket = totals.setdefault(r["currency"], {"market_value": 0.0, "cost_total": 0.0, "complete": True,
                                                       "day_pnl": 0.0, "day_complete": True})
            bucket["cost_total"] += r["cost_total"]
            if day_pnl is None:
                bucket["day_complete"] = False
            else:
                bucket["day_pnl"] += day_pnl
            if value is None:
                bucket["complete"] = False
            else:
                bucket["market_value"] += value
        summary = []
        for currency, t in sorted(totals.items()):
            complete = t["complete"]
            summary.append({
                "currency": currency,
                "cost_total": t["cost_total"],
                "market_value": t["market_value"] if complete else None,
                "pnl": t["market_value"] - t["cost_total"] if complete else None,
                "pnl_pct": ((t["market_value"] / t["cost_total"] - 1) * 100
                            if complete and t["cost_total"] else None),
                "day_pnl": t["day_pnl"] if t["day_complete"] else None,
            })
        return {"items": rows, "totals": summary, "nav_error": nav_error}

    def _recent_navs(self, fund_ids: List[str]) -> Dict[str, Any]:
        """各基金最新兩筆淨值；查不到時今日損益回 null，不影響市值（nav_error 已涵蓋連線失敗）。"""
        if self.gateway.recent_navs is None:
            return {}
        try:
            return self._market(self.gateway.recent_navs, fund_ids) or {}
        except FundUnavailableError:
            return {}

    @staticmethod
    def _day_change(units: float, nav: Optional[float], nav_date: Optional[date], is_stale: bool,
                    recent: Optional[List[Any]]):
        """最新淨值相對前一筆的漲跌與損益；過期淨值、只有一筆或兩邊日期對不上都回 (None, None)。"""
        if nav is None or is_stale or not recent or len(recent) < 2:
            return None, None
        (latest_nav, latest_date), (prev_nav, _) = recent[0], recent[1]
        if latest_date != nav_date or latest_nav != nav or not prev_nav:
            return None, None
        return (nav / prev_nav - 1) * 100, units * (nav - prev_nav)

    def create_holding(self, *, fund_id: str, units: float, cost_total: float, as_of: date,
                       platform: str = "", note: Optional[str] = None) -> Dict[str, Any]:
        info = self._info(fund_id)
        with self.db.session_scope() as session:
            exists = session.query(PortfolioFundHolding).filter_by(platform=platform, fund_id=fund_id).first()
            if exists:
                raise ValueError("duplicate_holding")
            holding = PortfolioFundHolding(
                platform=platform, fund_id=fund_id, fund_name=info["name"], units=units,
                cost_total=cost_total, currency=info.get("currency") or "TWD", as_of=as_of, note=note)
            session.add(holding)
            session.flush()
            result = self._holding_dict(holding)
        # 持有的基金要有鉅亨對照與歷史，daily 才會持續補缺（失敗不擋建立）
        try:
            self._ensure_history(fund_id, info, self._series(fund_id))
        except FundUnavailableError:
            pass
        return result

    def update_holding(self, holding_id: int, **fields) -> Optional[Dict[str, Any]]:
        allowed = {"units", "cost_total", "as_of", "platform", "note"}
        with self.db.session_scope() as session:
            holding = session.get(PortfolioFundHolding, holding_id)
            if holding is None:
                return None
            platform = fields.get("platform")
            if platform is not None and platform != holding.platform:
                # 與 create 同一條規則：同通路同基金只能有一筆（否則撞唯一鍵變 500）
                clash = (session.query(PortfolioFundHolding)
                         .filter(PortfolioFundHolding.platform == platform,
                                 PortfolioFundHolding.fund_id == holding.fund_id,
                                 PortfolioFundHolding.id != holding.id)
                         .first())
                if clash:
                    raise ValueError("duplicate_holding")
            for key, value in fields.items():
                if key in allowed and value is not None:
                    setattr(holding, key, value)
            session.flush()
            return self._holding_dict(holding)

    def delete_holding(self, holding_id: int) -> bool:
        with self.db.session_scope() as session:
            holding = session.get(PortfolioFundHolding, holding_id)
            if holding is None:
                return False
            session.delete(holding)
            return True
