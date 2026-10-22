"""scripts/shadow_buy_eval.py 的純計算部分：影子交易報酬、原判擷取、code 群聚 bootstrap。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from shadow_buy_eval import (  # noqa: E402
    DEFAULT_NOTIONAL,
    cluster_bootstrap_ci,
    is_raw_buy,
    latest_per_code_day,
    raw_decision,
    render,
    trade_return,
    verdict,
)
from tw_trade_costs import STOCK_TRANSACTION_TAX_RATE, round_trip_return  # noqa: E402


def _rt(entry, exit_):
    return round_trip_return(entry, exit_, entry_notional=DEFAULT_NOTIONAL,
                             tax_rate=STOCK_TRANSACTION_TAX_RATE)


def _bars(o, h, lo, c, adj=None):
    arr = [np.asarray(x, dtype=float) for x in (o, h, lo, c)]
    return (*arr, np.ones(len(o)) if adj is None else np.asarray(adj, dtype=float))


def test_time_exit_uses_last_close():
    r, kind = trade_return(*_bars([100, 101, 102], [103, 104, 105], [99, 100, 101], [101, 102, 110]))
    assert kind == "time"
    assert r == pytest.approx(_rt(100, 110))


def test_stop_hit_exits_at_stop_or_gap_open():
    bars = _bars([100, 99], [101, 100], [98, 94], [99, 96])
    r, kind = trade_return(*bars, stop=95, take=110)
    assert kind == "stop" and r == pytest.approx(_rt(100, 95))
    gap = _bars([100, 93], [101, 94], [98, 92], [99, 93])
    r, kind = trade_return(*gap, stop=95, take=110)
    assert kind == "stop" and r == pytest.approx(_rt(100, 93))


def test_take_hit_and_same_day_both_counts_as_stop():
    r, kind = trade_return(*_bars([100, 105], [104, 112], [99, 104], [103, 111]), stop=95, take=110)
    assert kind == "take" and r == pytest.approx(_rt(100, 110))
    r, kind = trade_return(*_bars([100, 100], [101, 112], [99, 94], [100, 100]), stop=95, take=110)
    assert kind == "stop" and r == pytest.approx(_rt(100, 95))


def test_levels_not_straddling_entry_are_ignored():
    # 開盤已跌破停損：價位失效，不該開盤就當場停損
    r, kind = trade_return(*_bars([94, 96], [97, 99], [93, 95], [96, 98]), stop=95, take=110)
    assert kind == "time" and r == pytest.approx(_rt(94, 98))


def test_adjusted_prices_used_for_pnl_and_triggers():
    # 第 2 天除息：前復權因子 0.5→1；價位換到還原空間（stop=40→20）不觸發，損益用還原價
    r, kind = trade_return(*_bars([100, 51], [101, 53], [99, 50], [100, 52], adj=[0.5, 1.0]),
                           stop=40, take=200)
    assert kind == "time" and r == pytest.approx(_rt(50, 52))


def test_split_inside_window_does_not_fake_a_stop():
    # 第 2 天 1 拆 4：未還原開盤 100→25，經濟上沒虧；名目 stop=95 不可因此觸發，之後 +20% 才停利
    adj = [0.25, 1.0, 1.0]
    bars = _bars([100, 25, 27], [101, 26, 30.5], [99, 24.5, 26.5], [100, 25.5, 30], adj=adj)
    r, kind = trade_return(*bars, stop=95, take=120)
    assert kind == "take" and r == pytest.approx(_rt(25, 30))
    # 反向：真的跌破還原後的停損仍要停損
    drop = _bars([100, 23, 22], [101, 24, 23], [99, 22.5, 21], [100, 23, 22], adj=adj)
    r, kind = trade_return(*drop, stop=95, take=120)
    assert kind == "stop" and r == pytest.approx(_rt(25, 23))


def test_split_between_report_and_entry_keeps_levels():
    # 報告日價位 stop 95／take 120（名目 100 附近），進場日當天 1 拆 4：開盤 25 不可讓價位失效
    bars = _bars([25, 27, 30.5], [26, 30.5, 31], [24.5, 26.5, 30], [25.5, 30, 30.5], adj=[1.0, 1.0, 1.0])
    r, kind = trade_return(*bars, stop=95, take=120, level_adj=0.25)
    assert kind == "take" and r == pytest.approx(_rt(25, 30))
    # 反向：沒有分割時，報告價位相對進場價不成區間就仍要忽略
    r, kind = trade_return(*bars, stop=95, take=120, level_adj=1.0)
    assert kind == "time"


def test_suspended_entry_day_returns_none():
    assert trade_return(*_bars([np.nan, 100], [np.nan, 101], [np.nan, 99], [np.nan, 100])) is None


def test_latest_per_code_day_keeps_whole_last_row():
    # 同日兩份：較晚那份沒填停損，不能拼上較早那份的停損；隔日那份要獨立保留
    df = pd.DataFrame({
        "code": ["2330.TW", "2330.TW", "2330.TW", "2317.TW"],
        "created_at": pd.to_datetime(["2026-10-01 18:00", "2026-10-01 10:00",
                                      "2026-10-02 18:00", "2026-10-01 18:00"]),
        "stop_loss": [np.nan, 95.0, 96.0, 50.0],
        "raw_result": ["late", "early", "next", "other"],
    })
    out = latest_per_code_day(df).set_index(["code", "day"])
    late = out.loc[("2330.TW", pd.Timestamp("2026-10-01"))]
    assert late["raw_result"] == "late" and np.isnan(late["stop_loss"])
    assert len(out) == 3
    assert out.loc[("2330.TW", pd.Timestamp("2026-10-02")), "stop_loss"] == 96.0


def test_raw_decision_prefers_calibration_raw_score():
    downgraded = json.dumps({"decision_type": "hold", "sentiment_score": 59, "dashboard": {
        "decision_score_calibration": {"raw_score": 68, "canonical_decision_type": "buy",
                                       "final_action": "hold"},
        "decision_stability": {"applied": True, "raw_score": 68}}})
    d = raw_decision(downgraded, 59)
    assert d["raw_score"] == 68 and d["raw_type"] == "buy" and d["final_type"] == "hold"
    assert d["downgraded"] and is_raw_buy(d["raw_score"], d["raw_type"])

    plain = json.dumps({"decision_type": "hold", "sentiment_score": 48,
                        "dashboard": {"decision_stability": {"applied": False}}})
    d = raw_decision(plain, 48)
    assert d["raw_score"] == 48 and not d["downgraded"]
    assert not is_raw_buy(d["raw_score"], d["raw_type"])
    assert is_raw_buy(55, "buy") and not is_raw_buy(None, None)
    assert is_raw_buy(60, "hold") and not is_raw_buy(59.9, "hold")


def test_raw_decision_reads_variant_and_pre_guardrail_type():
    # 後段護欄記下的護欄前動作優先於依分數推回的 canonical；沒標版本的舊報告歸 untagged
    calibration = {"raw_score": 58, "raw_decision_type": "buy", "canonical_decision_type": "hold"}
    tagged = json.dumps({"decision_type": "hold",
                         "dashboard": {"prompt_variant": "v2", "decision_score_calibration": calibration}})
    d = raw_decision(tagged, 52)
    assert d["variant"] == "v2" and d["raw_type"] == "buy" and is_raw_buy(d["raw_score"], d["raw_type"])
    assert raw_decision(json.dumps({"dashboard": {}}), 50)["variant"] == "untagged"


def test_render_by_variant_splits_tables():
    from types import SimpleNamespace

    reports = pd.DataFrame({
        "code": ["2330.TW", "2317.TW"], "created_at": pd.to_datetime(["2026-10-01 18:00", "2026-10-01 18:00"]),
        "day": pd.to_datetime(["2026-10-01", "2026-10-01"]), "raw_score": [70.0, 40.0],
        "raw_type": ["buy", "hold"], "downgraded": [True, False], "variant": ["baseline", "v2"]})
    ev = pd.DataFrame([{"code": c, "day": pd.Timestamp("2026-10-01"), "group": g, "h": 1, "mode": m,
                        "ret": 0.01, "exit": "time", "bench": 0.0, "downgraded": g == "raw_buy", "variant": v}
                       for c, g, v in (("2330.TW", "raw_buy", "baseline"), ("2317.TW", "others", "v2"))
                       for m in ("time", "levels")])
    args = SimpleNamespace(buy_threshold=60, bootstrap=50, seed=1, by_variant=True)
    text = render(ev, reports, args)
    base, v2 = text.split("## 版本：baseline")[1].split("## 版本：v2")
    assert "| raw-buy | 1（1 檔）" in base and "| raw-buy | 0 |" in v2
    assert "| others | 1（1 檔）" in v2 and "| others | 0 |" in base
    args.by_variant = False
    assert "版本：" not in render(ev, reports, args)


def test_bootstrap_resamples_whole_codes():
    # A 檔 100 筆 +1、B 檔 1 筆 -1：以 code 重抽時有 1/4 機率抽到 BB → 下界 -1；
    # 逐筆 iid 重抽則下界會黏在 +0.96 附近（假精度）
    vals = [1.0] * 100 + [-1.0]
    codes = ["A"] * 100 + ["B"]
    lo, hi = cluster_bootstrap_ci(vals, codes, n=2000, seed=1)
    assert lo == pytest.approx(-1.0) and hi == pytest.approx(1.0)
    assert cluster_bootstrap_ci([1.0, 2.0], ["A", "A"]) is None


def test_bootstrap_ci_independent_of_row_order():
    # 同一批資料換列順序，CI 不能跟著變（否則判定會被 SQL 回傳順序左右）
    vals = [0.03, -0.01, 0.02, -0.04, 0.01, 0.05, -0.02]
    codes = ["A", "B", "C", "D", "E", "F", "G"]
    fwd = cluster_bootstrap_ci(vals, codes, n=500)
    assert cluster_bootstrap_ci(vals[::-1], codes[::-1], n=500) == pytest.approx(fwd)


def test_bootstrap_diff_between_groups():
    ci = cluster_bootstrap_ci([2.0, 2.0, 2.0], ["A", "B", "C"], n=500,
                              other=([1.0, 1.0], ["D", "E"]))
    assert ci == pytest.approx((1.0, 1.0))


def test_verdict_inconclusive_when_crossing_zero_or_missing():
    assert verdict(None) == "inconclusive"
    assert verdict((-0.01, 0.02)) == "inconclusive"
    assert verdict((0.0, 0.02)) == "inconclusive"
    assert verdict((0.001, 0.02)) == "顯著為正"
    assert verdict((-0.02, -0.001)) == "顯著為負"


def test_help_has_no_side_effects():
    out = subprocess.run([sys.executable, str(SCRIPTS_DIR / "shadow_buy_eval.py"), "--help"],
                         capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}, timeout=60)
    assert out.returncode == 0 and "--out" in out.stdout


def test_build_events_uses_report_day_factor_for_levels():
    from shadow_buy_eval import BENCHMARK, build_events

    days = pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"])
    # 2330 在 10-02（進場日）1 拆 4：報告日 10-01 因子 0.25、之後 1.0
    px = {"open": [100, 25, 27, 30.5], "high": [101, 26, 30.5, 31],
          "low": [99, 24.5, 26.5, 30], "close": [100, 25.5, 30, 30.5]}
    panels = {k: pd.DataFrame({"2330": v, BENCHMARK: [50.0] * 4}, index=days) for k, v in px.items()}
    panels["adj"] = pd.DataFrame({"2330": [0.25, 1.0, 1.0, 1.0], BENCHMARK: [1.0] * 4}, index=days)
    reports = pd.DataFrame([{"code": "2330.TW", "stock_id": "2330", "day": days[0], "raw_score": 70,
                             "raw_type": "buy", "stop_loss": 95.0, "take_profit": 120.0,
                             "downgraded": True, "variant": "baseline"}])
    ev = build_events(reports, panels, [3], threshold=60, fee_discount=1.0)
    lv = ev[ev["mode"] == "levels"].iloc[0]
    assert lv["exit"] == "take" and lv["ret"] == pytest.approx(_rt(25, 30))
