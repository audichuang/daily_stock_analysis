"""報告新聞的顯示契約；只用記憶體替身，不連正式庫。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient as FastAPITestClient

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from api.deps import get_database_manager
from api.v1.endpoints.history import router
from src.services.history_service import HistoryService


def news(**overrides):
    values = dict(title="公司公告", snippet="一般摘要", url="https://example.test/news",
                  source="官方網站", published_date=datetime.now() - timedelta(days=1),
                  dimension="announcements", code="AAPL")
    return SimpleNamespace(**(values | overrides))


def database(records):
    db = MagicMock()
    db.get_analysis_history_by_id.return_value = SimpleNamespace(query_id="analysis-7", code="AAPL")
    db.get_news_intel_by_query_id.return_value = records
    return db


def test_news_strips_internal_note_before_truncation_and_preserves_prose():
    note = "【DeepSeek 搜尋日期未經原文核實；日級日期非精確發布時間】"
    db = database([news(title=note + "公司公告", snippet=note + "摘要" * 150, source=note + "官方網站")])
    item = HistoryService(db).get_news_intel("analysis-7")[0]
    assert item["title"] == "公司公告"
    assert item["snippet"] == "摘要" * 98 + "摘..."
    assert item["source"] == "官方網站"
    assert item["dimension"] == "announcements"
    assert item["published_date"] == db.get_news_intel_by_query_id.return_value[0].published_date.isoformat()


def test_news_preserves_missing_metadata_and_ordinary_brackets():
    db = database([news(snippet="【公司公告】營收改善", source=None, published_date=None, dimension=None)])
    item = HistoryService(db).get_news_intel("analysis-7")[0]
    assert item["snippet"] == "【公司公告】營收改善"
    assert item["source"] is None
    assert item["published_date"] is None
    assert item["dimension"] is None


def test_analysis_only_uses_same_symbol_and_never_time_window_fallback():
    db = database([])
    service = HistoryService(db)
    service._fallback_news_by_analysis_context = MagicMock(return_value=[news()])
    assert service.resolve_and_get_news("7", analysis_only=True) == []
    db.get_news_intel_by_query_id.assert_called_once_with(query_id="analysis-7", limit=20, code="AAPL")
    service._fallback_news_by_analysis_context.assert_not_called()
    assert len(service.resolve_and_get_news("7")) == 1
    service._fallback_news_by_analysis_context.assert_called_once()


def test_news_http_contract_is_additive_and_forwards_analysis_only():
    db = database([news()])
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/history")
    app.dependency_overrides[get_database_manager] = lambda: db
    with FastAPITestClient(app) as client:
        response = client.get("/api/v1/history/7/news?analysis_only=true&limit=100")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert set(item) == {"title", "snippet", "url", "source", "published_date", "dimension"}
        assert item["dimension"] == "announcements"
        assert response.json()["total"] == 1
        db.get_news_intel_by_query_id.assert_called_once_with(query_id="analysis-7", limit=100, code="AAPL")
        db.reset_mock()
        assert client.get("/api/v1/history/7/news").status_code == 200
        db.get_news_intel_by_query_id.assert_called_once_with(query_id="analysis-7", limit=20)
