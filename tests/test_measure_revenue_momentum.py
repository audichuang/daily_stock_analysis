"""scripts/measure_revenue_momentum.py 的純計算部分：動能旗標、有效公告日、逐月差。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from measure_revenue_momentum import (  # noqa: E402
    candidate_yoy_frame,
    correct_pit_dates,
    effective_announce,
    month_diffs,
    revenue_features,
)


def _rv(revenues, yoys, start="2018-01-01", sid="1234", drop=()):
    months = pd.date_range(start, periods=len(revenues), freq="MS")
    df = pd.DataFrame({
        "stock_id": sid, "revenue_month": months, "revenue": revenues, "yoy": yoys,
        "mom": pd.Series(revenues, dtype=float).pct_change().mul(100).to_numpy(),
        "announce_date": months + pd.DateOffset(months=1) + pd.Timedelta(days=9),
    })
    return df.drop(index=list(drop)).reset_index(drop=True)


def _row(feat, month):
    return feat.loc[feat["revenue_month"] == pd.Timestamp(month)].iloc[0]


def test_decel_uses_prior_three_months_only():
    # 前三月 YoY 40/50/60（均 50），本月 20 → decel = -30；本月不能混進平均
    f = revenue_features(_rv([100] * 4, [40, 50, 60, 20]), decel_pp=20)
    r = _row(f, "2018-04-01")
    assert r["decel"] == -30
    assert r["decel_lt0"] == 1.0 and r["decel_le20"] == 1.0
    assert np.isnan(_row(f, "2018-03-01")["decel"])  # 歷史不足 3 月 → 未知，不是「沒降速」


def test_decel_threshold_is_inclusive_but_not_loose():
    f = revenue_features(_rv([100] * 5, [50, 50, 50, 35, 50]), decel_pp=20)
    r = _row(f, "2018-04-01")
    assert r["decel_lt0"] == 1.0 and r["decel_le20"] == 0.0  # -15pp 不算大幅降速


def test_month_gap_does_not_bridge():
    # 拿掉第 3 個月：第 4、5 月的 shift 不可把缺月前的資料當成上個月
    f = revenue_features(_rv([100] * 6, [40, 50, 60, 20, 30, 30], drop=(2,)), decel_pp=20)
    assert np.isnan(_row(f, "2018-04-01")["decel"])
    assert np.isnan(_row(f, "2018-06-01")["decel"])


def test_broken_record_streak_requires_two_prior_records():
    base = [100] * 24
    # 第 25、26 月連創新高，第 27 月未創高 → 斷創高
    f = revenue_features(_rv(base + [120, 130, 125], [10] * 27))
    assert _row(f, "2020-03-01")["broke_record_streak"] == 1.0
    # 只有一個月創高就回落 → 不算「連創高」被斷
    f = revenue_features(_rv(base + [100, 130, 125], [10] * 27))
    assert _row(f, "2020-03-01")["broke_record_streak"] == 0.0
    # 繼續創高 → 不算
    f = revenue_features(_rv(base + [120, 130, 140], [10] * 27))
    assert _row(f, "2020-03-01")["broke_record_streak"] == 0.0
    # 歷史不足 24 月 → 未知
    f = revenue_features(_rv([100] * 10 + [120, 130, 125], [10] * 13))
    assert np.isnan(_row(f, "2019-01-01")["broke_record_streak"])


def test_yoy_turn_negative():
    f = revenue_features(_rv([100] * 3, [5, -1, -2]))
    assert _row(f, "2018-02-01")["yoy_turn_neg"] == 1.0
    assert _row(f, "2018-03-01")["yoy_turn_neg"] == 0.0  # 已經是負的，不是「翻負」


def test_effective_announce_takes_later_of_placeholder_and_extension():
    rv = _rv([100] * 3, [1, 2, 3], start="2019-12-01")
    out = effective_announce(rv)
    got = dict(zip(out["revenue_month"], out["announce_date"]))
    assert got[pd.Timestamp("2020-01-01")] == pd.Timestamp("2020-02-15")  # 疫情展延
    assert got[pd.Timestamp("2019-12-01")] == pd.Timestamp("2020-01-10")  # 未展延維持佔位
    assert out["announce_date"].dtype == rv["announce_date"].dtype


def test_month_diffs_sign_and_missing_arm():
    df = pd.DataFrame({
        "month": pd.to_datetime(["2020-01-01"] * 4 + ["2020-02-01"] * 2),
        "f": [1.0, 1.0, 0.0, 0.0, 1.0, 1.0],
        "r": [-0.02, -0.04, 0.01, 0.03, 0.5, 0.5],
    })
    d = month_diffs(df, "f")
    assert list(d.index) == [pd.Timestamp("2020-01-01")]  # 2 月缺「無旗標」臂 → 不算
    assert np.isclose(d.iloc[0], -0.03 - 0.02)


def test_candidate_panel_uses_extended_deadline_not_placeholder():
    # 2020-01 營收展延到 2/15：候選池那份 yoy 面板不能用 DB 佔位日 2/10 提前看到
    rv = pd.DataFrame({
        "stock_id": ["2330", "2330", "2454"],
        "revenue_month": pd.to_datetime(["2020-01-01", "2020-02-01", "2020-01-01"]),
        "announce_date": pd.to_datetime(["2020-02-10", "2020-03-10", "2020-02-10"]),
        "yoy": [25.0, 30.0, None],
    })
    out = candidate_yoy_frame(effective_announce(rv))
    assert list(out.columns) == ["stock_id", "date", "yoy"]
    assert out["date"].tolist() == [pd.Timestamp("2020-02-15"), pd.Timestamp("2020-03-10")]


def test_correct_pit_dates_moves_only_the_extended_month():
    rv = pd.DataFrame({"stock_id": ["2330"] * 3,
                       "date": pd.to_datetime(["2020-02-10", "2020-03-10", "2026-10-10"]),
                       "yoy": [25.0, 30.0, 5.0]})
    out = correct_pit_dates(rv)
    assert out["date"].tolist() == [pd.Timestamp("2020-02-15"), pd.Timestamp("2020-03-10"),
                                    pd.Timestamp("2026-10-10")]
    assert rv["date"].iloc[0] == pd.Timestamp("2020-02-10")  # 不改到輸入
