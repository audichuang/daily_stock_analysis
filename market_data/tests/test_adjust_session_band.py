"""``adjust.infer_rows`` 的複利漲跌停門檻（M4）與漲跌停帶吸附分割（M5）。

全部用記憶體內價格（monkeypatch ``pd.read_sql``），不碰 DB；交易日曆以 ``is_session``
注入，與本機 exchange_calendars 版本、臨時休市清單無關。
"""

from datetime import date, timedelta

import pandas as pd
import pytest

from market_data import adjust

START = date(2024, 1, 1)


def _weekdays(skip=()):
    skip = {pd.Timestamp(d).date() for d in skip}
    return lambda d: d.weekday() < 5 and d not in skip


def _history(end, n=10, price=None):
    """``end`` 之前 n 個平日的平盤 K（湊滿 MIN_BARS_BEFORE，且全在 START 之後）。"""
    days, d = [], pd.Timestamp(end) - timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return [dict(date=d, open=price, high=price, low=price, close=price, change=0.0)
            for d in sorted(days)]


def _run(monkeypatch, stock_id, bars, is_session=None, others=None, start=START):
    """``others``：{代號: K 線}，同一張 price 表裡的其他股票（決定哪些日期是全市場有列）。"""
    px = pd.DataFrame([{**b, "stock_id": stock_id} for b in bars]
                      + [{**b, "stock_id": sid} for sid, rows in (others or {}).items() for b in rows])
    px["date"] = pd.to_datetime(px["date"])
    monkeypatch.setattr(adjust.pd, "read_sql", lambda *a, **k: px.copy())
    rows = adjust.infer_rows(None, set(), start, is_session=is_session or _weekdays())
    return rows[rows["stock_id"] == stock_id]


def _bar(day, o, h, lo, c, ch):
    return dict(date=pd.Timestamp(day), open=o, high=h, low=lo, close=c, change=ch)


# --- M4：中間有沒成交的交易日，門檻按交易日數複利 ---

def test_6103_two_limit_downs_across_untraded_session_is_not_an_event(monkeypatch):
    # 6103：03-08 收 38.45，03-11（週一，交易日）無成交，03-12 開 31.95 = 兩根合法跌停
    bars = _history("2024-03-08", price=38.45) + [
        _bar("2024-03-08", 38.45, 38.45, 38.45, 38.45, 0.0),
        _bar("2024-03-12", 31.95, 32.5, 31.95, 32.0, None),
    ]
    assert _run(monkeypatch, "6103", bars).empty


@pytest.mark.parametrize("opened, event_day", [
    (53.15, "2024-03-18"), (48.0, "2024-03-19"), (53.0, "2024-03-18"),
])
def test_multi_session_limit_locked_legal_decline_is_not_an_event(monkeypatch, opened, event_day):
    # 分別接近 6、7、6 次跌停（含升降單位捨入），不可被價格帶吸附成 1:2 分割。
    bars = _history("2024-03-08", price=100.0) + [
        _bar("2024-03-08", 100.0, 100.0, 100.0, 100.0, 0.0),
        _bar(event_day, opened, opened, opened, opened, 0.0),
    ]
    assert _run(monkeypatch, "6103", bars).empty


@pytest.mark.parametrize("opened, event_day", [(48.0, "2024-03-18"), (53.0, "2024-03-15")])
def test_multi_session_limit_locked_gap_beyond_band_snaps_to_unique_split(monkeypatch, opened, event_day):
    # 6 個交易日跌到 48、5 個交易日跌到 53 皆超過複利門檻，且只符合 1:2 的價格帶。
    bars = _history("2024-03-08", price=100.0) + [
        _bar("2024-03-08", 100.0, 100.0, 100.0, 100.0, 0.0),
        _bar(event_day, opened, opened, opened, opened, 0.0),
    ]
    row, = _run(monkeypatch, "6103", bars).to_dict("records")
    assert row["kind"] == "split"
    assert row["factor"] == 0.5
    assert row["reference_price"] == 50.0


