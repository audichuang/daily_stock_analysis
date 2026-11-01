"""美股（含 ADR）季度財報取數：SEC companyfacts 優先、yfinance 備援，兩者交叉比對。

美股財報不落庫，這裡只把來源正規化成 `stock_financials` 共用的「期間列」：
每列的金額單位一律是「1 元財報幣別」；資本支出一律以「支出為正」表示。

SEC 的 duration fact 同一個 tag 混著單季與年初至今（YTD），現金流量甚至只有 YTD，
所以要用 end − start 的天數分類，缺單季才用 YTD 差分並標 derived。
"""
from __future__ import annotations

import logging
import math
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from data_provider.sec_edgar import SecEdgarClient
from src.config import get_config

logger = logging.getLogger(__name__)

_SEC_BUDGET_SECONDS = 25.0
_SEC_REQUEST_TIMEOUT = 12.0
CROSS_CHECK_TOLERANCE = 0.01
_CROSS_CHECK_KEYS = ("revenue", "gross", "op_income", "net_income", "eps", "ocf")

# 同一欄位在不同年代用不同 tag；依序優先，逐期合併。
_DURATION_TAGS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "gross": ("GrossProfit",),
    "cost": ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
    "op_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "ocf": ("NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
}
_EPS_TAGS = ("EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted")
_INSTANT_TAGS = {
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "equity": ("StockholdersEquity",),
    "equity_total": ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",),
    "contract": ("ContractWithCustomerLiability",),
    "contract_current": ("ContractWithCustomerLiabilityCurrent",),
    "contract_noncurrent": ("ContractWithCustomerLiabilityNoncurrent",),
}
_PERIOD_ANCHOR_TAGS = ("Assets", "NetIncomeLoss", "ProfitLoss", "NetCashProvidedByUsedInOperatingActivities")


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _reporting_form(row: dict) -> bool:
    return str(row.get("form", "")).split("/")[0] in {"10-Q", "10-K"}


def _reporting_currency(gaap: dict) -> Optional[str]:
    """財報幣別取筆數最多的貨幣單位；companyfacts 同一 tag 可能並存多種幣別，不能混算。"""
    counts: Dict[str, int] = {}
    for tag in _PERIOD_ANCHOR_TAGS:
        for unit, rows in ((gaap.get(tag) or {}).get("units") or {}).items():
            if unit.isalpha() and len(unit) == 3:
                counts[unit] = counts.get(unit, 0) + len(rows)
    return max(counts, key=counts.get) if counts else None


def _fiscal_periods(gaap: dict) -> Dict[str, dict]:
    """每份申報的期間＝該申報內最晚的 end；同一 fact 的 fy/fp 指的是申報，不是該列期間。"""
    filings: Dict[str, dict] = {}
    for tag in _PERIOD_ANCHOR_TAGS:
        for rows in ((gaap.get(tag) or {}).get("units") or {}).values():
            for row in rows:
                if not _reporting_form(row) or row.get("fp") not in {"Q1", "Q2", "Q3", "FY"} or not row.get("accn"):
                    continue
                filing = filings.setdefault(row["accn"], {"end": row["end"], "fy": row.get("fy"), "fp": row["fp"],
                                                          "filed": row.get("filed"), "form": row.get("form")})
                if row["end"] > filing["end"]:
                    filing["end"] = row["end"]
    periods: Dict[str, dict] = {}
    for filing in filings.values():
        current = periods.get(filing["end"])
        # 修正申報（10-Q/A）不能蓋掉原始公告日。
        if current is None or (filing.get("filed") or "") < (current.get("filed") or ""):
            periods[filing["end"]] = filing
    return periods


