"""停損補問與成本護欄：模型價位不能由技術支撐代填。"""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import AnalysisResult, GeminiAnalyzer, _AllModelsFailedError
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType
from src.schemas.decision_scale import extract_decision_guardrail_reason
from src.services.analysis_context_builder import PipelineAnalysisArtifacts
from src.utils.sniper_points import extract_sniper_points


PRICES = {"ideal_buy": 120, "stop_loss": 110, "take_profit": 150}
ABSENT = object()
TREND = SimpleNamespace(support_levels=[96], atr14_pct=3.5)


def result_with(prices=ABSENT, *, code="00631L.TW", action="buy", score=78, decision="buy"):
    battle = {"sniper_points": {"stop_loss": ""}}
    if prices is not ABSENT:
        battle["sniper_prices"] = deepcopy(prices)
    return AnalysisResult(
        code=code, name="測試", sentiment_score=score, trend_prediction="看多",
        operation_advice="買入" if decision == "buy" else "持有", decision_type=decision,
        action=action, analysis_summary="分析完成", report_language="zh-TW",
        dashboard={"core_conclusion": {"one_sentence": "分析完成"},
                   "intelligence": {"risk_alerts": []}, "battle_plan": battle},
    )


def pipeline_with(reply="{}"):
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(
        report_language="zh-TW", report_integrity_enabled=False, report_integrity_retry=0,
    )
    pipeline.analyzer = MagicMock(spec=GeminiAnalyzer)
    pipeline.analyzer.generate_text.return_value = reply
    pipeline.db = MagicMock()
    pipeline.db.save_analysis_history.return_value = 1
    pipeline.save_context_snapshot = False
    pipeline.query_source = "test"
    pipeline.analysis_skills = None
    pipeline._extract_decision_signal_after_history_save = MagicMock()
    return pipeline


def finalize(pipeline, result, *, trend=None):
    saved = []
    pipeline.db.save_analysis_history.side_effect = lambda **kw: saved.append(deepcopy(kw["result"])) or 1
    artifacts = PipelineAnalysisArtifacts(
        code=result.code, stock_name=result.name, market="tw", phase=None,
        base_context={}, enhanced_context={}, realtime_quote=None, trend_result=trend,
        chip_data=None, fundamental_context=None, news_context=None, news_result_count=None,
        metadata={"query_id": "stop-repair"}, portfolio_context=None,
    )
    pipeline._finalize_and_persist_result(
        result, artifacts, market_phase_summary=None, analysis_context_pack_overview=None,
        report_type="simple", snapshot_context={}, news_content_for_save=None,
    )
    return saved[0]


def test_backfill_keeps_model_null_instead_of_support_price():
    result = result_with({**PRICES, "stop_loss": None})
    pipeline = pipeline_with()
    pipeline._backfill_agent_dashboard_fields(result, TREND, "zh-TW")
    assert result.dashboard["battle_plan"]["sniper_prices"]["stop_loss"] is None
    assert extract_sniper_points(result)["stop_loss"] is None


@pytest.mark.parametrize("code", ["AAPL", "2330.TW", "00679B.TWO"])
@pytest.mark.parametrize("prices", [ABSENT, [], "N/A", {}, {**PRICES, "stop_loss": None}])
def test_agent_repairs_every_missing_block_shape_and_keeps_only_model_fields(code, prices):
    result = result_with(prices, code=code)
    pipeline = pipeline_with('{"sniper_prices":{"stop_loss":110}}')
    pipeline._backfill_agent_dashboard_fields(result, TREND, "zh-TW")
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh-TW")
    pipeline.analyzer.generate_text.assert_called_once()
    prompt = pipeline.analyzer.generate_text.call_args.args[0]
    assert "sniper_prices.stop_loss" in prompt
    assert "96" in prompt and "ATR14" in prompt and "3.5" in prompt
    assert extract_sniper_points(result)["stop_loss"] == 110
    expected = PRICES if isinstance(prices, dict) and prices else {"stop_loss": 110}
    assert result.dashboard["battle_plan"]["sniper_prices"] == expected


