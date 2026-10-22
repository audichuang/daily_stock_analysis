# -*- coding: utf-8 -*-
"""賣方共識（yfinance）：欄位清洗、狀態閘、fail-open、prompt 區塊與 base.py 接線（全離線）。

假 ticker 的形狀照 2026-10-22 實測 yfinance 1.7.0 對 2330.TW 的回傳。
"""

from __future__ import annotations

import copy
import datetime as dt
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from data_provider import analyst_consensus as ac
from data_provider.base import DataFetcherManager
from data_provider.twse_fundamental_adapter import TwseFundamentalAdapter

TODAY = dt.date(2026, 10, 22)
_TS_FRESH = int(dt.datetime(2026, 10, 21, 5, 30, tzinfo=dt.timezone.utc).timestamp())
_TS_OLD = int(dt.datetime(2026, 10, 10, 5, 30, tzinfo=dt.timezone.utc).timestamp())


def _ticker(n=35, ts=_TS_FRESH, fy1=(148.88, 145.76, 142.96, 136.48), up30=10, down30=1):
    cur, d7, d30, d90 = fy1
    idx = ["0q", "+1q", "0y", "+1y"]
    eps_trend = pd.DataFrame(
        {"current": [33.0, 33.6, 110.37, cur], "7daysAgo": [31.6, 32.7, 108.6, d7],
         "30daysAgo": [31.0, 31.9, 107.85, d30], "90daysAgo": [30.5, 31.7, 106.65, d90]},
        index=idx,
    )
    eps_rev = pd.DataFrame(
        {"upLast7days": [4, 6, 5, 7], "upLast30days": [6, 7, 9, up30],
         "downLast30days": [3, 1, 3, down30], "downLast7Days": [2, 0, 2, 0]},
        index=idx,
    )
    est = pd.DataFrame(
        {"avg": [33.0, 33.6, 110.37, 148.88], "low": [31.9, 30.7, 98.4, 126.5],
         "high": [33.9, 37.2, 113.2, 167.13], "numberOfAnalysts": [21, 19, 35, 36]},
        index=idx,
    )
    recs = pd.DataFrame(
        {"period": ["0m", "-1m", "-2m", "-3m"], "strongBuy": [9, 9, 8, 9], "buy": [25, 25, 24, 25],
         "hold": [1, 1, 1, 1], "sell": [0, 0, 0, 0], "strongSell": [0, 0, 0, 0]}
    )
    info = {
        "currentPrice": 2420.0, "targetMeanPrice": 3390.43, "targetMedianPrice": 3300.0,
        "targetHighPrice": 5000.0, "targetLowPrice": 2650.0, "numberOfAnalystOpinions": n,
        "recommendationKey": "strong_buy", "recommendationMean": 1.31429, "regularMarketTime": ts,
    }
    return SimpleNamespace(info=info, eps_trend=eps_trend, eps_revisions=eps_rev,
                           earnings_estimate=est, recommendations=recs)


@pytest.fixture(autouse=True)
def _fixed_day(monkeypatch):
    monkeypatch.setattr(ac, "_today", lambda: TODAY)
    ac._CACHE.clear()
    yield
    ac._CACHE.clear()


def _fetch(ticker, ref_price=None, code="2330.TW"):
    with patch("yfinance.Ticker", return_value=ticker) as m:
        return ac.fetch_analyst_consensus(code, ref_price=ref_price), m


def test_ok_snapshot_fields():
    c, _ = _fetch(_ticker(), ref_price=2420.0)
    assert c["status"] == "ok"
    assert c["n_analysts"] == 35
    assert c["as_of"] == "2026-10-21"
    assert c["implied_upside_pct"] == pytest.approx(36.4, abs=0.05)
    assert c["eps_fy1_rev_30d_pct"] == pytest.approx(4.14, abs=0.01)
    assert c["eps_fy1_rev_90d_pct"] == pytest.approx(9.09, abs=0.01)
    assert c["eps_fy1_revision_direction"] == "up"
    assert c["eps_fy1_dispersion_pct"] == pytest.approx(27.3, abs=0.1)
    assert c["rec_buy_share_change_3m_pct"] == 0.0


@pytest.mark.parametrize("n,expected", [(1, "thin"), (2, "thin"), (3, "ok"), (17, "ok")])
def test_thin_threshold(n, expected):
    # 門檻放鬆（拿掉）→ n=1 變 ok 紅；門檻過頭（例如 n<20）→ 3017 的 n=17 變 thin 紅
    c, _ = _fetch(_ticker(n=n), ref_price=2420.0)
    assert c["status"] == expected
    if expected == "thin":
        assert "target_median" not in c and "eps_fy1" not in c


