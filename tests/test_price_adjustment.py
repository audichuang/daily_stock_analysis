# -*- coding: utf-8 -*-
"""Tests for market_data.adjust 的純計算層（不碰 DB / 網路）。

前復權算錯會讓除息/分割跳空被當成真實漲跌，是所有報酬計算的根，所以這幾條必須守住。
"""

from __future__ import annotations

from datetime import date
import pandas as pd
import pytest

from market_data.adjust import _snap_to_split, factors_to_panel, merge_adjustment_rows
from market_data.sources import parse_reduction

DAYS = pd.date_range("2026-05-01", periods=10, freq="D")
COLS = pd.Index(["1234", "5678"])


def _adj(rows):
    return pd.DataFrame(rows, columns=["stock_id", "date", "factor"])


def test_panel_removes_ex_dividend_gap():
    """除息 10% 的跳空，還原後不該留下任何漲跌——否則會誤觸停損。"""
    fac = factors_to_panel(_adj([("1234", DAYS[5], 0.9)]), DAYS, COLS)
    assert fac.loc[DAYS[4], "1234"] == pytest.approx(0.9)
    assert fac.loc[DAYS[5], "1234"] == pytest.approx(1.0)   # 事件日起維持原值
    assert (fac["5678"] == 1.0).all()                        # 無事件的標的不受影響

    raw = pd.Series([100.0] * 5 + [90.0] * 5, index=DAYS)
    assert (raw * fac["1234"]).pct_change().abs().max() == pytest.approx(0.0, abs=1e-9)


def test_panel_is_cumulative_across_events():
    fac = factors_to_panel(_adj([
        ("1234", DAYS[3], 0.9),
        ("1234", DAYS[7], 0.95),
    ]), DAYS, COLS)
    assert fac.loc[DAYS[0], "1234"] == pytest.approx(0.9 * 0.95)
    assert fac.loc[DAYS[5], "1234"] == pytest.approx(0.95)
    assert fac.loc[DAYS[8], "1234"] == pytest.approx(1.0)


def test_merge_adjustment_rows_keeps_official_source_over_inference():
    official = pd.DataFrame([{
        "stock_id": "1234", "date": DAYS[3], "factor": 0.9,
        "kind": "dividend", "source": "twse_twt49u",
        "close_before": 100.0, "reference_price": 90.0,
    }])
    inferred = pd.DataFrame([{
        "stock_id": "1234", "date": DAYS[3], "factor": 0.8,
        "kind": "inferred", "source": "inferred_price",
        "close_before": 100.0, "reference_price": 80.0,
    }])
    out = merge_adjustment_rows(official, inferred)
    assert len(out) == 1
    assert out.iloc[0]["source"] == "twse_twt49u"
    assert out.iloc[0]["factor"] == pytest.approx(0.9)


def test_refresh_recent_fetch_failure_happens_before_transaction(monkeypatch):
    from market_data import adjust

    state = {"began": False}

    class _Ctx:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    class _Engine:
        def connect(self):
            return _Ctx()

        def begin(self):
            state["began"] = True
            return _Ctx()

    monkeypatch.setattr(adjust, "official_rows", lambda conn: pd.DataFrame())
    monkeypatch.setattr(
        adjust, "existing_official_rows", lambda conn, start: pd.DataFrame())
    monkeypatch.setattr(
        adjust,
        "fetch_tpex_dividends",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network failed")),
    )

    with pytest.raises(RuntimeError, match="network failed"):
        adjust.refresh_recent(_Engine(), date(2026, 7, 1), date(2026, 7, 31))
    assert state["began"] is False


def test_refresh_recent_refuses_to_erase_existing_official_source(monkeypatch):
    from market_data import adjust

    state = {"began": False}

    class _Ctx:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    class _Engine:
        def connect(self):
            return _Ctx()

        def begin(self):
            state["began"] = True
            return _Ctx()

    existing = pd.DataFrame([{
        "stock_id": "1234", "date": pd.Timestamp("2026-07-15"), "factor": 0.9,
        "kind": "dividend", "source": "tpex_exdailyq",
        "close_before": 100.0, "reference_price": 90.0,
    }])
    monkeypatch.setattr(adjust, "official_rows", lambda conn: pd.DataFrame())
    monkeypatch.setattr(adjust, "existing_official_rows", lambda conn, start: existing)
    monkeypatch.setattr(adjust, "fetch_tpex_dividends", lambda *args: pd.DataFrame())
    monkeypatch.setattr(adjust, "fetch_reductions", lambda *args: pd.DataFrame())

    with pytest.raises(RuntimeError, match="tpex_exdailyq"):
        adjust.refresh_recent(_Engine(), date(2026, 7, 1), date(2026, 7, 31))
    assert state["began"] is False



