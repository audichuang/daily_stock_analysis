# -*- coding: utf-8 -*-
"""Tests for structured ResearchArtifact contract helpers."""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from api.v1.schemas.research_artifact import ResearchArtifact
from src.services.research_artifact_service import artifact_input_from_detail, build_research_artifact


def test_build_research_artifact_from_report_with_evidence_and_invalidation() -> None:
    report = {
        "meta": {
            "id": 12,
            "query_id": "q-12",
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "created_at": "2026-03-19T08:00:00",
        },
        "summary": {
            "analysis_summary": "趋势维持偏强",
            "operation_advice": "持有",
            "action": "hold",
            "action_label": "持有",
            "trend_prediction": "震荡上行",
            "sentiment_score": 72,
        },
        "strategy": {
            "stop_loss": "1680",
            "take_profit": "1880",
        },
        "details": {
            "analysis_context_pack_overview": {
                "subject": {"market": "cn"},
                "blocks": [
                    {
                        "key": "daily_price",
                        "label": "日线行情",
                        "status": "available",
                        "source": "tencent",
                        "warnings": [],
                        "missing_reasons": [],
                    },
                    {
                        "key": "news",
                        "label": "新闻",
                        "status": "partial",
                        "source": "anspire",
                        "warnings": ["partial"],
                        "missing_reasons": [],
                    },
                ],
                "data_quality": {
                    "overall_score": 83,
                    "level": "good",
                    "limitations": ["新闻覆盖有限"],
                },
            },
            "news_content": "公司新闻摘要",
        },
    }

    artifact = ResearchArtifact.model_validate(build_research_artifact(report))

    assert artifact.schema_version == "research-artifact-v1"
    assert artifact.artifact_id == "report:12"
    assert artifact.subject.stock_code == "600519"
    assert artifact.subject.market == "cn"
    assert artifact.thesis.direction == "neutral"
    assert artifact.thesis.action == "hold"
    assert artifact.data_quality.level == "good"
    assert artifact.data_quality.source_count == 3
    assert {item.id for item in artifact.evidence} == {
        "context:daily_price",
        "context:news",
        "news:summary",
    }
    assert artifact.evidence[0].freshness == "unknown"
    assert artifact.evidence[0].quality_level == "good"
    condition_ids = {item.id for item in artifact.invalidation_conditions}
    assert "price:stop_loss" in condition_ids
    assert "data_quality:limitations" in condition_ids
    assert artifact.next_actions[-1].action == "monitor_invalidation"


def test_build_research_artifact_always_includes_invalidation_conditions() -> None:
    artifact = ResearchArtifact.model_validate(build_research_artifact({
        "meta": {"query_id": "q-empty", "stock_code": "AAPL"},
        "summary": {"analysis_summary": "等待更多证据", "sentiment_score": 50},
    }))

    assert artifact.artifact_id == "report:AAPL:q-empty"
    assert artifact.invalidation_conditions[0].id == "manual:thesis_reassessment"
    assert artifact.data_quality.level == "unknown"


def test_research_artifact_requires_invalidation_conditions() -> None:
    with pytest.raises(ValidationError):
        ResearchArtifact.model_validate({
            "artifact_id": "report:bad",
            "subject": {"stock_code": "AAPL"},
            "thesis": {"summary": "missing invalidation"},
            "invalidation_conditions": [],
        })


def test_fallback_artifact_id_is_unique_for_stocks_in_the_same_batch() -> None:
    first = build_research_artifact({
        "meta": {"query_id": "batch-1", "stock_code": "600519"},
        "summary": {"analysis_summary": "first"},
    })
    second = build_research_artifact({
        "meta": {"query_id": "batch-1", "stock_code": "000001"},
        "summary": {"analysis_summary": "second"},
    })

    assert first["artifact_id"] == "report:600519:batch-1"
    assert second["artifact_id"] == "report:000001:batch-1"
    assert first["artifact_id"] != second["artifact_id"]


