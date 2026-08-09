# -*- coding: utf-8 -*-
"""Tests for scripts/overnight.py（純數學，不碰網路）。

釘兩類會**靜默出錯**的東西：

1. **ADR 折算公式的方向**。我在同一個 session 裡把它寫反過（`÷ 匯率`），得到 61.8 元
   ——反過來寫不會噴錯，只會產出一個看起來像價格的數字。
2. **日期一致性檢查的分組**。韓股與台股同時段，盤前拿到的韓國收盤本來就比美股那組晚一個
   日曆日；混在一組比會每天誤報，而每天都報的警告等於沒有警告。
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from overnight import SERIES, adr_implied, date_warnings  # noqa: E402


def test_adr_converts_to_a_plausible_tw_share_price():
    # 2026-07-27 實測：ADR 399.09 美元、匯率 32.301、台積電台股收 2,350
    implied = adr_implied(399.09, 32.301)
    assert implied == pytest.approx(2578.5, abs=1.0)
    assert 0.05 < implied / 2350 - 1 < 0.15        # ADR 長期溢價約 +10%，不是 -97%


def test_reversed_formula_would_be_absurd():
    """把匯率寫成除數會得到 61.8——沒有例外、沒有告警，只有一個錯的數字。"""
    wrong = 399.09 / 32.301 / 5
    assert wrong < 100 and adr_implied(399.09, 32.301) > 2000


def _row(ticker, group, day):
    return {"名稱": ticker, "代碼": ticker, "組": group, "日期": date(2026, 8, *day)}


def test_korea_lagging_us_by_one_day_is_not_a_warning():
    """韓股與台股同時段，盤前拿到的韓國收盤本來就比美股那組晚一個日曆日。

    混在一組比會每天誤報——誤報等於沒有警告，因為沒人會再看它。
    """
    rows = [
        _row("^DJI", "us", (3,)), _row("^SOX", "us", (3,)), _row("MU", "us", (3,)),
        _row("000660.KS", "kr", (4,)), _row("005930.KS", "kr", (4,)),
        _row("TWD=X", "cont", (4,)),
    ]
    assert date_warnings(rows) == []


def test_mismatch_inside_one_group_still_warns():
    rows = [_row("^DJI", "us", (3,)), _row("^SOX", "us", (2,)),
            _row("000660.KS", "kr", (4,)), _row("005930.KS", "kr", (4,))]
    warns = date_warnings(rows)
    assert len(warns) == 1 and "美股" in warns[0]


def test_memory_proxies_are_in_series():
    """記憶體的代理是韓股與美光，不是費半（同日 r 0.577／0.364 vs 0.123）。"""
    tickers = {t for _, t, _, _ in SERIES}
    assert {"MU", "000660.KS", "005930.KS", "^KS11"} <= tickers
