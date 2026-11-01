"""DeepSeek 搜尋：獨立金鑰、來源退回、日期與舊輸出守門。"""
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from requests import HTTPError, Response

from tests.litellm_stub import ensure_litellm_stub
ensure_litellm_stub()
from src.config import Config
from src.search_service import DeepSeekSearchProvider, TavilySearchProvider, FinMindNewsProvider, SearchResult, SearchResponse, SearchService
from tests.test_event_gap_decision import _analyzer, _context, _finish

FIXTURES = Path(__file__).parent / "fixtures"


def _ok(provider, code="INTC", name="Intel"):
    return SearchResponse("fixture", [SearchResult(f"{name} {code} earnings revenue outlook", f"{name} {code} analyst report revenue earnings 營收 財報 目標價", "https://example.com/news", "fixture", date.today().isoformat())], provider)


def _http_error(status, text="secret-error-body"):
    response = Response(); response.status_code = status
    return HTTPError(text, response=response)


def _config(env):
    with patch.dict(os.environ, env, clear=True), patch("src.config.setup_env"), patch.object(Config, "_capture_bootstrap_runtime_env_overrides"):
        return Config._load_from_env()


def test_search_key_is_independent_of_model_key_and_hidden_from_ui():
    from src.core.config_registry import WEB_SETTINGS_HIDDEN_FROM_UI, build_schema_response
    old = _config({"DEEPSEEK_API_KEY": "model-only"})
    assert old.deepseek_search_api_keys == []
    search_only = _config({"DEEPSEEK_SEARCH_API_KEYS": "search-only"})
    assert search_only.deepseek_api_keys == []
    assert search_only.litellm_model == _config({}).litellm_model
    new = _config({"DEEPSEEK_SEARCH_API_KEYS": " first , second, , first ", "LITELLM_MODEL": "fixture-model"})
    assert new.deepseek_search_api_keys == ["first", "second", "first"]
    assert new.litellm_model == "fixture-model"
    assert new.has_search_capability_enabled()
    assert "DEEPSEEK_SEARCH_API_KEYS" in WEB_SETTINGS_HIDDEN_FROM_UI
    assert "DEEPSEEK_SEARCH_API_KEYS" not in {f["key"] for c in build_schema_response()["categories"] for f in c["fields"]}
    with patch("src.config.get_config", return_value=old):
        from src.search_service import get_search_service, reset_search_service
        reset_search_service()
        try:
            assert not any(isinstance(p, DeepSeekSearchProvider) for p in get_search_service()._providers)
        finally:
            reset_search_service()
    with patch("src.config.get_config", return_value=new):
        reset_search_service()
        try:
            service = get_search_service()
            assert isinstance(service._providers[0], DeepSeekSearchProvider)
            assert service._constructor_kwargs["deepseek_keys"] == new.deepseek_search_api_keys
        finally:
            reset_search_service()


def test_provider_order_enabled_and_disabled():
    args = {"tavily_keys": ["t"], "bocha_keys": ["b"], "anspire_keys": ["a"], "finmind_tokens": ["f"], "searxng_public_instances_enabled": False}
    old = SearchService(**args)
    assert [p.name for p in old._providers] == ["Anspire", "Bocha", "Tavily"]
    new = SearchService(**args, deepseek_keys=["d"])
    assert [p.name for p in new._providers] == ["DeepSeek", "Tavily", "Anspire", "Bocha"]
    assert [p.name for p in new._stock_news_providers("2330.TW")][:3] == ["FinMind", "DeepSeek", "Tavily"]
    assert [p.name for p in new._stock_news_providers("INTC")][:2] == ["DeepSeek", "Tavily"]


@pytest.mark.parametrize("query", ["台積電 台灣半導體 " * 30, "Intel earnings outlook " * 30, "😀" * 200])
def test_query_unicode_limit_bounds_summary_and_count(monkeypatch, query):
    provider = DeepSeekSearchProvider(["fixture"])
    raw = json.loads((FIXTURES/"deepseek_search_dates.json").read_text())["INTC"][0]
    raw["summary"] = "SUMMARY" * 1000
    raw["snippet"] = "wrong-snippet"
    request = Mock(return_value={"results": [raw]})
    monkeypatch.setattr(provider, "_request_search", request)
    response = provider.search(query, max_results=99, days=3)
    assert response.success
    wire = request.call_args.args[0]
    assert len(wire) <= 128
    assert wire.startswith(query[:4])
    assert f"after:{date.today()-timedelta(days=3)}" in wire
    assert f"before:{date.today()+timedelta(days=1)}" in wire
    assert request.call_args.args[2] == 50
    assert len(response.results[0].snippet) == 1500
    assert "SUMMARY" in response.results[0].snippet
    assert "wrong-snippet" not in response.results[0].snippet
    assert "未經原文核實" in response.results[0].snippet
    assert response.results[0].retrieved_at