def test_attribute_report_preserves_falsey_values() -> None:
    report = SimpleNamespace(
        meta=SimpleNamespace(query_id="batch-zero", stock_code="AAPL"),
        summary=SimpleNamespace(
            sentiment_score=0,
            analysis_summary="zero is a real score",
            action="",
        ),
        strategy=SimpleNamespace(),
        details=SimpleNamespace(),
    )

    artifact = ResearchArtifact.model_validate(build_research_artifact(report))

    assert artifact.artifact_id == "report:AAPL:batch-zero"
    assert artifact.thesis.score == 0
    assert artifact.thesis.confidence == 1.0
    assert artifact.thesis.direction == "bearish"
    assert artifact.thesis.action is None


def test_unavailable_context_blocks_do_not_inflate_source_count() -> None:
    artifact = ResearchArtifact.model_validate(build_research_artifact({
        "meta": {"query_id": "missing-only", "stock_code": "AAPL"},
        "summary": {"analysis_summary": "waiting for evidence"},
        "details": {
            "analysis_context_pack_overview": {
                "blocks": [
                    {"key": "daily_price", "status": "missing"},
                    {"key": "news", "status": "fetch_failed"},
                ],
            },
            "empty_news_disclosure": "News evidence is unavailable.",
        },
    }))

    assert artifact.data_quality.source_count == 0
    assert {item.id for item in artifact.evidence} == {
        "context:daily_price",
        "context:news",
        "news:summary",
    }


def test_market_structure_ok_is_healthy_evidence() -> None:
    artifact = ResearchArtifact.model_validate(build_research_artifact({
        "meta": {"query_id": "market-ok", "stock_code": "600519"},
        "summary": {"analysis_summary": "market structure available"},
        "details": {"market_structure": {"status": "ok"}},
    }))

    market_evidence = next(item for item in artifact.evidence if item.id == "market:structure")
    assert market_evidence.freshness == "unknown"
    assert market_evidence.quality_level == "good"
    assert artifact.data_quality.source_count == 1
    assert artifact.data_quality.level == "good"


@pytest.mark.parametrize("status", ["available", "fallback", "partial", "estimated", "ok", "missing"])
def test_availability_and_retrieval_time_do_not_claim_freshness(status: str) -> None:
    report = {
        "meta": {"stock_code": "AAPL", "created_at": "2026-10-02T12:00:00Z"},
        "details": {"analysis_context_pack_overview": {"blocks": [{
            "key": "quote", "status": status,
            "timestamp": "2026-10-02T12:00:00Z", "fetched_at": "2026-10-02T12:00:00Z",
        }]}},
    }
    evidence = build_research_artifact(report)["evidence"][0]
    assert evidence["freshness"] == "unknown"
    assert "as_of" not in evidence
    assert evidence["metadata"]["fetched_at"] == "2026-10-02T12:00:00Z"
    assert evidence["metadata"]["context_timestamp"] == "2026-10-02T12:00:00Z"


@pytest.mark.parametrize("camel_case", [False, True])
def test_evidence_keeps_observation_and_retrieval_times_separate(camel_case: bool) -> None:
    block = {
        "key": "quote", "status": "stale", "source": "recorded-provider",
        "providerTimestamp" if camel_case else "provider_timestamp": "2026-09-01T08:00:00+08:00",
        "fetchedAt" if camel_case else "fetched_at": "2026-10-02T12:00:00Z",
    }
    artifact = build_research_artifact({
        "meta": {"stock_code": "AAPL"},
        "details": {"analysis_context_pack_overview": {"blocks": [block]}},
    })
    evidence = artifact["evidence"][0]
    assert evidence["as_of"] == "2026-09-01T08:00:00+08:00"
    assert evidence["metadata"]["fetched_at"] == "2026-10-02T12:00:00Z"
    assert evidence["freshness"] == "stale"
    assert artifact["data_quality"]["stale_count"] == 1
    assert "as_of" not in block


def test_invalid_evidence_timestamps_are_omitted() -> None:
    artifact = build_research_artifact({
        "meta": {"stock_code": "AAPL"},
        "details": {"analysis_context_pack_overview": {"blocks": [{
            "key": "quote", "status": "available", "provider_timestamp": "not-a-time",
            "timestamp": "2026-10-02", "fetched_at": 123,
        }]}},
    })
    evidence = artifact["evidence"][0]
    assert "as_of" not in evidence
    assert "context_timestamp" not in evidence["metadata"]
    assert "fetched_at" not in evidence["metadata"]
    assert evidence["freshness"] == "unknown"