@pytest.mark.parametrize("prices", [ABSENT, [], "N/A", {}, {**PRICES, "stop_loss": None}])
@pytest.mark.parametrize("reply", ["{}", '{"sniper_prices":{"stop_loss":null}}', "暫不設定", "broken"])
@pytest.mark.parametrize("code, expected_action", [("2330.TW", "watch"), ("AAPL", "buy")])
def test_no_model_price_after_one_repair_preserves_block_and_market_scope(prices, reply, code, expected_action):
    result = result_with(prices, code=code)
    pipeline = pipeline_with(reply)
    before = deepcopy(result.dashboard["battle_plan"])
    assert not pipeline._repair_agent_stop_loss(result, TREND, "zh-TW")
    pipeline.analyzer.generate_text.assert_called_once()
    assert result.dashboard["battle_plan"] == before
    saved = finalize(pipeline, result)
    assert result.action == saved.action == expected_action
    assert extract_sniper_points(saved)["stop_loss"] is None
    if expected_action == "watch":
        assert "缺停損價" in result.risk_warning
        assert "無法檢查報酬風險比" in result.risk_warning
        assert result.risk_warning in extract_decision_guardrail_reason({"dashboard": saved.dashboard})
    else:
        assert "cost_check" not in saved.dashboard["battle_plan"]
        assert not result.risk_warning


@pytest.mark.parametrize("action, decision, score, repair", [
    ("buy", "buy", 78, True), ("add", "buy", 78, True),
    ("hold", "hold", 68, True), ("watch", "hold", 68, True),
    ("hold", "hold", 55, False), ("watch", "hold", 55, False),
    ("reduce", "sell", 68, False), ("sell", "sell", 78, False),
    ("reduce", "hold", 68, False),
])
def test_agent_repair_matches_real_score_alignment_without_changing_sell_guardrail(action, decision, score, repair):
    result = result_with({**PRICES, "stop_loss": None}, action=action, decision=decision, score=score)
    pipeline = pipeline_with('{"sniper_prices":{"stop_loss":110}}')
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh-TW") is repair
    assert pipeline.analyzer.generate_text.call_count == int(repair)


@pytest.mark.parametrize("field, label", [
    ("ideal_buy", "缺進場價"), ("stop_loss", "缺停損價"), ("take_profit", "缺目標價"),
])
def test_any_missing_tw_model_level_downgrades_before_history_and_signal(field, label):
    from src.services.decision_signal_extractor import build_decision_signal_payload_from_report

    result = result_with({**PRICES, field: None})
    saved = finalize(pipeline_with(), result)
    assert result.action == saved.action == "watch"
    check = saved.dashboard["battle_plan"]["cost_check"]
    assert check["status"] == "levels_missing" and check["passed"] is False
    assert check["missing_fields"] == [field]
    assert label in saved.risk_warning
    assert "無法檢查報酬風險比" in saved.risk_warning
    signal = build_decision_signal_payload_from_report(
        saved, trace_id="stop-repair", query_source="test", report_type="simple", profile_source="legacy_unknown",
    )
    assert signal["action"] == "watch"
    assert label in signal["metadata"]["guardrail_reason"]


def test_model_prices_are_kept_and_cost_checked_normally():
    result = result_with(PRICES)
    pipeline = pipeline_with()
    pipeline._backfill_agent_dashboard_fields(result, TREND, "zh-TW")
    assert not pipeline._repair_agent_stop_loss(result, TREND, "zh-TW")
    pipeline.analyzer.generate_text.assert_not_called()
    saved = finalize(pipeline, result)
    assert saved.action == "buy"
    assert saved.dashboard["battle_plan"]["sniper_prices"] == PRICES
    assert saved.dashboard["battle_plan"]["cost_check"]["passed"] is True


