"""公司行動推斷的合成 K 線測試，不連資料庫（monkeypatch ``pd.read_sql``，日曆以 ``is_session`` 注入）。"""

import sys
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from market_data import adjust, closures, health


def _weekday(day):
    return day.weekday() < 5


def _prices(previous=100.0, opened=120.0, previous_day="2024-03-08",
            event_day="2024-03-11", change=0.0, low=None, high=None, close=None):
    bars = [{"stock_id": "6103", "date": day, "open": previous,
             "high": previous, "low": previous, "close": previous, "change": 0.0}
            for day in pd.bdate_range(end=previous_day, periods=8)]
    bars.append({"stock_id": "6103", "date": pd.Timestamp(event_day), "open": opened,
                 "high": opened if high is None else high,
                 "low": opened if low is None else low,
                 "close": opened if close is None else close, "change": change})
    return pd.DataFrame(bars)


def _infer(prices, is_session=_weekday):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(adjust.pd, "read_sql", lambda *a, **k: prices.copy())
        # is_session=None 時走預設日曆；此處固定成「取不到日曆」，與本機 exchange_calendars 無關。
        mp.setattr(health, "_xtai_session_checker", lambda autodetect=True: None)
        return adjust.infer_rows(None, set(), prices.iloc[-1]["date"].date(), is_session=is_session)


@pytest.mark.parametrize("opened", [31.95, 46.5])
def test_two_sessions_of_legal_moves_are_not_events(opened):
    prices = _prices(previous=38.45, opened=opened, event_day="2024-03-12")
    assert _infer(prices).empty


def test_adjacent_session_unexplained_gap_is_still_inferred():
    row, = _infer(_prices()).to_dict("records")
    assert row["factor"] == 1.2
    assert row["reference_price"] == 120.0
    assert row["kind"] == "inferred"
    assert row["source"] == "inferred_price"


@pytest.mark.parametrize("opened", [90.0, 100.0, 110.0])
def test_ordinary_move_has_no_event(opened):
    assert _infer(_prices(opened=opened)).empty


@pytest.mark.parametrize("change", [0.0, None])
def test_limit_locked_one_to_ten_split_uses_exact_reference(change):
    prices = _prices(previous=1215.0, opened=133.5, change=change,
                     previous_day="2025-07-11", event_day="2025-07-21")
    row, = _infer(prices).to_dict("records")
    assert row["factor"] == 0.1
    assert row["reference_price"] == 121.5
    assert row["kind"] == "split"
    assert row["source"] == "inferred_price"


@pytest.mark.parametrize("opened, is_split", [(54.0, False), (55.2, False), (53.15, False)])
def test_multi_session_band_snap_excludes_consecutive_limit_moves(opened, is_split):
    # 跨 6 場：54.0、55.2（落在複利範圍內的 1:2 價格帶）和
    # 接近六次跌停的 53.15 單看價格分不出連續漲跌停，保守不推導（已知限制，待接官方面額變更資料）。
    prices = _prices(opened=opened, event_day="2024-03-18")
    rows = _infer(prices)
    assert (len(rows) == 1) == is_split
    if is_split:
        assert rows.iloc[0]["kind"] == "split" and rows.iloc[0]["factor"] == 0.5


@pytest.mark.parametrize("opened, factor", [(40.0, 0.4), (250.0, 2.5)])
def test_noninteger_split_ratio_is_supported(opened, factor):
    row, = _infer(_prices(opened=opened)).to_dict("records")
    assert row["factor"] == factor
    assert row["reference_price"] == opened
    assert row["kind"] == "split"


def test_limit_locked_one_to_two_point_five_split_uses_band():
    row, = _infer(_prices(opened=44.0)).to_dict("records")
    assert row["factor"] == 0.4
    assert row["reference_price"] == 40.0
    assert row["kind"] == "split"


@pytest.mark.parametrize("opened", [225.0, 180.0])
def test_band_snap_only_tries_one_over_n(opened):
    # 反向：價格帶吸附只試 1/N（票的範圍），鎖漲停的 N 倍跳升仍走原本 2.5% 吸附／推導。
    row, = _infer(_prices(opened=opened)).to_dict("records")
    assert row["kind"] == "inferred"
    assert row["factor"] == opened / 100.0


@pytest.mark.parametrize("previous, opened", [
    (300.0, 110.0), (100.0, 36.0), (800.0, 110.0), (1000.0, 180.0), (800.0, 105.0),
])
def test_ambiguous_band_does_not_snap_to_exact_split(previous, opened):
    # 多個 1/N 價格帶重疊時，離開盤價最近的比例不一定是真分割比例。
    row, = _infer(_prices(previous=previous, opened=opened)).to_dict("records")
    assert row["kind"] == "inferred"
    assert row["factor"] == pytest.approx(opened / previous)
    assert row["reference_price"] == opened


