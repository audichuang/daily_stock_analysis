# -*- coding: utf-8 -*-
"""T12：台股月營收進個股 prompt（單月口徑、標明月份），非台股／無月營收不出現。"""

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import GeminiAnalyzer  # noqa: E402


def _analyzer():
    return GeminiAnalyzer.__new__(GeminiAnalyzer)  # no __init__ / no network


_GROWTH = {
    "monthly_revenue": 335_000_000_000.0,
    "monthly_revenue_yoy": 54.65,
    "monthly_revenue_mom": -0.57,
    "cumulative_revenue_yoy": 41.11,
    "revenue_month": "11509",
    "revenue_month_iso": "2026-09",
}


def _prompt(code, growth, language="zh-TW"):
    context = {
        "code": code,
        "stock_name": "測試",
        "date": "2026-10-16",
        "today": {"close": 100.0, "ma5": 1, "ma10": 1, "ma20": 1},
        "fundamental_context": {"growth": {"status": "ok", "data": growth}} if growth is not None else {},
    }
    return _analyzer()._format_prompt(context, "測試", report_language=language)


def test_tw_prompt_has_monthly_revenue_row_with_month_and_growth():
    p = _prompt("2330.TW", dict(_GROWTH))
    assert "月營收（2026-09，單月，非年度）" in p
    assert "年增 +54.65%" in p and "月增 -0.57%" in p and "累計年增 +41.11%" in p
    assert "3350.00 亿新台币" in p  # zh 模板沿用 _format_amount 的中文量級，幣別為新台幣


def test_tw_prompt_en_template_uses_english_magnitude():
    p = _prompt("2330.TW", dict(_GROWTH), language="en")
    assert "Monthly Revenue (2026-09, single month, not annual)" in p
    assert "335.00B" in p and "亿" not in p.split("Monthly Revenue")[1].split("\n")[0]
    assert "YoY +54.65%, MoM -0.57%, cumulative YoY +41.11%" in p


def test_tw_prompt_falls_back_to_roc_month_when_iso_missing():
    p = _prompt("2330.TW", {**_GROWTH, "revenue_month_iso": None})
    assert "月營收（11509，單月，非年度）" in p


def test_tw_prompt_missing_pct_prints_na():
    p = _prompt("2330.TW", {**_GROWTH, "monthly_revenue_mom": None})
    assert "月增 N/A" in p and "年增 +54.65%" in p


def test_tw_prompt_without_monthly_revenue_has_no_row():
    assert "月營收" not in _prompt("2330.TW", {"monthly_revenue": None, "revenue_month": "11509"})
    assert "月營收" not in _prompt("2330.TW", None)


def test_non_tw_prompt_has_no_monthly_revenue_row():
    assert "月營收" not in _prompt("AAPL", dict(_GROWTH))
    assert "Monthly Revenue" not in _prompt("AAPL", dict(_GROWTH), language="en")
