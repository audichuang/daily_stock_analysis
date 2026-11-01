# -*- coding: utf-8 -*-
"""B17a／B17b／B17c：行情 API 的來源代碼與快取、分時量與均價、profile 追加區塊。"""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import data_provider.shioaji_fetcher as sf
from api.v1.endpoints import stocks as stocks_endpoint
from api.v1.schemas.stocks import StockProfileChips, StockProfilePosition
from src.core.trading_calendar import MarketPhase
from src.services.stock_profile_service import StockProfileService
from src.services.stock_service import StockService, normalize_source_code


@pytest.fixture(autouse=True)
def _clear_indices_cache():
    stocks_endpoint._INDICES_CACHE.clear()
    yield
    stocks_endpoint._INDICES_CACHE.clear()


def _manager(rows):
    manager = MagicMock()
    manager.get_main_indices.return_value = rows
    return patch("data_provider.base.DataFetcherManager", return_value=manager), manager


# --- B17a ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("yfinance(intraday,可能延迟)", "yfinance"),
        ("yfinance(daily)", "yfinance"),
        ("fallback", "yfinance"),
        ("shioaji", "shioaji"),
        (None, None),
    ],
)
def test_normalize_source_code(raw, expected) -> None:
    assert normalize_source_code(raw) == expected


def test_indices_cached_within_ttl_and_refetched_after() -> None:
    patcher, manager = _manager([{"code": "TWII", "name": "加權", "current": 1.0, "source": "shioaji"}])
    clock = MagicMock()
    clock.monotonic.side_effect = [100.0, 159.0, 161.0]
    with patcher, patch.object(stocks_endpoint, "time", clock):
        stocks_endpoint.get_main_indices(region="tw")
        stocks_endpoint.get_main_indices(region="tw")
        assert manager.get_main_indices.call_count == 1
        stocks_endpoint.get_main_indices(region="tw")
        assert manager.get_main_indices.call_count == 2


def test_indices_empty_result_is_not_cached() -> None:
    patcher, manager = _manager([])
    with patcher:
        stocks_endpoint.get_main_indices(region="tw")
        stocks_endpoint.get_main_indices(region="tw")
    assert manager.get_main_indices.call_count == 2


def test_indices_cache_is_per_region_and_unknown_region_not_cached() -> None:
    patcher, manager = _manager([{"code": "X", "name": "x", "current": 1.0}])
    with patcher:
        stocks_endpoint.get_main_indices(region="tw")
        stocks_endpoint.get_main_indices(region="us")
        stocks_endpoint.get_main_indices(region="xx")
    assert manager.get_main_indices.call_count == 3
    assert set(stocks_endpoint._INDICES_CACHE) == {"tw", "us"}


def test_indices_us_names_and_source_code_keep_old_source() -> None:
    patcher, _ = _manager(
        [{"code": "SPX", "name": "标普500指数", "current": 1.0, "source": "yfinance", "as_of": "2026-10-30"}]
    )
    with patcher:
        body = stocks_endpoint.get_main_indices(region="us")
    item = body["items"][0]
    assert item["name"] == "標普 500"
    assert item["source"] == "yfinance"
    assert item["source_code"] == "yfinance"
    assert item["as_of"] == "2026-10-30"


def test_indices_non_finite_becomes_null() -> None:
    patcher, _ = _manager([{"code": "SPX", "name": "x", "current": 1.0, "change": float("nan")}])
    with patcher:
        item = stocks_endpoint.get_main_indices(region="us")["items"][0]
    assert item["change"] is None
    assert item["current"] == 1.0


@pytest.mark.parametrize(
    ("phase", "expected_open"),
    [
        (MarketPhase.INTRADAY, True),
        (MarketPhase.LUNCH_BREAK, True),
        (MarketPhase.POSTMARKET, False),
        (MarketPhase.NON_TRADING, False),
        (MarketPhase.UNKNOWN, None),
    ],
)
def test_indices_market_status(phase, expected_open) -> None:
    patcher, _ = _manager([])
    with patcher, patch("src.core.trading_calendar.infer_market_phase", return_value=phase):
        body = stocks_endpoint.get_main_indices(region="tw")
    assert body["market_phase"] == phase.value
    assert body["market_open"] is expected_open


