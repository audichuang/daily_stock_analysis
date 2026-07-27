# -*- coding: utf-8 -*-
"""Tests for scripts/portfolio_walkforward.py 的資金會計（不碰 DB／網路）。

只測會讓權益曲線說謊的三件事：同日資金競爭有沒有真的擋住超額進場、成交報酬有沒有等於
「開盤買 / 收盤賣扣兩邊成本」、下市有沒有被結算（而不是無限期持有一個死部位）。
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

from portfolio_walkforward import (  # noqa: E402
    DEAD_DAYS, LIMIT_GAP, SIDE_COST, daily_scores, simulate, walk_forward_signals,
)
from measure_signal_forward import factors  # noqa: E402


def _piv(n=40, cols=("1111", "2222", "3333")):
    days = pd.bdate_range("2026-01-01", periods=n)
    close = pd.DataFrame({c: [100.0 + i for i in range(n)] for c in cols}, index=days)
    return {"close": close, "open": close.copy(), "high": close.copy(),
            "low": close * 0.99, "volume": close * 0 + 1000, "turnover": close * 0 + 3e8}


def _blank(piv):
    """全 False 的訊號面板 + 一組能讓 rank='score' 跑起來的因子面板。"""
    close = piv["close"]
    sig = pd.DataFrame(False, index=close.index, columns=close.columns)
    f = factors(piv, 1e8)
    yoy = pd.DataFrame(30.0, index=close.index, columns=close.columns)
    return sig, f, yoy


def test_no_signal_means_flat_equity():
    piv = _piv()
    sig, f, yoy = _blank(piv)
    eq, tr, sk, _ = simulate(piv, sig, f, yoy, 5, 5, "2026-01-05", "2026-02-20")
    assert eq.to_numpy() == pytest.approx(1.0)
    assert len(tr) == 0 and len(sk) == 0


def test_slot_limit_blocks_same_day_competitors():
    """同一天三檔觸發、只有一個空位 → 一筆成交、兩筆列入被排擠。

    這是整支腳本存在的理由：邊際期望值為正不代表有限資金拿得到，被擋掉的那些必須留痕
    才能算排擠成本。
    """
    piv = _piv()
    sig, f, yoy = _blank(piv)
    sig.iloc[10] = True                       # 三檔同日觸發
    eq, tr, sk, cn = simulate(piv, sig, f, yoy, 5, 1, "2026-01-05", "2026-02-20")
    assert len(tr) == 1
    assert len(sk) == 2 and set(sk["reason"]) <= {"no_slot", "no_cash"}
    assert eq.iloc[-1] > 1.0                  # 唯一那筆是賺的（面板單調上漲）


def test_trade_return_is_open_to_close_minus_both_side_costs():
    piv = _piv()
    sig, f, yoy = _blank(piv)
    sig.iloc[10, 0] = True
    h = 5
    _, tr, _, _ = simulate(piv, sig, f, yoy, h, 5, "2026-01-05", "2026-02-20")
    entry = piv["open"].iloc[11, 0]           # 訊號日的次一交易日開盤
    exit_ = piv["close"].iloc[11 + h - 1, 0]  # 進場後持有 h 個交易日
    expect = (exit_ / entry) * (1 - SIDE_COST) ** 2 - 1
    assert tr["r"].iloc[0] == pytest.approx(expect)
    assert tr["entry"].iloc[0] == pytest.approx(entry)


def test_delisted_position_is_settled_not_held_forever():
    piv = _piv()
    for k in ("close", "open"):
        piv[k].iloc[14:, 0] = float("nan")    # 1111 第 15 天起停止交易
    sig, f, yoy = _blank(piv)
    sig.iloc[10, 0] = True
    last, tr_last, _, _ = simulate(piv, sig, f, yoy, 60, 5, "2026-01-05", "2026-03-20")
    zero, tr_zero, _, _ = simulate(piv, sig, f, yoy, 60, 5, "2026-01-05", "2026-03-20",
                                   delisting="zero")
    # 持有期 60 天遠長於面板，但下市當天就該結清（否則權益曲線一直掛著一個死部位）
    assert len(tr_last) == 1 and bool(tr_last["delisted"].iloc[0])
    assert tr_zero["r"].iloc[0] == pytest.approx(-1.0)
    assert last.iloc[-1] > zero.iloc[-1]      # 最後成交價結算比歸零樂觀
    assert zero.iloc[-1] == pytest.approx(0.8, abs=0.01)   # 5 個空位其中 1 個歸零


def test_suspended_exit_day_defers_instead_of_selling_at_a_stale_price():
    """出場日停牌就順延到下一個可成交日——用最後成交價賣是賣在一個不存在的價格。

    也順帶鎖住「不看未來」：舊版用「這一列或之後還有沒有成交價」判定下市，等於在第一個
    缺價日就知道樣本內不會再有報價而提前釋放資金。
    """
    piv = _piv(n=40)
    sig, f, yoy = _blank(piv)
    sig.iloc[10, 0] = True                       # 進場日 index 11、原定出場 index 15
    for k in ("close", "open"):
        piv[k].iloc[15:17, 0] = float("nan")     # 出場日與次日停牌，第 3 天復牌
    _, tr, _, _ = simulate(piv, sig, f, yoy, 5, 5, "2026-01-05", "2026-02-20")
    assert len(tr) == 1
    assert tr["exit_date"].iloc[0] == piv["close"].index[17]   # 順延到復牌日
    assert bool(tr["deferred"].iloc[0]) and not bool(tr["delisted"].iloc[0])
    assert tr["exit"].iloc[0] == pytest.approx(piv["close"].iloc[17, 0])


def test_long_suspension_becomes_a_delisting_only_after_dead_days():
    piv = _piv(n=40)
    sig, f, yoy = _blank(piv)
    sig.iloc[5, 0] = True
    for k in ("close", "open"):
        piv[k].iloc[8:, 0] = float("nan")        # 第 9 天起再無報價
    _, tr, _, _ = simulate(piv, sig, f, yoy, 5, 5, "2026-01-05", "2026-03-20")
    assert bool(tr["delisted"].iloc[0])
    # 第一個缺價日是 index 8，連續 DEAD_DAYS 個交易日後才判死
    assert tr["exit_date"].iloc[0] == piv["close"].index[8 + DEAD_DAYS - 1]


def test_score_is_ranked_on_the_full_daily_pool_not_the_leftovers():
    """排序分數要在**當日完整候選池**上算——live 就是這樣算的。

    先剔除已持股再算 pct-rank，其餘個股的百分位間距會改變甚至翻轉排序（獨立審查指出）。
    """
    piv = _piv(n=100)                            # 需 >60 根，量比的 60 日視窗才不是 NaN
    sig, f, yoy = _blank(piv)
    d = piv["close"].index[70]
    sig.loc[d] = True
    yoy.loc[d] = [10.0, 90.0, 50.0]              # 2222 最強、3333 次之
    full = daily_scores(sig, f, yoy)
    order_full = sorted(["1111", "2222", "3333"], key=lambda s: -full[(d, s)])
    assert order_full[0] == "2222"
    # 把最強的那檔當成已持股移除後，剩下兩檔的相對順序不能被重算分數改掉
    sub = sig.copy()
    sub.loc[d, "2222"] = False
    partial = daily_scores(sub, f, yoy)
    assert (full[(d, "3333")] > full[(d, "1111")]) == (
        partial[(d, "3333")] > partial[(d, "1111")])
    assert full[(d, "3333")] != partial[(d, "3333")]      # 分數真的會變，所以口徑要固定


def test_limit_up_gap_entries_can_be_skipped_for_sensitivity():
    piv = _piv(n=40)
    piv["open"].iloc[11, 0] = piv["close"].iloc[10, 0] * (1 + LIMIT_GAP + 0.005)
    sig, f, yoy = _blank(piv)
    sig.iloc[10, 0] = True
    _, tr_on, _, cn = simulate(piv, sig, f, yoy, 5, 5, "2026-01-05", "2026-02-20",
                               skip_limit_gap=True)
    _, tr_off, _, _ = simulate(piv, sig, f, yoy, 5, 5, "2026-01-05", "2026-02-20")
    assert len(tr_on) == 0 and cn["limit_gap"] == 1
    assert len(tr_off) == 1


def test_walk_forward_never_trades_inside_its_own_training_window():
    """走前驗證的意義全在這一條：第一折的訓練區間內不能有任何訊號。"""
    piv = _piv(n=300)
    close = piv["close"]
    f = factors(piv, 1e8)
    yoy = pd.DataFrame(50.0, index=close.index, columns=close.columns)
    ret = pd.DataFrame(0.1, index=close.index, columns=close.columns)
    out, picks, start = walk_forward_signals(close, f, yoy, ret, 5,
                                             close.index[0], close.index[-1], 5, 1.3)
    assert not out.loc[:pd.Timestamp(start)].to_numpy().any()
    assert start > close.index[0]
