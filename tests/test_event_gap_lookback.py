"""事件交易日視窗、明確低點與新聞時效的回歸驗證。"""
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from tests.litellm_stub import ensure_litellm_stub
ensure_litellm_stub()
from src.services.event_gap import event_gap_context, event_gap_prompt, apply_event_gap_guard
from src.report_language import SUPPORTED_REPORT_LANGUAGES
from tests.test_event_gap_decision import _analyzer, _finish
from tests.test_pipeline_finalize import _result


def _config(lookback=5):
    return SimpleNamespace(event_gap_decision_enabled=True, event_gap_threshold_pct=12,
                           event_gap_lookback_sessions=lookback, report_language="zh-TW")


def _context(event_ago=1, size=8):
    dates = pd.bdate_range(end=date.today(), periods=size)
    rows = [{"date": day.date().isoformat(), "close": 65.76, "low": 65, "pct_chg": 0} for day in dates]
    if event_ago is not None:
        rows[-1-event_ago].update(pct_chg=-28.58, low=63.20)
    return {"code": "INTC", "date": rows[-1]["date"], "today": dict(rows[-1]),
            "realtime": {"change_pct": 0}, "event_gap_daily_bars": rows}


def test_event_stays_active_on_quiet_following_session():
    context = _context(1)
    event = event_gap_context("INTC", context, _config())
    assert event is not None
    assert event["event_date"] == context["event_gap_daily_bars"][-2]["date"]
    assert event["change_pct"] == -28.58
    assert event["event_low"] == 63.20
    assert event["sessions_since_event"] == 1


@pytest.mark.parametrize("ago,expected", [(0, True), (4, True), (5, False), (6, False)])
def test_five_sessions_includes_today_and_excludes_older_event(ago, expected):
    assert bool(event_gap_context("INTC", _context(ago), _config())) is expected


@pytest.mark.parametrize("lookback,ago,expected", [(1, 0, True), (1, 1, False), (3, 2, True), (3, 3, False)])
def test_configurable_session_window(lookback, ago, expected):
    assert bool(event_gap_context("INTC", _context(ago), _config(lookback))) is expected


def test_most_recent_event_wins_and_dates_are_sorted_and_deduplicated():
    context = _context(4)
    context["event_gap_daily_bars"][-2].update(pct_chg=15, low=64)
    expected_date = context["event_gap_daily_bars"][-2]["date"]
    context["event_gap_daily_bars"] = list(reversed(context["event_gap_daily_bars"])) * 2
    event = event_gap_context("INTC", context, _config())
    assert event["event_date"] == expected_date
    assert event["change_pct"] == 15
    assert event["event_low"] == 64
    assert event["sessions_since_event"] == 1


def test_missing_pct_is_computed_from_adjacent_actual_closes():
    context = _context(None, size=6)
    for i, row in enumerate(context["event_gap_daily_bars"]):
        row.pop("pct_chg")
        row["close"] = 100 if i == 0 else 70
    context["today"].update(close=70, pct_chg=0)
    event = event_gap_context("INTC", context, _config())
    assert event["sessions_since_event"] == 4
    assert event["change_pct"] == pytest.approx(-30)


def test_explicit_daily_pct_precedes_close_calculation_and_realtime():
    context = _context(None)
    context["realtime"]["change_pct"] = 30
    assert event_gap_context("INTC", context, _config()) is None


def test_invalid_history_falls_back_to_current_change_and_low():
    context = {"date": date.today().isoformat(), "today": {"low": 63.20}, "realtime": {"change_pct": -28.58},
               "event_gap_daily_bars": [{"date": "bad", "close": None, "pct_chg": float("nan")} ]}
    event = event_gap_context("INTC", context, _config())
    assert event["event_date"] == date.today().isoformat()
    assert event["event_low"] == 63.20
    assert event["sessions_since_event"] == 0
    context["realtime"]["change_pct"] = 0
    assert event_gap_context("INTC", context, _config()) is None


def test_prompt_prints_event_facts_and_omits_missing_low():
    event = event_gap_context("INTC", _context(), _config())
    prompt = event_gap_prompt(event)
    assert event["event_date"] in prompt
    assert "-28.58%" in prompt
    assert "事件日低點：63.2" in prompt
    event["event_low"] = None
    assert "事件日低點：" not in event_gap_prompt(event)
    event["event_low"] = 0
    assert "事件日低點：0" in event_gap_prompt(event)


