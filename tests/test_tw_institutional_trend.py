from data_provider.tw_institutional_trend import compute_institutional_trend


def _row(d, f=None, t=None, de=None, tot=None):
    return {"date": d, "foreign_net": f, "trust_net": t, "dealer_net": de, "total_net": tot}


def test_consecutive_buy_streak_includes_today():
    hist = [_row("2026-07-07", 100, 0, 0, 100), _row("2026-07-08", 200, 0, 0, 200)]
    today = _row("20260709", 300, 0, 0, 300)
    out = compute_institutional_trend(hist, today, None)
    assert out["foreign"]["streak"] == {"days": 3, "direction": "buy", "capped": True}
    assert out["foreign"]["cum_5d"] == 600
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
    assert out["foreign"]["cum_5d"] == 300             # None skipped, not counted as 0


def test_dedupe_when_db_already_has_today():
    hist = [_row("2026-07-08", 100, 0, 0, 100), _row("2026-07-09", 999, 0, 0, 999)]  # stale today
    today = _row("20260709", 300, 0, 0, 300)  # authoritative
    out = compute_institutional_trend(hist, today, None)
    assert out["sessions"] == 2                         # stale 07-09 dropped
    assert out["foreign"]["cum_5d"] == 400              # 100 + 300 (not 999)


def test_pct_of_shares_on_total_only():
    hist = [_row("2026-07-08", 0, 0, 0, 1000)]
    today = _row("20260709", 0, 0, 0, 1000)
    out = compute_institutional_trend(hist, today, 100000)
    assert out["total"]["pct_of_shares"] == round(2000 / 100000 * 100, 2)  # 2.0
    assert "pct_of_shares" not in out["foreign"]


def test_missing_shares_gives_none_pct():
    out = compute_institutional_trend([], _row("20260709", 0, 0, 0, 1000), None)
    assert out["total"]["pct_of_shares"] is None


def test_empty_returns_empty_dict():
    assert compute_institutional_trend([], None, None) == {}
    assert compute_institutional_trend(None, None, 100) == {}