def test_non_session_days_do_not_widen_the_band(monkeypatch):
    # 同樣 -16.9%，但中間只隔週末（非交易日）：n=1，仍是單日門檻 → 推導
    bars = _history("2024-03-08", price=38.45) + [
        _bar("2024-03-08", 38.45, 38.45, 38.45, 38.45, 0.0),
        _bar("2024-03-11", 31.95, 32.5, 31.95, 32.0, None),
    ]
    hit = _run(monkeypatch, "6104", bars)
    assert len(hit) == 1 and hit.iloc[0]["kind"] == "inferred"


def test_typhoon_closure_from_calendar_is_not_counted(monkeypatch):
    # 03-11 是休市日（日曆說非交易日）：沒有交易日被跳過，-16.9% 仍超過單日限制
    bars = _history("2024-03-08", price=38.45) + [
        _bar("2024-03-08", 38.45, 38.45, 38.45, 38.45, 0.0),
        _bar("2024-03-12", 31.95, 32.5, 31.95, 32.0, None),
    ]
    hit = _run(monkeypatch, "6105", bars, is_session=_weekdays(skip={"2024-03-11"}))
    assert len(hit) == 1


def test_gap_beyond_compounded_band_is_still_inferred(monkeypatch):
    # 隔一個交易日，-25% 超過兩根跌停的 0.89² = 0.792 → 仍是公司行動
    bars = _history("2024-03-08", price=40.0) + [
        _bar("2024-03-08", 40.0, 40.0, 40.0, 40.0, 0.0),
        _bar("2024-03-12", 30.0, 30.5, 29.8, 30.2, None),
    ]
    hit = _run(monkeypatch, "6106", bars)
    assert len(hit) == 1 and hit.iloc[0]["kind"] == "inferred"


def test_single_session_unexplained_20pct_gap_is_still_inferred(monkeypatch):
    bars = _history("2024-03-08", price=50.0) + [
        _bar("2024-03-08", 50.0, 50.0, 50.0, 50.0, 0.0),
        _bar("2024-03-11", 40.0, 40.5, 39.8, 40.0, None),
    ]
    hit = _run(monkeypatch, "6107", bars)
    assert len(hit) == 1
    assert hit.iloc[0]["kind"] == "inferred"
    assert hit.iloc[0]["factor"] == pytest.approx(0.8)


def test_ordinary_within_band_move_is_not_an_event(monkeypatch):
    bars = _history("2024-03-08", price=50.0) + [
        _bar("2024-03-08", 50.0, 50.0, 50.0, 50.0, 0.0),
        _bar("2024-03-11", 47.5, 48.0, 47.0, 47.5, -2.5),
    ]
    assert _run(monkeypatch, "6108", bars).empty


def test_exact_split_after_many_untraded_sessions_bypasses_compound_band(monkeypatch):
    # 減資停止買賣 8 個交易日後 2 倍復牌：1.11^8 ≈ 2.30 > 2，複利門檻會把它吞掉；
    # 精確比例不受複利限制（停止買賣期間參考價不逐日累積）
    bars = _history("2024-03-08", price=10.0) + [
        _bar("2024-03-08", 10.0, 10.0, 10.0, 10.0, 0.0),
        _bar("2024-03-20", 20.0, 20.5, 19.8, 20.0, None),
    ]
    hit = _run(monkeypatch, "6109", bars)
    assert len(hit) == 1
    assert hit.iloc[0]["kind"] == "split" and hit.iloc[0]["factor"] == 2.0


def test_falls_back_to_observed_dates_when_calendar_raises(monkeypatch):
    # 日曆拋例外（超出範圍）→ 用 price 裡出現過的日期當交易日：另一檔 03-11 有成交
    def broken(_d):
        raise ValueError("out of calendar range")
    other = [_bar(d["date"], 1, 1, 1, 1, 0.0) for d in _history("2024-03-13", n=12)]
    mine = _history("2024-03-08", price=38.45) + [
        _bar("2024-03-08", 38.45, 38.45, 38.45, 38.45, 0.0),
        _bar("2024-03-12", 31.95, 32.5, 31.95, 32.0, None),
    ]
    px = pd.DataFrame([{**b, "stock_id": "6110"} for b in mine]
                      + [{**b, "stock_id": "1111"} for b in other])
    monkeypatch.setattr(adjust.pd, "read_sql", lambda *a, **k: px.copy())
    rows = adjust.infer_rows(None, set(), START, is_session=broken)
    assert rows[rows["stock_id"] == "6110"].empty


