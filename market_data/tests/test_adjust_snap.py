"""``adjust.snap_events_to_sessions`` / ``factors_to_panel`` 的休市日對齊（純函數，免 DB）。

颱風休市日公告的除權息，事件日落在沒開市的日子：讀取端要把它移到下一個交易日，
否則斷崖被當成真實跌幅。日期用 2026-07 實際案例（07-10 週五休市、07-13 週一復市）。
"""

import pandas as pd
import pytest

from market_data.adjust import factors_to_panel, snap_events_to_sessions

# 07-10（週五）颱風休市，不在交易日曆上
SESSIONS = pd.DatetimeIndex(["2026-07-08", "2026-07-09", "2026-07-13", "2026-07-14"])
D = pd.Timestamp


def _ev(rows, cols=("stock_id", "date", "factor", "source")):
    return pd.DataFrame(rows, columns=list(cols))


def test_closed_day_event_moves_to_next_session():
    out = snap_events_to_sessions(_ev([("2891", D("2026-07-10"), 0.9641, "twse_twt49u")]), SESSIONS)
    assert list(out["date"]) == [D("2026-07-13")]
    assert list(out["snapped_from"]) == [D("2026-07-10")]


def test_session_day_event_is_untouched():
    out = snap_events_to_sessions(_ev([("2891", D("2026-07-09"), 0.9, "twse_twt49u")]), SESSIONS)
    assert list(out["date"]) == [D("2026-07-09")]
    assert out["snapped_from"].isna().all()


def test_2891_adjusted_return_on_resume_day_is_not_a_fake_drop():
    """acceptance：07-09 前復權收盤 = 69.90×0.9641，07-13 還原報酬 ≈ -1.32%。"""
    adj = _ev([("2891", D("2026-07-10"), 0.9641, "twse_twt49u")])
    fac = factors_to_panel(adj, SESSIONS, pd.Index(["2891"]))["2891"]
    raw = pd.Series([70.0, 69.90, 66.50, 66.0], index=SESSIONS)
    adjusted = raw * fac
    assert adjusted[D("2026-07-09")] == pytest.approx(69.90 * 0.9641)
    assert adjusted[D("2026-07-13")] == pytest.approx(66.50)
    ret = adjusted.pct_change()[D("2026-07-13")]
    assert ret == pytest.approx(66.50 / (69.90 * 0.9641) - 1)
    assert ret == pytest.approx(-0.0132, abs=1e-4)


def test_inferred_dropped_when_it_collides_with_snapped_official():
    """官方公告搬到 07-13 後，同日的 inferred_price 也在同一斷崖上抓到一筆——只能乘一次。"""
    adj = _ev([
        ("5519", D("2026-07-10"), 0.95, "twse_twt49u"),
        ("5519", D("2026-07-13"), 0.96, "inferred_price"),
    ])
    out = snap_events_to_sessions(adj, SESSIONS)
    assert list(out["source"]) == ["twse_twt49u"]
    fac = factors_to_panel(adj, SESSIONS, pd.Index(["5519"]))["5519"]
    assert fac[D("2026-07-09")] == pytest.approx(0.95)   # 不是 0.95×0.96


def test_standalone_inferred_is_kept():
    """沒有撞日的 inferred 照舊保留（只丟撞日者，不是一律丟 inferred）。"""
    adj = _ev([
        ("5519", D("2026-07-14"), 0.8, "inferred_price"),
        ("3489", D("2026-07-10"), 0.9, "twse_twt49u"),
    ])
    out = snap_events_to_sessions(adj, SESSIONS)
    assert sorted(out["source"]) == ["inferred_price", "twse_twt49u"]


def test_inferred_for_other_stock_not_dropped_by_official_collision():
    """撞日以 (stock_id, date) 計：別檔的官方事件不能吃掉這檔的 inferred。"""
    adj = _ev([
        ("1111", D("2026-07-13"), 0.9, "twse_twt49u"),
        ("2222", D("2026-07-13"), 0.8, "inferred_price"),
    ])
    out = snap_events_to_sessions(adj, SESSIONS)
    assert len(out) == 2


def test_snapped_official_multiplies_with_other_non_inferred_on_same_day():
    """搬移後與 07-13 當天另一筆非 inferred 事件撞日：兩者相乘（同日多事件語意）。"""
    adj = _ev([
        ("1234", D("2026-07-10"), 0.9, "twse_twt49u"),
        ("1234", D("2026-07-13"), 0.5, "twse_twtauu"),
    ])
    out = snap_events_to_sessions(adj, SESSIONS)
    assert len(out) == 2
    fac = factors_to_panel(adj, SESSIONS, pd.Index(["1234"]))["1234"]
    assert fac[D("2026-07-09")] == pytest.approx(0.9 * 0.5)
    assert fac[D("2026-07-13")] == pytest.approx(1.0)


def test_events_without_source_column_multiply_on_collision():
    adj = _ev([("1234", D("2026-07-10"), 0.9), ("1234", D("2026-07-13"), 0.5)],
              cols=("stock_id", "date", "factor"))
    fac = factors_to_panel(adj, SESSIONS, pd.Index(["1234"]))["1234"]
    assert fac[D("2026-07-09")] == pytest.approx(0.45)


def test_future_event_beyond_last_session_is_dropped():
    adj = _ev([("1234", D("2026-07-15"), 0.5, "twse_twt49u")])
    assert snap_events_to_sessions(adj, SESSIONS).empty
    fac = factors_to_panel(adj, SESSIONS, pd.Index(["1234"]))
    assert (fac == 1.0).all().all()


def test_event_before_first_session_is_dropped():
    adj = _ev([("1234", D("2026-07-06"), 0.5, "twse_twt49u")])
    assert snap_events_to_sessions(adj, SESSIONS).empty
    fac = factors_to_panel(adj, SESSIONS, pd.Index(["1234"]))
    assert (fac == 1.0).all().all()


def test_empty_inputs():
    assert snap_events_to_sessions(_ev([]), SESSIONS).empty
    assert snap_events_to_sessions(_ev([("1", D("2026-07-09"), 0.9, "x")]),
                                   pd.DatetimeIndex([])).empty


def test_non_unique_input_index_does_not_misalign():
    """concat 出來的長格式常帶重複 index，搬移標記不能對錯列。"""
    adj = _ev([("1", D("2026-07-10"), 0.9, "a"), ("2", D("2026-07-09"), 0.8, "a")])
    adj.index = [0, 0]
    out = snap_events_to_sessions(adj, SESSIONS)
    moved = out.set_index("stock_id")["snapped_from"]
    assert moved["1"] == D("2026-07-10") and pd.isna(moved["2"])