def test_panel_handles_split_and_reduction_together():
    """1:4 分割（0050 實例）與減資（factor>1）要能共存於同一檔。"""
    fac = factors_to_panel(_adj([
        ("1234", DAYS[3], 0.25),   # 1:4 分割
        ("1234", DAYS[7], 1.32),   # 減資
    ]), DAYS, COLS)
    assert fac.loc[DAYS[0], "1234"] == pytest.approx(0.25 * 1.32)
    raw = pd.Series([200.0] * 3 + [50.0] * 4 + [66.0] * 3, index=DAYS)
    assert (raw * fac["1234"]).pct_change().abs().max() == pytest.approx(0.0, abs=1e-9)


def test_panel_ignores_unknown_stock_and_offcalendar_date():
    fac = factors_to_panel(_adj([
        ("9999", DAYS[3], 0.5),                        # 不在 columns
        ("1234", pd.Timestamp("2026-04-01"), 0.5),     # 不在 index
    ]), DAYS, COLS)
    assert (fac == 1.0).all().all()


def test_panel_applies_closed_day_event_on_next_session():
    """颱風休市日公告的事件（週五休市）作用在下一個交易日（週一）：週一還原後不留假跌幅。"""
    sessions = pd.DatetimeIndex(["2026-07-08", "2026-07-09", "2026-07-13", "2026-07-14"])
    fac = factors_to_panel(_adj([("1234", pd.Timestamp("2026-07-10"), 0.9)]), sessions, COLS)
    assert fac.loc["2026-07-09", "1234"] == pytest.approx(0.9)
    assert fac.loc["2026-07-13", "1234"] == pytest.approx(1.0)
    raw = pd.Series([100.0, 100.0, 90.0, 90.0], index=sessions)
    assert (raw * fac["1234"]).pct_change().abs().max() == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("factor,expected,is_split", [
    # 以下 factor 一律是 open/prev_close（實測值），不是 close/prev_close
    (0.10000, 0.10, True),    # 6763 實測 491→開49.10，精確 1/10
    (0.04964, 0.05, True),    # 5314 實測 1390→開69.00，1/20 誤差 0.7%
    (0.10192, 0.10, True),    # 4763 實測 885→開90.20，1/10 誤差 1.9%
    (7.0488, 7.0, True),      # 00632R 反分割 7 合 1，誤差 0.7%
    (0.72, 0.72, False),      # 不接近任何比例，維持原值
    (1.32, 1.32, False),      # 減資不吸附（非整數比）
])
def test_snap_to_split(factor, expected, is_split):
    got, flag = _snap_to_split(factor)
    assert got == pytest.approx(expected, abs=1e-9)
    assert flag is is_split


def test_snap_does_not_swallow_obvious_crash():
    """明顯偏離任何整數比的崩跌不該被吸附。"""
    for raw in (0.15, 0.72, 0.5151):
        got, flag = _snap_to_split(raw)
        assert flag is False, f"{raw} 不該被判成分割"
        assert got == pytest.approx(raw)


def test_ratio_alone_cannot_separate_real_from_fake():
    """**這是商品類型過濾存在的理由**：光看比率分不出真假。

    00887 在 2024-10-14 的真崩跌 22.15→10.86（factor 0.4903）距 1/2 只有 1.94%，
    落在任何合理容差內，數學上無法與真分割區分。擋住它的是 `is_common_stock()`，
    不是容差——所以那道過濾不能為了「多抓幾檔」而放寬。
    """
    from market_data.adjust import is_common_stock
    assert _snap_to_split(10.86 / 22.15)[1] is True     # 純數學層會誤判
    assert is_common_stock("00887") is False            # 真正擋住它的是這道


def test_parse_reduction_reads_roc_slash_dates():
    """TWTAUU 用 '113/01/22' 斜線格式，不是 _roc_to_date 的 '113年01月22日'。"""
    payload = {
        "stat": "OK",
        "fields": ["恢復買賣日期", "股票代號", "名稱", "停止買賣前收盤價格",
                   "恢復買賣參考價", "漲停價格", "跌停價格", "開盤競價基準",
                   "除權參考價", "減資原因", "詳細資料"],
        "data": [["113/01/22", "3432", "台端", "10.65", "19.69", "21.65",
                  "17.75", "19.70", "--", "彌補虧損", "3432 ,20240110"]],
    }
    df = parse_reduction(payload)
    assert len(df) == 1
    assert df.iloc[0]["stock_id"] == "3432"
    assert df.iloc[0]["date"] == pd.Timestamp("2024-01-22")
    assert df.iloc[0]["reference_price"] / df.iloc[0]["close_before"] == pytest.approx(1.8488, abs=1e-4)


def test_parse_reduction_raises_when_every_row_fails():
    """全數解析失敗多半是格式改版；靜默回空會讓減資事件永久缺漏。"""
    payload = {
        "stat": "OK",
        "fields": ["恢復買賣日期", "股票代號", "停止買賣前收盤價格", "恢復買賣參考價"],
        "data": [["not-a-date", "3432", "x", "y"]],
    }
    with pytest.raises(ValueError, match="無法解析"):
        parse_reduction(payload)


