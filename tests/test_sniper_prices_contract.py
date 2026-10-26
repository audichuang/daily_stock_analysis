# -*- coding: utf-8 -*-
"""結構化狙擊點位 ``battle_plan.sniper_prices`` 的 prompt 與 schema 契約。

價位由模型判斷並以數字／null 給出，程式碼不從文字推斷；這裡守住每條 prompt 路徑都有要求這個欄位。
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.agent.agents.decision_agent import DecisionAgent  # noqa: E402
from src.agent.executor import AGENT_SYSTEM_PROMPT, LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT  # noqa: E402
from src.agent.protocols import AgentContext  # noqa: E402
from src.analyzer import GeminiAnalyzer  # noqa: E402
from src.schemas.report_schema import AnalysisReportSchema, BattlePlan  # noqa: E402


def _json_template_block(template: str) -> str:
    start = template.index('"sniper_prices": {')
    return template[start:template.index("}", start) + 1]


class TestSniperPricesPrompts(unittest.TestCase):
    def test_every_analyzer_system_template_asks_for_numeric_sniper_prices(self):
        templates = {
            "legacy_zh": GeminiAnalyzer.LEGACY_DEFAULT_SYSTEM_PROMPT,
            "skill_zh": GeminiAnalyzer.SYSTEM_PROMPT,
            "legacy_en": GeminiAnalyzer.LEGACY_DEFAULT_SYSTEM_PROMPT_EN,
            "skill_en": GeminiAnalyzer.SYSTEM_PROMPT_EN,
        }
        for name, template in templates.items():
            with self.subTest(template=name):
                block = _json_template_block(template)
                for key in ("ideal_buy", "secondary_buy", "stop_loss", "take_profit"):
                    self.assertIn(f'"{key}"', block)
                self.assertIn("null", block)
                self.assertIn("`dashboard.battle_plan.sniper_prices`", template)

    def test_principles_say_system_reads_only_numbers(self):
        self.assertIn("系统只读取 `sniper_prices` 的数字", GeminiAnalyzer.SYSTEM_PROMPT)
        self.assertIn("系统只读取 `sniper_prices` 的数字", GeminiAnalyzer.LEGACY_DEFAULT_SYSTEM_PROMPT)
        self.assertIn("the system reads only the numbers in `sniper_prices`", GeminiAnalyzer.SYSTEM_PROMPT_EN)
        self.assertIn("the system reads only the numbers in `sniper_prices`", GeminiAnalyzer.LEGACY_DEFAULT_SYSTEM_PROMPT_EN)

    def test_agent_executor_templates_include_sniper_prices(self):
        for name, template in (("legacy", LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT), ("skill", AGENT_SYSTEM_PROMPT)):
            with self.subTest(template=name):
                self.assertIn('"sniper_prices": {{"ideal_buy": 数字或null', template)
                self.assertIn("系统只读取 `sniper_prices` 的数字", template)

    def test_decision_agent_prompt_requires_sniper_prices(self):
        agent = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
        prompt = agent.system_prompt(AgentContext(query="test", stock_code="2330.TW"))
        self.assertIn("``sniper_prices``", prompt)
        self.assertIn("never infers them from the text", prompt)

    def test_integrity_complement_prompt_asks_for_structured_stop_loss(self):
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        field = ["dashboard.battle_plan.sniper_points.stop_loss"]
        for language in ("zh", "zh-TW", "en"):
            with self.subTest(language=language):
                text = analyzer._build_integrity_complement_prompt(field, language)
                self.assertIn("dashboard.battle_plan.sniper_prices.stop_loss", text)


class TestSniperPricesSchema(unittest.TestCase):
    def test_schema_accepts_numbers_and_nulls(self):
        plan = BattlePlan.model_validate({
            "sniper_points": {"stop_loss": "暫無，改以110元停損"},
            "sniper_prices": {"ideal_buy": None, "stop_loss": 110, "take_profit": "132.5"},
        })
        self.assertIsNone(plan.sniper_prices.ideal_buy)
        self.assertIsNone(plan.sniper_prices.secondary_buy)
        self.assertEqual(plan.sniper_prices.stop_loss, 110.0)
        self.assertEqual(plan.sniper_prices.take_profit, 132.5)

    def test_schema_defaults_when_field_absent(self):
        schema = AnalysisReportSchema.model_validate({
            "stock_name": "台積電",
            "dashboard": {"battle_plan": {"sniper_points": {"stop_loss": "110元"}}},
        })
        self.assertIsNone(schema.dashboard.battle_plan.sniper_prices)

    def test_schema_rejects_sentence_in_numeric_slot(self):
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            BattlePlan.model_validate({"sniper_prices": {"stop_loss": "跌破110元停損"}})


if __name__ == "__main__":
    unittest.main()
