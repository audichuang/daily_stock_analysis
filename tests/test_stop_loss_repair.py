# -*- coding: utf-8 -*-
"""買入結論缺模型停損價：程式只給證據請模型補一次，補不到由台股成本護欄降為觀望。

程式不拿技術面支撐價頂替模型的停損（舊行為：support_levels[0] 寫進 sniper_prices.stop_loss）。
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import (  # noqa: E402
    AnalysisResult,
    GeminiAnalyzer,
    format_stop_loss_evidence,
    parse_sniper_repair_reply,
)
from src.core.pipeline import StockAnalysisPipeline  # noqa: E402
from src.trade_cost_guardrail import apply_trade_cost_guardrail  # noqa: E402
from src.utils.sniper_points import SNIPER_KEYS, extract_sniper_points  # noqa: E402

TREND = SimpleNamespace(support_levels=[96.0, 92.5], atr14_pct=2.4)
MALFORMED_BLOCKS = [[], "N/A", {}]


def _result(code="AAPL", *, prices=None, decision_type="buy", action="buy", score=72,
            advice="买入", text_stop="", error_message=None):
    battle = {"sniper_points": {"ideal_buy": "100", "stop_loss": text_stop, "take_profit": "120"}}
    if prices is not None:
        battle["sniper_prices"] = prices
    return AnalysisResult(
        code=code, name="測試", sentiment_score=score, trend_prediction="看多",
        operation_advice=advice, decision_type=decision_type, action=action,
        analysis_summary="摘要", report_language="zh", current_price=100,
        error_message=error_message,
        dashboard={
            "core_conclusion": {"one_sentence": "一句話"},
            "intelligence": {"risk_alerts": []},
            "battle_plan": battle,
        },
    )


class _FakeAnalyzer:
    """記錄補全提示詞；提示詞沿用真的 GeminiAnalyzer 組法。"""

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []
        self._real = GeminiAnalyzer.__new__(GeminiAnalyzer)

    def build_sniper_repair_prompt(self, *args, **kwargs):
        return self._real.build_sniper_repair_prompt(*args, **kwargs)

    def generate_text(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return self.reply


def _pipeline(reply, *, enabled=True, retry=1):
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(
        report_language="zh", report_integrity_enabled=enabled, report_integrity_retry=retry,
    )
    pipeline.analyzer = _FakeAnalyzer(reply)
    return pipeline


def _reply(prices, points=None):
    body = {"sniper_prices": prices}
    if points is not None:
        body["sniper_points"] = points
    return json.dumps(body, ensure_ascii=False)


def _finalize(pipeline, result, code):
    from src.services.analysis_context_builder import PipelineAnalysisArtifacts

    pipeline.save_context_snapshot = False
    pipeline._build_context_snapshot = MagicMock(return_value={})
    pipeline.db = MagicMock()
    pipeline.db.save_analysis_history.return_value = None
    artifacts = PipelineAnalysisArtifacts(
        code=code, stock_name="測試", market="tw" if code.endswith(".TW") else "us", phase=None,
        base_context={}, enhanced_context={}, realtime_quote=None, trend_result=None, chip_data=None,
        fundamental_context={}, news_context=None, news_result_count=0, metadata={},
    )
    return pipeline._finalize_and_persist_result(
        result, artifacts, market_phase_summary=None, analysis_context_pack_overview=None,
        report_type="simple", snapshot_context={}, news_content_for_save=None,
    )


# ---------- 規則 1：缺停損就請模型補一次，只寫模型回的值 ----------


def test_null_model_stop_is_not_filled_with_support_and_prompt_carries_support_fact():
    pipeline = _pipeline(_reply({"stop_loss": None}))
    result = _result(prices={"ideal_buy": 100, "secondary_buy": None, "stop_loss": None, "take_profit": 120})
    # 轉換時的回填不得拿支撐價 96 寫進模型專屬欄位
    pipeline._backfill_agent_dashboard_fields(result, TREND, "zh")
    assert result.dashboard["battle_plan"]["sniper_prices"]["stop_loss"] is None

    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is False
    assert len(pipeline.analyzer.prompts) == 1
    prompt = pipeline.analyzer.prompts[0]
    assert "支撑位：96、92.5" in prompt and "ATR14：2.4%" in prompt
    # 模型仍回 null：維持 null，不由程式代填
    assert result.dashboard["battle_plan"]["sniper_prices"]["stop_loss"] is None
    assert extract_sniper_points(result)["stop_loss"] is None


def test_model_stop_from_repair_is_kept_as_is():
    pipeline = _pipeline(_reply({"stop_loss": 110}, {"stop_loss": "跌破 110 出場"}))
    result = _result(prices={"ideal_buy": 100, "secondary_buy": None, "stop_loss": None, "take_profit": 120})
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is True
    assert extract_sniper_points(result) == {
        "ideal_buy": 100, "secondary_buy": None, "stop_loss": 110, "take_profit": 120,
    }
    assert result.dashboard["battle_plan"]["sniper_points"]["stop_loss"] == "跌破 110 出場"


def test_model_stop_already_present_skips_repair():
    pipeline = _pipeline(_reply({"stop_loss": 90}))
    result = _result(prices={"ideal_buy": 100, "secondary_buy": None, "stop_loss": 95, "take_profit": 120})
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is False
    assert pipeline.analyzer.prompts == []
    assert extract_sniper_points(result)["stop_loss"] == 95


@pytest.mark.parametrize("code", ["AAPL", "2330.TW"])
@pytest.mark.parametrize("block", MALFORMED_BLOCKS, ids=["list", "na", "empty"])
def test_malformed_block_is_repaired_like_any_missing_stop(code, block):
    # 損壞區塊＝模型沒給：一樣請模型補，提示詞要整組四格；只寫模型回的格子
    pipeline = _pipeline(_reply({"ideal_buy": 100, "stop_loss": 94, "take_profit": 118}))
    result = _result(code, prices=block)
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is True
    assert len(pipeline.analyzer.prompts) == 1
    assert "dashboard.battle_plan.sniper_prices" in pipeline.analyzer.prompts[0]
    written = result.dashboard["battle_plan"]["sniper_prices"]
    assert written == {"ideal_buy": 100, "stop_loss": 94, "take_profit": 118}
    # 模型沒回的 secondary_buy 不由程式補成任何值
    assert "secondary_buy" not in written
    assert extract_sniper_points(result) == {
        "ideal_buy": 100, "secondary_buy": None, "stop_loss": 94, "take_profit": 118,
    }


def test_model_levels_are_kept_even_when_stop_is_still_missing():
    # 損壞區塊、模型補了買點與目標但停損仍 null：模型回的格子照寫，回報沒補到停損
    pipeline = _pipeline(_reply({"ideal_buy": 100, "stop_loss": None, "take_profit": 120}))
    result = _result(prices="N/A")
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is False
    assert result.dashboard["battle_plan"]["sniper_prices"] == {
        "ideal_buy": 100, "stop_loss": None, "take_profit": 120}


def test_legacy_text_contract_partial_reply_writes_stop_text_only():
    # 沒有 sniper_prices 的舊契約：模型只回停損時寫進文字，不另建缺格的 sniper_prices
    pipeline = _pipeline(_reply({"stop_loss": 95}))
    result = _result(prices=None, text_stop="跌破季線停損")
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is True
    assert "sniper_prices" not in result.dashboard["battle_plan"]
    assert extract_sniper_points(result) == {
        "ideal_buy": 100, "secondary_buy": None, "stop_loss": 95, "take_profit": 120,
    }


@pytest.mark.parametrize("text_levels", [("100", "120"), ("", "")], ids=["text-has-levels", "text-empty"])
def test_legacy_text_contract_partial_reply_writes_every_returned_level(text_levels):
    # 舊契約、模型回了買點／停損／目標但漏 secondary_buy：模型給的格子都要寫進文字，
    # 不能只留停損而沿用舊文字價位（混成 100/105/120），也不能把模型給的值丟掉
    pipeline = _pipeline(_reply({"ideal_buy": 110, "stop_loss": 105, "take_profit": 125}))
    result = _result("2330.TW", prices=None)
    points = result.dashboard["battle_plan"]["sniper_points"]
    points["ideal_buy"], points["take_profit"] = text_levels
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is True
    assert "sniper_prices" not in result.dashboard["battle_plan"]
    assert extract_sniper_points(result) == {
        "ideal_buy": 110, "secondary_buy": None, "stop_loss": 105, "take_profit": 125,
    }
    final = _finalize(pipeline, result, "2330.TW")
    assert (final.decision_type, final.action) == ("buy", "buy")
    assert final.dashboard["battle_plan"]["cost_check"]["status"] == "ok"


def test_legacy_text_contract_null_levels_in_reply_keep_original_text():
    # 反向：模型回 null 的格子不得蓋掉原文字價位（null 不是模型給的值）
    pipeline = _pipeline(_reply({"ideal_buy": None, "stop_loss": 95, "take_profit": None}))
    result = _result(prices=None, text_stop="跌破季線停損")
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is True
    assert result.dashboard["battle_plan"]["sniper_points"]["ideal_buy"] == "100"
    assert extract_sniper_points(result) == {
        "ideal_buy": 100, "secondary_buy": None, "stop_loss": 95, "take_profit": 120,
    }


@pytest.mark.parametrize("decision_type, action, score", [
    ("sell", "reduce", 72),   # 結構化賣出：買入區也不升買入
    ("hold", "hold", 55),     # 買入區外的持有
    ("hold", "reduce", 72),   # 買入區的減碼不會被對齊成買入
])
def test_non_long_decisions_are_not_repaired(decision_type, action, score):
    pipeline = _pipeline(_reply({"stop_loss": 90}))
    result = _result(prices={"ideal_buy": 100, "secondary_buy": None, "stop_loss": None, "take_profit": 120},
                     decision_type=decision_type, action=action, score=score, advice="持有")
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is False
    assert pipeline.analyzer.prompts == []


def test_buy_band_hold_is_repaired_because_it_will_be_lifted():
    pipeline = _pipeline(_reply({"stop_loss": 93}))
    result = _result(prices={"ideal_buy": 100, "secondary_buy": None, "stop_loss": None, "take_profit": 120},
                     decision_type="hold", action="hold", score=72, advice="持有")
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is True
    assert extract_sniper_points(result)["stop_loss"] == 93


@pytest.mark.parametrize("enabled, retry", [(False, 1), (True, 0)])
def test_repair_follows_integrity_retry_switches(enabled, retry):
    pipeline = _pipeline(_reply({"stop_loss": 90}), enabled=enabled, retry=retry)
    result = _result(prices={"ideal_buy": 100, "secondary_buy": None, "stop_loss": None, "take_profit": 120})
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is False
    assert pipeline.analyzer.prompts == []


def test_trend_fallback_buy_is_not_sent_to_model():
    # Agent 失敗、整份走趨勢退路：買入不是模型判的，不請模型替它補停損
    pipeline = _pipeline(_reply({"stop_loss": 90}))
    result = _result(prices=None, error_message="Agent 未能生成有效的决策仪表盘")
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is False
    assert pipeline.analyzer.prompts == []


def test_repair_call_failure_keeps_stop_missing():
    pipeline = _pipeline(None)
    pipeline.analyzer.generate_text = MagicMock(side_effect=RuntimeError("boom"))
    result = _result(prices={"ideal_buy": 100, "secondary_buy": None, "stop_loss": None, "take_profit": 120})
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is False
    assert extract_sniper_points(result)["stop_loss"] is None


def test_parse_repair_reply_only_reads_structured_values():
    assert parse_sniper_repair_reply('說明：停損 95\n{"sniper_prices": {"stop_loss": 95}}') == (
        {"stop_loss": 95}, None)
    # 只有說明文字、沒有 sniper_prices：不從文字猜價
    assert parse_sniper_repair_reply('{"sniper_points": {"stop_loss": "95"}}')[0] is None
    assert parse_sniper_repair_reply('{"sniper_prices": "N/A"}')[0] is None
    assert parse_sniper_repair_reply(None) == (None, None)


# ---------- 規則 2：台股買入缺任一格就無法檢查風報比，降為觀望 ----------


def _tw_buy(prices):
    return _result("2330.TW", prices=prices)


@pytest.mark.parametrize("missing, label", [
    ("stop_loss", "缺止损价"),
    ("take_profit", "缺目标价"),
    ("ideal_buy", "缺买点"),
])
def test_tw_buy_missing_any_level_is_softened_with_named_reason(missing, label):
    prices = {"ideal_buy": 100, "secondary_buy": None, "stop_loss": 95, "take_profit": 115, missing: None}
    result = _tw_buy(prices)
    assert apply_trade_cost_guardrail(result, code=result.code, report_language="zh") == [
        "trade_cost_levels_missing"]
    assert (result.decision_type, result.action) == ("hold", "watch")
    assert result.sentiment_score <= 59
    reason = result.dashboard["decision_score_calibration"]["guardrail_reason"]
    assert reason.startswith(label) and "无法检查风险收益比" in reason
    assert result.dashboard["battle_plan"]["cost_check"]["missing_levels"] == [missing]


def test_tw_reason_names_every_missing_level_and_never_blames_the_model():
    result = _tw_buy({"ideal_buy": 100, "secondary_buy": None, "stop_loss": None, "take_profit": None})
    apply_trade_cost_guardrail(result, code=result.code, report_language="zh-TW")
    reason = result.dashboard["decision_score_calibration"]["guardrail_reason"]
    assert reason.startswith("缺停損價／缺目標價，無法檢查報酬風險比")
    # 買入也可能來自程式趨勢退路，原因不能說是模型漏給
    assert "模型" not in reason


def test_tw_buy_with_all_three_levels_is_evaluated_normally():
    passing = _tw_buy({"ideal_buy": 100, "secondary_buy": None, "stop_loss": 95, "take_profit": 115})
    assert apply_trade_cost_guardrail(passing, code=passing.code, report_language="zh") == []
    assert (passing.decision_type, passing.action) == ("buy", "buy")
    assert passing.dashboard["battle_plan"]["cost_check"]["status"] == "ok"
    assert "missing_levels" not in passing.dashboard["battle_plan"]["cost_check"]

    thin = _tw_buy({"ideal_buy": 100, "secondary_buy": None, "stop_loss": 98, "take_profit": 101})
    assert apply_trade_cost_guardrail(thin, code=thin.code, report_language="zh") == ["trade_cost_buy_softened"]


@pytest.mark.parametrize("decision_type, action, score", [
    ("hold", "hold", 55), ("hold", "watch", 55), ("sell", "sell", 30), ("hold", "reduce", 72),
])
def test_tw_non_buy_missing_levels_is_untouched(decision_type, action, score):
    result = _result("2330.TW", prices=dict.fromkeys(SNIPER_KEYS), decision_type=decision_type,
                     action=action, score=score, advice="持有")
    assert apply_trade_cost_guardrail(result, code=result.code, report_language="zh") == []
    assert (result.decision_type, result.action, result.sentiment_score) == (decision_type, action, score)


def test_non_tw_buy_missing_levels_keeps_guardrail_scope():
    result = _result("AAPL", prices=dict.fromkeys(SNIPER_KEYS))
    assert apply_trade_cost_guardrail(result, code="AAPL", report_language="zh") == []
    assert (result.decision_type, result.action) == ("buy", "buy")


# ---------- 端到端：補全 → 定稿護欄 ----------


@pytest.mark.parametrize("block", MALFORMED_BLOCKS + [{"ideal_buy": 100, "stop_loss": None, "take_profit": 120}],
                         ids=["list", "na", "empty", "null-stop"])
def test_tw_still_missing_after_repair_ends_as_watch(block):
    pipeline = _pipeline(_reply({"stop_loss": None}))
    result = _result("2330.TW", prices=block)
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is False
    assert len(pipeline.analyzer.prompts) == 1
    final = _finalize(pipeline, result, "2330.TW")
    assert final.action == "watch" and final.decision_type == "hold"
    assert "无法检查风险收益比" in final.dashboard["decision_score_calibration"]["guardrail_reason"]


def test_tw_model_stop_after_repair_is_evaluated_normally():
    pipeline = _pipeline(_reply({"stop_loss": 95}))
    result = _result("2330.TW", prices={"ideal_buy": 100, "secondary_buy": None, "stop_loss": None,
                                        "take_profit": 115})
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is True
    final = _finalize(pipeline, result, "2330.TW")
    assert final.action == "buy"
    assert final.dashboard["battle_plan"]["cost_check"]["status"] == "ok"
    assert final.dashboard["battle_plan"]["cost_check"]["passed"] is True


def test_non_tw_still_missing_after_repair_stays_buy_but_repair_was_attempted():
    pipeline = _pipeline(_reply({"stop_loss": None}))
    result = _result("AAPL", prices="N/A")
    assert pipeline._repair_agent_stop_loss(result, TREND, "zh") is False
    assert len(pipeline.analyzer.prompts) == 1
    final = _finalize(pipeline, result, "AAPL")
    assert final.action == "buy"


def test_tw_buy_band_hold_without_stop_is_lifted_then_downgraded():
    pipeline = _pipeline(_reply({"stop_loss": None}))
    result = _result("2330.TW", prices={"ideal_buy": 100, "secondary_buy": None, "stop_loss": None,
                                        "take_profit": 115}, decision_type="hold", action="hold",
                     score=72, advice="持有")
    pipeline._repair_agent_stop_loss(result, TREND, "zh")
    assert len(pipeline.analyzer.prompts) == 1
    final = _finalize(pipeline, result, "2330.TW")
    assert final.action == "watch"
    assert final.dashboard["decision_score_calibration"]["guardrail_reason"].startswith("缺止损价")


# ---------- 分析器（單模型）路徑：完整性重試附上支撐／ATR 證據 ----------


def _analyzer():
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._router = None
    analyzer._llm = None
    analyzer._litellm_available = True
    analyzer._skill_instructions_override = ""
    analyzer._default_skill_policy_override = ""
    analyzer._use_legacy_default_prompt_override = True
    analyzer._config_override = SimpleNamespace(
        generation_backend="litellm", generation_fallback_backend="litellm",
        litellm_model="openai/test", litellm_fallback_models=[], llm_model_list=[],
        report_language="zh", gemini_request_delay=0, llm_temperature=0.7,
        report_integrity_enabled=True, report_integrity_retry=1,
        news_max_age_days=3, news_strategy_profile="short",
    )
    return analyzer


def _dashboard_json(stop):
    return json.dumps({
        "stock_name": "Apple", "sentiment_score": 72, "trend_prediction": "看多",
        "operation_advice": "买入", "decision_type": "buy", "action": "buy",
        "confidence_level": "中", "analysis_summary": "摘要",
        "dashboard": {
            "core_conclusion": {"one_sentence": "一句话"},
            "intelligence": {"risk_alerts": []},
            "battle_plan": {
                "sniper_points": {"ideal_buy": "100", "secondary_buy": "", "stop_loss": "", "take_profit": "120"},
                "sniper_prices": {"ideal_buy": 100, "secondary_buy": None, "stop_loss": stop, "take_profit": 120},
            },
        },
    }, ensure_ascii=False)


def _analyze(responses):
    from tests.test_analyzer_prompt_language import _rich_context

    analyzer = _analyzer()
    context = _rich_context()
    context["trend_analysis"] = {**context["trend_analysis"], "support_levels": [96.0], "atr14_pct": 2.4}
    prompts = []
    queue = list(responses)

    def _fake(prompt, generation_config, **kwargs):
        prompts.append(prompt)
        return queue.pop(0), "openai/test", {}

    with patch.object(analyzer, "_call_litellm", side_effect=_fake):
        result = analyzer.analyze(context, news_context="headline")
    return result, prompts


def test_analyzer_retry_prompt_carries_support_fact_and_keeps_model_stop():
    result, prompts = _analyze([_dashboard_json(None), _dashboard_json(97)])
    assert len(prompts) == 2
    assert "支撑位：96" not in prompts[0]
    assert "支撑位：96" in prompts[1] and "ATR14：2.4%" in prompts[1]
    assert extract_sniper_points(result)["stop_loss"] == 97


def test_analyzer_retry_still_null_stays_null():
    result, prompts = _analyze([_dashboard_json(None), _dashboard_json(None)])
    assert len(prompts) == 2
    assert extract_sniper_points(result)["stop_loss"] is None


def test_analyzer_complete_report_needs_no_evidence_retry():
    result, prompts = _analyze([_dashboard_json(95)])
    assert len(prompts) == 1
    assert extract_sniper_points(result)["stop_loss"] == 95


def test_evidence_is_empty_without_support_or_atr():
    assert format_stop_loss_evidence(None) == ""
    assert format_stop_loss_evidence(SimpleNamespace(support_levels=[], atr14_pct=None)) == ""
    assert "Support levels: 96" in format_stop_loss_evidence({"support_levels": [96]}, "en")


# ---------- 真實 Agent 入口：單 agent 與多 agent 都在落庫前補問（移植自 A 實作） ----------


@pytest.mark.parametrize("multi_agent", [False, True], ids=["single", "multi"])
@pytest.mark.parametrize("code, expected", [("00631L.TW", "watch"), ("AAPL", "buy")])
def test_real_agent_path_repairs_before_persist_for_both_executor_modes(multi_agent, code, expected):
    from copy import deepcopy

    from src.agent.executor import AgentResult
    from src.enums import ReportType

    pipeline = _pipeline(_reply({"stop_loss": None}))
    pipeline.config.agent_arch = "multi" if multi_agent else "single"
    pipeline.search_service = None
    pipeline.social_sentiment_service = None
    pipeline.save_context_snapshot = False
    pipeline.query_source = "test"
    pipeline.analysis_skills = None
    pipeline._extract_decision_signal_after_history_save = MagicMock()
    pipeline._ensure_agent_history = MagicMock()
    pipeline._load_agent_analysis_context = MagicMock(return_value={})
    pipeline._load_persisted_intelligence_context = MagicMock(return_value=None)
    pipeline._build_analysis_context_pack_outputs = MagicMock(return_value=(None, None))
    saved = []
    pipeline.db = MagicMock()
    pipeline.db.save_analysis_history.side_effect = lambda **kw: saved.append(deepcopy(kw["result"])) or 1
    # 買入區分數的持有＋損壞區塊：定稿會被對齊成買入，必須先補問
    payload = _result(code, prices=[], decision_type="hold", action="watch", score=72, advice="持有").to_dict()
    executor = MagicMock()
    executor.run.return_value = AgentResult(success=True, content="{}", dashboard=payload, provider="fake")
    prompt_state = SimpleNamespace(
        skill_manager=MagicMock(), skills_to_activate=[], explicit_skill_selection=False,
        use_legacy_default_prompt=True, technical_skill_policy="", skill_instructions="", default_skill_policy="",
    )
    with patch("src.agent.factory.get_tool_registry"), \
            patch("src.agent.factory.resolve_skill_prompt_state", return_value=prompt_state), \
            patch("src.agent.llm_adapter.LLMToolAdapter"), \
            patch("src.agent.factory._build_orchestrator", return_value=executor) as orchestrator, \
            patch("src.agent.executor.AgentExecutor", return_value=executor) as single:
        result = pipeline._analyze_with_agent(code, ReportType.SIMPLE, "repair-test", "測試", None, None)
    assert orchestrator.call_count == int(multi_agent)
    assert single.call_count == int(not multi_agent)
    assert result is not None
    assert len(pipeline.analyzer.prompts) == 1
    assert saved and saved[0].action == result.action == expected


@pytest.mark.parametrize("supports", [[96.0], []])
def test_enhanced_context_carries_real_support_only_as_evidence(supports):
    from src.stock_analyzer import TrendAnalysisResult

    pipeline = _pipeline("{}")
    pipeline.search_service = None
    trend = TrendAnalysisResult(code="2330.TW", support_levels=supports, atr14_pct=3.5)
    context = pipeline._enhance_context({"code": trend.code}, None, None, trend, fundamental_context={})
    assert context["trend_analysis"]["support_levels"] == supports
    assert "sniper_prices" not in context
