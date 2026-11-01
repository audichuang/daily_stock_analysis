"""事件展望：證據正規化、依證據收斂、讀取端投影、提示詞接線與回驗計分。"""
import importlib.util
import json
import sys
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from api.v1.schemas.history import AnalysisReport, ReportMeta, ReportSummary  # noqa: E402
from data_provider.base import DataFetcherManager  # noqa: E402
from data_provider.futu_fetcher import FutuFetcher  # noqa: E402
from data_provider.us_evidence import format_us_evidence, summarize_estimates  # noqa: E402
from src.agent.agents.decision_agent import DecisionAgent  # noqa: E402
from src.agent.protocols import AgentContext  # noqa: E402
from src.analyzer import AnalysisResult  # noqa: E402
from src.core.pipeline import PipelineAnalysisArtifacts, StockAnalysisPipeline  # noqa: E402
from src.report_language import SUPPORTED_REPORT_LANGUAGES  # noqa: E402
from src.services.event_outlook import (  # noqa: E402
    apply_event_outlook_guard,
    event_outlook_prompt,
    extract_event_outlook,
    normalize_event_outlook,
)

_spec = importlib.util.spec_from_file_location(
    "verify_event_outlook", Path(__file__).resolve().parent.parent / "scripts" / "verify_event_outlook.py"
)
verify = importlib.util.module_from_spec(_spec)
sys.modules["verify_event_outlook"] = verify
_spec.loader.exec_module(verify)

TODAY = date.today()
EVENT = (TODAY + timedelta(days=10)).isoformat()
ESTIMATES = {"eps": {"avg": 2.47, "analysts": 44, "currency": "USD"},
             "revenue": {"avg": 1.09e11, "analysts": 45, "currency": "USD"}}
US_CONTEXT = {"us_evidence": {"estimates": ESTIMATES}}
NEXT = {"type": "earnings", "date": EVENT}


def _llm(**overrides):
    return {
        "event": "Q3 財報", "event_type": "earnings", "event_date": "1999-01-01",
        "consensus": {"eps": 999, "revenue": 1, "analysts": 1},
        "expectation": "beat", "confidence": "high", "reasoning": "連四季超預期",
        "scenarios": [{"case": "beat", "expected_reaction": "上漲", "action_if_holding": "續抱", "action_if_flat": "等回檔"},
                      {"case": "nonsense"}],
        "news_impact": "新產品提高下季預期", "verify_after": "看毛利率",
        **overrides,
    }


def _frames():
    earnings = pd.DataFrame(
        {"avg": [2.47325, 2.7], "low": [2.34, 2.5], "high": [2.7, 3.1], "yearAgoEps": [1.3, 1.6],
         "numberOfAnalysts": [44, 42], "currency": ["USD", "USD"]}, index=["0q", "+1q"])
    revenue = pd.DataFrame(
        {"avg": [108976833310, 1], "low": [1, 1], "high": [2, 2], "yearAgoRevenue": [5, 5],
         "numberOfAnalysts": [45, 42], "currency": ["USD", "USD"]}, index=["0q", "+1q"])
    history = pd.DataFrame(
        {"epsActual": [1.3, 1.62, 1.87, 2.22, 0.1], "epsEstimate": [1.25, 1.53, 1.77, 2.09, 0.1],
         "surprisePercent": [0.0346, 0.0532, 0.0554, 0.0616, 0.0]},
        index=pd.to_datetime(["2025-10-31", "2026-01-31", "2026-04-30", "2026-07-31", "2025-07-31"]))
    revisions = pd.DataFrame({"upLast7days": [0], "upLast30days": [2], "downLast30days": [1], "downLast7Days": [1]},
                             index=["0q"])
    return earnings, revenue, history, revisions


