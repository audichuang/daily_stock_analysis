# -*- coding: utf-8 -*-
"""T12：台股月營收進個股 prompt（單月口徑、標明月份），非台股／無月營收不出現。"""

from tests.litellm_stub import ensure_litellm_stub
import pytest

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
    assert "3350.00 億新台幣" in p  # zh-TW 沿用 _format_amount 的中文量級，幣別為新台幣


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


# ---- T13：估值標籤（近四季＋資料日期）與交易所殖利率列 ----

_VAL = {"pe_ratio": 31.46, "pb_ratio": 10.3, "dividend_yield": 0.94, "valuation_as_of": "2026-10-16"}


def _val_prompt(code, valuation, language="zh-TW", rt=None):
    context = {
        "code": code,
        "stock_name": "測試",
        "date": "2026-10-16",
        "today": {"close": 100.0, "ma5": 1, "ma10": 1, "ma20": 1},
        "realtime": rt if rt is not None else {"price": 100.0},
        "fundamental_context": {"valuation": {"status": "ok", "data": valuation}},
    }
    return _analyzer()._format_prompt(context, "測試", report_language=language)


def test_tw_prompt_pe_pb_labels_carry_basis_and_date_with_exchange_yield_row():
    p = _val_prompt("2330.TW", dict(_VAL))
    assert "| 本益比（近四季，2026-10-16） | 31.46 |" in p
    assert "| 股價淨值比（2026-10-16） | 10.3 |" in p
    assert "| 殖利率（交易所公告） | 0.94% |" in p
    assert "本益比(動態)" not in p


def test_tw_prompt_simplified_and_english_templates_label_too():
    zh = _val_prompt("2330.TW", dict(_VAL), language="zh")
    assert "市盈率（近四季，2026-10-16）" in zh and "殖利率（交易所公告）" in zh
    en = _val_prompt("2330.TW", dict(_VAL), language="en")
    assert "PE (trailing 4 quarters, 2026-10-16) | 31.46" in en
    assert "Dividend Yield (exchange-published) | 0.94%" in en


def test_tw_prompt_without_as_of_or_yield_keeps_basis_label_but_no_yield_row():
    p = _val_prompt("2330.TW", {"pe_ratio": 31.46, "pb_ratio": 10.3})
    assert "| 本益比（近四季） | 31.46 |" in p
    assert "殖利率（交易所公告）" not in p


def test_non_tw_prompt_valuation_rows_unchanged():
    val = {**_VAL, "pe_ratio": 28.0}
    p = _val_prompt("AAPL", val)
    assert "| 本益比(動態) | 28.0 |" in p and "| 股價淨值比 | 10.3 |" in p
    assert "近四季" not in p and "殖利率（交易所公告）" not in p
    en = _val_prompt("AAPL", val, language="en", rt={"price": 100.0, "pe_ratio": 28.0, "pb_ratio": 3.0})
    assert "| PE (TTM/dynamic) | 28.0 |" in en and "| PB | 3.0 |" in en
    assert "Dividend Yield (exchange-published)" not in en


# ---- T15：財報列帶單位、正負號與口徑（單季／近四季） ----

_FR = {
    "report_date": "2026-06-30",
    "revenue": 1270380250000.0,
    "net_profit_parent": -12345678900,
    "operating_cash_flow": None,
    "roe": 25.3,
    "currency": "TWD",
    "basis": {"revenue": "quarter", "net_profit_parent": "ttm_derived"},
}


def _fr_prompt(code, financial_report, language="zh-TW"):
    context = {
        "code": code,
        "stock_name": "測試",
        "date": "2026-10-16",
        "today": {"close": 100.0, "ma5": 1, "ma10": 1, "ma20": 1},
        "fundamental_context": {"earnings": {"status": "ok", "data": {"financial_report": financial_report}}},
    }
    return _analyzer()._format_prompt(context, "測試", report_language=language)


def _row(prompt, label):
    return next(line for line in prompt.splitlines() if line.startswith(f"| {label} |"))


