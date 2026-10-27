"""scripts/research_macro_ladder.py 的純函式：07:30 資訊集對齊、夜盤契約選擇、訓練窗不前視、事件計數。"""

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from research_macro_ladder import (  # noqa: E402
    align_available,
    build_features,
    build_targets,
    drop_bad_ticks,
    incremental_r2,
    new_events,
    night_returns,
    onsets,
    rolling_oos,
    train_bounds,
)

# 2026-10-19 是週一；台股交易日週一～週五
TW = pd.DatetimeIndex(pd.bdate_range("2026-10-19", "2026-10-23"))


def _us(values_by_day):
    idx = pd.DatetimeIndex(pd.to_datetime(list(values_by_day)))
    return pd.Series(list(values_by_day.values()), index=idx, dtype=float)


def test_us_close_on_same_date_is_not_visible_at_0730():
    # 美股每天收盤值互不相同，才分辨得出 D、D−1、D−2
    us = _us({"2026-10-15": 1, "2026-10-16": 2, "2026-10-19": 3, "2026-10-20": 4,
              "2026-10-21": 5, "2026-10-22": 6, "2026-10-23": 7})
    got = align_available(TW, us, "us_close")
    # 週一 07:30 只看得到上週五（10-16）收盤；週二看得到週一；同日（台北隔天清晨才收）的值不可用
    assert got.tolist() == [2, 3, 4, 5, 6]


def test_us_alignment_is_not_over_lagged():
    # 反向：多推一天（用 D−2）會丟掉 07:30 已可得的美股收盤
    us = _us({"2026-10-16": 2, "2026-10-19": 3, "2026-10-20": 4})
    got = align_available(pd.DatetimeIndex(["2026-10-20", "2026-10-21"]), us, "us_close")
    assert got.tolist() == [3, 4]


def test_us_holiday_does_not_shift_by_row():
    # 美股週一休市：台股週二只看得到上週五，不能因為 shift(1) 拿到別的東西
    us = _us({"2026-10-16": 2, "2026-10-20": 4})
    got = align_available(TW, us, "us_close")
    # 週一、週二都只看得到上週五；週二的美股收盤到台股週三才可用
    assert got.tolist() == [2, 2, 4, 4, 4]


def test_fred_daily_waits_one_us_business_day():
    # DGS10 的 10-19（週一）值，保守視為 10-20 才上 FRED → 台股 10-21 才可用
    fred = _us({"2026-10-16": 4.0, "2026-10-19": 4.1})
    got = align_available(TW, fred, "next_us_bday")
    assert got.iloc[0] != got.iloc[0]  # 週一：10-16 的值週一（10-19）才 available，嚴格小於不成立
    assert got.tolist()[1:] == [4.0, 4.1, 4.1, 4.1]


def test_icsa_saturday_week_released_thursday_usable_friday():
    icsa = _us({"2026-10-10": 200_000, "2026-10-17": 250_000})
    got = align_available(TW, icsa, "icsa_thursday")
    # 10-17（週六）那週在 10-22（週四）美東早上公布 ＝ 台北週四晚上 → 週四 07:30 還看不到、週五才看得到
    assert got.tolist() == [200_000, 200_000, 200_000, 200_000, 250_000]


def test_new_events_counts_each_trigger_once_on_first_visible_day():
    flags = pd.Series([False, True, True, False],
                      index=pd.to_datetime(["2026-10-15", "2026-10-16", "2026-10-17", "2026-10-19"]))
    ev = new_events(TW, flags, "us_close")
    # 10-16、10-17 的觸發都在台股 10-19（週一）第一次可見，只算一次；10-19 的美股日不觸發
    assert ev.tolist() == [True, False, False, False, False]


def _tx(date, contract, session, volume, close=None, settle=None):
    return {"date": date, "contract": contract, "session": session, "open": close,
            "close": close, "settle": settle, "volume": volume}


def test_night_contract_is_chosen_from_previous_day_volume():
    d0, d1 = dt.date(2026, 10, 19), dt.date(2026, 10, 20)
    rows = [
        _tx(d0, "202610", "一般", 1000, close=100, settle=100),
        _tx(d0, "202611", "一般", 10, close=200, settle=200),
        _tx(d1, "202610", "盤後", 50, close=101),
        _tx(d1, "202611", "盤後", 5000, close=220),
        # d1 日盤（09:00 之後）換月：成交量轉到 202611，但這在 07:30 不可得
        _tx(d1, "202610", "一般", 10, close=101, settle=101),
        _tx(d1, "202611", "一般", 9000, close=221, settle=221),
    ]
    got = night_returns(rows, pd.DatetimeIndex([d0, d1]))
    assert np.isnan(got.iloc[0])
    assert got.iloc[1] == 101 / 100 - 1


def test_train_bounds_excludes_unresolved_targets():
    # R3（h=3）的第 s 列要到 s+2 收盤才知道：預測第 10 列只能用 s ≤ 7
    assert train_bounds(10, 3, 756) == (0, 8)
    assert train_bounds(10, 1, 756) == (0, 10)
    assert train_bounds(900, 1, 756) == (144, 900)


def test_rolling_oos_uses_only_resolved_rows():
    # 常數特徵 → 預測就是訓練窗 y 的平均；y＝列號，平均值直接揭露用到哪幾列
    n = 12
    X = np.ones((n, 1))
    y = np.arange(n, dtype=float)
    for h in (1, 3):
        pred, bench = rolling_oos(X, y, horizon=h, window=4, min_train=1)
        i = 9
        end = i - h + 1
        assert pred[i] == y[max(0, end - 4):end].mean()
        assert bench[i] == pred[i]


def test_targets_and_lagged_features_have_no_same_day_close():
    tw = pd.DataFrame({"open": [100, 101, 103, 102, 105, 104, 106],
                       "close": [101, 102, 102, 104, 104, 107, 105]},
                      index=pd.bdate_range("2026-10-12", periods=7), dtype=float)
    t = build_targets(tw)
    assert t["CO"].iloc[1] == 101 / 101 - 1
    assert t["OC"].iloc[2] == 102 / 103 - 1
    assert t["R3"].iloc[2] == 104 / 103 - 1     # open_t → close_{t+2}
    aligned = pd.DataFrame(1.0, index=tw.index, columns=[
        "SOX", "NDX", "SPX", "TSM", "DXY", "TWD", "BRENT", "HYG", "VIX", "DGS10", "DGS2", "ICSA_CHG"])
    f = build_features(tw, aligned, pd.Series(0.0, index=tw.index), pd.Series(0.0, index=tw.index))
    # 07:30 時台股最新收盤是 t−1
    assert f["tw_cc1"].iloc[3] == 102 / 102 - 1
    assert f["tw_oc1"].iloc[3] == 102 / 103 - 1


def test_drop_bad_ticks_uses_past_only():
    s = pd.Series([31.0, 31.1, 31.2, 1.8, 31.3, 31.2],
                  index=pd.bdate_range("2011-10-20", periods=6))
    clean, dropped = drop_bad_ticks(s, 0.05)
    assert dropped == [dt.date(2011, 10, 25)]
    assert len(clean) == 5


def test_onsets_and_incremental_r2():
    st = onsets([True, True, False, True, False, False, True], gap=3)
    assert np.isnan(st[1])
    assert st.tolist()[0] == 1 and st.tolist()[3] == 1 and st.tolist()[6] == 1
    rng = np.random.default_rng(0)
    y = rng.normal(size=200)
    r = incremental_r2(y, np.zeros(200), y * 0.5, np.zeros(200), block=10, n_boot=200)
    assert r["dr2"] > 0 and r["ci"][0] > 0