def test_summarize_takes_next_quarter_and_converts_surprise_ratio():
    earnings, revenue, history, revisions = _frames()
    result = summarize_estimates(earnings, revenue, history, revisions)
    assert result["eps"]["avg"] == 2.47325 and result["eps"]["analysts"] == 44
    assert result["revenue"]["avg"] == 108976833310
    assert result["eps"]["currency"] == result["revenue"]["currency"] == "USD"
    assert [row["quarter"] for row in result["track_record"]] == ["2025-10-31", "2026-01-31", "2026-04-30", "2026-07-31"]
    assert result["track_record"][0]["surprise_pct"] == 3.46
    assert result["revisions"] == {"up_7d": 0, "up_30d": 2, "down_7d": 1, "down_30d": 1}


def test_summarize_missing_frames_and_nan_yield_no_placeholder():
    assert summarize_estimates() == {}
    nan = pd.DataFrame({"avg": [float("nan")], "numberOfAnalysts": [3]}, index=["0q"])
    assert summarize_estimates(earnings_estimate=nan) == {}


def test_format_us_evidence_lists_estimates_only_when_present():
    assert "2.47" in format_us_evidence(US_CONTEXT)
    assert format_us_evidence({"us_evidence": {}}) == ""


def test_fetch_failure_does_not_drop_other_evidence():
    frames = _frames()

    class Ticker:
        earnings_estimate = frames[0]

        @property
        def revenue_estimate(self):
            raise RuntimeError("boom")

        earnings_history = frames[2]
        eps_revisions = frames[3]

    from data_provider.yfinance_fundamental_adapter import YfinanceFundamentalAdapter
    import yfinance
    original = yfinance.Ticker
    yfinance.Ticker = lambda symbol: Ticker()
    try:
        result = YfinanceFundamentalAdapter().get_us_estimate_evidence("NVDA")
    finally:
        yfinance.Ticker = original
    assert "eps" in result and "revenue" not in result and "track_record" in result


def _manager(monkeypatch, enabled):
    cfg = SimpleNamespace(enable_fundamental_pipeline=True, fundamental_cache_ttl_seconds=0,
                          fundamental_stage_timeout_seconds=60, fundamental_fetch_timeout_seconds=30,
                          fundamental_retry_max=1, analyst_consensus_enabled=False, event_outlook_enabled=enabled)
    monkeypatch.setattr("src.config.get_config", lambda: cfg)
    monkeypatch.setattr(FutuFetcher, "has_configured_endpoint", lambda: False)
    manager = DataFetcherManager(fetchers=[])
    adapter = manager._yfinance_fundamental_adapter
    monkeypatch.setattr(manager, "get_realtime_quote", lambda *a, **kw: None)
    monkeypatch.setattr(adapter, "get_fundamental_bundle", lambda code: {"valuation": {"forward_pe": 18}})
    monkeypatch.setattr(adapter, "get_us_activity_evidence", lambda *a: {"count": 1})
    return manager, adapter


@pytest.mark.parametrize("enabled", [True, False])
def test_manager_fetches_estimates_only_when_enabled(monkeypatch, enabled):
    manager, adapter = _manager(monkeypatch, enabled)
    call = Mock(return_value=ESTIMATES)
    monkeypatch.setattr(adapter, "get_us_estimate_evidence", call)
    context = manager.get_fundamental_context("INTC")
    assert call.called is enabled
    assert ("estimates" in context["us_evidence"]) is enabled
    assert context["us_evidence"]["ratings_30d"] == {"count": 1}


def test_manager_estimate_failure_keeps_other_evidence(monkeypatch):
    manager, adapter = _manager(monkeypatch, True)
    monkeypatch.setattr(adapter, "get_us_estimate_evidence", Mock(side_effect=ValueError("boom")))
    context = manager.get_fundamental_context("INTC")
    assert "estimates" not in context["us_evidence"]
    assert context["us_evidence"]["ratings_30d"] == {"count": 1}
    assert context["valuation"]["data"]["forward_pe"] == 18


