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