def _duration_series(gaap: dict, tags, unit: str) -> Dict[Tuple[str, str], float]:
    """(start, end) -> 值；同期多份申報取最新申報（重編後的值），tag 依優先序逐期合併。"""
    merged: Dict[Tuple[str, str], float] = {}
    for tag in tags:
        latest: Dict[Tuple[str, str], Tuple[str, float]] = {}
        for row in ((gaap.get(tag) or {}).get("units") or {}).get(unit, []):
            value = _finite(row.get("val"))
            if value is None or not row.get("start") or not _reporting_form(row):
                continue
            key = (row["start"], row["end"])
            filed = row.get("filed") or ""
            if key not in latest or filed >= latest[key][0]:
                latest[key] = (filed, value)
        for key, (_, value) in latest.items():
            merged.setdefault(key, value)
    return merged


def _instant_series(gaap: dict, tags, unit: str) -> Dict[str, float]:
    merged: Dict[str, float] = {}
    for tag in tags:
        latest: Dict[str, Tuple[str, float]] = {}
        for row in ((gaap.get(tag) or {}).get("units") or {}).get(unit, []):
            value = _finite(row.get("val"))
            if value is None or row.get("start") or not _reporting_form(row):
                continue
            filed = row.get("filed") or ""
            if row["end"] not in latest or filed >= latest[row["end"]][0]:
                latest[row["end"]] = (filed, value)
        for end, (_, value) in latest.items():
            merged.setdefault(end, value)
    return merged


def _single_quarter(series: Dict[Tuple[str, str], float], end: str, quarter: int,
                    prev_end: Optional[str]) -> Tuple[Optional[float], bool]:
    """回傳 (單季值, 是否差分而來)。第 N 季的 YTD 期長約 N×91 天，過濾掉滾動十二個月之類的列。"""
    for (start, stop), value in series.items():
        if stop == end and 75 <= _days(start, stop) <= 105:
            return value, False
    if prev_end is None:
        return None, False
    expected = quarter * 91
    for (start, stop), value in series.items():
        if stop == end and abs(_days(start, stop) - expected) <= 25:
            previous = series.get((start, prev_end))
            if previous is None:
                return None, False
            return value - previous, True
    return None, False


def parse_companyfacts(facts: dict, limit: int = 12) -> Optional[dict]:
    """companyfacts -> {currency, periods}；沒有 us-gaap 季報（如只交 20-F 的 ADR）回 None。"""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    currency = _reporting_currency(gaap)
    if not currency:
        return None
    fiscal = _fiscal_periods(gaap)
    if not any(item["fp"] != "FY" for item in fiscal.values()):
        return None
    ends = sorted(fiscal)[-limit:]
    series = {key: _duration_series(gaap, tags, currency) for key, tags in _DURATION_TAGS.items()}
    eps_series = _duration_series(gaap, _EPS_TAGS, f"{currency}/shares")
    instants = {key: _instant_series(gaap, tags, currency) for key, tags in _INSTANT_TAGS.items()}
    # 差分需要上一季的 YTD，所以 prev_end 要從完整序列找，不受 limit 影響。
    all_ends = sorted(fiscal)
    rows: List[dict] = []
    for end in ends:
        info = fiscal[end]
        quarter = {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}[info["fp"]]
        index = all_ends.index(end)
        prev_end = None
        if quarter > 1 and index > 0 and 60 <= _days(all_ends[index - 1], end) <= 120:
            prev_end = all_ends[index - 1]
        raw: Dict[str, Optional[float]] = {}
        derived: set = set()
        for key, values in series.items():
            value, was_derived = _single_quarter(values, end, quarter, prev_end)
            raw[key] = value
            if was_derived:
                derived.add(key)
        raw["eps"], eps_derived = _single_quarter(eps_series, end, quarter, prev_end)
        if eps_derived:
            derived.add("eps")
        if raw["gross"] is None and raw["revenue"] is not None and raw["cost"] is not None:
            raw["gross"] = raw["revenue"] - raw["cost"]
            derived.add("gross")
        raw.pop("cost", None)
        # 只讀該期期末的值：tag 停用多年（INTC 合約負債停在 2021）也不會拿舊值充數。
        raw["assets"] = instants["assets"].get(end)
        raw["equity"] = instants["equity"].get(end)
        raw["liabilities"] = instants["liabilities"].get(end)
        total_equity = instants["equity_total"].get(end, raw["equity"])
        if raw["liabilities"] is None and raw["assets"] is not None and total_equity is not None:
            raw["liabilities"] = raw["assets"] - total_equity
            derived.add("liabilities")
        contract = instants["contract"].get(end)
        if contract is None:
            parts = [instants["contract_current"].get(end), instants["contract_noncurrent"].get(end)]
            if parts[0] is not None:
                contract = parts[0] + (parts[1] or 0.0)
        raw["contract"] = contract
        rows.append({
            "key": f"{info['fy']}Q{quarter}", "label": f"{info['fy']} Q{quarter}",
            "fiscal_year": info["fy"], "fiscal_quarter": quarter, "period_end": end,
            "announce_date": info.get("filed"), "announce_date_kind": "filed",
            "filing_form": str(info.get("form") or ""), "raw": raw, "derived": derived,
        })
    return {"currency": currency, "periods": rows, "entity_name": facts.get("entityName")}