def test_existing_tolerance_path_still_accepts_missing_high_low():
    row, = _infer(_prices(opened=40.8, low=float("nan"), high=float("nan"))).to_dict("records")
    assert row["factor"] == 0.4
    assert row["kind"] == "split"


@pytest.mark.parametrize("opened, low, high", [(54.0, 44.0, 56.0), (46.0, 44.0, 55.0)])
def test_split_band_requires_both_extremes_inside(opened, low, high):
    row, = _infer(_prices(opened=opened, low=low, high=high)).to_dict("records")
    assert row["kind"] == "inferred"
    assert row["factor"] == opened / 100.0


def test_usable_change_keeps_existing_reference_path():
    prices = _prices(previous=1215.0, opened=133.5, close=133.5, change=3.5)
    row, = _infer(prices).to_dict("records")
    assert row["factor"] == 130.0 / 1215.0
    assert row["reference_price"] == 130.0
    assert row["kind"] == "inferred"


@pytest.mark.parametrize("opened, is_event", [(79.3, False), (123.0, False), (79.0, True), (124.0, True)])
def test_compounded_band_is_not_a_linear_or_unbounded_allowance(opened, is_event):
    rows = _infer(_prices(opened=opened, event_day="2024-03-12"))
    assert (len(rows) == 1) == is_event
    if is_event:
        assert rows.iloc[0]["kind"] == "inferred"


@pytest.mark.parametrize("opened, is_event", [(115.5, False), (86.0, False), (116.1, True), (84.9, True)])
def test_pre_2015_band_compounds_seven_percent_with_buffer(opened, is_event):
    prices = _prices(opened=opened, previous_day="2015-05-27", event_day="2015-05-29")
    rows = _infer(prices)
    assert (len(rows) == 1) == is_event


# 舊制 7%：107.5 在 7% 帶加 0.5% 升降單位餘裕內；107.6 超出餘裕但仍在 7.7% 緩衝內，須不吸附；
# 108 在 10% 帶內，須不吸附（證明依日期取 7% 而非 10%）。
@pytest.mark.parametrize("opened, kind", [
    (107.0, "split"), (107.5, "split"), (107.6, "inferred"), (108.0, "inferred")])
def test_split_price_band_uses_plain_legal_limit_for_date(opened, kind):
    prices = _prices(previous=1000.0, opened=opened,
                     previous_day="2015-05-28", event_day="2015-05-29")
    row, = _infer(prices).to_dict("records")
    assert row["kind"] == kind
    assert row["factor"] == (0.1 if kind == "split" else opened / 1000.0)


def test_tick_rounded_reference_still_snaps():
    # 前收 1213／10 = 121.3，參考價取到升降單位 121.5，漲停 133.5 > 121.3 × 1.1 = 133.43。
    row, = _infer(_prices(previous=1213.0, opened=133.5,
                          previous_day="2025-07-18", event_day="2025-07-21")).to_dict("records")
    assert row["kind"] == "split" and row["factor"] == 0.1


@pytest.mark.parametrize("low, high", [(0.0, 54.0)])
def test_nonpositive_low_does_not_widen_snap(low, high):
    row, = _infer(_prices(opened=54.0, low=low, high=high)).to_dict("records")
    assert row["kind"] == "inferred"
    assert row["factor"] == 0.54


@pytest.mark.parametrize("event_day, is_event", [("2024-03-12", True), ("2024-03-13", False)])
def test_explicit_holiday_is_not_counted_as_session(event_day, is_event):
    # 週一雖非週末，注入的日曆指定休市；週二才是第一場。
    def calendar(day):
        return _weekday(day) and day != pd.Timestamp("2024-03-11").date()

    rows = _infer(_prices(event_day=event_day), is_session=calendar)
    assert (len(rows) == 1) == is_event


def test_unusable_calendar_without_other_market_dates_keeps_single_session():
    # 日曆取不到／拋例外時退回 price 表出現過的日期；此處只有本檔，03-11 不在其中，n 仍為 1。
    def broken(day):
        raise ValueError("超出日曆範圍")

    for calendar in (None, broken, lambda day: False):
        row, = _infer(_prices(event_day="2024-03-12"), is_session=calendar).to_dict("records")
        assert row["factor"] == 1.2 and row["kind"] == "inferred"


@pytest.mark.parametrize("gap, is_event", [(20, True), (60, False)])
def test_split_exception_retains_existing_gap_cap(gap, is_event):
    event_day = pd.Timestamp("2024-03-08") + pd.Timedelta(days=gap)
    rows = _infer(_prices(opened=50.0, event_day=event_day))
    assert (len(rows) == 1) == is_event
    if is_event:
        assert rows.iloc[0]["kind"] == "split" and rows.iloc[0]["factor"] == 0.5


