# -*- coding: utf-8 -*-
"""Prompt data labels: volume-ratio basis, preliminary institutional data, local-first valuation."""

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider import base as dp_base  # noqa: E402
from data_provider import twse_fundamental_adapter as tfa  # noqa: E402
from data_provider.realtime_types import RealtimeSource  # noqa: E402
from src.analyzer import GeminiAnalyzer  # noqa: E402
from src.core.pipeline import StockAnalysisPipeline  # noqa: E402


def _pipeline():
    p = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    p.config = SimpleNamespace(report_language="zh-TW")
    p.search_service = SimpleNamespace(news_window_days=3)
    return p


def _quote(source=RealtimeSource.SHIOAJI, vr=1.31):
    return SimpleNamespace(code="2330.TW", name="台積電", price=1000.0, volume_ratio=vr, source=source)


def _enhance(code, db_vr, quote, trend_vr=None, db_date=None, phase=None, ctx_phase=None):
    """db_vr is the (possibly T-1) DB row ratio; trend_vr is trend_result.volume_ratio_5d (quote-session based)."""
    today = {"close": 1000.0, **({"volume_ratio": db_vr} if db_vr is not None else {})}
    if db_date:
        today["date"] = db_date
    trend = MagicMock(volume_ratio_5d=trend_vr, ma5=0) if trend_vr is not None else None
    from src.core.trading_calendar import MarketPhase
    with patch("src.core.pipeline.infer_market_phase", return_value=phase or MarketPhase.POSTMARKET):
        return _pipeline()._enhance_context({"code": code, "today": today}, quote, None, trend,
                                            fundamental_context={},
                                            market_phase_context=ctx_phase)["realtime"]


def _prompt(realtime, institution=None, valuation=None, code="2330.TW"):
    fc = {}
    if institution:
        fc["institution"] = {"status": "ok", "data": institution}
    if valuation:
        fc["valuation"] = {"data": valuation}
    ctx = {
        "code": code, "stock_name": "測試", "date": "2026-10-22",
        "today": {"close": 100.0, "ma5": 1, "ma10": 1, "ma20": 1},
        "realtime": realtime, "fundamental_context": fc,
    }
    return GeminiAnalyzer.__new__(GeminiAnalyzer)._format_prompt(ctx, "測試", report_language="zh-TW")


# --- (1) volume ratio basis ---------------------------------------------------
def test_tw_volume_ratio_uses_5d_basis_and_keeps_shioaji_as_vs_prev():
    rt = _enhance("2330.TW", 9.9, _quote(), trend_vr=0.75)
    assert rt["volume_ratio"] == 0.75
    assert rt["volume_ratio_desc"] == "明显萎缩"
    assert rt["volume_ratio_vs_prev"] == 1.31
    assert rt["volume_ratio_basis"] == "avg5"


def test_tw_intraday_volume_ratio_is_labelled_not_judged():
    from src.core.trading_calendar import MarketPhase
    rt = _enhance("2330.TW", 1.0, _quote(), trend_vr=0.4, phase=MarketPhase.INTRADAY)
    assert rt["volume_ratio_basis"] == "avg5_intraday"
    assert "缩量" not in rt["volume_ratio_desc"].replace("不据此判断缩量", "")
    assert "萎缩" not in rt["volume_ratio_desc"]
    p = _prompt(rt)
    assert "盤中累計、未按時間換算" in p
    post = _enhance("2330.TW", 1.0, _quote(), trend_vr=0.4)
    assert post["volume_ratio_basis"] == "avg5" and post["volume_ratio_desc"] == "极度萎缩"


def test_tw_volume_ratio_basis_intraday_if_either_context_or_wall_clock_says_so():
    from src.core.trading_calendar import MarketPhase as MP
    # context intraday, clock postmarket -> intraday
    rt = _enhance("2330.TW", 1.0, _quote(), trend_vr=0.4, phase=MP.POSTMARKET, ctx_phase={"phase": "intraday"})
    assert rt["volume_ratio_basis"] == "avg5_intraday"
    # context postmarket, clock intraday -> intraday (clock still wins when it says intraday)
    rt = _enhance("2330.TW", 1.0, _quote(), trend_vr=0.4, phase=MP.INTRADAY, ctx_phase={"phase": MP.POSTMARKET})
    assert rt["volume_ratio_basis"] == "avg5_intraday"
    # context premarket, clock 09:01 intraday -> intraday
    rt = _enhance("2330.TW", 1.0, _quote(), trend_vr=0.4, phase=MP.INTRADAY, ctx_phase={"phase": "premarket"})
    assert rt["volume_ratio_basis"] == "avg5_intraday"
    # reverse: both postmarket -> plain 5-day basis
    rt = _enhance("2330.TW", 1.0, _quote(), trend_vr=0.4, phase=MP.POSTMARKET, ctx_phase={"phase": "postmarket"})
    assert rt["volume_ratio_basis"] == "avg5" and rt["volume_ratio_desc"] == "极度萎缩"