def test_zero_base_and_outlier_revision_become_none():
    # 90 天前 EPS=0（5425.TWO 的 inf）與 +106%（3481.TW 基期 1.0）都要清成 None
    c, _ = _fetch(_ticker(fy1=(2.06, 2.0, 1.0, 0.0)))
    assert c["eps_fy1_rev_90d_pct"] is None
    assert c["eps_fy1_rev_30d_pct"] is None


def test_revision_within_cap_is_kept():
    # 反向：+17.5%（3017.TW 90 天）不能被清洗掉
    c, _ = _fetch(_ticker(fy1=(117.5, 117.0, 115.0, 100.0)))
    assert c["eps_fy1_rev_90d_pct"] == pytest.approx(17.5)


def test_no_activity_is_not_stable():
    c, _ = _fetch(_ticker(fy1=(10.0, 10.0, 10.0, 10.0), up30=0, down30=0))
    assert c["eps_fy1_revision_direction"] == "no_activity"


def test_down_direction():
    c, _ = _fetch(_ticker(fy1=(3.66, 4.32, 4.0, 4.1), up30=0, down30=3))
    assert c["eps_fy1_revision_direction"] == "down"


@pytest.mark.parametrize("fy1,up30,down30", [
    ((95.0, 98.0, 100.0, 100.0), 6, 2),   # 上修家數多但 30 天 EPS -5%
    ((105.0, 102.0, 100.0, 100.0), 1, 4),  # 下修家數多但 30 天 EPS +5%
])
def test_count_and_magnitude_disagree_is_mixed(fy1, up30, down30):
    # 家數與幅度方向相反不得標成 up/down（拿掉幅度條件會紅）
    c, _ = _fetch(_ticker(fy1=fy1, up30=up30, down30=down30))
    assert c["eps_fy1_revision_direction"] == "mixed"


def test_stale_by_old_price_date():
    c, _ = _fetch(_ticker(ts=_TS_OLD), ref_price=2420.0)
    assert c["status"] == "stale"


@pytest.mark.parametrize("ref,expected", [(2500.0, "stale"), (2440.0, "ok")])
def test_stale_by_price_gap(ref, expected):
    # 2420 vs 2500 差 3.2% → stale；vs 2440 差 0.8% → ok（門檻過嚴會紅）
    c, _ = _fetch(_ticker(), ref_price=ref)
    assert c["status"] == expected


def test_upside_uses_ref_price():
    c, _ = _fetch(_ticker(), ref_price=2440.0)
    assert c["implied_upside_pct"] == pytest.approx((3300 / 2440 - 1) * 100, abs=0.05)


def test_no_coverage_returns_none():
    t = _ticker()
    t.info = {"currentPrice": 100.0}
    c, _ = _fetch(t)
    assert c is None


def test_exception_fails_open_and_is_not_cached():
    with patch("yfinance.Ticker", side_effect=RuntimeError("boom")):
        assert ac.fetch_analyst_consensus("2330.TW") is None
    c, m = _fetch(_ticker())
    assert c is not None and m.call_count == 1


def test_cached_per_symbol_per_day():
    _fetch(_ticker())
    c, m = _fetch(_ticker())
    assert c["status"] == "ok" and m.call_count == 0


# ---- prompt 區塊 -------------------------------------------------------------

def test_format_ok_block_has_revisions_and_caveat():
    c, _ = _fetch(_ticker(), ref_price=2420.0)
    out = ac.format_analyst_consensus_block(c, "zh-TW")
    assert "賣方共識" in out and "n=35" in out
    assert "上修 10 家、下修 1 家" in out
    assert "次年度" in out and "+1y" not in out
    assert "不得據此提高 confidence" in out
    assert "系統性偏多" in out


def test_format_thin_has_no_numbers():
    c, _ = _fetch(_ticker(n=2))
    out = ac.format_analyst_consensus_block(c, "zh-TW")
    assert "2 位分析師" in out and "3300" not in out


@pytest.mark.parametrize("bad", [None, {}, {"status": "none"}, "x"])
def test_format_invalid_is_empty(bad):
    assert ac.format_analyst_consensus_block(bad, "zh-TW") == ""


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_format_english_has_no_chinese(lang):
    c, _ = _fetch(_ticker())
    out = ac.format_analyst_consensus_block(c, lang)
    assert out and not any("一" <= ch <= "鿿" for ch in out)


