"""獨立移植 Nasdaq 財報邏輯；Yahoo 只作備援，沒有日期就回空值。"""
import html
import logging
import math
import re
from datetime import date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)
NASDAQ_API = "https://api.nasdaq.com/api"
NASDAQ_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/",
    "User-Agent": "Mozilla/5.0",
}
MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
NEW_YORK = ZoneInfo("America/New_York")
MOPS_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"
MOPS_PAGE_URL = "https://mopsov.twse.com.tw/mops/web/t100sb02_1"
ROC_DATE = re.compile(r"(\d{2,3})/(\d{1,2})/(\d{1,2})")
TIME_LABELS = {"time-pre-market": "盤前", "time-after-hours": "盤後", "time-not-supplied": "時段未定"}


def nasdaq_json(path):
    response = requests.get(f"{NASDAQ_API}/{path}", headers=NASDAQ_HEADERS, timeout=15)
    response.raise_for_status()
    body = response.json()
    if body.get("data") is None:
        raise ValueError("Nasdaq 未提供資料")
    return body["data"]


def parse_nasdaq_date(text):
    match = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", text or "")
    if not match or match[1] not in MONTHS:
        return None
    return date(int(match[3]), MONTHS[match[1]], int(match[2]))


def parse_earnings_date(code, data):
    day = parse_nasdaq_date(data.get("announcement"))
    if day is None:
        return None
    text = re.sub(r"\s+", " ", data.get("reportText") or "")
    eps = re.search(r"consensus EPS forecast for the quarter is \$?(-?\d+(?:\.\d+)?)", text, re.I)
    # earnings-date 是 Zacks 推估；confirmed 只來自 Yahoo 的 isEarningsDateEstimate。
    return {"date": day, "status": "estimated",
            "detail": "Nasdaq / Zacks 推估" + (f"，市場預估 EPS ${eps[1]}" if eps else ""),
            "source_url": f"https://www.nasdaq.com/market-activity/stocks/{quote(code.replace('-', '.').lower())}/earnings"}


def parse_earnings_calendar(code, day, data):
    # 官方回 200 仍可能停更：asOf 必須與要求的日期一致。
    if parse_nasdaq_date(data.get("asOf")) != day:
        raise ValueError("Nasdaq 日曆回應日期不符")
    symbol = code.replace("-", ".").upper()
    for row in data.get("rows") or []:
        if (row.get("symbol") or "").upper() != symbol:
            continue
        parts = [TIME_LABELS.get(row.get("time"), "時段未定")]
        if row.get("fiscalQuarterEnding"):
            parts.append(f"財季 {row['fiscalQuarterEnding']}")
        if row.get("epsForecast"):
            parts.append(f"市場預估 EPS {row['epsForecast']}")
        # Nasdaq 官方說明日期由歷史申報日演算法推導：有列在日曆上仍只是推估。
        return {"date": day, "status": "estimated", "detail": "，".join(parts),
                "source_url": f"https://www.nasdaq.com/market-activity/earnings?date={day.isoformat()}"}
    return None


def yahoo_earnings(code, today):
    import yfinance as yf

    ticker = yf.Ticker(code.replace(".", "-"))
    info = ticker.info or {}
    # 503 時 yfinance 可能回空資料；沒有基本識別欄位就是查詢失敗，不是「沒有財報日」。
    if not info.get("symbol") and not info.get("quoteType"):
        raise ValueError("Yahoo 未回傳報價資料")
    # 不用 .calendar 的日期：它先以主機時區轉成 date，台北主機上美東盤後財報會晚一天。
    dates = []
    for key in ("earningsTimestampStart", "earningsTimestamp", "earningsTimestampEnd"):
        stamp = info.get(key)
        if isinstance(stamp, (int, float)) and math.isfinite(stamp):
            day = datetime.fromtimestamp(stamp, tz=NEW_YORK).date()
            if day >= today:
                dates.append(day)
    if not dates:
        return None
    eps = (ticker.calendar or {}).get("Earnings Average")
    confirmed = info.get("isEarningsDateEstimate") is False
    detail = "Yahoo 標示公司已確認" if confirmed else "Yahoo 備援推估（非公司確認日）"
    if isinstance(eps, (int, float)) and math.isfinite(eps):
        detail += f"，市場預估 EPS ${eps:g}"
    return {"date": min(dates), "status": "confirmed" if confirmed else "estimated", "detail": detail,
            "source_url": f"https://finance.yahoo.com/quote/{quote(code.replace('.', '-'))}/calendar/"}


def _prefer_company_confirmed(code, today, candidate):
    """Yahoo 明確標示非推估時採用它；查不到不影響 Nasdaq 的推估結果。"""
    try:
        yahoo = yahoo_earnings(code, today)
    except Exception as exc:
        logger.warning("Yahoo 確認狀態查詢失敗 %s: %s", code, type(exc).__name__)
        return candidate
    return yahoo if yahoo and yahoo["status"] == "confirmed" else candidate


def fetch_earnings(code, today):
    nasdaq_failed = False
    try:
        candidate = parse_earnings_date(code, nasdaq_json(
            f"analyst/{quote(code.replace('-', '.'))}/earnings-date"))
        if candidate and candidate["date"] >= today:
            try:
                listed = parse_earnings_calendar(code, candidate["date"], nasdaq_json(
                    f"calendar/earnings?date={candidate['date'].isoformat()}"))
                return _prefer_company_confirmed(code, today, listed or candidate)
            except Exception as exc:
                logger.warning("財報日曆核對失敗 %s: %s", code, type(exc).__name__)
                return _prefer_company_confirmed(code, today, candidate)
    except Exception as exc:
        nasdaq_failed = True
        logger.warning("Nasdaq 財報來源失敗 %s: %s", code, type(exc).__name__)
    try:
        return yahoo_earnings(code, today)
    except Exception:
        if nasdaq_failed:
            raise
        # Nasdaq 明確沒有日期、Yahoo 又限流：不可保留先前的未來日期。
        return None


def _cell_text(raw):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", raw))).strip()


def parse_mops_conferences(body, year, month):
    """解析 MOPS 法說會彙總表；無法辨識或月份不符就拋錯，呼叫端保留舊快取。"""
    if "查無資料" in body:
        return []
    if "公司代號" not in body:
        raise ValueError("MOPS 回應不是法說會彙總表")
    rows = []
    for raw_row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        cells = [_cell_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", raw_row, re.S)]
        if len(cells) < 6 or not re.fullmatch(r"\w{4,6}", cells[0]):
            continue
        days = []
        for roc_year, roc_month, roc_day in ROC_DATE.findall(cells[2]):
            days.append(date(int(roc_year) + 1911, int(roc_month), int(roc_day)))
        # MOPS 沒有回應日期欄位，用「列日期落在查詢月份」判斷有沒有停更或串錯月。
        if not any(d.year == year and d.month == month for d in days):
            raise ValueError("MOPS 法說會日期與查詢月份不符")
        rows.append({"code": cells[0], "name": cells[1], "date": days[0], "date_text": cells[2],
                     "time": cells[3], "place": cells[4], "summary": cells[5]})
    return rows


def fetch_tw_conferences(year, month, market):
    """market：sii＝上市、otc＝上櫃。"""
    response = requests.post(MOPS_URL, data={
        "encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": market,
        "year": year - 1911, "month": month, "co_id": "",
    }, headers={"User-Agent": NASDAQ_HEADERS["User-Agent"]}, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    return parse_mops_conferences(response.text, year, month)
