"""data_provider.tw_margin_trend.compute_margin_trend 純函式測試（T14）。"""
from datetime import date, timedelta

from data_provider.tw_margin_trend import compute_margin_trend


def _rows(n, start_balance=1000, step=10, short=50, last=date(2026, 10, 15)):
    return [
        {
            "date": (last - timedelta(days=n - 1 - i)).isoformat(),
            "margin_balance": start_balance + step * i,
            "short_balance": short,
        }
        for i in range(n)
    ]


def test_empty_and_garbage_inputs_return_empty_dict():
    assert compute_margin_trend([]) == {}
    assert compute_margin_trend(None) == {}
    assert compute_margin_trend([{"date": "bad", "margin_balance": 1}]) == {}
    assert compute_margin_trend([{"date": "2026-10-15", "margin_balance": None}]) == {}
    assert compute_margin_trend(42) == {}  # 絕不 raise


def test_25_sessions_has_5_and_20_session_changes_and_ratio():
    t = compute_margin_trend(_rows(25))
    assert t["as_of"] == "2026-10-15" and t["sessions"] == 25
    assert t["margin_balance"] == 1240 and t["short_balance"] == 50
    assert t["margin_chg_5"] == 50      # 1240 - 1190
    assert t["margin_chg_20"] == 200    # 1240 - 1040
    assert abs(t["short_margin_ratio"] - 50 / 1240 * 100) < 1e-9


def test_session_thresholds_are_6_and_21_rows():
    assert compute_margin_trend(_rows(5))["margin_chg_5"] is None
    assert compute_margin_trend(_rows(6))["margin_chg_5"] == 50
    assert compute_margin_trend(_rows(6))["margin_chg_20"] is None
    assert compute_margin_trend(_rows(20))["margin_chg_20"] is None
    assert compute_margin_trend(_rows(21))["margin_chg_20"] == 200
    assert compute_margin_trend(_rows(3))["margin_chg_5"] is None


def test_zero_margin_balance_gives_no_ratio():
    t = compute_margin_trend([{"date": "2026-10-15", "margin_balance": 0, "short_balance": 5}])
    assert t["margin_balance"] == 0 and t["short_margin_ratio"] is None


def test_missing_short_balance_gives_no_ratio():
    t = compute_margin_trend([{"date": "2026-10-15", "margin_balance": 100}])
    assert t["short_balance"] is None and t["short_margin_ratio"] is None


def test_unsorted_nan_and_duplicate_rows_are_handled():
    nan = float("nan")
    rows = _rows(7)
    rows.reverse()
    rows.append({"date": "2026-10-14", "margin_balance": nan, "short_balance": 1})  # NaN 列略過
    rows.append({"date": "2026-10-15", "margin_balance": 1060, "short_balance": 50})  # 同日重複
    t = compute_margin_trend(rows)
    assert t["as_of"] == "2026-10-15" and t["sessions"] == 7
    assert t["margin_balance"] == 1060
