"""個股財報：把台股 `market.financial_statement` 與美股 SEC／yfinance 正規化成同一份契約。

欄位選擇與資料坑寫在 `docs/stock-financials.md`。幾個容易靜默算錯的地方：

- 台股 `cash_flows` 是年初至今累計，單季要差分；少一季就不算，不拿累計值充數。
- 金額一律正規化成「1 元財報幣別」，來源單位另外寫在 `source.source_unit`。
- 金融業的「母公司業主」因解析時 keep-last 實際是綜合損益，淨利不能讀那一列。
- 合約負債只讀精確兩個科目，`LIKE` 會掃進保險合約負債（富邦金 4.77 兆）。
"""
from __future__ import annotations

import logging
import math
import threading
import time
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional

from src.services.market_symbol_utils import is_tw_suffix_symbol, split_suffix_symbol

logger = logging.getLogger(__name__)

DISPLAY_PERIODS = 8
_TW_FETCH_YEARS = 4
TW_UNIT_MULTIPLIER = 1000.0  # MOPS 財報與月營收都是新台幣千元
_US_CACHE_TTL_SECONDS = 6 * 3600
_US_ERROR_TTL_SECONDS = 300
_us_cache: Dict[str, tuple] = {}
_us_locks: Dict[str, threading.Lock] = {}
_us_locks_guard = threading.Lock()

_NET_INCOME_ACCOUNTS = ("母公司業主（淨利／損）", "本期淨利（淨損）")
_NET_REVENUE_ACCOUNTS = ("淨收益", "收益合計", "收益", "收入合計")
_EPS_ACCOUNT = "基本每股盈餘合計"
_INCOME_ACCOUNTS: Dict[str, tuple] = {
    "revenue": ("營業收入合計",),
    "net_revenue": _NET_REVENUE_ACCOUNTS,
    "gross": ("營業毛利（毛損）",),
    "op_income": ("營業利益（損失）",),
    "net_income": _NET_INCOME_ACCOUNTS,
    "eps": (_EPS_ACCOUNT,),
}
_OCF_ACCOUNT = "營業活動之淨現金流入（流出）"
_CAPEX_ACCOUNTS = ("取得不動產、廠房及設備", "取得不動產及設備")
_CONTRACT_ACCOUNTS = ("合約負債－流動", "合約負債－非流動")
_EQUITY_ACCOUNTS = ("歸屬於母公司業主之權益合計", "權益總計", "權益總額")
_BALANCE_ACCOUNTS = ("資產總計", "負債總計", *_EQUITY_ACCOUNTS, *_CONTRACT_ACCOUNTS)
_FINANCIAL_MARKER_ACCOUNTS = ("利息淨收益", "淨收益", "保險服務結果", "收益合計", "保險收入")
_TW_FINANCIAL_INDUSTRY = "17"