def _persisted_outlook(enabled, fundamental_context):
    """走真的 finalize：驗證寫入歷史當下的值，傳統與 agent 路徑都經過這裡。"""
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(report_language="zh-TW", event_outlook_enabled=enabled)
    pipeline.save_context_snapshot = False
    pipeline.query_source = "system"
    pipeline.analysis_skills = None
    pipeline.db = MagicMock()
    saved = []
    pipeline.db.save_analysis_history.side_effect = lambda **kw: saved.append(deepcopy(kw["result"].dashboard)) or 1
    result = AnalysisResult(code="NVDA", name="NVIDIA", sentiment_score=60, trend_prediction="看多",
                            operation_advice="持有", decision_type="hold", action="hold", confidence_level="中",
                            dashboard={"event_outlook": _llm()})
    artifacts = PipelineAnalysisArtifacts(
        code="NVDA", stock_name="NVIDIA", market="us", phase=None, base_context={}, enhanced_context={},
        realtime_quote=None, trend_result=None, chip_data=None, fundamental_context=fundamental_context,
        news_context=None, news_result_count=None, metadata={"query_id": "q"})
    with patch("src.services.decision_signal_extractor.DecisionSignalService"):
        pipeline._finalize_and_persist_result(
            result, artifacts, market_phase_summary=None, analysis_context_pack_overview=None,
            report_type="simple", snapshot_context={"next_earnings": NEXT}, news_content_for_save=None)
    return saved[0], result


def test_finalize_persists_guarded_outlook_and_leaves_score_alone():
    saved, result = _persisted_outlook(True, {})
    assert saved["event_outlook"]["expectation"] == "insufficient_data"
    assert saved["event_outlook"]["consensus"] is None
    assert result.sentiment_score == 60

    saved, result = _persisted_outlook(True, US_CONTEXT)
    assert saved["event_outlook"]["expectation"] == "beat"
    assert saved["event_outlook"]["consensus"]["eps"] == 2.47
    assert result.sentiment_score == 60


def test_finalize_flag_off_never_persists_outlook():
    saved, _ = _persisted_outlook(False, US_CONTEXT)
    assert "event_outlook" not in saved


def test_guard_uses_evidence_numbers_and_date_over_llm_echo():
    outlook = normalize_event_outlook(_llm(), US_CONTEXT, NEXT)
    assert outlook["consensus"] == {"eps": 2.47, "revenue": 1.09e11, "analysts": 44,
                                    "eps_currency": "USD", "revenue_currency": "USD"}
    assert outlook["event_date"] == EVENT
    assert outlook["expectation"] == "beat" and outlook["confidence"] == "high"
    assert [s["case"] for s in outlook["scenarios"]] == ["beat"]
    assert outlook["news_impact"] == "新產品提高下季預期"


@pytest.mark.parametrize("context", [{}, {"us_evidence": {}}, None, {"us_evidence": {"estimates": {"revisions": {"up_7d": 1}}}}])
def test_guard_forces_insufficient_data_without_estimates(context):
    outlook = normalize_event_outlook(_llm(), context, NEXT)
    assert outlook["expectation"] == "insufficient_data"
    assert outlook["confidence"] == "low"
    assert outlook["consensus"] is None
    assert outlook["scenarios"], "沒有預估仍保留情境"


def test_adr_keeps_separate_eps_and_revenue_currency_through_api_model():
    """實測 TSM：EPS 5.1641 USD、營收 1705011253270 TWD。"""
    estimates = summarize_estimates(
        pd.DataFrame({"avg": [5.1641], "numberOfAnalysts": [20], "currency": ["USD"]}, index=["0q"]),
        pd.DataFrame({"avg": [1705011253270], "numberOfAnalysts": [18], "currency": ["TWD"]}, index=["0q"]))
    assert estimates["eps"]["currency"] == "USD" and estimates["revenue"]["currency"] == "TWD"
    context = {"us_evidence": {"estimates": estimates}}
    assert '"currency": "TWD"' in format_us_evidence(context)
    stored = normalize_event_outlook(_llm(), context, NEXT)
    assert stored["consensus"]["eps_currency"] == "USD" and stored["consensus"]["revenue_currency"] == "TWD"
    outlook = extract_event_outlook(json.loads(json.dumps({"dashboard": {"event_outlook": stored}})))
    report = AnalysisReport(meta=ReportMeta(query_id="q", stock_code="TSM"), summary=ReportSummary(), event_outlook=outlook)
    assert report.event_outlook.consensus.revenue_currency == "TWD"
    assert report.event_outlook.consensus.eps_currency == "USD"


