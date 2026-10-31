"""美股證據：缺值、窗口、預算、純資訊與富途讀數守門。"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
import time

import pandas as pd
import pytest

from tests.litellm_stub import ensure_litellm_stub
ensure_litellm_stub()
from data_provider.yfinance_fundamental_adapter import YfinanceFundamentalAdapter
from data_provider.us_evidence import info_evidence, summarize_activity, format_us_evidence, supplement_realtime
from data_provider.futu_fetcher import FutuFetcher
from data_provider.base import DataFetcherManager
from src.analyzer import AnalysisResult, stabilize_decision_with_structure


def test_info_missing_finite_and_actual_dates():
    future = datetime.now(timezone.utc) + timedelta(days=10)
    past = datetime.now(timezone.utc) - timedelta(days=20)
    evidence = info_evidence({"sharesShort": 0, "shortRatio": 2.5, "shortPercentOfFloat": .12,
                              "heldPercentInstitutions": .9, "heldPercentInsiders": float("nan"),
                              "earningsTimestamp": future.timestamp(), "dateShortInterest": past.timestamp()})
    assert evidence["short_interest"] == {"shares_short": 0, "days_to_cover": 2.5, "float_pct": 12.0, "as_of": past.date().isoformat()}
    assert evidence["institutions_pct"] == 90
    assert "insiders_pct" not in evidence
    assert evidence["next_earnings_at"] == future.isoformat()
    assert info_evidence({"earningsTimestamp": past.timestamp()}) == {}
    assert info_evidence({}) == {}


def test_activity_windows_and_unknown_transactions():
    now = datetime.now(timezone.utc)
    frame = pd.DataFrame({"Start Date": [now - timedelta(days=d) for d in [2, 89, 91, -1, 1]],
                          "Text": ["Purchase at price", "Sale at price", "Purchase", "Sale", "Stock Gift"],
                          "Shares": [100, 25, 9999, 8888, 500]})
    result = summarize_activity(frame, "insider", now=now)
    assert result["net_shares"] == 75
    assert result["classified_count"] == 2
    assert result["excluded_count"] == 1
    assert summarize_activity(frame.iloc[4:], "insider", now=now) == {}
    ratings = pd.DataFrame({"Firm": ["a", "b", "c"], "Action": ["up", "down", "up"], "ToGrade": ["buy", "sell", "buy"]},
                           index=[now - timedelta(days=d) for d in [1, 31, -1]])
    result = summarize_activity(ratings, "ratings", now=now)
    assert result["count"] == 1
    assert result["entries"][0]["firm"] == "a"


def test_us_only_and_forward_pe_without_quote_info():
    ticker = Mock()
    ticker.get_info.return_value = {"forwardPE": 16, "sharesShort": 123}
    ticker.quarterly_income_stmt = pd.DataFrame()
    ticker.quarterly_cashflow = pd.DataFrame()
    ticker.dividends = pd.Series(dtype=float)
    with patch("yfinance.Ticker", return_value=ticker):
        us = YfinanceFundamentalAdapter().get_fundamental_bundle("INTC")
        assert us["valuation"]["forward_pe"] == 16
        assert us["us_evidence"]["short_interest"]["shares_short"] == 123
        assert "as_of" not in us["us_evidence"]["short_interest"]
        tw = YfinanceFundamentalAdapter().get_fundamental_bundle("2330.TW")
        assert "us_evidence" not in tw
        assert "forward_pe" not in tw["valuation"]
    assert "預期本益比" in format_us_evidence({"valuation": {"data": us["valuation"]}, "us_evidence": us["us_evidence"]})


def test_futu_daily_flow_distribution_snapshot(monkeypatch):
    import futu as ft
    fetcher = FutuFetcher()
    ctx = Mock()
    fetcher._ctx = ctx
    monkeypatch.setattr(fetcher, "_get_ctx", lambda: ctx)
    monkeypatch.setattr(fetcher, "has_configured_endpoint", lambda: True)
    dates = pd.bdate_range(end=pd.Timestamp.now(tz="UTC").date(), periods=7)
    ctx.get_capital_flow.return_value = (0, pd.DataFrame({"capital_flow_item_time": dates[::-1], "in_flow": range(7), "main_in_flow": ["N/A", *range(6)]}))
    ctx.get_capital_distribution.return_value = (0, pd.DataFrame([{"capital_in_big": 10, "capital_out_big": float("nan"), "update_time": dates[-1].isoformat()}]))
    ctx.get_market_snapshot.return_value = (0, pd.DataFrame([{"volume_ratio": 2, "turnover_rate": 1.5, "pe_ratio": 999, "pe_ttm_ratio": 888}]))
    result = fetcher.get_us_evidence("INTC", deadline=time.monotonic() + 30)
    ctx.get_capital_flow.assert_called_once_with("US.INTC", period_type=ft.PeriodType.DAY)
    assert len(result["daily_flow"]) == 5
    assert result["daily_flow"][-1]["date"] == dates[-1].date().isoformat()
    assert "main_in_flow" not in result["daily_flow"][-1]
    assert "capital_out_big" not in result["distribution"]
    assert result["snapshot"] == {"volume_ratio": 2, "turnover_rate": 1.5}
    ctx.set_sync_query_connect_timeout.assert_called()
    context = {"realtime": {"volume_ratio": 5, "turnover_rate": None}, "fundamental_context": {"us_evidence": {"futu": result}}}
    supplement_realtime(context)
    assert context["realtime"] == {"volume_ratio": 5, "turnover_rate": 1.5}
    text = format_us_evidence(context["fundamental_context"])
    assert "僅正常交易時段、未經回測、不計入評分" in text


def test_futu_disconnected_fast_failure(monkeypatch):
    fetcher = FutuFetcher()
    monkeypatch.setattr(fetcher, "has_configured_endpoint", lambda: True)
    connect = Mock(side_effect=ConnectionRefusedError)
    monkeypatch.setattr("data_provider.futu_fetcher.socket.create_connection", connect)
    get_ctx = Mock()
    monkeypatch.setattr(fetcher, "_get_ctx", get_ctx)
    assert fetcher.get_us_evidence("INTC", deadline=time.monotonic() + 30) == {}
    assert connect.call_args.kwargs["timeout"] <= 1
    get_ctx.assert_not_called()


@pytest.mark.parametrize("decision", ["buy", "sell", "hold"])
def test_futu_does_not_change_decision_stability(decision):
    base = {"capital_flow": {"status": "not_supported", "data": {}}}
    with_futu = deepcopy(base)
    with_futu["us_evidence"] = {"futu": {"daily_flow": [{"in_flow": -900000000, "main_in_flow": -800000000}]}}
    result = AnalysisResult("INTC", "Intel", 80, "bullish", "buy", decision_type=decision, action=decision, current_price=10)
    first, second = deepcopy(result), deepcopy(result)
    # 真實結構穩定器，保留相同技術輸入與不同純資訊。
    trend = {"ma5": 11, "ma10": 12, "ma20": 13, "support_levels": [9], "resistance_levels": [10.1]}
    stabilize_decision_with_structure(first, trend, base)
    stabilize_decision_with_structure(second, trend, with_futu)
    assert first.to_dict() == second.to_dict()
    if decision == "buy":
        polluted = {"capital_flow": {"status": "ok", "data": {"stock_flow": {"main_net_inflow": -900000000}}}}
        negative_control = deepcopy(result)
        stabilize_decision_with_structure(negative_control, trend, polluted)
        assert first.to_dict() != negative_control.to_dict()


def _manager(monkeypatch, *, stage=60, fetch=30):
    cfg = SimpleNamespace(enable_fundamental_pipeline=True, fundamental_cache_ttl_seconds=0,
                          fundamental_stage_timeout_seconds=stage, fundamental_fetch_timeout_seconds=fetch,
                          fundamental_retry_max=1, analyst_consensus_enabled=False)
    monkeypatch.setattr("src.config.get_config", lambda: cfg)
    manager = DataFetcherManager(fetchers=[])
    monkeypatch.setattr(manager, "get_realtime_quote", lambda *a, **kw: None)
    monkeypatch.setattr(manager._yfinance_fundamental_adapter, "get_fundamental_bundle", lambda code: {
        "valuation": {"forward_pe": 18}, "us_evidence": {"short_interest": {"shares_short": 123}},
    })
    return manager


def test_independent_requests_keep_info_and_other_evidence(monkeypatch):
    manager = _manager(monkeypatch)
    calls = []

    def activity(code, kind):
        calls.append(kind)
        if kind == "insider":
            raise ValueError("missing transaction table")
        return {"count": 1}

    monkeypatch.setattr(manager._yfinance_fundamental_adapter, "get_us_activity_evidence", activity)
    monkeypatch.setattr(FutuFetcher, "has_configured_endpoint", lambda: True)
    futu = Mock()
    futu.get_us_evidence.return_value = {"daily_flow": [{"main_in_flow": -1234}]}
    manager._us_futu_fetcher = futu
    context = manager.get_fundamental_context("INTC")
    assert calls == ["insider", "ratings"]
    assert context["valuation"]["data"]["forward_pe"] == 18
    assert context["us_evidence"]["short_interest"]["shares_short"] == 123
    assert "insider_90d" not in context["us_evidence"]
    assert context["us_evidence"]["ratings_30d"] == {"count": 1}
    assert context["us_evidence"]["futu"] == futu.get_us_evidence.return_value
    assert context["capital_flow"]["status"] == "not_supported"
    assert context["capital_flow"]["data"] == {}
    assert futu.get_us_evidence.call_args.kwargs["deadline"] <= time.monotonic() + 30
    manager.close()
    futu.close.assert_called_once()


def test_disabled_futu_does_not_request(monkeypatch):
    manager = _manager(monkeypatch)
    monkeypatch.setattr(manager._yfinance_fundamental_adapter, "get_us_activity_evidence", lambda *a: {})
    monkeypatch.setattr(FutuFetcher, "has_configured_endpoint", lambda: False)
    call = Mock(side_effect=AssertionError("must not contact OpenD"))
    monkeypatch.setattr(FutuFetcher, "get_us_evidence", call)
    context = manager.get_fundamental_context("INTC")
    assert "futu" not in context["us_evidence"]
    call.assert_not_called()


def test_activity_requests_obey_remaining_stage_budget(monkeypatch):
    manager = _manager(monkeypatch, stage=.05, fetch=.05)
    monotonic = time.monotonic
    started = monotonic()
    # 阻塞情境就是本測試要守的 timeout，不使用會受負載影響的即時 mock 預算。
    from threading import Event
    release = Event()
    completed = Event()
    def activity(*args):
        release.wait(30)
        completed.set()
        return {"count": 1}
    call = Mock(side_effect=activity)
    monkeypatch.setattr(manager._yfinance_fundamental_adapter, "get_us_activity_evidence", call)
    monkeypatch.setattr(FutuFetcher, "has_configured_endpoint", lambda: True)
    futu = Mock()
    manager._us_futu_fetcher = futu
    try:
        context = manager.get_fundamental_context("INTC")
        assert monotonic() - started < 2
        assert context["us_evidence"]["short_interest"]["shares_short"] == 123
        assert "insider_90d" not in context["us_evidence"]
        assert call.call_count == 1
        futu.get_us_evidence.assert_not_called()
    finally:
        release.set()
        assert completed.wait(30)


@pytest.mark.parametrize("existing_ratio", [None, 5])
def test_real_legacy_enrichment_supplements_only_missing_fields(existing_ratio):
    from src.core.pipeline import StockAnalysisPipeline
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(report_language="zh-TW")
    pipeline.search_service = None
    context = {"code": "INTC", "today": {}}
    fundamental = {"us_evidence": {"futu": {"snapshot": {"volume_ratio": 2, "turnover_rate": 1.5}}}}
    quote = SimpleNamespace(volume_ratio=existing_ratio, turnover_rate=None, price=10)
    enriched = pipeline._enhance_context(context, quote, None, None, "Intel", fundamental)
    assert enriched["realtime"]["volume_ratio"] == (5 if existing_ratio is not None else 2)
    assert enriched["realtime"]["turnover_rate"] == 1.5
    expected_desc = pipeline._describe_volume_ratio(5) if existing_ratio is not None else ""
    assert enriched["realtime"]["volume_ratio_desc"] == expected_desc
