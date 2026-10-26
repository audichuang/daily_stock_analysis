"""Taiwan stock cash-flow costs, including dividend-only NHI premium."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from tw_trade_costs import (  # noqa: E402
    ETF_TRANSACTION_TAX_RATE,
    STOCK_TRANSACTION_TAX_RATE,
    affordable_shares,
    broker_commission,
    buy_cash_outflow,
    buy_fill_price,
    dividend_supplementary_premium,
    round_trip_return,
    sell_cash_inflow,
    sell_fill_price,
)


def test_buy_and_sell_each_charge_broker_commission_and_sell_charges_tax():
    assert buy_cash_outflow(1_000, 100.0) == pytest.approx(100_142.5)
    assert sell_cash_inflow(1_000, 110.0) == pytest.approx(109_513.25)


def test_minimum_commission_is_applied_on_both_sides():
    assert buy_cash_outflow(10, 10.0) == pytest.approx(120.0)
    assert sell_cash_inflow(10, 10.0) == pytest.approx(79.7)


def test_round_trip_return_uses_cash_outflow_and_cash_inflow_not_flat_subtraction():
    entry = buy_fill_price(100)
    exit_ = sell_fill_price(110)
    expected = (exit_ * (1 - 0.001425 - 0.003)
                / (entry * (1 + 0.001425)) - 1)
    assert round_trip_return(
        100.0, 110.0, entry_notional=200_000, minimum_fee=0.0
    ) == pytest.approx(expected)


def test_nhi_supplementary_premium_belongs_to_eligible_dividend_payment_not_sale():
    assert dividend_supplementary_premium(19_999, enabled=True) == 0
    assert dividend_supplementary_premium(20_000, enabled=True) == pytest.approx(422.0)
    assert dividend_supplementary_premium(12_000_000, enabled=True) == pytest.approx(211_000.0)


def test_nhi_is_zero_when_account_is_exempt_or_model_is_not_explicitly_enabled():
    assert dividend_supplementary_premium(50_000) == 0
    assert dividend_supplementary_premium(50_000, enabled=True, exempt=True) == 0


def test_every_annualising_script_shares_one_trading_calendar():
    """同一條淨值曲線在兩支腳本裡印出不同 CAGR，讀者無從對帳。

    踩過：`backtest_screen` 用美股慣例 252、`portfolio_walkforward` 用 245，於是同一段
    0050 買進持有被報成 +29.37% 與 +28.44%。實測這份資料是 242.8 交易日/年。

    **斷言必須打在真正做年化的那行上，不能只比常數相等**——把 `TRADING_DAYS` 的別名留著、
    在計算處寫死 `/ 252` 的 mutation 會讓「常數相等」的測試照樣綠（獨立審查指出）。
    """
    import numpy as np
    import pandas as pd

    import portfolio_walkforward
    from tw_trade_costs import TRADING_DAYS_PER_YEAR

    assert TRADING_DAYS_PER_YEAR == 245

    # 手算期望值：490 個交易日 = 2 年（用 245），總報酬 +44% → 年化剛好 +20%
    n = 2 * TRADING_DAYS_PER_YEAR
    curve = pd.Series(np.linspace(1.0, 1.44, n),
                      index=pd.bdate_range("2020-01-01", periods=n))
    got = float(portfolio_walkforward.metrics(curve)["年化"].rstrip("%"))
    assert got == pytest.approx(20.0, abs=0.05), (
        f"年化 {got}%；若計算處寫死 252，2 年會被算成 {n / 252:.3f} 年、年化偏高")


def test_etf_sell_tax_is_a_third_of_the_stock_rate():
    """ETF（0050）賣方證交稅 0.1%、個股 0.3%。基準用錯稅率會系統性壓低 0050。"""
    assert ETF_TRANSACTION_TAX_RATE == pytest.approx(0.001)
    assert STOCK_TRANSACTION_TAX_RATE == pytest.approx(0.003)
    etf = sell_cash_inflow(1_000, 100.0, minimum_fee=0.0,
                           tax_rate=ETF_TRANSACTION_TAX_RATE)
    stock = sell_cash_inflow(1_000, 100.0, minimum_fee=0.0)
    assert etf - stock == pytest.approx(100_000 * 0.002)


def test_sell_cashflow_has_no_nhi_parameter_or_deduction():
    assert sell_cash_inflow(1_000, 100.0, minimum_fee=0.0) == pytest.approx(99_557.5)


@pytest.mark.parametrize("early,tax", [(False, 0.001), (True, 0.0)])
def test_daily_report_levels_share_bond_etf_tax_by_actual_exit_date(early, tax):
    import pandas as pd
    from backtest_daily_report_levels import buy_and_hold, simulate

    days = pd.to_datetime(["2026-12-31", "2027-01-04"])
    bars = pd.DataFrame({"date": days, "open": [100.0, 105.0], "high": [112.0, 112.0],
                         "low": [99.0, 104.0], "close": [110.0, 110.0]})
    adj = pd.DataFrame({"00679B": [1.0, 1.0]}, index=days)
    reports = pd.DataFrame([{"day": pd.Timestamp("2026-12-30"), "ideal_buy": 100.0,
                             "stop_loss": 90.0, "take_profit": 110.0, "operation_advice": "買進"}])
    trades = simulate("00679B", reports, bars, adj, 200_000, False,
                      same_day_tp=True, no_tp=not early, hold_days=1)
    assert len(trades) == 1
    assert trades[0]["exit_type"] == ("take_profit" if early else "time")
    shares = affordable_shares(200_000, buy_fill_price(100.0))
    cost = buy_cash_outflow(shares, buy_fill_price(100.0))
    expected = sell_cash_inflow(shares, sell_fill_price(110.0), tax_rate=tax) / cost - 1
    assert trades[0]["ret"] == pytest.approx(expected)
    held = bars.iloc[:1] if early else bars
    expected_hold = sell_cash_inflow(shares, 110.0, tax_rate=tax) / cost - 1
    assert buy_and_hold("00679B", held, adj, 200_000) == pytest.approx(expected_hold)


def test_invalid_cost_parameters_are_rejected_even_for_zero_amounts():
    with pytest.raises(ValueError, match="fee parameters"):
        broker_commission(0, fee_rate=-1)
    with pytest.raises(ValueError, match="fee parameters"):
        affordable_shares(100, 10, fee_discount=-1)
    with pytest.raises(ValueError, match="shares and price"):
        buy_cash_outflow(-1, 100)
    with pytest.raises(ValueError, match="shares and price"):
        sell_cash_inflow(1, -100)
    with pytest.raises(ValueError, match="exit_price"):
        round_trip_return(100, -1, entry_notional=200_000)
    with pytest.raises(ValueError, match="premium parameters"):
        dividend_supplementary_premium(0, rate=-1)