def test_format_stale_block_warns_and_ok_does_not():
    stale, _ = _fetch(_ticker(ts=_TS_OLD), ref_price=2420.0)
    assert "數字可能未更新" in ac.format_analyst_consensus_block(stale, "zh-TW")
    ac._CACHE.clear()
    ok, _ = _fetch(_ticker(), ref_price=2420.0)
    assert "數字可能未更新" not in ac.format_analyst_consensus_block(ok, "zh-TW")


def test_prompt_injects_block_only_when_present():
    from tests.test_analyzer_prompt_language import _make_analyzer, _rich_context

    c, _ = _fetch(_ticker())
    ctx = copy.deepcopy(_rich_context())
    ctx.setdefault("fundamental_context", {})["consensus"] = c
    out = _make_analyzer(legacy=True)._format_prompt(ctx, "X", news_context="n", report_language="zh-TW")
    assert "賣方共識" in out
    ctx["fundamental_context"].pop("consensus")
    out = _make_analyzer(legacy=True)._format_prompt(ctx, "X", news_context="n", report_language="zh-TW")
    assert "賣方共識" not in out


# ---- base.py 接線 --------------------------------------------------------------

_EMPTY_BUNDLE = {"status": "not_supported", "growth": {}, "earnings": {}, "belong_boards": [],
                 "source_chain": [], "errors": []}


def _ctx(code, enabled, consensus_ret=None, consensus_exc=None, fetch_timeout=15.0):
    cfg = SimpleNamespace(
        enable_fundamental_pipeline=True, fundamental_cache_ttl_seconds=0,
        fundamental_stage_timeout_seconds=30.0, fundamental_fetch_timeout_seconds=fetch_timeout,
        fundamental_retry_max=1, analyst_consensus_enabled=enabled,
    )
    manager = DataFetcherManager(fetchers=[])
    kw = {"side_effect": consensus_exc} if consensus_exc else {"return_value": consensus_ret}
    with patch("src.config.get_config", return_value=cfg), \
            patch.object(manager, "get_realtime_quote", return_value=SimpleNamespace(price=2420.0)), \
            patch.object(TwseFundamentalAdapter, "get_valuation", return_value={}), \
            patch.object(TwseFundamentalAdapter, "get_growth", return_value={}), \
            patch("data_provider.yfinance_fundamental_adapter.YfinanceFundamentalAdapter.get_fundamental_bundle",
                  return_value=_EMPTY_BUNDLE), \
            patch("data_provider.tw_institutional_fetcher.TwInstitutionalFetcher.get_institutional_net",
                  return_value=None), \
            patch("data_provider.analyst_consensus.fetch_analyst_consensus", **kw) as m:
        return manager.get_fundamental_context(code), m


def test_wiring_enabled_attaches_and_passes_ref_price():
    ctx, m = _ctx("2330.TW", True, {"status": "ok", "n_analysts": 35})
    assert ctx["consensus"]["n_analysts"] == 35
    assert m.call_args.kwargs["ref_price"] == 2420.0
    assert "consensus" not in ctx["coverage"]


def test_wiring_us_also_supported():
    ctx, m = _ctx("AAPL", True, {"status": "ok", "n_analysts": 40})
    assert ctx.get("consensus", {}).get("n_analysts") == 40


def test_wiring_disabled_never_calls():
    ctx, m = _ctx("2330.TW", False, {"status": "ok"})
    assert "consensus" not in ctx and m.call_count == 0


def test_wiring_respects_fetch_timeout_zero():
    # FUNDAMENTAL_FETCH_TIMEOUT_SECONDS=0 代表關閉逐檔抓取，旗標開也不能抓
    ctx, m = _ctx("2330.TW", True, {"status": "ok"}, fetch_timeout=0.0)
    assert "consensus" not in ctx and m.call_count == 0


def test_wiring_exception_fails_open():
    ctx, _ = _ctx("2330.TW", True, consensus_exc=RuntimeError("boom"))
    assert "consensus" not in ctx
    assert ctx["market"] == "tw"


@pytest.mark.parametrize("fy1,up30,down30,pct,direction", [
    ((-1.6, -1.7, -2.0, -2.0), 4, 0, 20.0, "up"),     # 虧損縮小 -2→-1.6 是上修
    ((-2.4, -2.3, -2.0, -2.0), 0, 4, -20.0, "down"),  # 虧損擴大 -2→-2.4 是下修
])
def test_negative_eps_base_keeps_revision_sign(fy1, up30, down30, pct, direction):
    c, _ = _fetch(_ticker(fy1=fy1, up30=up30, down30=down30))
    assert c["eps_fy1_rev_30d_pct"] == pytest.approx(pct)
    assert c["eps_fy1_revision_direction"] == direction
