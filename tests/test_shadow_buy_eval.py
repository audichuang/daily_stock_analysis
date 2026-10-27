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
    FORECAST_H,
    baseline_probs,
    build_forecast_events,
    cluster_bootstrap_ci,
    date_block_ci,
    forecast_outcome,
    forecast_scores,
    macro_ctx_label,
    rank_ic,
    render_forecast,
    is_raw_buy,
    latest_per_code_day,
    raw_decision,
    render,
    trade_return,
    verdict,
)
from tw_trade_costs import ETF_TRANSACTION_TAX_RATE, STOCK_TRANSACTION_TAX_RATE, round_trip_return  # noqa: E402


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


def test_gap_open_beyond_a_level_fills_at_open_before_intraday_other_side():
    # 開 112 已越過停利 110：開盤就停利出場，之後盤中跌破停損 95 不能改判成停損。
    r, kind = trade_return(*_bars([100, 112], [101, 113], [99, 94], [100, 100]), stop=95, take=110)
    assert kind == "take" and r == pytest.approx(_rt(100, 112))
    # 反向：開 94 已跌破停損，之後盤中衝過停利也仍是開盤停損。
    r, kind = trade_return(*_bars([100, 94], [101, 112], [99, 93], [100, 100]), stop=95, take=110)
    assert kind == "stop" and r == pytest.approx(_rt(100, 94))


@pytest.mark.parametrize("scale", [1.0, 0.5])
@pytest.mark.parametrize("open_,exit_,expected_kind", [
    (112.0, 112.0, "take"),
    (110.0, 110.0, "take"),
    (93.0, 93.0, "stop"),
    (95.0, 95.0, "stop"),
    (100.0, 95.0, "stop"),
    (109.0, 95.0, "stop"),
])
def test_gap_fill_precedes_intrabar_ambiguity(scale, open_, exit_, expected_kind):
    bars = _bars(
        [100, open_ * scale], [101, 113 * scale], [99, 92 * scale], [100, 100 * scale],
        adj=[scale, 1.0],
    )
    r, kind = trade_return(*bars, stop=95, take=110)
    assert kind == expected_kind
    assert r == pytest.approx(_rt(100 * scale, exit_ * scale))


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


def test_missing_final_close_is_incomplete_not_last_finite_close():
    # 視窗最後一天停牌／下市：不能拿第 2 天 110 冒充期末出場（舊行為報 time +9%）
    r, kind = trade_return(*_bars([100, 108, np.nan], [101, 111, np.nan], [99, 107, np.nan],
                                  [100, 110, np.nan]))
    assert kind == "incomplete" and np.isnan(r)


def test_mid_window_gap_with_final_close_is_still_time_exit():
    # 反向：中間停牌一天但最後一天有收盤，仍是正常的期末出場
    r, kind = trade_return(*_bars([100, np.nan, 109], [101, np.nan, 111], [99, np.nan, 108],
                                  [100, np.nan, 110]))
    assert kind == "time" and r == pytest.approx(_rt(100, 110))


def test_level_hit_before_missing_tail_still_counts():
    # 反向：停損在停牌前就觸發，出場價已知，不算未完成
    r, kind = trade_return(*_bars([100, 99, np.nan], [101, 100, np.nan], [98, 94, np.nan],
                                  [99, 96, np.nan]), stop=95, take=110)
    assert kind == "stop" and r == pytest.approx(_rt(100, 95))


@pytest.mark.parametrize("missing", [3, 4])
def test_missing_final_close_or_factor_is_incomplete(missing):
    # 最後一天缺收盤或缺還原因子都算不出出場價，不能回傳 NaN 卻標成 time
    bars = list(_bars([100, 105], [101, 106], [99, 104], [100, 110]))
    bars[missing][-1] = np.nan
    r, kind = trade_return(*bars)
    assert kind == "incomplete" and np.isnan(r)


