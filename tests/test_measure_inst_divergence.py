# -*- coding: utf-8 -*-
"""scripts/measure_inst_divergence.py 的純函式（不碰 DB／網路）。

守的是會讓樣本外檢定無效、但程式照常結束的地方：法人 lag、宇宙內排名與平手、
臂的互斥、暖機歸零、同日超額、事先登記的判定分級。
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

import measure_inst_divergence as mid  # noqa: E402

DAYS = pd.bdate_range("2015-01-05", periods=30)


def _panel(values, cols=("1101", "2330")):
    return pd.DataFrame(values, index=DAYS[: len(values)], columns=list(cols), dtype=float)


def test_flow_uses_only_data_through_previous_session():
    # 只有第 i 天有一筆淨買超，其餘 0：window=3、lag=1 時，D 日看得到的是 D-3..D-1。
    net = pd.DataFrame(0.0, index=DAYS[:10], columns=["2330"])
    net.iloc[5, 0] = 100.0
    s = mid.flow_strength(net, None, "raw", window=3, lag=1)["2330"]
    assert s.iloc[5] == 0.0          # 當天的列還沒公布（lag 0 會是 100）
    assert s.iloc[6] == 100.0        # 隔天才看得到（lag 2 會是 0）
    assert s.iloc[8] == 100.0
    assert s.iloc[9] == 0.0          # 滾出 3 日窗口


def test_flow_is_nan_when_window_has_a_missing_row():
    net = pd.DataFrame(1.0, index=DAYS[:8], columns=["2330"])
    net.iloc[3, 0] = np.nan
    s = mid.flow_strength(net, None, "raw", window=3, lag=1)["2330"]
    assert s.iloc[4:7].isna().all()  # 含缺列的窗口不拿去排名
    assert s.iloc[7] == 3.0


def test_volume_norm_divides_by_window_volume_and_drops_zero_volume():
    net = pd.DataFrame(10.0, index=DAYS[:5], columns=["2330", "1101"])
    vol = pd.DataFrame({"2330": 100.0, "1101": 0.0}, index=DAYS[:5])
    s = mid.flow_strength(net, vol, "volume", window=2, lag=1)
    assert s["2330"].iloc[3] == pytest.approx(20.0 / 200.0)
    assert s["1101"].isna().all()    # 零成交量不產生 inf
    with pytest.raises(ValueError):
        mid.flow_strength(net, vol, "bogus")


def test_universe_requires_previous_session_institutional_row():
    close = _panel([[10, 10]] * 25)
    turnover = _panel([[3e8, 3e8]] * 25)
    present = _panel([[1, 1]] * 25).astype(bool)
    present.iloc[21, 0] = False      # 1101 第 21 天沒有法人列
    flow = _panel([[1.0, 1.0]] * 25)
    u = mid.build_universe(close, turnover, present, flow, flow, 2e8, lag=1)
    assert bool(u.iloc[21, 0])       # 當天缺列不影響（lag 1，用的是 D-1）
    assert not bool(u.iloc[22, 0])   # 隔天才因 D-1 缺列出宇宙
    assert bool(u.iloc[22, 1])
    assert not u.iloc[:19].any().any()   # 20 日均額未滿不算流動


def test_universe_excludes_illiquid_and_missing_flow():
    close = _panel([[10, 10]] * 22)
    turnover = _panel([[1e8, 3e8]] * 22)
    present = _panel([[1, 1]] * 22).astype(bool)
    flow = _panel([[1.0, np.nan]] * 22)
    u = mid.build_universe(close, turnover, present, flow, flow, 2e8)
    assert not u.any().any()


def test_rank_only_within_universe_and_ties_average_into_middle():
    cols = [f"{1100 + i}" for i in range(10)]
    flow = pd.DataFrame([[0, 0, 0, 0, 0, 0, 0, 0, -5, 9]], index=DAYS[:1], columns=cols, dtype=float)
    uni = pd.DataFrame(True, index=DAYS[:1], columns=cols)
    r = mid.cross_rank(flow, uni).iloc[0]
    assert r["1109"] > mid.TOP and r["1108"] <= mid.BOTTOM
    # 八個 0 平手取平均名次 → 中間帶；method="min" 會把它們全壓進後 20%
    assert all(mid.BOTTOM < r[c] <= mid.TOP for c in cols[:8])
    # 宇宙外的股票不參與排名、也不影響別人的名次
    uni2 = uni.copy()
    uni2["1109"] = False
    r2 = mid.cross_rank(flow, uni2).iloc[0]
    assert np.isnan(r2["1109"])
    assert r2["1108"] == pytest.approx(1 / 9)


def test_arms_are_mutually_exclusive_and_exhaustive():
    rng = np.random.default_rng(0)
    f = pd.DataFrame(rng.random((40, 30)), index=pd.bdate_range("2015-01-05", periods=40))
    t = pd.DataFrame(rng.random((40, 30)), index=f.index)
    f.iloc[0, 0] = np.nan
    arms = mid.classify(f, t)
    stack = sum(arms[k].astype(int) for k in mid.ARMS)
    assert (stack.to_numpy()[f.notna().to_numpy()] == 1).all()
    assert stack.iloc[0, 0] == 0
    assert (arms["分歧臂"] == ((f > .8) & (t <= .2))).all().all()
    assert (arms["鏡像臂"] == ((f <= .2) & (t > .8))).all().all()
    assert (arms["雙中間"] == ((f > .2) & (f <= .8) & (t > .2) & (t <= .8))).all().all()


def test_window_mask_zeroes_warmup_and_after_signal_end():
    sig = pd.DataFrame(True, index=DAYS[:10], columns=["2330"])
    out = mid.window_mask(sig, DAYS[3], DAYS[6])
    assert out["2330"].tolist() == [False] * 3 + [True] * 4 + [False] * 3
    assert sig.all().all()           # 不改呼叫端的面板


def test_same_day_excess_subtracts_signal_day_universe_mean():
    ev = pd.DataFrame({"date": [DAYS[1], DAYS[2], DAYS[3]], "r": [0.10, 0.05, 0.2]})
    day_mean = pd.Series([0.0, 0.02, -0.01, np.nan], index=DAYS[:4])
    out = mid.same_day_excess(ev, day_mean)
    assert out["diff"].iloc[0] == pytest.approx(0.08)
    assert out["diff"].iloc[1] == pytest.approx(0.06)
    assert np.isnan(out["diff"].iloc[2])


def test_net_panel_applies_shared_costs_only_to_universe_cells():
    from tw_trade_costs import round_trip_return

    ret = _panel([[0.10, 0.10]])
    uni = pd.DataFrame([[True, False]], index=ret.index, columns=ret.columns)
    out = mid.net_panel(ret, uni)
    assert out.iloc[0, 0] == pytest.approx(round_trip_return(
        1.0, 1.10, entry_notional=mid.DEFAULT_POSITION_NOTIONAL))
    assert out.iloc[0, 0] < 0.10
    assert np.isnan(out.iloc[0, 1])


def test_net_panel_keeps_total_loss_cells_like_arm_events():
    """`--delisting zero` 讓下市格 r=-1.0；基準必須和臂事件（to_events）一樣算進去。"""
    from measure_signal_forward import to_events

    ret = _panel([[-1.0, 0.10], [-1.0, -1.0]])
    uni = pd.DataFrame(True, index=ret.index, columns=ret.columns)
    out = mid.net_panel(ret, uni)
    for d in ret.index:  # 逐日跑 to_events，避開同檔 h 日內去重
        _, ev = to_events(uni.loc[[d]], ret.loc[[d]], 1, {})
        by_stock = ev.set_index("stock_id")["r"]
        for s in ret.columns:
            assert out.at[d, s] == pytest.approx(by_stock[s])
    day_mean = out.mean(axis=1)
    # 混合日：全損 + 漲 10% 的基準是負的，不是只剩 +10% 那格
    assert day_mean.iloc[0] < -0.4
    # 全損日：基準是有值的大額虧損，不是 NaN（否則當日事件被整批丟掉）
    assert not np.isnan(day_mean.iloc[1])
    assert day_mean.iloc[1] < -0.99


def test_net_panel_leaves_missing_returns_unmeasured():
    """反向檢查：宇宙內但報酬缺值的格維持 NaN，不能被補成 0 或全損。"""
    ret = _panel([[np.nan, 0.10]])
    uni = pd.DataFrame(True, index=ret.index, columns=ret.columns)
    out = mid.net_panel(ret, uni)
    assert np.isnan(out.iloc[0, 0])
    assert out.mean(axis=1).iloc[0] == pytest.approx(out.iloc[0, 1])


def _row(n, excess, mean, p30, ci):
    return {"事件": n, "超額%": excess, "均值%": mean, "P(≥30%)": p30, "_ci": ci}


@pytest.mark.parametrize("d,m,mid_row,expected", [
    (_row(300, 5, 20, 30, (.01, .1)), _row(300, 4, 20, 30, (.01, .1)), _row(900, -2, 0, 0, None), "通過"),
    (_row(300, 5, 20, 30, (.01, .1)), _row(300, -1, 20, 30, (.01, .1)), _row(900, -2, 0, 0, None), "封存"),
    (_row(300, 5, 20, 30, (.01, .1)), _row(300, 4, 20, 30, (.01, .1)), _row(900, 0.5, 0, 0, None), "封存"),
    (_row(300, 5, 20, 30, (-.01, .1)), _row(300, 4, 20, 30, (.01, .1)), _row(900, -2, 0, 0, None),
     "inconclusive（點估計"),
    (_row(80, 5, 20, 30, (.01, .1)), _row(300, 4, 20, 30, (.01, .1)), _row(900, -2, 0, 0, None),
     "inconclusive（事件數"),
    (_row(300, 5, 20, 5, (.01, .1)), _row(300, 4, 20, 30, (.01, .1)), _row(900, -2, 0, 0, None),
     "inconclusive（區間排除 0"),
])
def test_verdict_follows_preregistered_tiers(d, m, mid_row, expected):
    base = {"均值%": 10, "P(≥30%)": 10}
    got = mid.verdict({"分歧臂": d, "鏡像臂": m, "雙中間": mid_row}, base)
    assert got.startswith(expected)