def test_indices_market_status_not_frozen_by_cache() -> None:
    patcher, _ = _manager([{"code": "TWII", "name": "x", "current": 1.0}])
    with patcher, patch(
        "src.core.trading_calendar.infer_market_phase",
        side_effect=[MarketPhase.INTRADAY, MarketPhase.POSTMARKET],
    ):
        assert stocks_endpoint.get_main_indices(region="tw")["market_open"] is True
        assert stocks_endpoint.get_main_indices(region="tw")["market_open"] is False


# --- B17b ---------------------------------------------------------------------


def _taipei_ns(hour: int, minute: int) -> int:
    return int(dt.datetime(2026, 6, 24, hour, minute, tzinfo=dt.timezone.utc).timestamp() * 1e9)


def _kbars_api(payload):
    api = MagicMock()
    api.kbars.return_value = payload
    return api


def test_day_trend_adds_volume_in_shares_and_running_vwap(monkeypatch) -> None:
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setattr(sf, "_lookup_contract", lambda api, fn: object())
    monkeypatch.setattr(
        sf,
        "_ensure_session",
        # 故意亂序：量要跟著 ts 一起排
        lambda: _kbars_api(
            {"ts": [_taipei_ns(9, 1), _taipei_ns(9, 0)], "Close": [110.0, 100.0], "Volume": [3, 1]}
        ),
    )
    points = sf.shioaji_trend("2330.TW", "day")
    assert [p["volume"] for p in points] == [1000, 3000]
    assert points[0]["avg_price"] == 100.0
    assert points[1]["avg_price"] == 107.5
    assert sf.last_trend_skip_reason() == ""


def test_day_trend_without_volume_omits_fields(monkeypatch) -> None:
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setattr(sf, "_lookup_contract", lambda api, fn: object())
    monkeypatch.setattr(
        sf, "_ensure_session", lambda: _kbars_api({"ts": [_taipei_ns(9, 0)], "Close": [100.0]})
    )
    assert set(sf.shioaji_trend("2330.TW", "day")[0]) == {"t", "price"}


def test_month_trend_sums_daily_volume(monkeypatch) -> None:
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setattr(sf, "_lookup_contract", lambda api, fn: object())
    monkeypatch.setattr(
        sf,
        "_ensure_session",
        lambda: _kbars_api(
            {"ts": [_taipei_ns(9, 0), _taipei_ns(13, 30)], "Close": [100.0, 110.0], "Volume": [1, 2]}
        ),
    )
    assert sf.shioaji_trend("2330.TW", "month") == [{"t": "2026-06-24", "price": 110.0, "volume": 3000}]


@pytest.mark.parametrize(
    ("session", "contract", "payload", "expected"),
    [
        (None, None, None, "no_session"),
        (MagicMock(), None, None, "no_contract"),
        (MagicMock(), object(), {"ts": [], "Close": []}, "no_bars"),
    ],
)
def test_trend_skip_reason(monkeypatch, session, contract, payload, expected) -> None:
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setattr(sf, "_lookup_contract", lambda api, fn: contract)
    if session is not None and payload is not None:
        session.kbars.return_value = payload
    monkeypatch.setattr(sf, "_ensure_session", lambda: session)
    assert sf.shioaji_trend("2330.TW", "day") is None
    assert sf.last_trend_skip_reason() == expected


def test_trend_skip_reason_kbars_failure(monkeypatch) -> None:
    api = MagicMock()
    api.kbars.side_effect = TimeoutError()
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setattr(sf, "_lookup_contract", lambda a, fn: object())
    monkeypatch.setattr(sf, "_ensure_session", lambda: api)
    assert sf.shioaji_trend("2330.TW", "day") is None
    assert sf.last_trend_skip_reason() == "kbars_failed:TimeoutError"


def test_year_is_expected_degrade_without_warning(monkeypatch, caplog) -> None:
    monkeypatch.setattr(StockService, "get_history_data", lambda self, *a, **k: {"data": []})
    service = StockService()
    with caplog.at_level("WARNING"):
        service.get_price_trend("2330.TW", "year")
    assert service.last_trend_degraded_reason == "range_unsupported"
    assert "降级" not in caplog.text