def _stop_loss_description(language) -> str:
    report = {
        "meta": {"stock_code": "AAPL", "report_language": language},
        "strategy": {"stop_loss": "180"},
    }
    conditions = build_research_artifact(report)["invalidation_conditions"]
    return next(item["description"] for item in conditions if item["id"] == "price:stop_loss")


@pytest.mark.parametrize(
    "language,expected",
    [
        ("zh-TW", "股價跌破報告的停損區：180"),
        ("zh", "价格跌破报告停损区：180"),
        ("en", "Price breaks the report stop-loss area: 180"),
        ("ko", "가격이 보고서의 손절 구간을 이탈: 180"),
    ],
)
def test_invalidation_text_follows_report_language(language, expected) -> None:
    assert _stop_loss_description(language) == expected


def test_invalidation_text_without_language_stays_english() -> None:
    # 舊報告沒存語言：維持既有英文，iOS 的對照表才接得住。
    assert _stop_loss_description(None).startswith("Price breaks")


def test_zh_tw_artifact_has_no_english_template_sentences() -> None:
    artifact = build_research_artifact({
        "meta": {"stock_code": "2330.TW", "report_language": "zh-TW"},
        "summary": {"analysis_summary": "論點", "action": "reduce", "action_label": "減碼"},
        "strategy": {"stop_loss": "900", "take_profit": "1100"},
        "details": {
            "news_content": "新聞",
            "financial_report": {"revenue": 1},
            "dividend_metrics": {"ttm": 1},
            "market_structure": {"status": "ok"},
        },
    })
    rendered = [item["description"] for item in artifact["invalidation_conditions"]]
    rendered += [item["title"] for item in artifact["evidence"]]
    rendered += [item["label"] for item in artifact["next_actions"]]
    for text in rendered:
        assert not any("a" <= ch.lower() <= "z" for ch in text), text


def test_artifact_input_from_detail_reads_language_from_raw_result() -> None:
    artifact_input = artifact_input_from_detail({
        "id": 7,
        "stock_code": "2330.TW",
        "raw_result": {"report_language": "zh-TW"},
    })
    assert artifact_input["meta"]["report_language"] == "zh-TW"


def _us_report(evidence, status=None, **details):
    return {
        "meta": {"stock_code": "AAPL", "report_language": "zh-TW"},
        "summary": {"analysis_summary": "論點", "one_sentence": "一句話", "exit_triggers": ["跌破 180"]},
        "strategy": {"stop_loss": "180 元", "stop_loss_price": 180.0, "take_profit": "220", "take_profit_price": 220.0},
        "details": {"us_evidence": evidence, "us_evidence_status": status, **details},
    }


def test_decision_fields_project_onto_thesis() -> None:
    thesis = build_research_artifact(_us_report({}))["thesis"]
    assert thesis["one_sentence"] == "一句話"
    assert thesis["exit_triggers"] == ["跌破 180"]


def test_sec_link_only_allows_https_sec_gov() -> None:
    artifact = build_research_artifact(_us_report({"sec_filings": {"recent_8k": [
        {"date": "2026-10-01", "items": "2.02", "url": "https://www.sec.gov/a.htm", "excerpt": "摘錄"},
        {"date": "2026-10-02", "items": "8.01", "url": "http://www.sec.gov/b.htm"},
        {"date": "2026-10-03", "items": "8.01", "url": "https://sec.gov.evil.example/c.htm"},
        {"date": "2026-10-04", "items": "8.01", "url": "javascript:alert(1)"},
    ]}}))
    by_id = {item["id"]: item for item in artifact["evidence"]}
    assert by_id["sec:8k:1"]["url"] == "https://www.sec.gov/a.htm"
    assert by_id["sec:8k:1"]["excerpt"] == "摘錄"
    assert by_id["sec:8k:1"]["counts_toward_score"] is False
    for index in (2, 3, 4):
        assert "url" not in by_id[f"sec:8k:{index}"]


