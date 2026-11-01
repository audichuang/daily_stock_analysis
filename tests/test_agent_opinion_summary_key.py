# -*- coding: utf-8 -*-
"""專家 agent 的 JSON 改用 summary 鍵；舊的 reasoning 鍵仍要能讀，raw_data 只留一份。"""
import json
from unittest.mock import MagicMock

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

import pytest  # noqa: E402

from src.agent.agents.intel_agent import IntelAgent  # noqa: E402
from src.agent.agents.risk_agent import RiskAgent  # noqa: E402
from src.agent.agents.technical_agent import TechnicalAgent  # noqa: E402
from src.agent.protocols import AgentContext  # noqa: E402
from src.agent.skills.skill_agent import SkillAgent  # noqa: E402


def _agents():
    deps = {"tool_registry": MagicMock(), "llm_adapter": MagicMock()}
    return [IntelAgent(**deps), RiskAgent(**deps), TechnicalAgent(**deps), SkillAgent(skill_id="bull_trend", **deps)]


def _payload(**text):
    return json.dumps({"signal": "hold", "confidence": 0.5, "risk_level": "low", **text})


@pytest.mark.parametrize("index", range(4))
def test_prompt_asks_for_summary_not_reasoning(index):
    prompt = _agents()[index].system_prompt(AgentContext(stock_code="600519"))
    assert '"summary"' in prompt and '"reasoning"' not in prompt


@pytest.mark.parametrize("index", range(4))
def test_summary_becomes_reasoning_with_one_key_left(index):
    op = _agents()[index].post_process(AgentContext(stock_code="600519"), _payload(summary="s"))
    assert op.reasoning == "s"
    assert op.raw_data["reasoning"] == "s" and "summary" not in op.raw_data


@pytest.mark.parametrize("index", range(4))
def test_legacy_reasoning_key_still_reads(index):
    op = _agents()[index].post_process(AgentContext(stock_code="600519"), _payload(reasoning="r"))
    assert op.reasoning == "r"
