# -*- coding: utf-8 -*-
"""Tests for the shared finalize-and-persist stage (Commit 1 of deepen-core).

Covers `StockAnalysisPipeline._finalize_and_persist_result`, the method that
consolidates the legacy and agent analysis paths' previously-duplicated
guardrail + history-save tail.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline
from src.report_language import localize_operation_advice
from src.services.analysis_context_builder import PipelineAnalysisArtifacts


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