def test_per_day_tax_uses_actual_exit_day_rate():
    bars = _bars([100, 101, 102], [101, 120, 103], [99, 100, 101], [100, 105, 110])
    taxes = [0.0, 0.0, 0.001]  # 例：債券 ETF 停徵在第 2 天到期
    r, kind = trade_return(*bars, stop=95, take=110, tax_rate=taxes)
    assert kind == "take"
    assert r == pytest.approx(round_trip_return(100, 110, entry_notional=DEFAULT_NOTIONAL, tax_rate=0.0))
    r, kind = trade_return(*bars, tax_rate=taxes)
    assert kind == "time"
    assert r == pytest.approx(round_trip_return(100, 110, entry_notional=DEFAULT_NOTIONAL, tax_rate=0.001))


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


def _panels_for(sid, closes, days):
    from shadow_buy_eval import BENCHMARK

    n = len(days)
    px = {"open": closes, "high": closes, "low": closes, "close": closes}
    panels = {k: pd.DataFrame({sid: v, BENCHMARK: [50.0] * n}, index=days, dtype=float) for k, v in px.items()}
    panels["adj"] = pd.DataFrame({sid: [1.0] * n, BENCHMARK: [1.0] * n}, index=days)
    return panels


def _one_report(sid, code, day):
    return pd.DataFrame([{"code": code, "stock_id": sid, "day": day, "raw_score": 70, "raw_type": "buy",
                          "stop_loss": np.nan, "take_profit": np.nan, "downgraded": False,
                          "variant": "baseline"}])


def test_build_events_bond_etf_tax_exempt_only_inside_statutory_period():
    from shadow_buy_eval import build_events

    closes = [100.0, 100.0, 110.0]
    for days, tax in ((pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]), 0.0),
                      (pd.to_datetime(["2027-01-04", "2027-01-05", "2027-01-06"]), 0.001)):
        ev = build_events(_one_report("00679B", "00679B.TWO", days[0]), _panels_for("00679B", closes, days),
                          [2], threshold=60, fee_discount=1.0)
        row = ev[ev["mode"] == "time"].iloc[0]
        assert row["ret"] == pytest.approx(
            round_trip_return(100, 110, entry_notional=DEFAULT_NOTIONAL, tax_rate=tax))


def test_render_excludes_and_counts_incomplete_trades():
    from shadow_buy_eval import build_events

    days = pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"])
    ev = build_events(_one_report("2330", "2330.TW", days[0]),
                      _panels_for("2330", [100.0, 100.0, 110.0, np.nan], days),
                      [3], threshold=60, fee_discount=1.0)
    assert set(ev["exit"]) == {"incomplete"}
    reports = pd.DataFrame([{"code": "2330.TW", "created_at": days[0], "day": days[0], "raw_score": 70.0,
                             "raw_type": "buy", "downgraded": False, "variant": "baseline"}])
    from types import SimpleNamespace
    args = SimpleNamespace(buy_threshold=60, bootstrap=50, seed=1, by_variant=False)
    md = render(ev, reports, args)
    assert "未完成" in md and "raw-buy 1 筆" in md
    assert "| raw-buy | 0 |" in md  # 沒有混進報酬統計


# ---------------------------------------------------------------- --forecast（固定預測題 p_5d_beat_0050）

def _flat(entry, exit_, n=FORECAST_H):
    o = [entry] + [entry] * (n - 1)
    c = [entry] * (n - 1) + [exit_]
    return _bars(o, o, c, c)


def test_forecast_outcome_costs_are_per_leg():
    """兩腿成本分開：個股 0.3% 稅、0050 0.1% 稅。兩腿報酬相同時，0050 因為稅低而淨報酬較高。"""
    net_s, net_b, y = forecast_outcome(
        _flat(100, 110), _flat(100, 110),
        stock_tax=STOCK_TRANSACTION_TAX_RATE, bench_tax=ETF_TRANSACTION_TAX_RATE)
    assert net_s == pytest.approx(round_trip_return(100, 110, entry_notional=DEFAULT_NOTIONAL,
                                                    tax_rate=STOCK_TRANSACTION_TAX_RATE))
    assert net_b == pytest.approx(round_trip_return(100, 110, entry_notional=DEFAULT_NOTIONAL,
                                                    tax_rate=ETF_TRANSACTION_TAX_RATE))
    assert net_b > net_s and y == 0   # 同樣漲 10%：稅率差讓個股贏不了 0050


