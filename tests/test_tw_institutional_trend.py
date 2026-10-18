from datetime import date, timedelta

from data_provider.tw_institutional_trend import compute_institutional_trend


def _weekday_rows(n, end=date(2026, 7, 8), value=10):
    """end 往前數 n 個平日（每列 foreign=value，其餘 0）；只用來造窗口長度，不涉及假日。"""
    rows, d = [], end
    while len(rows) < n:
        if d.weekday() < 5:
            rows.append(_row(d.isoformat(), value, 0, 0, value))
        d -= timedelta(days=1)
    return list(reversed(rows))


def _row(d, f=None, t=None, de=None, tot=None):
    return {"date": d, "foreign_net": f, "trust_net": t, "dealer_net": de, "total_net": tot}


def test_consecutive_buy_streak_includes_today():
    hist = [_row("2026-07-07", 100, 0, 0, 100), _row("2026-07-08", 200, 0, 0, 200)]
    today = _row("20260709", 300, 0, 0, 300)
    out = compute_institutional_trend(hist, today, None)
    assert out["foreign"]["streak"] == {"days": 3, "direction": "buy", "capped": True}
    assert out["foreign"]["cum_5d"] is None            # 只有 3 場，不足 5 場就不給累計
    assert out["as_of"] == "2026-07-09"


def test_sign_flip_breaks_streak():
    hist = [_row("2026-07-07", -50, 0, 0, -50), _row("2026-07-08", 100, 0, 0, 100)]
    today = _row("20260709", 200, 0, 0, 200)
    out = compute_institutional_trend(hist, today, None)
    assert out["foreign"]["streak"]["days"] == 2  # today + prev buy; -50 flips
    assert out["foreign"]["streak"]["direction"] == "buy"


def test_zero_and_null_break_streak_and_skip_cum():
    hist = [_row("2026-07-07", None, 0, 0, None), _row("2026-07-08", 100, 0, 0, 100)]
    today = _row("20260709", 200, 0, 0, 200)
    out = compute_institutional_trend(hist, today, None)
    assert out["foreign"]["streak"]["days"] == 2       # None breaks before it
    assert out["foreign"]["cum_5d"] is None            # None 不當 0 補、也不略過湊數


def test_dedupe_when_db_already_has_today():
    hist = [_row("2026-07-08", 100, 0, 0, 100), _row("2026-07-09", 999, 0, 0, 999)]  # stale today
    today = _row("20260709", 300, 0, 0, 300)  # authoritative
    out = compute_institutional_trend(hist, today, None)
    assert out["sessions"] == 2                         # stale 07-09 dropped
    assert out["foreign"]["streak"]["days"] == 2
    assert out["history_sessions"] == 1
    # 以 5 場窗口驗證用的是權威的今天（300）而非庫內舊值（999）
    out5 = compute_institutional_trend(_weekday_rows(4) + [_row("2026-07-09", 999, 0, 0, 999)], today, None)
    assert out5["foreign"]["cum_5d"] == 40 + 300


def test_pct_of_shares_on_total_only():
    hist = [_row(r["date"], 0, 0, 0, 1000) for r in _weekday_rows(19)]
    today = _row("20260709", 0, 0, 0, 1000)
    out = compute_institutional_trend(hist, today, 100000)
    assert out["total"]["cum_20d"] == 20000
    assert out["total"]["pct_of_shares"] == round(20000 / 100000 * 100, 2)  # 20.0
    assert "pct_of_shares" not in out["foreign"]


def test_missing_shares_gives_none_pct():
    out = compute_institutional_trend([], _row("20260709", 0, 0, 0, 1000), None)
    assert out["total"]["pct_of_shares"] is None


def test_empty_returns_empty_dict():
    assert compute_institutional_trend([], None, None) == {}
    assert compute_institutional_trend(None, None, 100) == {}


# ---- T10：累計只在有效場次足夠時出現 ----

def _cums(n):
    hist = _weekday_rows(n - 1)
    out = compute_institutional_trend(hist, _row("20260709", 10, 0, 0, 10), None)
    return out["foreign"]["cum_5d"], out["foreign"]["cum_20d"], out["sessions"]


