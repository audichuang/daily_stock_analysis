"""scripts/measure_revenue_momentum.py 的純計算部分：動能旗標、有效公告日、逐月差。"""

from __future__ import annotations

import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import measure_revenue_momentum as revmom  # noqa: E402
from measure_revenue_momentum import (  # noqa: E402
    FLAGS,
    candidate_yoy_frame,
    correct_pit_dates,
    effective_announce,
    fmt_row,
    month_diffs,
    pit_revenue_panel,
    pool_exit_rows,
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
    assert got[pd.Timestamp("2020-01-01")] == pd.Timestamp("2020-02-17")  # 疫情展延與週末順延
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
    assert out["date"].tolist() == [pd.Timestamp("2020-02-17"), pd.Timestamp("2020-03-10")]


def test_correct_pit_dates_applies_extension_and_weekend_roll():
    rv = pd.DataFrame({"stock_id": ["2330"] * 3,
                       "date": pd.to_datetime(["2020-02-10", "2020-03-10", "2026-10-10"]),
                       "yoy": [25.0, 30.0, 5.0]})
    out = correct_pit_dates(rv)
    assert out["date"].tolist() == [pd.Timestamp("2020-02-17"), pd.Timestamp("2020-03-10"),
                                    pd.Timestamp("2026-10-12")]
    assert rv["date"].iloc[0] == pd.Timestamp("2020-02-10")  # 不改到輸入


def test_correct_pit_dates_moves_2026_financial_stock_to_15th():
    rv = pd.DataFrame({
        "stock_id": ["2881", "2330", "5880", "2881"],
        "date": pd.to_datetime(["2026-04-10", "2026-04-10", "2026-02-10", "2025-12-10"]),
        "yoy": [10.0, 20.0, 15.0, 12.0],
    })
    out = correct_pit_dates(rv)
    assert out["date"].tolist() == [
        pd.Timestamp("2026-04-15"),
        pd.Timestamp("2026-04-10"),
        pd.Timestamp("2026-02-23"),
        pd.Timestamp("2025-12-10"),
    ]


def _exit_inputs(releases):
    days = pd.bdate_range("2026-04-01", periods=60)
    cols = pd.Index(["2330.TW", "2454.TW", "00631L.TW"])
    open_ = pd.DataFrame(
        np.arange(len(days) * len(cols)).reshape(len(days), len(cols)) + 100.0,
        index=days, columns=cols,
    )
    piv = {"open": open_, "close": open_ + 10.0}
    feat = pd.DataFrame(releases, columns=["stock_id", "announce_date", "flag"])
    feat["announce_date"] = pd.to_datetime(feat["announce_date"])
    panels = {f: pit_revenue_panel(
        feat.rename(columns={"announce_date": "date", "flag": "yoy"}).dropna(), days, cols,
    ) for f in FLAGS}
    panels["_ann"] = feat.set_index("stock_id")["announce_date"].dropna()
    return panels, piv


def test_pool_exit_rows_uses_only_held_stocks_own_releases():
    panels, piv = _exit_inputs([
        ("2330.TW", "2026-04-10", 1.0),
        ("2454.TW", "2026-04-15", 0.0),
        ("2454.TW", None, 0.0),
    ])
    ev = pd.DataFrame({"ti": [0, 0, 0], "stock_id": piv["close"].columns})

    out = pool_exit_rows(ev, panels, piv, 40, SimpleNamespace())

    assert out["stock_id"].tolist() == ["2330.TW", "2454.TW"]
    assert out["month"].tolist() == [pd.Timestamp("2026-04-01")] * 2
    for row, sid, entry in zip(out.itertuples(), ["2330.TW", "2454.TW"],
                               ["2026-04-14", "2026-04-17"]):
        assert row.r == pytest.approx(piv["close"].iloc[40][sid] / piv["open"].loc[entry, sid] - 1)
        assert all(getattr(row, f) == float(sid == "2330.TW") for f in FLAGS)


def test_pool_exit_rows_deduplicates_visible_day_but_keeps_genuine_releases():
    panels, piv = _exit_inputs([
        ("2330.TW", "2026-04-10", 1.0),
        ("2330.TW", "2026-04-10", 1.0),
        ("2330.TW", "2026-04-11", 1.0),  # 週末公告與週五公告同在週一可見
        ("2330.TW", "2026-04-20", 1.0),  # 同月、同旗標，仍是新的公布
        ("2330.TW", "2026-05-15", 0.0),
        ("2454.TW", "2026-04-20", 0.0),  # 同日的另一檔也必須保留
    ])
    ev = pd.DataFrame({"ti": [0, 0], "stock_id": ["2330.TW", "2454.TW"]})

    out = pool_exit_rows(ev, panels, piv, 40, SimpleNamespace())

    assert out["stock_id"].tolist() == ["2330.TW"] * 3 + ["2454.TW"]
    assert out["month"].tolist() == pd.to_datetime([
        "2026-04-01", "2026-04-01", "2026-05-01", "2026-04-01",
    ]).tolist()
    for f in FLAGS:
        assert out[f].tolist() == [1.0, 1.0, 0.0, 0.0]
    entries = ["2026-04-14", "2026-04-22", "2026-05-19", "2026-04-22"]
    expected = [piv["close"].iloc[40][sid] / piv["open"].loc[d, sid] - 1
                for sid, d in zip(out["stock_id"], entries)]
    assert out["r"].tolist() == pytest.approx(expected)


@pytest.mark.parametrize("releases", [
    [("2454.TW", "2026-04-15", 0.0)],
    [("2330.TW", None, 1.0)],
    [("2330.TW", "2026-03-30", 1.0), ("2330.TW", "2026-05-26", 0.0),
     ("2330.TW", "2026-07-01", 1.0)],
])
def test_pool_exit_rows_with_no_eligible_own_release_can_still_be_summarized(releases):
    panels, piv = _exit_inputs(releases)
    ev = pd.DataFrame({"ti": [0], "stock_id": ["2330.TW"]})

    out = pool_exit_rows(ev, panels, piv, 40, SimpleNamespace())

    assert out.empty
    assert list(out.columns) == ["stock_id", "month", "r", *FLAGS]
    for f in FLAGS:
        summary = fmt_row("持有中", out, f, pd.DatetimeIndex([]), SimpleNamespace(bootstrap=0))
        assert summary["n旗標"] == summary["n無"] == summary["月數"] == 0
        assert summary["判定"] == "inconclusive"


def test_main_retains_stock_identity_for_exit_release_dates(monkeypatch):
    days = pd.bdate_range("2026-04-01", periods=60)
    cols = pd.Index(["2330", "2454"])
    prices = pd.DataFrame(100.0, index=days, columns=cols)
    piv = {k: prices.copy() for k in ("open", "high", "close", "volume", "turnover")}
    rv = pd.concat([
        _rv([100] * 6, [40, 40, 40, 20, 30, 40], start="2025-12-01", sid=s)
        for s in cols
    ], ignore_index=True)
    rv.loc[rv["stock_id"] == "2454", "announce_date"] += pd.Timedelta(days=5)
    sig = pd.DataFrame(False, index=days, columns=cols)
    sig.iloc[0] = True
    monkeypatch.setattr(revmom, "database_url", lambda: "unused")
    engine = SimpleNamespace(connect=lambda: nullcontext(object()))
    monkeypatch.setattr(revmom, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(revmom, "load", lambda *args: (piv, None, None))
    monkeypatch.setattr(revmom.pd, "read_sql", lambda *args, **kwargs: rv.copy())
    monkeypatch.setattr(revmom, "build_signals", lambda *args: (
        sig, {"liquid": pd.DataFrame(True, index=days, columns=cols)},
    ))
    actual_pool_exit_rows = revmom.pool_exit_rows
    observed = []

    def capture_exit_rows(*args):
        out = actual_pool_exit_rows(*args)
        observed.append(out)
        return out

    monkeypatch.setattr(revmom, "pool_exit_rows", capture_exit_rows)

    assert revmom.main([
        "--start", "2026-03-31", "--end", "2026-06-23", "--horizons", "5",
        "--pool-hold", "40", "--bootstrap", "0",
    ]) == 0
    assert len(observed) == 1
    assert observed[0]["stock_id"].value_counts().to_dict() == {"2330": 2, "2454": 2}