# key、顯示名、kind（amount／ratio／per_share）、一句話定義。定義是程式固定的教學，LLM 關掉時也看得到。
_METRICS: Dict[str, dict] = {
    "revenue": {"label": "營收", "kind": "amount",
                "definition": "公司這一季賣東西、提供服務收到的總金額，還沒扣任何成本。先看它有沒有比去年同季成長。"},
    "net_revenue": {"label": "淨收益", "kind": "amount",
                    "definition": "金融業的「營收」：利息收入扣掉利息支出，再加手續費、投資損益等。不能跟一般公司的營收直接比。"},
    "gross_margin": {"label": "毛利率", "kind": "ratio",
                     "definition": "毛利 ÷ 營收。每賣 100 元、扣掉直接成本後還剩多少。它往上代表更有定價能力或成本下降。"},
    "operating_margin": {"label": "營業利益率", "kind": "ratio",
                         "definition": "營業利益 ÷ 營收。再扣掉研發、行銷、管理費用後本業還賺多少。比毛利率更接近本業真正的獲利能力。"},
    "net_income": {"label": "淨利", "kind": "amount",
                   "definition": "繳完稅、算完所有收支後，屬於股東的盈餘。可能被業外一次性項目放大或壓低，要和營業利益一起看。"},
    "eps": {"label": "每股盈餘 EPS", "kind": "per_share",
            "definition": "淨利 ÷ 流通股數，每一股這季賺多少。不同公司的 EPS 不能直接比高低，要看同一家公司的變化。"},
    "operating_cash_flow": {"label": "營業現金流", "kind": "amount",
                            "definition": "本業實際收進口袋的現金。獲利為正卻長期是負的，代表賺的多半還是應收帳款或存貨，要小心。"},
    "capex": {"label": "資本支出", "kind": "amount",
              "definition": "買廠房、設備等長期資產花的現金。大幅增加通常是在擴產，短期壓現金流，要看之後營收跟不跟得上。"},
    "free_cash_flow": {"label": "自由現金流", "kind": "amount",
                       "definition": "營業現金流 − 資本支出。公司賺進的現金扣掉維持與擴張的投資後，真正能拿去配息、還債的錢。"},
    "debt_ratio": {"label": "負債比", "kind": "ratio",
                   "definition": "總負債 ÷ 總資產。公司的資產有多少是借來的。沒有絕對標準，要跟同業和自己過去比。"},
    "contract_liabilities": {"label": "合約負債", "kind": "amount",
                             "definition": "客戶先付錢、公司還沒交貨的金額。增加常代表訂單能見度提高；它是負債，但通常是好的那種。"},
    "roe_ttm": {"label": "股東權益報酬率（近四季）", "kind": "ratio",
                "definition": "近四季淨利 ÷ 股東權益。股東放在公司的每 100 元一年賺多少，是金融業最常看的獲利指標。"},
}
_GENERAL_ORDER = ("revenue", "gross_margin", "operating_margin", "net_income", "eps", "operating_cash_flow",
                  "capex", "free_cash_flow", "debt_ratio", "contract_liabilities")
_FINANCIAL_ORDER = ("net_revenue", "revenue", "net_income", "eps", "roe_ttm")
_FINANCIAL_HIDDEN_REASON = {
    "gross_margin": "金融業沒有進貨成本，損益表沒有毛利這一項。",
    "operating_margin": "金融業損益表沒有營業利益這一項，改看淨收益與淨利。",
    "operating_cash_flow": "銀行的營業現金流主要是存放款進出，不代表本業賺進多少現金。",
    "capex": "金融業的主要資產是金融資產，資本支出不是分析重點。",
    "free_cash_flow": "營業現金流對金融業不具意義，自由現金流同樣不適用。",
    "debt_ratio": "存款、保單本來就是金融業的負債，負債比高是本業特性，不能和一般公司比。",
    "contract_liabilities": "金融業的保險合約負債是準備金性質，和一般公司的預收貨款不同，不顯示以免高估。",
}
_MISSING_REASON = {
    "contract_liabilities": "這家公司沒有單獨揭露合約負債（可能併在其他負債），不拿別的科目代替。",
}


def is_supported_market(code: str) -> Optional[str]:
    from data_provider.us_index_mapping import is_us_stock_code

    if is_tw_suffix_symbol(code):
        return "tw"
    if is_us_stock_code(code.upper().removesuffix(".US")):
        return "us"
    return None


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _base_payload(code: str, market: Optional[str]) -> dict:
    return {
        "stock_code": code, "market": market, "status": "no_data", "status_reason": None,
        "stock_name": None, "template": "general", "currency": None, "trading_currency": None,
        "source": None, "cross_check": None, "periods": [], "metrics": [], "not_applicable": [],
        "monthly_revenue": [], "ttm_revenue_yoy_pct": None, "limitations": [], "is_stale": False,
    }


# ---------- 台股 ----------

def _tw_period(statement_date: date) -> Optional[dict]:
    """`date` 欄是公告截止日（afterIFRS），3/31 是前一年的 Q4。"""
    from market_data.financial_statement import afterIFRS

    for quarter in (1, 2, 3, 4):
        anchor = afterIFRS(2001, quarter)
        if (anchor.month, anchor.day) == (statement_date.month, statement_date.day):
            year = statement_date.year - 1 if quarter == 4 else statement_date.year
            end_month = quarter * 3
            end_day = {3: 31, 6: 30, 9: 30, 12: 31}[end_month]
            return {"year": year, "quarter": quarter, "end": date(year, end_month, end_day)}
    return None


