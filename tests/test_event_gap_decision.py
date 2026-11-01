"""事件判讀的開關、逐字元相容性與最後落庫護欄。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from tests.litellm_stub import ensure_litellm_stub
ensure_litellm_stub()
from src.analyzer import GeminiAnalyzer
from src.services.event_gap import event_gap_context, event_gap_prompt
from tests.test_pipeline_finalize import _make_pipeline, _artifacts, _result


BASELINE = Path(__file__).parent / "fixtures" / "event_gap_baseline.json"


def _analyzer(cls=GeminiAnalyzer):
    analyzer = cls.__new__(cls)
    analyzer._get_runtime_config = lambda: SimpleNamespace(news_max_age_days=7, news_strategy_profile="short", tw_live_events_enabled=False)
    analyzer._get_skill_prompt_sections = lambda: ("", "", True)
    analyzer._tw_ma_weighted_active = lambda *args: False
    analyzer._tw_macro_ab_active = lambda *args: False
    analyzer._tw_institutional_trend_lines = lambda *args: ""
    analyzer._tw_margin_lines = lambda *args: ""
    return analyzer


def _context(code="INTC", change=-28.58):
    return {"code": code, "stock_name": "Test", "date": "fixture-session", "today": {"close": 65.76, "pct_chg": change},
            "realtime": {"price": 65.76, "change_pct": change}}


def _finish(config, context, *, evidence=False, decision="sell", code="INTC", method=None, agent=False, news_text=""):
    pipeline = _make_pipeline()
    pipeline.config = config
    result = _result(code=code, decision_type=decision, action=decision, report_language="zh-TW", news_evidence_present=evidence)
    result.news_summary = news_text
    saved = []
    signals = []
    pipeline.db.save_analysis_history.side_effect = lambda **kw: saved.append(deepcopy(kw["result"].to_dict())) or 1
    with patch("src.services.decision_signal_extractor.DecisionSignalService") as service:
        service.return_value.create_signal.side_effect = lambda data: signals.append(deepcopy(data))
        (method or pipeline._finalize_and_persist_result)(
            result, _artifacts(code=code, market="us", enhanced_context=context),
            market_phase_summary=None, analysis_context_pack_overview=None, report_type="simple",
            snapshot_context=context, news_content_for_save=None, attach_agent_diagnostics=agent,
        )
    assert saved and saved[0] == result.to_dict()
    return result, saved[0], signals


@pytest.mark.parametrize("enabled,code,change,trigger", [
    (False, "INTC", -28.58, False), (True, "INTC", -12, True), (True, "INTC", 12, True),
    (True, "INTC", -11.99, False), (True, "2330.TW", 12, True), (True, "00631L.TW", -13, True),
    (True, "1234.TWO", -20, True), (True, "0700.HK", 20, False), (True, "600519", -20, False),
    (True, "INTC", float("nan"), False), (True, "INTC", None, False),
])
def test_event_gap_trigger(enabled, code, change, trigger):
    cfg = SimpleNamespace(event_gap_decision_enabled=enabled, event_gap_threshold_pct=12)
    assert bool(event_gap_context(code, _context(code, change), cfg)) is trigger


def test_configurable_threshold_and_daily_fallback():
    cfg = SimpleNamespace(event_gap_decision_enabled=True, event_gap_threshold_pct=20)
    assert event_gap_context("INTC", {"today": {"pct_chg": 19}}, cfg) is None
    assert event_gap_context("INTC", {"today": {"pct_chg": -20}}, cfg)["triggered"]


@pytest.mark.parametrize("language", ["zh", "zh-TW", "en", "ko"])
@pytest.mark.parametrize("code", ["INTC", "2330.TW"])
def test_disabled_or_not_triggered_prompt_byte_for_byte(language, code):
    analyzer = _analyzer()
    baseline = json.loads(BASELINE.read_text())
    for enabled, change in [(False, -28.58), (True, -11.99)]:
        context = _context(code, change)
        cfg = SimpleNamespace(event_gap_decision_enabled=enabled, event_gap_threshold_pct=12)
        event = event_gap_context(code, context, cfg)
        assert event is None
        user = analyzer._format_prompt(context, "Test", report_language=language)
        system = analyzer._get_analysis_system_prompt(language, code)
        key = f"{code}/{language}/{change}"
        assert sha256(user.encode()).hexdigest() == baseline["prompts"][key]["user"]
        assert sha256(system.encode()).hexdigest() == baseline["prompts"][key]["system"]


def test_event_prompt_has_rules_and_evidence():
    context = _context()
    cfg = SimpleNamespace(event_gap_decision_enabled=True, event_gap_threshold_pct=12)
    context["event_gap"] = event_gap_context("INTC", context, cfg)
    context["fundamental_context"] = {"valuation": {"data": {"forward_pe": 15}}, "us_evidence": {
        "ratings_30d": {"count": 1}, "short_interest": {"shares_short": 100, "as_of": "fixture-date"},
    }}
    prompt = _analyzer()._format_prompt(context, "Test", report_language="zh-TW")
    assert prompt.endswith(event_gap_prompt(context["event_gap"]))
    for text in ("投資論題", "下修", "幾個交易日", "事件日低點", "分批試單", "失效條件", "不得使用含事件日之前價格的均線", "預期本益比", "評等可能尚未反映最新事件", "資料日：fixture-date"):
        assert text in prompt


@pytest.mark.parametrize("agent", [False, True])
@pytest.mark.parametrize("decision", ["buy", "sell"])
def test_missing_news_hold_is_saved_after_all_other_guards(agent, decision):
    cfg = SimpleNamespace(report_language="zh-TW", event_gap_decision_enabled=True, event_gap_threshold_pct=12)
    result, saved, signals = _finish(cfg, _context(), decision=decision, agent=agent, news_text="模型聲稱已有新聞")
    assert saved["decision_type"] == "hold"
    assert saved["action"] == "watch"
    assert saved["confidence_level"] == "低"
    assert "重大波動但沒有新聞，不下買賣結論" in result.get_core_conclusion()
    assert saved["dashboard"]["event_gap"]["blocked_without_news"]
    assert signals and signals[0]["action"] == "watch"


def test_structured_news_evidence_is_used_without_matching_text():
    cfg = SimpleNamespace(report_language="zh-TW", event_gap_decision_enabled=True, event_gap_threshold_pct=12)
    result, _, _ = _finish(cfg, _context(), evidence=True)
    assert result.decision_type == "sell"
    assert not result.dashboard["event_gap"]["blocked_without_news"]


@pytest.mark.parametrize("enabled,change", [(False, -28.58), (True, -11.99)])
def test_untriggered_result_byte_for_byte(enabled, change):
    cfg = SimpleNamespace(report_language="zh-TW", event_gap_decision_enabled=enabled, event_gap_threshold_pct=12)
    _, saved, _ = _finish(cfg, _context(change=change))
    baseline = json.loads(BASELINE.read_text())
    assert json.dumps(saved, ensure_ascii=False, sort_keys=True) == baseline["result"]


@pytest.mark.parametrize("agent", [False, True])
@pytest.mark.parametrize("available,count", [(False, None), (True, 0), (True, 1)])
@pytest.mark.parametrize("sec_kind", ["disabled", "earnings", "excerpt", "header", "expired"])
def test_actual_pipeline_paths_use_market_availability_and_event_rules(monkeypatch, caplog, agent, available, count, sec_kind):
    from datetime import datetime, timezone
    from src.agent.executor import AgentResult
    from src.agent.news_evidence import record_news_evidence
    from src.core.pipeline import StockAnalysisPipeline
    from src.enums import ReportType
    from src.search_service import SearchService, SearchResponse, SearchResult
    from tests.test_pipeline_index_targets import _analysis_pipeline
    pipeline = _analysis_pipeline("INTC", "Intel")
    pipeline.config.agent_mode = agent
    pipeline.config.event_gap_decision_enabled = True
    pipeline.config.event_gap_threshold_pct = 12
    pipeline.config.event_gap_lookback_sessions = 5
    pipeline.config.report_language = "zh-TW"
    pipeline.config.enable_chip_distribution = False
    pipeline.config.enable_realtime_quote = False
    pipeline.save_context_snapshot = True
    pipeline._build_legacy_analysis_artifacts = StockAnalysisPipeline._build_legacy_analysis_artifacts.__get__(pipeline)
    pipeline._refresh_decision_action_for_final_result = StockAnalysisPipeline._refresh_decision_action_for_final_result
    from datetime import timedelta
    from data_provider.us_evidence import format_us_evidence
    fundamental = {}
    sec_present = sec_kind in {"earnings", "excerpt"}
    if sec_kind != "disabled":
        filing = {"date": (datetime.now(timezone.utc).date() - timedelta(days=15 if sec_kind == "expired" else 5)).isoformat(),
                  "items": "2.02,9.01" if sec_kind in {"earnings", "expired"} else "9.01"}
        if sec_kind == "excerpt":
            filing["excerpt"] = "Company earnings release"
        fundamental = {"us_evidence": {"sec_filings": {"recent_8k": [filing]}}}
    pipeline.fetcher_manager.get_fundamental_context.return_value = fundamental
    pipeline.fetcher_manager.get_stock_name.return_value = "Intel"
    pipeline.fetcher_manager.get_chip_distribution.return_value = None
    service = SearchService.__new__(SearchService)
    service._finmind_provider = Mock()
    service._providers = [Mock(is_available=True)] if available else []
    results = [SearchResult("news", "evidence", "https://example.com", "test")] if count else []
    response = SearchResponse("INTC", results, "fixture")
    service.search_comprehensive_intel = Mock(return_value={"latest_news": response})
    service.search_stock_news = Mock(return_value=response)
    service.format_intel_report = Mock(return_value="fixture news placeholder")
    pipeline.search_service = service
    context = _context()
    if fundamental:
        context["fundamental_context"] = fundamental
    pipeline._get_analysis_context_with_market_fallback.return_value = context
    pipeline._enhance_context.return_value = deepcopy(context)
    result = _result(code="INTC", decision_type="sell", action="sell", report_language="zh-TW")
    pipeline.analyzer.analyze.return_value = result
    pipeline._ensure_agent_history = Mock()
    pipeline._load_agent_analysis_context = Mock(return_value=context)
    pipeline._append_daily_data_source = Mock()
    # 只隔離市場時鐘與外部模型；來源／事件判定與 finalize 跑真實程式。
    phase = Mock()
    phase.to_dict.return_value = {"phase": "postmarket", "effective_daily_bar_date": "fixture-session"}
    phase.effective_daily_bar_date = datetime.now(timezone.utc).date()
    monkeypatch.setattr("src.core.pipeline.build_market_phase_context", lambda **kw: phase)
    monkeypatch.setattr("src.core.pipeline.render_market_phase_summary", lambda *a: {})
    sent = []
    def run(message, context):
        sent.append(deepcopy(context))
        if count:
            record_news_evidence(count)
        return AgentResult(success=True, content="{}", dashboard=result.to_dict(), provider="fixture")
    executor = Mock()
    executor.run.side_effect = run
    monkeypatch.setattr("src.agent.factory.build_agent_executor", lambda *a: executor)
    saved = []
    pipeline.db.save_analysis_history.side_effect = lambda **kw: saved.append(deepcopy(kw["result"].to_dict())) or 1
    returned = pipeline.analyze_stock("INTC", ReportType.SIMPLE, "fixture-query", current_time=datetime.now(timezone.utc))
    assert returned is not None
    assert returned.news_result_count == count
    assert returned.news_evidence_present is (bool(count) or sec_present)
    assert saved and saved[0]["news_result_count"] == count
    assert saved[0]["news_evidence_present"] is (bool(count) or sec_present)
    if not count and not sec_present:
        assert returned.decision_type == "hold"
        assert returned.confidence_level == "低"
    else:
        assert returned.decision_type == "sell"
    if agent:
        assert sent[0]["event_gap"]["triggered"]
        if fundamental:
            assert sent[0]["us_evidence_prompt"] == format_us_evidence(fundamental)
    else:
        assert pipeline.analyzer.analyze.call_args.args[0]["event_gap"]["triggered"]
    if not available:
        assert "未配置此市場" in caplog.text
        service.search_comprehensive_intel.assert_not_called()
        service.search_stock_news.assert_not_called()


def test_agent_executor_event_rules_reach_system_prompt():
    from src.agent.executor import AgentExecutor
    executor = AgentExecutor.__new__(AgentExecutor)
    executor.skill_instructions = ""
    executor.default_skill_policy = ""
    executor.use_legacy_default_prompt = True
    executor.tool_registry = Mock()
    executor.tool_registry.to_openai_tools.return_value = []
    executor._run_loop = Mock()
    context = {"stock_code": "INTC", "event_gap": {"triggered": True}, "us_evidence_prompt": "fixture evidence"}
    executor.run("Analyze", context)
    messages = executor._run_loop.call_args.args[0]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].endswith(event_gap_prompt(context["event_gap"]))
    assert "fixture evidence" in messages[1]["content"]
    first = messages[0]["content"]
    executor.run("Analyze", {"stock_code": "INTC"})
    second = executor._run_loop.call_args.args[0][0]["content"]
    assert first == second + event_gap_prompt(context["event_gap"])


def test_multistage_agents_receive_system_override_and_evidence():
    from src.agent.agents.technical_agent import TechnicalAgent
    from src.agent.orchestrator import AgentOrchestrator
    # 真正的初始上下文組裝，再送入共用的 stage message 邊界。
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    context = {"stock_code": "INTC", "event_gap": {"triggered": True}, "us_evidence_prompt": "fixture evidence"}
    ctx = orchestrator._build_context("Analyze", context)
    agent = TechnicalAgent.__new__(TechnicalAgent)
    agent.skill_instructions = ""
    agent.technical_skill_policy = ""
    agent.memory = SimpleNamespace(enabled=False)
    messages = agent._build_messages(ctx)
    assert messages[0]["content"].endswith(event_gap_prompt(context["event_gap"]))
    assert any(message["content"] == "fixture evidence" for message in messages[1:])


@pytest.mark.parametrize("enabled,change,triggered", [(False, -28.58, False), (True, -11.99, False), (True, -28.58, True)])
def test_traditional_generation_receives_event_system_and_user_rules(enabled, change, triggered):
    from src.config import Config
    analyzer = _analyzer()
    cfg = Config(stock_list=[], event_gap_decision_enabled=enabled, event_gap_threshold_pct=12,
                 gemini_request_delay=0, report_integrity_enabled=False, report_language="zh-TW")
    analyzer._get_runtime_config = lambda: cfg
    analyzer.get_generation_backend_config_error = lambda: None
    analyzer.is_available = lambda: True
    analyzer._resolve_generation_backend_config = lambda: ("litellm", None)
    client = Mock()
    client.generate.return_value = ("{}", "fixture-model", None)
    analyzer._resolve_llm_client = lambda: client
    analyzer._parse_response = lambda *args: _result(code="INTC")
    context = _context(change=change)
    baseline_system = analyzer._get_analysis_system_prompt("zh-TW", "INTC")
    result = analyzer.analyze(context)
    assert result.success
    assert client.generate.call_count == 1
    call = client.generate.call_args
    assert ("重大波動事件判讀" in call.args[0]) is triggered
    assert call.kwargs["system_prompt"] == baseline_system + event_gap_prompt(event_gap_context("INTC", context, cfg))


@pytest.mark.parametrize("score", [22, 80])
def test_history_keeps_persisted_event_watch_action(score):
    from src.services.history_service import HistoryService
    cfg = SimpleNamespace(report_language="zh-TW", event_gap_decision_enabled=True, event_gap_threshold_pct=12)
    _, saved, _ = _finish(cfg, _context(), decision="buy")
    record = SimpleNamespace(operation_advice="觀望", report_type="simple", sentiment_score=score)
    fields = HistoryService.__new__(HistoryService)._decision_action_fields_for_record(record, saved)
    assert fields["action"] == "watch"


def test_event_without_applied_guard_does_not_override_history_score_alignment():
    from src.schemas.decision_scale import extract_decision_guardrail_reason
    raw = {"dashboard": {"event_gap": {"blocked_without_news": False, "reason": "not applied"}}}
    assert extract_decision_guardrail_reason(raw) is None


@pytest.mark.parametrize("env,enabled,threshold", [({}, False, 12),
    ({"EVENT_GAP_DECISION_ENABLED": "true", "EVENT_GAP_THRESHOLD_PCT": "15"}, True, 15)])
def test_event_config_reads_environment_with_safe_defaults(env, enabled, threshold):
    import os
    from src.config import Config
    with patch.dict(os.environ, env, clear=True), patch("src.config.setup_env"), \
            patch.object(Config, "_capture_bootstrap_runtime_env_overrides"):
        config = Config._load_from_env()
    assert config.event_gap_decision_enabled is enabled
    assert config.event_gap_threshold_pct == threshold
    assert config.event_gap_lookback_sessions == 5


def test_blocked_without_news_clears_split_conditions():
    from types import SimpleNamespace

    from src.services.event_gap import apply_event_gap_guard

    result = SimpleNamespace(
        news_evidence_present=False,
        dashboard={"phase_decision": {"entry_conditions": ["站回 70 買進"], "exit_triggers": ["跌破 60"]}},
    )
    apply_event_gap_guard(result, {"triggered": True}, "zh-TW")
    phase = result.dashboard["phase_decision"]
    assert phase["entry_conditions"] == [] and phase["exit_triggers"] == []
