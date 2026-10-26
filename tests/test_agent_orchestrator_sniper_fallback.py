# -*- coding: utf-8 -*-
"""Regression tests for AgentOrchestrator sniper point fallbacks."""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.agent.orchestrator import AgentOrchestrator
from src.agent.protocols import AgentContext


class TestAgentOrchestratorSniperFallback(unittest.TestCase):
    def test_secondary_buy_does_not_duplicate_ideal_buy(self):
        orch = AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
        )
        ctx = AgentContext(query="test", stock_code="301308", stock_name="江波龙")

        payload = {
            "decision_type": "buy",
            "analysis_summary": "趋势仍强，等待回踩。",
            "dashboard": {
                "key_levels": {
                    "support": 301.61,
                    "stop_loss": 295.0,
                    "resistance": 340.44,
                }
            },
        }

        normalized = orch._finalize_dashboard_payload(payload, ctx)

        self.assertIsNotNone(normalized)
        sniper = normalized["dashboard"]["battle_plan"]["sniper_points"]
        self.assertEqual(sniper["ideal_buy"], 301.61)
        self.assertEqual(sniper["secondary_buy"], "N/A")

    def test_secondary_buy_numeric_string_does_not_duplicate_ideal_buy(self):
        orch = AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
        )
        ctx = AgentContext(query="test", stock_code="301308", stock_name="江波龙")

        payload = {
            "decision_type": "buy",
            "analysis_summary": "趋势仍强，等待回踩。",
            "dashboard": {
                "battle_plan": {
                    "sniper_points": {
                        "secondary_buy": "301.61",
                    }
                },
                "key_levels": {
                    "support": 301.61,
                    "stop_loss": 295.0,
                    "resistance": 340.44,
                },
            },
        }

        normalized = orch._finalize_dashboard_payload(payload, ctx)

        self.assertIsNotNone(normalized)
        sniper = normalized["dashboard"]["battle_plan"]["sniper_points"]
        self.assertEqual(sniper["ideal_buy"], 301.61)
        self.assertEqual(sniper["secondary_buy"], "N/A")

    def test_structured_sniper_prices_survive_finalize_and_win_over_key_level_text(self):
        from src.utils.sniper_points import resolve_sniper_prices

        orch = AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
        )
        ctx = AgentContext(query="test", stock_code="301308", stock_name="江波龙")
        prices = {"ideal_buy": None, "secondary_buy": None, "stop_loss": 290.0, "take_profit": 330.0}
        payload = {
            "decision_type": "buy",
            "analysis_summary": "趋势仍强，等待回踩。",
            "dashboard": {
                "battle_plan": {"sniper_points": {}, "sniper_prices": dict(prices)},
                "key_levels": {"support": 301.61, "stop_loss": 295.0, "resistance": 340.44},
            },
        }

        normalized = orch._finalize_dashboard_payload(payload, ctx)

        battle = normalized["dashboard"]["battle_plan"]
        self.assertEqual(battle["sniper_prices"], prices)
        # 模型有給結構化價位時，不再用 key_levels 補文字，避免顯示與模型判斷矛盾的價位
        self.assertEqual(battle["sniper_points"], {})
        self.assertEqual(resolve_sniper_prices(battle), prices)


if __name__ == "__main__":
    unittest.main()
