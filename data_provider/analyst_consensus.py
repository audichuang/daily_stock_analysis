# -*- coding: utf-8 -*-
"""賣方共識（分析師目標價／EPS 修正／評級）— yfinance 彙整，台股＋美股，僅供參考。

只在基本面階段呼叫（不在報價路徑，避免把 ticker.info 加回看板延遲）。
任何例外回 None（fail-open）；yfinance 對台股常在 stderr 印「HTTP 404 No fundamentals
data found」，那是另一個子模組，不代表本函式失敗。

狀態：
- ok：n>=3 且價格日期新鮮
- thin：n<3，呼叫端只印分析師數、不印數字
- stale：價格時間戳落後今天超過 _MAX_PRICE_AGE_DAYS 曆日，或與呼叫端的參考價相差 >3%
  （yfinance 沒有共識本身的 as_of，只能用價格間接判斷）
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Tuple

from data_provider.yfinance_fundamental_adapter import _convert_to_yf_symbol, _safe_float

logger = logging.getLogger(__name__)

_MIN_ANALYSTS = 3
_MAX_PRICE_AGE_DAYS = 4  # 曆日；涵蓋週末＋一天假日
_MAX_PRICE_GAP = 0.03
_MAX_ABS_REVISION_PCT = 50.0  # 超過視為基期異常（如 90 天前 EPS≈0），該欄設 None

# ponytail: 程序級快取、以 (symbol, 日期) 為 key，只長不清；一天幾十檔無所謂，常駐服務跨日才會累積
_CACHE: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


def _today() -> date:
    return date.today()


def _pct_change(cur: Optional[float], base: Optional[float]) -> Optional[float]:
    if cur is None or base is None or base == 0:
        return None
    pct = (cur / base - 1.0) * 100.0
    if abs(pct) > _MAX_ABS_REVISION_PCT:
        return None
    return round(pct, 2)


def _row(df: Any, period: str) -> Optional[Any]:
    try:
        if df is None or getattr(df, "empty", True) or period not in df.index:
            return None
        return df.loc[period]
    except Exception:  # noqa: BLE001
        return None


def _cell(row: Any, key: str) -> Optional[float]:
    if row is None:
        return None
    try:
        return _safe_float(row.get(key))
    except Exception:  # noqa: BLE001
        return None


def _buy_share(df: Any, period: str) -> Optional[float]:
    """recommendations 某期（0m/-3m）的 strongBuy+buy 佔比（%）。"""
    try:
        if df is None or getattr(df, "empty", True) or "period" not in df.columns:
            return None
        rows = df[df["period"] == period]
        if rows.empty:
            return None
        r = rows.iloc[0]
        counts = [float(r.get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")]
        total = sum(counts)
        return None if total <= 0 else (counts[0] + counts[1]) / total * 100.0
    except Exception:  # noqa: BLE001
        return None


def _build(ticker: Any, ref_price: Optional[float]) -> Optional[Dict[str, Any]]:
    info = ticker.info or {}
    n = info.get("numberOfAnalystOpinions")
    try:
        n = int(n) if n is not None else None
    except (TypeError, ValueError):
        n = None
    median = _safe_float(info.get("targetMedianPrice"))
    if not n and median is None:
        return None  # 沒有覆蓋（ETF、小型股）

    current = _safe_float(info.get("currentPrice")) or _safe_float(info.get("regularMarketPrice"))
    as_of = None
    ts = info.get("regularMarketTime")
    try:
        if ts:
            as_of = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
    except (TypeError, ValueError, OverflowError, OSError):
        as_of = None

    if n is None or n < _MIN_ANALYSTS:
        return {"source": "yfinance", "status": "thin", "n_analysts": n,
                "as_of": as_of.isoformat() if as_of else None}

    status = "ok"
    if as_of is None or (_today() - as_of).days > _MAX_PRICE_AGE_DAYS:
        status = "stale"
    if ref_price and current and abs(current / ref_price - 1.0) > _MAX_PRICE_GAP:
        status = "stale"

    base_price = ref_price or current
    low = _safe_float(info.get("targetLowPrice"))
    high = _safe_float(info.get("targetHighPrice"))

    eps_trend = getattr(ticker, "eps_trend", None)
    eps_rev = getattr(ticker, "eps_revisions", None)
    est = getattr(ticker, "earnings_estimate", None)
    recs = getattr(ticker, "recommendations", None)

    fy1_trend = _row(eps_trend, "+1y")
    fy1_cur = _cell(fy1_trend, "current")
    fy1_rev = _row(eps_rev, "+1y")
    up30 = _cell(fy1_rev, "upLast30days")
    down30 = _cell(fy1_rev, "downLast30days")
    rev30 = _pct_change(fy1_cur, _cell(fy1_trend, "30daysAgo"))
    rev90 = _pct_change(fy1_cur, _cell(fy1_trend, "90daysAgo"))
    if up30 is None and down30 is None and rev30 is None:
        direction = None
    elif not up30 and not down30 and not rev30 and not rev90:
        # 沒有任何修正活動，不是「穩定」
        direction = "no_activity"
    elif (up30 or 0) > (down30 or 0) and (rev30 is None or rev30 >= 0):
        direction = "up"
    elif (down30 or 0) > (up30 or 0) and (rev30 is None or rev30 <= 0):
        direction = "down"
    else:
        direction = "mixed"

    fy1_est = _row(est, "+1y")
    fy1_low, fy1_high, fy1_avg = _cell(fy1_est, "low"), _cell(fy1_est, "high"), _cell(fy1_est, "avg")
    dispersion = (
        round((fy1_high - fy1_low) / abs(fy1_avg) * 100.0, 1)
        if fy1_low is not None and fy1_high is not None and fy1_avg
        else None
    )
    share_now, share_3m = _buy_share(recs, "0m"), _buy_share(recs, "-3m")

    return {
        "source": "yfinance",
        "status": status,
        "n_analysts": n,
        "as_of": as_of.isoformat() if as_of else None,
        "price": current,
        "target_median": median,
        "target_mean": _safe_float(info.get("targetMeanPrice")),
        "target_low": low,
        "target_high": high,
        "implied_upside_pct": (
            round((median / base_price - 1.0) * 100.0, 1) if median and base_price else None
        ),
        "eps_fy0": _cell(_row(eps_trend, "0y"), "current"),
        "eps_fy1": fy1_cur,
        "eps_fy1_rev_30d_pct": rev30,
        "eps_fy1_rev_90d_pct": rev90,
        "eps_fy1_up_30d": int(up30) if up30 is not None else None,
        "eps_fy1_down_30d": int(down30) if down30 is not None else None,
        "eps_fy1_revision_direction": direction,
        "eps_fy1_dispersion_pct": dispersion,
        "rec_mean": _safe_float(info.get("recommendationMean")),
        "rec_key": info.get("recommendationKey"),
        "rec_buy_share_change_3m_pct": (
            round(share_now - share_3m, 1) if share_now is not None and share_3m is not None else None
        ),
    }


def fetch_analyst_consensus(stock_code: str, ref_price: Any = None) -> Optional[Dict[str, Any]]:
    """回傳賣方共識 dict，或 None（無覆蓋／任何錯誤）。同一 symbol 同一天只抓一次。"""
    symbol = _convert_to_yf_symbol(stock_code)
    if not symbol:
        return None
    ref_price = _safe_float(ref_price)
    if ref_price is not None and ref_price <= 0:
        ref_price = None
    key = (symbol, _today().isoformat())
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]
    try:
        import yfinance as yf

        result = _build(yf.Ticker(symbol), ref_price)
    except Exception as exc:  # noqa: BLE001 - fail-open by design
        logger.info("[consensus] %s fetch failed: %s", symbol, exc)
        return None  # 失敗不進快取，下次重試
    with _CACHE_LOCK:
        _CACHE[key] = result
    return result


def _fmt(value: Any, suffix: str = "", signed: bool = False) -> str:
    v = _safe_float(value)
    if v is None:
        return "N/A"
    return (f"{v:+.1f}" if signed else f"{round(v, 2):g}") + suffix


def format_analyst_consensus_block(consensus: Any, report_language: str = "zh-TW") -> str:
    """把共識 dict 排成 prompt 區塊；None／無效狀態回空字串（prompt 就不出現這段）。

    重點放在 EPS 修正方向與分歧，目標價水準只當背景，並固定附上「不得據此提高信心」的提示。
    """
    if not isinstance(consensus, dict):
        return ""
    status = consensus.get("status")
    if status not in ("ok", "stale", "thin"):
        return ""
    english = report_language in ("en", "ko")
    tw = report_language == "zh-TW"

    def L(zh_tw: str, zh: str, en: str) -> str:
        return en if english else (zh_tw if tw else zh)

    n = consensus.get("n_analysts")
    as_of = consensus.get("as_of") or "N/A"
    if status == "thin":
        return "\n" + L(
            f"> 賣方共識：僅 {n or 0} 位分析師覆蓋，樣本太少，不列數字、不得引用。\n",
            f"> 卖方共识：仅 {n or 0} 位分析师覆盖，样本太少，不列数字、不得引用。\n",
            f"> Sell-side consensus: only {n or 0} analyst(s); too thin to cite.\n",
        )

    dir_labels = {
        "up": L("上修", "上修", "up"),
        "down": L("下修", "下修", "down"),
        "mixed": L("家數與幅度不一致", "家数与幅度不一致", "mixed"),
        "no_activity": L("近 30 天無修正活動（不代表穩定）", "近 30 天无修正活动（不代表稳定）", "no revision activity (not 'stable')"),
    }
    direction = dir_labels.get(consensus.get("eps_fy1_revision_direction"), "N/A")
    up30, down30 = consensus.get("eps_fy1_up_30d"), consensus.get("eps_fy1_down_30d")
    lines = [
        "",
        "### " + L(
            f"賣方共識（yfinance 彙整，n={n}，價格日期 {as_of}；僅供參考）",
            f"卖方共识（yfinance 汇总，n={n}，价格日期 {as_of}；仅供参考）",
            f"Sell-side Consensus (yfinance, n={n}, price date {as_of}; informational only)",
        ),
        L("| 項目 | 值 |", "| 项目 | 值 |", "| Item | Value |"),
        "|------|------|",
        "| " + L("次年度 EPS 修正方向（近 30 天）", "次年度 EPS 修正方向（近 30 天）", "Next-FY EPS revision (30d)")
        + f" | {direction}；"
        + L(f"上修 {up30 if up30 is not None else 'N/A'} 家、下修 {down30 if down30 is not None else 'N/A'} 家",
            f"上修 {up30 if up30 is not None else 'N/A'} 家、下修 {down30 if down30 is not None else 'N/A'} 家",
            f"up {up30 if up30 is not None else 'N/A'} / down {down30 if down30 is not None else 'N/A'}")
        + " |",
        "| " + L("次年度 EPS 共識", "次年度 EPS 共识", "Next-FY EPS consensus")
        + f" | {_fmt(consensus.get('eps_fy1'))}（30{L('天', '天', 'd')} {_fmt(consensus.get('eps_fy1_rev_30d_pct'), '%', True)}、"
        + f"90{L('天', '天', 'd')} {_fmt(consensus.get('eps_fy1_rev_90d_pct'), '%', True)}；"
        + L("高低分歧", "高低分歧", "high-low spread") + f" {_fmt(consensus.get('eps_fy1_dispersion_pct'), '%')}） |",
        "| " + L("評級", "评级", "Rating")
        + f" | {_fmt(consensus.get('rec_mean'))}（{consensus.get('rec_key') or 'N/A'}；"
        + L("近 3 個月買進佔比變化", "近 3 个月买进占比变化", "3m change in buy share")
        + f" {_fmt(consensus.get('rec_buy_share_change_3m_pct'), 'pp', True)}） |",
        "| " + L("目標價中位數（背景）", "目标价中位数（背景）", "Median target (background)")
        + f" | {_fmt(consensus.get('target_median'))}（{L('隱含', '隐含', 'implied')} "
        + f"{_fmt(consensus.get('implied_upside_pct'), '%', True)}，"
        + L("區間", "区间", "range") + f" {_fmt(consensus.get('target_low'))}~{_fmt(consensus.get('target_high'))}） |",
        "",
    ]
    if status == "stale":
        lines.append("> " + L(
            "共識價格日期過舊或與現價差距 >3%，數字可能未更新，只能參考方向。",
            "共识价格日期过旧或与现价差距 >3%，数字可能未更新，只能参考方向。",
            "Warning: consensus price is old or >3% off the live price; numbers may be stale.",
        ))
    lines.append("> " + L(
        "賣方目標價系統性偏多、極少如期達成，不要拿隱含上漲當理由；只看 EPS 修正方向與分歧，"
        "且此訊號在台股未經驗證：不得據此提高 confidence、改變 action 或放寬進場門檻，只能寫進理由作背景。",
        "卖方目标价系统性偏多、极少如期达成，不要拿隐含上涨当理由；只看 EPS 修正方向与分歧，"
        "且此信号在台股未经验证：不得据此提高 confidence、改变 action 或放宽进场门槛，只能写进理由作背景。",
        "Sell-side targets are systematically optimistic and rarely met; do not cite implied upside. "
        "Look only at EPS revision direction and dispersion. This signal is unvalidated: never raise confidence, "
        "change the action, or loosen entry rules because of it; mention it only as background in the reasoning.",
    ))
    return "\n".join(lines) + "\n"
