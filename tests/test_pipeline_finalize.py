# -*- coding: utf-8 -*-
"""Tests for the shared finalize-and-persist stage (Commit 1 of deepen-core).

Covers `StockAnalysisPipeline._finalize_and_persist_result`, the method that
consolidates the legacy and agent analysis paths' previously-duplicated
guardrail + history-save tail.
"""

import os
import sys
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline
from src.report_language import localize_operation_advice
from src.schemas.decision_action import display_action_fields_for_result
from src.services.analysis_context_builder import PipelineAnalysisArtifacts
from scripts.shadow_buy_eval import raw_decision


def _make_pipeline(*, save_context_snapshot: bool = True) -> StockAnalysisPipeline:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(report_language="zh")
    pipeline.save_context_snapshot = save_context_snapshot
    pipeline.query_source = "system"
    pipeline.analysis_skills = None
    pipeline.db = MagicMock()
    pipeline.db.save_analysis_history.return_value = 1
    return pipeline


def _artifacts(**overrides) -> PipelineAnalysisArtifacts:
    defaults = dict(
        code="600519",
        stock_name="贵州茅台",
        market="cn",
        phase=None,
        base_context={},
        enhanced_context={},
        realtime_quote=None,
        trend_result=None,
        chip_data=None,
        fundamental_context=None,
        news_context=None,
        news_result_count=None,
        metadata={"query_id": "q-finalize"},
        portfolio_context=None,
    )
    defaults.update(overrides)
    return PipelineAnalysisArtifacts(**defaults)


def _result(**overrides) -> AnalysisResult:
    defaults = dict(
        code="600519",
        name="贵州茅台",
        sentiment_score=80,
        trend_prediction="强烈看多",
        operation_advice="建议买入",
        decision_type="buy",
        confidence_level="高",
    )
    defaults.update(overrides)
    return AnalysisResult(**defaults)


def _finalize_public_action(result, *, artifacts=None, snapshot_context=None):
    pipeline = _make_pipeline()
    saved_results = []
    signals = []

    def save_history(**kwargs):
        saved_results.append(deepcopy(kwargs["result"]))
        return 1

    pipeline.db.save_analysis_history.side_effect = save_history
    with patch("src.services.decision_signal_extractor.DecisionSignalService") as service:
        service.return_value.create_signal.side_effect = lambda payload: signals.append(deepcopy(payload))
        returned = pipeline._finalize_and_persist_result(
            result,
            artifacts or _artifacts(),
            market_phase_summary=None,
            analysis_context_pack_overview=None,
            report_type="simple",
            snapshot_context=snapshot_context or {},
            news_content_for_save=None,
        )
        service.return_value.create_signal.assert_called_once()
    pipeline.db.save_analysis_history.assert_called_once()
    assert returned is result
    return saved_results[0], signals[0]


@pytest.mark.parametrize("initial_action", [None, "buy", "add"])
@pytest.mark.parametrize(
    "decision_type, advice, expected_action, high_risk",
    [
        ("sell", "觀望", "watch", False),
        ("sell", "觀望", "watch", True),
        ("sell", "观望", "watch", False),
        ("sell", "持有", "hold", False),
        ("sell", "买入", "watch", False),
        ("sell", "", "watch", False),
        ("buy", "减仓", "reduce", False),
        ("hold", "卖出", "sell", False),
        ("hold", "回避", "avoid", False),
        ("hold", "觀望", "watch", False),
    ],
)
def test_finalize_contradictory_non_buy_never_publishes_buy(
    decision_type, advice, expected_action, initial_action, high_risk,
):
    result = _result(
        decision_type=decision_type, operation_advice=advice,
        sentiment_score=68, action=initial_action,
    )
    snapshot = {"daily_market_context": {"risk_tags": ["high_risk"]}} if high_risk else {}

    saved, signal = _finalize_public_action(result, snapshot_context=snapshot)

    assert result.action == saved.action == signal["action"] == expected_action
    assert display_action_fields_for_result(result)["action"] == expected_action
    assert result.sentiment_score == saved.sentiment_score == 68
    calibration = saved.dashboard["decision_score_calibration"]
    expected_reason = "决策或操作建议与买入分数矛盾，保留非买入动作，禁止升为买入或加仓。"
    assert calibration["guardrail_reason"] == expected_reason
    assert signal["metadata"]["guardrail_reason"] == expected_reason
    assert raw_decision(saved.to_dict())["downgraded"] is False
    assert "raw_score" not in calibration
    assert "adjusted_score" not in calibration
    assert "raw_decision_type" not in calibration
    assert calibration["final_action"] == expected_action