def test_tw_volume_ratio_ignores_t_minus_1_db_row():
    # DB row is T-1 (ratio 2.4) while the quote is T; the headline ratio must come from the T-based trend series.
    q = _quote()
    q.provider_timestamp = "2026-10-23T10:00"
    rt = _enhance("2330.TW", 2.4, q, trend_vr=0.4, db_date="2026-10-22")
    assert rt["volume_ratio"] == 0.4
    assert rt["volume_ratio_desc"] != "明显放量"


def test_tw_without_5d_ratio_drops_misleading_shioaji_value_from_main_field():
    rt = _enhance("2330.TW", 2.4, _quote())  # no trend_result: never fall back to the DB row
    assert "volume_ratio" not in rt
    assert rt["volume_ratio_vs_prev"] == 1.31


def test_non_tw_volume_ratio_unchanged():
    rt = _enhance("AAPL", 0.75, _quote(vr=1.31))
    assert rt["volume_ratio"] == 1.31
    assert "volume_ratio_vs_prev" not in rt and "volume_ratio_basis" not in rt


def test_prompt_labels_both_ratios():
    rt = {"price": 1.0, "volume_ratio": 0.75, "volume_ratio_desc": "明显萎缩",
          "volume_ratio_vs_prev": 1.31, "volume_ratio_basis": "avg5"}
    p = _prompt(rt)
    assert "量比（對5日均量）" in p and "| **0.75** |" in p
    assert "較昨量（當日累計量／昨量，非5日均量口徑） | 1.31" in p


def test_english_prompt_has_no_cjk_in_volume_ratio_label():
    rt = {"price": 1.0, "volume_ratio": 0.75, "volume_ratio_desc": "x", "volume_ratio_basis": "avg5"}
    ctx = {"code": "2330.TW", "stock_name": "T", "date": "2026-10-22",
           "today": {"close": 100.0, "ma5": 1, "ma10": 1, "ma20": 1}, "realtime": rt}
    p = GeminiAnalyzer.__new__(GeminiAnalyzer)._format_prompt(ctx, "T", report_language="en")
    line = next(ln for ln in p.splitlines() if "Volume Ratio" in ln)
    assert "(vs 5-day avg volume)" in line and "均量" not in line


# --- (2) preliminary institutional data ----------------------------------------
def test_inst_is_preliminary_only_for_today_taipei():
    from zoneinfo import ZoneInfo
    today = datetime.datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")
    assert dp_base._tw_inst_is_preliminary(today) is True
    assert dp_base._tw_inst_is_preliminary("20200101") is False
    assert dp_base._tw_inst_is_preliminary(None) is False


def test_prompt_marks_preliminary_institution_only_when_flagged():
    inst = {"foreign_net": 1, "trust_net": 2, "dealer_net": 3, "total_net": 6, "date": "20261022", "source": "t"}
    with patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""):
        assert "初版，投信常於隔夜修正" in _prompt({"price": 1.0}, {**inst, "is_preliminary": True})
        assert "初版" not in _prompt({"price": 1.0}, {**inst, "is_preliminary": False})
        assert "初版" not in _prompt({"price": 1.0}, inst)


# --- (3) local-first valuation -------------------------------------------------
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _lazy_db_url(monkeypatch):
    # get_engine() only builds a lazy engine; latest_valuation itself is always patched in these tests.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/x")

def _row(days_ago, pe=20.5):
    d = tfa._today() - datetime.timedelta(days=days_ago)
    return {"date": d, "pe_ratio": pe, "pb_ratio": 5.0, "dividend_yield": 1.2}


def test_valuation_prefers_fresh_local_row_with_as_of():
    a = tfa.TwseFundamentalAdapter()
    with patch("market_data.market_repo.latest_valuation", return_value=_row(0)):
        v = a.get_valuation("2330.TW")
    assert v["pe_ratio"] == 20.5 and v["as_of"] == tfa._today().isoformat()


def test_valuation_stale_or_missing_local_falls_back_to_api():
    a = tfa.TwseFundamentalAdapter()
    api = {"2330": {"pe_ratio": 9.9, "pb_ratio": 1.0, "dividend_yield": 2.0, "as_of": "2026-10-21"}}
    a._cached = lambda name, build: api if name == "valuation_twse" else {}
    for local in (_row(30), None):
        with patch("market_data.market_repo.latest_valuation", return_value=local):
            assert a.get_valuation("2330.TW")["pe_ratio"] == 9.9
    with patch("market_data.market_repo.latest_valuation", side_effect=RuntimeError("db down")):
        assert a.get_valuation("2330.TW")["pe_ratio"] == 9.9