def test_session_index_unions_observed_dates_without_inventing_sessions():
    observed = pd.to_datetime(["2016-06-06", "2016-06-04", "2016-06-02", "2016-06-04"])
    sessions = adjust._session_index("2016-06-02", "2016-06-06", observed, _weekdays())
    # 週五即使全市場缺列仍保留；週六補班有成交才納入，週日不得憑空放寬門檻。
    expected = pd.to_datetime(["2016-06-02", "2016-06-03", "2016-06-04", "2016-06-06"])
    pd.testing.assert_index_equal(sessions, expected)
    assert adjust._sessions_between(["2016-06-02"], ["2016-06-04"], sessions).tolist() == [2]


@pytest.mark.parametrize("previous_day, event_day, makeup_day, stock_id, previous, opened", [
    ("2016-06-02", "2016-06-04", "2016-06-04", "5348", 7.84, 6.37),
    ("2016-01-29", "2016-02-01", "2016-01-30", "5455", 100.0, 85.69),
    ("2016-01-29", "2016-02-01", "2016-01-30", "4131", 100.0, 111.65),
])
def test_observed_makeup_sessions_prevent_false_adjustments(
        monkeypatch, previous_day, event_day, makeup_day, stock_id, previous, opened):
    bars = _history(previous_day, price=previous) + [
        _bar(previous_day, previous, previous, previous, previous, 0.0),
        _bar(event_day, opened, opened, opened, opened, 0.0),
    ]
    # 日期須在移除每檔首根 K（prev 為空）之前收集：補班日只由他檔首根 K 證明時仍算交易日。
    px = pd.DataFrame([{**b, "stock_id": stock_id} for b in bars] + [
        {**_bar(makeup_day, 10.0, 10.0, 10.0, 10.0, 0.0), "stock_id": "9998"},
    ])
    monkeypatch.setattr(adjust.pd, "read_sql", lambda *a, **k: px.copy())
    assert adjust.infer_rows(None, set(), event_day, is_session=_weekdays()).empty


# --- M5：change 不可用時，分割首日鎖漲跌停 ---

@pytest.mark.parametrize("change", [0.0, None])
@pytest.mark.parametrize("event_day", ["2024-03-18", "2024-03-20"])
def test_suspended_half_split_locked_limit_up_inside_compounded_band_is_not_inferred(monkeypatch, change, event_day):
    # 已知限制：跨 6／8 場停牌後 1:2 鎖漲停（55.5）落在複利範圍內，單看價格分不出它和
    # 連續漲跌停；寧可漏記也不把歷史價整段乘 0.5，待接官方「變更面額恢復買賣」資料補上。
    bars = _history("2024-03-08", price=101.0) + [
        _bar("2024-03-08", 101.0, 101.0, 101.0, 101.0, 0.0),
        _bar(event_day, 55.5, 55.5, 55.5, 55.5, change),
    ]
    assert _run(monkeypatch, "6103", bars).empty


@pytest.mark.parametrize("change", [0.0, None])
@pytest.mark.parametrize("event_day", ["2024-03-19", "2024-03-21"])
def test_seven_limit_downs_with_tick_rounding_are_not_an_event(monkeypatch, change, event_day):
    # 100 × 0.9^7 ≈ 47.82969，取到 47.8；跨 7／9 場皆可由七次跌停解釋。
    bars = _history("2024-03-08", price=100.0) + [
        _bar("2024-03-08", 100.0, 100.0, 100.0, 100.0, 0.0),
        _bar(event_day, 47.8, 47.8, 47.8, 47.8, change),
    ]
    assert _run(monkeypatch, "6103", bars).empty


