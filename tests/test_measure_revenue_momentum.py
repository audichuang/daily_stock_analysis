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


def test_pool_exit_rows_reads_flag_at_own_visible_day_not_other_stocks():
    """旗標面板值＝列號，可追出每列讀的是哪個可見日；別檔公告日不能替持股多生一列。"""
    idx = pd.bdate_range("2020-03-02", periods=30)
    cols = pd.Index(["2330.TW", "2454.TW"])
    rown = np.arange(len(idx), dtype=float)[:, None].repeat(len(cols), axis=1)
    piv = {"open": pd.DataFrame(rown + 10, index=idx, columns=cols),
           "close": pd.DataFrame(rown + 20, index=idx, columns=cols)}
    panels = {f: pd.DataFrame(rown, index=idx, columns=cols) for f in FLAGS}
    # 2330：第 5、12 列公告；2454 在第 8 列公告；2330 第 25 列公告已超過出場日
    panels["_ann"] = pd.Series([idx[5], idx[12], idx[8], idx[25]],
                               index=["2330.TW", "2330.TW", "2454.TW", "2330.TW"])
    ev = pd.DataFrame({"ti": [2], "stock_id": ["2330.TW"]})

    out = pool_exit_rows(ev, panels, piv, 20, SimpleNamespace())  # 出場列 22

    assert (out["stock_id"] == "2330.TW").all()
    for f in FLAGS:
        assert out[f].tolist() == [6.0, 13.0]
    # 進場＝可見日隔日開盤（列 7／14），出場＝第 22 列收盤
    assert out["r"].tolist() == pytest.approx([42 / 17 - 1, 42 / 24 - 1])


# ---- 研究宇宙：量測母體必須走共用的 `is_common_stock` -------------------------------------
UNIVERSE_CODES = ["2330", "6488", "5305", "9802", "9904", "9921", "9105", "912000",
                  "00878", "0050", "00631L", "2887A", "70001"]
UNIVERSE_COMMON = {"2330", "6488", "5305", "9802", "9904", "9921"}


def test_main_filters_every_panel_with_the_shared_universe(monkeypatch):
    """退回 `startswith("00")` 會讓 TDR／特別股進母體；擋太寬（整個 9 開頭）會誤殺普通股。"""
    from market_data.adjust import is_common_stock

    days = pd.bdate_range("2026-04-01", periods=10)
    prices = pd.DataFrame(100.0, index=days, columns=UNIVERSE_CODES)
    piv = {k: prices.copy() for k in ("open", "high", "close", "volume", "turnover")}
    rv = _rv([100] * 6, [40, 40, 40, 20, 30, 40], start="2025-12-01", sid="2330")
# --- --experiment surprise：SUS、營收÷歷史最高、閘門與判準 ---

def _seasonal_series(diffs, tail_d):
    """前 12 月 100，之後 R_m = R_{m-12} + d_m；最後一個月的 d 是 tail_d。"""
    rev = [100.0] * 12
    for i, d in enumerate(list(diffs) + [tail_d]):
        rev.append(rev[i] + d)
    return rev


def test_sus_uses_prior_24_seasonal_diffs_with_drift():
    rev = _seasonal_series([10, 20] * 12, 30)          # 第 37 月（2021-01）d=30
    f = revmom.revenue_surprise_features(_rv(rev, [10.0] * len(rev)))
    expected = (30 - 15) / np.std([10, 20] * 12, ddof=1)
    assert _row(f, "2021-01-01")["sus"] == pytest.approx(expected)


def test_sus_min_periods_is_exactly_eighteen():
    # 第 12 月起才有季節差：第 30 月（index 30）之前有 18 個有效 d、第 29 月只有 17 個
    rev = _seasonal_series([10, 20] * 9, 30)            # index 30 = 2020-07
    f = revmom.revenue_surprise_features(_rv(rev, [10.0] * len(rev)))
    assert not np.isnan(_row(f, "2020-07-01")["sus"])
    assert np.isnan(_row(f, "2020-06-01")["sus"])       # 17 個 → 未知


def test_sus_does_not_bridge_missing_month():
    rev = _seasonal_series([10, 20] * 12, 30)
    f = revmom.revenue_surprise_features(_rv(rev, [10.0] * len(rev), drop=(24,)))
    assert np.isnan(_row(f, "2021-01-01")["sus"])        # 上年同月（2020-01）被拿掉
    assert not np.isnan(_row(f, "2020-12-01")["sus"])    # 其他月份不受影響


