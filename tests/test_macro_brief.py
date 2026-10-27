# -*- coding: utf-8 -*-
"""scripts/macro_brief.py 的純函式（不碰 DB、不連外）。

釘兩件會靜默算錯的事：殖利率的變化要用 bp（拿百分比算 4.5→4.6 會印成 +2.2%，看起來像大事），
以及利率路徑不能把沒有報價的合約當 0 機率默默加總。
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from macro_brief import latest_rate_slot, prior_rate_slot, print_rates, rate_path, series_stats  # noqa: E402


def _points(values):
    start = date(2099, 1, 1)
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def test_yield_changes_are_in_basis_points():
    st = series_stats(_points([4.0] * 63 + [4.5, 4.6]), "yield")
    assert st["changes"]["1週"] == pytest.approx(60.0)   # 4.6 − 4.0 = 60bp
    assert st["from_high"] == pytest.approx(0.0)


def test_index_changes_are_percent_and_short_history_is_none():
    st = series_stats(_points([100.0] * 10 + [110.0]), "index")
    assert st["changes"]["1週"] == pytest.approx(0.10)
    assert st["changes"]["3月"] is None
    assert st["ma60"] is None and st["ma200"] is None
    assert series_stats([], "index") is None


def test_moving_average_flags():
    st = series_stats(_points([100.0] * 199 + [90.0]), "index")
    assert st["ma60"] is False and st["ma200"] is False
    assert st["from_high"] == pytest.approx(-0.10)


def test_rate_path_groups_sides_and_reports_missing_quotes():
    m1, m2 = date(2099, 1, 28), date(2099, 3, 18)
    path = rate_path([
        (m2, "hike_25", 0.6), (m1, "hold", 0.9), (m1, "hike_25", 0.07), (m1, "hike_gt25", 0.01),
        (m1, "cut_25", None), (m2, "hold", 0.3), (m2, "mystery", 0.5)])
    assert [p["meeting"] for p in path] == [m1, m2]
    assert path[0]["hike"] == pytest.approx(0.08)
    assert path[0]["hold"] == pytest.approx(0.9)
    assert path[0]["cut"] == 0 and path[0]["missing"] == ["cut_25"]
    assert path[1]["hike"] == pytest.approx(0.6) and path[1]["missing"] == []


# ---------- 隔夜已公布／今日待公布 ----------

from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from macro_brief import format_published, format_upcoming, split_events  # noqa: E402

TPE = ZoneInfo("Asia/Taipei")
NY = ZoneInfo("America/New_York")
CUTOFF = datetime(2099, 1, 2, 13, 30, tzinfo=TPE)    # 前一場次（週五）13:30 台北
NOW = datetime(2099, 1, 5, 7, 30, tzinfo=TPE)        # 週一 07:30 台北
UNTIL = datetime(2099, 1, 5, 13, 30, tzinfo=TPE)


def _ev(name, at, **kw):
    base = dict(title=name, released_at=at, actual_value=None, prior_value=None, observation_date=None,
                actual_vintage=None, status="confirmed", source="fred", series_id="FRED:X", time_note=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _names(rows):
    return [r.title for r in rows]


def test_split_events_boundaries_cutoff_excluded_now_included():
    rows = [_ev("at_cutoff", CUTOFF), _ev("just_after_cutoff", CUTOFF.replace(minute=31)),
            _ev("at_now", NOW), _ev("just_after_now", NOW.replace(minute=31)),
            _ev("at_until", UNTIL), _ev("after_until", UNTIL.replace(minute=31)),
            _ev("legacy_no_time", None)]
    published, upcoming = split_events(rows, NOW, CUTOFF, UNTIL)
    assert _names(published) == ["just_after_cutoff", "at_now"]
    assert _names(upcoming) == ["just_after_now", "at_until"]


def test_monday_morning_sees_fridays_nfp_but_not_thursdays_claims():
    nfp = datetime(2099, 1, 2, 8, 30, tzinfo=NY)          # 週五 08:30 美東 ＝ 週五 21:30 台北
    claims = datetime(2099, 1, 1, 8, 30, tzinfo=NY)       # 週四，早於前一場次收盤
    cpi_tonight = datetime(2099, 1, 5, 8, 30, tzinfo=NY)  # 週一美東 08:30 ＝ 台北 21:30，場次之後
    published, upcoming = split_events([_ev("nfp", nfp), _ev("claims", claims), _ev("cpi", cpi_tonight)],
                                       NOW, CUTOFF, UNTIL)
    assert _names(published) == ["nfp"]
    assert _names(upcoming) == [], "手填的 UNTIL 是今天 13:30：今晚的數據在它之後（實際窗口見 print_release_columns 的測試）"


def test_format_published_shows_first_release_prior_vintage_and_no_consensus():
    r = _ev("美國非農就業(NFP)", datetime(2099, 1, 2, 8, 30, tzinfo=NY), actual_value=159350, prior_value=159200.5,
            observation_date=date(2098, 12, 1), actual_vintage=date(2099, 1, 2))
    line = format_published(r)
    assert "159,350" in line and "159,200.5" in line and "vintage 2099-01-02" in line and "無共識" in line
    assert "01-02 21:30台北" in line and "01-02 08:30美東" in line
    pending = format_published(_ev("x", datetime(2099, 1, 2, 8, 30, tzinfo=NY)))
    assert "尚未入庫" in pending and "無共識" in pending


def test_event_lines_never_say_above_or_below_expectation():
    r = _ev("美國 CPI", datetime(2099, 1, 2, 8, 30, tzinfo=NY), actual_value=330.1, prior_value=329.9,
            observation_date=date(2098, 12, 1), actual_vintage=date(2099, 1, 2))
    text_ = "\n".join([format_published(r), format_published(_ev("y", NOW)), format_upcoming(r)])
    for banned in ("預期", "高於", "低於", "beat", "miss"):
        assert banned not in text_


def test_print_series_skips_weekly_series_in_the_daily_table():
    """週頻序列的 1週／1月／3月是列數 5／21／63（＝5 週／5 個月／1 年）；不能混進日線表。"""
    from macro_brief import print_series

    class _Conn:
        def execute(self, *a, **k):
            start = date(2099, 1, 1)
            rows = [("FRED:ICSA", start + timedelta(days=i), 200000.0 + i) for i in range(70)]
            rows += [("^GSPC", start + timedelta(days=i), 5000.0 + i) for i in range(70)]
            return SimpleNamespace(all=lambda: rows)

    lines = []
    print_series(_Conn(), date(2099, 3, 12), out=lines.append)
    text_ = "\n".join(lines)
    assert "標普500" in text_ and "初領失業金" not in text_
    assert "FRED:ICSA" not in text_, "週頻序列有資料就不該被列進『DB 沒有這些序列』"


# ---------- print_release_columns 的實際窗口（接 health 場次）與央行／ISM 列 ----------

import macro_brief  # noqa: E402
from market_data import health  # noqa: E402


class _FakeConn:
    """依 SQL 參數 a < released_at <= b 過濾列，模擬 print_release_columns 的查詢。"""

    def __init__(self, rows):
        self.rows = rows
        self.params = None

    def execute(self, _sql, params):
        self.params = params
        hit = [r for r in self.rows if params["a"] < r.released_at <= params["b"]]
        return SimpleNamespace(all=lambda: sorted(hit, key=lambda r: r.released_at))


def _weekday(d):
    return d.weekday() < 5


def _columns(monkeypatch, rows, now):
    monkeypatch.setattr(health, "session_before", lambda day, is_session=None: health._walk_sessions(
        day, -1, 1, 10, _weekday))
    monkeypatch.setattr(health, "sessions_after", lambda day, n, is_session=None: health._walk_sessions(
        day, 1, n, 10, _weekday))
    lines = []
    macro_brief.print_release_columns(_FakeConn(rows), now, out=lines.append)
    return "\n".join(lines)


def test_weekday_morning_lists_tonights_us_data_and_cbc_as_upcoming(monkeypatch):
    # 2099-01-06 週二 07:30 台北：今晚 21:30 的 CPI、22:00 台北的 ISM、16:00 的央行都該在「今日待公布」
    now = datetime(2099, 1, 6, 7, 30, tzinfo=TPE)
    rows = [_ev("美國 CPI", datetime(2099, 1, 6, 21, 30, tzinfo=TPE)),
            _ev("ISM", datetime(2099, 1, 6, 22, 0, tzinfo=TPE), status="estimated", source="rule"),
            _ev("央行理監事會", datetime(2099, 1, 6, 16, 0, tzinfo=TPE), source="cbc"),
            _ev("明晚數據", datetime(2099, 1, 7, 21, 30, tzinfo=TPE))]
    text_ = _columns(monkeypatch, rows, now)
    upcoming = text_.split("今日待公布", 1)[1]
    assert "美國 CPI" in upcoming and "ISM" in upcoming and "央行理監事會" in upcoming
    assert "明晚數據" not in upcoming
    assert "2099-01-07 13:30" in upcoming


def test_monday_morning_window_sees_fridays_nfp_and_tonights_cpi(monkeypatch):
    rows = [_ev("週五NFP", datetime(2099, 1, 2, 21, 30, tzinfo=TPE)),
            _ev("週五早盤前", datetime(2099, 1, 2, 9, 0, tzinfo=TPE)),
            _ev("今晚CPI", datetime(2099, 1, 5, 21, 30, tzinfo=TPE))]
    text_ = _columns(monkeypatch, rows, NOW)
    published, upcoming = text_.split("今日待公布", 1)
    assert "週五NFP" in published and "週五早盤前" not in published
    assert "今晚CPI" in upcoming


def test_cbc_row_shows_time_note_and_no_alfred_promise():
    cbc = _ev("央行理監事會", datetime(2099, 1, 5, 16, 0, tzinfo=TPE), source="cbc",
              time_note="會後記者會（台北下午，時間待確認）", series_id=None)
    for line in (format_published(cbc), format_upcoming(cbc)):
        assert "時間待確認" in line
    assert "ALFRED" not in format_published(cbc) and "不適用" in format_published(cbc)
    # 有 series_id 但 ALFRED 還沒收到：仍然是「下次 daily 補」
    assert "下次 daily 補" in format_published(_ev("x", NOW, series_id="FRED:PAYEMS", time_note=None))


# ---------- rate_expectations 多 slot：只取一個 slot，不重複加總 ----------

def _at(day, hour):
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


def test_latest_rate_slot_takes_newest_captured_slot_of_the_newest_day():
    d0, d1 = date(2099, 1, 5), date(2099, 1, 12)
    slots = [(d0, "postclose", _at(d0, 10)), (d1, "premarket", _at(d1, 0)), (d1, "postclose", _at(d1, 10)),
             (d1, "legacy", None)]
    assert latest_rate_slot(slots) == (d1, "postclose")
    assert latest_rate_slot([(d1, "legacy", None), (d0, "premarket", _at(d0, 0))]) == (d1, "legacy")
    assert latest_rate_slot([]) is None


def test_prior_rate_slot_prefers_same_slot_then_premarket_and_is_at_least_a_week_old():
    cur = date(2099, 1, 12)
    old = date(2099, 1, 5)
    slots = [(old, "premarket", _at(old, 0)), (old, "postclose", _at(old, 10)),
             (date(2099, 1, 8), "premarket", _at(date(2099, 1, 8), 0))]      # 只有 4 天前：不夠一週
    assert prior_rate_slot(slots, cur, "postclose") == (old, "postclose")
    assert prior_rate_slot(slots, cur, "premarket") == (old, "premarket")
    assert prior_rate_slot(slots, cur, "intraday") == (old, "premarket")      # 沒有同 slot → 盤前
    assert prior_rate_slot([(old, "legacy", None)], cur, "postclose") == (old, "legacy")
    assert prior_rate_slot([(date(2099, 1, 8), "premarket", None)], cur, "premarket") is None


class _RateRows(list):
    def all(self):
        return list(self)


class _RateConn:
    """依 SQL 形狀回記憶體資料：查列的 SQL 一定要帶 snapshot_slot 條件，否則視為整天加總而失敗。"""

    def __init__(self, rows):
        self.rows = rows   # (snapshot_date, slot, captured_at, meeting_date, outcome, prob_mid)

    def execute(self, stmt, params=None):
        sql, params = str(stmt), params or {}
        if "GROUP BY" in sql:
            grouped = {}
            for sd, slot, cap, *_ in self.rows:
                key = (sd, slot)
                grouped[key] = max(filter(None, [grouped.get(key), cap]), default=None)
            return _RateRows((sd, slot, cap) for (sd, slot), cap in grouped.items())
        assert "snapshot_slot = :k" in sql, f"讀利率列必須限定 slot：{sql}"
        floor = params["s"] if "meeting_date >= :s" in sql else None
        return _RateRows((m, o, p) for sd, slot, _c, m, o, p in self.rows
                     if sd == params["s"] and slot == params["k"] and (floor is None or m >= floor))


def test_print_rates_reads_one_slot_so_probabilities_are_not_double_counted():
    cur, old, meeting = date(2099, 1, 12), date(2099, 1, 5), date(2099, 2, 1)
    rows = []
    for sd, slot, hike, hold, hour in [
            (cur, "premarket", 0.10, 0.88, 0), (cur, "postclose", 0.30, 0.68, 10),
            (old, "premarket", 0.05, 0.93, 0), (old, "postclose", 0.07, 0.91, 10)]:
        rows += [(sd, slot, _at(sd, hour), meeting, "hike_25", hike), (sd, slot, _at(sd, hour), meeting, "hold", hold)]
    lines = []
    print_rates(_RateConn(rows), out=lines.append)
    text_out = "\n".join(lines)
    assert "快照日 2099-01-12 postclose（對照 2099-01-05 postclose）" in text_out
    row = next(line for line in lines if line.startswith("2099-02-01"))
    # 只有 postclose 的 30%（兩個 slot 加起來會是 40%）；一週前同 slot 是 7%（不是盤前 5%、也不是 12%）
    assert "     30%" in row and "     68%" in row and "      7%" in row
    assert "40%" not in row and "156%" not in text_out


def test_print_rates_without_snapshots_says_so():
    lines = []
    print_rates(_RateConn([]), out=lines.append)
    assert any("沒有快照" in line for line in lines)
