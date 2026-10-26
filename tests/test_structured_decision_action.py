"""動作由模型以列舉給出；敘述文字不得改變結構化判斷。"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.agent.agents.decision_agent import DecisionAgent
from src.agent.executor import AGENT_SYSTEM_PROMPT, LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT
from src.agent.protocols import AgentContext
from src.analyzer import AnalysisResult, GeminiAnalyzer
from src.schemas.decision_action import build_action_fields, normalize_decision_action
from src.schemas.report_schema import AnalysisReportSchema
from src.services.decision_signal_extractor import build_decision_signal_payload_from_report


@pytest.mark.parametrize("advice", [
    "不建議現在買入", "建議現在買入", "買入後不追高", "no need to sell",
    "buy after sell-off", "Buy now.", "等待突破後買入", "持有/觀望待回踩",
])
def test_sentences_need_structured_action(advice):
    assert normalize_decision_action(advice) is None
    assert build_action_fields(operation_advice=advice, sentiment_score=82, align_with_score=True) == {
        "action": None, "action_label": None,
    }
    assert build_action_fields(operation_advice=advice, explicit_action="watch", report_language="zh-TW") == {
        "action": "watch", "action_label": "觀望",
    }


@pytest.mark.parametrize(("label", "action"), [
    (" 買入 ", "buy"), ("买入", "buy"), ("Sell", "sell"), ("賣出", "sell"),
    (" 減倉 ", "reduce"), ("减仓", "reduce"), ("加碼", "add"), ("加码", "add"),
    ("持有", "hold"), ("觀望", "watch"), ("观望", "watch"), ("WATCH", "watch"),
])
def test_exact_labels_remain_compatible(label, action):
    assert normalize_decision_action(label) == action
    assert build_action_fields(operation_advice=label)["action"] == action


@pytest.mark.parametrize("action", ["buy", "add", "hold", "reduce", "sell", "watch", "avoid", "alert"])
def test_schema_declares_action_enum_and_preserves_it(action):
    assert "action" in AnalysisReportSchema.model_fields
    report = AnalysisReportSchema.model_validate({"operation_advice": "不建議現在買入", "action": action})
    assert report.action == action
    assert AnalysisReportSchema.model_validate({}).action is None


@pytest.mark.parametrize("invalid", ["不建議買入", "Buy now.", "strong_buy", "unknown", 1])
def test_schema_rejects_non_enum_action(invalid):
    with pytest.raises(ValidationError):
        AnalysisReportSchema.model_validate({"action": invalid})


@pytest.mark.parametrize("language", ["zh", "zh-TW", "en", "ko"])
@pytest.mark.parametrize("legacy", [True, False])
def test_all_report_prompts_require_action_enum(language, legacy):
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._get_skill_prompt_sections = lambda: ("", "", legacy)
    analyzer._tw_ma_weighted_active = lambda *args: False
    prompts = [
        analyzer._get_analysis_system_prompt(language, "00631L.TW"),
        LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT if legacy else AGENT_SYSTEM_PROMPT,
        DecisionAgent(MagicMock(), MagicMock()).system_prompt(AgentContext(meta={"report_language": language})),
    ]
    for prompt in prompts:
        assert '"action": "buy/add/hold/reduce/sell/watch/avoid/alert"' in prompt


@pytest.mark.parametrize("action", [None, "watch", "reduce"])
def test_parser_and_signal_extraction_share_structured_action(action):
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._get_runtime_config = lambda: SimpleNamespace(report_language="zh-TW")
    data = {"operation_advice": "建議現在買入", "sentiment_score": 50, "action": action}
    result = analyzer._parse_response(json.dumps(data), "00631L.TW", "元大台灣50正2")
    assert result.action == action
    assert result.decision_type == ("sell" if action == "reduce" else "hold")
    assert result.operation_advice == data["operation_advice"]
    payload = build_decision_signal_payload_from_report(
        result, trace_id="structured-action", query_source="test", report_type="simple", profile_source="legacy_unknown",
    )
    if action is None:
        assert payload is None
    else:
        assert payload["action"] == action
        assert payload["stock_code"] == "00631L.TW"


def test_negated_sentence_does_not_override_agent_watch():
    result = AnalysisResult(
        code="2330.TW", name="台積電", sentiment_score=50, trend_prediction="震盪",
        operation_advice="不建議現在買入", action="watch", decision_type="hold",
    )
    payload = build_decision_signal_payload_from_report(
        result, trace_id="negated-watch", query_source="test", report_type="simple", profile_source="legacy_unknown",
    )
    assert payload["action"] == "watch"


@pytest.mark.parametrize(("action", "advice", "expected"), [
    ("watch", "不建議現在買入", "watch"), ("reduce", "建議現在買入", "reduce"),
    (None, "建議現在買入", None), (None, "不建議現在買入", None), (None, " 減倉 ", "reduce"),
])
def test_history_and_reassessment_share_exact_action_contract(action, advice, expected):
    from datetime import datetime
    from src.services.decision_signal_reassess_service import (
        DecisionSignalUnsupportedReportSnapshotError, _build_candidate,
    )
    from src.services.decision_signal_service import DecisionSignalService
    from src.services.history_comparison_service import _record_to_signal
    from src.services.history_service import HistoryService

    raw = {"action": action, "operation_advice": advice, "sentiment_score": 50, "report_language": "zh-TW"}
    record = SimpleNamespace(
        code="2887A.TW", report_type="simple", operation_advice=advice, sentiment_score=50,
        raw_result=json.dumps(raw), created_at=datetime(2026, 1, 1), query_id="action-history",
        trend_prediction="震盪",
    )
    history = HistoryService.__new__(HistoryService)
    assert history._decision_action_fields_for_record(record, raw)["action"] == expected
    assert _record_to_signal(record)["action"] == expected
    assert DecisionSignalService._history_action_fields(raw=raw, record=record)[0] == expected
    if expected is None:
        with pytest.raises(DecisionSignalUnsupportedReportSnapshotError, match="no structured decision action"):
            _build_candidate(record, raw, {})
    else:
        assert _build_candidate(record, raw, {}).action == expected


@pytest.mark.parametrize("enabled", [True, False])
def test_actual_risk_override_updates_structured_action_only_when_applied(enabled):
    from src.agent.orchestrator import AgentOrchestrator
    from src.agent.protocols import AgentOpinion

    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator.config = SimpleNamespace(agent_risk_override=enabled)
    ctx = AgentContext(stock_code="2330.TW")
    ctx.set_data("final_dashboard", {"decision_type": "buy", "action": "buy", "action_label": "買入"})
    ctx.add_opinion(AgentOpinion(
        agent_name="risk", signal="sell", confidence=0.9, reasoning="重大風險",
        raw_data={"veto_buy": True},
    ))
    application = orchestrator._apply_risk_override(ctx)
    assert application.applied == enabled
    assert ctx.get_data("final_dashboard")["action"] == ("hold" if enabled else "buy")
    assert ctx.get_data("final_dashboard").get("action_label") == (None if enabled else "買入")


def test_finalization_preserves_structural_guardrail_action_before_history_write():
    from src.core.pipeline import StockAnalysisPipeline
    from src.services.analysis_context_builder import PipelineAnalysisArtifacts

    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(report_language="zh-TW")
    pipeline.save_context_snapshot = False
    pipeline._build_context_snapshot = MagicMock(return_value={})
    pipeline.db = MagicMock()
    saved = []

    def capture_save(*, result, **kwargs):
        saved.append((result.action, result.operation_advice))
        return None

    pipeline.db.save_analysis_history.side_effect = capture_save
    result = AnalysisResult(
        code="2330.TW", name="台積電", sentiment_score=82, trend_prediction="看多",
        operation_advice="買入", action="buy", decision_type="buy", report_language="zh-TW",
        current_price=100, dashboard={},
    )
    artifacts = PipelineAnalysisArtifacts(
        code="2330.TW", stock_name="台積電", market="tw", phase=None,
        base_context={}, enhanced_context={}, realtime_quote=None, trend_result=None, chip_data=None,
        fundamental_context={"capital_flow": {"status": "failed", "data": {}}},
        news_context=None, news_result_count=0, metadata={},
    )
    pipeline._finalize_and_persist_result(
        result, artifacts, market_phase_summary=None, analysis_context_pack_overview=None,
        report_type="simple", snapshot_context={}, news_content_for_save=None,
    )
    assert result.decision_type == "hold"
    assert result.action == "hold"
    assert result.operation_advice == "持有觀察"
    assert result.dashboard["decision_stability"]["applied"] is True
    assert saved == [("hold", "持有觀察")]