def _yf_value(df, labels, column) -> Optional[float]:
    if df is None or getattr(df, "empty", True):
        return None
    for label in labels:
        if label in df.index:
            value = _finite(df.loc[label].get(column))
            if value is not None:
                return value
    return None


def fetch_yfinance_periods(ticker: str, limit: int = 12) -> dict:
    """yfinance 季報 -> 期間列；幣別取 financialCurrency（TSM 是 TWD），不是交易幣別。"""
    import pandas as pd
    import yfinance as yf

    handle = yf.Ticker(ticker)
    info = handle.get_info() or {}
    result = {"quote_type": info.get("quoteType"), "currency": info.get("financialCurrency"),
              "trading_currency": info.get("currency"), "entity_name": info.get("longName") or info.get("shortName"),
              "sector": info.get("sector"), "periods": []}
    income = handle.quarterly_income_stmt
    cash = handle.quarterly_cashflow
    balance = handle.quarterly_balance_sheet
    if income is None or getattr(income, "empty", True):
        return result
    columns = sorted({*income.columns, *(cash.columns if cash is not None else [])})[-limit:]
    for column in columns:
        end = pd.Timestamp(column).date()
        capex = _yf_value(cash, ("Capital Expenditure",), column)
        raw = {
            "revenue": _yf_value(income, ("Total Revenue", "Operating Revenue"), column),
            "gross": _yf_value(income, ("Gross Profit",), column),
            "op_income": _yf_value(income, ("Operating Income",), column),
            "net_income": _yf_value(income, ("Net Income", "Net Income Common Stockholders"), column),
            "eps": _yf_value(income, ("Basic EPS",), column),
            "ocf": _yf_value(cash, ("Operating Cash Flow",), column),
            # yfinance 的資本支出是負數，統一成支出為正。
            "capex": None if capex is None else -capex,
            "assets": _yf_value(balance, ("Total Assets",), column),
            "liabilities": _yf_value(balance, ("Total Liabilities Net Minority Interest",), column),
            "equity": _yf_value(balance, ("Stockholders Equity",), column),
            "contract": None,
        }
        # INTC 實測：最新季 Yahoo 只有 EPS、營收與淨利都是 NaN；這種季不是一份完整財報。
        if raw["revenue"] is None and raw["net_income"] is None:
            continue
        quarter = (end.month - 1) // 3 + 1
        result["periods"].append({
            "key": f"{end.year}Q{quarter}", "label": f"{end.year} Q{quarter}",
            "fiscal_year": end.year, "fiscal_quarter": quarter, "period_end": end.isoformat(),
            "announce_date": None, "announce_date_kind": "unknown", "filing_form": "", "raw": raw, "derived": set(),
        })
    return result


