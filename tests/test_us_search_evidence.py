"""美股新聞來源與金鑰輪替守門。"""
from unittest.mock import Mock

import pytest
from requests import HTTPError, Response
from tavily.errors import ForbiddenError, InvalidAPIKeyError, UsageLimitExceededError

from src.search_service import SearchService


def test_finmind_is_only_available_for_tw():
    service = SearchService.__new__(SearchService)
    service._finmind_provider = Mock()
    service._providers = []
    assert service.is_available
    assert service.is_available_for_stock("2330.TW")
    assert not service.is_available_for_stock("INTC")
    assert not service.is_available_for_stock("0700.HK")
    service._providers = [Mock(is_available=True)]
    assert service.is_available_for_stock("INTC")

from src.search_service import TavilySearchProvider


@pytest.mark.parametrize("topic", [None, "news"])
@pytest.mark.parametrize("error", [ForbiddenError("plan"), InvalidAPIKeyError("auth"), UsageLimitExceededError("quota"), 401, 429, 432, 433])
def test_tavily_switches_key_in_same_search(monkeypatch, topic, error):
    if isinstance(error, int):
        response = Response()
        response.status_code = error
        error = HTTPError(response=response)
    monkeypatch.setattr("src.search_service.random.randrange", lambda n: 0)
    provider = TavilySearchProvider(["first", "second"])
    calls = []

    def search(query, key, max_results, **kwargs):
        calls.append((key, kwargs))
        if key == "first":
            raise error
        from src.search_service import SearchResponse, SearchResult
        return SearchResponse(query, [SearchResult("t", "s", "https://example.com", "x")], "Tavily")

    monkeypatch.setattr(provider, "_do_search", search)
    response = provider.search("INTC", topic=topic)
    assert response.success
    assert [c[0] for c in calls] == ["first", "second"]
    assert response.results[0].retrieved_at
    assert calls[-1][1] == ({"days": 7, "topic": "news"} if topic else {"days": 7})



@pytest.mark.parametrize("topic", [None, "news"])
@pytest.mark.parametrize("error", [RuntimeError("bug"), TimeoutError("slow")])
def test_tavily_other_errors_do_not_retry(monkeypatch, topic, error):
    provider = TavilySearchProvider(["a", "b"])
    search = Mock(side_effect=error)
    monkeypatch.setattr(provider, "_do_search", search)
    assert not provider.search("INTC", topic=topic).success
    assert search.call_count == 1


def test_tavily_random_start_each_key_at_most_once(monkeypatch):
    monkeypatch.setattr("src.search_service.random.randrange", lambda n: 1)
    provider = TavilySearchProvider(["a", "b", "c", "b"])
    search = Mock(side_effect=ForbiddenError("limit"))
    monkeypatch.setattr(provider, "_do_search", search)
    assert not provider.search("INTC").success
    assert [call.args[1] for call in search.call_args_list] == ["b", "c", "a"]


def test_agent_search_tools_skip_unconfigured_market(monkeypatch, caplog):
    from tests.litellm_stub import ensure_litellm_stub
    ensure_litellm_stub()
    from src.agent.tools import search_tools
    from src.agent.news_evidence import activate_news_evidence_scope, get_current_news_evidence, reset_news_evidence_scope
    service = SearchService.__new__(SearchService)
    service._finmind_provider = Mock()
    service._providers = []
    service.search_stock_news = Mock()
    service.search_comprehensive_intel = Mock()
    monkeypatch.setattr(search_tools, "_get_search_service", lambda: service)
    token = activate_news_evidence_scope()
    try:
        for handler in (search_tools._handle_search_stock_news, search_tools._handle_search_comprehensive_intel):
            assert "error" in handler("INTC", "Intel")
        assert get_current_news_evidence().resolve(search_available=service.is_available_for_stock("INTC")) is None
        assert "未配置此市場" in caplog.text
        service.search_stock_news.assert_not_called()
        service.search_comprehensive_intel.assert_not_called()
    finally:
        reset_news_evidence_scope(token)


@pytest.mark.parametrize("topic", [None, "news"])
@pytest.mark.parametrize("error", [ForbiddenError("plan"), InvalidAPIKeyError("auth"), UsageLimitExceededError("quota"), RuntimeError("bug")])
def test_tavily_real_do_search_preserves_error_classification(monkeypatch, topic, error):
    monkeypatch.setattr("src.search_service.random.randrange", lambda n: 0)
    client = Mock()
    client.search.side_effect = [error, {"results": []}]
    constructor = Mock(return_value=client)
    monkeypatch.setattr("tavily.TavilyClient", constructor)
    response = TavilySearchProvider(["a", "b"]).search("INTC", topic=topic)
    retryable = not isinstance(error, RuntimeError)
    assert response.success is retryable
    assert client.search.call_count == (2 if retryable else 1)
