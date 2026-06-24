# -*- coding: utf-8 -*-
"""价格走势 endpoint /stocks/{code}/trend 与 StockService.get_price_trend（mock，无网络/无真登入）。"""

import data_provider.shioaji_fetcher as sf
from api.v1.endpoints import stocks as stocks_endpoint
from src.services.stock_service import StockService


def test_trend_endpoint_maps_points_and_source(monkeypatch):
    monkeypatch.setattr(
        stocks_endpoint.StockService,
        "get_price_trend",
        lambda self, code, rng: (
            [{"t": "2026-06-01", "price": 100.0}, {"t": "2026-06-02", "price": 101.5}],
            "shioaji",
        ),
    )
    resp = stocks_endpoint.get_stock_trend(stock_code="2330.TW", range="month")
    assert resp.stock_code == "2330.TW"
    assert resp.range == "month"
    assert resp.source == "shioaji"
    assert len(resp.points) == 2
    assert resp.points[1].price == 101.5


def test_get_price_trend_prefers_shioaji(monkeypatch):
    monkeypatch.setattr(sf, "shioaji_trend", lambda code, rng: [{"t": "2026-06-24T01:00:00+00:00", "price": 999.0}])
    points, source = StockService().get_price_trend("2330.TW", "day")
    assert source == "shioaji"
    assert points[0]["price"] == 999.0


def test_get_price_trend_month_falls_back_to_daily_history(monkeypatch):
    monkeypatch.setattr(sf, "shioaji_trend", lambda code, rng: None)  # Shioaji 不可用 -> yfinance
    captured = {}

    def fake_history(self, stock_code, period="daily", days=30):
        captured["days"] = days
        return {"data": [
            {"date": "2026-06-01", "close": 100.0},
            {"date": "2026-06-02", "close": None},   # 缺值跳过
            {"date": "2026-06-03", "close": 102.0},
        ]}

    monkeypatch.setattr(StockService, "get_history_data", fake_history)
    points, source = StockService().get_price_trend("2330.TW", "month")
    assert captured["days"] == 30
    assert [p["price"] for p in points] == [100.0, 102.0]  # None 被过滤
    assert source.startswith("yfinance")


def test_get_price_trend_year_uses_365_days(monkeypatch):
    monkeypatch.setattr(sf, "shioaji_trend", lambda code, rng: None)
    captured = {}
    monkeypatch.setattr(
        StockService, "get_history_data",
        lambda self, stock_code, period="daily", days=30: captured.update(days=days) or {"data": []},
    )
    points, source = StockService().get_price_trend("2330.TW", "year")
    assert captured["days"] == 365


def test_get_price_trend_history_failure_returns_empty(monkeypatch):
    monkeypatch.setattr(sf, "shioaji_trend", lambda code, rng: None)

    def boom(self, stock_code, period="daily", days=30):
        raise RuntimeError("source down")

    monkeypatch.setattr(StockService, "get_history_data", boom)
    points, source = StockService().get_price_trend("2330.TW", "month")
    assert points == []


def test_shioaji_trend_year_returns_none_due_to_30day_cap(monkeypatch):
    # year 超过 kbars 30 天上限 -> shioaji_trend 直接 None（不触发登入）
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    assert sf.shioaji_trend("2330.TW", "year") is None
