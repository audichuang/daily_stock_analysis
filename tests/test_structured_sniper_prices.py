"""狙擊價格由模型判斷，消費端不得從敘述句反推。"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from datetime import date

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.utils.sniper_points import SNIPER_KEYS, extract_sniper_points, parse_sniper_value
from src.analyzer import AnalysisResult, GeminiAnalyzer, check_content_integrity, apply_placeholder_fill
from src.schemas.report_schema import AnalysisReportSchema
from src.services.decision_signal_extractor import build_decision_signal_payload_from_report
from src.services.decision_signal_reassess_service import _extract_persisted_sniper_points
from src.storage import DatabaseManager


CONTRADICTORY = "暫無，為避免在118元停損而錯失反彈，改以110元停損"


def report(prices):
    return {"dashboard": {"battle_plan": {
        "sniper_points": dict.fromkeys(SNIPER_KEYS, CONTRADICTORY),
        "sniper_prices": prices,
    }}}


@pytest.mark.parametrize("value", [110, None])
@pytest.mark.parametrize("wrapper", ["dashboard", "raw_response"])
@pytest.mark.parametrize("text", [CONTRADICTORY, "118元"])
def test_structured_prices_override_text_in_every_result_shape(value, wrapper, text):
    raw = report(dict.fromkeys(SNIPER_KEYS, value))
    raw["dashboard"]["battle_plan"]["sniper_points"] = dict.fromkeys(SNIPER_KEYS, text)
    result = SimpleNamespace(**{wrapper: raw})
    assert extract_sniper_points(result) == dict.fromkeys(SNIPER_KEYS, value)


@pytest.mark.parametrize("field", SNIPER_KEYS)
def test_legacy_sentence_is_rejected_but_bare_price_survives(field):
    assert parse_sniper_value(CONTRADICTORY, field) is None
    assert parse_sniper_value("118元", field) == 118


def result_with(prices):
    result = AnalysisResult(code="00631L.TW", name="測試", sentiment_score=55,
                            trend_prediction="震盪", operation_advice="觀望", decision_type="hold",
                            analysis_summary="觀望", report_language="zh-TW")
    result.dashboard = report(prices)["dashboard"]
    result.dashboard.update(core_conclusion={"one_sentence": "觀望"}, intelligence={"risk_alerts": []})
    return result


@pytest.mark.parametrize("value, expected", [
    (118, 118), (118.5, 118.5), ("118", 118), ("118元", 118), (" 118 元 ", 118),
    ("118-120", 120), ("118~120", 120), ("118至120", 120), ("1,118元", 1118),
])
def test_legacy_literal_formats_still_work(value, expected):
    assert parse_sniper_value(value) == expected


@pytest.mark.parametrize("value", [True, False, 0, -1, float("nan"), float("inf"), "110", "110元", {}, []])
def test_structured_contract_does_not_coerce_invalid_values_or_fall_back(value):
    assert extract_sniper_points(report(dict.fromkeys(SNIPER_KEYS, value))) == dict.fromkeys(SNIPER_KEYS)
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AnalysisReportSchema.model_validate(report({"stop_loss": value}))


@pytest.mark.parametrize("value", [110, None])
def test_schema_defaults_and_accepts_model_judgment(value):
    schema = AnalysisReportSchema.model_validate(report(dict.fromkeys(SNIPER_KEYS, value)))
    assert schema.dashboard.battle_plan.sniper_prices.model_dump() == dict.fromkeys(SNIPER_KEYS, value)
    legacy = AnalysisReportSchema.model_validate({"dashboard": {"battle_plan": {"sniper_points": {"stop_loss": "118元"}}}})
    assert legacy.dashboard.battle_plan.sniper_prices is None


@pytest.mark.parametrize("value", [110, None])
@pytest.mark.parametrize("text", [CONTRADICTORY, "118元"])
def test_storage_extractor_reassessment_and_history_api_share_judgment(value, text):
    from api.v1.endpoints.history import get_history_detail
    from src.services.history_service import HistoryService
    prices = dict.fromkeys(SNIPER_KEYS, value)
    result = result_with(prices)
    result.dashboard["battle_plan"]["sniper_points"] = dict.fromkeys(SNIPER_KEYS, text)
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    try:
        record_id = db.save_analysis_history(result, query_id="sniper-test", report_type="full", news_content="")
        assert record_id > 0
        record = db.get_analysis_history_by_id(record_id)
        assert {key: getattr(record, key) for key in SNIPER_KEYS} == prices
        assert _extract_persisted_sniper_points(SimpleNamespace(**dict.fromkeys(SNIPER_KEYS, 999)), result.to_dict()) == prices
        detail = HistoryService(db)._record_to_detail_dict(record)
        assert detail["sniper_prices"] == prices
        api_report = get_history_detail(str(record_id), db)
        assert api_report.strategy.sniper_prices.model_dump() == prices
        assert api_report.strategy.stop_loss == text
    finally:
        DatabaseManager.reset_instance()
    payload = build_decision_signal_payload_from_report(
        result, trace_id="test", query_source="test", report_type="full", profile_source="legacy_unknown",
    )
    assert payload is not None
    for key, target in (("ideal_buy", "entry_low"), ("secondary_buy", "entry_high"),
                        ("stop_loss", "stop_loss"), ("take_profit", "target_price")):
        assert payload.get(target) == prices[key]


@pytest.mark.parametrize("value", [110, None])
def test_analysis_response_and_api_preserve_text_and_expose_prices(value):
    from api.v1.endpoints.analysis import _build_analysis_report
    from src.services.analysis_service import AnalysisService
    prices = dict.fromkeys(SNIPER_KEYS, value)
    result = result_with(prices)
    response = AnalysisService.__new__(AnalysisService)._build_analysis_response(result, "test", "full")
    api_report = _build_analysis_report(response["report"], "test", result.code, result.name)
    assert api_report.strategy.sniper_prices.model_dump() == prices
    assert api_report.strategy.stop_loss == CONTRADICTORY


@pytest.mark.parametrize("stop", [96, None])
def test_cost_guardrail_uses_model_prices_and_keeps_buy_band_hold_behavior(stop):
    from src.trade_cost_guardrail import apply_trade_cost_guardrail
    result = result_with({"ideal_buy": 100, "secondary_buy": None, "stop_loss": stop, "take_profit": 110})
    result.sentiment_score = 78
    apply_trade_cost_guardrail(result, code=result.code)
    check = result.dashboard["battle_plan"]["cost_check"]
    assert check["status"] == ("ok" if stop is not None else "levels_missing")
    if stop is not None:
        assert check["gross_rr"] == 2.5
    assert result.sentiment_score == 78


@pytest.mark.parametrize("value", [110, None])
def test_condensed_displays_do_not_resurrect_text_prices(value, monkeypatch):
    from bot.commands.ask import AskCommand
    from src.notification import NotificationService
    from src.share_image import _stock_data, _stock_data_from_payload
    from src.services.report_renderer import render
    from src.config import get_config
    result = result_with(dict.fromkeys(SNIPER_KEYS, value))
    notifier = NotificationService.__new__(NotificationService)
    notifier._config = get_config()
    notifier._report_show_llm_model = False
    notifier._report_summary_only = False
    monkeypatch.setattr(get_config(), "report_renderer_enabled", False)
    texts = [AskCommand._format_stock_result(result.code, result.to_dict(), ""),
             notifier.generate_single_stock_report(result), notifier.generate_wechat_dashboard([result]),
             render("wechat", [result])]
    for text in texts:
        assert "118" not in text
        assert ("110" in text) == (value is not None)
    markdown = "### 作战计划\n\n| 点位类型 | 价格 |\n|---|---|\n| 理想买入点 | 118元 |\n| 止损位 | 118元 |"
    assert len(_stock_data(markdown, date(2026, 10, 27)).sniper) == 2
    poster = _stock_data_from_payload(result.to_dict(), markdown, date(2026, 10, 27))
    assert all(price == "110" for _, price, _ in poster.sniper)
    assert len(poster.sniper) == (4 if value is not None else 0)


@pytest.mark.parametrize("value", [110, None])
def test_integrity_and_agent_backfills_respect_explicit_null(value):
    from src.agent.orchestrator import AgentOrchestrator
    from src.agent.protocols import AgentContext
    from src.core.pipeline import StockAnalysisPipeline
    prices = dict.fromkeys(SNIPER_KEYS, value)
    result = result_with(prices)
    assert check_content_integrity(result) == (True, [])
    result.dashboard["battle_plan"]["sniper_points"] = {}
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline._backfill_agent_dashboard_fields(result, SimpleNamespace(support_levels=[999]), "zh-TW")
    assert extract_sniper_points(result) == prices
    assert "stop_loss" not in result.get_sniper_points()
    orchestrator = AgentOrchestrator(tool_registry=MagicMock(), llm_adapter=MagicMock())
    raw = result.to_dict()
    raw["dashboard"]["key_levels"] = {"support": 999, "stop_loss": 999, "resistance": 999}
    normalized = orchestrator._finalize_dashboard_payload(raw, AgentContext(query="test", stock_code=result.code))
    assert extract_sniper_points(normalized) == prices
    assert normalized["dashboard"]["battle_plan"]["sniper_points"] == {}


def test_missing_structured_stop_triggers_repair_despite_numeric_text():
    result = result_with({})
    result.dashboard["battle_plan"]["sniper_points"]["stop_loss"] = "118元"
    field = "dashboard.battle_plan.sniper_prices.stop_loss"
    assert check_content_integrity(result) == (False, [field])
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    assert "sniper_prices" in analyzer._build_integrity_complement_prompt([field], "zh-TW")
    apply_placeholder_fill(result, [field])
    assert result.dashboard["battle_plan"]["sniper_prices"]["stop_loss"] is None
    assert extract_sniper_points(result)["stop_loss"] is None


@pytest.mark.parametrize("language", ["zh", "zh-TW", "en", "ko"])
@pytest.mark.parametrize("legacy", [True, False])
def test_all_prompt_paths_require_structured_judgment(language, legacy):
    from src.agent.executor import AGENT_SYSTEM_PROMPT, LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT
    from src.agent.agents.decision_agent import DecisionAgent
    from src.agent.protocols import AgentContext
    from src.utils.sniper_points import SNIPER_PRICES_PROMPT
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._get_skill_prompt_sections = lambda: ("", "", legacy)
    analyzer._tw_ma_weighted_active = lambda *args: False
    prompts = [analyzer._get_analysis_system_prompt(language, "00631L.TW"),
               (LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT if legacy else AGENT_SYSTEM_PROMPT).format(
                   market_role="", market_guidelines="", default_skill_policy_section="", skills_section="", language_section=""),
               DecisionAgent(MagicMock(), MagicMock()).system_prompt(AgentContext(query="test", meta={"report_language": language}))]
    for prompt in prompts:
        assert SNIPER_PRICES_PROMPT in prompt
        assert all(key in prompt for key in SNIPER_KEYS)


def test_chat_synthesis_keeps_natural_language_contract():
    from src.agent.agents.decision_agent import DecisionAgent
    from src.agent.protocols import AgentContext
    from src.utils.sniper_points import SNIPER_PRICES_PROMPT
    prompt = DecisionAgent(MagicMock(), MagicMock()).system_prompt(
        AgentContext(query="test", meta={"response_mode": "chat", "report_language": "zh-TW"}),
    )
    assert SNIPER_PRICES_PROMPT not in prompt
    assert "Do NOT output JSON" in prompt


@pytest.mark.parametrize("value", [110, None])
@pytest.mark.parametrize("strategy", [{}, {"stop_loss": "118元", "sniper_prices": dict.fromkeys(SNIPER_KEYS, 999)}])
def test_api_rebuild_reads_raw_structured_contract_before_cached_strategy(value, strategy):
    from api.v1.endpoints.analysis import _build_analysis_report
    prices = dict.fromkeys(SNIPER_KEYS, value)
    result = result_with(prices)
    api_report = _build_analysis_report(
        {"strategy": strategy, "details": {"raw_result": result.to_dict()}}, "test", result.code, result.name,
    )
    assert api_report.strategy.sniper_prices.model_dump() == prices