def test_forecast_outcome_edge_where_only_split_costs_flip_y():
    # 個股比 0050 多漲 0.15%：總成本差 0.2%（稅 0.3% vs 0.1%）→ 扣成本後個股輸；兩腿都用個股稅會誤判成贏
    s_bars, b_bars = _flat(100, 110.15), _flat(100, 110)
    _, _, y_split = forecast_outcome(s_bars, b_bars, stock_tax=STOCK_TRANSACTION_TAX_RATE,
                                     bench_tax=ETF_TRANSACTION_TAX_RATE)
    _, _, y_same = forecast_outcome(s_bars, b_bars, stock_tax=STOCK_TRANSACTION_TAX_RATE,
                                    bench_tax=STOCK_TRANSACTION_TAX_RATE)
    assert (y_split, y_same) == (0, 1)


def test_forecast_outcome_none_when_a_leg_is_missing_or_incomplete():
    ok = _flat(100, 105)
    no_open = _bars([float("nan")] + [100] * 4, [100] * 5, [100] * 5, [100] * 5)
    no_close = _bars([100] * 5, [100] * 5, [100] * 5, [100] * 4 + [float("nan")])
    for bad in (no_open, no_close):
        assert forecast_outcome(bad, ok, stock_tax=0.003, bench_tax=0.001) is None
        assert forecast_outcome(ok, bad, stock_tax=0.003, bench_tax=0.001) is None


def test_baseline_uses_only_events_resolved_before_forecast_day_and_laplace():
    day = pd.to_datetime(["2026-01-05", "2026-01-12", "2026-01-12"])
    resolved = pd.to_datetime(["2026-01-09", "2026-01-12", "2026-01-16"])
    y = [1, 0, 1]
    probs, n = baseline_probs(day, resolved, y)
    # 第 1 筆：沒有歷史 → (0+1)/(0+2)；第 2、3 筆：只看得到 01-09 那筆（y=1；01-12 當天才收盤的不算）
    assert list(n) == [0, 1, 1]
    assert probs.tolist() == pytest.approx([0.5, 2 / 3, 2 / 3])


def test_baseline_window_is_252_days():
    day = pd.to_datetime(["2027-01-04"])
    old = baseline_probs(day.repeat(1), pd.to_datetime(["2026-01-02"]).repeat(1), [1])   # 367 天前：窗外
    assert old[1].tolist() == [0]
    inside = baseline_probs(day, pd.to_datetime(["2026-06-01"]), [1])
    assert inside[1].tolist() == [1]


def test_date_block_ci_resamples_dates_not_events():
    rng = np.random.default_rng(0)
    dates = pd.to_datetime(pd.date_range("2026-01-01", periods=60).repeat(5))
    vals = np.repeat(rng.normal(0.5, 0.1, 60), 5)   # 同日 5 檔完全相關
    ci5 = date_block_ci(vals, dates, block=5, n=500, seed=1)
    ci10 = date_block_ci(vals, dates, block=10, n=500, seed=1)
    assert ci5[0] > 0 and ci10[0] > 0 and ci5[0] < vals.mean() < ci5[1]
    # 日期數不足 2×block → None（呼叫端標 inconclusive）
    assert date_block_ci(vals[:25], dates[:25], block=5, n=100) is None
    # 兩組差：同分布 → CI 跨零
    other = np.repeat(rng.normal(0.5, 0.1, 60), 5)
    diff = date_block_ci(vals, dates, block=5, n=500, seed=1, other=(other, dates))
    assert diff[0] < 0 < diff[1]


def test_date_block_ci_block_length_widens_ci_for_serially_correlated_series():
    """5 日標籤重疊 → 相鄰日期相關；block 越長區間越寬。把 block 忽略（逐日重抽）兩個寬度會一樣。"""
    n_days = 120
    dates = pd.to_datetime(pd.date_range("2026-01-01", periods=n_days))
    vals = np.sin(np.arange(n_days) / 8.0) + np.random.default_rng(3).normal(0, 0.05, n_days)
    w1 = np.subtract(*date_block_ci(vals, dates, block=1, n=1000, seed=7)[::-1])
    w10 = np.subtract(*date_block_ci(vals, dates, block=10, n=1000, seed=7)[::-1])
    assert w10 > 1.5 * w1


