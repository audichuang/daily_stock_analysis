"""health 的「應有場次」絕對新鮮度檢查（免 DB）。

price 與 TAIEX 都是 TWSE 來源，原本只互相比對：兩邊同時缺今天（被封、盤中跑）時
全部通過，報告照推（2026-10-16 實測 price 0 筆、index 停 10-15、health 全 0）。

所有測試都注入 `now` 與 `is_session`，不依賴環境有沒有 exchange_calendars
（本機 market_data 環境沒有、CI 有）；只有契約測試會真的讀 XTAI。
"""

import sys
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from market_data import health

_TPE = ZoneInfo("Asia/Taipei")
_HOLIDAYS = {date(2026, 10, 9)}     # 國慶日補假（10/10 週六）


def _is_session(day):
    return day.weekday() < 5 and day not in _HOLIDAYS


def _at(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=_TPE)


def _expected(now):
    return health.expected_session(now, _is_session)


# --- expected_session -------------------------------------------------------

def test_trading_day_evening_expects_today():
    assert _expected(_at(date(2026, 10, 16), 18)) == date(2026, 10, 16)


def test_trading_day_morning_expects_the_previous_session():
    assert _expected(_at(date(2026, 10, 16), 10, 36)) == date(2026, 10, 15)


def test_cutoff_is_17_not_the_13_30_close():
    """15:00 資料還沒發布完，不該要求今天；17:00 整點起才要求。"""
    day = date(2026, 10, 16)
    assert _expected(_at(day, 15)) == date(2026, 10, 15)
    assert _expected(_at(day, 16, 59)) == date(2026, 10, 15)
    assert _expected(_at(day, 17)) == day
    assert health.SESSION_COMPLETE_AFTER == time(17, 0)


def test_weekend_expects_the_last_friday():
    assert _expected(_at(date(2026, 10, 17), 12)) == date(2026, 10, 16)
    assert _expected(_at(date(2026, 10, 18), 23)) == date(2026, 10, 16)


def test_public_holiday_is_not_expected_so_it_does_not_block():
    assert _expected(_at(date(2026, 10, 9), 18, 30)) == date(2026, 10, 8)
    # 假日後的週一早上：越過週末與假日回到 10-08
    assert _expected(_at(date(2026, 10, 12), 9)) == date(2026, 10, 8)


def test_naive_now_is_taipei_and_other_zones_are_converted():
    assert _expected(datetime(2026, 10, 16, 18)) == date(2026, 10, 16)
    # 09:30 UTC = 17:30 台北
    assert _expected(datetime(2026, 10, 16, 9, 30, tzinfo=timezone.utc)) == date(2026, 10, 16)
    # 08:30 UTC = 16:30 台北，尚未到截止
    assert _expected(datetime(2026, 10, 16, 8, 30, tzinfo=timezone.utc)) == date(2026, 10, 15)


def test_missing_calendar_returns_none_not_a_weekday_guess(monkeypatch):
    """日曆取不到就跳過；退回週一~五會把 10-09 這種休市日誤判成缺資料。"""
    monkeypatch.setitem(sys.modules, "exchange_calendars", None)   # import 會丟 ImportError
    assert health._xtai_session_checker() is None
    assert health.expected_session(_at(date(2026, 10, 9), 18, 30)) is None


def test_a_calendar_that_never_says_session_returns_none():
    assert health.expected_session(_at(date(2026, 10, 16), 18), lambda day: False) is None


def test_a_calendar_that_raises_returns_none():
    def broken(day):
        raise ValueError("out of bounds")

    assert health.expected_session(_at(date(2026, 10, 16), 18), broken) is None


# --- report / run wiring ----------------------------------------------------

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    """按 substring 回罐頭列；「某日是否存在」的兩個查詢依參數 `d` 判定。"""

    def __init__(self, plan, price_days, taiex_days, calls):
        self.plan, self.calls = plan, calls
        self.price_days, self.taiex_days = price_days, taiex_days

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, params))
        if "FROM market.price WHERE date = :d" in sql:
            return _FakeResult([(1,)] if params["d"] in self.price_days else [])
        if "index_id = 'TAIEX' AND date = :d" in sql:
            return _FakeResult([(1,)] if params["d"] in self.taiex_days else [])
        for needle, rows in self.plan:
            if needle in sql:
                return _FakeResult(rows)
        return _FakeResult([])


def _engine(price_days, taiex_days):
    """price／TAIEX 各自有的日子；法人／融資／估值比 price 少最後一天（T+1，屬正常）。"""
    calls = []
    ordered = sorted(price_days)
    plan = [
        ("count(*), min(", [(1, ordered[0], ordered[-1])]),
        ("FROM market.price ORDER BY date DESC", [(d,) for d in reversed(ordered)]),
        ("index_id = 'TAIEX' AND date >= :start", [(d,) for d in taiex_days]),
        ("FROM market.institutional WHERE", [(d,) for d in ordered[:-1]]),
        ("FROM market.margin WHERE", [(d,) for d in ordered[:-1]]),
        ("FROM market.valuation WHERE", [(d,) for d in ordered[:-1]]),
    ]

    class _Engine:
        def connect(self):
            return _Conn(plan, set(price_days), set(taiex_days), calls)

    return _Engine(), calls


_DAYS = [date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)]
_NOW_EVENING = _at(date(2026, 10, 16), 18, 30)