def test_revenue_only_forces_insufficient_and_keeps_revenue():
    """earnings_estimate 失敗、只剩營收時，模型的 beat／high 不能留下。"""
    frames = _frames()
    context = {"us_evidence": {"estimates": summarize_estimates(None, frames[1], frames[2], frames[3])}}
    outlook = normalize_event_outlook(_llm(), context, NEXT)
    assert outlook["expectation"] == "insufficient_data" and outlook["confidence"] == "low"
    assert outlook["consensus"]["eps"] is None and outlook["consensus"]["revenue"] == 108976833310
    assert outlook["consensus"]["analysts"] == 45


def test_eps_only_still_allows_a_call():
    frames = _frames()
    context = {"us_evidence": {"estimates": summarize_estimates(frames[0])}}
    outlook = normalize_event_outlook(_llm(), context, NEXT)
    assert outlook["expectation"] == "beat" and outlook["confidence"] == "high"
    assert outlook["consensus"]["revenue"] is None


@pytest.mark.parametrize("language", SUPPORTED_REPORT_LANGUAGES)
def test_prompt_discloses_missing_eps_separately(language):
    from src.services.event_outlook import _TEXT
    from src.report_language import normalize_report_language

    text = _TEXT[normalize_report_language(language)]
    only = event_outlook_prompt({"us_evidence": {"estimates": {"revenue": {"avg": 1.0}}}}, language)
    assert text["revenue_only"] in only and text["have"] not in only and text["missing"] not in only
    assert text["have"] in event_outlook_prompt(US_CONTEXT, language)
    assert text["missing"] in event_outlook_prompt({}, language)


def test_guard_keeps_llm_miss_call_when_estimates_exist():
    assert normalize_event_outlook(_llm(expectation="miss"), US_CONTEXT, NEXT)["expectation"] == "miss"


def test_guard_non_earnings_event_has_no_expectation_or_consensus_and_keeps_its_date():
    outlook = normalize_event_outlook(_llm(event_type="other", event_date=EVENT), US_CONTEXT, NEXT)
    assert outlook["expectation"] == "insufficient_data" and outlook["consensus"] is None
    assert outlook["event_date"] == EVENT


def test_guard_clears_invented_date_when_calendar_has_none():
    assert normalize_event_outlook(_llm(), US_CONTEXT, {"date": None})["event_date"] is None
    # 快取只有法說日時，LLM 說的財報日不採用
    conference = {"type": "investor_conference", "date": EVENT}
    assert normalize_event_outlook(_llm(), US_CONTEXT, conference)["event_date"] is None
    tw = normalize_event_outlook(_llm(event_type="investor_conference"), {}, conference)
    assert tw["event_date"] == EVENT and tw["expectation"] == "insufficient_data"


def test_guard_invalid_label_becomes_insufficient_not_guessed():
    assert normalize_event_outlook(_llm(expectation="應該會超預期"), US_CONTEXT, NEXT)["expectation"] == "insufficient_data"


@pytest.mark.parametrize("value", [None, "有財報", [], {}, {"event": "  "}])
def test_guard_no_event_is_null(value):
    assert normalize_event_outlook(value, US_CONTEXT, NEXT) is None


def test_apply_guard_only_touches_event_outlook():
    dashboard = {"event_outlook": _llm(), "battle_plan": {"x": 1}}
    result = SimpleNamespace(dashboard=dashboard, sentiment_score=70, action="buy")
    apply_event_outlook_guard(result, {}, NEXT, enabled=True)
    assert dashboard["event_outlook"]["expectation"] == "insufficient_data"
    assert dashboard["battle_plan"] == {"x": 1}
    assert result.sentiment_score == 70 and result.action == "buy"


