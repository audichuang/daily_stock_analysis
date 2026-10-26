"""scripts/backtest_daily_report_levels.py 的證交稅：依代號與賣出日（債券 ETF 停徵有期限）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import backtest_daily_report_levels as bdl  # noqa: E402
from tw_trade_costs import (  # noqa: E402
    affordable_shares,
    buy_cash_outflow,
    buy_fill_price,
    sell_cash_inflow,
    sell_fill_price,
)


def _pos():
    return {"entry_date": pd.Timestamp("2026-06-01"), "entry_raw": 100.0, "entry_adj": 1.0,
            "shares": 1_000.0, "cost": 100_000.0, "bars": 0, "stop": None, "tp": None}


@pytest.mark.parametrize("stock_id,exit_day,tax", [
    ("00679B", "2026-12-31", 0.0),      # 停徵迄日當天賣出：免稅
    ("00679B", "2027-01-04", 0.001),    # 停徵期後：ETF 稅率，不是永久免稅
    ("00680L", "2026-06-02", 0.001),    # 槓桿型債券 ETF 不適用停徵
    ("2330", "2026-06-02", 0.003),
])
def test_close_charges_tax_by_stock_and_sale_date(stock_id, exit_day, tax):
    trade = bdl._close(stock_id, _pos(), pd.Timestamp(exit_day), 110.0, 1.0, "time")
    expected = sell_cash_inflow(1_000.0, sell_fill_price(110.0), tax_rate=tax)
    assert trade["pnl"] == pytest.approx(expected - 100_000.0)


@pytest.mark.parametrize("early,tax", [(False, 0.001), (True, 0.0)])
def test_simulate_and_buy_and_hold_use_actual_exit_date(early, tax):
    # 跨停徵迄日：12/31 停利出場免稅；持到 2027 才出場課 ETF 0.1%
    days = pd.to_datetime(["2026-12-31", "2027-01-04"])
    bars = pd.DataFrame({"date": days, "open": [100.0, 105.0], "high": [112.0, 112.0],
                         "low": [99.0, 104.0], "close": [110.0, 110.0]})
    adj = pd.DataFrame({"00679B": [1.0, 1.0]}, index=days)
    reports = pd.DataFrame([{"day": pd.Timestamp("2026-12-30"), "ideal_buy": 100.0,
                             "stop_loss": 90.0, "take_profit": 110.0, "operation_advice": "買進"}])
    trades = bdl.simulate("00679B", reports, bars, adj, 200_000, False,
                          same_day_tp=True, no_tp=not early, hold_days=1)
    assert len(trades) == 1
    assert trades[0]["exit_type"] == ("take_profit" if early else "time")
    shares = affordable_shares(200_000, buy_fill_price(100.0))
    cost = buy_cash_outflow(shares, buy_fill_price(100.0))
    expected = sell_cash_inflow(shares, sell_fill_price(110.0), tax_rate=tax) / cost - 1
    assert trades[0]["ret"] == pytest.approx(expected)
    held = bars.iloc[:1] if early else bars
    expected_hold = sell_cash_inflow(shares, 110.0, tax_rate=tax) / cost - 1
    assert bdl.buy_and_hold("00679B", held, adj, 200_000) == pytest.approx(expected_hold)
