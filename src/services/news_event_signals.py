"""新聞檢索用的事件訊號：上次財報日與重大波動，只讀既有資料、不打外部來源。"""
import logging
import re
from datetime import date, timedelta
from types import SimpleNamespace

from src.core.quote_session import coerce_to_date, premarket_session_unknown, resolve_quote_session
from src.core.trading_calendar import (
    MarketPhase,
    get_effective_trading_date,
    infer_market_phase,
    is_market_open,
    latest_opened_session,
)
from src.services.event_gap import detect_event_gap

logger = logging.getLogger(__name__)

# 超過這個天數的財報不再錨定 earnings 窗口。
EARNINGS_ANCHOR_MAX_AGE_DAYS = 30
# 只決定要不要多查「為何變動」與抓全文，不影響決策層的 event_gap_threshold_pct。
# 台股單日漲跌幅上限 10%，共用的 12% 碰不到。7% 取自 3481 −7.5% 這個實例，沒有回測。
NEWS_EVENT_THRESHOLD_PCT_BY_MARKET = {"tw": 7.0}


_RELEASE_TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")


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


def _calendar_published_day(code, now):
    """行事曆只有已確認且標了時間（法說會）、該時間已過，才算已發布；預定或推估都不算。"""
    from src.services.calendar_service import earnings_evidence

    row = earnings_evidence(code) or {}
    if _parse_day(row.get("date")) != now.date() or row.get("status") != "confirmed":
        return None
    match = _RELEASE_TIME_RE.search(str(row.get("detail") or ""))
    if match is None or (now.hour, now.minute) < (int(match[1]), int(match[2])):
        return None
    return now.date()


def _known_quote_session(market, now, quote):
    """報價確定屬於哪一場才回傳，判定與分析上下文相同；無日期又可能落後的盤前／休市報價回 None。"""
    quote_is_today = bool(
        market and is_market_open(market, now.date()) and infer_market_phase(market, now) != MarketPhase.PREMARKET
    )
    if not quote_is_today and premarket_session_unknown(quote):
        return None
    return resolve_quote_session(
        quote,
        market_today=now.date(),
        quote_is_today=quote_is_today,
        previous_session=lambda: get_effective_trading_date(market, current_time=now),
    )


def _session_rows(market, now, daily_bars, quote):
    """事件場次以帶日期的日線為主；報價只補它確定所屬、且不晚於最近已開盤場次的那一場。"""
    cutoff = latest_opened_session(market, now) or now.date()
    rows = []
    change = getattr(quote, "change_pct", None)
    if change is not None:
        session = _known_quote_session(market, now, quote)
        if session is not None and session <= cutoff:
            # 排在日線前面：同一場有實際日線時由日線覆蓋。
            rows.append({"date": session.isoformat(), "pct_chg": change})
    for bar in daily_bars or []:
        day = coerce_to_date(bar.get("date"))
        if day is not None and day <= cutoff:
            rows.append(bar)
    return rows


def resolve_news_event_signals(
    code, market, now, *, config, fundamental_context=None, daily_bars=None, realtime_quote=None,
):
    """回傳 search_comprehensive_intel 的事件參數；now 是市場當地時間，任一來源失敗都不影響分析。"""
    today = now.date()
    signals = {"earnings_date": None, "price_event": None}
    try:
        earliest = today - timedelta(days=EARNINGS_ANCHOR_MAX_AGE_DAYS)
        day = _latest_sec_earnings_day(fundamental_context, today) or _calendar_published_day(code, now)
        if day is not None and day >= earliest:
            signals["earnings_date"] = day
    except Exception as exc:
        logger.warning("財報日訊號讀取失敗 %s: %s", code, type(exc).__name__)
    try:
        rows = _session_rows(market, now, daily_bars, realtime_quote)
        context = {"event_gap_daily_bars": rows}
        thresholds = SimpleNamespace(
            event_gap_threshold_pct=NEWS_EVENT_THRESHOLD_PCT_BY_MARKET.get(
                market, getattr(config, "event_gap_threshold_pct", 12.0)),
            event_gap_lookback_sessions=getattr(config, "event_gap_lookback_sessions", 5),
        )
        signals["price_event"] = detect_event_gap(code, context, thresholds)
    except Exception as exc:
        logger.warning("重大波動訊號判讀失敗 %s: %s", code, type(exc).__name__)
    return signals