def test_finalize_normal_buy_band_buy_still_publishes_buy():
    result = _result(sentiment_score=68)

    saved, signal = _finalize_public_action(result)

    assert result.action == saved.action == signal["action"] == "buy"
    assert result.sentiment_score == 68
    assert not signal["metadata"].get("guardrail_reason")
    assert "decision_score_calibration" not in (saved.dashboard or {})


@pytest.mark.parametrize("guardrail", ["market_context", "trade_cost"])
@pytest.mark.parametrize("decision_type", ["buy", "hold"])
@pytest.mark.parametrize("advice", ["觀望", "持有觀望"])
def test_finalize_real_guardrail_reason_takes_precedence_over_contradiction(guardrail, decision_type, advice):
    result = _result(
        code="2330.TW", name="台積電", decision_type=decision_type,
        operation_advice=advice, sentiment_score=68, report_language="en",
        dashboard={"battle_plan": {"sniper_points": {
            "ideal_buy": "100", "stop_loss": "97.86", "take_profit": "103.69",
        }}},
    )
    snapshot = {"daily_market_context": {"risk_tags": ["high_risk"]}} if guardrail == "market_context" else {}

    saved, signal = _finalize_public_action(
        result, artifacts=_artifacts(code="2330.TW", market="tw"), snapshot_context=snapshot,
    )

    assert result.action == saved.action == signal["action"] == "watch"
    calibration = saved.dashboard["decision_score_calibration"]
    if guardrail == "market_context":
        assert saved.sentiment_score == 52
        expected_reason = "Daily market context is conservative/high risk; aggressive buy advice was softened."
    else:
        assert saved.sentiment_score == 59
        assert saved.dashboard["battle_plan"]["cost_check"]["passed"] is False
        expected_reason = saved.risk_warning
        assert "round-trip cost" in expected_reason
    assert calibration["guardrail_reason"] == expected_reason
    assert signal["metadata"]["guardrail_reason"] == expected_reason
    assert raw_decision(saved.to_dict())["downgraded"] is True
    assert calibration["raw_score"] == 68
    assert calibration["adjusted_score"] == saved.sentiment_score


def test_finalize_consistent_low_score_sell_is_untouched():
    # 反向：分數不在買入區的一致賣出照舊發布賣出，也不留矛盾原因
    result = _result(decision_type="sell", operation_advice="卖出", sentiment_score=15, dashboard={})

    saved, signal = _finalize_public_action(result)

    assert result.action == saved.action == signal["action"] == "sell"
    assert result.sentiment_score == 15
    assert "decision_score_calibration" not in (saved.dashboard or {})


@pytest.mark.parametrize("initial_action", [None, "buy", "add"])
@pytest.mark.parametrize("change_pct", [-1.6, 1.0], ids=["shakeout", "no_shakeout"])
def test_finalize_buy_band_hold_resets_action_only_for_shakeout(initial_action, change_pct):
    result = _result(
        decision_type="hold", operation_advice="洗盘观察", sentiment_score=68,
        current_price=30.5, change_pct=change_pct, action=initial_action,
    )
    artifacts = _artifacts(
        trend_result=SimpleNamespace(support_levels=[30.0], resistance_levels=[34.0]),
        fundamental_context={"capital_flow": {"status": "ok", "data": {
            "stock_flow": {"main_net_inflow": 1_000_000},
        }}},
    )

    saved, signal = _finalize_public_action(result, artifacts=artifacts)

    expected = "hold" if change_pct < 0 else initial_action or "buy"
    assert result.action == saved.action == signal["action"] == expected
    assert display_action_fields_for_result(result)["action"] == expected
    assert result.operation_advice == "洗盘观察"
    assert result.sentiment_score == saved.sentiment_score == 68
    assert bool(signal["metadata"].get("guardrail_reason")) == (change_pct < 0)