@pytest.mark.parametrize("prices", [[], {**PRICES, "stop_loss": None}])
def test_agent_model_supplies_complete_levels_and_normal_cost_evaluation(prices):
    result = result_with(prices)
    pipeline = pipeline_with(json.dumps({"sniper_prices": PRICES}))
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh-TW")
    saved = finalize(pipeline, result)
    assert saved.action == "buy"
    assert saved.dashboard["battle_plan"]["sniper_prices"] == PRICES
    assert saved.dashboard["battle_plan"]["cost_check"]["status"] == "ok"
    assert saved.dashboard["battle_plan"]["cost_check"]["passed"] is True


def test_agent_partial_repair_does_not_hide_missing_entry_and_target():
    result = result_with([])
    pipeline = pipeline_with('{"sniper_prices":{"stop_loss":110}}')
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh-TW")
    saved = finalize(pipeline, result)
    assert saved.action == "watch"
    assert saved.dashboard["battle_plan"]["sniper_prices"] == {"stop_loss": 110}
    assert saved.dashboard["battle_plan"]["cost_check"]["missing_fields"] == ["ideal_buy", "take_profit"]
    assert "缺進場價" in saved.risk_warning and "缺目標價" in saved.risk_warning


def run_analyzer(prices, *, code="2330.TW", reply_prices=PRICES, integrity=False, retries=0,
                 action="buy", decision="buy", score=78, repair_failure=None, responses=None):
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._config_override = SimpleNamespace(
        generation_backend="codex_cli", generation_fallback_backend="", litellm_model="",
        gemini_request_delay=0, report_language="zh-TW", llm_temperature=0.2,
        report_integrity_enabled=integrity, report_integrity_retry=retries,
    )
    initial = result_with(prices, code=code, action=action, decision=decision, score=score)
    repaired = result_with(reply_prices, code=code, action=action, decision=decision, score=score)
    client = MagicMock()
    client.generate.side_effect = responses or [
        (json.dumps(initial.to_dict(), ensure_ascii=False), "fake", None),
        repair_failure or (json.dumps(repaired.to_dict(), ensure_ascii=False), "fake", None),
    ]
    analyzer._llm = client
    with patch.object(analyzer, "is_available", return_value=True), \
            patch.object(analyzer, "get_generation_backend_config_error", return_value=None), \
            patch.object(analyzer, "_get_analysis_system_prompt", return_value="system"), \
            patch.object(analyzer, "_get_skill_prompt_sections", return_value=(None, None, True)), \
            patch.object(analyzer, "_format_prompt", return_value="base"), \
            patch.object(analyzer, "_build_market_snapshot", return_value={}):
        result = analyzer.analyze({"code": code, "stock_name": "測試",
                                   "trend_analysis": {"support_levels": [96], "atr14_pct": 3.5}})
    assert result.success, result.error_message
    return result, client


@pytest.mark.parametrize("prices", [ABSENT, [], "N/A", {}, {**PRICES, "stop_loss": None}])
@pytest.mark.parametrize("code", ["AAPL", "2330.TW"])
@pytest.mark.parametrize("integrity, retries", [(False, 0), (True, 0), (True, 3)])
def test_single_model_repairs_once_with_support_and_atr_even_when_integrity_disabled(prices, code, integrity, retries):
    result, client = run_analyzer(prices, code=code, integrity=integrity, retries=retries)
    assert client.generate.call_count == 2
    prompt = client.generate.call_args.args[0]
    assert "sniper_prices.stop_loss" in prompt
    assert "96" in prompt and "ATR14" in prompt and "3.5" in prompt
    assert extract_sniper_points(result) == {**PRICES, "secondary_buy": None}


