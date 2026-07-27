# -*- coding: utf-8 -*-
"""Tests for scripts/verify_swing_decisions.py（不碰 DB／網路）。

回驗的兩個致命點：持有窗口有沒有跟量測腳本逐格對齊（差一天，Brier 與加值都對不上），
以及未到期的決策有沒有被誤當成已到期（那會用不足 60 天的報酬評分）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from verify_swing_decisions import (  # noqa: E402
    diff_ci, fill_ok, read_log, summarize, window,
)

CAL = pd.bdate_range("2026-01-05", periods=30)      # 週一起算的營業日


def test_window_is_next_open_to_the_hth_trading_day_close():
    entry, exit_, left = window(CAL, "2026-01-05", 5)
    assert entry == CAL[1] and exit_ == CAL[5] and left == 0


def test_decision_made_on_a_non_trading_day_aligns_backwards():
    """判斷常在週末／收盤後做——要對齊到最近的**過去**交易日，不能借用未來那一天的開盤。"""
    sat = pd.Timestamp("2026-01-10")                 # 週六
    assert window(CAL, sat, 5)[0] == window(CAL, CAL[4], 5)[0]   # 對齊到 1/9 週五


def test_pending_decision_reports_remaining_days_instead_of_a_fake_return():
    entry, exit_, left = window(CAL, CAL[27], 5)
    assert entry is None and exit_ is None and left == 3


def test_read_log_skips_blank_and_comment_lines(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text('# 註解\n\n{"date":"2026-07-24","stock_id":"2615","verdict":"enter"}\n',
                 encoding="utf-8")
    df = read_log(p)
    assert len(df) == 1 and df["stock_id"].iloc[0] == "2615"


def test_read_log_refuses_a_truncated_line_instead_of_dropping_it(tmp_path):
    """一行壞掉就整份不算——靜默跳過等於讓回驗少掉幾筆而沒人知道。"""
    p = tmp_path / "d.jsonl"
    p.write_text('{"date":"2026-07-24","stock_id":"2615"\n', encoding="utf-8")
    with pytest.raises(SystemExit, match="不是合法 JSON"):
        read_log(p)


def test_entry_waits_for_decided_at_not_just_the_signal_date():
    """週五的訊號若到週一晚上才研究完，不能用週一開盤成交——那天的判斷還不存在。

    `decided_at` 就是為了讓這件事可稽核才要求必填；忽略它會讓回驗數字含未來資訊。
    """
    fri, mon, tue = CAL[4], CAL[5], CAL[6]
    naive = window(CAL, fri, 5)[0]
    late = window(CAL, fri, 5, decided_at="2026-01-12T21:30+08:00")[0]   # 週一晚間
    assert naive == mon          # 只看訊號日 → 週一進場
    assert late == tue            # 看判斷時點 → 週二才合法


def test_decided_at_before_the_signal_date_does_not_pull_entry_earlier():
    assert window(CAL, CAL[4], 5, decided_at="2025-12-01T09:00+08:00")[0] == CAL[5]


def test_gap_through_the_entry_range_is_a_no_fill():
    """開盤已高於建議區間上界＝這筆沒成交；算成成交就是把沒發生的決策計進加值統計。"""
    assert not fill_ok(95.0, [85.0, 88.0])
    assert fill_ok(88.0, [85.0, 88.0])
    assert fill_ok(80.0, [85.0, 88.0])       # 更便宜仍算成交
    assert fill_ok(999.0, None)              # 沒填區間就不判定


def test_diff_ci_needs_two_sided_evidence():
    """差值本身永遠不為零,所以結論必須靠區間。明顯的差要不跨零、雜訊要跨零。"""
    import numpy as np
    big = pd.Series(np.r_[np.full(40, 0.5), np.full(40, 0.5)])
    small = pd.Series(np.r_[np.full(40, -0.5), np.full(40, -0.5)])
    lo, hi = diff_ci(big, small)
    assert lo > 0 and hi > 0
    noisy = pd.Series([0.1, -0.1] * 20)
    lo2, hi2 = diff_ci(noisy, noisy)
    assert lo2 < 0 < hi2
    assert all(pd.isna(v) for v in diff_ci(pd.Series([0.1]), pd.Series([0.2])))


def test_summarize_counts_the_tails():
    r = pd.Series([0.5, 0.1, -0.25, -0.05])
    s = summarize(r, "enter")
    assert s["筆數"] == 4 and s["勝率"] == "50.0%"
    assert s["P(≥30%)"] == "25.0%" and s["P(≤-20%)"] == "25.0%"