def test_unexpected_degrade_is_warned_and_exposed(monkeypatch, caplog) -> None:
    monkeypatch.setattr(sf, "shioaji_trend", lambda code, rng: None)
    monkeypatch.setattr(sf, "last_trend_skip_reason", lambda: "no_session")
    monkeypatch.setattr(StockService, "_intraday_trend", staticmethod(lambda code: []))
    service = StockService()
    with caplog.at_level("WARNING"):
        _, source = service.get_price_trend("2330.TW", "day")
    assert source == "yfinance(intraday,可能延迟)"
    assert service.last_trend_degraded_reason == "no_session"
    assert "no_session" in caplog.text


def test_non_tw_has_no_degraded_reason(monkeypatch) -> None:
    monkeypatch.setattr(sf, "shioaji_trend", lambda code, rng: None)
    monkeypatch.setattr(StockService, "_intraday_trend", staticmethod(lambda code: []))
    service = StockService()
    service.get_price_trend("AAPL", "day")
    assert service.last_trend_degraded_reason is None


def test_trend_endpoint_appends_fields_and_keeps_source(monkeypatch) -> None:
    def fake(self, code, rng):
        self.last_trend_degraded_reason = "no_session"
        return (
            [{"t": "2026-06-24T09:00:00+08:00", "price": 100.0, "volume": 1000, "avg_price": 100.0}],
            "yfinance(intraday,可能延迟)",
        )

    monkeypatch.setattr(stocks_endpoint.StockService, "get_price_trend", fake)
    resp = stocks_endpoint.get_stock_trend(stock_code="2330.TW", range="day")
    assert resp.source == "yfinance(intraday,可能延迟)"
    assert resp.source_code == "yfinance"
    assert resp.degraded_reason == "no_session"
    assert resp.points[0].volume == 1000
    assert resp.points[0].avg_price == 100.0


# --- 成交量口徑 -----------------------------------------------------------------

_TPE = dt.timezone(dt.timedelta(hours=8))


def _same_session_blocks():
    quote = {
        "status": "fresh",
        "data": {"volume": 36_620_000.0, "amount": 9.0, "as_of": "2026-10-30T13:30:00+08:00"},
        "limitations": [],
    }
    history = {"data": [{"date": "2026-10-30", "volume": 29_595_000.0, "amount": 8.0}]}
    return quote, history


def _align(quote, history, *, market="tw", hour=15):
    return StockProfileService._with_official_session_volume(
        quote, history, market=market, now=dt.datetime(2026, 10, 30, hour, 0, tzinfo=_TPE)
    )


def test_post_close_quote_volume_aligns_with_daily_bar() -> None:
    quote, history = _same_session_blocks()
    merged = _align(quote, history)
    assert merged["data"]["volume"] == 29_595_000.0
    assert merged["data"]["amount"] == 8.0
    assert quote["data"]["volume"] == 36_620_000.0  # 不改到傳入的物件


def test_intraday_keeps_live_volume() -> None:
    quote, history = _same_session_blocks()
    assert _align(quote, history, hour=10)["data"]["volume"] == 36_620_000.0


def test_other_session_bar_does_not_override() -> None:
    quote, history = _same_session_blocks()
    history["data"][0]["date"] = "2026-10-29"
    assert _align(quote, history)["data"]["volume"] == 36_620_000.0


def test_non_tw_market_is_left_alone() -> None:
    quote, history = _same_session_blocks()
    assert _align(quote, history, market="us")["data"]["volume"] == 36_620_000.0


# --- B17c ---------------------------------------------------------------------


def _profile_service() -> StockProfileService:
    return StockProfileService(
        stock_service=MagicMock(),
        history_service=MagicMock(),
        intelligence_service=MagicMock(),
        portfolio_repository=MagicMock(),
        alert_service=MagicMock(),
    )