def _tw_deadline(year: int, quarter: int, financial: bool) -> date:
    """法定公告期限：金融業 Q1／Q3 與半年報晚約半個月（見 afterIFRS docstring）。"""
    if quarter == 4:
        return date(year + 1, 3, 31)
    if financial:
        return {1: date(year, 5, 30), 2: date(year, 8, 31), 3: date(year, 11, 29)}[quarter]
    return {1: date(year, 5, 15), 2: date(year, 8, 14), 3: date(year, 11, 14)}[quarter]


def _pick(accounts: Dict[str, float], names: Iterable[str], prefix: str = "") -> Optional[float]:
    for name in names:
        value = accounts.get(prefix + name)
        if value is not None:
            return value
    return None


def tw_periods_from_rows(rows: Iterable[tuple], *, financial: bool) -> List[dict]:
    """(date, statement_type, account, value) 長表 -> 單季期間列，金額換算成 1 元。

    損益：單季欄優先，沒有才用累計差分。現金流量表只有累計，一律差分；前一季缺就留空。
    """
    by_period: Dict[tuple, Dict[str, Dict[str, float]]] = {}
    for statement_date, statement_type, account, value in rows:
        info = _tw_period(statement_date)
        number = _finite(value)
        if info is None or number is None:
            continue
        slot = by_period.setdefault((info["year"], info["quarter"]), {"info": info, "sheets": {}})
        slot["sheets"].setdefault(statement_type, {})[account] = number
    periods: List[dict] = []
    for (year, quarter), slot in sorted(by_period.items()):
        sheets = slot["sheets"]
        income = sheets.get("income_sheet", {})
        cumulate = sheets.get("income_sheet_cumulate", {})
        cash = sheets.get("cash_flows", {})
        balance = sheets.get("balance_sheet", {})
        previous = by_period.get((year, quarter - 1), {}).get("sheets", {}) if quarter > 1 else {}
        raw: Dict[str, Optional[float]] = {}
        derived: set = set()
        for key, names in _INCOME_ACCOUNTS.items():
            multiplier = 1.0 if key == "eps" else TW_UNIT_MULTIPLIER
            single = _pick(income, names)
            total = _pick(cumulate, names, "累計")
            if single is None and total is not None:
                if quarter == 1:
                    single = total
                else:
                    before = _pick(previous.get("income_sheet_cumulate", {}), names, "累計")
                    if before is not None:
                        single = total - before
                        derived.add(key)
            raw[key] = None if single is None else single * multiplier
        for key, names, sign in (("ocf", (_OCF_ACCOUNT,), 1.0), ("capex", _CAPEX_ACCOUNTS, -1.0)):
            year_to_date = _pick(cash, names)
            quarter_value = None
            if year_to_date is not None:
                if quarter == 1:
                    quarter_value = year_to_date
                else:
                    before = _pick(previous.get("cash_flows", {}), names)
                    if before is not None:
                        quarter_value = year_to_date - before
                        derived.add(key)
            # 現金流量表的投資支出是負數，統一成支出為正。
            raw[key] = None if quarter_value is None else quarter_value * sign * TW_UNIT_MULTIPLIER
        assets, liabilities = balance.get("資產總計"), balance.get("負債總計")
        equity = _pick(balance, _EQUITY_ACCOUNTS)
        raw["assets"] = None if assets is None else assets * TW_UNIT_MULTIPLIER
        raw["liabilities"] = None if liabilities is None else liabilities * TW_UNIT_MULTIPLIER
        raw["equity"] = None if equity is None else equity * TW_UNIT_MULTIPLIER
        contract_parts = [balance[name] for name in _CONTRACT_ACCOUNTS if name in balance]
        raw["contract"] = sum(contract_parts) * TW_UNIT_MULTIPLIER if contract_parts else None
        net_includes_minority = raw["net_income"] is not None and _pick(income, _NET_INCOME_ACCOUNTS[:1]) is None \
            and _pick(cumulate, _NET_INCOME_ACCOUNTS[:1], "累計") is None
        periods.append({
            "net_includes_minority": net_includes_minority,
            "key": f"{year}Q{quarter}", "label": f"{year} Q{quarter}", "fiscal_year": year,
            "fiscal_quarter": quarter, "period_end": slot["info"]["end"].isoformat(),
            "announce_date": _tw_deadline(year, quarter, financial).isoformat(),
            "announce_date_kind": "statutory_deadline", "filing_form": "", "raw": raw, "derived": derived,
        })
    return periods