def test_rank_ic_signs():
    assert rank_ic([0.1, 0.5, 0.9, 0.7], [-1, 0, 2, 1]) == pytest.approx(1.0)
    assert rank_ic([0.1, 0.5, 0.9, 0.7], [2, 1, -1, 0]) == pytest.approx(-1.0)
    assert np.isnan(rank_ic([0.5, 0.5, 0.5], [1, 2, 3]))


def test_macro_ctx_label_reads_experiments_and_defaults_to_none():
    assert macro_ctx_label(json.dumps({"dashboard": {"experiments": {"macro_ctx": "on"}}})) == "on"
    assert macro_ctx_label(json.dumps({"dashboard": {}})) == "none"
    assert macro_ctx_label("not json") == "none"


def _forecast_panels(n_days=40):
    cal = pd.bdate_range("2026-01-05", periods=n_days)
    px = {k: pd.DataFrame({"2330": 100.0, "0050": 100.0}, index=cal) for k in ("open", "high", "low", "close")}
    px["adj"] = pd.DataFrame({"2330": 1.0, "0050": 1.0}, index=cal)
    return px, cal


def test_build_forecast_events_window_exclusions_and_kind():
    panels, cal = _forecast_panels()
    panels["close"].loc[cal[6], "2330"] = 110.0   # 報告日 cal[0] 之後 T+1=cal[1]，第 5 日＝cal[5]；cal[6] 不在窗內
    panels["close"].loc[cal[5], "2330"] = 108.0
    reports = pd.DataFrame({
        "code": ["2330.TW", "0050.TW", "2330.TW"], "stock_id": ["2330", "0050", "2330"],
        "day": [cal[0], cal[0], cal[-2]], "p": [0.6, 0.6, 0.6], "ctx": ["on", "on", "on"]})
    ev = build_forecast_events(reports, panels)
    assert len(ev) == 1   # 0050 本身排除；視窗沒走完的排除
    row = ev.iloc[0]
    assert row["resolved_at"] == cal[5] and row["y"] == 1 and row["kind"] == "stock"


def test_render_forecast_inconclusive_when_sample_small_and_reports_arms():
    panels, cal = _forecast_panels(30)
    rows = []
    for i in range(3):
        rows.append({"code": "2330.TW", "stock_id": "2330", "day": cal[i], "p": 0.6, "ctx": "on"})
    ev = build_forecast_events(pd.DataFrame(rows), panels)
    args = type("A", (), {"bootstrap": 200, "seed": 1})()
    text = render_forecast(ev, args)
    assert "inconclusive" in text and "固定預測題" in text
    assert "沒有已走完" in render_forecast(pd.DataFrame(), args)


def test_forecast_scores_brier_and_d_sign():
    ev = pd.DataFrame({
        "day": pd.to_datetime(["2026-03-02"] * 2), "resolved_at": pd.to_datetime(["2026-03-02"] * 2),
        "p": [0.9, 0.1], "y": [1, 1], "net_stock": [0.01, 0.01], "net_bench": [0.0, 0.0],
        "ctx": ["on", "on"], "kind": ["stock", "stock"], "code": ["a", "b"]})
    sc = forecast_scores(ev)
    assert sc["brier"].tolist() == pytest.approx([0.01, 0.81])
    assert (sc["d"] > 0).tolist() == [True, False]   # 預測準的 d>0（比基準好），預測反的 d<0


def test_build_forecast_events_uses_etf_tax_for_the_0050_leg():
    """端到端：個股比 0050 多漲 0.15%，成本差 0.2%（稅 0.3% vs 0.1%）→ 個股輸。兩腿都用個股稅會誤判成贏。"""
    panels, cal = _forecast_panels()
    for k in ("open", "high", "low", "close"):
        panels[k].loc[cal[1]:, "0050"] = 100.0
    panels["close"].loc[cal[5], "2330"] = 110.15
    panels["close"].loc[cal[5], "0050"] = 110.0
    reports = pd.DataFrame({"code": ["2330.TW"], "stock_id": ["2330"], "day": [cal[0]], "p": [0.6], "ctx": ["on"]})
    ev = build_forecast_events(reports, panels)
    assert ev.iloc[0]["y"] == 0 and ev.iloc[0]["net_stock"] > 0
