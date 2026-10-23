# -*- coding: utf-8 -*-
"""search_comprehensive_intel: per-dimension provider fallback and Taiwan FinMind routing."""

import sys
from datetime import date
from unittest.mock import MagicMock, patch

if "newspaper" not in sys.modules:
    sys.modules["newspaper"] = MagicMock()

from src.search_service import FinMindNewsProvider, SearchResponse, SearchResult, SearchService  # noqa: E402


def _ok(name):
    item = SearchResult(
        title=f"鴻海 2317 最新消息 {name}", snippet="鴻海 營收 創高 研報 目標價",
        url=f"https://example.com/{name}", source=name,
        published_date=date.today().isoformat(),
    )
    return SearchResponse(query="q", results=[item], provider=name, success=True)


def _bad(name):
    return SearchResponse(query="q", results=[], provider=name, success=False, error_message="429")


def _provider(name, behavior):
    p = MagicMock()
    p.name = name
    p.is_available = True
    p.search.side_effect = behavior
    return p


def _service(providers, finmind=None):
    service = SearchService(searxng_public_instances_enabled=False, news_max_age_days=3)
    service._providers = providers
    service._finmind_provider = finmind
    return service


def _run(service, code="2317.TW", name="鴻海", max_searches=6):
    with patch("src.search_service.time.sleep"):
        return service.search_comprehensive_intel(code, name, max_searches=max_searches)


def test_failed_provider_hands_over_to_next():
    blocked = _provider("SearXNG", lambda *a, **k: _bad("SearXNG"))
    good = _provider("Good", lambda *a, **k: _ok("Good"))
    results = _run(_service([blocked, good]))
    assert results["market_analysis"].results  # dimension is not lost
    assert all(r.results for r in results.values())


def test_exception_and_empty_hand_over():
    def boom(*a, **k):
        raise RuntimeError("anti-bot")

    empty = _provider("Empty", lambda *a, **k: SearchResponse(query="q", results=[], provider="Empty", success=True))
    good = _provider("Good", lambda *a, **k: _ok("Good"))
    results = _run(_service([_provider("Boom", boom), empty, good]))
    assert all(r.success and r.results for r in results.values())


def test_all_providers_failing_keeps_dimension_as_failure():
    results = _run(_service([_provider("A", lambda *a, **k: _bad("A")), _provider("B", lambda *a, **k: _bad("B"))]))
    assert results and not any(r.results for r in results.values())


def test_taiwan_latest_news_tries_finmind_first_only_there():
    finmind = FinMindNewsProvider(["t"])
    finmind.search = MagicMock(side_effect=lambda *a, **k: _ok("FinMind"))
    good = _provider("Good", lambda *a, **k: _ok("Good"))
    results = _run(_service([good], finmind))
    assert results["latest_news"].results[0].source == "FinMind"
    assert finmind.search.call_count == 1
    assert finmind.search.call_args.kwargs["stock_code"] == "2317.TW"


def test_finmind_empty_falls_back_to_generic():
    finmind = FinMindNewsProvider(["t"])
    finmind.search = MagicMock(side_effect=lambda *a, **k: _bad("FinMind"))
    good = _provider("Good", lambda *a, **k: _ok("Good"))
    results = _run(_service([good], finmind), max_searches=1)
    assert results["latest_news"].results[0].source == "Good"


def test_non_taiwan_never_touches_finmind():
    finmind = FinMindNewsProvider(["t"])
    finmind.search = MagicMock(side_effect=lambda *a, **k: _ok("FinMind"))
    good = _provider("Good", lambda *a, **k: _ok("Good"))
    _run(_service([good], finmind), code="AAPL", name="Apple")
    assert finmind.search.call_count == 0
