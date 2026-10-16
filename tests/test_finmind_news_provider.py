# -*- coding: utf-8 -*-
"""FinMind 台股個股新聞（fork）：濾雜訊、去重、逐天查與快取、token 輪替、只服務台股。"""

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.config import Config  # noqa: E402
from src.search_service import FinMindNewsProvider, SearchService  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_day_cache():
    FinMindNewsProvider._day_cache.clear()
    yield
    FinMindNewsProvider._day_cache.clear()


def _row(title, source="自由財經", hours_ago=2, link="https://example.com/a"):
    stamp = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"date": stamp.strftime("%Y-%m-%d %H:%M:%S"), "stock_id": "2317",
            "link": link, "source": source, "title": title}


ROWS = [
    _row("焦點股》鴻海：揮軍OCP引關注 帶量上漲 - 自由財經", hours_ago=5),
    _row("2317 鴻海 - 再笨再白痴都會賣鴻海 - 股市爆料同學會 - CMoney", source="CMoney", hours_ago=4),
    _row("鴻海(2317) 個股概覽 | 個股 - 股市 - CMoney", source="CMoney", hours_ago=3),
    _row("鴻海9月營收首破兆元！Q3營收創高 - 科技島", source="科技島", hours_ago=1),
    _row("鴻海9月營收首破兆元！Q3營收創高 - 上市櫃 - 旺得富理財網", source="旺得富理財網", hours_ago=1),
]


def _provider_with_rows(rows):
    provider = FinMindNewsProvider(["token-a"])
    provider._fetch_day = MagicMock(side_effect=lambda stock_id, day, cacheable: rows if day == datetime.now(timezone.utc).date().isoformat() else [])
    return provider


def test_filters_forum_posts_and_overview_pages_and_dedupes_reposts():
    response = _provider_with_rows(ROWS).search("q", max_results=10, days=3, stock_code="2317.TW")
    titles = [item.title for item in response.results]
    assert response.success
    assert titles == ["鴻海9月營收首破兆元！Q3營收創高", "焦點股》鴻海：揮軍OCP引關注 帶量上漲"]
    assert all(item.published_date.endswith("+00:00") for item in response.results)


def test_non_taiwan_code_sends_no_request():
    provider = _provider_with_rows(ROWS)
    response = provider.search("q", stock_code="AAPL")
    assert not response.success
    provider._fetch_day.assert_not_called()


def test_queries_one_utc_day_per_request_and_caches_past_days():
    provider = FinMindNewsProvider(["token-a"])
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append(params["start_date"])
        assert "end_date" not in params
        return MagicMock(status_code=200, json=lambda: {"data": []})

    with patch("src.search_service.requests.get", side_effect=fake_get):
        provider.search("q", days=3, stock_code="2317.TW")
        provider.search("q", days=3, stock_code="2317.TW")
    today = datetime.now(timezone.utc).date().isoformat()
    assert len(calls) == 4 + 1  # 第一次 4 個 UTC 日；第二次只重查今天
    assert calls[-1] == today


def test_rotates_tokens_and_retries_on_quota_error():
    provider = FinMindNewsProvider(["token-a", "token-b"])
    seen = []

    def fake_get(url, params, headers, timeout):
        seen.append(headers["Authorization"])
        if headers["Authorization"].endswith("token-a"):
            return MagicMock(status_code=402, text="limit")
        return MagicMock(status_code=200, json=lambda: {"data": []})

    with patch("src.search_service.requests.get", side_effect=fake_get):
        response = provider.search("q", days=1, stock_code="2330.TW")
    assert response.success
    assert seen[:2] == ["Bearer token-a", "Bearer token-b"]


def test_non_quota_error_fails_without_burning_other_tokens():
    provider = FinMindNewsProvider(["token-a", "token-b"])
    with patch("src.search_service.requests.get",
               return_value=MagicMock(status_code=500, text="boom")) as get:
        response = provider.search("q", days=1, stock_code="2330.TW")
    assert not response.success
    assert get.call_count == 1


def test_service_without_tokens_never_uses_finmind():
    service = SearchService()
    assert service._finmind_provider is None
    assert service._stock_news_providers("2317.TW") == []
    assert not service.is_available


def test_service_tries_finmind_first_only_for_taiwan_codes():
    service = SearchService(finmind_tokens=["token-a"])
    assert service.is_available
    assert [p.name for p in service._stock_news_providers("2317.TW")] == ["FinMind"]
    assert service._stock_news_providers("6488.TWO")[0].name == "FinMind"
    assert service._stock_news_providers("AAPL") == []


def test_search_stock_news_returns_finmind_results_for_taiwan_stock():
    service = SearchService(finmind_tokens=["token-a"])
    service._finmind_provider._fetch_day = _provider_with_rows(ROWS)._fetch_day
    response = service.search_stock_news("2317.TW", "鴻海", max_results=5)
    assert response.provider == "FinMind"
    assert response.results
    assert not any("爆料同學會" in item.title or "個股概覽" in item.title for item in response.results)


@patch("src.config.setup_env")
@patch.object(Config, "_parse_litellm_yaml", return_value=[])
@patch.object(Config, "_parse_stock_email_groups", return_value=[])
def test_config_reads_numbered_tokens_in_order(*_mocks):
    env = {"FINMIND_TOKEN_2": "b", "FINMIND_TOKEN_10": "c", "FINMIND_TOKEN_1": "a",
           "FINMIND_TOKEN_3": " ", "FINMIND_TOKEN_COUNT": "3"}
    try:
        with patch.dict(os.environ, env, clear=True):
            assert Config._load_from_env().finmind_tokens == ["a", "b", "c"]
            assert Config._load_from_env().has_search_capability_enabled()
        with patch.dict(os.environ, {}, clear=True):
            assert Config._load_from_env().finmind_tokens == []
    finally:
        Config.reset_instance()
