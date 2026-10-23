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
