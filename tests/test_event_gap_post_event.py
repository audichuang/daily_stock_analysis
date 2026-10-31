"""事件後收盤不能被模型敘事蓋過。"""
from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace

from tests.litellm_stub import ensure_litellm_stub
ensure_litellm_stub()
from src.services.event_gap import event_gap_context, event_gap_prompt


def test_actual_shape_discloses_broken_event_low():
    today = date.today()
    context = {"date": today.isoformat(), "today": {"date": today.isoformat(), "close": 278.22},
               "event_gap_daily_bars": [
                   {"date": (today-timedelta(days=1)).isoformat(), "close": 280, "low": 278.29, "pct_chg": -13},
                   {"date": today.isoformat(), "close": 278.22, "low": 277, "pct_chg": -.64}]}
    config = SimpleNamespace(event_gap_decision_enabled=True, event_gap_threshold_pct=12, event_gap_lookback_sessions=5)
    event = event_gap_context("GOOG", context, config)
    assert event["post_event_min_close"] == 278.22
    assert event["latest_close"] == 278.22
    assert event["event_low_broken"] is True
    prompt = event_gap_prompt(event)
    assert "事件後最低收盤：278.22" in prompt
    assert "最新收盤：278.22" in prompt
    assert "已跌破事件日低點：是" in prompt
    assert "事件後新低重新計算" in prompt
    assert "不得假設事件日低點仍守住" in prompt
    context["event_gap_daily_bars"][-1]["close"] = 279
    context["today"]["close"] = 279
    event = event_gap_context("GOOG", context, config)
    assert event["event_low_broken"] is False
    assert "已跌破事件日低點：否" in event_gap_prompt(event)
    del context["event_gap_daily_bars"][0]["low"]
    event = event_gap_context("GOOG", context, config)
    assert "event_low_broken" not in event
    assert "已跌破事件日低點：" not in event_gap_prompt(event)


def test_prior_break_is_not_erased_by_latest_rebound_and_event_day_is_excluded():
    today = date.today()
    rows = [{"date": (today-timedelta(days=2)).isoformat(), "close": 280, "low": 278.29, "pct_chg": -13},
            {"date": (today-timedelta(days=1)).isoformat(), "close": 278.22, "pct_chg": 0},
            {"date": today.isoformat(), "close": 280, "pct_chg": 0}]
    config = SimpleNamespace(event_gap_decision_enabled=True, event_gap_threshold_pct=12, event_gap_lookback_sessions=5)
    context = {"date": today.isoformat(), "today": rows[-1], "event_gap_daily_bars": rows}
    event = event_gap_context("GOOG", context, config)
    assert event["post_event_min_close"] == 278.22
    assert event["latest_close"] == 280
    assert event["event_low_broken"] is True
    rows[0]["close"] = 278.5
    rows[1]["close"] = 279
    assert event_gap_context("GOOG", context, config)["post_event_min_close"] == 279
    rows[1]["close"] = 278.29
    event = event_gap_context("GOOG", context, config)
    assert event["event_low_broken"] is False
    rows[1].pop("close"); rows[2].pop("close")
    event = event_gap_context("GOOG", context, config)
    assert "post_event_min_close" not in event and "latest_close" not in event and "event_low_broken" not in event


def test_same_day_and_invalid_closes_do_not_invent_post_event_observations():
    config = SimpleNamespace(event_gap_decision_enabled=True, event_gap_threshold_pct=12, event_gap_lookback_sessions=5)
    context = {"date": date.today().isoformat(), "today": {"date": date.today().isoformat(), "pct_chg": -13, "low": 278.29, "close": float("nan")}}
    event = event_gap_context("GOOG", context, config)
    assert "post_event_min_close" not in event and "latest_close" not in event and "event_low_broken" not in event
    prompt = event_gap_prompt(event)
    assert "事件後最低收盤：" not in prompt and "最新收盤：" not in prompt and "已跌破事件日低點：" not in prompt


def test_post_event_facts_reach_legacy_and_agent_system_prompts():
    from unittest.mock import Mock
    from src.agent.executor import AgentExecutor
    from tests.test_event_gap_decision import _analyzer
    from src.config import Config
    from tests.test_pipeline_finalize import _result
    event = {"triggered": True, "event_low": 278.29, "post_event_min_close": 278.22, "latest_close": 278.22, "event_low_broken": True}
    analyzer = _analyzer()
    config = Config(stock_list=[], event_gap_decision_enabled=True, gemini_request_delay=0, report_integrity_enabled=False, report_language="zh-TW")
    analyzer._get_runtime_config = lambda: config
    analyzer.get_generation_backend_config_error = lambda: None
    analyzer.is_available = lambda: True
    analyzer._resolve_generation_backend_config = lambda: ("litellm", None)
    client = Mock(); client.generate.return_value = ("{}", "fixture", None)
    analyzer._resolve_llm_client = lambda: client
    analyzer._parse_response = lambda *a: _result(code="GOOG")
    today = date.today()
    context = {"code":"GOOG", "date":today.isoformat(), "today":{"date":today.isoformat(),"close":278.22},
               "event_gap_daily_bars":[{"date":(today-timedelta(days=1)).isoformat(),"close":280,"low":278.29,"pct_chg":-13},
                                       {"date":today.isoformat(),"close":278.22,"pct_chg":0}]}
    context["event_gap"] = event_gap_context("GOOG", context, config)
    assert analyzer.analyze(context).success
    for prompt in (client.generate.call_args.args[0], client.generate.call_args.kwargs["system_prompt"]):
        assert "已跌破事件日低點：是" in prompt
        assert "事件後最低收盤：278.22" in prompt
    executor = AgentExecutor.__new__(AgentExecutor)
    executor.skill_instructions=""; executor.default_skill_policy=""; executor.use_legacy_default_prompt=True
    executor.tool_registry=Mock(); executor.tool_registry.to_openai_tools.return_value=[]; executor._run_loop=Mock()
    executor.run("Analyze", {"stock_code":"GOOG","event_gap":event})
    system = executor._run_loop.call_args.args[0][0]["content"]
    assert "已跌破事件日低點：是" in system
    assert "事件後新低重新計算" in system