def _tw_is_financial(rows: List[tuple], industry: Optional[str]) -> bool:
    if industry == _TW_FINANCIAL_INDUSTRY:
        return True
    return any(row[2] in _FINANCIAL_MARKER_ACCOUNTS or row[2] in {"累計" + name for name in _FINANCIAL_MARKER_ACCOUNTS}
               for row in rows)


def _tw_payload(code: str, today: date) -> dict:
    from sqlalchemy import text

    from market_data.db import get_engine
    from src.services.tw_stock_dossier import fundamentals

    payload = _base_payload(code, "tw")
    sid = (split_suffix_symbol(code) or (code,))[0]
    payload.update(currency="TWD", trading_currency="TWD")
    payload["source"] = {"id": "market.financial_statement", "label": "公開資訊觀測站財報（本地資料庫）",
                         "source_unit": "新台幣千元", "url": "https://mops.twse.com.tw/"}
    wanted = {*(_NET_REVENUE_ACCOUNTS), *_FINANCIAL_MARKER_ACCOUNTS, *_NET_INCOME_ACCOUNTS, _EPS_ACCOUNT,
              "營業收入合計", "營業毛利（毛損）", "營業利益（損失）"}
    accounts = sorted({*wanted, *("累計" + name for name in wanted), _OCF_ACCOUNT, *_CAPEX_ACCOUNTS, *_BALANCE_ACCOUNTS})
    engine = get_engine()
    with engine.connect() as conn:
        # 這條路徑只讀；API 不能被慢查詢拖住。
        conn.execute(text("SET LOCAL statement_timeout = 8000"))
        rows = [tuple(row) for row in conn.execute(text(
            "SELECT date, statement_type, account, value FROM market.financial_statement "
            "WHERE stock_id = :sid AND date >= :since AND date <= :today AND account = ANY(:accounts)"),
            {"sid": sid, "since": today - timedelta(days=366 * _TW_FETCH_YEARS), "today": today,
             "accounts": accounts}).fetchall()]
        info = conn.execute(text("SELECT name, industry FROM market.stock_info WHERE stock_id = :sid"),
                            {"sid": sid}).first()
    if info:
        payload["stock_name"] = info[0]
    if not rows:
        # 代號 00 開頭是 ETF／ETN：基金沒有公司財報，不是資料缺。
        if sid.startswith("00") or sid.startswith("02"):
            payload["status"] = "not_applicable"
            payload["status_reason"] = "ETF 是基金，沒有公司財報；要看的是追蹤標的、費用率與折溢價。"
        else:
            payload["status_reason"] = "資料庫查無這檔的財報。可能是新上市或尚未回補。"
        return payload
    financial = _tw_is_financial(rows, info[1] if info else None)
    periods = tw_periods_from_rows(rows, financial=financial)
    revenue = fundamentals(engine, sid, today)
    months = revenue.get("monthly_revenue") or []
    monthly: List[dict] = []
    for index, month in enumerate(months):
        previous = months[index - 1].get("revenue_k") if index else None
        current = month.get("revenue_k")
        mom = round((current / previous - 1) * 100, 1) if current is not None and previous else None
        monthly.append({"month": month["month"], "revenue": None if current is None else current * TW_UNIT_MULTIPLIER,
                        "yoy_pct": month.get("yoy_pct"), "mom_pct": mom, "announce_date": month.get("announced")})
    payload["monthly_revenue"] = monthly
    payload["ttm_revenue_yoy_pct"] = revenue.get("ttm_revenue_yoy_pct")
    _assemble(payload, periods, financial=financial)
    latest = periods[-1] if periods else None
    if latest:
        # 財報季更要手動跑 `market_data.cli financials`；過了下一季期限兩週還沒有新列就講明。
        year, quarter = latest["fiscal_year"], latest["fiscal_quarter"]
        next_year, next_quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
        if today > _tw_deadline(next_year, next_quarter, financial) + timedelta(days=14):
            payload["is_stale"] = True
            payload["limitations"].append(
                f"最新一季是 {latest['label']}，下一季法定期限已過兩週仍未入庫，數字可能落後。")
    if monthly:
        month_year, month_number = map(int, monthly[-1]["month"].split("-"))
        due_year, due_month = (month_year + 1, 1) if month_number == 12 else (month_year, month_number + 1)
        if today > date(due_year, due_month, 10) + timedelta(days=35):
            payload["is_stale"] = True
            payload["limitations"].append(f"月營收最新只到 {monthly[-1]['month']}，可能停更。")
    payload["limitations"].append("台股的公告日是法定期限；實際公告可能更早，資料庫未保存實際日期。")
    return payload


