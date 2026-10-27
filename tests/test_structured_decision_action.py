# -*- coding: utf-8 -*-
"""動作由 LLM／agent 的結構化 `action` 欄位給出；程式碼不從建議文字推斷動作。"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.agent.orchestrator import AgentOrchestrator, _risk_adjusted_action  # noqa: E402
from src.agent.protocols import AgentContext  # noqa: E402
from src.agent.risk_override import RiskOverrideApplication  # noqa: E402
from src.agent.executor import AGENT_SYSTEM_PROMPT, LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT  # noqa: E402
from src.analyzer import AnalysisResult, GeminiAnalyzer, _set_structural_hold_wording  # noqa: E402
from src.core.pipeline import StockAnalysisPipeline  # noqa: E402
from src.phase_decision_guardrail import apply_phase_decision_guardrails  # noqa: E402
from src.schemas.decision_action import build_action_fields, normalize_decision_action  # noqa: E402
from src.schemas.report_schema import AnalysisReportSchema  # noqa: E402
from src.services.decision_signal_extractor import build_decision_signal_payload_from_report  # noqa: E402

_ACTION_ENUM = "buy/add/hold/reduce/sell/watch/avoid/alert"


def _result(**overrides) -> AnalysisResult:
    defaults = dict(
        code="2330.TW",
        name="台積電",
        sentiment_score=50,
        trend_prediction="震盪",
        operation_advice="觀望",
        decision_type="hold",
        confidence_level="中",
        report_language="zh-TW",
    )
    defaults.update(overrides)
    return AnalysisResult(**defaults)


# ---------- prompt：兩條 agent 路徑都要求結構化 action ----------

@pytest.mark.parametrize("language", ["zh", "zh-TW", "en", "ko"])
def test_decision_agent_prompt_requires_structured_action(language: str) -> None:
    from src.agent.agents.decision_agent import DecisionAgent

    agent = DecisionAgent.__new__(DecisionAgent)
    agent.skill_instructions = ""
    ctx = AgentContext(query="analyze", stock_code="2330.TW", meta={"report_language": language})
    prompt = agent.system_prompt(ctx)

    assert "decision_type, action, confidence_level" in prompt
    assert "buy|add|hold|reduce|sell|watch|avoid|alert" in prompt
    assert "never infers it from ``operation_advice``" in prompt


@pytest.mark.parametrize("prompt_name", ["LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT", "AGENT_SYSTEM_PROMPT"])
def test_agent_executor_prompts_require_structured_action(prompt_name: str) -> None:
    from src.agent import executor

    prompt = getattr(executor, prompt_name)
    assert f'"action": "{_ACTION_ENUM}"' in prompt
    assert "不會從 `operation_advice` 的文字推斷動作" in prompt


def test_analyzer_canonical_scale_prompt_requires_structured_action() -> None:
    from src.schemas.decision_scale import (
        CANONICAL_DECISION_SCALE_PROMPT_EN,
        CANONICAL_DECISION_SCALE_PROMPT_ZH,
    )

    assert "不會從 `operation_advice` 文字推斷動作" in CANONICAL_DECISION_SCALE_PROMPT_ZH
    assert "never infers it from `operation_advice` text" in CANONICAL_DECISION_SCALE_PROMPT_EN


# ---------- orchestrator：風控下調用結構化訊號改寫 action ----------

def _orchestrator_payload(action):
    payload = {
        "decision_type": "buy",
        "sentiment_score": 75,
        "operation_advice": "買入",
        "analysis_summary": "趨勢偏強。",
        "dashboard": {},
    }
    if action is not None:
        payload["action"] = action
    return payload


def _risk_ctx(applied: bool) -> AgentContext:
    ctx = AgentContext(query="test", stock_code="2330.TW", stock_name="台積電")
    if applied:
        ctx.meta["risk_override_application"] = RiskOverrideApplication(
            evidence_present=True,
            override_enabled=True,
            trigger="risk_veto",
            applied=True,
            reason="risk_veto_applied",
            post_risk_signal="hold",
            from_signal="buy",
            to_signal="hold",
        )
    return ctx


def _finalize(payload, ctx):
    orch = AgentOrchestrator(tool_registry=MagicMock(), llm_adapter=MagicMock())
    return orch._finalize_dashboard_payload(payload, ctx)


def test_risk_veto_replaces_stale_llm_buy_action_with_watch() -> None:
    normalized = _finalize(_orchestrator_payload("buy"), _risk_ctx(applied=True))

    assert normalized["decision_type"] == "hold"
    assert normalized["action"] == "watch"


def test_risk_veto_keeps_llm_action_already_within_post_risk_signal() -> None:
    # 反向：LLM 已給 hold 桶內的 avoid，不可被一律覆寫成 watch
    normalized = _finalize(_orchestrator_payload("avoid"), _risk_ctx(applied=True))

    assert normalized["action"] == "avoid"


def test_without_risk_override_llm_action_passes_through_untouched() -> None:
    # 反向：沒有風控下調時不改寫，也不憑 decision_type 憑空補 action
    assert _finalize(_orchestrator_payload("buy"), _risk_ctx(applied=False))["action"] == "buy"
    assert "action" not in _finalize(_orchestrator_payload(None), _risk_ctx(applied=False))


@pytest.mark.parametrize(
    ("raw_action", "signal", "expected"),
    [
        ("buy", "hold", "watch"),
        ("add", "sell", "reduce"),
        ("hold", "sell", "reduce"),
        (None, "hold", "watch"),
        ("sell", "sell", "sell"),
        ("alert", "hold", "alert"),
    ],
)
def test_risk_adjusted_action_matrix(raw_action, signal, expected) -> None:
    assert _risk_adjusted_action(raw_action, signal) == expected


# ---------- pipeline refresh：護欄給的結構化動作不被句子建議抹掉 ----------

def test_refresh_keeps_guardrail_structured_action_when_advice_becomes_sentence() -> None:
    result = _result(
        operation_advice="等待盤中確認，禁止追高。",
        action="watch",
        sentiment_score=50,
    )

    StockAnalysisPipeline._refresh_decision_action_for_final_result(
        result,
        report_type="simple",
        previous_operation_advice="買入",
        record_contradiction=False,
    )

    assert result.action == "watch"


@pytest.mark.parametrize(("action", "decision_type", "expected"), [
    ("buy", "hold", None),      # 改寫者沒同步動作：殘留 buy 與三態 hold 矛盾，保守清空
    ("reduce", "buy", None),
    ("watch", "hold", "watch"),  # 反向：與三態一致的結構化動作要保留
    ("avoid", "hold", "avoid"),
    ("reduce", "sell", "reduce"),
])
def test_refresh_sentence_rewrite_clears_only_action_inconsistent_with_decision_type(
    action, decision_type, expected,
) -> None:
    result = _result(operation_advice="持有觀察", action=action, decision_type=decision_type, sentiment_score=50)

    StockAnalysisPipeline._refresh_decision_action_for_final_result(
        result,
        report_type="simple",
        previous_operation_advice="買入",
        record_contradiction=False,
    )

    assert result.action == expected


def test_refresh_bare_label_rewrite_replaces_stale_structured_action() -> None:
    # 反向：建議被改寫成單一標籤「觀望」時，殘留的 buy 仍要被換掉
    result = _result(operation_advice="觀望", action="buy", sentiment_score=50)

    StockAnalysisPipeline._refresh_decision_action_for_final_result(
        result,
        report_type="simple",
        previous_operation_advice="買入",
        record_contradiction=False,
    )

    assert result.action == "watch"


# ---------- 改寫建議文字的護欄要自己設結構化動作 ----------

@pytest.mark.parametrize(("advice_key", "expected"), [("range", "watch"), ("shakeout", "hold"), ("hold", "hold")])
def test_structural_hold_wording_sets_structured_action_without_calibration(advice_key, expected) -> None:
    result = _result(operation_advice="買入", action="buy", decision_type="hold")

    _set_structural_hold_wording(
        result,
        "zh-TW",
        advice_key=advice_key,
        reason_key="hold_mid_range",
        current_price=31.0,
        support=30.0,
        resistance=34.0,
        flow_bias="neutral",
    )

    assert result.action == expected


def test_phase_recap_rewrite_sets_structured_watch_action() -> None:
    result = _result(
        operation_advice="今日收盘后复盘显示可买入",
        action="buy",
        report_language="zh",
        analysis_summary="明日重点关注突破",
        dashboard={
            "core_conclusion": {"one_sentence": "今日收盘后复盘显示偏强"},
            "phase_decision": {"immediate_action": "明日重点关注突破", "watch_conditions": []},
        },
    )

    apply_phase_decision_guardrails(
        result,
        market_phase_summary={"phase": "intraday", "market": "cn"},
        analysis_context_pack_overview={"data_quality": {"overall_status": "available"}},
        report_language="zh",
    )

    assert result.operation_advice == "等待盘中确认，禁止追高。"
    assert result.action == "watch"


# ---------- 解析、信號、歷史與重評共用同一份結構化動作契約 ----------

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


@pytest.mark.parametrize("language", ["zh", "zh-TW", "en", "ko"])
@pytest.mark.parametrize("legacy", [True, False])
def test_all_report_prompts_require_action_enum(language, legacy):
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._get_skill_prompt_sections = lambda: ("", "", legacy)
    analyzer._tw_ma_weighted_active = lambda *args: False
    prompts = [
        analyzer._get_analysis_system_prompt(language, "00631L.TW"),
        LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT if legacy else AGENT_SYSTEM_PROMPT,
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


def _finalize_pipeline(saved: list):
    from src.core.pipeline import StockAnalysisPipeline

    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(report_language="zh")
    pipeline.save_context_snapshot = False
    pipeline._build_context_snapshot = MagicMock(return_value={})
    pipeline.db = MagicMock()

    def capture_save(*, result, **kwargs):
        saved.append((result.action, result.decision_type, result.operation_advice))
        return None

    pipeline.db.save_analysis_history.side_effect = capture_save
    return pipeline


def _finalize_artifacts(code: str = "2330.TW"):
    from src.services.analysis_context_builder import PipelineAnalysisArtifacts

    return PipelineAnalysisArtifacts(
        code=code, stock_name="台積電", market="tw", phase=None,
        base_context={}, enhanced_context={}, realtime_quote=None, trend_result=None, chip_data=None,
        fundamental_context={}, news_context=None, news_result_count=0, metadata={},
    )


@pytest.mark.parametrize("decision_type", ["buy", "sell"])
def test_finalization_keeps_phase_guardrail_watch_for_buy_or_sell_decision(decision_type: str) -> None:
    # 盤中盤後口吻護欄改寫成「等待盤中確認」句子並給觀望：decision_type 若仍是 buy／sell，
    # 刷新時的三態對不上檢查會把觀望清成未知，整條動作鏈失效、DecisionSignal 不寫入。
    saved: list = []
    pipeline = _finalize_pipeline(saved)
    advice = "买入（盘后复盘）" if decision_type == "buy" else "卖出（盘后复盘）"
    result = AnalysisResult(
        code="2330.TW", name="台積電", sentiment_score=68, trend_prediction="看多",
        operation_advice=advice, action=decision_type, decision_type=decision_type,
        report_language="zh", current_price=100, dashboard={},
    )
    pipeline._finalize_and_persist_result(
        result, _finalize_artifacts(), market_phase_summary={"phase": "intraday", "market": "tw"},
        analysis_context_pack_overview={"data_quality": {"overall_status": "available"}},
        report_type="simple", snapshot_context={}, news_content_for_save=None,
    )

    assert result.operation_advice == "等待盘中确认，禁止追高。"
    assert result.action == "watch"
    assert result.decision_type == "hold"
    assert saved and saved[-1][:2] == ("watch", "hold")


def test_finalization_still_clears_unsynced_action_after_sentence_rewrite() -> None:
    # 反向：護欄改寫成句子卻沒同步動作（action 仍是 buy、decision_type 已降 hold）時照樣清掉殘留值。
    result = _result(operation_advice="持有觀察，等待量能確認", action="buy", decision_type="hold",
                     sentiment_score=55)
    StockAnalysisPipeline._refresh_decision_action_for_final_result(
        result, report_type="simple", previous_operation_advice="買入", record_contradiction=False,
    )
    assert result.action is None


def test_parsed_reduce_without_advice_survives_buy_band_sell_guardrail() -> None:
    # LLM 只給 action=reduce、沒給 operation_advice／decision_type：解析器補預設「持有」並投影 sell，
    # 買入區分數的 sell 矛盾護欄要沿用結構化 reduce，不能被預設的裸標籤「持有」蓋掉。
    response = json.dumps({
        "stock_name": "台積電", "sentiment_score": 68, "action": "reduce",
        "analysis_summary": "量能轉弱", "dashboard": {"core_conclusion": {"one_sentence": "量能轉弱"}},
    })
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    result = analyzer._parse_response(response, "2330.TW", "台積電")
    assert (result.action, result.decision_type) == ("reduce", "sell")

    saved: list = []
    pipeline = _finalize_pipeline(saved)
    result.current_price = 100
    pipeline._finalize_and_persist_result(
        result, _finalize_artifacts(), market_phase_summary=None, analysis_context_pack_overview=None,
        report_type="simple", snapshot_context={}, news_content_for_save=None,
    )

    assert result.action == "reduce"
    assert saved and saved[-1][0] == "reduce"


@pytest.mark.parametrize(("action", "advice", "expected"), [
    # 反向：結構化動作是買入類時仍不可升級，有裸標籤就退回標籤、否則退回觀望。
    ("buy", "持有", "hold"),
    ("add", "觀望，等待回踩", "watch"),
    ("buy", "減倉", "reduce"),
    (None, "持有", "hold"),
])
def test_buy_band_sell_guardrail_never_keeps_buy_class_action(action, advice, expected) -> None:
    result = _result(sentiment_score=68, decision_type="sell", action=action, operation_advice=advice)
    StockAnalysisPipeline._refresh_decision_action_for_final_result(
        result, report_type="simple", previous_operation_advice=advice, record_contradiction=False,
    )
    assert result.action == expected


_PHASE_RECAP_CASES = [
    ("zh", "买入（盘后复盘）", "等待盘中确认，禁止追高。"),
    ("zh", "卖出（盘后复盘）", "等待盘中确认，禁止追高。"),
    ("ko", "매수 장 마감 후 리뷰", "장중 확인을 기다리고 추격 매수하지 마세요."),
    ("ko", "매도 장 마감 후 리뷰", "장중 확인을 기다리고 추격 매수하지 마세요."),
    ("en", "Buy (post-market recap)", "Wait for intraday confirmation; do not chase."),
    ("en", "Sell (post-market recap)", "Wait for intraday confirmation; do not chase."),
]


def _finalize_phase_recap(language: str, advice: str, decision_type: str, score: int, saved: list) -> AnalysisResult:
    pipeline = _finalize_pipeline(saved)
    pipeline.config = SimpleNamespace(report_language=language)
    result = AnalysisResult(
        code="2330.TW", name="台積電", sentiment_score=score, trend_prediction="看多",
        operation_advice=advice, action=decision_type, decision_type=decision_type,
        report_language=language, current_price=100, dashboard={},
    )
    pipeline._finalize_and_persist_result(
        result, _finalize_artifacts(), market_phase_summary={"phase": "intraday", "market": "tw"},
        analysis_context_pack_overview={"data_quality": {"overall_status": "available"}},
        report_type="simple", snapshot_context={}, news_content_for_save=None,
    )
    return result


@pytest.mark.parametrize("score", [68, 30])
@pytest.mark.parametrize("language,advice,safe_advice", _PHASE_RECAP_CASES)
def test_phase_guardrail_watch_is_not_realigned_to_score(language: str, advice: str, safe_advice: str,
                                                         score: int) -> None:
    # 盤中盤後口吻護欄給的觀望是護欄決定，必須留下 guardrail_reason：
    # 否則買入區（68）會被分數對齊升成 buy、賣出區（30）降成 reduce，賣出決策反而寫出買入訊號。
    from src.schemas.decision_action import display_action_fields_for_result
    from src.services.decision_signal_extractor import resolve_decision_signal_action_fields

    saved: list = []
    decision_type = "buy" if advice.lower().startswith(("买", "매수", "buy")) else "sell"
    result = _finalize_phase_recap(language, advice, decision_type, score, saved)

    assert result.operation_advice == safe_advice
    assert result.action == "watch"
    assert saved and saved[-1][:2] == ("watch", "hold")
    assert display_action_fields_for_result(result, report_type="simple")["action"] == "watch"
    assert resolve_decision_signal_action_fields(result, report_type="simple")["action"] == "watch"
    calibration = result.dashboard.get("decision_score_calibration") or {}
    assert calibration.get("guardrail_reason")
    assert calibration.get("final_action") == "watch"


def test_unguarded_watch_still_aligns_with_buy_band_score() -> None:
    # 反向：沒有任何護欄觸發的觀望（無盤後口吻）在買入區照舊對齊分數，修法不能把分數對齊整個關掉。
    from src.schemas.decision_action import display_action_fields_for_result

    saved: list = []
    pipeline = _finalize_pipeline(saved)
    result = AnalysisResult(
        code="2330.TW", name="台積電", sentiment_score=68, trend_prediction="看多",
        operation_advice="观望", action="watch", decision_type="hold",
        report_language="zh", current_price=100,
        # 模型給齊買點／停損／目標且扣成本划算：成本護欄放行，才看得到分數對齊本身
        dashboard={"battle_plan": {"sniper_prices": {
            "ideal_buy": 100, "secondary_buy": None, "stop_loss": 95, "take_profit": 115,
        }}},
    )
    pipeline._finalize_and_persist_result(
        result, _finalize_artifacts(), market_phase_summary={"phase": "intraday", "market": "tw"},
        analysis_context_pack_overview={"data_quality": {"overall_status": "available"}},
        report_type="simple", snapshot_context={}, news_content_for_save=None,
    )

    assert not (result.dashboard.get("decision_score_calibration") or {}).get("guardrail_reason")
    assert display_action_fields_for_result(result, report_type="simple")["action"] == "buy"


def test_unguarded_buy_band_watch_without_model_stop_is_downgraded_with_reason() -> None:
    # 同上但模型沒給停損：對齊成買入後由成本護欄以「缺停損價」降為觀望，原因記進護欄原因
    from src.schemas.decision_action import display_action_fields_for_result

    saved: list = []
    pipeline = _finalize_pipeline(saved)
    result = AnalysisResult(
        code="2330.TW", name="台積電", sentiment_score=68, trend_prediction="看多",
        operation_advice="观望", action="watch", decision_type="hold",
        report_language="zh", current_price=100,
        dashboard={"battle_plan": {"sniper_prices": {
            "ideal_buy": 100, "secondary_buy": None, "stop_loss": None, "take_profit": 115,
        }}},
    )
    pipeline._finalize_and_persist_result(
        result, _finalize_artifacts(), market_phase_summary={"phase": "intraday", "market": "tw"},
        analysis_context_pack_overview={"data_quality": {"overall_status": "available"}},
        report_type="simple", snapshot_context={}, news_content_for_save=None,
    )

    reason = (result.dashboard.get("decision_score_calibration") or {}).get("guardrail_reason")
    assert reason and reason.startswith("缺止损价")
    assert display_action_fields_for_result(result, report_type="simple")["action"] == "watch"


def test_phase_guardrail_records_reason_only_when_it_assigns_watch() -> None:
    # 反向：只改寫一句話結論、沒動建議與結構化動作時，不該寫 guardrail_reason 擋掉分數對齊。
    result = _result(
        operation_advice="买入", action="buy", decision_type="buy", sentiment_score=68, report_language="zh",
        dashboard={"core_conclusion": {"one_sentence": "收盘后复盘再看"}},
    )
    apply_phase_decision_guardrails(
        result, market_phase_summary={"phase": "intraday", "market": "tw"},
        analysis_context_pack_overview=None, report_language="zh",
    )
    assert result.action == "buy"
    assert "decision_score_calibration" not in result.dashboard
