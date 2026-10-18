from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import GeminiAnalyzer  # noqa: E402


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
    # 只有 3 個場次：連買超照印，但累計窗口不滿所以不印（舊版會把 3 天標成「近 20 日累計」）
    assert "近 20 日累計" not in out and "近 5 日累計" not in out


def test_trend_never_enters_institution_context():
    # The trend is prompt-only; the source institution record must stay raw (untouched).
    from data_provider.tw_institutional_trend import compute_institutional_trend

    inst = {"foreign_net": 1, "trust_net": 1, "dealer_net": 1, "total_net": 3, "date": "20260709"}
    inst_before = dict(inst)
    _ = compute_institutional_trend([], dict(inst), None)  # pass a copy, as the helper does
    assert inst == inst_before  # source record untouched
    assert "trend" not in inst


# ---- T10：累計窗口、上櫃揭露、歷史停更 ----

_TODAY = {"foreign_net": 300, "trust_net": 0, "dealer_net": 0, "total_net": 300, "date": "20260709"}


def _weekdays_before(end_exclusive, n):
    out, d = [], end_exclusive - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


def _lines(code, n_hist, language="zh-TW", calendar="weekdays", hist_end=date(2026, 7, 9)):
    """n_hist 個平日歷史（結束於 hist_end 前一個平日）+ 合成今日紀錄。"""
    days = _weekdays_before(hist_end, n_hist) if n_hist else []
    hist = pd.DataFrame(
        [{"date": d.isoformat(), "foreign_net": 10, "trust_net": 0, "dealer_net": 0, "total_net": 10}
         for d in days]
    )
    if calendar == "weekdays":
        sessions = pd.DatetimeIndex([d for d in _weekdays_before(date(2026, 7, 10), 20)])
    else:
        sessions = calendar  # None -> 行事曆不可用
    with patch("market_data.market_repo.institutional", return_value=hist), \
         patch("market_data.market_repo.stock_info", return_value={"shares_outstanding": 10_000_000}), \
         patch("market_data.db.get_engine", return_value=None), \
         patch("src.core.trading_calendar.get_trading_dates", return_value=sessions):
        return _analyzer()._tw_institutional_trend_lines(code, dict(_TODAY), language)


def test_tpex_without_history_gets_disclosure_not_20d_cumulative():
    out = _lines("6488.TWO", 0)
    assert "只收錄上市（TWSE），上櫃無歷史" in out
    assert "近 20 日累計" not in out and "近 5 日累計" not in out
    assert "連 ≥1 日" not in out and "外資" not in out


def test_tpex_disclosure_in_all_three_languages():
    assert "上柜无历史" in _lines("6488.TWO", 0, "zh")
    en = _lines("6488.TWO", 0, "en")
    assert "TPEx" in en and "20-day cumulative" not in en


def test_listed_stock_with_62_sessions_prints_20_day_window():
    out = _lines("2330.TW", 62)
    assert "近 20 日累計 +490 股" in out  # 19 日 x 10 + 今日 300
    assert "近 5 日累計" not in out


def test_listed_stock_with_10_sessions_prints_only_5_day_window():
    out = _lines("2330.TW", 10)
    assert "近 5 日累計" in out
    assert "近 20 日累計" not in out


def test_five_day_window_label_in_all_languages():
    assert "近 5 日累计" in _lines("2330.TW", 10, "zh")
    assert "5-day cumulative" in _lines("2330.TW", 10, "en")
    assert "20-day cumulative" in _lines("2330.TW", 62, "en")
    assert "近 20 日累计" in _lines("2330.TW", 62, "zh")


def test_stale_history_prints_gap_disclosure_in_all_languages():
    # 歷史停在 07-02，但 07-08 才是今天之前的最後一個交易日
    stale_end = date(2026, 7, 3)
    tw = _lines("2330.TW", 30, hist_end=stale_end)
    assert "停在 2026-07-02、應到 2026-07-08" in tw
    assert "近 20 日累計" not in tw and "連 ≥" not in tw
    assert "停在 2026-07-02、应到 2026-07-08" in _lines("2330.TW", 30, "zh", hist_end=stale_end)
    en = _lines("2330.TW", 30, "en", hist_end=stale_end)
    assert "stops at 2026-07-02 (expected 2026-07-08)" in en


def test_fresh_history_is_not_reported_stale():
    assert "停在" not in _lines("2330.TW", 30)


def test_calendar_unavailable_fails_open_on_continuity_check():
    out = _lines("2330.TW", 30, hist_end=date(2026, 7, 3), calendar=None)
    assert "停在" not in out and "近 20 日累計" in out


# ---- T11：當日抓取失敗時仍給本地歷史、明講失敗原因 ----