# ---------- 美股 ----------

def _us_payload(code: str) -> dict:
    from src.services.us_financials import fetch_us_financials

    payload = _base_payload(code, "us")
    data = fetch_us_financials(code)
    if data.get("error"):
        payload["status"] = "unavailable"
        payload["status_reason"] = "SEC 與 Yahoo Finance 暫時都讀不到，請稍後再試。"
        return payload
    payload["stock_name"] = data.get("entity_name")
    if data.get("quote_type") in {"ETF", "MUTUALFUND"}:
        payload["status"] = "not_applicable"
        payload["status_reason"] = "ETF／基金沒有公司財報；要看的是追蹤標的、費用率與折溢價。"
        return payload
    payload["limitations"].extend(data.get("limitations") or [])
    payload["currency"] = data.get("currency")
    payload["trading_currency"] = data.get("trading_currency")
    payload["cross_check"] = data.get("cross_check")
    is_sec = data.get("source") == "sec_companyfacts"
    payload["source"] = {
        "id": data.get("source"),
        "label": "SEC EDGAR companyfacts（10-Q／10-K）" if is_sec else "Yahoo Finance 季報",
        "source_unit": f"1 {data.get('currency') or ''}".strip(),
        "url": "https://www.sec.gov/edgar/searchedgar/companysearch" if is_sec else "https://finance.yahoo.com/",
    }
    periods = data.get("periods") or []
    if not periods or not payload["currency"]:
        payload["status_reason"] = "SEC 與 Yahoo Finance 都沒有這檔的季報。"
        return payload
    _assemble(payload, periods, financial=bool(data.get("financial")))
    if not is_sec:
        payload["limitations"].append("Yahoo Finance 的期末日是四捨五入到月底的近似值，也沒有公告日。")
    if payload["trading_currency"] and payload["trading_currency"] != payload["currency"]:
        payload["limitations"].append(
            f"財報幣別是 {payload['currency']}，股價以 {payload['trading_currency']} 交易，兩者不能直接相除。"
            "EPS 是 Yahoo 的口徑、通常是每 ADR（TSM 實測 1 ADR＝5 股普通股），不要和原股 EPS 比。")
        for metric in payload["metrics"]:
            if metric["key"] == "eps":
                metric["unit"] = f"{payload['currency']}/ADR"
    if is_sec and any(row["fiscal_quarter"] * 3 % 12 != date.fromisoformat(row["period_end"]).month % 12
                      for row in periods[-1:]):
        payload["limitations"].append("這家公司用自己的會計年度，Q3 不一定是日曆第三季；以期末日為準。")
    last_end = date.fromisoformat(periods[-1]["period_end"])
    if date.today() - last_end > timedelta(days=150):
        payload["is_stale"] = True
        payload["limitations"].append(f"最新一季期末是 {periods[-1]['period_end']}，下一季財報已該出來，數字可能落後。")
    check = payload["cross_check"] or {}
    if check.get("mismatches"):
        fields = list(dict.fromkeys(_FIELD_LABEL.get(item["field"], item["field"]) for item in check["mismatches"]))
        payload["limitations"].append(
            f"{'、'.join(fields)}有 {len(check['mismatches'])} 筆 SEC 與 Yahoo 差異超過 1%，這裡以 SEC 申報為準。")
    return payload


