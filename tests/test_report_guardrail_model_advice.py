# -*- coding: utf-8 -*-
"""護欄改寫結論時保留模型原句：只追加 model_one_sentence／model_position_advice／guardrail_kind，舊欄位不變。"""

import copy

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from api.v1.schemas.history import ReportSummary  # noqa: E402
from src.analyzer import (  # noqa: E402
    AnalysisResult,
    _downgrade_buy_without_capital_flow,
    _set_structural_hold_wording,
)
from src.daily_market_context_guardrail import _sync_softened_dashboard_fields  # noqa: E402
from src.phase_decision_guardrail import apply_phase_decision_guardrails  # noqa: E402
from src.services.report_decision_fields import extract_report_decision_fields  # noqa: E402

MODEL_SENTENCE = "42.2 回測不破試單 1 成，41 停損"
MODEL_POSITION = {"no_position": "42.2 附近試單 1 成", "has_position": "跌破 41 停損"}
DOWNGRADE_REASON = "資金流數據缺失，買入結論缺少資金面確認，先按觀察處理。"


def _buy_result() -> AnalysisResult:
    return AnalysisResult(
        code="2330.TW",
        name="台積電",
        sentiment_score=72,
        trend_prediction="看多",
        operation_advice="買入",
        decision_type="buy",
        action="buy",
        confidence_level="中",
        report_language="zh-TW",
        dashboard={
            "core_conclusion": {
                "one_sentence": MODEL_SENTENCE,
                "position_advice": dict(MODEL_POSITION),
            },
        },
    )


def _downgrade(result: AnalysisResult) -> None:
    _downgrade_buy_without_capital_flow(
        result,
        "zh-TW",
        current_price=42.5,
        support=41.0,
        resistance=45.0,
        flow_status="empty_stock_flow",
    )


def _structural_hold(result: AnalysisResult) -> None:
    _set_structural_hold_wording(
        result,
        "zh-TW",
        advice_key="range",
        reason_key="hold_mid_range",
        current_price=42.5,
        support=41.0,
        resistance=45.0,
        flow_bias="neutral",
    )


def _core(result: AnalysisResult) -> dict:
    return result.dashboard["core_conclusion"]


# ---------- (a) 資料不可用護欄 ----------

def test_capital_flow_downgrade_keeps_model_sentence_and_marks_data_unavailable() -> None:
    result = _buy_result()

    _downgrade(result)

    core = _core(result)
    assert core["model_one_sentence"] == MODEL_SENTENCE
    assert core["model_position_advice"] == MODEL_POSITION
    assert core["guardrail_kind"] == "data_unavailable"
    # Old fields keep the guardrail wording and action exactly as before.
    assert core["one_sentence"] == f"持有觀察：{DOWNGRADE_REASON}"
    assert core["position_advice"]["no_position"].startswith("空倉先不追買")
    assert result.action == "hold"
    assert result.decision_type == "hold"


def test_model_position_advice_is_a_snapshot_not_the_live_dict() -> None:
    result = _buy_result()

    _downgrade(result)

    core = _core(result)
    assert core["model_position_advice"] is not core["position_advice"]
    assert core["model_position_advice"] != core["position_advice"]


# ---------- (b) 市場邏輯護欄 ----------

def test_structural_hold_marks_market_logic() -> None:
    result = _buy_result()

    _structural_hold(result)

    core = _core(result)
    assert core["guardrail_kind"] == "market_logic"
    assert core["model_one_sentence"] == MODEL_SENTENCE
    assert core["one_sentence"] != MODEL_SENTENCE
    assert result.action == "watch"


def test_reapplied_guardrails_keep_first_model_sentence_and_latest_kind() -> None:
    result = _buy_result()

    _downgrade(result)
    _structural_hold(result)

    core = _core(result)
    assert core["model_one_sentence"] == MODEL_SENTENCE
    assert core["model_position_advice"] == MODEL_POSITION
    assert core["guardrail_kind"] == "market_logic"


def test_empty_model_sentence_is_not_preserved() -> None:
    result = _buy_result()
    _core(result)["one_sentence"] = "   "
    _core(result)["position_advice"] = {}

    _downgrade(result)

    core = _core(result)
    assert "model_one_sentence" not in core
    assert "model_position_advice" not in core
    assert core["guardrail_kind"] == "data_unavailable"


# ---------- 其他改寫 one_sentence 的護欄 ----------

