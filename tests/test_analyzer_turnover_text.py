# -*- coding: utf-8 -*-
"""B04：完整報告即時行情表的週轉率不得印成「None%」，價格欄位用千分位。"""

import copy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from src.analyzer import GeminiAnalyzer
from tests.test_analyzer_prompt_language import _make_analyzer, _rich_context

_FAKE_CFG = SimpleNamespace(news_max_age_days=3, news_strategy_profile="short")


def _prompt(language: str, **realtime_overrides) -> str:
    context = copy.deepcopy(_rich_context())
    context["realtime"].update(realtime_overrides)
    analyzer = _make_analyzer(legacy=True)
    with patch("src.analyzer.get_config", return_value=_FAKE_CFG), \
            patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""):
        return analyzer._format_prompt(context, "Apple", news_context="n", report_language=language)


def _row(prompt: str, label: str) -> str:
    return next(line for line in prompt.splitlines() if label in line)


@pytest.mark.parametrize(
    "language,label,missing",
    [("zh-TW", "週轉率", "暫無"), ("zh", "换手率", "暂无"), ("en", "Turnover Rate", "N/A")],
)
def test_turnover_none_renders_placeholder_not_none_percent(language, label, missing):
    prompt = _prompt(language, turnover_rate=None)
    row = _row(prompt, label)
    assert f"**{missing}**" in row
    assert "None" not in row
    assert "%" not in row
    assert "None%" not in prompt


@pytest.mark.parametrize("language,label", [("zh-TW", "週轉率"), ("zh", "换手率"), ("en", "Turnover Rate")])
def test_turnover_number_renders_two_decimals(language, label):
    row = _row(_prompt(language, turnover_rate=1.234), label)
    assert "**1.23%**" in row


def test_turnover_numeric_string_and_blank():
    # Stored snapshots can carry the rate as a string ("11.46"); blanks fall back.
    assert "**11.46%**" in _row(_prompt("zh-TW", turnover_rate="11.46"), "週轉率")
    assert "**暫無**" in _row(_prompt("zh-TW", turnover_rate=""), "週轉率")


@pytest.mark.parametrize("language,label", [("zh-TW", "目前價格"), ("en", "Current Price")])
def test_realtime_price_uses_thousands_separator(language, label):
    row = _row(_prompt(language, price=1234.5), label)
    assert "1,234.50" in row


@pytest.mark.parametrize("language,label", [("zh-TW", "目前價格"), ("en", "Current Price")])
@pytest.mark.parametrize(
    "price,text", [(3.852, "3.852"), (0.355, "0.355"), (0.0123, "0.0123"), (12345.6789, "12,345.6789"), (41, "41.00")]
)
def test_realtime_price_keeps_precision_beyond_two_decimals(language, label, price, text):
    row = _row(_prompt(language, price=price), label)
    assert f"| {text}" in row
