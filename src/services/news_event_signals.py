"""新聞檢索用的事件訊號：上次財報日與重大波動，只讀既有資料、不打外部來源。"""
import logging
from datetime import date, timedelta

from src.services.event_gap import detect_event_gap

logger = logging.getLogger(__name__)

# 超過這個天數的財報不再錨定 earnings 窗口。
EARNINGS_ANCHOR_MAX_AGE_DAYS = 30


def _parse_day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _latest_sec_earnings_day(fundamental_context, today):
    """美股：SEC 8-K Item 2.02 的申報日。行事曆只存下一次財報，查不到已發布的日期。"""
    evidence = (fundamental_context or {}).get("us_evidence") or {}
    filings = (evidence.get("sec_filings") or {}).get("recent_8k") or []
    days = []
    for entry in filings:
        items = {item.strip() for item in str(entry.get("items") or "").split(",")}
        day = _parse_day(entry.get("date"))
        if "2.02" in items and day is not None and day <= today:
            days.append(day)
    return max(days) if days else None


def _calendar_earnings_day(code, today):
    """行事曆的下一次財報／法說若就在今天，當成已發生的財報日。"""
    from src.services.calendar_service import earnings_evidence

    day = _parse_day((earnings_evidence(code) or {}).get("date"))
    return day if day == today else None


def resolve_news_event_signals(code, today, *, config, fundamental_context=None, daily_bars=None, realtime_quote=None):
    """回傳 search_comprehensive_intel 的事件參數；任一來源失敗都不影響分析。"""
    signals = {"earnings_date": None, "price_event": None}
    try:
        earliest = today - timedelta(days=EARNINGS_ANCHOR_MAX_AGE_DAYS)
        day = _latest_sec_earnings_day(fundamental_context, today) or _calendar_earnings_day(code, today)
        if day is not None and day >= earliest:
            signals["earnings_date"] = day
    except Exception as exc:
        logger.warning("財報日訊號讀取失敗 %s: %s", code, type(exc).__name__)
    try:
        context = {"event_gap_daily_bars": daily_bars or [], "today": {"date": today.isoformat()}}
        change = getattr(realtime_quote, "change_pct", None)
        if change is not None:
            context["realtime"] = {"change_pct": change}
        signals["price_event"] = detect_event_gap(code, context, config)
    except Exception as exc:
        logger.warning("重大波動訊號判讀失敗 %s: %s", code, type(exc).__name__)
    return signals
