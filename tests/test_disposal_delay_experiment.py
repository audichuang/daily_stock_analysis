# -*- coding: utf-8 -*-
"""處置公告延後進場實驗（`measure_signal_forward --disposal-cache` 與
`fetch_twse_disposal_history`）的純函式測試，不碰 DB／網路。"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fetch_twse_disposal_history import (  # noqa: E402
    cn_number,
    dedupe,
    parse_punish_payload,
    session_lengths,
)
from measure_signal_forward import (  # noqa: E402
    DEFAULT_POSITION_NOTIONAL,
    disposal_arm_returns,
    disposal_context,
    disposal_verdict,
    exclusion_block_bootstrap,
    report_disposal,
)
from tw_trade_costs import round_trip_return  # noqa: E402

DAYS = pd.bdate_range("2026-01-05", periods=40)


def _ev(ti, stock="1111"):
    return pd.DataFrame({"stock_id": [stock], "ti": [ti], "date": [DAYS[ti]], "r": [0.0]})


def _disp(announce, start, end, stock="1111"):
    return pd.DataFrame({"stock_id": [stock], "announce": [DAYS[announce]],
                         "start": [DAYS[start]], "end": [DAYS[end]]})


# ── 受影響事件的判定 ─────────────────────────────────────────────


def test_announced_on_signal_day_covering_entry_is_affected():
    ctx = disposal_context(_ev(10), _disp(10, 11, 15), DAYS, h=5)
    assert ctx.at[0, "affected"]
    assert ctx.at[0, "a_idx"] == 10 and ctx.at[0, "e_idx"] == 15


def test_ongoing_disposal_announced_earlier_is_affected():
    ctx = disposal_context(_ev(10), _disp(6, 7, 11), DAYS, h=5)
    assert ctx.at[0, "affected"]


def test_announcement_after_signal_day_is_not_affected_but_counted_as_later():
    """D+2 才公告的處置在進場時不可知：不能入受影響組（前視），只記在 later。"""
    ctx = disposal_context(_ev(10), _disp(12, 13, 17), DAYS, h=5)
    assert not ctx.at[0, "affected"]
    assert ctx.at[0, "later"]


def test_announcement_after_signal_day_is_rejected_even_if_period_covers_entry():
    """時點守門：公布日在 D 之後就不可知，即使登記的處置期（資料異常）已涵蓋 D+1。"""
    ctx = disposal_context(_ev(10), _disp(11, 11, 15), DAYS, h=5)
    assert not ctx.at[0, "affected"]


def test_disposal_that_ended_before_entry_is_not_affected():
    """反向檢查：只要「近期有處置」就算受影響是過度匹配——處置期須涵蓋 D+1。"""
    ctx = disposal_context(_ev(10), _disp(3, 4, 10), DAYS, h=5)
    assert not ctx.at[0, "affected"]


def test_other_stock_disposal_does_not_match():
    ctx = disposal_context(_ev(10), _disp(10, 11, 15, stock="2222"), DAYS, h=5)
    assert not ctx.at[0, "affected"]


def test_weekend_announcement_maps_to_previous_session():
    """週六公告（D=週五）在週一開盤前已公開，算受影響；a_idx 取週五。"""
    days = pd.bdate_range("2026-01-05", periods=20)          # 01-09 是週五
    fri = days.get_loc(pd.Timestamp("2026-01-09"))
    disp = pd.DataFrame({"stock_id": ["1111"], "announce": [pd.Timestamp("2026-01-10")],
                         "start": [days[fri + 1]], "end": [days[fri + 5]]})
    ev = pd.DataFrame({"stock_id": ["1111"], "ti": [fri], "date": [days[fri]], "r": [0.0]})
    ctx = disposal_context(ev, disp, days, h=5)
    assert ctx.at[0, "affected"] and ctx.at[0, "a_idx"] == fri


def test_announcement_after_panel_end_is_not_counted_as_later():
    """面板之後才公告的處置不能被 searchsorted 夾到最後一列、算成「持有中才公告」。"""
    after = DAYS[-1] + pd.Timedelta(days=7)
    disp = pd.DataFrame({"stock_id": ["1111"], "announce": [after],
                         "start": [after + pd.Timedelta(days=1)],
                         "end": [after + pd.Timedelta(days=10)]})
    ctx = disposal_context(_ev(34), disp, DAYS, h=5)          # ti + h == 最後一列
    assert not ctx.at[0, "later"] and not ctx.at[0, "affected"]


def test_announcement_on_last_panel_day_is_still_counted_as_later():
    """反向檢查：面板最後一天公告的仍在持有窗內，不能被一起丟掉。"""
    ctx = disposal_context(_ev(34), _disp(39, 39, 39), DAYS, h=5)
    assert ctx.at[0, "later"]


# ── 各臂報酬：持有長度不變 ──────────────────────────────────────


def _ret_panel():
    """第 t 列的毛報酬 = t/100，方便辨認取到哪一列。"""
    vals = np.arange(len(DAYS), dtype=float)[:, None] / 100
    return pd.DataFrame(vals, index=DAYS, columns=["1111"])


def test_delay_shifts_the_whole_holding_window_from_the_announcement():
    ev = _ev(10)
    ctx = disposal_context(ev, _disp(10, 11, 15), DAYS, h=5)
    arms = disposal_arm_returns(ev, ctx, _ret_panel(), delays=(3, 4))
    net = lambda t: round_trip_return(1.0, 1.0 + t / 100, entry_notional=DEFAULT_POSITION_NOTIONAL)  # noqa: E731
    # 延後 3：訊號日視為第 13 列（公告後第 4 個交易日開盤進場），整個持有窗跟著挪
    assert arms.at[0, "delay_3"] == pytest.approx(net(13))
    assert arms.at[0, "delay_4"] == pytest.approx(net(14))
    # 處置期後：以迄日（第 15 列）為訊號日
    assert arms.at[0, "after_end"] == pytest.approx(net(15))


def test_delay_never_enters_before_the_normal_entry():
    """公告早於訊號日夠久時，延後臂不可比正常進場更早（等於正常進場）。"""
    ev = _ev(10)
    ctx = disposal_context(ev, _disp(2, 3, 12), DAYS, h=5)
    arms = disposal_arm_returns(ev, ctx, _ret_panel(), delays=(3,))
    assert arms.at[0, "delay_3"] == pytest.approx(round_trip_return(1.0, 1.10, entry_notional=DEFAULT_POSITION_NOTIONAL))


def test_delayed_arm_past_panel_end_is_nan_not_settled():
    ev = _ev(38)
    ctx = disposal_context(ev, _disp(38, 39, 39), DAYS, h=5)
    ret = _ret_panel()
    arms = disposal_arm_returns(ev, ctx, ret, delays=(3,))
    assert np.isnan(arms.at[0, "delay_3"])


# ── report_disposal：配對、差的方向、表格基準 ─────────────────────


def _report_inputs():
    """三個受影響事件（一個被延後、一個處置中＝延後等於正常、一個延後臂右端截斷）與兩個未受影響事件。"""
    stocks = ["1111", "2222", "3333", "4444", "5555"]
    ret = pd.DataFrame(np.nan, index=DAYS, columns=stocks)
    ret.loc[DAYS[:35], :] = 0.0
    ret.iloc[10, 0], ret.iloc[13, 0] = 0.05, 0.40   # 1111：正常 +5%、延後 3 日 +40%
    ret.iloc[10, 2] = 0.20                           # 3333：公告後第 3 天才是訊號日，延後 3 日等於正常
    ret.iloc[:35, 3], ret.iloc[:35, 4] = 0.10, 0.30
    net = lambda g: round_trip_return(1.0, 1.0 + g, entry_notional=DEFAULT_POSITION_NOTIONAL)  # noqa: E731
    # 刻意不照股票代號排序，避免靠位置對齊碰巧對到
    ev = pd.DataFrame({"stock_id": ["3333", "2222", "5555", "1111", "4444"],
                       "ti": [10, 33, 10, 10, 12]}, index=[7, 3, 9, 1, 5])
    ev["date"] = DAYS[ev["ti"]]
    ev["r"] = [net(0.20), -0.50, net(0.30), net(0.05), net(0.10)]
    disp = pd.DataFrame({"stock_id": ["1111", "2222", "3333"],
                         "announce": DAYS[[10, 33, 7]], "start": DAYS[[11, 34, 8]],
                         "end": DAYS[[20, 39, 15]]})
    return ev, disp, ret, net


def test_report_disposal_pairs_arms_with_the_same_events_and_sign():
    ev, disp, ret, net = _report_inputs()
    s = report_disposal(ev, disp, ret, DAYS, 5, delays=(3,), n_boot=0)
    arm = s["arms"]["delay_3"]
    # 2222 的延後臂超出面板 → 不入配對；1111 被延後、3333 處置中（差 0）
    assert arm["n"] == 2 and arm["n_delayed"] == 1
    assert arm["d_mean"] == pytest.approx(((net(0.40) - net(0.05)) + 0.0) / 2)
    assert arm["d_mean"] > 0                                   # 臂 − 正常，不是反過來
    assert arm["d_hit"] == pytest.approx(0.5)
    # 表格的正常進場列要和臂同一批事件，不能混入被截掉的 −50% 事件
    assert arm["base_mean"] == pytest.approx((net(0.05) + net(0.20)) / 2)
    assert arm["arm_mean"] == pytest.approx((net(0.40) + net(0.20)) / 2)
    ex = s["arms"]["exclude"]
    assert s["n_affected"] == 3 and ex["n"] == 3
    assert ex["d_mean"] == pytest.approx((net(0.10) + net(0.30)) / 2 - ev["r"].mean())


def test_report_disposal_prints_paired_normal_row_per_arm(capsys):
    ev, disp, ret, _ = _report_inputs()
    report_disposal(ev, disp, ret, DAYS, 5, delays=(3,), n_boot=0)
    out = capsys.readouterr().out
    assert "正常進場（delay_3 配對）" in out and "正常進場（全部）" in out


# ── 判準與剔除的 bootstrap ──────────────────────────────────────


def test_verdict_requires_both_points_positive_and_interval_above_zero():
    assert disposal_verdict(40, 0.02, 0.01, (0.001, 0.04)) == "通過"
    assert disposal_verdict(40, 0.02, -0.01, (0.001, 0.04)) == "inconclusive"
    assert disposal_verdict(40, 0.02, 0.01, (-0.001, 0.04)) == "inconclusive"
    assert disposal_verdict(29, 0.02, 0.01, (0.001, 0.04)) == "inconclusive"
    assert disposal_verdict(40, -0.02, -0.01, (-0.04, -0.001)) == "較差"
    assert disposal_verdict(40, 0.02, 0.01, None) == "inconclusive"


def test_exclusion_bootstrap_matches_known_group_gap():
    """每天都有一個 r=0 的被剔除事件與一個 r=0.1 的未剔除事件：剔除效果恆為 +0.05。"""
    cal = np.arange(30)
    frame = pd.DataFrame({"date": np.repeat(cal, 2), "value": np.tile([0.0, 0.1], 30),
                          "excluded": np.tile([True, False], 30)})
    lo, hi = exclusion_block_bootstrap(frame, cal, n=200, block=5, seed=1)
    assert lo == pytest.approx(0.05) and hi == pytest.approx(0.05)


def test_exclusion_bootstrap_is_none_without_excluded_events():
    cal = np.arange(30)
    frame = pd.DataFrame({"date": cal, "value": 0.1, "excluded": False})
    assert exclusion_block_bootstrap(frame, cal, n=200, block=5, seed=1) is None


# ── 抓取與沿革 ──────────────────────────────────────────────────

_FIELDS = ["編號", "公布日期", "證券代號", "證券名稱", "累計", "處置條件", "處置起迄時間",
           "處置措施", "處置內容", "備註"]


def _payload(title="公布處置有價證券資訊 (110/01/01 至 110/06/30)"):
    content = ("２處置期間：自民國一百一十年六月十八日起至一百一十年七月一日﹝十個營業日，如遇休市"
               "則順延執行〕。\n３處置措施：\nａ以人工管制之撮合終端機執行撮合作業（約每二十分鐘撮合一次）。")
    return {"stat": "OK", "title": title, "fields": _FIELDS, "data": [
        [1, "*110/06/17", "2603", "長榮", 2, "連續三次", "110/06/18～110/07/01", "第二次處置",
         content, ""]]}


def test_parse_payload_reads_dates_minutes_and_stated_days():
    df = parse_punish_payload(_payload(), datetime.date(2021, 1, 1), datetime.date(2021, 6, 30))
    row = df.iloc[0]
    assert row["announce"] == datetime.date(2021, 6, 17)
    assert (row["start"], row["end"]) == (datetime.date(2021, 6, 18), datetime.date(2021, 7, 1))
    assert row["match_minutes"] == 20 and row["stated_days"] == 10
    assert row["stock_id"] == "2603"


def test_parse_payload_rejects_a_different_range():
    with pytest.raises(ValueError):
        parse_punish_payload(_payload(), datetime.date(2021, 7, 1), datetime.date(2021, 12, 31))


def test_dedupe_drops_rows_returned_by_both_overlapping_chunks():
    a = parse_punish_payload(_payload(), datetime.date(2021, 1, 1), datetime.date(2021, 6, 30))
    b = parse_punish_payload(_payload("公布處置有價證券資訊 (110/07/01 至 110/12/31)"),
                             datetime.date(2021, 7, 1), datetime.date(2021, 12, 31))
    assert len(dedupe(pd.concat([a, b], ignore_index=True))) == 1


@pytest.mark.parametrize("text,want", [("五", 5), ("十", 10), ("十二", 12), ("二十", 20),
                                       ("四十五", 45), ("２", 2), ("12", 12), ("百", None)])
def test_cn_number(text, want):
    assert cn_number(text) == want


def test_session_lengths_count_trading_days_inclusive():
    days = pd.bdate_range("2026-01-05", periods=20)
    disp = pd.DataFrame({"start": [days[1], pd.Timestamp("2026-01-10")],
                         "end": [days[5], pd.Timestamp("2026-01-16")]})
    assert list(session_lengths(disp, days)) == [5, 5]
