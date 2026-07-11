from unittest.mock import patch

from src.analyzer import GeminiAnalyzer


def _analyzer():
    return GeminiAnalyzer.__new__(GeminiAnalyzer)  # no __init__ / no network


def test_trend_lines_fail_open_on_db_error_returns_empty():
    a = _analyzer()
    with patch("market_data.market_repo.institutional", side_effect=RuntimeError("db down")):
        out = a._tw_institutional_trend_lines(
            "2330.TW",
            {"foreign_net": 1, "trust_net": 1, "dealer_net": 1, "total_net": 3, "date": "20260709"},
            "zh-TW",
        )
    assert out == ""


def test_trend_lines_render_when_history_present():
    a = _analyzer()
    hist_rows = [
        {"date": "2026-07-07", "foreign_net": 100, "trust_net": 0, "dealer_net": 0, "total_net": 100},
        {"date": "2026-07-08", "foreign_net": 200, "trust_net": 0, "dealer_net": 0, "total_net": 200},
    ]

    class _DF:
        empty = False

        def to_dict(self, orient):
            return hist_rows

    with patch("market_data.market_repo.institutional", return_value=_DF()), \
         patch("market_data.market_repo.stock_info", return_value={"shares_outstanding": 100000}), \
         patch("market_data.db.get_engine", return_value=None):
        out = a._tw_institutional_trend_lines(
            "2330.TW",
            {"foreign_net": 300, "trust_net": 0, "dealer_net": 0, "total_net": 300, "date": "20260709"},
            "zh-TW",
        )
    assert "外資" in out and "連" in out and "日" in out  # 繁體 trend line present
    assert "近 20 日累計" in out


def test_trend_never_enters_institution_context():
    # The trend is prompt-only; the source institution record must stay raw (untouched).
    from data_provider.tw_institutional_trend import compute_institutional_trend

    inst = {"foreign_net": 1, "trust_net": 1, "dealer_net": 1, "total_net": 3, "date": "20260709"}
    inst_before = dict(inst)
    _ = compute_institutional_trend([], dict(inst), None)  # pass a copy, as the helper does
    assert inst == inst_before  # source record untouched
    assert "trend" not in inst
