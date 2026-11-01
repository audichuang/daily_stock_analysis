# -*- coding: utf-8 -*-
"""問股 API 追加欄位：會話個股、策略繁中名稱與分組、取消能力旗標、回答摘要。"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from api.v1.endpoints import agent as agent_endpoint  # noqa: E402
from src.agent.agent_backend import AgentRunResult  # noqa: E402
from src.agent.chat_executor import AgentChatExecutor, PreparedAgentChatTurn  # noqa: E402
from src.agent.executor import (  # noqa: E402
    STRUCTURED_ANSWER_CLOSE,
    STRUCTURED_ANSWER_OPEN,
    STRUCTURED_ANSWER_SECTION,
    AgentResult,
    PreparedAgentChat,
    prepare_agent_chat,
    split_structured_answer,
)
from src.agent.skills.base import SkillManager  # noqa: E402
from src.config import Config  # noqa: E402
from src.services.agent_chat_session_service import AgentChatSessionService  # noqa: E402
from src.storage import ConversationMessage, ConversationSessionState, DatabaseManager  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_api_database(tmp_path: Path):
    DatabaseManager.reset_instance()
    Config.reset_instance()
    DatabaseManager(db_url=f"sqlite:///{tmp_path / 'api.db'}")
    yield
    DatabaseManager.reset_instance()
    Config.reset_instance()


def _meta(payload) -> str:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"{STRUCTURED_ANSWER_OPEN}{text}{STRUCTURED_ANSWER_CLOSE}"


# ---- 回答摘要 ----


def test_split_extracts_validated_fields_and_cleans_body() -> None:
    content = "本文\n\n" + _meta({
        "conclusion": "偏多",
        "resistance": 1100,
        "support": 980.5,
        "invalidation": "跌破 980",
        "follow_ups": ["停損設哪", "法人動向"],
    })
    body, structured = split_structured_answer(content)
    assert body == "本文"
    assert structured == {
        "conclusion": "偏多",
        "resistance": 1100.0,
        "support": 980.5,
        "invalidation": "跌破 980",
        "follow_ups": ["停損設哪", "法人動向"],
    }


def test_split_without_marker_returns_content_unchanged() -> None:
    assert split_structured_answer("純文字回答") == ("純文字回答", None)


@pytest.mark.parametrize("meta", [
    STRUCTURED_ANSWER_OPEN + '{"conclusion": "被截斷',  # 沒有結尾標記
    _meta("not json"),
    _meta('["list"]'),
    _meta({"conclusion": "", "resistance": None, "support": None, "invalidation": None, "follow_ups": []}),
])
def test_split_always_removes_marker_from_body(meta: str) -> None:
    body, structured = split_structured_answer("本文\n" + meta)
    assert body == "本文"
    assert structured is None


@pytest.mark.parametrize("bad_price", ["1000元", -5, 0, True, float("inf")])
def test_split_rejects_invalid_prices_but_keeps_other_fields(bad_price) -> None:
    # json.dumps 會把 inf 寫成 Infinity，json.loads 也收，要在校驗這層擋
    _, structured = split_structured_answer("x" + _meta({"conclusion": "結論", "resistance": bad_price}))
    assert structured["resistance"] is None
    assert structured["conclusion"] == "結論"


def test_split_caps_follow_ups_and_text_length() -> None:
    _, structured = split_structured_answer("x" + _meta({
        "conclusion": "長" * 600,
        "follow_ups": ["a", "b", "c", "d", 5, ""],
    }))
    assert len(structured["conclusion"]) == 500
    assert structured["follow_ups"] == ["a", "b", "c"]


def test_section_template_uses_the_markers_it_parses() -> None:
    assert STRUCTURED_ANSWER_OPEN in STRUCTURED_ANSWER_SECTION
    assert STRUCTURED_ANSWER_CLOSE in STRUCTURED_ANSWER_SECTION


def test_prepare_does_not_request_summary_by_default() -> None:
    # AgentExecutor.chat 不切摘要段，預設一旦要求，標記就會原樣出現在回答裡
    default = inspect.signature(prepare_agent_chat).parameters["request_structured_answer"].default
    assert default is False


class _Backend:
    backend_id = "litellm"
    runtime_owns_loop = False

    def __init__(self, result: AgentRunResult) -> None:
        self.result = result

    def run(self, _request):
        return self.result


def _turn() -> PreparedAgentChatTurn:
    return PreparedAgentChatTurn(
        message="question",
        session_id="session",
        prepared=PreparedAgentChat(system_prompt="system", history_messages=[], stock_scope=None),
        baseline_len=2,
        run_id="run",
        user_message_id=1,
    )


def _execute(result: AgentRunResult):
    executor = AgentChatExecutor(backend=_Backend(result), config=SimpleNamespace(), context_llm_adapter=object())
    with patch("src.agent.chat_executor.conversation_manager.add_message", return_value=2) as add_message, \
         patch("src.agent.chat_executor.persist_provider_trace_turns"):
        return executor.execute_turn(_turn()), add_message


def test_execute_turn_persists_clean_body_and_returns_summary() -> None:
    result, add_message = _execute(AgentRunResult(
        success=True, backend="litellm", final_answer="本文\n" + _meta({"conclusion": "偏多"}),
    ))
    assert result.content == "本文"
    assert result.structured_answer["conclusion"] == "偏多"
    persisted = add_message.call_args.args[2]
    assert persisted == "本文"
    assert STRUCTURED_ANSWER_OPEN not in persisted


def test_execute_turn_failure_has_no_summary() -> None:
    result, _ = _execute(AgentRunResult(success=False, backend="litellm", error_message="boom"))
    assert result.structured_answer is None


def test_chat_executor_requests_summary_from_prompt() -> None:
    executor = AgentChatExecutor(backend=_Backend(AgentRunResult()), config=SimpleNamespace(), context_llm_adapter=object())
    prepared = PreparedAgentChat(system_prompt="system", history_messages=[], stock_scope=None)
    with patch("src.agent.chat_executor.prepare_agent_chat", return_value=prepared) as prepare, \
         patch("src.agent.chat_executor.conversation_manager.prepare_turn", return_value=(MagicMock(), {})), \
         patch("src.agent.chat_executor.conversation_manager.commit_user_turn", return_value={"user_message_id": 1}):
        executor.prepare_turn(message="q", session_id="s")
    assert prepare.call_args.kwargs["request_structured_answer"] is True


# ---- 取消能力與事件 ----


async def _immediate_to_thread(func, /, *args, **kwargs):
    return func(*args, **kwargs)


async def _collect(request) -> list[dict]:
    response = await agent_endpoint.agent_chat_stream(request, session_service=AgentChatSessionService())
    return [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in response.body_iterator]


def _stream(backend_id: str, result: AgentResult) -> list[dict]:
    turn = SimpleNamespace(accepted_snapshot={
        "active_stock_context": None,
        "session_state_version": 1,
        "session_generation": "generation",
        "selected_skill_ids": None,
        "session_id": "stream",
    })
    executor = MagicMock()
    executor.execute_turn.return_value = result
    prepared = (executor, turn, turn.accepted_snapshot, None)
    config = SimpleNamespace(report_language="zh")
    with patch("api.v1.endpoints.agent.get_config", return_value=config), \
         patch("api.v1.endpoints.agent._select_agent_chat_backend", return_value=backend_id), \
         patch("api.v1.endpoints.agent._prepare_chat_request", return_value=prepared), \
         patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread):
        return asyncio.run(_collect(agent_endpoint.ChatRequest(message="q", session_id="stream")))


@pytest.mark.parametrize("backend_id, expected", [("litellm", False), ("codex_app_server", True)])
def test_accepted_event_reports_cancel_capability(backend_id: str, expected: bool) -> None:
    events = _stream(backend_id, AgentResult(success=True, content="ok", backend=backend_id))
    assert events[0]["type"] == "accepted"
    assert events[0]["cancel_supported"] is expected


def test_done_event_carries_summary() -> None:
    structured = {"conclusion": "偏多", "resistance": 1100.0, "support": None, "invalidation": None, "follow_ups": []}
    events = _stream("litellm", AgentResult(success=True, content="本文", backend="litellm", structured_answer=structured))
    done = events[-1]
    assert done["type"] == "done"
    assert done["content"] == "本文"
    assert done["structured"] == structured


def test_done_event_summary_null_when_absent() -> None:
    events = _stream("litellm", AgentResult(success=True, content="本文", backend="litellm"))
    assert events[-1]["structured"] is None


# ---- 會話個股 ----


def test_sessions_expose_active_stock() -> None:
    db = DatabaseManager.get_instance()
    with db.session_scope() as session:
        session.add(ConversationMessage(session_id="with-stock", role="user", content="台積電如何"))
        session.add(ConversationMessage(session_id="no-state", role="user", content="大盤如何"))
        session.add(ConversationMessage(session_id="no-stock", role="user", content="今天如何"))
        session.add(ConversationSessionState(
            session_id="with-stock",
            selected_skill_ids_json="null",
            active_stock_code="2330.TW",
            active_stock_name="台積電",
        ))
        session.add(ConversationSessionState(session_id="no-stock", selected_skill_ids_json="null"))

    sessions = {item["session_id"]: item for item in db.get_chat_sessions()}
    assert sessions["with-stock"]["stock_code"] == "2330.TW"
    assert sessions["with-stock"]["stock_name"] == "台積電"
    for session_id in ("no-state", "no-stock"):
        assert sessions[session_id]["stock_code"] is None
        assert sessions[session_id]["stock_name"] is None
    assert agent_endpoint.SessionItem(**sessions["with-stock"]).stock_code == "2330.TW"


# ---- 策略 ----


def test_every_builtin_strategy_has_zh_tw_name_and_group() -> None:
    manager = SkillManager()
    assert manager.load_builtin_strategies() > 0
    allowed = {"trend", "pattern", "theory", "catalyst", "fundamental"}
    for skill in manager.list_skills():
        assert skill.display_name_zh_tw, skill.name
        assert skill.group in allowed, skill.name
        assert skill.group_name_zh_tw, skill.name


def test_skills_response_appends_fields_and_keeps_old_ones() -> None:
    manager = SkillManager()
    manager.load_builtin_strategies()
    with patch("src.agent.factory.get_skill_manager", return_value=manager):
        payload = agent_endpoint._build_skills_response(SimpleNamespace())
    bull = next(skill for skill in payload.skills if skill.id == "bull_trend")
    assert bull.name == "默认多头趋势"  # 舊欄位不動
    assert bull.display_name_zh_tw == "預設多頭趨勢"
    assert bull.group == "trend"
    assert bull.group_name_zh_tw == "趨勢"


def test_skill_without_zh_tw_fields_returns_null() -> None:
    skill = SimpleNamespace(name="custom", display_name="自訂", description="d", default_priority=1,
                            user_invocable=True)
    manager = MagicMock()
    manager.list_skills.return_value = [skill]
    with patch("src.agent.factory.get_skill_manager", return_value=manager), \
         patch("src.agent.skills.defaults.get_primary_default_skill_id", return_value=""):
        payload = agent_endpoint._build_skills_response(SimpleNamespace())
    assert payload.skills[0].display_name_zh_tw is None
    assert payload.skills[0].group is None
