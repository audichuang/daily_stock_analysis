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

import portfolio_walkforward as portfolio  # noqa: E402

from portfolio_walkforward import (  # noqa: E402
    DEAD_DAYS, DEFAULT_CAPITAL, LIMIT_GAP, bench_0050, daily_scores, main,
    metrics, simulate, walk_forward_signals, yearly_returns,
)
from measure_signal_forward import factors  # noqa: E402
from tw_trade_costs import (  # noqa: E402
    ETF_TRANSACTION_TAX_RATE,
    STOCK_TRANSACTION_TAX_RATE,
    affordable_shares,
    buy_cash_outflow,
    buy_fill_price,
    sell_cash_inflow,
    sell_fill_price,
)


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


def test_help_renders_literal_percentage_without_loading_the_database(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0
    assert "9.5%" in capsys.readouterr().out


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


def test_trade_return_uses_buy_commission_then_sell_commission_and_tax():
    piv = _piv()
    sig, f, yoy = _blank(piv)
    sig.iloc[10, 0] = True
    h = 5
    _, tr, _, _ = simulate(piv, sig, f, yoy, h, 5, "2026-01-05", "2026-02-20")
    entry = buy_fill_price(piv["open"].iloc[11, 0])
    exit_ = sell_fill_price(piv["close"].iloc[11 + h - 1, 0])
    budget = DEFAULT_CAPITAL / 5
    shares = affordable_shares(budget, entry)
    expect = sell_cash_inflow(shares, exit_) / buy_cash_outflow(shares, entry) - 1
    assert tr["r"].iloc[0] == pytest.approx(expect)
    assert tr["entry"].iloc[0] == pytest.approx(entry)


def test_0050_benchmark_charges_buy_commission_and_the_etf_sell_tax():
    """0050 是 ETF：賣方證交稅 0.1%，不是個股的 0.3%。沿用個股稅率會高估基準成本，
    而這條流水線的結論正是「輸給 0050」——偏誤方向對策略有利，所以必須用對稅率。"""
    days = pd.bdate_range("2026-01-01", periods=3)
    piv = {"close": pd.DataFrame({"0050": [100.0, 100.0, 100.0]}, index=days)}
    capital = 200_000.0

    equity = bench_0050(piv, days, capital=capital)
    entry = buy_fill_price(100.0)
    shares = affordable_shares(capital, entry)
    paid = buy_cash_outflow(shares, entry)
    expected_end = capital - paid + sell_cash_inflow(
        shares, sell_fill_price(100.0), tax_rate=ETF_TRANSACTION_TAX_RATE)

    expected_after_buy = (capital - paid + shares * 100.0) / capital
    assert equity.iloc[0] == pytest.approx(expected_after_buy)
    assert equity.iloc[0] < 1.0
    assert equity.iloc[-1] == pytest.approx(expected_end / capital)
    assert equity.iloc[-1] < 1.0
    # 用個股稅率會多扣 0.2% 的期末市值，基準因此被系統性壓低
    stock_tax_end = capital - paid + sell_cash_inflow(
        shares, sell_fill_price(100.0), tax_rate=STOCK_TRANSACTION_TAX_RATE)
    assert equity.iloc[-1] > stock_tax_end / capital

    # --- 手算的黃金值：**刻意不呼叫任何 tw_trade_costs helper** ---
    # 上面的期望值和生產程式碼走同一批 helper，所以「helper 自己漏算手續費」的 mutation
    # 會讓兩邊一起錯、測試照樣綠（獨立審查指出）。這裡改用純算術釘住：
    #   entry = 100 × 1.0015 = 100.15；shares = 200000 / (100.15 × 1.001425) = 1994.162811
    #   買進付光本金 → cash = 0
    #   exit = 100 × 0.9985 = 99.85；net = gross × (1 − 0.001425 − 0.001) = 198634.2976
    # 個股稅率 0.3% 會得到 0.9911803164，差得夠遠、不會被 rel=1e-9 混過去。
    assert equity.iloc[-1] == pytest.approx(0.9931714880, rel=1e-9)


def test_yearly_returns_start_the_first_year_from_original_capital():
    """第一年若用第一列權益當分母，首日進場成本會被抵掉、逐年表跟 metrics 對不起來。"""
    days = pd.bdate_range("2025-12-01", periods=40)
    curve = pd.Series(0.99, index=days)
    curve.loc[curve.index[curve.index.year == 2026]] = 1.05

    yearly = yearly_returns(curve)

    assert yearly.iloc[0] == pytest.approx(-1.0)      # 2025：1.0 → 0.99
    assert yearly.iloc[1] == pytest.approx((1.05 / 0.99 - 1) * 100)


def test_metrics_keeps_original_capital_as_the_return_baseline():
    days = pd.bdate_range("2026-01-01", periods=2)
    equity = pd.Series([0.99, 1.0], index=days)

    result = metrics(equity)

    assert result["總報酬"] == "+0.0%"
    assert result["最大回撤"] == "-1.0%"


def test_terminal_equity_deducts_exit_cost_for_right_censored_position():
    piv = _piv(n=20, cols=("1111",))
    for field in ("close", "open", "high", "low"):
        piv[field].loc[:, "1111"] = 100.0
    sig, f, yoy = _blank(piv)
    sig.iloc[5, 0] = True

    eq, trades, _, counts = simulate(
        piv, sig, f, yoy, 60, 5, piv["close"].index[1], piv["close"].index[-1])

    budget = DEFAULT_CAPITAL / 5
    entry = buy_fill_price(100.0)
    shares = affordable_shares(budget, entry)
    paid = buy_cash_outflow(shares, entry)
    expected = (DEFAULT_CAPITAL - paid
                + sell_cash_inflow(shares, sell_fill_price(100.0))) / DEFAULT_CAPITAL
    assert trades.empty
    assert counts["open_at_end"] == 1
    assert eq.iloc[-1] == pytest.approx(expected)
    assert eq.iloc[-1] < 1.0


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
    assert tr["exit"].iloc[0] == pytest.approx(sell_fill_price(piv["close"].iloc[17, 0]))


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


def test_walk_forward_training_uses_requested_cost_assumptions(monkeypatch):
    piv = _piv(n=300)
    close = piv["close"]
    f = factors(piv, 1e8)
    yoy = pd.DataFrame(50.0, index=close.index, columns=close.columns)
    ret = pd.DataFrame(0.1, index=close.index, columns=close.columns)
    calls = []

    def fake_to_events(sig, actual_ret, h, extra, **kwargs):
        calls.append(kwargs)
        events = pd.DataFrame({"r": [0.1] * 20})
        return events.copy(), events

    monkeypatch.setattr(portfolio, "to_events", fake_to_events)
    portfolio.walk_forward_signals(
        close, f, yoy, ret, 5, close.index[0], close.index[-1], 5, 1.3,
        entry_notional=123_456, fee_discount=0.6,
    )

    assert calls
    assert all(call == {
        "entry_notional": 123_456,
        "fee_discount": 0.6,
    } for call in calls)


# ---- 研究宇宙：組合模擬的池子必須走共用的 `is_common_stock` -------------------------------
UNIVERSE_CODES = ["2330", "6488", "5305", "9802", "9904", "9921", "9105", "912000",
                  "00878", "0050", "00631L", "2887A", "70001"]
UNIVERSE_COMMON = {"2330", "6488", "5305", "9802", "9904", "9921"}


def test_pool_filters_with_the_shared_universe_predicate(monkeypatch):
    """退回 `startswith("00")` 會讓 TDR／特別股回到池子；擋太寬（整個 9 開頭）會誤殺普通股。"""
    from market_data.adjust import is_common_stock

    days = pd.bdate_range("2026-01-05", periods=5)
    panel = pd.DataFrame(100.0, index=days, columns=UNIVERSE_CODES)
    piv = {k: panel.copy() for k in ("open", "high", "low", "close", "volume", "turnover")}
    info = pd.DataFrame({"stock_id": UNIVERSE_CODES, "name": UNIVERSE_CODES})
    monkeypatch.setattr(portfolio, "get_engine", lambda: object())
    monkeypatch.setattr(portfolio, "load", lambda *a: (piv, pd.DataFrame(), info))
    seen = []
    captured = {}

    def checked(sid):
        seen.append(sid)
        return is_common_stock(sid)

    class PoolCaptured(Exception):
        pass

    def capture(rv, index, columns):
        captured["columns"] = list(columns)
        raise PoolCaptured

    # 先釘住腳本綁的就是共用謂詞；否則下面的 spy 會蓋掉錯誤的本地綁定，守門形同虛設。
    assert portfolio.is_common_stock is is_common_stock
    monkeypatch.setattr(portfolio, "is_common_stock", checked)
    monkeypatch.setattr(portfolio, "pit_revenue_panel", capture)
    with pytest.raises(PoolCaptured):
        main(["--start", f"{days[0]:%Y-%m-%d}", "--end", f"{days[-1]:%Y-%m-%d}"])

    assert sorted(seen) == sorted(UNIVERSE_CODES)
    assert set(captured["columns"]) == UNIVERSE_COMMON


def test_unit_weights_reproduce_equal_weight_exactly():
    """weights=None 必須就是原本的等權；全 1.0 的倍數也不能改變任何一位。"""
    piv = _piv()
    sig, f, yoy = _blank(piv)
    sig.iloc[10] = True
    base = simulate(piv, sig, f, yoy, 5, 5, "2026-01-05", "2026-02-20")
    ones = {(d, s): 1.0 for d in sig.index for s in sig.columns if sig.at[d, s]}
    same = simulate(piv, sig, f, yoy, 5, 5, "2026-01-05", "2026-02-20", weights=ones)
    pd.testing.assert_series_equal(base[0], same[0])
    pd.testing.assert_frame_equal(base[1], same[1])


def test_inverse_vol_weights_give_the_lower_vol_stock_the_larger_position():
    from portfolio_walkforward import invvol_weights

    piv = _piv()
    sig, f, yoy = _blank(piv)
    sig.iloc[10, :2] = True                   # 1111、2222 同日觸發
    d = sig.index[10]
    vol = pd.DataFrame(0.02, index=sig.index, columns=sig.columns)
    vol.loc[d, "1111"], vol.loc[d, "2222"], vol.loc[d, "3333"] = 0.01, 0.04, 0.02
    w = invvol_weights(sig, vol, ref="xs")    # 參考 = 當日中位 0.02
    assert w[(d, "1111")] == pytest.approx(2.0)
    assert w[(d, "2222")] == pytest.approx(0.5)
    _, tr, _, _ = simulate(piv, sig, f, yoy, 5, 5, "2026-01-05", "2026-02-20", weights=w)
    cost = tr.set_index("stock_id")["cost"]
    assert cost["1111"] > 3 * cost["2222"]    # 2.0 倍 vs 0.5 倍等權份額


def test_inverse_vol_weights_clip_wait_for_reference_and_default_missing_vol():
    from portfolio_walkforward import invvol_weights

    days = pd.bdate_range("2026-01-05", periods=4)
    cols = ["1111", "2222", "3333"]
    sig = pd.DataFrame(True, index=days, columns=cols)
    vol = pd.DataFrame([[0.01, 0.03, 0.30]] * 4, index=days, columns=cols)
    vol.iloc[3, 1] = float("nan")
    w = invvol_weights(sig, vol, ref="expanding", min_ref=6)
    assert {w[(days[0], s)] for s in cols} == {1.0}       # 只有 3 格，參考值還不可信
    assert w[(days[1], "1111")] == pytest.approx(2.0)     # 0.03/0.01=3 → 上限 2
    assert w[(days[1], "2222")] == pytest.approx(1.0)     # 未截斷的就是原比值
    assert w[(days[1], "3333")] == pytest.approx(0.5)     # 0.03/0.30=0.1 → 下限 0.5
    assert w[(days[3], "2222")] == 1.0                    # vol20 缺值 → 等權


def test_compare_weighting_reports_zero_difference_for_identical_arms(capsys):
    from portfolio_walkforward import compare_weighting

    piv = _piv(n=200)
    sig, f, yoy = _blank(piv)
    sig.iloc[10] = True
    eq, tr, _, cn = simulate(piv, sig, f, yoy, 5, 5, "2026-01-05", "2026-10-01")
    diff, ci = compare_weighting(eq, tr, cn, eq, tr, cn, "invvol", 20, 50, 42)
    assert (diff == 0).all() and ci == (0.0, 0.0)
    assert "平均持股比重" in capsys.readouterr().out
