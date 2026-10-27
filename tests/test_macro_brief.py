# -*- coding: utf-8 -*-
"""scripts/macro_brief.py 的純函式（不碰 DB、不連外）。

釘兩件會靜默算錯的事：殖利率的變化要用 bp（拿百分比算 4.5→4.6 會印成 +2.2%，看起來像大事），
以及利率路徑不能把沒有報價的合約當 0 機率默默加總。
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from macro_brief import rate_path, series_stats  # noqa: E402


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
                actual_vintage=None, status="confirmed", source="fred")
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
    assert _names(upcoming) == [], "今晚的數據在次一場次 13:30 之後，不屬於『今日待公布』"


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
