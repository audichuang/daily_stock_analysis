# -*- coding: utf-8 -*-
"""批次行情 endpoint /api/v1/stocks/quotes 与单股 endpoint 行情来源字段回归（全 mock，无网络）。"""

import pytest
from fastapi import HTTPException

from api.v1.endpoints import stocks as stocks_endpoint


def _row(code: str) -> dict:
    return {
        "stock_code": code,
        "stock_name": f"股票{code}",
        "current_price": 100.0,
        "change": 1.0,
        "change_percent": 1.0,
        "open": 99.0,
        "high": 101.0,
        "low": 98.0,
        "prev_close": 99.0,
        "volume": 1000,
        "amount": 100000.0,
        "update_time": "2026-06-24T10:00:00",
        "source": "shioaji",
        "as_of": "2026-06-24T10:00:00+08:00",
        "is_stale": False,
    }


def test_batch_maps_quotes_and_marks_missing_as_null(monkeypatch):
    def fake_quotes(self, codes):
        # 第二个代码无数据 -> None
        return [_row(codes[0]), None]

    monkeypatch.setattr(stocks_endpoint.StockService, "get_realtime_quotes", fake_quotes)

    resp = stocks_endpoint.get_stock_quotes(codes="2330.TW,9999.TW")
    assert len(resp.items) == 2
    assert resp.items[0].quote is not None
    assert resp.items[0].quote.source == "shioaji"
    assert resp.items[0].quote.as_of == "2026-06-24T10:00:00+08:00"
    assert resp.items[0].quote.is_stale is False
    # 无数据列用 quote=None + error，绝不用 0.0 哨兵伪装真实价
    assert resp.items[1].quote is None
    assert resp.items[1].error == "no_data"


def test_batch_empty_codes_returns_400(monkeypatch):
    monkeypatch.setattr(stocks_endpoint.StockService, "get_realtime_quotes", lambda self, c: [])
    with pytest.raises(HTTPException) as exc:
        stocks_endpoint.get_stock_quotes(codes="   ,  ,")
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "empty_codes"


def test_batch_too_many_codes_returns_400(monkeypatch):
    monkeypatch.setattr(stocks_endpoint.StockService, "get_realtime_quotes", lambda self, c: [])
    codes = ",".join(f"{i}.TW" for i in range(stocks_endpoint.MAX_BATCH_CODES + 1))
    with pytest.raises(HTTPException) as exc:
        stocks_endpoint.get_stock_quotes(codes=codes)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "too_many_codes"


def test_batch_dedupes_codes_preserving_order(monkeypatch):
    seen_codes = {}

    def fake_quotes(self, codes):
        seen_codes["codes"] = codes
        return [_row(c) for c in codes]

    monkeypatch.setattr(stocks_endpoint.StockService, "get_realtime_quotes", fake_quotes)
    resp = stocks_endpoint.get_stock_quotes(codes="2330.TW, 2317.TW ,2330.TW")
    assert seen_codes["codes"] == ["2330.TW", "2317.TW"]
    assert [i.stock_code for i in resp.items] == ["2330.TW", "2317.TW"]


def test_batch_bad_row_does_not_500_whole_batch(monkeypatch):
    # current_price 缺失 -> StockQuote(**row) 构造失败，应仅该列 error，其余正常
    def fake_quotes(self, codes):
        good = _row(codes[0])
        bad = {"stock_code": codes[1]}  # 缺 required current_price
        return [good, bad]

    monkeypatch.setattr(stocks_endpoint.StockService, "get_realtime_quotes", fake_quotes)
    resp = stocks_endpoint.get_stock_quotes(codes="2330.TW,2317.TW")
    assert resp.items[0].quote is not None
    assert resp.items[1].quote is None
    assert resp.items[1].error  # 有错误说明，而非抛 500


def test_single_quote_endpoint_includes_source_fields(monkeypatch):
    # 闭 adversary 洞 #3：单股 endpoint 也必须带出 source/as_of/is_stale
    monkeypatch.setattr(
        stocks_endpoint.StockService,
        "get_realtime_quote",
        lambda self, code: _row(code),
    )
    quote = stocks_endpoint.get_stock_quote(stock_code="2330.TW")
    assert quote.source == "shioaji"
    assert quote.as_of == "2026-06-24T10:00:00+08:00"
    assert quote.is_stale is False
