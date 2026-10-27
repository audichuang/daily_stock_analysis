# -*- coding: utf-8 -*-
"""scripts/research_explore_queue.py 與 portfolio_walkforward 均線出場的純函式測試（不碰 DB／網路）。

守的是會讓探索性結論說謊的地方：選到的是輸家不是贏家、產業中位數只用合格股且小產業剔除、
均線出場「連續 N 日」的計數與隔日開盤成交、事先寫定的三項全勝判準。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from measure_signal_forward import factors  # noqa: E402
from portfolio_walkforward import ma_line, simulate, update_break_streak  # noqa: E402
import research_explore_queue as req  # noqa: E402
from research_explore_queue import (  # noqa: E402
    bottom_quantile, build_parser, industry_relative, overlaps_restricted, period_stats,
    rebalance_dates, reversal_periods, verdict,
)
from tw_trade_costs import round_trip_return, sell_fill_price  # noqa: E402


# ---------------------------------------------------------------- 產業相對、選股

def test_industry_relative_subtracts_the_same_day_industry_median():
    r = pd.Series({"1101": 0.01, "1102": 0.03, "1103": 0.05, "2301": -0.10, "2302": 0.00, "2303": 0.10})
    ind = pd.Series({"1101": "01", "1102": "01", "1103": "01", "2301": "23", "2302": "23", "2303": "23"})
    rel = industry_relative(r, ind, pd.Series(True, index=r.index), min_group=3)
    assert rel["1101"] == pytest.approx(-0.02)
    assert rel["1103"] == pytest.approx(0.02)
    assert rel["2301"] == pytest.approx(-0.10)
    assert rel["2302"] == pytest.approx(0.0)


def test_industry_relative_drops_small_industries_and_ineligible_names():
    """合格家數不足的產業整個剔除；不合格股不參與中位數（否則流動性差的股票會拉動基準）。"""
    r = pd.Series({"1101": 0.0, "1102": 0.02, "1103": 0.04, "1104": 0.50, "2301": -0.2, "2302": 0.1})
    ind = pd.Series({"1101": "01", "1102": "01", "1103": "01", "1104": "01", "2301": "23", "2302": "23"})
    elig = pd.Series({"1101": True, "1102": True, "1103": True, "1104": False,
                      "2301": True, "2302": True})
    rel = industry_relative(r, ind, elig, min_group=3)
    assert set(rel.index) == {"1101", "1102", "1103"}
    assert rel["1101"] == pytest.approx(-0.02)          # 中位數 0.02，不是含 1104 的 0.03


def test_industry_relative_ignores_names_without_industry():
    r = pd.Series({"1101": 0.0, "1102": 0.1, "1103": 0.2, "9999": -0.9})
    ind = pd.Series({"1101": "01", "1102": "01", "1103": "01"})
    rel = industry_relative(r, ind, pd.Series(True, index=r.index), min_group=3)
    assert "9999" not in rel.index


def test_bottom_quantile_picks_the_worst_relative_names():
    rel = pd.Series({"a": 0.3, "b": -0.4, "c": 0.0, "d": -0.1, "e": 0.2,
                     "f": 0.1, "g": -0.2, "h": 0.05, "i": 0.15, "j": -0.3})
    assert bottom_quantile(rel, 0.2) == ["b", "j"]
    assert bottom_quantile(rel, 0.01) == ["b"]           # 至少一檔
    assert bottom_quantile(pd.Series(dtype=float), 0.2) == []


def test_rebalance_dates_step_and_offset_do_not_overlap():
    idx = pd.bdate_range("2026-01-01", periods=20)
    d0 = rebalance_dates(idx, "2026-01-03", 5)
    assert d0[0] == pd.Timestamp("2026-01-05") and len(d0) == 4
    assert (np.diff(idx.get_indexer(d0)) == 5).all()
    assert rebalance_dates(idx, "2026-01-03", 5, offset=2)[0] == pd.Timestamp("2026-01-07")


def test_restricted_flag_uses_the_holding_window_not_the_signal_day():
    idx = pd.bdate_range("2025-03-25", periods=60)
    assert overlaps_restricted(idx, pd.Timestamp("2025-04-04"), 5)     # 訊號在前、持有窗碰到
    assert not overlaps_restricted(idx, pd.Timestamp("2025-03-27"), 5)
    assert overlaps_restricted(idx, pd.Timestamp("2025-05-22"), 5)
    assert not overlaps_restricted(idx, pd.Timestamp("2025-05-23"), 5)  # 持有從 5/26 起


def _reversal_panel():
    days = pd.bdate_range("2026-01-01", periods=40)
    cols = [f"110{i}" for i in range(6)] + ["0050"]
    close = pd.DataFrame(100.0, index=days, columns=cols)
    # 訊號日 days[25]：1100 過去 5 日 −10%（產業內最差），其餘 0%
    close.loc[days[21]:, "1100"] = 90.0
    close.loc[days[26]:, "1100"] = 99.0                  # 隔天反彈
    open_ = close.copy()
    open_.loc[days[26], "1100"] = 91.0                   # T+1 開盤買在 91
    close.loc[days[26]:, "0050"] = 101.0
    open_.loc[days[26], "0050"] = 100.0
    return {"close": close, "open": open_, "high": close.copy(), "volume": close * 0 + 1e4,
            "turnover": close * 0 + 3e8}, days


def test_reversal_period_buys_the_loser_at_next_open_and_charges_round_trip():
    piv, days = _reversal_panel()
    ind = pd.Series({f"110{i}": "01" for i in range(6)})
    df = reversal_periods(piv, ind, start=days[25], lookback=5, hold=5, q=0.2,
                          min_turnover=1e8, min_group=5)
    row = df.iloc[0]
    assert row["date"] == days[25] and row["n_pick"] == 1
    assert row["strat"] == pytest.approx(round_trip_return(1.0, 99.0 / 91.0, entry_notional=200_000.0))
    assert row["bench"] == pytest.approx(0.01)
    assert row["diff"] == pytest.approx(row["strat"] - 0.01)


def _suspend_at_exit_panel(resumes):
    """兩檔同產業輸家都被選中；1101 只在 T+h 那天停牌，``resumes`` 決定之後是否復牌。"""
    days = pd.bdate_range("2026-01-01", periods=40)
    cols = [f"110{i}" for i in range(6)] + ["0050"]
    close = pd.DataFrame(100.0, index=days, columns=cols)
    close.loc[days[21]:, ["1100", "1101"]] = 90.0       # 訊號日 days[25] 兩檔都是 −10%
    close.loc[days[26]:, ["1100", "1101"]] = 99.0
    close.loc[days[30], "1101"] = np.nan                # T+h（h=5）停牌
    if resumes:
        close.loc[days[31]:, "1101"] = 105.0            # 復牌第一個收盤與停牌前不同
    else:
        close.loc[days[30]:, "1101"] = np.nan           # 從此沒有成交價＝下市
    open_ = close.copy()
    open_.loc[days[26], ["1100", "1101"]] = 91.0
    close.loc[days[26]:, "0050"] = 101.0
    open_.loc[days[26], "0050"] = 100.0
    piv = {"close": close, "open": open_, "high": close.copy(), "volume": close * 0 + 1e4,
           "turnover": close * 0 + 3e8}
    return piv, days


@pytest.mark.parametrize("resumes", [True, False])
def test_reversal_pick_is_not_dropped_by_whether_it_resumes_after_exit_day(resumes):
    """訊號日選中的股票不能因「到期後有沒有復牌」這種未來資訊被剔除、改變當期權重。"""
    piv, days = _suspend_at_exit_panel(resumes)
    ind = pd.Series({f"110{i}": "01" for i in range(6)})
    df = reversal_periods(piv, ind, start=days[25], lookback=5, hold=5, q=0.34,
                          min_turnover=1e8, min_group=5)
    row = df.iloc[0]
    assert row["n_pick"] == 2
    # 復牌：用 T+h 之後第一個收盤（105）結算，不是停牌前的 99；下市：用最後收盤（99）結算
    exit_1101 = 105.0 if resumes else 99.0
    legs = [round_trip_return(1.0, x / 91.0, entry_notional=200_000.0) for x in (99.0, exit_1101)]
    assert row["strat"] == pytest.approx(np.mean(legs))
    assert row["n_deferred"] == (1 if resumes else 0)


def test_reversal_still_skips_a_pick_without_next_open():
    """T+1 沒有開盤價買不到，照事前規格不買（不能連進場價也往後補）。"""
    piv, days = _suspend_at_exit_panel(True)
    piv["open"].loc[days[26], "1101"] = np.nan
    ind = pd.Series({f"110{i}": "01" for i in range(6)})
    df = reversal_periods(piv, ind, start=days[25], lookback=5, hold=5, q=0.34,
                          min_turnover=1e8, min_group=5)
    assert df.iloc[0]["n_pick"] == 1


def test_readonly_engine_sets_read_only_as_a_connection_option(monkeypatch):
    """唯讀要在連線參數生效：connect 事件裡 SET 會落在隱式交易內，還池 rollback 就撤銷。"""
    seen = {}

    def fake_create_engine(url, **kw):
        seen["url"], seen["kw"] = url, kw
        return object()

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@127.0.0.1:1/x")
    monkeypatch.setattr(req, "create_engine", fake_create_engine)
    req._readonly_engine()
    assert seen["url"] == "postgresql+psycopg2://u:p@127.0.0.1:1/x"
    opts = seen["kw"]["connect_args"]["options"].split()
    assert "default_transaction_read_only=on" in opts
    assert opts[opts.index("default_transaction_read_only=on") - 1] == "-c"


# ---------------------------------------------------------------- 判準與統計

def test_period_stats_drawdown_and_sharpe():
    st = period_stats([0.10, -0.50, 0.20], 1)
    assert st["mdd"] == pytest.approx(-0.5)
    assert st["total"] == pytest.approx(1.1 * 0.5 * 1.2 - 1)
    assert period_stats([0.1], 1)["sharpe"] != period_stats([0.1], 1)["sharpe"]   # NaN


@pytest.mark.parametrize("mean,ci,s,expected", [
    (0.01, (0.001, 0.02), {"sharpe": 1.5, "mdd": -0.2}, "探索性支持"),
    (0.01, (-0.001, 0.02), {"sharpe": 1.5, "mdd": -0.2}, "inconclusive"),
    (0.01, None, {"sharpe": 1.5, "mdd": -0.2}, "inconclusive"),
    (0.01, (0.001, 0.02), {"sharpe": 1.0, "mdd": -0.2}, "不支持"),     # Sharpe 輸
    (0.01, (0.001, 0.02), {"sharpe": 1.5, "mdd": -0.4}, "不支持"),     # 回撤較深
    (0.01, (0.001, 0.02), {"sharpe": 1.2, "mdd": -0.2}, "不支持"),     # Sharpe 平手不算贏
    (-0.01, (-0.02, -0.001), {"sharpe": 1.5, "mdd": -0.2}, "不支持"),
    # 區間跨零一律 inconclusive（AGENTS §1.2），不因 Sharpe／MDD 點估計輸就判不支持：B 主規格的數字
    (0.000469, (-0.000429, 0.001407), {"sharpe": 1.13, "mdd": -0.556}, "inconclusive"),
    (-0.0001, (-0.001, 0.0008), {"sharpe": 1.0, "mdd": -0.4}, "inconclusive"),
    (0.01, None, {"sharpe": 1.0, "mdd": -0.4}, "inconclusive"),           # 算不出區間
])
def test_verdict_requires_all_three_wins(mean, ci, s, expected):
    assert verdict(mean, ci, s, {"sharpe": 1.2, "mdd": -0.3}) == expected


def test_cli_has_both_experiments_and_help_does_not_touch_the_database(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "reversal" in out and "ma-exit" in out


# ---------------------------------------------------------------- 均線出場（portfolio_walkforward）

def test_break_streak_counts_resets_and_skips_missing_days():
    assert update_break_streak(0, 9.0, 10.0) == 1
    assert update_break_streak(2, 9.0, 10.0) == 3
    assert update_break_streak(2, 10.0, 10.0) == 0            # 收在均線上（含等於）歸零
    assert update_break_streak(2, np.nan, 10.0) == 2          # 停牌不計數也不歸零
    assert update_break_streak(2, 9.0, np.nan) == 2


def test_ma_line_does_not_bridge_missing_quotes():
    close = pd.DataFrame({"1111": [1.0, 2.0, np.nan, 4.0, 5.0, 6.0]})
    ma = ma_line(close, 3)
    assert ma["1111"].isna().tolist() == [True, True, True, True, True, False]


def _one_stock(n=40):
    days = pd.bdate_range("2026-01-01", periods=n)
    close = pd.DataFrame({"1111": [100.0 + i for i in range(n)]}, index=days)
    open_ = close - 0.5
    piv = {"close": close, "open": open_, "high": close.copy(), "volume": close * 0 + 1000,
           "turnover": close * 0 + 3e8}
    sig = pd.DataFrame(False, index=days, columns=close.columns)
    sig.iloc[2] = True                                        # 第 3 天訊號、第 4 天開盤買
    f = factors(piv, 1e8)
    yoy = pd.DataFrame(30.0, index=days, columns=close.columns)
    return piv, sig, f, yoy, days


def _ma_below_from(days, close, first_below):
    """從 ``first_below`` 那天起收盤都在均線下，之前都在上。"""
    ma = close - 1.0
    ma.loc[days[first_below]:] = close.loc[days[first_below]:] + 1.0
    return ma


def test_ma_exit_sells_at_next_open_after_sustained_break():
    piv, sig, f, yoy, days = _one_stock()
    ma = _ma_below_from(days, piv["close"], 10)               # 第 10、11、12 天連三日跌破
    eq, tr, _, _ = simulate(piv, sig, f, yoy, 30, 1, days[1], days[-1], exit_ma=(ma, 3))
    assert len(tr) == 1
    t = tr.iloc[0]
    assert t["exit_reason"] == "ma"
    assert t["exit_date"] == days[13]                          # 第 12 天收盤成立 → 第 13 天開盤賣
    assert t["exit"] == pytest.approx(sell_fill_price(float(piv["open"].at[days[13], "1111"])))


def test_ma_exit_break_must_be_consecutive():
    piv, sig, f, yoy, days = _one_stock()
    ma = _ma_below_from(days, piv["close"], 10)
    ma.loc[days[11]] = piv["close"].loc[days[11]] - 1.0      # 第 11 天站回 → 從第 12 天重數
    _, tr, _, _ = simulate(piv, sig, f, yoy, 30, 1, days[1], days[-1], exit_ma=(ma, 3))
    assert tr.iloc[0]["exit_date"] == days[15]


def test_ma_exit_keeps_the_time_cap_unless_disabled():
    piv, sig, f, yoy, days = _one_stock()
    never = piv["close"] - 1.0                                # 永遠在均線上
    _, tr, _, _ = simulate(piv, sig, f, yoy, 10, 1, days[1], days[-1], exit_ma=(never, 3))
    assert tr.iloc[0]["exit_reason"] == "time" and tr.iloc[0]["exit_date"] == days[12]
    _, tr2, _, cn = simulate(piv, sig, f, yoy, 10, 1, days[1], days[-1], exit_ma=(never, 3),
                             time_cap=False)
    assert len(tr2) == 0 and cn["open_at_end"] == 1


def test_untriggered_ma_exit_reproduces_the_fixed_horizon_run_exactly():
    piv, sig, f, yoy, days = _one_stock()
    never = piv["close"] - 1.0
    eq0, tr0, _, _ = simulate(piv, sig, f, yoy, 10, 1, days[1], days[-1])
    eq1, tr1, _, _ = simulate(piv, sig, f, yoy, 10, 1, days[1], days[-1], exit_ma=(never, 3))
    pd.testing.assert_series_equal(eq0, eq1)
    pd.testing.assert_frame_equal(tr0, tr1)


def test_ma_exit_defers_when_next_open_is_missing():
    piv, sig, f, yoy, days = _one_stock()
    ma = _ma_below_from(days, piv["close"], 10)
    piv["open"].loc[days[13], "1111"] = np.nan                # 隔日沒有開盤價 → 順延
    eq, tr, _, _ = simulate(piv, sig, f, yoy, 30, 1, days[1], days[-1], exit_ma=(ma, 3))
    t = tr.iloc[0]
    assert t["exit_date"] == days[14] and t["exit_reason"] == "ma"
    assert t["exit"] == pytest.approx(sell_fill_price(float(piv["open"].at[days[14], "1111"])))
