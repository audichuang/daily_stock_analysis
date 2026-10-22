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


def test_tpex_without_history_gets_generic_disclosure_not_20d_cumulative():
    # 上櫃自 2018-01-15 起也有本地歷史：缺歷史時與上市同一句，不再宣稱「上櫃無歷史」
    out = _lines("6488.TWO", 0)
    assert "本地歷史不足" in out and "上櫃無歷史" not in out
    assert "近 20 日累計" not in out and "近 5 日累計" not in out
    assert "連 ≥1 日" not in out and "外資" not in out


def test_tpex_with_history_prints_trend_like_listed():
    out = _lines("6488.TWO", 62)
    assert "近 20 日累計" in out and "上櫃" not in out


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


def _failed_prompt(code, n_hist, language="zh-TW", block=None, margin=None, margin_raises=False):
    """走真的 _format_prompt：institution block 為 failed，歷史 n_hist 個平日（止於 2026-10-16）。
    margin 預設為空表（離線測試不碰真實 DB）；margin_raises=True 時 margin() 拋例外。"""
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
    margin_patch = (
        patch("market_data.market_repo.margin", side_effect=RuntimeError("db down"))
        if margin_raises
        else patch("market_data.market_repo.margin", return_value=margin if margin is not None else pd.DataFrame())
    )
    with patch("market_data.market_repo.institutional", return_value=hist), \
         patch("market_data.market_repo.stock_info", return_value={"shares_outstanding": 10_000_000}), \
         patch("market_data.db.get_engine", return_value=None), margin_patch:
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


# ---- T14：融資融券（張、T+1 資料日、5／20 場次變化、券資比），上櫃揭露，法人失敗仍出現 ----

def _margin_df(n, last=date(2026, 10, 15)):
    """n 個平日的融資融券列（升序，止於 last）：融資餘額每日 +10 從 1000 起，融券 50。"""
    days = _weekdays_before(last + timedelta(days=1), n)
    return pd.DataFrame(
        [{"date": d.isoformat(), "margin_balance": 1000 + 10 * i, "margin_buy": 0, "margin_sell": 0,
          "short_balance": 50, "short_buy": 0, "short_sell": 0}
         for i, d in enumerate(days)]
    )


def _margin_lines(code, df=None, language="zh-TW", raises=False):
    if raises:
        p = patch("market_data.market_repo.margin", side_effect=RuntimeError("db down"))
    else:
        p = patch("market_data.market_repo.margin", return_value=df)
    with p as m, patch("market_data.db.get_engine", return_value=None):
        out = _analyzer()._tw_margin_lines(code, language)
    return out, m


def test_margin_lines_listed_with_25_rows_prints_balance_date_changes_and_ratio():
    out, _ = _margin_lines("2330.TW", _margin_df(25))
    # 最新餘額 1000+240=1240；5 場次前 1190（+50）、20 場次前 1040（+200）；券資比 50/1240
    assert "融資融券（截至 2026-10-15，T+1 發布；單位：張）" in out
    assert "融資餘額 1,240 張" in out
    assert "較 5 個場次前 +50 張" in out and "較 20 個場次前 +200 張" in out
    assert "融券餘額 50 張" in out and "券資比 4.03%" in out


def test_margin_lines_three_languages():
    zh, _ = _margin_lines("2330.TW", _margin_df(25), "zh")
    assert "融资融券（截至 2026-10-15，T+1 发布；单位：张）" in zh and "较 20 个场次前 +200 张" in zh
    en, _ = _margin_lines("2330.TW", _margin_df(25), "en")
    assert "Margin trading (as of 2026-10-15, published T+1; unit: lots)" in en
    assert "margin balance 1,240 lots" in en and "+200 lots vs 20 sessions ago" in en
    assert "short-to-margin ratio 4.03%" in en


def test_margin_lines_insufficient_sessions_omit_changes():
    out, _ = _margin_lines("2330.TW", _margin_df(3))
    assert "融資餘額 1,020 張" in out
    assert "個場次前" not in out
    out10, _ = _margin_lines("2330.TW", _margin_df(10))
    assert "較 5 個場次前" in out10 and "較 20 個場次前" not in out10


def test_margin_lines_tpex_queries_db_like_listed():
    out, m = _margin_lines("6488.TWO", _margin_df(25))
    assert "融資餘額 1,240 張" in out and "上櫃" not in out
    m.assert_called_once()


def test_margin_lines_fail_open_on_db_error_and_empty():
    assert _margin_lines("2330.TW", raises=True)[0] == ""
    assert _margin_lines("2330.TW", pd.DataFrame())[0] == ""
    assert _margin_lines("2330.TW", None)[0] == ""


def test_margin_block_present_in_prompt_even_when_institution_failed():
    for block in (dict(_FAIL_BLOCK), {"status": "not_supported", "data": {}, "errors": ["fundamental fetch disabled"]}):
        p = _failed_prompt("2330.TW", 30, block=block, margin=_margin_df(25))
        assert "融資餘額 1,240 張" in p
    # 法人 ok 分支同樣出現，且放在法人區塊之後
    ok_block = {"status": "ok", "data": dict(_TODAY), "errors": []}
    p = _failed_prompt("2330.TW", 30, block=ok_block, margin=_margin_df(25))
    assert "融資餘額 1,240 張" in p and p.index("三大法人動向") < p.index("融資融券（截至")


def test_margin_block_tpex_from_db_and_non_tw_untouched_in_prompt():
    p = _failed_prompt("6488.TWO", 0, margin=_margin_df(25))
    assert "融資餘額 1,240 張" in p and "上櫃個股沒有本地融資融券資料" not in p
    us = _failed_prompt("AAPL", 30, margin=_margin_df(25))
    assert "融資餘額" not in us


def test_margin_block_db_error_does_not_break_prompt():
    p = _failed_prompt("2330.TW", 30, margin_raises=True)
    assert "融資餘額" not in p and "當日三大法人：取得失敗" in p