def test_parse_reduction_rejects_unexpected_schema():
    with pytest.raises(ValueError, match="欄位不符預期"):
        parse_reduction({"stat": "OK", "fields": ["日期", "代號"], "data": []})


# --- 商品類型：價格推導只對「受漲跌幅限制的普通股」成立 ---
# 獨立審查抓到：00887 在 2024-10 的真實 -48%/-51% 崩跌（海外休市、溢價異常）
# 曾被判成兩次 1:2 分割，把跌幅改寫成 +3%/-2%。以下鎖住修正後的行為。

@pytest.mark.parametrize("sid,is_common", [
    ("2330", True),      # 普通股
    ("1101", True),
    ("0050", False),     # ETF
    ("00887", False),    # ETF（曾被誤判成兩次分割）
    ("00631L", False),   # 槓桿 ETF，無漲跌幅限制
    ("00632R", False),   # 反向 ETF
    ("020000", False),   # ETN
    ("9110", False),     # TDR，第二上市外國證券
    ("70001", False),    # 權證
])
def test_is_common_stock(sid, is_common):
    from market_data.adjust import is_common_stock
    assert is_common_stock(sid) is is_common


def test_verified_actions_cover_benchmark_split():
    """0050 是回測基準，它的 1:4 分割必須有因子，否則基準報酬會錯 12 個百分點。"""
    from market_data.adjust import VERIFIED_ACTIONS
    assert VERIFIED_ACTIONS[("0050", "2025-06-18")] == pytest.approx(0.25)


def test_snap_rejects_etf_crash_ratios():
    """00887 實際跌幅對應的比率不該被當成乾淨的 1/N 分割而靜默吸附。"""
    from market_data.adjust import _snap_to_split
    for raw in (20.00 / 38.83, 10.86 / 22.15):   # 約 0.515、0.490
        got, is_split = _snap_to_split(raw)
        if is_split:
            # 若落在 1/2 容差內，代表光靠比率無法分辨——這正是必須靠商品類型過濾的理由
            assert got == pytest.approx(0.5)


def _window_boundary_run(monkeypatch, start):
    import contextlib
    from market_data import adjust

    cols = adjust.ADJUSTMENT_COLUMNS
    dk = pd.Timestamp("2026-07-15")  # official event day with no bar
    days = [d for d in pd.bdate_range("2026-05-01", "2026-08-10") if d != dk]
    px = pd.DataFrame([{
        "stock_id": "2330", "date": d, "open": 100.0 if d < dk else 50.0,
        "close": 100.0 if d < dk else 50.0, "change": 0.0} for d in days])
    off = pd.DataFrame([{"stock_id": "2330", "date": dk,
                         "close_before": 100.0, "reference_price": 50.0}])

    def fake_read_sql(sql, conn, params=None, parse_dates=None):
        s = str(sql)
        if "from market.price " in s or "from market.price\n" in s:
            return px[px.date >= pd.Timestamp(params["s"])].copy()
        if "ex_dividend" in s:
            return off.copy()
        return pd.DataFrame(columns=cols)

    rows = []

    class _Conn:
        def execute(self, *a, **k):
            pass

    class _Eng:
        @contextlib.contextmanager
        def connect(self):
            yield _Conn()

        @contextlib.contextmanager
        def begin(self):
            yield _Conn()

    empty = lambda *a, **k: pd.DataFrame(columns=cols)  # noqa: E731
    monkeypatch.setattr(adjust.pd, "read_sql", fake_read_sql)
    monkeypatch.setattr(adjust, "fetch_tpex_dividends", empty)
    monkeypatch.setattr(adjust, "fetch_reductions", empty)
    monkeypatch.setattr(adjust, "fetch_tpex_reductions", empty)
    monkeypatch.setattr(
        adjust, "upsert", lambda conn, tbl, recs, keys: rows.extend(recs) or len(recs))
    adjust.refresh_recent(_Eng(), start, date(2026, 8, 10))
    return rows


def test_refresh_recent_window_start_after_event_does_not_reinfer(monkeypatch):
    # Event on 07-15 has no bar; window starts 07-16 so the 07-16 gap is the same event.
    rows = _window_boundary_run(monkeypatch, date(2026, 7, 16))
    assert [r for r in rows if r["source"] == "inferred_price"] == []


def test_refresh_recent_window_still_infers_unexplained_gap(monkeypatch):
    # Guard against over-fixing: an unrelated gap inside the window must still be inferred.
    from market_data import adjust
    real = adjust.official_rows
    monkeypatch.setattr(adjust, "official_rows", lambda conn: real(conn).iloc[0:0])
    rows = _window_boundary_run(monkeypatch, date(2026, 7, 10))
    assert [r["stock_id"] for r in rows if r["source"] == "inferred_price"] == ["2330"]
