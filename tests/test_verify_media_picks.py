"""scripts/verify_media_picks.py：進場日、右設限、超額、命中方向、去重、inconclusive 規則（合成價格面板，不連 DB）。"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("verify_media_picks", ROOT / "scripts" / "verify_media_picks.py")
vmp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vmp)

DAYS = pd.bdate_range("2026-01-05", periods=40)


def panels(stock_open, stock_close, bench_close=100.0, n=40, sid="2330"):
    """0050 固定價（或指定收盤）；個股開盤／收盤由呼叫端給（長度 n 的 list）。"""
    idx = DAYS[:n]
    b = pd.Series(bench_close, index=idx, dtype=float) if np.isscalar(bench_close) else pd.Series(bench_close, index=idx)
    return {"open": pd.DataFrame({"0050": b, sid: pd.Series(stock_open, index=idx, dtype=float)}),
            "close": pd.DataFrame({"0050": b, sid: pd.Series(stock_close, index=idx, dtype=float)})}


def pick(anchor, code="2330.TW", **kw):
    return {"kind": "call", "code": code, "anchor": pd.Timestamp(anchor), "speaker": "甲", "show": "S",
            "media_kind": "tv", "stance": "bullish"} | kw


def flat_with_air_gap(air_idx, n=40):
    o = [100.0] * n
    c = [100.0] * n
    o[air_idx] = c[air_idx] = 1000.0     # 播出當天大跳空：用到它就會算出巨大的假報酬／假虧損
    return o, c


def test_entry_is_session_after_air_day_not_air_day():
    o, c = flat_with_air_gap(3)
    for i in range(4, 40):
        c[i] = 110.0
    ev = vmp.build_events([pick(DAYS[3])], panels(o, c), (5,))
    r = ev.iloc[0]
    assert r["status"] == "ok" and r["entry_date"] == DAYS[4]
    assert 0.07 < r["excess"] < 0.11            # 100 進、110 出；若用播出日 1000 進場會是 -0.9 上下


def test_anchor_on_weekend_enters_next_monday():
    o, c = flat_with_air_gap(5)                  # DAYS[5] = 週一 01-12；週日 01-11 播出
    ev = vmp.build_events([pick("2026-01-11")], panels(o, c), (2,))
    assert ev.iloc[0]["entry_date"] == DAYS[5]


def test_right_censored_is_excluded_and_counted_never_filled():
    n = 10
    o, c = [100.0] * n, [100.0] * n
    ev = vmp.build_events([pick(DAYS[3])], panels(o, c, n=n), (2, 6, 7))
    st = dict(zip(ev["h"], ev["status"]))
    # 進場 idx4：h=6 出場 idx9（最後一天）剛好走完；h=7 差一天
    assert st == {2: "ok", 6: "ok", 7: "censored"}
    assert ev[ev["status"] == "censored"][["ret", "excess"]].isna().all().all()
    res = vmp.analyse(ev, (2, 6, 7), n_boot=50)
    assert res["excluded"]["call@7"]["censored"] == 1 and res["excluded"]["call@2"]["ok"] == 1


def test_anchor_after_last_session_is_censored():
    ev = vmp.build_events([pick(DAYS[39])], panels([100.0] * 40, [100.0] * 40), (1,))
    assert ev.iloc[0]["status"] == "censored"


def test_excess_is_stock_minus_benchmark_same_window():
    o, c = [100.0] * 40, [100.0] * 40
    for i in range(5, 40):
        c[i] = 110.0
    bench = [100.0] * 40
    for i in range(5, 40):          # 進場日開盤（panels 的 open 與 close 共用這條線）仍是 100
        bench[i] = 105.0
    ev = vmp.build_events([pick(DAYS[3])], panels(o, c, bench), (5,))
    r = ev.iloc[0]
    assert r["excess"] == pytest.approx(r["ret"] - r["bench"])
    assert 0.03 < r["excess"] < 0.06            # 約 +10% − 5%
    assert r["ret"] < 0.10 and r["bench"] < 0.05  # 都已扣成本


def test_unknown_code_and_missing_price_are_counted_not_filled():
    o, c = [100.0] * 40, [100.0] * 40
    c[8] = np.nan                                 # h=5 的出場日（進場 idx4 → idx8）沒成交
    ev = vmp.build_events([pick(DAYS[3]), pick(DAYS[3], code="9999.TW"), pick(DAYS[3], code="2330")],
                          panels(o, c), (5,))
    assert sorted(ev["status"]) == ["no_price", "unknown_code", "unknown_code"]


def test_bearish_hit_is_negative_excess():
    ex = [-0.05, -0.02, 0.01]
    assert vmp.hit_mask(ex, "bear").tolist() == [True, True, False]
    assert vmp.hit_mask(ex, "bull").tolist() == [False, False, True]
    df = pd.DataFrame({"excess": ex, "excess_gross": ex, "code": ["a", "b", "c"]})
    assert vmp.stats(df, "bear", n_boot=50)["hit"] == pytest.approx(2 / 3)
    assert vmp.stats(df, "bull", n_boot=50)["hit"] == pytest.approx(1 / 3)


def _row(**kw):
    return {"video_id": "v", "show": "S", "date": "2026-01-08", "stock_code": "2330.TW", "stance": "bullish",
            "speaker": "甲", "kind": "tv", "name_said": "台積電"} | kw


def test_calls_dedup_same_speaker_code_date_and_show_fallback():
    rows = [_row(), _row(show="T"), _row(date="2026-01-09"),                      # 同人同日同檔 → 一個
            _row(speaker=None, show="X"), _row(speaker="", show="X"),               # 無講者用節目
            _row(stance="neutral", speaker="丙"), _row(stock_code=None, speaker="丁"),
            _row(resolve="no_picks", speaker="戊")]
    out, dropped = vmp.call_picks(rows, [])
    assert sorted((p["speaker"], p["anchor"].date().isoformat()) for p in out) == [
        ("[X]", "2026-01-08"), ("甲", "2026-01-08"), ("甲", "2026-01-09")]
    assert dropped["conflict"] == 0


def test_conflicting_direction_same_day_is_dropped_and_counted():
    out, dropped = vmp.call_picks([_row(), _row(stance="avoid")], [])
    assert out == [] and dropped["conflict"] == 1
    out, _ = vmp.call_picks([_row(stance="bearish"), _row(stance="avoid")], [])   # 同為空方：不算衝突
    assert len(out) == 1


def test_unclear_review_is_excluded():
    rv = [{"video_id": "v", "name_said": "台積電", "stock_code": "2330.TW", "verdict": "unclear"}]
    out, dropped = vmp.call_picks([_row()], rv)
    assert out == [] and dropped["review_unclear"] == 1


def test_verdict_anchor_uses_taipei_date_and_keeps_last_rejudge():
    rows = [{"code": "2330.TW", "date": "2026-01-06", "verdict": "watch", "written_at": "2026-01-06T23:30:00+08:00"},
            {"code": "2330.TW", "date": "2026-01-06", "verdict": "avoid", "written_at": "2026-01-06T23:50:00+08:00"},
            {"code": "2317.TW", "date": "2026-01-06", "verdict": "research", "written_at": "2026-01-06T16:30:00+00:00"}]
    out = {p["code"]: p for p in vmp.verdict_picks(rows)}
    assert len(out) == 2 and out["2330.TW"]["verdict"] == "avoid"
    assert out["2330.TW"]["anchor"] == pd.Timestamp("2026-01-06")
    assert out["2317.TW"]["anchor"] == pd.Timestamp("2026-01-07")     # UTC 16:30 = 台北隔天 00:30


def test_verdict_entry_is_session_after_written_day():
    o, c = flat_with_air_gap(3)
    p = vmp.verdict_picks([{"code": "2330.TW", "date": "x", "verdict": "research",
                            "written_at": f"{DAYS[3].date()}T23:30:00+08:00"}])
    ev = vmp.build_events(p, panels(o, c), (3,))
    assert ev.iloc[0]["entry_date"] == DAYS[4] and abs(ev.iloc[0]["excess"]) < 0.01


def _df(vals, codes=None):
    codes = codes or [f"c{i}" for i in range(len(vals))]
    return pd.DataFrame({"excess": vals, "excess_gross": vals, "code": codes})


def test_inconclusive_when_n_below_20_even_if_ci_excludes_zero():
    s = vmp.stats(_df([0.05 + i * 0.001 for i in range(19)]), n_boot=200)
    assert s["n"] == 19 and s["ci"][0] > 0 and s["label"] == "inconclusive"
    s = vmp.stats(_df([0.05 + i * 0.001 for i in range(20)]), n_boot=200)
    assert s["n"] == 20 and s["label"] == "顯著為正"


def test_inconclusive_when_ci_crosses_zero_with_enough_n():
    rng = np.random.default_rng(0)
    s = vmp.stats(_df(list(rng.normal(0, 0.05, 60))), n_boot=300)
    assert s["n"] == 60 and s["ci"][0] < 0 < s["ci"][1] and s["label"] == "inconclusive"


def test_single_code_has_no_ci_so_inconclusive():
    s = vmp.stats(_df([0.05] * 30, ["a"] * 30), n_boot=50)
    assert s["ci"] is None and s["label"] == "inconclusive"


def test_spread_label_needs_both_groups_enough():
    a, b = _df([0.06 + i * 0.001 for i in range(25)]), _df([-0.06 - i * 0.001 for i in range(10)])
    s = vmp.spread_stats(a, b, n_boot=200)
    assert s["diff"] > 0.1 and s["label"] == "inconclusive"           # b 只有 10
    b = _df([-0.06 - i * 0.001 for i in range(25)])
    assert vmp.spread_stats(a, b, n_boot=200)["label"] == "顯著為正"


def _events(rows):
    """每列預設毛超額＝淨超額、各自不同進場日（dates 不是被測性質時不擋 enough）。"""
    return pd.DataFrame([{"kind": "call", "h": 10, "status": "ok", "media_kind": "tv", "excess_gross": r["excess"],
                          "entry_date": DAYS[i % len(DAYS)]} | r for i, r in enumerate(rows)])


def test_speaker_records_shape_and_directions():
    rows = [{"speaker": "甲", "stance": "bullish", "excess": 0.05, "code": "a"},
            {"speaker": "甲", "stance": "bullish", "excess": -0.01, "code": "b"},
            {"speaker": "甲", "stance": "bullish", "excess": 0.02, "code": "c", "status": "censored"},
            {"speaker": "甲", "stance": "avoid", "excess": -0.04, "code": "d"},
            {"speaker": "甲", "stance": "bearish", "excess": 0.03, "code": "e"},
            {"speaker": "甲", "stance": "bullish", "excess": 0.9, "code": "f", "h": 5},       # 別的 horizon 不算
            {"speaker": "乙", "stance": "bullish", "excess": 0.1, "code": "g"}]
    rec = vmp.speaker_records(_events(rows), horizon=10)
    assert set(rec) == {"甲", "乙"} and set(rec["甲"]) == {"bull", "bear"} and set(rec["乙"]) == {"bull"}
    bull = rec["甲"]["bull"]
    assert bull == {"n_calls": 3, "n": 2, "dates": 2, "hit_rate": 0.5, "mean_excess": pytest.approx(0.02),
                    "enough": False}
    assert rec["甲"]["bear"]["hit_rate"] == 0.5 and rec["甲"]["bear"]["mean_excess"] == pytest.approx(-0.005)


def test_speaker_records_enough_flag_threshold_and_empty():
    rows = [{"speaker": "甲", "stance": "bullish", "excess": 0.01, "code": f"c{i}"} for i in range(20)]
    assert vmp.speaker_records(_events(rows[:19]))["甲"]["bull"]["enough"] is False
    assert vmp.speaker_records(_events(rows))["甲"]["bull"]["enough"] is True
    assert vmp.speaker_records(pd.DataFrame()) == {}


def test_render_prints_inconclusive_and_excluded_counts():
    ev = vmp.build_events([pick(DAYS[3]), pick(DAYS[39], code="9999.TW")], panels([100.0] * 40, [100.0] * 40), (5,))
    res = vmp.analyse(ev, (5,), n_boot=50)
    text = vmp.render(res, {"verdicts": 0, "calls": 2, "raw_calls": 2, "dropped": {}})
    assert "inconclusive" in text and "unknown_code" in text and "censored" in text


def test_few_entry_dates_is_inconclusive_even_with_tight_ci():
    vals = [-0.02 - i * 0.0001 for i in range(40)]
    df = _df(vals)
    df["entry_date"] = [DAYS[i % 4] for i in range(40)]          # 40 筆、20 檔，卻只有 4 個進場日
    assert vmp.stats(df, n_boot=200)["label"] == "inconclusive"
    df["entry_date"] = [DAYS[i % 5] for i in range(40)]
    s = vmp.stats(df, n_boot=200)
    assert s["dates"] == 5 and s["label"] == "顯著為負"


def test_spread_needs_five_entry_dates_on_each_side():
    a, b = _df([0.06 + i * 0.001 for i in range(20)]), _df([-0.06 - i * 0.001 for i in range(20)])
    a["entry_date"], b["entry_date"] = DAYS[0], DAYS[0]                      # 兩組各 20 筆、只有一個進場日
    s = vmp.spread_stats(a, b, n_boot=200)
    assert s["diff"] > 0.1 and s["ci"][0] > 0 and s["dates"] == 1 and s["label"] == "inconclusive"
    a["entry_date"] = [DAYS[i % 5] for i in range(20)]
    assert vmp.spread_stats(a, b, n_boot=200)["label"] == "inconclusive"     # 只有 research 夠、avoid 還是 1 天
    b["entry_date"] = [DAYS[i % 5] for i in range(20)]
    s = vmp.spread_stats(a, b, n_boot=200)
    assert s["dates"] == 5 and s["label"] == "顯著為正"


def test_flat_stock_vs_flat_benchmark_is_neither_bull_nor_bear_hit():
    ev = vmp.build_events([pick(DAYS[3])], panels([100.0] * 40, [100.0] * 40), (5,))
    r = ev.iloc[0]
    assert r["excess"] < 0 and r["excess_gross"] == pytest.approx(0.0)       # 淨超額被稅差 0.2% 壓成負，毛超額為 0
    ok = ev[ev["status"] == "ok"]
    assert vmp.stats(ok, "bear", n_boot=50)["hit"] == 0.0
    assert vmp.stats(ok, "bull", n_boot=50)["hit"] == 0.0
    rec = vmp.speaker_records(ev.assign(stance="bearish"), horizon=5)["甲"]["bear"]
    assert rec["hit_rate"] == 0.0 and rec["mean_excess"] == pytest.approx(0.0)


def test_bear_mean_is_gross_bull_mean_is_net():
    df = _df([-0.002] * 3, ["a", "b", "c"]).assign(excess_gross=[0.0, 0.0, 0.0])
    assert vmp.stats(df, "bull", n_boot=50)["mean"] == pytest.approx(-0.002)
    assert vmp.stats(df, "bear", n_boot=50)["mean"] == pytest.approx(0.0)


def test_speaker_records_need_five_entry_dates_for_enough():
    rows = [{"speaker": "甲", "stance": "bullish", "excess": 0.01, "code": f"c{i}"} for i in range(20)]
    same_day = _events(rows).assign(entry_date=DAYS[0])
    rec = vmp.speaker_records(same_day)["甲"]["bull"]
    assert rec["n"] == 20 and rec["dates"] == 1 and rec["enough"] is False
    four = _events(rows).assign(entry_date=[DAYS[i % 4] for i in range(20)])
    assert vmp.speaker_records(four)["甲"]["bull"]["enough"] is False
    five = _events(rows).assign(entry_date=[DAYS[i % 5] for i in range(20)])
    assert vmp.speaker_records(five)["甲"]["bull"]["enough"] is True
