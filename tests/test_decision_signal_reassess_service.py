# -*- coding: utf-8 -*-
"""reassess 只信原文狙擊點：原文有該欄位就不回退到已存的舊價位。"""

from types import SimpleNamespace

from src.services.decision_signal_reassess_service import _extract_persisted_sniper_points

_NO_BUY = "暫不設定買點，須收盤站回 MA5 1957 元才評估"


def _points(record_kwargs, raw_points):
    record = SimpleNamespace(**record_kwargs)
    raw = {"dashboard": {"battle_plan": {"sniper_points": raw_points}}}
    return _extract_persisted_sniper_points(record, raw)


def test_raw_text_without_price_overrides_stale_stored_float():
    out = _points({"ideal_buy": 1957.0}, {"ideal_buy": _NO_BUY})
    assert out["ideal_buy"] is None


def test_missing_raw_field_falls_back_to_stored_float():
    out = _points({"ideal_buy": 1957.0, "stop_loss": 1700.0}, {"stop_loss": "1,778 元"})
    assert out["ideal_buy"] == 1957.0
    assert out["stop_loss"] == 1778.0


def test_empty_raw_field_falls_back_to_stored_float():
    out = _points({"ideal_buy": 1957.0}, {"ideal_buy": "  ", "stop_loss": "1,778 元"})
    assert out["ideal_buy"] == 1957.0


def test_stored_none_uses_raw_price():
    out = _points({"ideal_buy": None}, {"ideal_buy": "1,950 元"})
    assert out["ideal_buy"] == 1950.0


def _structured_points(record_kwargs, raw_points, prices, *, in_raw_response=False):
    record = SimpleNamespace(**record_kwargs)
    battle = {"sniper_points": raw_points, "sniper_prices": prices}
    if in_raw_response:
        raw = {"dashboard": {"battle_plan": {"sniper_points": raw_points}}, "raw_response": {"dashboard": {"battle_plan": battle}}}
    else:
        raw = {"dashboard": {"battle_plan": battle}}
    return _extract_persisted_sniper_points(record, raw)


def test_structured_prices_override_text_and_stored_columns():
    out = _structured_points(
        {"ideal_buy": 118.0, "secondary_buy": 115.0, "stop_loss": 118.0, "take_profit": None},
        {"ideal_buy": "118元", "stop_loss": "暫無，為避免在118元停損而錯失反彈，改以110元停損"},
        {"ideal_buy": None, "stop_loss": 110, "take_profit": 130},
    )
    # 結構化 null 與漏給的格子都是 None：不回到文字 118，也不回到已存欄位
    assert out == {"ideal_buy": None, "secondary_buy": None, "stop_loss": 110.0, "take_profit": 130.0}


def test_structured_prices_found_in_raw_response():
    out = _structured_points({"stop_loss": 118.0}, {"stop_loss": "118元"}, {"stop_loss": 110}, in_raw_response=True)
    assert out["stop_loss"] == 110.0


def test_legacy_sentence_with_price_is_none_not_stored_float():
    out = _points({"stop_loss": 118.0}, {"stop_loss": "止損位：118元（跌破MA20）"})
    assert out["stop_loss"] is None