def test_sus_pit_uses_reported_yoy_not_stored_prior_year_level():
    # 入庫的上年同月被事後改大（季節差全 0），但當時公告的 YoY 是 20% → d_pit = R·20/120
    rev = [100.0] * 37
    yoy = [0.0, 0.0] * 18 + [20.0]
    yoy[12:36] = [5.0, 10.0] * 12
    f = revmom.revenue_surprise_features(_rv(rev, yoy))
    r = _row(f, "2021-01-01")
    assert np.isnan(r["sus"])                             # 入庫水準：季節差 std=0 → 未知
    d_hist = [100 * y / (100 + y) for y in [5.0, 10.0] * 12]
    expected = (100 * 20 / 120 - np.mean(d_hist)) / np.std(d_hist, ddof=1)
    assert r["sus_pit"] == pytest.approx(expected)


def test_sus_pit_is_nan_when_yoy_is_minus_hundred():
    rev = [100.0] * 37
    yoy = [5.0, 10.0] * 18 + [-100.0]
    f = revmom.revenue_surprise_features(_rv(rev, yoy))
    assert np.isnan(_row(f, "2021-01-01")["sus_pit"])


def test_ath_ratio_needs_24_months_and_uses_prior_max_only():
    rev = [100.0] * 23 + [150.0, 120.0, 180.0]
    f = revmom.revenue_surprise_features(_rv(rev, [10.0] * len(rev)))
    assert np.isnan(_row(f, "2019-12-01")["ath_ratio"])  # 只有 23 個月歷史
    assert _row(f, "2020-01-01")["ath_ratio"] == pytest.approx(120 / 150)
    assert _row(f, "2020-02-01")["ath_ratio"] == pytest.approx(180 / 150)  # 不含自己


def test_gate_flags_top_quintile_is_strict_and_per_month():
    m1, m2 = pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01")
    feat = pd.DataFrame({
        "stock_id": [f"{1000 + i}" for i in range(10)] * 2 + ["9999"],
        "revenue_month": [m1] * 10 + [m2] * 10 + [m2],
        "announce_date": [m1 + pd.Timedelta(days=40)] * 10 + [m2 + pd.Timedelta(days=40)] * 11,
        "sus": list(range(1, 11)) + list(range(110, 100, -1)) + [np.nan],  # 兩月水準不同
        "sus_pit": 0.0, "ath_ratio": [0.99, 1.0] * 10 + [np.nan],
    })
    g = revmom.gate_flags(feat)
    jan = g[g["revenue_month"] == m1].set_index("stock_id")["sus_top20"]
    assert jan[jan == 1].index.tolist() == ["1008", "1009"]   # 百分位 0.9、1.0；0.8 不算；不跨月混排
    feb = g[g["revenue_month"] == m2].set_index("stock_id")["sus_top20"]
    assert feb[feb == 1].index.tolist() == ["1000", "1001"]   # 各月各自排名
    assert np.isnan(feb["9999"])                               # 缺值不是「不通過」
    assert g["ath_ge1"].iloc[:2].tolist() == [0.0, 1.0]       # 絕對門檻含等號


def test_gate_panels_follow_revenue_pit_visibility():
    days = pd.bdate_range("2020-02-03", periods=20)
    flags = pd.DataFrame({"stock_id": ["2330"], "revenue_month": [pd.Timestamp("2020-01-01")],
                          "announce_date": [pd.Timestamp("2020-02-17")], "g": [1.0]})
    p = revmom.gate_panels(flags, days, pd.Index(["2330"]), gates={"g": ("x", "top")})["g"]
    assert np.isnan(p.at[pd.Timestamp("2020-02-17"), "2330"])  # 公告日當天不可見
    assert p.at[pd.Timestamp("2020-02-18"), "2330"] == 1.0


def _ci(lo95, lo99):
    return {k: {95.0: (lo95, 1.0), 98.75: (lo99, 1.0)} for k in ("mean", "hit")}