@pytest.mark.parametrize("opened, is_split", [(47.65, False), (48.05, False), (47.55, False), (48.1, False)])
def test_consecutive_limit_guard_has_small_relative_tolerance(monkeypatch, opened, is_split):
    # 七次跌停理論價約 47.82969 附近：落在複利範圍內一律不推導成分割（含捨入後的 47.55／48.1）。
    bars = _history("2024-03-08", price=100.0) + [
        _bar("2024-03-08", 100.0, 100.0, 100.0, 100.0, 0.0),
        _bar("2024-03-19", opened, opened, opened, opened, 0.0),
    ]
    rows = _run(monkeypatch, "6103", bars)
    assert (len(rows) == 1) == is_split
    if is_split:
        assert rows.iloc[0]["kind"] == "split"
        assert rows.iloc[0]["factor"] == 0.5


def test_true_1_to_10_split_locked_limit_up_snaps_to_exact_tenth(monkeypatch):
    # 6919 2025-07-21：停牌前末筆在 07-11，跨 6 個交易日；參考價 121.5、鎖漲停 133.5。
    bars = _history("2025-07-11", price=1215.0) + [
        _bar("2025-07-11", 1215.0, 1215.0, 1215.0, 1215.0, 0.0),
        _bar("2025-07-21", 133.5, 133.5, 133.5, 133.5, 0.0),
    ]
    hit = _run(monkeypatch, "6919", bars)
    assert len(hit) == 1
    row = hit.iloc[0]
    assert row["kind"] == "split"
    assert row["factor"] == 0.1
    assert row["reference_price"] == pytest.approx(121.5)


def test_split_locked_limit_down_snaps_too(monkeypatch):
    # 1:10，首日鎖跌停 109.5（參考價 121.5 × 0.9 → 取到升降單位）
    bars = _history("2025-07-11", price=1215.0) + [
        _bar("2025-07-11", 1215.0, 1215.0, 1215.0, 1215.0, 0.0),
        _bar("2025-07-21", 109.5, 109.5, 109.5, 109.5, None),
    ]
    hit = _run(monkeypatch, "6920", bars)
    assert len(hit) == 1 and hit.iloc[0]["factor"] == 0.1


def test_1_to_2_5_split_snaps_to_0_4(monkeypatch):
    # 6548 型 1:2.5：前收 250、參考價 100、開盤鎖漲停 110、change 缺值
    bars = _history("2025-07-11", price=250.0) + [
        _bar("2025-07-11", 250.0, 250.0, 250.0, 250.0, 0.0),
        _bar("2025-07-21", 110.0, 110.0, 108.0, 110.0, None),
    ]
    hit = _run(monkeypatch, "6548", bars)
    assert len(hit) == 1
    assert hit.iloc[0]["kind"] == "split"
    assert hit.iloc[0]["factor"] == pytest.approx(0.4)


def test_limit_locked_split_after_longer_suspension_uses_exact_reference(monkeypatch):
    # 合成停牌 20 天、跨 14 個交易日：跌幅超出複利範圍，吸附後須保留分割的長 gap 例外。
    bars = _history("2025-07-01", price=1215.0) + [
        _bar("2025-07-01", 1215.0, 1215.0, 1215.0, 1215.0, 0.0),
        _bar("2025-07-21", 133.5, 133.5, 133.5, 133.5, 0.0),
    ]
    row, = _run(monkeypatch, "6923", bars).to_dict("records")
    assert row["kind"] == "split"
    assert row["factor"] == 0.1
    assert row["reference_price"] == 121.5


def test_snap_to_split_knows_2_5():
    assert adjust._snap_to_split(0.401) == (0.4, True)


def test_bar_range_outside_every_band_is_not_snapped(monkeypatch):
    # 反向：change 不可用但當日區間太寬，塞不進任何 prev/N 的漲跌停帶 → 不硬吸附
    bars = _history("2025-07-18", price=100.0) + [
        _bar("2025-07-18", 100.0, 100.0, 100.0, 100.0, 0.0),
        _bar("2025-07-21", 37.0, 45.0, 31.0, 44.0, None),
    ]
    hit = _run(monkeypatch, "6921", bars)
    assert len(hit) == 1
    assert hit.iloc[0]["kind"] == "inferred"
    assert hit.iloc[0]["factor"] == pytest.approx(0.37)  # 開盤價代理，不是 1/N 吸附值
    assert hit.iloc[0]["reference_price"] == pytest.approx(37.0)


