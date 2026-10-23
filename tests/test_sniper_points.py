# -*- coding: utf-8 -*-
"""parse_sniper_value 對 LLM 敘述句的解析（2026-10-22 正式庫實例）。"""

import pytest

from src.utils.sniper_points import parse_sniper_value

STOP_TRAD = "停損位：如果在1,909.00元進場，以1倍ATR14（131.00元）設定停損於1,778.00元"
STOP_SIMP = "止损位：如果在1,909.00元进场，以1倍ATR14（131.00元）设定止损于1,778.00元"


@pytest.mark.parametrize("text", [STOP_TRAD, STOP_SIMP])
def test_conditional_entry_then_stop_target(text):
    assert parse_sniper_value(text) == 1778.0


@pytest.mark.parametrize("text", [
    "暫不設定", "暫不建議買入", "暫不買進，等待回測", "暂不设定", "暂不建议买入",
    "暫不建議買入，若回測137.8元再評估", "不設定", "N/A",
])
def test_explicit_not_set_is_none(text):
    assert parse_sniper_value(text) is None


def test_target_price_clause_after_entry():
    assert parse_sniper_value("若回測1,909元進場，目標價2,100元") == 2100.0


def test_plain_cases_unchanged():
    assert parse_sniper_value("建议在 100 元附近买入") == 100.0
    assert parse_sniper_value("價格：100.5元") == 100.5
    assert parse_sniper_value("停損於95元") == 95.0
