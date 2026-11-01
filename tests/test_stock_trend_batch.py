# -*- coding: utf-8 -*-
"""批次當日走勢 /stocks/intraday-trends 與 StockService.get_intraday_trends（mock，無網路／無真登入）。"""

import pytest
from fastapi import HTTPException

from api.v1.endpoints import stocks as stocks_endpoint
from src.services import stock_service as stock_service_module
from src.services.stock_service import StockService


@pytest.fixture(autouse=True)
def _clear_cache():
    stock_service_module._INTRADAY_TREND_CACHE.clear()
    yield
    stock_service_module._INTRADAY_TREND_CACHE.clear()


def _count_calls(monkeypatch, result=None):
    calls = []

    def fake(self, code, range_):
        calls.append((code, range_))
        return (result if result is not None else [{"t": "2026-11-02T09:00:00+08:00", "price": 100.0}]), "shioaji"

    monkeypatch.setattr(StockService, "get_price_trend", fake)
    return calls


def test_second_call_within_ttl_does_not_refetch(monkeypatch):
    calls = _count_calls(monkeypatch)
    StockService().get_intraday_trends(["2330.TW", "2317.TW"])
    StockService().get_intraday_trends(["2330.TW", "2317.TW"])
    assert sorted(calls) == [("2317.TW", "day"), ("2330.TW", "day")]


def test_refetches_after_ttl_expires(monkeypatch):
    # 反向：快取不能變成永遠不更新
    calls = _count_calls(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr(stock_service_module.time, "monotonic", lambda: clock[0])
    StockService().get_intraday_trends(["2330.TW"])
    clock[0] += stock_service_module._INTRADAY_TREND_TTL_S - 1
    StockService().get_intraday_trends(["2330.TW"])
    assert len(calls) == 1
    clock[0] += 2
    StockService().get_intraday_trends(["2330.TW"])
    assert len(calls) == 2


def test_cache_key_ignores_case(monkeypatch):
    calls = _count_calls(monkeypatch)
    StockService().get_intraday_trends(["2330.tw"])
    rows = StockService().get_intraday_trends(["2330.TW"])
    assert len(calls) == 1
    assert rows[0]["stock_code"] == "2330.TW"  # 回應代碼跟著這次的請求


def test_single_failure_returns_empty_without_failing_the_batch(monkeypatch):
    def fake(self, code, range_):
        if code == "2317.TW":
            raise RuntimeError("quota")
        return [{"t": "2026-11-02T09:00:00+08:00", "price": 100.0}], "shioaji"

    monkeypatch.setattr(StockService, "get_price_trend", fake)
    rows = StockService().get_intraday_trends(["2330.TW", "2317.TW"])
    assert [r["stock_code"] for r in rows] == ["2330.TW", "2317.TW"]
    assert rows[0]["points"] and rows[0]["error"] is None
    assert rows[1]["points"] == [] and rows[1]["error"] == "unavailable"


def test_failures_are_cached_too(monkeypatch):
    # 撞配額時最不該每 30 秒重打
    calls = []

    def fake(self, code, range_):
        calls.append(code)
        raise RuntimeError("quota")

    monkeypatch.setattr(StockService, "get_price_trend", fake)
    StockService().get_intraday_trends(["2330.TW"])
    StockService().get_intraday_trends(["2330.TW"])
    assert calls == ["2330.TW"]


def test_empty_points_report_no_data(monkeypatch):
    _count_calls(monkeypatch, result=[])
    assert StockService().get_intraday_trends(["2330.TW"])[0]["error"] == "no_data"


def test_sampling_caps_points_and_keeps_the_last_one(monkeypatch):
    points = [{"t": str(i), "price": float(i)} for i in range(270)]
    _count_calls(monkeypatch, result=points)
    sampled = StockService().get_intraday_trends(["2330.TW"])[0]["points"]
    assert len(sampled) == stock_service_module._INTRADAY_TREND_MAX_POINTS
    assert sampled[0]["price"] == 0.0
    assert sampled[-1]["price"] == 269.0


def test_short_series_is_not_resampled(monkeypatch):
    points = [{"t": str(i), "price": float(i)} for i in range(5)]
    _count_calls(monkeypatch, result=points)
    assert StockService().get_intraday_trends(["2330.TW"])[0]["points"] == points


def test_endpoint_maps_rows_and_dedupes(monkeypatch):
    _count_calls(monkeypatch)
    resp = stocks_endpoint.get_intraday_trends(codes="2330.TW, 2330.TW,AAPL")
    assert [i.stock_code for i in resp.items] == ["2330.TW", "AAPL"]
    assert resp.items[0].points[0].price == 100.0
    assert resp.items[0].source_code == "shioaji"


def test_endpoint_limit_counts_raw_input_before_dedupe(monkeypatch):
    _count_calls(monkeypatch)
    limit = stocks_endpoint.MAX_BATCH_CODES
    stocks_endpoint.get_intraday_trends(codes=",".join(["2330.TW"] * limit))
    with pytest.raises(HTTPException) as exc:
        stocks_endpoint.get_intraday_trends(codes=",".join(["2330.TW"] * (limit + 1)))
    assert exc.value.status_code == 400


def test_endpoint_rejects_empty_codes():
    with pytest.raises(HTTPException) as exc:
        stocks_endpoint.get_intraday_trends(codes=" , ")
    assert exc.value.status_code == 400