_FAIL_BLOCK = {
    "status": "failed",
    "data": {},
    "errors": ["tw institutional record unavailable"],
}


def _failed_prompt(code, n_hist, language="zh-TW", block=None):
    """走真的 _format_prompt：institution block 為 failed，歷史 n_hist 個平日（止於 2026-10-16）。"""
    days = _weekdays_before(date(2026, 10, 17), n_hist) if n_hist else []
    hist = pd.DataFrame(
        [{"date": d.isoformat(), "foreign_net": 10, "trust_net": 0, "dealer_net": 0, "total_net": 10}
         for d in days]
    )
    context = {
        "code": code,
        "stock_name": "測試",
        "date": "2026-10-17",
        "today": {"close": 100, "ma5": 99, "ma10": 98, "ma20": 97},
        "fundamental_context": {"institution": block if block is not None else dict(_FAIL_BLOCK)},
    }
    with patch.object(GeminiAnalyzer, "_init_litellm", return_value=None):
        analyzer = GeminiAnalyzer()
    with patch("market_data.market_repo.institutional", return_value=hist), \
         patch("market_data.market_repo.stock_info", return_value={"shares_outstanding": 10_000_000}), \
         patch("market_data.db.get_engine", return_value=None):
        return analyzer._format_prompt(context, "測試", news_context=None, report_language=language)


def test_failed_tw_prompt_has_failure_line_and_local_history_trend():
    p = _failed_prompt("2330.TW", 30)
    assert "當日三大法人：取得失敗（tw institutional record unavailable）；以下僅本地歷史" in p
    assert "三大法人近期趨勢（截至 2026-10-16，共 30 交易日）" in p
    assert "近 20 日累計 +200 股" in p  # 20 個歷史場次 x 10，今日不存在所以不加 300
    assert "不得推論籌碼面" not in p
    # 失敗行在趨勢之前
    assert p.index("取得失敗") < p.index("三大法人近期趨勢")


def test_failed_tw_prompt_languages():
    assert "当日三大法人：取得失败（tw institutional record unavailable）；以下仅本地历史" in _failed_prompt("2330.TW", 30, "zh")
    en = _failed_prompt("2330.TW", 30, "en")
    assert "fetch failed (tw institutional record unavailable); only local history below" in en
    assert "Recent institutional trend (as of 2026-10-16, 30 sessions)" in en


def test_failed_tw_prompt_without_history_says_unavailable_and_forbids_inference():
    p = _failed_prompt("2330.TW", 0)
    assert "三大法人資料不可用（當日取得失敗：tw institutional record unavailable），不得推論籌碼面" in p
    assert "三大法人近期趨勢" not in p and "以下僅本地歷史" not in p
    assert "do not infer the chip structure" in _failed_prompt("2330.TW", 0, "en")
    assert "不得推论筹码面" in _failed_prompt("2330.TW", 0, "zh")


def test_failed_tw_prompt_with_single_history_row_is_unavailable():
    # 只有 1 個歷史場次沒有「上表當日數據」可引用，也印不出趨勢 -> 不可用
    p = _failed_prompt("2330.TW", 1)
    assert "不得推論籌碼面" in p and "三大法人近期趨勢" not in p
    assert "上表當日數據" not in p


def test_failed_tpex_without_history_says_unavailable():
    assert "不得推論籌碼面" in _failed_prompt("6488.TWO", 0)


def test_non_tw_prompt_has_no_institution_failure_line():
    for block in (dict(_FAIL_BLOCK), {"status": "not_supported", "data": {}, "errors": ["not supported for offshore market"]}):
        p = _failed_prompt("AAPL", 30, block=block)
        assert "取得失敗" not in p and "不得推論籌碼面" not in p
        assert "三大法人近期趨勢" not in p
    assert "取得失敗" not in _failed_prompt("2330.TW", 30, block={"status": "not_supported", "data": {}, "errors": ["fundamental fetch disabled"]})


def test_trend_lines_with_empty_today_use_db_last_day_and_do_not_need_calendar():
    days = _weekdays_before(date(2026, 10, 17), 30)
    hist = pd.DataFrame(
        [{"date": d.isoformat(), "foreign_net": 10, "trust_net": 0, "dealer_net": 0, "total_net": 10}
         for d in days]
    )
    with patch("market_data.market_repo.institutional", return_value=hist), \
         patch("market_data.market_repo.stock_info", return_value={}), \
         patch("market_data.db.get_engine", return_value=None), \
         patch("src.core.trading_calendar.get_trading_dates", side_effect=AssertionError("no calendar check without today")):
        out = _analyzer()._tw_institutional_trend_lines("2330.TW", {}, "zh-TW")
    assert "截至 2026-10-16" in out