def test_legacy_system_and_user_prompts_include_same_event_low():
    from src.config import Config
    from unittest.mock import Mock
    context = _context()
    analyzer = _analyzer()
    config = Config(stock_list=[], event_gap_decision_enabled=True, gemini_request_delay=0,
                    report_integrity_enabled=False, report_language="zh-TW")
    analyzer._get_runtime_config = lambda: config
    analyzer.get_generation_backend_config_error = lambda: None
    analyzer.is_available = lambda: True
    analyzer._resolve_generation_backend_config = lambda: ("litellm", None)
    client = Mock()
    client.generate.return_value = ("{}", "fixture", None)
    analyzer._resolve_llm_client = lambda: client
    analyzer._parse_response = lambda *args: _result(code="INTC")
    assert analyzer.analyze(context).success
    call = client.generate.call_args
    for prompt in (call.args[0], call.kwargs["system_prompt"]):
        assert context["event_gap_daily_bars"][-2]["date"] in prompt
        assert "事件日低點：63.2" in prompt


@pytest.mark.parametrize("language", SUPPORTED_REPORT_LANGUAGES)
def test_guard_has_message_for_every_supported_language(language):
    result = _result(code="INTC", report_language=language)
    apply_event_gap_guard(result, event_gap_context("INTC", _context(), _config()), language)
    assert result.decision_type == "hold"
    assert result.action == "watch"
    expected = {
        "zh": "重大波动但没有新闻，不下买卖结论",
        "zh-TW": "重大波動但沒有新聞，不下買賣結論",
        "en": "Major price move without news evidence; no buy or sell conclusion.",
        "ko": "큰 주가 변동에 대한 뉴스 근거가 없어 매수·매도 결론을 내리지 않습니다.",
    }
    assert result.dashboard["event_gap"]["reason"] == expected[language]


def test_same_historical_event_drives_persisted_no_news_guard():
    context = _context(4)
    result, saved, _ = _finish(_config(), context, decision="buy")
    assert result.action == "watch"
    event = saved["dashboard"]["event_gap"]
    assert event["event_date"] == context["event_gap_daily_bars"][-5]["date"]
    assert event["sessions_since_event"] == 4
    assert event["blocked_without_news"]


@pytest.mark.parametrize("agent", [False, True])
def test_loaded_daily_history_reaches_both_pipeline_paths_without_extra_fetch(monkeypatch, caplog, agent):
    from unittest.mock import Mock
    from tests import test_event_gap_decision as original
    from tests import test_pipeline_index_targets as fixtures
    context = _context(1)
    history = context.pop("event_gap_daily_bars")
    factory = fixtures._analysis_pipeline
    pipelines = []
    def build(*args, **kwargs):
        pipeline = factory(*args, **kwargs)
        pipeline.db.get_data_range.return_value = [SimpleNamespace(to_dict=lambda row=row: row) for row in history]
        pipeline._build_agent_analysis_artifacts = Mock(wraps=pipeline._build_agent_analysis_artifacts)
        pipelines.append(pipeline)
        return pipeline
    monkeypatch.setattr(fixtures, "_analysis_pipeline", build)
    monkeypatch.setattr(original, "_context", lambda: context)
    original.test_actual_pipeline_paths_use_market_availability_and_event_rules(monkeypatch, caplog, agent, True, 0, "disabled")
    pipeline = pipelines[0]
    pipeline.db.get_data_range.assert_called_once()
    pipeline.fetcher_manager.get_daily_data.assert_not_called()
    if agent:
        sent_context = pipeline._build_agent_analysis_artifacts.call_args.kwargs["initial_context"]
    else:
        sent_context = pipeline.analyzer.analyze.call_args.args[0]
    event = sent_context["event_gap"]
    saved_event = pipeline.db.save_analysis_history.call_args.kwargs["result"].dashboard["event_gap"]
    assert event["event_date"] == history[-2]["date"]
    assert event["event_low"] == 63.20
    assert event["sessions_since_event"] == 1
    assert all(saved_event[key] == value for key, value in event.items())


@pytest.mark.parametrize("mode", ["single", "multi"])
def test_agent_system_messages_print_event_date_change_and_low(mode):
    from unittest.mock import Mock
    event = event_gap_context("INTC", _context(), _config())
    context = {"stock_code": "INTC", "event_gap": event}
    if mode == "single":
        from src.agent.executor import AgentExecutor
        executor = AgentExecutor.__new__(AgentExecutor)
        executor.skill_instructions = ""
        executor.default_skill_policy = ""
        executor.use_legacy_default_prompt = True
        executor.tool_registry = Mock()
        executor._run_loop = Mock()
        executor.run("Analyze", context)
        prompt = executor._run_loop.call_args.args[0][0]["content"]
    else:
        from src.agent.orchestrator import AgentOrchestrator
        from src.agent.agents.technical_agent import TechnicalAgent
        ctx = AgentOrchestrator.__new__(AgentOrchestrator)._build_context("Analyze", context)
        agent = TechnicalAgent.__new__(TechnicalAgent)
        agent.skill_instructions = ""
        agent.technical_skill_policy = ""
        agent.memory = SimpleNamespace(enabled=False)
        prompt = agent._build_messages(ctx)[0]["content"]
    assert event["event_date"] in prompt
    assert "-28.58%" in prompt
    assert "事件日低點：63.2" in prompt


