# -*- coding: utf-8 -*-
"""trading_calendar learns about today's typhoon closure by itself (NAS has no cron)."""

import datetime

import pytest

from market_data import closures
from src.core import trading_calendar as tc

TODAY = datetime.datetime.now(tc.ZoneInfo("Asia/Taipei")).date()


@pytest.fixture
def armed(monkeypatch, tmp_path):
    monkeypatch.setenv("TW_CLOSURE_AUTODETECT", "true")
    monkeypatch.setenv("TW_ADHOC_CLOSED_FILE", str(tmp_path / "closed.txt"))
    monkeypatch.setattr(tc, "_closure_last_check", None)
    # Weekend runs would short-circuit on the calendar; pretend the calendar is open.
    monkeypatch.setattr(closures, "_calendar_says_open", lambda day: True)
    calls = []
    monkeypatch.setattr(closures, "fetch_dgpa_closures",
                        lambda timeout=10: calls.append(timeout) or {TODAY})
    return calls


def test_closure_detected_recorded_and_throttled(armed, tmp_path):
    tc._get_calendar("XTAI")
    assert closures.adhoc_closed_dates(tmp_path / "closed.txt") == {TODAY}
    assert armed == [3]  # short timeout
    tc._get_calendar("XTAI")
    tc._get_calendar("XTAI")
    assert armed == [3]  # throttled: one fetch, not one per call


def test_other_exchanges_never_fetch(armed):
    tc._get_calendar("XNYS")
    assert armed == []


def test_fetch_failure_is_swallowed(armed, monkeypatch):
    def boom(timeout=10):
        raise RuntimeError("net down")

    monkeypatch.setattr(closures, "fetch_dgpa_closures", boom)
    tc._get_calendar("XTAI")  # must not raise


def test_disabled_by_env(armed, monkeypatch):
    monkeypatch.setenv("TW_CLOSURE_AUTODETECT", "false")
    tc._get_calendar("XTAI")
    assert armed == []


def test_open_day_rechecked_only_after_interval(armed, monkeypatch):
    monkeypatch.setattr(closures, "fetch_dgpa_closures",
                        lambda timeout=10: armed.append(timeout) or set())
    tc._get_calendar("XTAI")
    tc._get_calendar("XTAI")
    assert armed == [3]
    day, t = tc._closure_last_check
    monkeypatch.setattr(tc, "_closure_last_check", (day, t - tc._CLOSURE_CHECK_INTERVAL - 1))
    tc._get_calendar("XTAI")
    assert armed == [3, 3]