def cross_check(primary: List[dict], secondary: List[dict], limit: int = 8) -> dict:
    """同一份財報（期末相差 ≤10 天）逐欄比對；來源差異揭露出來，不靜默挑一邊。"""
    compared = 0
    mismatches: List[dict] = []
    for row in primary[-limit:]:
        end = date.fromisoformat(row["period_end"])
        other = next((item for item in secondary
                      if abs((date.fromisoformat(item["period_end"]) - end).days) <= 10), None)
        if other is None:
            continue
        for key in _CROSS_CHECK_KEYS:
            first, second = row["raw"].get(key), other["raw"].get(key)
            if first is None or second is None:
                continue
            compared += 1
            base = max(abs(first), abs(second))
            if base and abs(first - second) / base > CROSS_CHECK_TOLERANCE:
                mismatches.append({"field": key, "period": row["key"], "primary": first, "secondary": second})
    status = "unavailable" if not compared else "mismatch" if mismatches else "matched"
    return {"source": "yfinance", "status": status, "compared": compared, "mismatches": mismatches}


def fetch_us_financials(ticker: str) -> dict:
    """回傳 {source, currency, trading_currency, periods, template, cross_check, quote_type, limitations}。

    兩個來源獨立失敗；都拿不到時 `error` 為真，由呼叫端回 unavailable（不快取太久）。
    """
    symbol = ticker.upper().removesuffix(".US")
    user_agent = (getattr(get_config(), "sec_edgar_user_agent", "") or "").strip()
    sec = sic = None
    sec_failed = False
    if user_agent:
        client = SecEdgarClient(user_agent, request_timeout=_SEC_REQUEST_TIMEOUT)
        deadline = time.monotonic() + _SEC_BUDGET_SECONDS
        try:
            cik = client._cik(symbol, deadline=deadline)
            if cik is not None:
                facts = client._json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json",
                                     deadline=deadline)
                sec = parse_companyfacts(facts)
                if sec:
                    sic = _sic_code(client, cik, deadline)
        except Exception as exc:
            sec_failed = True
            logger.warning("[us_financials] SEC companyfacts 失敗 %s: %s", symbol, type(exc).__name__)
    yahoo: Optional[dict] = None
    yahoo_failed = False
    try:
        yahoo = fetch_yfinance_periods(symbol)
    except Exception as exc:
        yahoo_failed = True
        logger.warning("[us_financials] yfinance 失敗 %s: %s", symbol, type(exc).__name__)
    limitations: List[str] = []
    if sec:
        check = cross_check(sec["periods"], (yahoo or {}).get("periods") or [])
        return {"source": "sec_companyfacts", "currency": sec["currency"],
                "trading_currency": (yahoo or {}).get("trading_currency") or sec["currency"],
                "entity_name": sec.get("entity_name"), "periods": sec["periods"], "cross_check": check,
                "financial": sic is not None and 6000 <= sic <= 6499, "quote_type": (yahoo or {}).get("quote_type"),
                "limitations": limitations, "error": False}
    if user_agent is None or not user_agent:
        limitations.append("未設定 SEC_EDGAR_USER_AGENT，改用 Yahoo Finance 的季報。")
    elif sec_failed:
        limitations.append("SEC 暫時無法讀取，改用 Yahoo Finance 的季報。")
    else:
        limitations.append("這家公司沒有向 SEC 申報 XBRL 季報（外國發行人多只交年報），季度數字來自 Yahoo Finance，未經 SEC 交叉比對。")
    yahoo = yahoo or {}
    return {"source": "yfinance", "currency": yahoo.get("currency"), "trading_currency": yahoo.get("trading_currency"),
            "entity_name": yahoo.get("entity_name"), "periods": yahoo.get("periods") or [],
            "cross_check": {"source": "sec_companyfacts", "status": "unavailable", "compared": 0, "mismatches": []},
            "financial": yahoo.get("sector") == "Financial Services", "quote_type": yahoo.get("quote_type"),
            "limitations": limitations, "error": yahoo_failed and not yahoo.get("periods")}


def _sic_code(client: SecEdgarClient, cik: str, deadline: float) -> Optional[int]:
    """金融業模板靠 SIC 判斷；讀不到就當一般公司，只是多顯示幾個不適用的欄位。"""
    try:
        data = client._json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", deadline=deadline)
        return int(data.get("sic"))
    except Exception:
        logger.debug("SEC SIC unavailable", exc_info=True)
        return None