def test_valuation_older_local_loses_to_newer_api_and_fills_gaps():
    a = tfa.TwseFundamentalAdapter()
    api_asof = (tfa._today() - datetime.timedelta(days=1)).isoformat()
    api = {"2330": {"pe_ratio": 9.9, "pb_ratio": 1.0, "dividend_yield": 2.0, "as_of": api_asof}}
    a._cached = lambda name, build: api if name == "valuation_twse" else {}
    with patch("market_data.market_repo.latest_valuation", return_value=_row(5)):
        assert a.get_valuation("2330.TW")["as_of"] == api_asof
    # same-day local wins without touching the API, even with a null yield
    calls = []
    a._cached = lambda name, build: calls.append(name) or api
    with patch("market_data.market_repo.latest_valuation", return_value=_row(0)):
        assert a.get_valuation("2330.TW")["pe_ratio"] == 20.5
    assert calls == []


def test_valuation_newer_local_fills_missing_yield_from_api():
    a = tfa.TwseFundamentalAdapter()
    older = (tfa._today() - datetime.timedelta(days=3)).isoformat()
    api = {"2330": {"pe_ratio": 9.9, "pb_ratio": 1.0, "dividend_yield": 2.0, "as_of": older}}
    a._cached = lambda name, build: api if name == "valuation_twse" else {}
    row = dict(_row(1), dividend_yield=None)
    with patch("market_data.market_repo.latest_valuation", return_value=row):
        v = a.get_valuation("2330.TW")
    # no cross-day gap filling: older values must not be stamped with the newer as_of
    assert v["pe_ratio"] == 20.5 and v["dividend_yield"] is None and v["as_of"] != older


def test_valuation_same_day_rows_fill_gaps():
    a = tfa.TwseFundamentalAdapter()
    day = (tfa._today() - datetime.timedelta(days=1))
    api = {"2330": {"pe_ratio": 9.9, "pb_ratio": 1.0, "dividend_yield": 2.0, "as_of": day.isoformat()}}
    a._cached = lambda name, build: api if name == "valuation_twse" else {}
    row = dict(_row(1), dividend_yield=None)
    with patch("market_data.market_repo.latest_valuation", return_value=row):
        v = a.get_valuation("2330.TW")
    assert v["pe_ratio"] == 20.5 and v["dividend_yield"] == 2.0


def test_valuation_api_row_without_as_of_does_not_crash():
    a = tfa.TwseFundamentalAdapter()
    api = {"2330": {"pe_ratio": 9.9, "pb_ratio": 1.0, "dividend_yield": 2.0, "as_of": None}}
    a._cached = lambda name, build: api if name == "valuation_twse" else {}
    with patch("market_data.market_repo.latest_valuation", return_value=_row(1)):
        v = a.get_valuation("2330.TW")
    assert v["pe_ratio"] == 20.5


def test_market_engine_has_connect_timeout():
    from market_data import db
    captured = {}
    with patch.object(db, "create_engine", side_effect=lambda url, **kw: captured.update(kw)):
        db._engine_for.__wrapped__("postgresql+psycopg://u:p@h/x", 3000)
    assert captured["connect_args"]["connect_timeout"] <= 10
    assert "statement_timeout=3000" in captured["connect_args"]["options"]


def test_manager_marks_institution_is_preliminary():
    from data_provider.base import DataFetcherManager
    from zoneinfo import ZoneInfo
    cfg = SimpleNamespace(enable_fundamental_pipeline=True, fundamental_cache_ttl_seconds=0,
                          fundamental_stage_timeout_seconds=30.0, fundamental_fetch_timeout_seconds=15.0,
                          fundamental_retry_max=1)
    today = datetime.datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")
    bundle = {"status": "not_supported", "growth": {}, "earnings": {}, "belong_boards": [],
              "source_chain": [], "errors": []}

    def flag(date):
        rec = {"stock_code": "2330", "date": date, "source": "TWSE-T86", "unit": "shares",
               "foreign_net": 1, "trust_net": 2, "dealer_net": 3, "total_net": 6}
        m = DataFetcherManager(fetchers=[])
        with patch("src.config.get_config", return_value=cfg), \
                patch.object(m, "get_realtime_quote", return_value=None), \
                patch("data_provider.twse_fundamental_adapter.TwseFundamentalAdapter.get_valuation", return_value={}), \
                patch("data_provider.twse_fundamental_adapter.TwseFundamentalAdapter.get_growth", return_value={}), \
                patch("data_provider.yfinance_fundamental_adapter.YfinanceFundamentalAdapter.get_fundamental_bundle",
                      return_value=bundle), \
                patch("data_provider.tw_institutional_fetcher.TwInstitutionalFetcher.get_institutional_net",
                      return_value=rec):
            return m.get_fundamental_context("2330.TW")["institution"]["data"]["is_preliminary"]

    assert flag(today) is True
    assert flag("20200101") is False
