"""After close, a quote from the latest closed session must not be flagged stale."""
from datetime import datetime, timezone, timedelta

import pytest

from data_provider.base import DataFetcherManager
from data_provider.realtime_types import UnifiedRealtimeQuote

TW = timezone(timedelta(hours=8))


def _enrich(monkeypatch, code, provider_local, now_local):
    mgr = DataFetcherManager(fetchers=[])
    monkeypatch.setattr(
        DataFetcherManager, "_utc_now_iso",
        staticmethod(lambda: now_local.astimezone(timezone.utc).isoformat()),
    )
    q = UnifiedRealtimeQuote(code=code, provider_timestamp=provider_local.isoformat())
    return mgr._enrich_realtime_quote(q, realtime_cache_ttl=600)


def test_postmarket_quote_from_todays_session_is_fresh(monkeypatch):
    # Fri 2026-10-23 18:00, last tick 13:30
    q = _enrich(monkeypatch, "2330.TW", datetime(2026, 10, 23, 13, 30, tzinfo=TW),
                datetime(2026, 10, 23, 18, 0, tzinfo=TW))
    assert q.is_stale is False


def test_weekend_quote_from_friday_is_fresh(monkeypatch):
    q = _enrich(monkeypatch, "2330.TW", datetime(2026, 10, 23, 13, 30, tzinfo=TW),
                datetime(2026, 10, 25, 10, 0, tzinfo=TW))
    assert q.is_stale is False


def test_quote_older_than_last_closed_session_is_stale(monkeypatch):
    # Fri 18:00 but quote is from Thursday: the closed session is Friday's
    q = _enrich(monkeypatch, "2330.TW", datetime(2026, 10, 22, 13, 30, tzinfo=TW),
                datetime(2026, 10, 23, 18, 0, tzinfo=TW))
    assert q.is_stale is True


def test_intraday_old_quote_still_stale(monkeypatch):
    # Fri 11:00 intraday, quote from 09:30 (> ttl): intraday logic unchanged
    q = _enrich(monkeypatch, "2330.TW", datetime(2026, 10, 23, 9, 30, tzinfo=TW),
                datetime(2026, 10, 23, 11, 0, tzinfo=TW))
    assert q.is_stale is True


def test_unknown_market_keeps_old_behavior(monkeypatch):
    q = _enrich(monkeypatch, "???", datetime(2026, 10, 23, 13, 30, tzinfo=TW),
                datetime(2026, 10, 23, 18, 0, tzinfo=TW))
    assert q.is_stale is True
