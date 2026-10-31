"""獨立移植 Nasdaq 財報邏輯；Yahoo 只作備援，沒有日期就回空值。"""
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
    # earnings-date 是 Zacks 推估；只有日曆同日同代號的列才能升級 confirmed。
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
        return {"date": day, "status": "confirmed", "detail": "，".join(parts),
                "source_url": f"https://www.nasdaq.com/market-activity/earnings?date={day.isoformat()}"}
    return None


def yahoo_earnings(code, today):
    import yfinance as yf

    data = yf.Ticker(code.replace(".", "-")).calendar or {}
    dates = []
    for value in data.get("Earnings Date") or []:
        if isinstance(value, datetime):
            value = value.astimezone(ZoneInfo("America/New_York")).date() if value.tzinfo else value.date()
        if isinstance(value, date) and value >= today:
            dates.append(value)
    if not dates:
        return None
    eps = data.get("Earnings Average")
    detail = "Yahoo 備援推估（非公司確認日）"
    if isinstance(eps, (int, float)) and math.isfinite(eps):
        detail += f"，市場預估 EPS ${eps:g}"
    return {"date": min(dates), "status": "estimated", "detail": detail,
            "source_url": f"https://finance.yahoo.com/quote/{quote(code.replace('.', '-'))}/calendar/"}


def fetch_earnings(code, today):
    nasdaq_failed = False
    try:
        candidate = parse_earnings_date(code, nasdaq_json(
            f"analyst/{quote(code.replace('-', '.'))}/earnings-date"))
        if candidate and candidate["date"] >= today:
            try:
                confirmed = parse_earnings_calendar(code, candidate["date"], nasdaq_json(
                    f"calendar/earnings?date={candidate['date'].isoformat()}"))
                return confirmed or candidate
            except Exception as exc:
                logger.warning("財報日曆核對失敗 %s: %s", code, type(exc).__name__)
                return candidate
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