def test_operators_preserved_and_empty_query_does_not_request(monkeypatch):
    p = DeepSeekSearchProvider(["fixture"])
    request = Mock(return_value={"results": []}); monkeypatch.setattr(p, "_request_search", request)
    query = "台積電 site:example.com lang:zh after:2026-01-01 before:2026-12-31"
    assert p.search(query).success
    assert request.call_args.args[0] == query
    request.reset_mock()
    assert not p.search(" \n ").success
    request.assert_not_called()


def test_transport_bearer_endpoint_timeout(monkeypatch):
    # 唯一的 requests mock 是 transport 契約；其餘均隔離自家 HTTP 接縫。
    post = Mock(return_value=SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"results": []}))
    monkeypatch.setattr("src.search_service.requests.post", post)
    assert DeepSeekSearchProvider(["fixture"]).search("Intel").success
    assert post.call_args.args[0] == "https://api.deepseek.com/v1/tools/search"
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer fixture"}
    assert post.call_args.kwargs["timeout"] == 10
    assert set(post.call_args.kwargs["json"]) == {"query", "count"}


@pytest.mark.parametrize("status", [401, 402, 429])
def test_key_failures_rotate_without_logging_secrets(monkeypatch, caplog, status):
    monkeypatch.setattr("src.search_service.random.randrange", lambda n: 0)
    p = DeepSeekSearchProvider(["secret-first", "secret-second", "secret-first"])
    request = Mock(side_effect=[_http_error(status, "secret-first Bearer secret-second"), {"results": []}])
    monkeypatch.setattr(p, "_request_search", request)
    response = p.search("Intel")
    assert response.success
    assert [call.args[1] for call in request.call_args_list] == ["secret-first", "secret-second"]
    assert "secret-first" not in caplog.text and "secret-second" not in caplog.text
    assert "secret-" not in caplog.text
    assert "Bearer" not in caplog.text


@pytest.mark.parametrize("error", [_http_error(400), _http_error(500), TimeoutError("secret-first")])
def test_non_key_errors_do_not_rotate_or_leak(monkeypatch, caplog, error):
    p = DeepSeekSearchProvider(["secret-first", "secret-second"])
    request = Mock(side_effect=error); monkeypatch.setattr(p, "_request_search", request)
    response = p.search("Intel")
    assert not response.success and response.error_message == type(error).__name__
    assert request.call_count == 1
    assert "secret-first" not in caplog.text and "secret-error-body" not in caplog.text


@pytest.mark.parametrize("status", [401, 402, 429])
def test_tavily_uses_the_same_safe_key_rotation(monkeypatch, caplog, status):
    monkeypatch.setattr("src.search_service.random.randrange", lambda n: 0)
    p = TavilySearchProvider(["secret-first", "secret-second"])
    request = Mock(side_effect=[_http_error(status, "secret-first Bearer secret-second"), _ok("Tavily")])
    monkeypatch.setattr(p, "_do_search", request)
    assert p.search("Intel").success
    assert [call.args[1] for call in request.call_args_list] == ["secret-first", "secret-second"]
    assert "secret-" not in caplog.text and "Bearer" not in caplog.text


@pytest.mark.parametrize("raw,expected", [
    ("2026-10-28T16:00:00+00:00", "2026-10-29"),
    ("2026-10-27T16:00:00+00:00", "2026-10-28"),
    ("2026-10-29T00:00:00+08:00", "2026-10-29"),
    ("2026-10-29T20:01:00Z", "2026-10-29"),
    ("2026-10-29", "2026-10-29"), (None, None), ("invalid", None)])
def test_dates_only_correct_observed_midnight_encoding(raw, expected):
    # 此處驗固定格式轉換，不是以固定日期當現在的時效 fixture。
    assert DeepSeekSearchProvider._publication_day(raw) == expected


@pytest.mark.parametrize("age,kept", [(2, True), (3, False), (30, False)])
def test_three_day_boundary_is_correct_without_relaxing_window(monkeypatch, age, kept):
    p = DeepSeekSearchProvider(["fixture"])
    raw = json.loads((FIXTURES/"deepseek_search_dates.json").read_text())["INTC"][0]
    source_day = date.today() - timedelta(days=age)
    raw["date"] = (datetime.combine(source_day, datetime.min.time(), timezone(timedelta(hours=8))).astimezone(timezone.utc)).isoformat()
    monkeypatch.setattr(p, "_request_search", lambda *a: {"results": [raw]})
    service = SearchService(searxng_public_instances_enabled=False)
    filtered = service._filter_news_response(p.search("INTC Intel"), search_days=3, max_results=6, log_scope="fixture")
    assert bool(filtered.results) is kept
    if kept:
        assert filtered.results[0].published_date == source_day.isoformat()


