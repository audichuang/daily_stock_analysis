# -*- coding: utf-8 -*-
"""Prompt data labels: volume-ratio basis, preliminary institutional data, local-first valuation."""

import datetime
from types import SimpleNamespace
from unittest.mock import patch

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider import base as dp_base  # noqa: E402
from data_provider import twse_fundamental_adapter as tfa  # noqa: E402
from data_provider.realtime_types import RealtimeSource  # noqa: E402
from src.analyzer import GeminiAnalyzer  # noqa: E402
from src.core.pipeline import StockAnalysisPipeline  # noqa: E402


def _pipeline():
    p = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    p.config = SimpleNamespace(report_language="zh-TW")
    p.search_service = SimpleNamespace(news_window_days=3)
    return p


def _quote(source=RealtimeSource.SHIOAJI, vr=1.31):
    return SimpleNamespace(code="2330.TW", name="台積電", price=1000.0, volume_ratio=vr, source=source)


def _enhance(code, today_vr, quote):
    ctx = {"code": code, "today": {"close": 1000.0, **({"volume_ratio": today_vr} if today_vr is not None else {})}}
    return _pipeline()._enhance_context(ctx, quote, None, None, fundamental_context={})["realtime"]


def _prompt(realtime, institution=None, valuation=None, code="2330.TW"):
    fc = {}
    if institution:
        fc["institution"] = {"status": "ok", "data": institution}
    if valuation:
        fc["valuation"] = {"data": valuation}
    ctx = {
        "code": code, "stock_name": "測試", "date": "2026-10-22",
        "today": {"close": 100.0, "ma5": 1, "ma10": 1, "ma20": 1},
        "realtime": realtime, "fundamental_context": fc,
    }
    return GeminiAnalyzer.__new__(GeminiAnalyzer)._format_prompt(ctx, "測試", report_language="zh-TW")


# --- (1) volume ratio basis ---------------------------------------------------
def test_tw_volume_ratio_uses_5d_basis_and_keeps_shioaji_as_vs_prev():
    rt = _enhance("2330.TW", 0.75, _quote())
    assert rt["volume_ratio"] == 0.75
    assert rt["volume_ratio_desc"] == "明显萎缩"
    assert rt["volume_ratio_vs_prev"] == 1.31
    assert rt["volume_ratio_basis"] == "5日均量"


def test_tw_without_5d_ratio_drops_misleading_shioaji_value_from_main_field():
    rt = _enhance("2330.TW", None, _quote())
    assert "volume_ratio" not in rt
    assert rt["volume_ratio_vs_prev"] == 1.31


def test_non_tw_volume_ratio_unchanged():
    rt = _enhance("AAPL", 0.75, _quote(vr=1.31))
    assert rt["volume_ratio"] == 1.31
    assert "volume_ratio_vs_prev" not in rt and "volume_ratio_basis" not in rt


def test_prompt_labels_both_ratios():
    rt = {"price": 1.0, "volume_ratio": 0.75, "volume_ratio_desc": "明显萎缩",
          "volume_ratio_vs_prev": 1.31, "volume_ratio_basis": "5日均量"}
    p = _prompt(rt)
    assert "量比（對5日均量）" in p and "| **0.75** |" in p
    assert "較昨量（當日累計量／昨量，非5日均量口徑） | 1.31" in p


# --- (2) preliminary institutional data ----------------------------------------
def test_inst_is_preliminary_only_for_today_taipei():
    from zoneinfo import ZoneInfo
    today = datetime.datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")
    assert dp_base._tw_inst_is_preliminary(today) is True
    assert dp_base._tw_inst_is_preliminary("20200101") is False
    assert dp_base._tw_inst_is_preliminary(None) is False


def test_prompt_marks_preliminary_institution_only_when_flagged():
    inst = {"foreign_net": 1, "trust_net": 2, "dealer_net": 3, "total_net": 6, "date": "20261022", "source": "t"}
    with patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""):
        assert "初版，投信常於隔夜修正" in _prompt({"price": 1.0}, {**inst, "is_preliminary": True})
        assert "初版" not in _prompt({"price": 1.0}, {**inst, "is_preliminary": False})
        assert "初版" not in _prompt({"price": 1.0}, inst)


# --- (3) local-first valuation -------------------------------------------------
def _row(days_ago, pe=20.5):
    d = tfa._today() - datetime.timedelta(days=days_ago)
    return {"date": d, "pe_ratio": pe, "pb_ratio": 5.0, "dividend_yield": 1.2}


def test_valuation_prefers_fresh_local_row_with_as_of():
    a = tfa.TwseFundamentalAdapter()
    with patch("market_data.market_repo.latest_valuation", return_value=_row(0)):
        v = a.get_valuation("2330.TW")
    assert v["pe_ratio"] == 20.5 and v["as_of"] == tfa._today().isoformat()


def test_valuation_stale_or_missing_local_falls_back_to_api():
    a = tfa.TwseFundamentalAdapter()
    api = {"2330": {"pe_ratio": 9.9, "pb_ratio": 1.0, "dividend_yield": 2.0, "as_of": "2026-10-21"}}
    a._cached = lambda name, build: api if name == "valuation_twse" else {}
    for local in (_row(30), None):
        with patch("market_data.market_repo.latest_valuation", return_value=local):
            assert a.get_valuation("2330.TW")["pe_ratio"] == 9.9
    with patch("market_data.market_repo.latest_valuation", side_effect=RuntimeError("db down")):
        assert a.get_valuation("2330.TW")["pe_ratio"] == 9.9
