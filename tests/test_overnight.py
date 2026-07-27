# -*- coding: utf-8 -*-
"""Tests for scripts/overnight.py（純數學，不碰網路）。

只釘一件事：ADR 折算公式的方向。我在同一個 session 裡把它寫反過（`÷ 匯率`），
得到 61.8 元——反過來寫不會噴錯，只會產出一個看起來像價格的數字。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from overnight import adr_implied  # noqa: E402


def test_adr_converts_to_a_plausible_tw_share_price():
    # 2026-07-27 實測：ADR 399.09 美元、匯率 32.301、台積電台股收 2,350
    implied = adr_implied(399.09, 32.301)
    assert implied == pytest.approx(2578.5, abs=1.0)
    assert 0.05 < implied / 2350 - 1 < 0.15        # ADR 長期溢價約 +10%，不是 -97%


def test_reversed_formula_would_be_absurd():
    """把匯率寫成除數會得到 61.8——沒有例外、沒有告警，只有一個錯的數字。"""
    wrong = 399.09 / 32.301 / 5
    assert wrong < 100 and adr_implied(399.09, 32.301) > 2000