def test_verdict_requires_both_stats_and_both_intervals():
    assert revmom.verdict(0.02, 0.03, _ci(0.01, 0.005), 400, 300) == "通過且存活"
    assert revmom.verdict(0.02, 0.03, _ci(0.01, -0.01), 400, 300) == "通過（未過 Bonferroni）"
    assert revmom.verdict(0.02, 0.03, _ci(-0.01, -0.02), 400, 300) == "inconclusive"
    assert revmom.verdict(0.02, -0.01, _ci(0.01, 0.005), 400, 300) == "inconclusive"
    assert revmom.verdict(0.02, 0.03, _ci(0.01, 0.005), 299, 300) == "inconclusive"
    assert revmom.verdict(0.02, 0.03, _ci(0.01, 0.005), 300, 300) == "通過且存活"  # n ≥ 300 含等號
    assert revmom.verdict(0.02, 0.03, None, 400, 300) == "inconclusive"
    one_side = {"mean": {95.0: (0.01, 1), 98.75: (0.01, 1)}, "hit": {95.0: (-0.01, 1), 98.75: (-0.01, 1)}}
    assert revmom.verdict(0.02, 0.03, one_side, 400, 300) == "inconclusive"


def test_main_surprise_mode_skips_momentum_sections(monkeypatch):
    days = pd.bdate_range("2026-04-01", periods=60)
    cols = pd.Index(["2330", "2454"])
    prices = pd.DataFrame(100.0, index=days, columns=cols)
    piv = {k: prices.copy() for k in ("open", "high", "close", "volume", "turnover")}
    rv = pd.concat([_rv([100] * 6, [40] * 6, start="2025-12-01", sid=s) for s in cols],
                   ignore_index=True)
    sig = pd.DataFrame(False, index=days, columns=cols)
    monkeypatch.setattr(revmom, "database_url", lambda: "unused")
    engine = SimpleNamespace(connect=lambda: nullcontext(object()))
    monkeypatch.setattr(revmom, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(revmom, "load", lambda *args: (piv, None, None))
    monkeypatch.setattr(revmom.pd, "read_sql", lambda *args, **kwargs: rv.copy())
    seen = []
    captured = {}

    def checked(sid):
        seen.append(sid)
        return is_common_stock(sid)

    class PanelsCaptured(Exception):
        pass

    def capture(filtered, yoy, *args):
        captured.update({k: list(v.columns) for k, v in filtered.items()})
        captured["yoy"] = list(yoy.columns)
        raise PanelsCaptured

    # 先釘住腳本綁的就是共用謂詞；否則下面的 spy 會蓋掉錯誤的本地綁定，守門形同虛設。
    assert revmom.is_common_stock is is_common_stock
    monkeypatch.setattr(revmom, "is_common_stock", checked)
    monkeypatch.setattr(revmom, "build_signals", capture)
    with pytest.raises(PanelsCaptured):
        revmom.main(["--start", "2026-04-01", "--end", f"{days[-1]:%Y-%m-%d}",
                     "--horizons", "5", "--bootstrap", "0"])

    assert sorted(seen) == sorted(UNIVERSE_CODES)
    assert captured and all(set(cols) == UNIVERSE_COMMON for cols in captured.values())
    monkeypatch.setattr(revmom, "build_signals", lambda *args: (
        sig, {"liquid": pd.DataFrame(True, index=days, columns=cols)}))
    seen = {}
    monkeypatch.setattr(revmom, "surprise_report",
                        lambda piv_, rv_, sig_, extra, horizons, a: seen.update(h=horizons))
    monkeypatch.setattr(revmom, "release_cross_section",
                        lambda *a, **k: pytest.fail("momentum section ran in surprise mode"))
    assert revmom.main(["--experiment", "surprise", "--start", "2026-03-31",
                        "--end", "2026-06-23", "--horizons", "5,10", "--pool-hold", "60",
                        "--bootstrap", "0"]) == 0
    assert seen["h"] == [5, 10, 60]


def _arm_row(verdict_label, dm, dh):
    return {"組": "x", "n": 400, "均值差pp": dm, "P30差pp": dh, "判定": verdict_label,
            revmom.RAW_DM: dm / 100, revmom.RAW_DH: dh / 100}


@pytest.mark.parametrize("pit_dm,pit_dh,vetoed", [
    (-0.5, 1.0, True),      # 均值差反向
    (1.0, -0.3, True),      # P30 差反向
    (0.0, 1.0, True),       # 不 > 0 也算方向不同（與判準 (a) 同一條線）
    (1.5, 0.8, False),      # 同方向 → 不否決
])
def test_pit_veto_downgrades_surviving_sus_only_when_pit_points_other_way(pit_dm, pit_dh, vetoed):
    rows = {("補充", "sus_top20"): _arm_row(revmom.SURVIVED, 2.0, 2.0),
            ("補充", "sus_pit_top20"): _arm_row("探索", pit_dm, pit_dh)}
    revmom.apply_pit_veto(rows)
    assert rows[("補充", "sus_top20")]["判定"] == (revmom.PIT_VETOED if vetoed else revmom.SURVIVED)


def test_pit_veto_pairs_same_arm_and_leaves_other_verdicts_alone():
    rows = {
        ("補充", "sus_top20"): _arm_row(revmom.SURVIVED, 2.0, 2.0),
        ("補充", "sus_pit_top20"): _arm_row("探索", 1.0, 1.0),     # 補充組同方向
        ("取代", "sus_top20"): _arm_row(revmom.SURVIVED, 2.0, 2.0),
        ("取代", "sus_pit_top20"): _arm_row("探索", -1.0, -1.0),   # 只有取代組反向
        ("補充", "ath_top20"): _arm_row(revmom.SURVIVED, 2.0, 2.0),  # ATH 沒有 PIT 變體
        ("補充", "sus_ge1"): _arm_row("探索", 2.0, 2.0),
    }
    rows[("取代", "sus_top20")]["判定"] = "通過（未過 Bonferroni）"   # 本來就不存活：不改
    revmom.apply_pit_veto(rows)
    assert rows[("補充", "sus_top20")]["判定"] == revmom.SURVIVED
    assert rows[("取代", "sus_top20")]["判定"] == "通過（未過 Bonferroni）"
    assert rows[("補充", "ath_top20")]["判定"] == revmom.SURVIVED
    rows[("取代", "sus_top20")]["判定"] = revmom.SURVIVED
    revmom.apply_pit_veto(rows)
    assert rows[("取代", "sus_top20")]["判定"] == revmom.PIT_VETOED
    assert rows[("補充", "sus_top20")]["判定"] == revmom.SURVIVED     # 不跨組配對


def _tiny_diff_pit_row(variant):
    """以真 compare_arm 產生 PIT 變體列：候選池 6000 筆（1000 筆命中），變體只差一筆。

    差距都小到顯示四捨五入會失真：均值差約 +0.007pp（顯示 0.01）、P30 差約 ±0.014pp 或 0
    （顯示 0.0）。否決必須看原始差，不是顯示值。
    """
    hit = revmom.HIT_THRESHOLD
    ref = pd.DataFrame({"r": [hit + 0.2] * 1000 + [0.0] * 5000})
    if variant == "extra_hit":          # 多一筆命中 → 兩者原始差都 > 0
        arm = pd.concat([ref, pd.DataFrame({"r": [hit + 0.2]})], ignore_index=True)
    elif variant == "bump_no_hit":      # 一筆未命中上調但沒跨門檻 → P30 差恰為 0
        arm = ref.copy()
        arm.loc[arm.index[-1], "r"] = hit / 2
    else:                               # 多一筆大漲未命中 → 均值差 > 0、P30 差 < 0 但顯示 -0.0
        arm = pd.concat([ref, pd.DataFrame({"r": [hit * 0.99]})], ignore_index=True)
    a = SimpleNamespace(bootstrap=0, bootstrap_seed=42, min_events=1)
    return revmom.compare_arm("sus_pit_top20", arm, ref, n_days=100, h=60, a=a)


@pytest.mark.parametrize("variant,vetoed", [
    ("extra_hit", False),     # 原始差皆 > 0：顯示值 P30差pp=0.0 不能造成誤否決
    ("bump_no_hit", True),    # P30 原始差恰為 0：不 > 0 → 否決（擋「改成 ≥ 0」的過度修正）
    ("near_miss", True),      # P30 原始差 < 0、顯示 -0.0：否決（擋容差／取絕對值）
])
def test_pit_veto_uses_raw_differences_not_rounded_display(variant, vetoed):
    pit = _tiny_diff_pit_row(variant)
    if variant == "extra_hit":
        assert pit["P30差pp"] == 0.0      # 前提：顯示值確實被四捨五入成 0
    rows = {("補充", "sus_top20"): _arm_row(revmom.SURVIVED, 2.0, 2.0),
            ("補充", "sus_pit_top20"): pit}
    revmom.apply_pit_veto(rows)
    assert rows[("補充", "sus_top20")]["判定"] == (revmom.PIT_VETOED if vetoed else revmom.SURVIVED)


def test_surprise_report_applies_pit_veto_to_printed_verdict(monkeypatch, capsys):
    days = pd.bdate_range("2020-01-01", periods=5)
    cols = pd.Index(["2330"])
    piv = {"close": pd.DataFrame(100.0, index=days, columns=cols)}
    pool = pd.DataFrame({"r": [0.1], **{g: [1.0] for g in revmom.SURPRISE_GATES}})
    monkeypatch.setattr(revmom, "revenue_surprise_features",
                        lambda rv: pd.DataFrame({"sus": [], "sus_pit": [], "ath_ratio": []}))
    monkeypatch.setattr(revmom, "gate_flags", lambda feat: None)
    monkeypatch.setattr(revmom, "gate_panels",
                        lambda flags, idx, cols: {g: None for g in revmom.SURPRISE_GATES})
    monkeypatch.setattr(revmom, "forward_returns", lambda piv_, h, how: (None, None))
    monkeypatch.setattr(revmom, "to_events", lambda *a, **k: (None, pool))
    monkeypatch.setattr(revmom, "apply_thresholds",
                        lambda *a, **k: pd.DataFrame(False, index=days, columns=cols))

    def fake_compare(label, arm, ref, n_days, h, a, primary=False):
        if "sus_pit_top20" in label:
            return {**_arm_row("探索", -1.0, -1.0), "組": label}
        return {**_arm_row(revmom.SURVIVED if primary else "探索", 2.0, 2.0), "組": label}

    monkeypatch.setattr(revmom, "compare_arm", fake_compare)
    a = SimpleNamespace(pool_hold=60, start="2020-01-01", d5=0.05, vol_lo=1.3, vol_hi=2.0,
                        position_notional=200_000, bootstrap=0, bootstrap_seed=42)
    revmom.surprise_report(piv, pd.DataFrame({"stock_id": []}), None, {}, [60], a)
    out = capsys.readouterr().out
    sus_lines = [ln for ln in out.splitlines() if "sus_top20（" in ln]
    ath_lines = [ln for ln in out.splitlines() if "ath_top20" in ln]
    assert len(sus_lines) == 2, out
    assert all(revmom.PIT_VETOED in ln for ln in sus_lines)
    assert all(revmom.SURVIVED in ln and revmom.PIT_VETOED not in ln for ln in ath_lines)
    assert revmom.RAW_DM not in out and revmom.RAW_DH not in out   # 原始差不印進表格


def _mixed_deadline_feat(insurance_sus):
    """2026-01 營收月：10 檔 10 日可見、2 檔（保險類）15 日才可見。"""
    m = pd.Timestamp("2026-01-01")
    early, late = pd.Timestamp("2026-02-10"), pd.Timestamp("2026-02-16")
    return pd.DataFrame({
        "stock_id": [f"{1100 + i}" for i in range(10)] + ["2881", "2882"],
        "revenue_month": [m] * 12,
        "announce_date": [early] * 10 + [late] * 2,
        "sus": list(range(1, 11)) + list(insurance_sus),
        "sus_pit": 0.0, "ath_ratio": 1.0,
    })


def test_gate_flags_early_cohort_ignores_values_not_yet_visible():
    # 10 日可見的那批只能和 10 日已可見的同月股票比；15 日才公布的保險類數值不能改變它們的旗標
    low = revmom.gate_flags(_mixed_deadline_feat([-5.0, -4.0])).set_index("stock_id")["sus_top20"]
    high = revmom.gate_flags(_mixed_deadline_feat([50.0, 60.0])).set_index("stock_id")["sus_top20"]
    early = [f"{1100 + i}" for i in range(10)]
    assert low[early].tolist() == high[early].tolist()
    assert low[low == 1].index.tolist() == ["1108", "1109"]          # 只在 10 檔內排名
    assert high[early][high[early] == 1].index.tolist() == ["1108", "1109"]


def test_gate_flags_late_cohort_ranks_against_whole_visible_month():
    # 15 日那批可見時整個月份都已可見 → 對全部 12 檔排名，而不是只在保險類兩檔之間排
    g = revmom.gate_flags(_mixed_deadline_feat([5.5, 3.0])).set_index("stock_id")["sus_top20"]
    assert g["2881"] == 0.0     # 兩檔中最高，但在 12 檔裡只排 7/12
    assert g["2882"] == 0.0
    g = revmom.gate_flags(_mixed_deadline_feat([20.0, 3.0])).set_index("stock_id")["sus_top20"]
    assert g["2881"] == 1.0