@pytest.mark.parametrize("failure", ["empty", "error", "old", "unknown"])
@pytest.mark.parametrize("comprehensive", [False, True])
def test_real_fallback_reaches_tavily(monkeypatch, failure, comprehensive):
    service = SearchService(deepseek_keys=["d"], tavily_keys=["t"], searxng_public_instances_enabled=False)
    deep, tavily = service._providers
    item = {"title": "Intel INTC earnings", "summary": "Intel revenue earnings", "url": "https://example.com/earnings", "date": (date.today()-timedelta(days=30)).isoformat() if failure == "old" else None}
    request = Mock(side_effect=_http_error(402)) if failure == "error" else Mock(return_value={"results": [] if failure == "empty" else [item]})
    monkeypatch.setattr(deep, "_request_search", request)
    search = Mock(side_effect=lambda *a, **kw: _ok("Tavily")); monkeypatch.setattr(tavily, "_do_search", search)
    with patch("src.search_service.time.sleep"):
        response = service.search_comprehensive_intel("INTC", "Intel", max_searches=1)["latest_news"] if comprehensive else service.search_stock_news("INTC", "Intel")
    assert response.success and response.provider == "Tavily"
    assert response.results
    search.assert_called_once()


@pytest.mark.parametrize("code,name", [("INTC", "Intel"), ("2330.TW", "台積電")])
def test_round_robin_is_preserved_with_finmind_only_for_latest(monkeypatch, code, name):
    service = SearchService(deepseek_keys=["d"], tavily_keys=["t"], finmind_tokens=["f"], searxng_public_instances_enabled=False)
    for provider in [*service._providers, service._finmind_provider]:
        monkeypatch.setattr(provider, "search", Mock(side_effect=lambda *a, provider=provider, **kw: _ok(provider.name, code, name)))
    with patch("src.search_service.time.sleep"):
        result = service.search_comprehensive_intel(code, name, max_searches=5)
    assert [r.provider for r in result.values()] == (["FinMind", "DeepSeek", "DeepSeek", "DeepSeek", "DeepSeek"] if code.endswith("TW") else ["DeepSeek", "Tavily", "DeepSeek", "Tavily", "DeepSeek"])
    assert service._finmind_provider.search.call_count == (1 if code.endswith("TW") else 0)


@pytest.mark.parametrize("code,name", [("INTC", "Intel"), ("2330.TW", "台積電")])
def test_disabled_search_prompt_agent_and_result_byte_for_byte(monkeypatch, code, name):
    monkeypatch.delenv("DEEPSEEK_SEARCH_API_KEYS", raising=False)
    baseline = json.loads((FIXTURES/"deepseek_disabled_baseline.json").read_text())["stocks"][code]
    def response(self, query, api_key, max_results, days=7, **kwargs):
        title = "Intel INTC earnings revenue outlook" if "Intel" in query else "台積電 2330 營收 財報 目標價"
        return SearchResponse(query=query, results=[SearchResult(title, "financial results revenue forecast 台積電 營收 財報", "https://example.com/news", "fixture", published_date=date.today().isoformat())], provider=self.name)
    monkeypatch.setattr(TavilySearchProvider, "_do_search", response)
    service = SearchService(tavily_keys=["fixture"], searxng_public_instances_enabled=False)
    assert not any(isinstance(p, DeepSeekSearchProvider) for p in service._providers)
    with patch("src.search_service.time.sleep"):
        result = service.search_comprehensive_intel(code, name, max_searches=5)
    for r in result.values():
        r.search_time=0
        for item in r.results:
            item.retrieved_at="fixture-retrieval"
    normalized = json.loads(json.dumps({k:asdict(v) for k,v in result.items()}, ensure_ascii=False).replace(date.today().isoformat(), "<today>"))
    assert normalized == baseline["results"]
    text = service.format_intel_report(result, name).replace(date.today().isoformat(), "<today>")
    assert text == baseline["text"]
    context = _context(code, change=0)
    for lang, expected in baseline["prompts"].items():
        assert sha256(_analyzer()._format_prompt(context, name, news_context=text, report_language=lang).encode()).hexdigest() == expected
    _, saved, _ = _finish(SimpleNamespace(report_language="zh-TW", event_gap_decision_enabled=False), context, code=code)
    assert saved == baseline["result"]
    from src.agent.executor import AgentExecutor
    agent = AgentExecutor.__new__(AgentExecutor)
    assert agent._build_user_message("Analyze", {"stock_code":code,"report_language":"zh-TW","news_context":text}) == baseline["agent_prompt"]