def test_usable_change_is_not_overridden_by_band_snap(monkeypatch):
    # 反向：change 可用時以官方參考價為準。前收 20、官方參考價 10.6（close 11 - change 0.4，
    # 因子 0.53 的減資），當日區間 [10.5, 11] 碰巧也塞得進 prev/2 = 10 的漲跌停帶——不可改吸附成 0.5。
    # 日期須在 CHANGE_SIGNED_SINCE 之後，change 才算可用。
    bars = _history("2026-09-11", price=20.0) + [
        _bar("2026-09-11", 20.0, 20.0, 20.0, 20.0, 0.0),
        _bar("2026-09-14", 10.8, 11.0, 10.5, 11.0, 0.4),
    ]
    hit = _run(monkeypatch, "6922", bars)
    assert len(hit) == 1
    assert hit.iloc[0]["kind"] == "inferred"
    assert hit.iloc[0]["factor"] == pytest.approx(0.53)


# --- 補班週六：XTAI 日曆沒有，但 price 表全市場有列 ---

_MAKEUP_START = date(2016, 1, 1)


def _market(days, extra=()):
    """三檔平盤的其他股票，在 ``days`` 的平日與 ``extra`` 列出的日子都有成交。"""
    dates = [d for d in pd.date_range(days[0], days[1]) if d.weekday() < 5] + [pd.Timestamp(e) for e in extra]
    return {sid: [_bar(d, 10.0, 10.0, 10.0, 10.0, 0.0) for d in sorted(dates)]
            for sid in ("1101", "1102", "1103")}


def _5348(event_change=None):
    # 5348：2016-06-02（四）收 7.84、06-03（五）無成交、06-04（補班週六）開 6.37 = 兩根合法跌停
    return _history("2016-06-02", price=7.84) + [
        _bar("2016-06-02", 7.84, 7.84, 7.84, 7.84, 0.0),
        _bar("2016-06-04", 6.37, 6.4, 6.37, 6.4, event_change),
    ]


def test_makeup_saturday_traded_market_wide_counts_as_a_session(monkeypatch):
    # XTAI（以平日替身）沒有 06-04；全市場在 06-04 有列 → 06-03、06-04 兩個交易日，0.9² 內不是事件
    others = _market(("2016-05-16", "2016-06-08"), extra=("2016-06-04",))
    assert _run(monkeypatch, "5348", _5348(), others=others, start=_MAKEUP_START).empty


def test_saturday_row_of_only_the_event_stock_does_not_widen_the_band(monkeypatch):
    # 反向：週六只有這一檔自己有列（其他股票沒開盤）→ 不算全市場交易日，仍是單日門檻 → 推導
    others = _market(("2016-05-16", "2016-06-08"))
    hit = _run(monkeypatch, "5348", _5348(), others=others, start=_MAKEUP_START)
    assert len(hit) == 1 and hit.iloc[0]["kind"] == "inferred"
    assert hit.iloc[0]["factor"] == pytest.approx(6.37 / 7.84)


def test_stray_row_on_a_holiday_does_not_widen_the_band(monkeypatch):
    # 反向：03-11 休市，只有一檔其他股票有零星列 → 不可把休市日算成交易日放寬門檻
    others = {sid: [b for b in rows if b["date"] != pd.Timestamp("2024-03-11")]
              for sid, rows in _market(("2024-02-19", "2024-03-15")).items()}
    others["1101"].append(_bar("2024-03-11", 10.0, 10.0, 10.0, 10.0, 0.0))
    bars = _history("2024-03-08", price=38.45) + [
        _bar("2024-03-08", 38.45, 38.45, 38.45, 38.45, 0.0),
        _bar("2024-03-12", 31.95, 32.5, 31.95, 32.0, None),
    ]
    hit = _run(monkeypatch, "6105", bars, others=others, is_session=_weekdays(skip={"2024-03-11"}))
    assert len(hit) == 1