@pytest.mark.parametrize("code, action", [("2330.TW", "watch"), ("AAPL", "buy")])
def test_single_model_still_null_after_retry_uses_same_cost_scope(code, action):
    prices = {**PRICES, "stop_loss": None}
    result, client = run_analyzer(prices, code=code, reply_prices=prices, integrity=True, retries=3)
    assert client.generate.call_count == 2
    assert extract_sniper_points(result)["stop_loss"] is None
    saved = finalize(pipeline_with(), result)
    assert saved.action == action


def test_stop_first_missing_during_general_completion_still_gets_one_stop_repair():
    initial = result_with(PRICES, code="2330.TW")
    initial.analysis_summary = ""
    missing_stop = result_with({**PRICES, "stop_loss": None}, code="2330.TW")
    repaired = result_with(PRICES, code="2330.TW")
    responses = [(json.dumps(item.to_dict(), ensure_ascii=False), "fake", None)
                 for item in (initial, missing_stop, repaired)]
    result, client = run_analyzer(PRICES, integrity=True, retries=1, responses=responses)
    assert client.generate.call_count == 3
    assert extract_sniper_points(result)["stop_loss"] == 110
    assert "96" in client.generate.call_args.args[0]


@pytest.mark.parametrize("code, action", [("2330.TW", "watch"), ("AAPL", "buy")])
@pytest.mark.parametrize("repair_failure", [
    RuntimeError("repair failed"), _AllModelsFailedError("repair failed"), ("not JSON", "fake", None),
])
def test_single_model_repair_failure_keeps_original_for_cost_check(code, action, repair_failure):
    prices = {**PRICES, "stop_loss": None}
    result, client = run_analyzer(prices, code=code, repair_failure=repair_failure)
    assert client.generate.call_count == 2
    assert result.dashboard["battle_plan"]["sniper_prices"] == prices
    assert finalize(pipeline_with(), result).action == action


@pytest.mark.parametrize("decision, action, score", [
    ("buy", "buy", 78), ("hold", "hold", 55), ("sell", "reduce", 78),
])
def test_single_model_preserves_valid_stop_and_non_actionable_decisions(decision, action, score):
    prices = PRICES if decision == "buy" else {**PRICES, "stop_loss": None}
    result, client = run_analyzer(prices, decision=decision, action=action, score=score)
    assert client.generate.call_count == 1
    assert result.action == action


@pytest.mark.parametrize("multi_agent", [False, True])
@pytest.mark.parametrize("code, expected", [("00631L.TW", "watch"), ("AAPL", "buy")])
def test_real_agent_path_repairs_before_persist_for_both_executor_modes(multi_agent, code, expected):
    from src.agent.executor import AgentResult

    pipeline = pipeline_with()
    pipeline.config.agent_arch = "multi" if multi_agent else "single"
    pipeline.search_service = None
    pipeline.social_sentiment_service = None
    pipeline._ensure_agent_history = MagicMock()
    pipeline._load_agent_analysis_context = MagicMock(return_value={})
    pipeline._load_persisted_intelligence_context = MagicMock(return_value=None)
    pipeline._build_analysis_context_pack_outputs = MagicMock(return_value=(None, None))
    payload = result_with([], code=code, action="watch", decision="hold", score=68).to_dict()
    agent = AgentResult(success=True, content="{}", dashboard=payload, provider="fake")
    executor = MagicMock()
    executor.run.return_value = agent
    saved = []
    pipeline.db.save_analysis_history.side_effect = lambda **kw: saved.append(deepcopy(kw["result"])) or 1
    prompt_state = SimpleNamespace(
        skill_manager=MagicMock(), skills_to_activate=[], explicit_skill_selection=False,
        use_legacy_default_prompt=True, technical_skill_policy="", skill_instructions="", default_skill_policy="",
    )
    with patch("src.agent.factory.get_tool_registry"), \
            patch("src.agent.factory.resolve_skill_prompt_state", return_value=prompt_state), \
            patch("src.agent.llm_adapter.LLMToolAdapter"), \
            patch("src.agent.factory._build_orchestrator", return_value=executor) as orchestrator, \
            patch("src.agent.executor.AgentExecutor", return_value=executor) as single:
        result = pipeline._analyze_with_agent(
            code, ReportType.SIMPLE, "repair-test", "測試", None, None,
        )
    assert orchestrator.call_count == int(multi_agent)
    assert single.call_count == int(not multi_agent)
    assert result is not None
    pipeline.analyzer.generate_text.assert_called_once()
    assert saved[0].action == result.action == expected