def test_old_event_news_is_excluded_without_widening_news_evidence():
    from src.search_service import SearchService, SearchResponse, SearchResult
    from src.services.empty_news import news_evidence_present
    context = _context(4)
    event = event_gap_context("INTC", context, _config())
    response = SearchResponse("INTC", [SearchResult("earnings", "event", "https://example.com", "fixture",
                                                  published_date=event["event_date"])], "fixture")
    service = SearchService.__new__(SearchService)
    filtered = service._filter_news_response(response, search_days=3, max_results=5, log_scope="event-gap-test")
    assert filtered.results == []
    result = _result(code="INTC", news_evidence_present=news_evidence_present(len(filtered.results), None, None))
    apply_event_gap_guard(result, event, "zh-TW")
    assert result.dashboard["event_gap"]["blocked_without_news"]
    assert result.action == "watch"
    # 既有契約只看任一可用來源是否有證據，並不把新聞與事件日重新關聯。
    assert news_evidence_present(0, "recent social context", None)
    assert news_evidence_present(0, None, "recent persisted intelligence")


@pytest.mark.parametrize("value", [None, pd.NaT, float("nan"), "bad"])
def test_missing_history_dates_do_not_raise(value):
    context = {"event_gap_daily_bars": [{"date": value, "pct_chg": -30}], "realtime": {"change_pct": 1}}
    assert event_gap_context("INTC", context, _config()) is None


def test_lookback_configuration_is_loaded_from_environment(monkeypatch):
    import os
    from unittest.mock import patch
    from src.config import Config
    with patch.dict(os.environ, {"EVENT_GAP_LOOKBACK_SESSIONS": "3"}, clear=True), \
            patch("src.config.setup_env"), patch.object(Config, "_capture_bootstrap_runtime_env_overrides"):
        assert Config._load_from_env().event_gap_lookback_sessions == 3


def test_weekend_keeps_event_active_but_friday_news_leaves_monday_window(monkeypatch):
    from datetime import datetime, timedelta, time
    from src.search_service import SearchService, SearchResponse, SearchResult
    from src.services.empty_news import news_evidence_present
    monday = date.today() - timedelta(days=date.today().weekday())
    friday = monday - timedelta(days=3)
    class MondayClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.combine(monday, time(12))
    monkeypatch.setattr("src.search_service.datetime", MondayClock)
    rows = [{"date": friday.isoformat(), "pct_chg": -28.58, "low": 63.20, "close": 65.76},
            {"date": monday.isoformat(), "pct_chg": 0, "low": 65, "close": 65.76}]
    context = {"date": monday.isoformat(), "today": rows[-1], "event_gap_daily_bars": rows}
    event = event_gap_context("INTC", context, _config(2))
    assert event["sessions_since_event"] == 1
    response = SearchResponse("INTC", [SearchResult("earnings", "event", "https://example.com", "fixture",
                                                  published_date=friday.isoformat())], "fixture")
    filtered = SearchService.__new__(SearchService)._filter_news_response(
        response, search_days=3, max_results=5, log_scope="weekend-event-test")
    assert not news_evidence_present(len(filtered.results), None, None)


def test_future_daily_rows_are_not_events_for_current_analysis():
    context = _context(None)
    future = (pd.Timestamp(context["date"]) + pd.offsets.BDay()).date().isoformat()
    context["event_gap_daily_bars"].append({"date": future, "pct_chg": -30, "low": 60})
    assert event_gap_context("INTC", context, _config()) is None


def test_feature_off_does_not_change_prompt_even_with_loaded_event_history():
    context = _context(1)
    config = _config()
    config.event_gap_decision_enabled = False
    assert event_gap_context("INTC", context, config) is None
    without_history = {key: value for key, value in context.items() if key != "event_gap_daily_bars"}
    analyzer = _analyzer()
    assert analyzer._format_prompt(context, "Intel", report_language="zh-TW") == analyzer._format_prompt(
        without_history, "Intel", report_language="zh-TW")


def test_guard_normalizes_supported_language_alias():
    result = _result(code="INTC")
    apply_event_gap_guard(result, event_gap_context("INTC", _context(), _config()), "zh_tw")
    assert result.dashboard["event_gap"]["reason"] == "重大波動但沒有新聞，不下買賣結論"


def test_actual_close_calculation_precedes_estimated_today_pct():
    context = _context(None)
    context["event_gap_daily_bars"][-2]["close"] = 100
    context["event_gap_daily_bars"][-1].update(close=70, pct_chg=None, low=63.20)
    context["today"].update(close=70, pct_chg=0, is_estimated=True)
    context["realtime"]["change_pct"] = 0
    event = event_gap_context("INTC", context, _config())
    assert event["event_date"] == context["date"]
    assert event["sessions_since_event"] == 0
    assert event["change_pct"] == pytest.approx(-30)
    assert event["event_low"] == 63.20