def test_projected_evidence_keys_survive_camelcase() -> None:
    artifact = build_research_artifact(_us_report({
        "insider_90d": {"window_days": 90, "as_of": "2026-10-01", "buy_shares": 1, "sell_shares": 2, "net_shares": -1},
        "ratings_30d": {"window_days": 30, "count": 1, "entries": [{"date": "2026-10-01", "firm": "A"}]},
        "estimates": {"revisions": {"up_7d": 1, "down_30d": 2}, "eps": {"avg": 1.5, "year_ago": 1.0}},
    }))
    by_id = {item["id"]: item for item in artifact["evidence"]}
    assert by_id["insider:recent"]["window_days"] == 90
    assert by_id["insider:recent"]["facts"]["net_shares"] == -1
    assert by_id["estimates:next_quarter"]["facts"]["revisions"] == {"up_week": 1, "down_month": 2}

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                assert not any(left.isdigit() and right.isalpha() for left, right in zip(key, key[1:])), key
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk([item.get("facts") for item in artifact["evidence"]])
    assert not any("90d" in item["id"] for item in artifact["evidence"])


def test_source_status_keeps_known_codes_and_drops_unknown() -> None:
    artifact = build_research_artifact(_us_report(
        {},
        status={"sec_finra": "not_configured", "insider": "timeout", "futu": "weird"},
    ))
    assert artifact["source_status"] == {"sec_finra": "not_configured", "insider": "timeout"}


@pytest.mark.parametrize(
    "price,stop_status,take_status",
    [(170.0, "triggered", "pending"), (200.0, "pending", "pending"), (230.0, "pending", "triggered"), (None, "pending", "pending")],
)
def test_price_conditions_trigger_only_from_facts(price, stop_status, take_status) -> None:
    conditions = {
        item["id"]: item
        for item in build_research_artifact(_us_report({}, analysis_price=price))["invalidation_conditions"]
    }
    assert conditions["price:stop_loss"]["direction"] == "below"
    assert conditions["price:stop_loss"]["status"] == stop_status
    assert conditions["price:take_profit_review"]["direction"] == "above"
    assert conditions["price:take_profit_review"]["status"] == take_status


def test_price_condition_without_structured_level_stays_pending() -> None:
    # 舊報告只有文字價位：不解析句子，也不判定觸發。
    report = _us_report({}, analysis_price=100.0)
    report["strategy"] = {"stop_loss": "180 元"}
    conditions = build_research_artifact(report)["invalidation_conditions"]
    assert next(item for item in conditions if item["id"] == "price:stop_loss")["status"] == "pending"


@pytest.mark.parametrize("broken,status", [(True, "triggered"), (False, "pending"), (None, "pending")])
def test_event_gap_is_projected_and_low_break_follows_fact(broken, status) -> None:
    event = {"triggered": True, "event_date": "2026-10-30", "change_pct": -28.58, "event_low": 60.5}
    if broken is not None:
        event["event_low_broken"] = broken
    artifact = build_research_artifact(_us_report({}, event_gap=event))
    assert artifact["event_gap"]["event_date"] == "2026-10-30"
    condition = next(item for item in artifact["invalidation_conditions"] if item["id"] == "event:low_break")
    assert condition["status"] == status
    assert condition["description"] == "收盤跌破事件日低點：60.5"


def test_evidence_source_status_codes() -> None:
    from data_provider.base import DataFetcherManager as Manager

    assert Manager._evidence_source_status({"a": 1}, None) == "ok"
    assert Manager._evidence_source_status({"a": 1}, "x timeout") == "ok"
    assert Manager._evidence_source_status(None, "us_evidence_ratings timeout") == "timeout"
    assert Manager._evidence_source_status(None, "boom") == "fetch_failed"
    assert Manager._evidence_source_status({}, None) == "no_data"


def test_artifact_input_reads_evidence_status_from_snapshot() -> None:
    artifact_input = artifact_input_from_detail({
        "stock_code": "AAPL",
        "sniper_prices": {"stop_loss": 180.0, "take_profit": None},
        "raw_result": {"dashboard": {"event_gap": {"event_low": 1.0}}},
        "context_snapshot": {"enhanced_context": {
            "realtime": {"price": 170.0},
            "fundamental_context": {"as_of": "T", "us_evidence": {"a": 1}, "us_evidence_status": {"futu": "ok"}},
        }},
    })
    assert artifact_input["details"]["us_evidence_status"] == {"futu": "ok"}
    assert artifact_input["details"]["analysis_price"] == 170.0
    assert artifact_input["details"]["event_gap"] == {"event_low": 1.0}
    assert artifact_input["strategy"]["stop_loss_price"] == 180.0