def test_report_flags_the_session_when_both_price_and_taiex_lack_it():
    """實證案例：10-16 18:30，price 與 TAIEX 都停在 10-15，舊 health 全 0。"""
    engine, calls = _engine(_DAYS, _DAYS)

    result = health.report(engine, now=_NOW_EVENING, is_session=_is_session)

    integrity = result["integrity"]
    assert integrity["expected_session"] == {
        "date": "2026-10-16", "price": False, "taiex": False}
    assert integrity["missing_expected_session"] == ["2026-10-16"]
    assert integrity["missing_price_dates"] == [] and integrity["missing_index_dates"] == []
    assert {p["d"] for sql, p in calls if "date = :d" in sql} == {date(2026, 10, 16)}


@pytest.mark.parametrize("price_ok, taiex_ok", [(True, False), (False, True)])
def test_report_blocks_when_only_one_side_has_the_session(price_ok, taiex_ok):
    today = date(2026, 10, 16)
    engine, _ = _engine(_DAYS + ([today] if price_ok else []),
                        _DAYS + ([today] if taiex_ok else []))

    result = health.report(engine, now=_NOW_EVENING, is_session=_is_session)

    assert result["integrity"]["expected_session"]["price"] is price_ok
    assert result["integrity"]["expected_session"]["taiex"] is taiex_ok
    assert result["integrity"]["missing_expected_session"] == ["2026-10-16"]


def test_report_passes_when_both_have_the_session():
    today = date(2026, 10, 16)
    engine, _ = _engine(_DAYS + [today], _DAYS + [today])

    result = health.report(engine, now=_NOW_EVENING, is_session=_is_session)

    assert result["integrity"]["expected_session"] == {
        "date": "2026-10-16", "price": True, "taiex": True}
    assert result["integrity"]["missing_expected_session"] == []


def test_report_at_10_36_expects_yesterday_which_is_present():
    engine, _ = _engine(_DAYS, _DAYS)

    result = health.report(engine, now=_at(date(2026, 10, 16), 10, 36),
                           is_session=_is_session)

    assert result["integrity"]["expected_session"]["date"] == "2026-10-15"
    assert result["integrity"]["missing_expected_session"] == []


def test_run_strict_fails_and_names_the_missing_side(capsys):
    engine, _ = _engine(_DAYS, _DAYS)

    code = health.run(engine, strict=True, now=_NOW_EVENING, is_session=_is_session)

    out = capsys.readouterr().out
    assert code == 1
    assert "expected session: 2026-10-16 (price ✗, TAIEX ✗)" in out
    assert "latest price session: 2026-10-15" in out
    assert "重跑 daily" in out


def test_run_strict_names_only_the_side_that_is_missing(capsys):
    today = date(2026, 10, 16)
    engine, _ = _engine(_DAYS + [today], _DAYS)

    assert health.run(engine, strict=True, now=_NOW_EVENING, is_session=_is_session) == 1
    assert "(price ✓, TAIEX ✗)" in capsys.readouterr().out


def test_run_non_strict_reports_the_gap_but_exits_zero(capsys):
    engine, _ = _engine(_DAYS, _DAYS)

    assert health.run(engine, strict=False, now=_NOW_EVENING, is_session=_is_session) == 0
    assert "expected session: 2026-10-16" in capsys.readouterr().out


def test_run_strict_passes_and_always_prints_latest_price_session(capsys):
    today = date(2026, 10, 16)
    engine, _ = _engine(_DAYS + [today], _DAYS + [today])

    code = health.run(engine, strict=True, now=_NOW_EVENING, is_session=_is_session)

    out = capsys.readouterr().out
    assert code == 0
    assert "expected session: 2026-10-16 (price ✓, TAIEX ✓)" in out
    assert "latest price session: 2026-10-16" in out


def test_run_skips_and_does_not_block_when_the_calendar_is_unavailable(monkeypatch, capsys):
    monkeypatch.setattr(health, "_xtai_session_checker", lambda: None)
    engine, _ = _engine(_DAYS, _DAYS)

    code = health.run(engine, strict=True, now=_NOW_EVENING)

    out = capsys.readouterr().out
    assert code == 0
    assert "expected session check skipped (exchange_calendars unavailable)" in out
    assert "latest price session: 2026-10-15" in out


# --- 與 src.core.trading_calendar 的契約 ------------------------------------

_CONTRACT_MOMENTS = [
    (date(2026, 10, 16), 8, 30), (date(2026, 10, 16), 10, 36),
    (date(2026, 10, 16), 17, 0), (date(2026, 10, 16), 18, 30),
    (date(2026, 10, 17), 12, 0), (date(2026, 10, 18), 20, 0),
    (date(2026, 10, 9), 9, 0), (date(2026, 10, 9), 18, 30),
    (date(2026, 10, 12), 8, 0),
]


@pytest.mark.parametrize("day, hour, minute", _CONTRACT_MOMENTS)
def test_agrees_with_trading_calendar_outside_the_1330_1700_window(day, hour, minute):
    """13:30–17:00 刻意不同（交易日曆已視為收盤，health 要等資料發布），其餘必須一致。"""
    pytest.importorskip("exchange_calendars")
    from src.core.trading_calendar import get_effective_trading_date

    now = _at(day, hour, minute)

    assert health.expected_session(now) == get_effective_trading_date("tw", current_time=now)


def test_the_window_between_close_and_cutoff_is_the_intended_divergence():
    pytest.importorskip("exchange_calendars")
    from src.core.trading_calendar import get_effective_trading_date

    now = _at(date(2026, 10, 16), 15)

    assert get_effective_trading_date("tw", current_time=now) == date(2026, 10, 16)
    assert health.expected_session(now) == date(2026, 10, 15)