def _snapshot(*, fx_missing=False, aggregate=1000.0):
    return {
        "total_market_value": 2000.0,
        "fx_missing": fx_missing,
        "accounts": [
            {
                "total_market_value": 1000.0,
                "total_market_value_aggregate": aggregate,
                "positions": [
                    {
                        "symbol": "2330",
                        "market": "tw",
                        "currency": "TWD",
                        "quantity": 10.0,
                        "total_cost": 1000.0,
                        "last_price": 90.0,
                        "market_value_base": 900.0,
                        "price_available": True,
                    },
                    {"symbol": "AAPL", "market": "us", "currency": "USD", "quantity": 1.0, "total_cost": 1.0},
                ],
            }
        ],
    }


def _position(snapshot, quote_price=120.0):
    quote = {"data": {"current_price": quote_price}}
    with patch("src.services.portfolio_service.PortfolioService") as service_cls:
        service_cls.return_value.get_portfolio_snapshot.return_value = snapshot
        result = _profile_service()._position_block("2330.TW", market="tw", quote=quote)
    return result, service_cls


def test_position_uses_live_quote_for_pnl_and_is_read_only() -> None:
    result, service_cls = _position(_snapshot())
    service_cls.return_value.get_portfolio_snapshot.assert_called_once_with(
        include_realtime=False, read_only=True
    )
    assert result["quantity"] == 10.0
    assert result["avg_cost"] == 100.0
    assert result["market_value"] == 1200.0
    assert result["unrealized_pnl"] == 200.0
    assert result["unrealized_pnl_pct"] == 20.0
    assert result["weight_pct"] == 45.0  # 900 / 2000
    StockProfilePosition(**result)


def test_position_weight_null_when_fx_missing() -> None:
    assert _position(_snapshot(fx_missing=True))[0]["weight_pct"] is None
    assert _position(_snapshot(aggregate=None))[0]["weight_pct"] is None


def test_position_none_when_not_found_or_failed() -> None:
    snapshot = _snapshot()
    snapshot["accounts"][0]["positions"] = snapshot["accounts"][0]["positions"][1:]
    assert _position(snapshot)[0] is None
    with patch("src.services.portfolio_service.PortfolioService", side_effect=RuntimeError("db")):
        assert _profile_service()._position_block("2330.TW", market="tw", quote={}) is None


def test_chips_combines_institutional_and_margin_dates() -> None:
    institutional = pd.DataFrame(
        [{"date": "2026-10-30", "foreign_net": 1000, "trust_net": 0, "dealer_net": float("nan"), "total_net": 1000}]
    )
    margin = pd.DataFrame([{"date": "2026-10-29", "margin_balance": 500, "short_balance": 50}])
    with patch("market_data.db.get_engine"), patch(
        "market_data.market_repo.institutional", return_value=institutional
    ), patch("market_data.market_repo.margin", return_value=margin):
        chips = StockProfileService._chips_block("2330.TW")
    assert chips["institutional_date"] == "2026-10-30"
    assert chips["foreign_net"] == 1000.0
    assert chips["trust_net"] == 0.0  # 0 是讀數
    assert chips["dealer_net"] is None  # NaN 不是
    assert chips["margin_date"] == "2026-10-29"
    assert chips["margin_chg_5"] is None
    StockProfileChips(**chips)


def test_chips_none_when_db_fails_or_empty() -> None:
    with patch("market_data.db.get_engine", side_effect=RuntimeError("no db")):
        assert StockProfileService._chips_block("2330.TW") is None
    with patch("market_data.db.get_engine"), patch(
        "market_data.market_repo.institutional", return_value=pd.DataFrame()
    ), patch("market_data.market_repo.margin", return_value=pd.DataFrame()):
        assert StockProfileService._chips_block("2330.TW") is None


def test_news_block_reads_latest_report_only_for_this_analysis() -> None:
    service = _profile_service()
    service.history_service.resolve_and_get_news.return_value = [
        {"title": "t", "url": "u", "source": "s", "published_date": "2026-10-30", "snippet": "x"}
    ]
    items = service._news_block({"data": {"latest_report": {"id": 7}}})
    service.history_service.resolve_and_get_news.assert_called_once_with("7", limit=10, analysis_only=True)
    assert items == [{"title": "t", "url": "u", "source": "s", "published_date": "2026-10-30"}]


def test_news_block_null_without_report() -> None:
    assert _profile_service()._news_block({"data": {"latest_report": None}}) is None