def test_tw_financial_rows_zh_have_unit_sign_and_basis_labels():
    p = _fr_prompt("2330.TW", dict(_FR))
    assert "| 營業收入 | 12703.80 億新台幣 | 單季 |" in p
    assert "| 歸母淨利 | -123.46 億新台幣 | 近四季推算（營收×淨利率） |" in p
    assert "1270380250000" not in p and "-12345678900" not in p
    # None → N/A、無口徑標籤；ROE 是比率，原樣不格式化
    assert "| 營運現金流 | N/A |  |" in p
    assert "| ROE | 25.3 |" in p


def test_tw_financial_rows_en_have_scaled_numbers_sign_and_basis_labels():
    p = _fr_prompt("2330.TW", dict(_FR), language="en")
    assert "| Revenue | 1270.38B | quarterly |" in p
    assert "| Net Profit Attributable to Parent | -12.35B | TTM-derived (revenue x net margin) |" in p
    assert "| Operating Cash Flow | N/A |  |" in p
    assert "| ROE | 25.3 |" in p


def test_financial_rows_non_numeric_prints_na_and_missing_basis_leaves_note_empty():
    fr = {"revenue": "N/A", "net_profit_parent": "-5000", "operating_cash_flow": 1.5e8, "roe": "N/A"}
    p = _fr_prompt("2330.TW", fr)
    assert "| 營業收入 | N/A |  |" in p
    assert "| 歸母淨利 | -5000 新台币 |  |" in p
    assert "| 營運現金流 | 1.50 億新台幣 |  |" in p
    assert "| ROE | N/A |" in p


def test_financial_rows_ttm_label_and_follow_report_currency_not_trade_market():
    # 港股 ADR 常以人民幣報表：金額單位跟財報幣別走，不跟交易市場走
    fr = {"revenue": 9.5e11, "currency": "CNY", "basis": {"revenue": "ttm"}}
    p = _fr_prompt("HK09988", fr)
    assert "| 營業收入 | 9500.00 亿元 | 近四季 |" in p


def test_format_amount_sign_and_non_numeric():
    a = _analyzer()
    assert a._format_amount(-12345678900, "tw") == "-123.46 亿新台币"
    assert a._format_amount(-12345678900, "tw", "en") == "-12.35B"
    assert a._format_amount(-50000, "tw") == "-5.00 万新台币"
    assert a._format_amount(-300, "tw") == "-300 新台币"
    assert a._format_amount(None, "tw") == "N/A"
    assert a._format_amount("N/A", "tw") == "N/A"
    assert a._format_amount("N/A", "tw", "en") == "N/A"
    assert a._format_amount(float("nan"), "tw") == "N/A"
    assert a._format_amount("1270380250000.0", "tw") == "12703.80 亿新台币"


@pytest.mark.parametrize("language,label,values", [
    ("zh-TW", "營業收入", ["100.00 亿EUR", "-5.00 万EUR", "30 EUR"]),
    ("zh", "营业收入", ["100.00 亿EUR", "-5.00 万EUR", "30 EUR"]),
    ("en", "Revenue", ["10.00B EUR", "-50.00K EUR", "30 EUR"]),
    ("ko", "Revenue", ["10.00B EUR", "-50.00K EUR", "30 EUR"]),
])
def test_unknown_financial_currency_keeps_iso_code(language, label, values):
    for amount, expected in zip((1e10, -50000, 30), values):
        p = _fr_prompt("HK09988", {"revenue": amount, "currency": " eur "}, language=language)
        assert f"| {label} | {expected} |" in p
    p = _fr_prompt("HK09988", {"revenue": None, "currency": "EUR"}, language=language)
    assert f"| {label} | N/A |" in p


@pytest.mark.parametrize("currency,expected", [
    ("CNY", "100.00 億元"), ("RMB", "100.00 億元"), ("USD", "100.00 億美元"),
    ("HKD", "100.00 億港元"), ("TWD", "100.00 億新台幣"),
    ("JPY", "100.00 億日元"), ("KRW", "100.00 億韓元"), (None, "100.00 億港元"),
])
def test_supported_financial_currency_format_unchanged(currency, expected):
    fr = {"revenue": 1e10, "currency": currency}
    assert f"| 營業收入 | {expected} |" in _fr_prompt("HK09988", fr)
    assert "| Revenue | 10.00B |" in _fr_prompt("HK09988", fr, language="en")