def test_apply_guard_disabled_drops_field():
    dashboard = {"event_outlook": _llm()}
    apply_event_outlook_guard(SimpleNamespace(dashboard=dashboard), US_CONTEXT, NEXT, enabled=False)
    assert "event_outlook" not in dashboard


@pytest.mark.parametrize("raw", [None, "x", {}, {"dashboard": None}, {"dashboard": {"event_outlook": "壞資料"}},
                                 {"dashboard": {"event_outlook": {"event": "x", "consensus": {"eps": float("nan")},
                                                                  "scenarios": "壞"}}}])
def test_extract_never_raises_and_api_model_accepts_result(raw):
    outlook = extract_event_outlook(raw)
    report = AnalysisReport(meta=ReportMeta(query_id="q", stock_code="NVDA"), summary=ReportSummary(), event_outlook=outlook)
    assert json.dumps(report.model_dump())


def test_sync_report_builder_reads_outlook_from_raw_result():
    from api.v1.endpoints.analysis import _build_analysis_report

    raw = {"dashboard": {"event_outlook": normalize_event_outlook(_llm(), US_CONTEXT, NEXT)}}
    report = _build_analysis_report({"details": {"raw_result": raw}}, "q", "NVDA", "NVIDIA")
    assert report.event_outlook.expectation == "beat"
    assert _build_analysis_report({"details": {"raw_result": {}}}, "q", "NVDA", "NVIDIA").event_outlook is None


def test_extract_round_trips_through_api_model():
    stored = normalize_event_outlook(_llm(), US_CONTEXT, NEXT)
    outlook = extract_event_outlook(json.loads(json.dumps({"dashboard": {"event_outlook": stored}})))
    report = AnalysisReport(meta=ReportMeta(query_id="q", stock_code="NVDA"), summary=ReportSummary(), event_outlook=outlook)
    assert report.model_dump()["event_outlook"]["expectation"] == "beat"


@pytest.mark.parametrize("language", SUPPORTED_REPORT_LANGUAGES)
def test_prompt_states_contract_and_data_status_in_each_language(language):
    have = event_outlook_prompt(US_CONTEXT, language)
    missing = event_outlook_prompt({}, language)
    for key in ("event_outlook", "insufficient_data", "scenarios", "news_impact", "verify_after", "event_type"):
        assert key in have
    assert have != missing
    assert "{skeleton}" not in have


def test_decision_agent_receives_contract_only_outside_chat():
    agent = DecisionAgent.__new__(DecisionAgent)
    ctx = AgentContext(query="q", stock_code="NVDA", stock_name="NVIDIA")
    ctx.meta["event_outlook_prompt"] = "EVENT_CONTRACT"
    assert "EVENT_CONTRACT" in agent.build_user_message(ctx)
    ctx.meta["response_mode"] = "chat"
    assert "EVENT_CONTRACT" not in agent.build_user_message(ctx)


def test_analyzer_prompt_gated_by_flag():
    from src.analyzer import GeminiAnalyzer

    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    context = {"code": "NVDA", "date": TODAY.isoformat(), "today": {}, "fundamental_context": US_CONTEXT}
    for enabled, expected in ((True, True), (False, False)):
        config = SimpleNamespace(event_outlook_enabled=enabled, bias_threshold=5.0, news_max_age_days=30,
                                 news_strategy_profile="medium")
        analyzer._get_runtime_config = lambda config=config: config
        analyzer._get_skill_prompt_sections = lambda: ("", "", True)
        with patch("src.analyzer.get_config", return_value=config):
            assert ("event_outlook" in analyzer._format_prompt(context, "NVIDIA", news_context=None)) is expected


# ---- 回驗 ----

def _history(quarter_end, surprise):
    return pd.DataFrame({"epsActual": [1.1], "epsEstimate": [1.0], "surprisePercent": [surprise]},
                        index=pd.to_datetime([quarter_end]))