_FIELD_LABEL = {"revenue": "營收", "gross": "毛利", "op_income": "營業利益", "net_income": "淨利",
                "eps": "EPS", "ocf": "營業現金流"}


def _us_payload_cached(code: str) -> dict:
    with _us_locks_guard:
        lock = _us_locks.setdefault(code, threading.Lock())
    with lock:
        hit = _us_cache.get(code)
        if hit and time.monotonic() < hit[0]:
            return hit[1]
        payload = _us_payload(code)
        ttl = _US_ERROR_TTL_SECONDS if payload["status"] == "unavailable" else _US_CACHE_TTL_SECONDS
        _us_cache[code] = (time.monotonic() + ttl, payload)
        return payload


# ---------- 欄位組裝 ----------

def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def _metric_value(key: str, rows: List[dict], index: int) -> tuple:
    """回傳 (值, 是否差分)。比率的 derived 跟著分子走，因為那才是近似的來源。"""
    row = rows[index]
    raw, derived = row["raw"], row["derived"]
    revenue = raw.get("revenue")
    if key == "revenue":
        return raw.get("revenue"), "revenue" in derived
    if key == "net_revenue":
        return raw.get("net_revenue"), "net_revenue" in derived
    if key == "gross_margin":
        return _ratio(raw.get("gross"), revenue), "gross" in derived
    if key == "operating_margin":
        return _ratio(raw.get("op_income"), revenue), "op_income" in derived
    if key == "net_income":
        return raw.get("net_income"), "net_income" in derived
    if key == "eps":
        return raw.get("eps"), "eps" in derived
    if key == "operating_cash_flow":
        return raw.get("ocf"), "ocf" in derived
    if key == "capex":
        return raw.get("capex"), "capex" in derived
    if key == "free_cash_flow":
        ocf, capex = raw.get("ocf"), raw.get("capex")
        return (None if ocf is None or capex is None else ocf - capex), "ocf" in derived or "capex" in derived
    if key == "debt_ratio":
        return _ratio(raw.get("liabilities"), raw.get("assets")), "liabilities" in derived
    if key == "contract_liabilities":
        return raw.get("contract"), False
    if key == "roe_ttm":
        if index < 3:
            return None, False
        window = [rows[i]["raw"].get("net_income") for i in range(index - 3, index + 1)]
        if any(value is None for value in window):
            return None, False
        return _ratio(sum(window), raw.get("equity")), False
    raise KeyError(key)


def _change(current: Optional[float], base: Optional[float], kind: str) -> Optional[float]:
    """比率回傳百分點差；金額回傳成長率，基期 ≤0 時成長率沒有意義所以留空。"""
    if current is None or base is None:
        return None
    if kind == "ratio":
        return round(current - base, 2)
    if base <= 0:
        return None
    return round((current / base - 1) * 100, 2)


def _prior_index(rows: List[dict], index: int, min_days: int, max_days: int) -> Optional[int]:
    """用期末日找基期，不靠期間標籤：SEC 的 fy 偶有誤標，日曆距離不會。"""
    end = date.fromisoformat(rows[index]["period_end"])
    for candidate in range(index - 1, -1, -1):
        gap = (end - date.fromisoformat(rows[candidate]["period_end"])).days
        if min_days <= gap <= max_days:
            return candidate
        if gap > max_days:
            return None
    return None


