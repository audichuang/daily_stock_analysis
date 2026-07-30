# -*- coding: utf-8 -*-
"""Tests for scripts.backtest_screen 的回測正確性核心（不碰 DB / 網路）。

只測會讓整個回測結論失效的事：有沒有前視偏誤、指標面板有沒有對齊。
前復權的正確性在 tests/test_price_adjustment.py（已移到 market_data.adjust）。
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

from backtest_screen import (  # noqa: E402
    FEE_RATE,
    SLIPPAGE,
    MIN_FEE,
    TAX_RATE,
    _irr,
    affordable_shares,
    build_indicators,
    buy_hold_benchmark,
    buy_cost,
    exposure_matched_cagr,
    sell_net,
)

DAYS = pd.date_range("2026-05-01", periods=10, freq="D")


def _panel(values):
    return pd.DataFrame({"1234": values}, index=DAYS)


def test_institutional_data_is_lagged():
    """法人資料 T 日盤後常要 T+1 才補齊，回測必須 shift，否則是用未來資訊。"""
    close = _panel([100.0] * 10)
    inst = pd.DataFrame({
        "stock_id": ["1234"] * 10, "date": DAYS,
        "foreign_net": [0.0] * 9 + [5000.0],  # 只有最後一天有大買超
        "trust_net": [0.0] * 10, "dealer_net": [0.0] * 10,
    })
    val = pd.DataFrame({"stock_id": ["1234"] * 10, "date": DAYS, "pe_ratio": [10.0] * 10})

    ind = build_indicators(close, close, inst, val, lag_days=1)
    # 最後一天的買超不該出現在最後一天的 inst5，只能在「之後」才看得到
    assert ind["inst5"].iloc[-1]["1234"] == pytest.approx(0.0)

    ind0 = build_indicators(close, close, inst.copy(), val, lag_days=0)
    assert ind0["inst5"].iloc[-1]["1234"] == pytest.approx(5000.0)


def test_indicators_align_to_price_columns():
    """法人／估值表覆蓋的標的少於價格表，對不齊會在選股時 KeyError。"""
    close = pd.DataFrame({"1234": [100.0] * 10, "5678": [50.0] * 10}, index=DAYS)
    inst = pd.DataFrame({
        "stock_id": ["1234"] * 10, "date": DAYS,
        "foreign_net": [1.0] * 10, "trust_net": [0.0] * 10, "dealer_net": [0.0] * 10,
    })
    val = pd.DataFrame({"stock_id": ["1234"] * 10, "date": DAYS, "pe_ratio": [10.0] * 10})

    ind = build_indicators(close, close, inst, val)
    assert list(ind["inst5"].columns) == ["1234", "5678"]
    assert list(ind["pe"].columns) == ["1234", "5678"]
    assert ind["inst5"]["5678"].iloc[-1] == pytest.approx(0.0)  # 無資料補 0，不是 NaN


# --- 交易成本：這段是 money path，之前的 bug 正是成本只記在報酬欄、沒從現金扣 ---

def test_buy_cost_adds_fee():
    cost = buy_cost(1000, 50.0, FEE_RATE)
    assert cost == pytest.approx(50000 + 50000 * FEE_RATE)
    assert cost > 50000  # 買進一定比股票成本貴


def test_sell_net_deducts_fee_and_tax():
    net = sell_net(1000, 50.0, FEE_RATE)
    assert net == pytest.approx(50000 - 50000 * FEE_RATE - 50000 * TAX_RATE)
    assert net < 50000  # 賣出一定比股票收入少


def test_minimum_fee_applies_to_small_trades():
    """小額交易的成本由最低手續費主導，費率算法會低估。"""
    small = 1000.0                      # 1000 元的單子，費率手續費只有 1.4 元
    cost = buy_cost(small / 10.0, 10.0, FEE_RATE)
    assert cost == pytest.approx(small + MIN_FEE)
    net = sell_net(small / 10.0, 10.0, FEE_RATE)
    assert net == pytest.approx(small - MIN_FEE - small * TAX_RATE)


def test_round_trip_at_flat_price_loses_money():
    """價格不動時來回一趟必為淨損——若此測試通過不了，代表成本沒被計入。"""
    shares, price = 1000, 50.0
    cost = buy_cost(shares, price, FEE_RATE)
    net = sell_net(shares, price, FEE_RATE)
    loss_pct = net / cost - 1
    assert loss_pct < 0
    # 來回應接近 手續費×2 + 證交稅
    assert loss_pct == pytest.approx(-(FEE_RATE * 2 + TAX_RATE), abs=5e-4)


def test_fee_discount_reduces_cost():
    assert buy_cost(1000, 50.0, FEE_RATE * 0.6) < buy_cost(1000, 50.0, FEE_RATE)


# --- 基準對等性 ---

@pytest.mark.parametrize("script", [
    "backtest_screen.py", "measure_signal_forward.py", "portfolio_walkforward.py",
    "screen_tw.py", "verify_swing_decisions.py",
])
def test_every_pipeline_script_can_print_help(script):
    """argparse 會對 help 字串做 `%` 格式化，所以裸 `%` 會讓 `--help` 直接 ValueError。

    踩過兩次：`portfolio_walkforward --skip-limit-gap` 與 `backtest_screen --include-tib`。
    第一次只在單支腳本加測試，第二支就漏掉了——所以這裡一次釘住全部入口。
    `--help` 在 argparse 階段就結束，不會碰 DB。
    """
    import subprocess

    r = subprocess.run([sys.executable, str(SCRIPTS_DIR / script), "--help"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, f"{script} --help 失敗：{r.stderr[-500:]}"


def test_buy_hold_benchmark_charges_entry_and_the_etf_exit_tax():
    """0050 的賣出證交稅是 ETF 的 0.1%，不是 `sell_net` 預設的個股 0.3%。"""
    from tw_trade_costs import ETF_TRANSACTION_TAX_RATE, sell_cash_inflow

    days = pd.bdate_range("2026-01-01", periods=3)
    price = pd.Series(100.0, index=days)

    curve = buy_hold_benchmark(price, capital=200_000, fee_rate=FEE_RATE)

    entry = 100 * (1 + SLIPPAGE)
    shares = affordable_shares(200_000, entry, fee_rate=FEE_RATE)
    cash = 200_000 - buy_cost(shares, entry, FEE_RATE)
    expected = cash + sell_cash_inflow(shares, 100 * (1 - SLIPPAGE),
                                       fee_rate=FEE_RATE,
                                       tax_rate=ETF_TRANSACTION_TAX_RATE)
    assert curve.iloc[-1] == pytest.approx(expected)
    # 個股稅率會多扣 0.2%，基準被壓低
    assert curve.iloc[-1] > cash + sell_net(shares, 100 * (1 - SLIPPAGE), FEE_RATE)


def _ledger(cash_ratio):
    eq = pd.Series(100.0, index=DAYS)
    return pd.DataFrame({"equity": eq, "cash": eq * cash_ratio})


def test_exposure_matched_equals_benchmark_when_fully_invested():
    bench = pd.Series([100.0 * (1.01 ** i) for i in range(10)], index=DAYS)
    years = 10 / 252
    full = exposure_matched_cagr(bench, _ledger(0.0), years)
    direct = (bench.iloc[-1] / bench.iloc[0]) ** (1 / years) - 1
    # 首日曝險以 0 起算（當日曝險收盤後才知道），故略低於直接持有
    assert full > 0
    assert full < direct


def test_exposure_matched_is_zero_when_all_cash():
    bench = pd.Series([100.0 * (1.01 ** i) for i in range(10)], index=DAYS)
    assert exposure_matched_cagr(bench, _ledger(1.0), 10 / 252) == pytest.approx(0.0)


def test_exposure_matched_scales_with_exposure():
    """半倉承受的基準報酬應介於空手與滿倉之間——這是比較對等性的核心。"""
    bench = pd.Series([100.0 * (1.01 ** i) for i in range(10)], index=DAYS)
    years = 10 / 252
    half = exposure_matched_cagr(bench, _ledger(0.5), years)
    full = exposure_matched_cagr(bench, _ledger(0.0), years)
    assert 0 < half < full


def test_irr_recovers_known_rate():
    """單筆投入、單筆回收：IRR 應等於複利率。"""
    assert _irr([(0.0, -100.0), (2.0, 121.0)]) == pytest.approx(0.10, abs=1e-4)
    assert _irr([(0.0, -100.0), (1.0, 100.0)]) == pytest.approx(0.0, abs=1e-4)


def test_irr_returns_nan_when_no_sign_change():
    assert pd.isna(_irr([(0.0, -100.0), (1.0, -50.0)]))


# --- 整條交易迴圈：獨立審查指出「沒有任何測試真正呼叫 run()」，
#     所以 helper 的成本測試全綠，期末 ledger 仍可能漏成本。以下用合成面板跑真迴圈。

def _synthetic(n_days=30, price=100.0, drift=0.0):
    days = pd.bdate_range("2026-01-01", periods=n_days)
    cols = pd.Index(["1111", "2222"])
    px = pd.DataFrame(
        {c: [price * (1 + drift) ** i for i in range(n_days)] for c in cols}, index=days)
    ind = {
        "close": px, "ma10": px * 0.9, "ma20": px * 0.9, "ma60": px * 0.9,
        "atr": px * 0.02,
    }
    return days, cols, px, ind


def test_run_conserves_cash_when_flat_and_never_traded():
    """沒有訊號時淨值必須恰好等於初始本金——多一分少一分都代表記帳漏了。"""
    from backtest_screen import run
    days, _, px, ind = _synthetic()
    trades, ledger = run(ind, px, days, {}, slots=5, rule="ma60",
                         max_hold=250, capital=1_000_000)
    assert trades.empty
    assert ledger["equity"].iloc[-1] == pytest.approx(1_000_000)
    assert ledger["fees"].iloc[-1] == 0.0


def test_run_charges_fees_into_equity_on_round_trip():
    """價格全程不動、買一趟賣一趟，淨值必須因成本而**下降**。

    這正是先前的 bug：成本只寫進交易明細的 ret 欄，cash 沒扣，淨值曲線看不出來。
    """
    from backtest_screen import run
    days, _, px, ind = _synthetic(n_days=30)
    ind = {**ind, "ma60": px * 1.10}          # 收盤永遠低於 MA60 → 進場後隔日就出場
    sig = {days[0]: ["1111"]}
    trades, ledger = run(ind, px, days, sig, slots=5, rule="ma60",
                         max_hold=250, capital=1_000_000)

    assert len(trades) == 1
    assert trades["ret"].iloc[0] < 0                       # 平盤來回必虧
    assert ledger["equity"].iloc[-1] < 1_000_000           # 淨值要反映成本
    assert ledger["fees"].iloc[-1] > 0
    # 期末淨值的損失量應等於交易明細的損益（記帳一致性）
    assert ledger["equity"].iloc[-1] - 1_000_000 == pytest.approx(
        trades["pnl"].sum(), rel=1e-6)


def test_run_never_exceeds_slot_limit():
    from backtest_screen import run
    days, _, px, ind = _synthetic(n_days=30)
    sig = {d: ["1111", "2222"] for d in days}
    _, ledger = run(ind, px, days, sig, slots=1, rule="none",
                    max_hold=250, capital=1_000_000)
    assert ledger["positions"].max() <= 1


def test_run_signal_on_T_fills_at_T_plus_1_open():
    """T 日收盤產生的訊號不得用 T 日價格成交——用開盤跳空的面板驗證成交價。"""
    from backtest_screen import run
    days, cols, px, ind = _synthetic(n_days=10)
    open_ = px * 1.5                                        # 開盤價明顯高於收盤
    sig = {days[0]: ["1111"]}
    trades, _ = run(ind, open_, days, sig, slots=5, rule="none",
                    max_hold=250, capital=1_000_000)
    assert len(trades) == 1
    assert trades["entry_day"].iloc[0] == days[1]           # T+1 才成交，不是 T


def test_run_position_size_compounds_with_equity():
    """部位大小要跟著淨值走；用初始本金的話獲利不再投入、曝險會隨獲利下滑。"""
    from backtest_screen import run
    days, _, px, ind = _synthetic(n_days=60, drift=0.02)    # 每日 +2%
    sig = {d: ["1111", "2222"] for d in days}
    _, ledger = run(ind, px, days, sig, slots=2, rule="none",
                    max_hold=250, capital=1_000_000)
    # 資產翻倍後仍應維持高曝險（現金佔比不該隨獲利累積而膨脹）。
    # 看倒數第二列：最後一列是期末強制平倉後的狀態，全部是現金屬正常。
    late_cash_ratio = (ledger["cash"] / ledger["equity"]).iloc[-2]
    assert ledger["equity"].iloc[-1] > 1_000_000
    assert late_cash_ratio < 0.5


def test_regime_gate_blocks_new_entries():
    """regime 關閉的日子不得開新倉（用 T 日收盤判斷、T+1 成交，與訊號同時序）。"""
    from backtest_screen import run
    days, _, px, ind = _synthetic(n_days=30)
    sig = {d: ["1111"] for d in days}
    closed = pd.Series(False, index=days)
    trades, ledger = run(ind, px, days, sig, slots=5, rule="none", max_hold=250,
                         capital=1_000_000, entry_ok=closed)
    assert trades.empty and ledger["positions"].max() == 0


def test_regime_exit_also_liquidates_holdings():
    """只擋進場對回撤無效（實測 -61.6%→-60.6%），因為回撤來自抱著部位穿越下跌。

    `--regime-exit` 要在 regime 關閉當日就把持倉排進賣單，隔日開盤出清。
    """
    from backtest_screen import run
    days, _, px, ind = _synthetic(n_days=30)
    sig = {days[0]: ["1111"]}
    ok = pd.Series(True, index=days)
    ok.iloc[10:] = False                       # 第 11 天起 regime 轉空
    trades, ledger = run(ind, px, days, sig, slots=5, rule="none", max_hold=250,
                         capital=1_000_000, entry_ok=ok, regime_exit=True)
    assert len(trades) == 1
    assert trades["reason"].iloc[0] == "regime出場"
    assert trades["exit_day"].iloc[0] == days[11]    # T 日判斷、T+1 成交
    assert ledger["positions"].iloc[12:].max() == 0

    # 同樣情境不開 regime_exit 時,部位會一路抱到期末
    tr2, _ = run(ind, px, days, sig, slots=5, rule="none", max_hold=250,
                 capital=1_000_000, entry_ok=ok)
    assert tr2["reason"].iloc[0] == "期末平倉"


def test_mark_falls_back_to_last_known_price_on_suspension():
    """停牌（close 為 NaN）不能當成 0——那會造成假回撤，還連帶縮小下一批部位。"""
    from backtest_screen import _mark
    days, cols, px, _ = _synthetic(n_days=5)
    close = px.copy()
    close.iloc[2, 0] = float("nan")                       # 1111 第 3 天停牌
    last = {"1111": 100.0}
    assert _mark(close, days[2], "1111", last) == 100.0
    assert _mark(close, days[1], "1111", last) == pytest.approx(close.iloc[1, 0])
    assert _mark(close, days[2], "9999", {}) == 0.0       # 從未有價：只能回 0


def test_run_suspended_holding_does_not_zero_equity():
    """停牌當日的持倉市值要用最後已知價，淨值不該瞬間掉一個部位。"""
    from backtest_screen import run
    days, _, px, ind = _synthetic(n_days=10)
    close = px.copy()
    close.iloc[5, :] = float("nan")                       # 第 6 天兩檔都停牌
    ind = {**ind, "close": close}
    sig = {days[0]: ["1111", "2222"]}
    _, ledger = run(ind, px, days, sig, slots=2, rule="none",
                    max_hold=250, capital=1_000_000)
    eq = ledger["equity"]
    assert eq.iloc[5] > 0.99 * eq.iloc[4]                 # 舊版會掉到近 0


def test_run_final_liquidation_costs_land_in_ledger():
    """期末平倉的賣出成本要回寫 ledger——stats() 讀 ledger，不回寫就高估期末淨值。"""
    from backtest_screen import run
    days, _, px, ind = _synthetic(n_days=10)
    sig = {days[0]: ["1111"]}
    trades, ledger = run(ind, px, days, sig, slots=1, rule="none",
                         max_hold=250, capital=1_000_000)
    assert trades["reason"].iloc[-1] == "期末平倉"
    # 平盤來回必虧，且 ledger 的期末損失要等於交易明細的損益（記帳一致）
    assert ledger["equity"].iloc[-1] < 1_000_000
    assert ledger["equity"].iloc[-1] - 1_000_000 == pytest.approx(
        trades["pnl"].sum(), rel=1e-6)


def test_run_unfilled_sell_order_is_retried_not_dropped():
    """T+1 停牌沒有開盤價時賣單必須留著，隔日再成交——舊版直接丟掉會無聲繼續持有。"""
    from backtest_screen import run
    days, _, px, ind = _synthetic(n_days=10)
    open_ = px.copy()
    open_.iloc[2, 0] = float("nan")                       # 1111 在第 3 天沒有開盤價
    ind = {**ind, "ma60": px * 1.10}                      # 收盤永遠低於 MA60 → 隔日就出場
    sig = {days[0]: ["1111"]}
    trades, _ = run(ind, open_, days, sig, slots=1, rule="ma60",
                    max_hold=250, capital=1_000_000)
    assert len(trades) == 1
    assert trades["exit_day"].iloc[0] == days[3]          # 順延一天成交，不是消失
    assert trades["reason"].iloc[0] == "跌破MA60"