def test_in_band_rows_never_walk_calendar():
    calls = []

    def calendar(day):
        calls.append(day)
        return _weekday(day)

    assert _infer(_prices(opened=105.0), is_session=calendar).empty
    assert not calls
    assert _infer(_prices(event_day="2024-03-12"), is_session=calendar).empty
    assert calls


@pytest.mark.parametrize("use_default", [False, True])
def test_infer_rows_reads_extremes_and_passes_calendar(monkeypatch, use_default):
    prices = _prices(previous=1215.0, opened=133.5)
    # 同批資料再加跨場次的一般跳空，驗證日曆與價格帶的接線皆生效。
    gap_prices = _prices(previous=38.45, opened=31.95, event_day="2024-03-12")
    gap_prices["stock_id"] = "6104"
    queries = []

    def read_sql(query, conn, **kwargs):
        queries.append(str(query))
        assert conn is None
        return pd.concat([prices, gap_prices], ignore_index=True)

    monkeypatch.setattr(adjust.pd, "read_sql", read_sql)
    monkeypatch.setattr(health, "_xtai_session_checker", lambda autodetect=True: _weekday)
    kwargs = {} if use_default else {"is_session": _weekday}
    rows = adjust.infer_rows(None, set(), prices.iloc[0]["date"].date(), **kwargs)
    row, = rows.to_dict("records")
    assert row["stock_id"] == "6103" and row["factor"] == 0.1
    assert "open, high, low, close, change" in queries[0]


def test_infer_rows_unavailable_default_calendar_falls_back_to_observed_dates(monkeypatch):
    monkeypatch.setattr(adjust.pd, "read_sql", lambda *a, **k: _prices(event_day="2024-03-12"))
    monkeypatch.setattr(health, "_xtai_session_checker", lambda autodetect=True: None)
    row, = adjust.infer_rows(None, set(), "2024-03-01").to_dict("records")
    assert row["kind"] == "inferred" and row["factor"] == 1.2


@pytest.mark.parametrize("calendar_available", [True, False])
@pytest.mark.parametrize("file_exists", [True, False])
def test_infer_default_calendar_never_autodetects_or_writes_closures(
        monkeypatch, tmp_path, calendar_available, file_exists):
    path = tmp_path / "closed.txt"
    if file_exists:
        path.write_text("2024-03-11  # 臨時休市\n", encoding="utf-8")
    before = (path.read_bytes(), path.stat().st_mtime_ns) if file_exists else None
    monkeypatch.setattr(closures, "closed_file", lambda: path)
    monkeypatch.setenv("TW_CLOSURE_AUTODETECT", "true")

    def forbidden(*args, **kwargs):
        pytest.fail("推導不得自動偵測休市、連網或寫入休市清單")

    monkeypatch.setattr(requests, "get", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(closures, "autodetect_today", forbidden)
    monkeypatch.setattr(health, "autodetect_today", forbidden)
    monkeypatch.setattr(closures, "fetch_dgpa_closures", forbidden)
    # 用可用／不可用的日曆替身，確保未安裝 exchange_calendars 也驗得到自動偵測的退化。
    xcals = SimpleNamespace(get_calendar=lambda name: SimpleNamespace(is_session=_weekday))
    monkeypatch.setitem(sys.modules, "exchange_calendars", xcals if calendar_available else None)
    prices = _prices(event_day="2024-03-12")
    monkeypatch.setattr(adjust.pd, "read_sql", lambda *a, **k: prices.copy())

    rows = adjust.infer_rows(None, set(), "2024-03-01", is_session=None)
    # 日曆可用時須保留本機清單；沒有清單才會數到兩場、排除這筆一般跳空。
    assert (len(rows) == 1) == (file_exists or not calendar_available)
    if len(rows):
        assert rows.iloc[0]["kind"] == "inferred" and rows.iloc[0]["factor"] == 1.2
    if file_exists:
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    else:
        assert not path.exists()


def test_health_default_calendar_keeps_closure_autodetection(monkeypatch):
    calls = []
    xcals = SimpleNamespace(get_calendar=lambda name: SimpleNamespace(is_session=_weekday))
    monkeypatch.setitem(sys.modules, "exchange_calendars", xcals)
    monkeypatch.setattr(health, "autodetect_today", lambda: calls.append(True))
    monkeypatch.setattr(health, "adhoc_closed_dates", lambda: {pd.Timestamp("2024-03-11").date()})
    checker = health._xtai_session_checker()
    assert calls == [True]
    assert not checker(pd.Timestamp("2024-03-11").date())
    assert checker(pd.Timestamp("2024-03-12").date())