def _assemble(payload: dict, rows: List[dict], *, financial: bool) -> None:
    rows = sorted(rows, key=lambda row: row["period_end"])
    # 兩列撞同一 key（會計年度誤標）時留較新的那列，否則用戶端會對不到值。
    seen: Dict[str, dict] = {}
    for row in rows:
        seen[row["key"]] = row
    rows = sorted(seen.values(), key=lambda row: row["period_end"])
    payload["template"] = "financial" if financial else "general"
    display_rows = rows[-DISPLAY_PERIODS:]
    start = len(rows) - len(display_rows)
    payload["periods"] = [{k: row.get(k) for k in ("key", "label", "fiscal_year", "fiscal_quarter", "period_end",
                                                    "announce_date", "announce_date_kind", "filing_form")}
                          for row in display_rows]
    order = _FINANCIAL_ORDER if financial else _GENERAL_ORDER
    metrics: List[dict] = []
    not_applicable: List[dict] = []
    if financial:
        not_applicable.extend({"key": key, "label": _METRICS[key]["label"], "reason": reason}
                              for key, reason in _FINANCIAL_HIDDEN_REASON.items())
    for key in order:
        spec = _METRICS[key]
        points: List[dict] = []
        for index in range(start, len(rows)):
            value, was_derived = _metric_value(key, rows, index)
            year_index = _prior_index(rows, index, 340, 395)
            quarter_index = _prior_index(rows, index, 70, 110)
            year_value = None if year_index is None else _metric_value(key, rows, year_index)[0]
            quarter_value = None if quarter_index is None else _metric_value(key, rows, quarter_index)[0]
            is_ratio = spec["kind"] == "ratio"
            yoy = _change(value, year_value, spec["kind"])
            qoq = _change(value, quarter_value, spec["kind"])
            points.append({
                "period": rows[index]["key"], "value": None if value is None else round(value, 4),
                "yoy_pct": None if is_ratio else yoy, "qoq_pct": None if is_ratio else qoq,
                "yoy_pp": yoy if is_ratio else None, "qoq_pp": qoq if is_ratio else None,
                "derived": bool(was_derived and value is not None),
            })
        if not any(point["value"] is not None for point in points):
            if key in _MISSING_REASON and not financial:
                not_applicable.append({"key": key, "label": spec["label"], "reason": _MISSING_REASON[key]})
            continue
        metrics.append({"key": key, "label": spec["label"], "kind": spec["kind"],
                        "unit": _metric_unit(spec["kind"], payload.get("currency")),
                        "definition": spec["definition"], "points": points})
    payload["metrics"] = metrics
    payload["not_applicable"] = not_applicable
    payload["status"] = "ok" if metrics else "no_data"
    if not metrics:
        payload["status_reason"] = "查得到申報，但沒有可用的季度欄位。"
    if any(row.get("net_includes_minority") for row in display_rows):
        payload["limitations"].append("這裡的淨利含非控制權益（本期淨利）；每股盈餘已扣特別股與非控制權益，兩者無法直接相除。")
    if any(point["derived"] for metric in metrics for point in metric["points"]
           if metric["key"] == "eps"):
        payload["limitations"].append("標「推算」的單季 EPS 是累計 EPS 相減，股數變動時與公司公布值略有差距。")


def _metric_unit(kind: str, currency: Optional[str]) -> str:
    if kind == "ratio":
        return "%"
    if kind == "per_share":
        return f"{currency or ''}/股".strip("/")
    return currency or ""


# ---------- 對外 ----------

def build_financials(code: str, *, today: Optional[date] = None) -> dict:
    """核心入口：永遠回一份帶 status 的 payload；來源失敗回 unavailable，不丟例外到端點。"""
    code = code.strip().upper()
    market = is_supported_market(code)
    if market is None:
        payload = _base_payload(code, None)
        payload["status"] = "unsupported"
        payload["status_reason"] = "目前只支援台股（.TW／.TWO）與美股。"
        return payload
    try:
        if market == "tw":
            return _tw_payload(code, today or date.today())
        return _us_payload_cached(code)
    except Exception as exc:
        logger.warning("[stock_financials] %s 取數失敗: %s", code, exc, exc_info=True)
        payload = _base_payload(code, market)
        payload["status"] = "unavailable"
        payload["status_reason"] = "財報資料暫時無法讀取，請稍後再試。"
        return payload