def _row(code="NVDA", event_days_ago=5, created_days_ago=8, expectation="beat", event_type="earnings", report_id=1):
    return {"report_id": report_id, "code": code, "created_at": str(TODAY - timedelta(days=created_days_ago)),
            "outlook": {"event_type": event_type, "event_date": (TODAY - timedelta(days=event_days_ago)).isoformat(),
                        "expectation": expectation, "confidence": "medium"}}


def _evidence(announced_days_ago=5, surprise=0.05, quarter_days_ago=40, reported=1.1):
    stamp = pd.Timestamp(TODAY - timedelta(days=announced_days_ago)).tz_localize("America/New_York") + pd.Timedelta(hours=16)
    dates = pd.DataFrame({"Reported EPS": [reported, float("nan")]},
                         index=pd.DatetimeIndex([stamp, stamp + pd.Timedelta(days=90)]))
    return {"history": _history(TODAY - timedelta(days=quarter_days_ago), surprise), "dates": dates}


def _build(rows, evidence=None, done=()):
    return verify.build_outcomes(rows, lambda code: evidence if evidence is not None else _evidence(), done)


def test_corrected_event_date_still_counts_one_quarter_once():
    """推估日從 10/28 改成 10/30：同一季只留最後一份事前報告。"""
    first = _row(event_days_ago=7, created_days_ago=12, report_id=1)
    corrected = _row(event_days_ago=5, created_days_ago=9, expectation="miss", report_id=2)
    result = _build([first, corrected])
    assert [o["report_id"] for o in result["outcomes"]] == [2]
    assert result["outcomes"][0]["expectation"] == "miss" and result["outcomes"][0]["hit"] is False


def test_quarter_already_in_journal_is_not_written_again():
    quarter = (TODAY - timedelta(days=40)).isoformat()
    corrected = _row(event_days_ago=3)
    assert _build([corrected], done={("NVDA", quarter)})["outcomes"] == []
    assert len(_build([corrected], done={("AAPL", quarter)})["outcomes"]) == 1


def test_report_after_actual_announcement_is_not_scored_even_if_estimate_is_later():
    """推估 3 天前、實際 6 天前就公告：4 天前的報告已看到結果。"""
    late = _row(event_days_ago=3, created_days_ago=4)
    outcome = _build([late], _evidence(announced_days_ago=6))["outcomes"][0]
    assert outcome["scorable"] is False and outcome["note"] == "post_announcement"
    assert "hit" not in outcome


def test_last_ex_ante_report_wins_over_post_announcement_one():
    before = _row(event_days_ago=3, created_days_ago=8, report_id=1)
    after = _row(event_days_ago=3, created_days_ago=4, expectation="miss", report_id=2)
    outcome = _build([before, after], _evidence(announced_days_ago=6))["outcomes"][0]
    assert outcome["report_id"] == 1 and outcome["scorable"] is True and outcome["hit"] is True


def test_report_on_announcement_day_is_not_ex_ante():
    same_day = _row(event_days_ago=5, created_days_ago=5)
    same_day["created_at"] += " 12:00:00"
    assert _build([same_day], _evidence(announced_days_ago=5))["outcomes"][0]["scorable"] is False
    day_before = _row(event_days_ago=5, created_days_ago=6)
    assert _build([day_before], _evidence(announced_days_ago=5))["outcomes"][0]["scorable"] is True


def test_unconfirmed_announcement_stays_pending_not_scored():
    row = _row()
    for evidence in (_evidence(reported=9.9), {**_evidence(), "dates": None}, {"history": _evidence()["history"]}):
        result = _build([row], evidence)
        assert result["outcomes"] == [] and result["pending"] == 1


def test_ambiguous_announcement_is_not_guessed():
    evidence = _evidence()
    stamp = evidence["dates"].index[0]
    evidence["dates"] = pd.DataFrame({"Reported EPS": [1.1, 1.1]},
                                     index=pd.DatetimeIndex([stamp, stamp + pd.Timedelta(days=1)]))
    assert _build([_row()], evidence)["pending"] == 1