def test_session_index_is_calendar_union_full_market_dates():
    observed = pd.to_datetime(["2016-06-03"] * 3 + ["2016-06-04"] * 3 + ["2016-06-05"])
    sessions = adjust._session_index(observed.min(), observed.max(), observed, is_session=_weekdays())
    assert list(sessions) == list(pd.to_datetime(["2016-06-03", "2016-06-04"]))


# --- change 的正負號只在 CHANGE_SIGNED_SINCE 之後可信；之前要由漲跌停帶證明方向 ---

def _flipped(event_day, prev_day):
    # 官方參考價 100、開 105、收 103，change 真值 +3 卻存成 -3（舊回補翻錯號）→ close - change = 106，
    # 仍在開盤 ±11% 內，守門擋不住
    return _history(prev_day, price=80.0) + [
        _bar(prev_day, 80.0, 80.0, 80.0, 80.0, 0.0),
        _bar(event_day, 105.0, 106.0, 102.0, 103.0, -3.0),
    ]


@pytest.mark.parametrize("event_day, prev_day", [("2025-07-21", "2025-07-18"), ("2026-08-22", "2026-08-21")])
def test_ambiguous_change_sign_before_signed_since_falls_back_to_open(monkeypatch, event_day, prev_day):
    # 100 與 106 的漲跌停帶都塞得下當日 [102, 106]：方向證明不了 → 開盤價代理
    row, = _run(monkeypatch, "8418", _flipped(event_day, prev_day)).to_dict("records")
    assert row["reference_price"] == pytest.approx(105.0)     # 開盤價代理，不是 106
    assert row["factor"] == pytest.approx(105.0 / 80.0)


@pytest.mark.parametrize("event_day, prev_day", [("2026-08-23", "2026-08-21"), ("2026-09-14", "2026-09-11")])
def test_change_on_or_after_signed_since_is_trusted(monkeypatch, event_day, prev_day):
    # 反向：截止日當天（含）起 change 帶正確號，照舊用 close - change
    row, = _run(monkeypatch, "8418", _flipped(event_day, prev_day)).to_dict("records")
    assert row["reference_price"] == pytest.approx(106.0)


@pytest.mark.parametrize("stored_change", [-10.0, 10.0])
def test_band_proves_change_sign_before_signed_since(monkeypatch, stored_change):
    # 8932 2026-03-09：1:2 分割、整天鎖跌停 89.8、官方參考價 99.8。截止日前 change 的號不可信，
    # 但 79.8 的漲停上限約 88.2 塞不下 89.8，只有 99.8 成立 → 不論存成 ±10 都還原成精確 1:2。
    bars = _history("2026-02-24", price=199.5) + [
        _bar("2026-02-24", 193.0, 200.0, 188.5, 199.5, 7.5),
        _bar("2026-03-09", 89.8, 89.8, 89.8, 89.8, stored_change),
    ]
    row, = _run(monkeypatch, "8932", bars).to_dict("records")
    assert row["kind"] == "split"
    assert row["factor"] == 0.5
    assert row["reference_price"] == pytest.approx(99.8)


def test_band_proven_reference_needs_exactly_one_candidate():
    s = lambda *v: pd.Series(v, dtype=float)   # noqa: E731
    # 依序：漲停上限排除 79.8（88.2 塞不下 89.8，→ 99.8）、跌停下限排除 99（低點 85 < 99×0.9，→ 91）、
    # 漲停上限排除 101（高點 114 > 101×1.1，→ 109）、兩個都成立（100／106）、兩個都不成立（區間太寬）
    got = adjust._band_proven_reference(
        close=s(89.8, 95.0, 105.0, 103.0, 50.0), change=s(10.0, -4.0, 4.0, -3.0, 1.0),
        low=s(89.8, 85.0, 100.0, 102.0, 40.0),
        high=s(89.8, 96.0, 114.0, 106.0, 60.0), lim=s(0.10, 0.10, 0.10, 0.10, 0.10))
    assert got.iloc[0] == pytest.approx(99.8)
    assert got.iloc[1] == pytest.approx(91.0)
    assert got.iloc[2] == pytest.approx(109.0)
    assert got.iloc[3:].isna().all()