def test_daily_market_softening_preserves_model_sentence() -> None:
    dashboard = {"core_conclusion": {"one_sentence": MODEL_SENTENCE, "position_advice": dict(MODEL_POSITION)}}

    _sync_softened_dashboard_fields(dashboard, softened_advice="持有觀察", language="zh-TW")

    core = dashboard["core_conclusion"]
    assert core["one_sentence"] == "持有觀察"
    assert core["model_one_sentence"] == MODEL_SENTENCE
    assert core["model_position_advice"] == MODEL_POSITION
    assert core["guardrail_kind"] == "market_logic"


def test_phase_recap_rewrite_preserves_sentence_only() -> None:
    result = AnalysisResult(
        code="2330.TW",
        name="台積電",
        sentiment_score=50,
        trend_prediction="震荡",
        operation_advice="今日收盘后复盘显示可买入",
        decision_type="hold",
        action="buy",
        confidence_level="中",
        report_language="zh",
        analysis_summary="明日重点关注突破",
        dashboard={
            "core_conclusion": {
                "one_sentence": "今日收盘后复盘显示偏强",
                "position_advice": {"no_position": "等回踩", "has_position": "续抱"},
            },
            "phase_decision": {"immediate_action": "明日重点关注突破", "watch_conditions": []},
        },
    )

    apply_phase_decision_guardrails(
        result,
        market_phase_summary={"phase": "intraday", "market": "cn"},
        analysis_context_pack_overview={"data_quality": {"overall_status": "available"}},
        report_language="zh",
    )

    core = _core(result)
    assert core["one_sentence"] == "等待盘中确认，禁止追高。"
    assert core["model_one_sentence"] == "今日收盘后复盘显示偏强"
    assert core["guardrail_kind"] == "market_logic"
    # position_advice is not rewritten on this path, so there is nothing to preserve.
    assert "model_position_advice" not in core


# ---------- (c) 報告欄位投影 ----------

def test_projection_is_none_without_guardrail() -> None:
    raw = {
        "dashboard": {
            "core_conclusion": {
                "one_sentence": MODEL_SENTENCE,
                "position_advice": dict(MODEL_POSITION),
                # Stray keys must not leak when no guardrail was applied.
                "model_one_sentence": "stale",
                "guardrail_kind": "market_logic",
            },
        },
    }

    fields = extract_report_decision_fields(raw, "zh-TW")

    assert fields["guardrail_applied"] is False
    assert fields["model_one_sentence"] is None
    assert fields["model_position_advice"] is None
    assert fields["guardrail_kind"] is None


def test_projection_is_none_for_market_review_and_non_dict() -> None:
    for raw in ({"raw_response": "複盤"}, None):
        fields = extract_report_decision_fields(raw, "zh-TW")
        assert fields["model_one_sentence"] is None
        assert fields["model_position_advice"] is None
        assert fields["guardrail_kind"] is None


def test_projection_returns_preserved_wording_after_guardrail() -> None:
    result = _buy_result()
    _downgrade(result)

    fields = extract_report_decision_fields({"dashboard": copy.deepcopy(result.dashboard)}, "zh-TW")

    assert fields["guardrail_applied"] is True
    assert fields["model_one_sentence"] == MODEL_SENTENCE
    assert fields["model_position_advice"] == MODEL_POSITION
    assert fields["guardrail_kind"] == "data_unavailable"
    assert fields["one_sentence"] == f"持有觀察：{DOWNGRADE_REASON}"


def test_old_guarded_report_without_model_keys_projects_none() -> None:
    raw = {
        "dashboard": {
            "core_conclusion": {"one_sentence": "持有觀察：資金流數據缺失"},
            "decision_stability": {"applied": True, "reason": "資金流數據缺失"},
        },
    }

    fields = extract_report_decision_fields(raw, "zh-TW")

    assert fields["guardrail_applied"] is True
    assert fields["model_one_sentence"] is None
    assert fields["model_position_advice"] is None
    assert fields["guardrail_kind"] is None


def test_unknown_guardrail_kind_is_dropped_and_summary_validates() -> None:
    raw = {
        "dashboard": {
            "core_conclusion": {"one_sentence": "持有觀察", "guardrail_kind": "something_else"},
            "decision_stability": {"applied": True, "reason": "護欄"},
        },
    }

    fields = extract_report_decision_fields(raw, "zh-TW")
    fields["phase_watch_conditions"] = fields.pop("watch_conditions")

    assert fields["guardrail_kind"] is None
    summary = ReportSummary(**fields)
    assert summary.guardrail_kind is None
    assert summary.model_one_sentence is None