def test_missing_quarter_row_stays_pending():
    assert _build([_row()], _evidence(quarter_days_ago=110)) == {"outcomes": [], "pending": 1}


def test_non_earnings_and_all_insufficient_do_not_touch_network():
    fetch = Mock()
    rows = [_row(event_type="other"), _row(code="2330.TW", expectation="insufficient_data")]
    assert verify.build_outcomes(rows, fetch) == {"outcomes": [], "pending": 0}
    fetch.assert_not_called()


def test_latest_ex_ante_insufficient_is_recorded_unscored():
    early = _row(created_days_ago=20, report_id=1)
    latest = _row(created_days_ago=8, expectation="insufficient_data", report_id=2)
    outcome = _build([early, latest])["outcomes"][0]
    assert outcome["report_id"] == 2 and outcome["scorable"] is False and outcome["note"] == "insufficient_data"


def test_scored_outcome_compares_against_actual_and_baseline():
    outcome = _build([_row(expectation="miss")])["outcomes"][0]
    assert outcome["actual"] == "beat" and outcome["hit"] is False and outcome["always_beat_hit"] is True
    assert outcome["quarter"] == (TODAY - timedelta(days=40)).isoformat() and outcome["announced_at"]


def test_naive_created_at_is_read_conservatively_as_utc():
    # 公告當地 00:00（紐約）前幾小時，當 UTC 讀已跨過 cutoff：不算事前
    stamp = pd.Timestamp(TODAY - timedelta(days=5)).tz_localize("America/New_York") + pd.Timedelta(hours=16)
    cutoff = stamp.normalize().tz_convert("UTC").tz_localize(None)
    row = _row()
    row["created_at"] = str(cutoff + pd.Timedelta(minutes=1))
    assert _build([row])["outcomes"][0]["scorable"] is False
    row["created_at"] = str(cutoff - pd.Timedelta(minutes=1))
    assert _build([row])["outcomes"][0]["scorable"] is True


def _outcome(code, hit, beat=False):
    return {"code": code, "scorable": True, "hit": hit, "always_beat_hit": beat}


def test_summary_small_sample_is_inconclusive_even_if_perfect():
    summary = verify.summarize([_outcome(f"C{i}", True) for i in range(19)])
    assert summary["hit_rate"] == 1.0 and summary["verdict"] == "inconclusive"


def test_summary_enough_clear_sample_gets_verdict():
    assert verify.summarize([_outcome(f"C{i}", True) for i in range(20)])["verdict"] == "better_than_always_beat"
    assert verify.summarize([_outcome(f"C{i}", False, True) for i in range(20)])["verdict"] == "worse_than_always_beat"


def test_summary_ci_crossing_zero_is_inconclusive():
    rows = [_outcome(f"C{i}", i % 2 == 0, i % 2 == 1) for i in range(40)]
    assert verify.summarize(rows)["verdict"] == "inconclusive"


def test_summary_pure_beat_guesser_matches_baseline_not_better():
    rows = [_outcome(f"C{i}", True, True) for i in range(40)]
    summary = verify.summarize(rows)
    assert summary["hit_rate"] == 1.0 and summary["verdict"] == "inconclusive"


def test_summary_excludes_unscorable_and_empty():
    assert verify.summarize([])["verdict"] == "inconclusive"
    summary = verify.summarize([{"code": "A", "scorable": False}])
    assert summary["n"] == 0 and summary["excluded"] == 1


def test_journal_round_trip(tmp_path):
    path = tmp_path / "o.jsonl"
    verify.append_outcomes([{"code": "A", "event_date": "2026-01-01"}], path)
    verify.append_outcomes([{"code": "B", "event_date": "2026-01-02"}], path)
    assert [r["code"] for r in verify.read_outcomes(path)] == ["A", "B"]
    assert verify.read_outcomes(tmp_path / "none.jsonl") == []
