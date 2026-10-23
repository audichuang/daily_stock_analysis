# -*- coding: utf-8 -*-
"""parse_sniper_value 對 LLM 敘述句的解析（2026-10-22 正式庫實例）。"""

import pytest

from src.utils.sniper_points import extract_sniper_points, parse_sniper_value

STOP_TRAD = "停損位：如果在1,909.00元進場，以1倍ATR14（131.00元）設定停損於1,778.00元"
STOP_SIMP = "止损位：如果在1,909.00元进场，以1倍ATR14（131.00元）设定止损于1,778.00元"


@pytest.mark.parametrize("text", [STOP_TRAD, STOP_SIMP])
def test_stop_loss_takes_stop_clause_not_entry(text):
    assert parse_sniper_value(text, "stop_loss") == 1778.0


@pytest.mark.parametrize("text", [
    "暫不設定", "暫不建議買入", "暫不買進，等待回測", "暂不设定", "暂不建议买入",
    "暫不建議買入，若回測137.8元再評估", "不設定", "N/A",
])
@pytest.mark.parametrize("field", ["ideal_buy", "stop_loss"])
def test_explicit_not_set_is_none(text, field):
    assert parse_sniper_value(text, field) is None


@pytest.mark.parametrize("text, expected", [
    ("暫不建議追高，回測500元附近再買", 500.0),
    ("回測1900元附近分批布局，跌破1850元暫不進場", 1900.0),
])
def test_not_set_only_when_leading(text, expected):
    assert parse_sniper_value(text, "ideal_buy") == expected


def test_buy_field_ignores_stop_clause():
    assert parse_sniper_value("建議回測1,800元附近買進（停損於1,700元）", "ideal_buy") == 1800.0
    assert parse_sniper_value("1909元附近進場，停損設在1778元", "ideal_buy") == 1909.0
    assert parse_sniper_value("1909元附近進場，停損設在1778元", None) == 1909.0


def test_take_profit_target_clause_and_first_of_many():
    assert parse_sniper_value("若回測1,909元進場，目標價2,100元", "take_profit") == 2100.0
    assert parse_sniper_value("第一目標價2100元，第二目標價2300元", "take_profit") == 2100.0


def test_stop_field_ignores_target_anchor():
    assert parse_sniper_value("跌破1700元停損，目標價2100元", "stop_loss") == 1700.0


def test_plain_cases_unchanged():
    assert parse_sniper_value("建议在 100 元附近买入") == 100.0
    assert parse_sniper_value("價格：100.5元") == 100.5
    assert parse_sniper_value("停損於95元", "stop_loss") == 95.0


def test_extract_passes_field():
    class R:
        def get_sniper_points(self):
            return {"ideal_buy": "1909元進場，停損設在1778元", "stop_loss": STOP_TRAD,
                    "take_profit": "暫不設定", "secondary_buy": None}
    assert extract_sniper_points(R()) == {
        "ideal_buy": 1909.0, "secondary_buy": None, "stop_loss": 1778.0, "take_profit": None}
