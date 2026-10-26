"""Taiwan stock cash-flow costs, including dividend-only NHI premium."""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

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
    per_share_cost_multipliers,
    round_trip_return,
    sell_cash_inflow,
    sell_fill_price,
    tw_sell_tax_rate,
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


# 債券 ETF 證交稅停徵：《證券交易稅條例》第 2 條之 1，106/01/01～115/12/31（含首尾）；
# 槓桿／反向債券 ETF 不適用。期待值獨立寫死，不讀被測模組的常數。
@pytest.mark.parametrize("stock_id,sale_date,expected", [
    ("00679B", date(2026, 6, 30), 0.0),          # 停徵期內
    ("00679B.TWO", date(2017, 1, 1), 0.0),       # 起日當天（含後綴也認得）
    ("00937B", date(2026, 12, 31), 0.0),         # 迄日當天
    ("00679B", date(2027, 1, 1), 0.001),         # 停徵期後：不是永久免稅
    ("00679B", date(2016, 12, 31), 0.001),       # 停徵期前
    ("00680L", date(2026, 6, 30), 0.001),        # 槓桿型債券 ETF 不適用
    ("00681R", date(2026, 6, 30), 0.001),        # 反向型債券 ETF 不適用
    ("0050", date(2026, 6, 30), 0.001),
    ("00631L", date(2026, 6, 30), 0.001),
    ("2330", date(2026, 6, 30), 0.003),
    ("2887A", date(2026, 6, 30), 0.003),         # 特別股：A 結尾但不是 00 開頭
])
def test_tw_sell_tax_rate_bond_etf_exemption_is_date_bounded(stock_id, sale_date, expected):
    assert tw_sell_tax_rate(stock_id, sale_date) == pytest.approx(expected)


def test_tw_sell_tax_rate_accepts_datetime_like_sale_date():
    import pandas as pd

    assert tw_sell_tax_rate("00679B", pd.Timestamp("2026-12-31 13:30")) == 0.0
    assert tw_sell_tax_rate("00679B", datetime(2027, 1, 1, 9, 0)) == pytest.approx(0.001)


def test_per_share_cost_multipliers_explicit_tax_rate_overrides_is_etf():
    buy, sell = per_share_cost_multipliers(tax_rate=0.0)
    assert buy == pytest.approx((1 + 0.0015) * (1 + 0.001425))
    assert sell == pytest.approx((1 - 0.0015) * (1 - 0.001425))
    # 沒給 tax_rate 時沿用 is_etf 舊行為
    assert per_share_cost_multipliers(is_etf=True)[1] == pytest.approx((1 - 0.0015) * (1 - 0.001425 - 0.001))
    with pytest.raises(ValueError):
        per_share_cost_multipliers(tax_rate=-0.001)