def test_cum_exists_only_when_window_is_full():
    assert _cums(1) == (None, None, 1)            # 上櫃：只有當日一列
    assert _cums(4) == (None, None, 4)
    assert _cums(5) == (50, None, 5)
    assert _cums(19) == (50, None, 19)
    assert _cums(20) == (50, 200, 20)             # 剛好 20 場就給（門檻是 >=，不是 >）
    assert _cums(30) == (50, 200, 30)


def test_cum_none_when_a_value_inside_window_is_missing():
    hist = _weekday_rows(19)
    hist[-3] = _row(hist[-3]["date"], None, 0, 0, 10)   # 窗口內一列 foreign 缺值
    out = compute_institutional_trend(hist, _row("20260709", 10, 0, 0, 10), None)
    assert out["foreign"]["cum_20d"] is None
    assert out["foreign"]["cum_5d"] is None             # 缺值也落在最近 5 列內
    assert out["trust"]["cum_20d"] == 0                 # 其他法人不受影響
    # 缺值在 5 列之外：5 日仍成立、20 日不成立
    hist = _weekday_rows(19)
    hist[0] = _row(hist[0]["date"], None, 0, 0, 10)
    out = compute_institutional_trend(hist, _row("20260709", 10, 0, 0, 10), None)
    assert out["foreign"]["cum_20d"] is None
    assert out["foreign"]["cum_5d"] == 50


def test_total_filled_from_three_actors_when_null():
    hist = [_row("2026-07-08", 100, 20, -30, None)]
    out = compute_institutional_trend(hist, _row("20260709", 10, 0, 0, 10), None)
    assert out["total"]["streak"] == {"days": 2, "direction": "buy", "capped": True}  # 沒有因 None 斷掉
    full = compute_institutional_trend(_weekday_rows(3, end=date(2026, 7, 7)) + [_row("2026-07-08", 100, 20, -30, None)],
                                       _row("20260709", 10, 0, 0, 10), None)
    assert full["total"]["cum_5d"] == 10 * 3 + 90 + 10   # 3 列 10 + (100+20-30) + 今天 10


def test_total_not_filled_when_an_actor_is_missing():
    hist = [_row("2026-07-08", 100, None, -30, None)]
    out = compute_institutional_trend(hist, _row("20260709", 10, 0, 0, 10), None)
    assert out["total"]["streak"]["days"] == 1           # 昨天總計仍是 None，斷在今天


def test_stale_history_is_dropped_and_reported():
    hist = [_row("2026-07-01", 100, 0, 0, 100), _row("2026-07-02", 100, 0, 0, 100)]
    out = compute_institutional_trend(hist, _row("20260709", 50, 0, 0, 50), None,
                                      expected_prev_session=date(2026, 7, 8))
    assert out["history_gap"] == {"last_history": "2026-07-02", "expected": "2026-07-08"}
    assert out["sessions"] == 1 and out["history_sessions"] == 0
    assert out["foreign"]["cum_5d"] is None and out["foreign"]["streak"]["days"] == 1


def test_fresh_history_across_weekend_is_not_a_gap():
    # 週五（07-03）→ 週一（07-06）：曆日差 3 但中間沒有交易日，不算停更
    hist = [_row("2026-07-02", 100, 0, 0, 100), _row("2026-07-03", 100, 0, 0, 100)]
    out = compute_institutional_trend(hist, _row("20260706", 50, 0, 0, 50), None,
                                      expected_prev_session="2026-07-03")
    assert "history_gap" not in out
    assert out["sessions"] == 3 and out["history_sessions"] == 2
    assert out["foreign"]["streak"]["days"] == 3


def test_no_expected_session_skips_continuity_check():
    hist = [_row("2026-06-01", 100, 0, 0, 100)]
    out = compute_institutional_trend(hist, _row("20260709", 50, 0, 0, 50), None)
    assert "history_gap" not in out and out["sessions"] == 2


def test_empty_history_is_not_reported_as_gap():
    out = compute_institutional_trend([], _row("20260709", 50, 0, 0, 50), None,
                                      expected_prev_session=date(2026, 7, 8))
    assert "history_gap" not in out and out["sessions"] == 1