class FinalizeAndPersistResultTestCase(unittest.TestCase):
    def test_guardrail_sequence_softens_aggressive_buy_under_conservative_context(self):
        """(a) The guardrail sequence (phase + daily-market-context) actually runs."""
        pipeline = _make_pipeline()
        result = _result()
        artifacts = _artifacts()
        snapshot_context = {"daily_market_context": {"risk_tags": ["high_risk"]}}

        returned = pipeline._finalize_and_persist_result(
            result,
            artifacts,
            market_phase_summary=None,
            analysis_context_pack_overview=None,
            report_type="simple",
            snapshot_context=snapshot_context,
            news_content_for_save=None,
        )

        self.assertIs(returned, result)
        self.assertEqual(result.decision_type, "hold")
        self.assertEqual(result.operation_advice, localize_operation_advice("观望", "zh"))

    def _finalize_tw_buy(self, levels, trend_result=None):
        pipeline = _make_pipeline()
        result = _result(code="2330.TW", name="台積電", dashboard={
            "battle_plan": {"sniper_points": {k: str(v) for k, v in levels.items()}}})
        pipeline._finalize_and_persist_result(
            result,
            _artifacts(code="2330.TW", stock_name="台積電", market="tw", trend_result=trend_result),
            market_phase_summary=None,
            analysis_context_pack_overview=None,
            report_type="simple",
            snapshot_context={},
            news_content_for_save=None,
        )
        return result

    def test_trade_cost_guardrail_runs_in_the_finalize_sequence(self):
        """台股買入的價位扣掉來回成本後賠比賺多（回測中位間距 +3.69%／-2.14%）→ 降為觀望。"""
        result = self._finalize_tw_buy({"ideal_buy": 100, "stop_loss": 97.86, "take_profit": 103.69})
        self.assertFalse(result.dashboard["battle_plan"]["cost_check"]["passed"])
        self.assertEqual(result.decision_type, "hold")
        self.assertIn("净风报比", result.risk_warning)

    def test_trade_cost_guardrail_receives_the_trend_atr(self):
        result = self._finalize_tw_buy({"ideal_buy": 100, "stop_loss": 96, "take_profit": 110},
                                       trend_result=SimpleNamespace(atr14_pct=5.54))
        check = result.dashboard["battle_plan"]["cost_check"]
        self.assertEqual(check["atr14_pct"], 5.54)
        self.assertTrue(check["stop_within_atr"])

    def test_trade_cost_guardrail_leaves_a_worthwhile_buy_alone(self):
        result = self._finalize_tw_buy({"ideal_buy": 100, "stop_loss": 96, "take_profit": 110})
        self.assertTrue(result.dashboard["battle_plan"]["cost_check"]["passed"])
        self.assertEqual(result.decision_type, "buy")

    def _finalize_with_config(self, config, dashboard=None):
        pipeline = _make_pipeline()
        pipeline.config = config
        result = _result(dashboard=dashboard if dashboard is not None else {})
        pipeline._finalize_and_persist_result(
            result,
            _artifacts(),
            market_phase_summary=None,
            analysis_context_pack_overview=None,
            report_type="simple",
            snapshot_context={},
            news_content_for_save=None,
        )
        return result

    def test_prompt_variant_is_stamped_on_persisted_dashboard(self):
        """提示詞版本標籤隨報告落庫，影子評估 --by-variant 才分得出 A/B。"""
        result = self._finalize_with_config(SimpleNamespace(report_language="zh", prompt_variant="v2"))
        self.assertEqual(result.dashboard["prompt_variant"], "v2")
        result = self._finalize_with_config(SimpleNamespace(report_language="zh"))
        self.assertEqual(result.dashboard["prompt_variant"], "baseline")
        # 上游已標記的版本不得被設定覆蓋
        result = self._finalize_with_config(SimpleNamespace(report_language="zh", prompt_variant="v2"),
                                            dashboard={"prompt_variant": "agent-v1"})
        self.assertEqual(result.dashboard["prompt_variant"], "agent-v1")

    def test_save_analysis_history_receives_none_news_content_for_save(self):
        """(b) news_content_for_save=None reaches save_analysis_history unchanged."""
        pipeline = _make_pipeline()
        result = _result(decision_type="hold", operation_advice="持有")
        artifacts = _artifacts(news_context="prefetched news body")

        pipeline._finalize_and_persist_result(
            result,
            artifacts,
            market_phase_summary=None,
            analysis_context_pack_overview=None,
            report_type="simple",
            snapshot_context={},
            news_content_for_save=None,
        )

        call_kwargs = pipeline.db.save_analysis_history.call_args.kwargs
        self.assertIsNone(call_kwargs["news_content"])
        # The snapshot's own news_content still carries the artifacts value.
        self.assertEqual(
            call_kwargs["context_snapshot"]["news_content"], "prefetched news body"
        )

    def test_save_analysis_history_receives_text_news_content_for_save(self):
        """(b) news_content_for_save=<text> reaches save_analysis_history unchanged."""
        pipeline = _make_pipeline()
        result = _result(decision_type="hold", operation_advice="持有")
        artifacts = _artifacts(news_context="prefetched news body")

        pipeline._finalize_and_persist_result(
            result,
            artifacts,
            market_phase_summary=None,
            analysis_context_pack_overview=None,
            report_type="simple",
            snapshot_context={},
            news_content_for_save="legacy news for save",
        )

        call_kwargs = pipeline.db.save_analysis_history.call_args.kwargs
        self.assertEqual(call_kwargs["news_content"], "legacy news for save")

    def test_attach_agent_diagnostics_patches_snapshot_after_save(self):
        """(c) attach_agent_diagnostics=True patches diagnostics + stock_name post-save."""
        pipeline = _make_pipeline()
        result = _result(decision_type="hold", operation_advice="持有")
        artifacts = _artifacts()
        snapshot_context = {"stock_name": "贵州茅台(resolved)"}

        with patch(
            "src.core.pipeline.current_diagnostic_snapshot",
            side_effect=[{"trace_id": "pre-save"}, {"trace_id": "post-save"}],
        ):
            pipeline._finalize_and_persist_result(
                result,
                artifacts,
                market_phase_summary=None,
                analysis_context_pack_overview=None,
                report_type="simple",
                snapshot_context=snapshot_context,
                news_content_for_save=None,
                attach_agent_diagnostics=True,
            )

        call_kwargs = pipeline.db.save_analysis_history.call_args.kwargs
        saved_snapshot = call_kwargs["context_snapshot"]
        # Same dict object result.diagnostic_context_snapshot points at, so the
        # post-save patch (captured after save_analysis_history/extract) is visible here.
        self.assertIs(result.diagnostic_context_snapshot, saved_snapshot)
        self.assertEqual(saved_snapshot["diagnostics"]["trace_id"], "post-save")
        self.assertEqual(saved_snapshot["stock_name"], "贵州茅台(resolved)")

    def test_attach_agent_diagnostics_false_does_not_set_stock_name(self):
        """Legacy path (attach_agent_diagnostics=False) never gets a top-level stock_name key."""
        pipeline = _make_pipeline()
        result = _result(decision_type="hold", operation_advice="持有")
        artifacts = _artifacts()
        snapshot_context = {"stock_name": "should-not-propagate"}

        pipeline._finalize_and_persist_result(
            result,
            artifacts,
            market_phase_summary=None,
            analysis_context_pack_overview=None,
            report_type="simple",
            snapshot_context=snapshot_context,
            news_content_for_save=None,
            attach_agent_diagnostics=False,
        )

        call_kwargs = pipeline.db.save_analysis_history.call_args.kwargs
        self.assertNotIn("stock_name", call_kwargs["context_snapshot"])

    def test_result_none_returns_none_safely(self):
        """(d) result=None returns None without touching the db."""
        pipeline = _make_pipeline()
        artifacts = _artifacts()

        returned = pipeline._finalize_and_persist_result(
            None,
            artifacts,
            market_phase_summary=None,
            analysis_context_pack_overview=None,
            report_type="simple",
            snapshot_context={},
            news_content_for_save=None,
        )

        self.assertIsNone(returned)
        pipeline.db.save_analysis_history.assert_not_called()

    def test_unsuccessful_result_skips_persistence(self):
        """result.success=False runs guardrails but never calls save_analysis_history."""
        pipeline = _make_pipeline()
        result = _result(decision_type="hold", operation_advice="持有", success=False)
        artifacts = _artifacts()

        returned = pipeline._finalize_and_persist_result(
            result,
            artifacts,
            market_phase_summary=None,
            analysis_context_pack_overview=None,
            report_type="simple",
            snapshot_context={},
            news_content_for_save=None,
        )

        self.assertIs(returned, result)
        pipeline.db.save_analysis_history.assert_not_called()


if __name__ == "__main__":
    unittest.main()