@pytest.mark.parametrize("supports", [[96], []])
def test_enhanced_context_carries_real_support_only_as_evidence(supports):
    from src.stock_analyzer import TrendAnalysisResult

    pipeline = pipeline_with()
    pipeline.search_service = None
    trend = TrendAnalysisResult(code="2330.TW", support_levels=supports, atr14_pct=3.5)
    context = pipeline._enhance_context({"code": trend.code}, None, None, trend, fundamental_context={})
    assert context["trend_analysis"]["support_levels"] == supports
    assert "sniper_prices" not in context


@pytest.mark.parametrize("code", ["2330.TW", "AAPL"])
def test_agent_repair_exception_keeps_original_prices_for_cost_guardrail(code):
    prices = {**PRICES, "stop_loss": None}
    result = result_with(prices, code=code)
    pipeline = pipeline_with()
    pipeline.analyzer.generate_text.side_effect = RuntimeError("repair failed")
    assert not pipeline._repair_agent_stop_loss(result, TREND, "zh-TW")
    pipeline.analyzer.generate_text.assert_called_once()
    assert result.dashboard["battle_plan"]["sniper_prices"] == prices
    assert finalize(pipeline, result).action == ("watch" if code == "2330.TW" else "buy")


def test_agent_legacy_model_numbers_survive_partial_stop_repair():
    result = result_with()
    result.dashboard["battle_plan"]["sniper_points"] = {"ideal_buy": "120元", "take_profit": "150元"}
    pipeline = pipeline_with('{"sniper_prices":{"stop_loss":110}}')
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh-TW")
    assert result.dashboard["battle_plan"]["sniper_prices"] == PRICES
    assert finalize(pipeline, result).action == "buy"


def test_legacy_model_stop_needs_no_repair_but_sentences_do():
    pipeline = pipeline_with('{"sniper_prices":{"stop_loss":110}}')
    result = result_with()
    result.dashboard["battle_plan"]["sniper_points"]["stop_loss"] = "110元"
    assert not pipeline._repair_agent_stop_loss(result, TREND, "zh-TW")
    pipeline.analyzer.generate_text.assert_not_called()
    result.dashboard["battle_plan"]["sniper_points"]["stop_loss"] = "跌破110元才評估停損"
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh-TW")
    pipeline.analyzer.generate_text.assert_called_once()


@pytest.mark.parametrize("language, label", [
    ("zh-TW", "缺目標價"), ("zh", "缺目标价"), ("en", "missing target price"), ("ko", "목표가 누락"),
])
def test_missing_level_reason_localizes_and_never_blames_trend_fallback_on_model(language, label):
    from src.trade_cost_guardrail import apply_trade_cost_guardrail

    result = result_with({**PRICES, "take_profit": None})
    result.data_sources = "agent:fake,trend:fallback"
    apply_trade_cost_guardrail(result, code=result.code, report_language=language)
    assert result.action == "watch"
    assert label in result.risk_warning
    assert "模型" not in result.risk_warning and "model" not in result.risk_warning.lower()


@pytest.mark.parametrize("action, decision, score", [
    ("hold", "hold", 55), ("watch", "hold", 55),
    ("reduce", "hold", 68), ("reduce", "sell", 78), ("sell", "sell", 78),
])
def test_missing_levels_do_not_change_final_non_buy_actions(action, decision, score):
    result = result_with({}, action=action, decision=decision, score=score)
    saved = finalize(pipeline_with(), result)
    assert saved.action == action
    assert saved.sentiment_score == score
    assert not saved.risk_warning
