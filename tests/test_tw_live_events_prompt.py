# -*- coding: utf-8 -*-
"""台股個股 prompt 的處置／注意股與事件日曆區塊（全離線）。

fixture 沿用 `tests/fixtures/tw_live/`（2026-10-20 實測）：基準日 10/20、下一個交易日 10/21。
HTTP 一律換掉 `tw_official_http._send`，新鮮度判準走真的 parser，才測得到「凍結回 200」的拒收。
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from market_data import events, health, risk_flags, tw_official_http as http
from src.analyzer import GeminiAnalyzer
from src.services import tw_live_events as live_mod
from tests.test_analyzer_prompt_language import _make_analyzer, _rich_context
from tests.test_tw_events import LM_TPEX, LM_TWT48U, _OutboundBlocked, _bytes, _mops_page, _resp

AS_OF = dt.date(2026, 10, 20)
ROUTES = {
    risk_flags.TWSE_PUNISH_URL: "twse_punish_next_20261021.json",
    risk_flags.TWSE_NOTICE_URL: "twse_notice_20261020.json",
    risk_flags.TPEX_ATTENTION_URL: "tpex_attention_20261020.json",
    risk_flags.TPEX_DISPOSAL_URL: "tpex_disposal_next_20261021.json",
}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    import socket as _socket

    def guard(self, address):
        raise _OutboundBlocked(f"離線測試嘗試連外 {address}")

    monkeypatch.setattr(_socket.socket, "connect", guard)
    monkeypatch.setattr(health, "expected_session", lambda *a, **k: AS_OF)
    live_mod._fetch_cached.cache_clear()
    yield
    live_mod._fetch_cached.cache_clear()


def _install(monkeypatch, overrides=None):
    calls = []
    overrides = overrides or {}

    def fake_send(method, url, **kwargs):
        data = kwargs.get("data") or {}
        calls.append(url)
        if url in overrides:
            return overrides[url]
        if url in ROUTES:
            return _resp(_bytes(ROUTES[url]))
        if url == events.MOPS_URL:
            return _mops_page(data["TYPEK"], data["year"])
        if url == events.TWT48U_URL:
            return _resp(_bytes("twt48u_all_20261020.json"), last_modified=LM_TWT48U)
        if url == events.TPEX_EXRIGHT_URL:
            return _resp(_bytes("tpex_exright_prepost_20261020.json"), last_modified=LM_TPEX)
        raise _OutboundBlocked(f"未登記的 URL：{url}")

    monkeypatch.setattr(http, "_send", fake_send)
    return calls


def _block(code, analysis_date="2026-10-20"):
    return live_mod.format_tw_live_block(live_mod.load_tw_live_events(analysis_date), code, "zh-TW")


def _stale_notice():
    payload = json.loads(_bytes(ROUTES[risk_flags.TWSE_NOTICE_URL]))
    payload = copy.deepcopy(payload)
    idx = payload["fields"].index("日期")
    for row in payload["data"]:
        row[idx] = "115/10/19"  # 端點凍結在前一天、照樣回 200
    return _resp(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def test_disposition_hit_is_flagged_with_liquidity_guidance(monkeypatch):
    _install(monkeypatch)
    out = _block("2424.TW")
    assert "處置／注意股（下一交易日 2026-10-21）：是（處置中" in out
    assert "分盤撮合" in out and "首要風險" in out and "2～3 個交易日" in out


def test_clean_stock_says_no_only_for_its_own_checked_market(monkeypatch):
    # 上櫃注意壞掉：上櫃不算查過，但上市的「否」不受影響（反向：不能要求四份全好才寫否）
    _install(monkeypatch, {risk_flags.TPEX_ATTENTION_URL: _resp(b"<html>404</html>", "text/html")})
    out = _block("2330.TW")
    assert "：否（處置＋注意名單皆已查）" in out
    assert "無（已查：除權息）" in out
    assert "法說會僅列已申報者，未列不代表沒有" in out
    otc = _block("6488.TWO")
    assert "未確認（名單不可用：" in otc and "上櫃注意" in otc and "：否（" not in otc


def test_stale_attention_list_is_rejected_not_read_as_clean(monkeypatch):
    _install(monkeypatch, {risk_flags.TWSE_NOTICE_URL: _stale_notice(),
                           risk_flags.TPEX_ATTENTION_URL: _resp(b"<html>404</html>", "text/html")})
    out = _block("2330.TW")
    assert "未確認（名單不可用：上市注意" in out
    assert "：否（" not in out
    assert "上櫃注意" not in out  # 原因只列本市場的名單
    assert "未確認（名單不可用：上櫃注意" in _block("6488.TWO")


def test_stale_ex_rights_header_drops_the_category(monkeypatch):
    stale = _resp(_bytes("twt48u_all_20261020.json"), last_modified="Thu, 15 Oct 2026 21:28:56 GMT")
    _install(monkeypatch, {events.TWT48U_URL: stale})
    live = live_mod.load_tw_live_events("2026-10-20")
    assert "除權息" not in live["event_checked"]["twse"]
    assert "0056" not in live["by_stock"]
    out = _block("2330.TW")  # 同一輪快取；除權息沒查過就不能寫「無」
    assert "：未列（" in out and "無（已查" not in out


def test_events_are_listed_for_the_stock(monkeypatch):
    _install(monkeypatch)
    out = _block("2337.TW")
    assert "法說 10/27" in out


def test_historical_analysis_date_does_not_fetch(monkeypatch):
    calls = _install(monkeypatch)
    assert live_mod.load_tw_live_events("2026-10-19") is None
    assert live_mod.load_tw_live_events(None) is None
    assert calls == []
    # 盤中：分析日是今天、預期場次仍是前一天 → 照抓
    assert live_mod.load_tw_live_events("2026-10-21") is not None


def test_whole_market_lists_fetched_once_per_run(monkeypatch):
    calls = _install(monkeypatch)
    _block("2330.TW")
    first = len(calls)
    _block("2424.TW")
    _block("6488.TWO")
    assert first > 0 and len(calls) == first


def test_fetcher_exception_fails_open(monkeypatch):
    calls = _install(monkeypatch)
    monkeypatch.setattr(risk_flags, "fetch_risk_flags", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    assert _block("2330.TW") == ""
    assert calls == []


def test_non_tw_code_renders_nothing(monkeypatch):
    _install(monkeypatch)
    live = live_mod.load_tw_live_events("2026-10-20")
    for code in ("AAPL", "600519", "2330", "7203.T"):
        assert live_mod.format_tw_live_block(live, code, "zh-TW") == ""


def _prompt(code, enabled):
    ctx = copy.deepcopy(_rich_context())
    ctx["code"] = code
    cfg = SimpleNamespace(news_max_age_days=3, news_strategy_profile="short", tw_live_events_enabled=enabled)
    with patch("src.analyzer.get_config", return_value=cfg), \
            patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""), \
            patch.object(GeminiAnalyzer, "_tw_margin_lines", return_value=""), \
            patch("src.analyzer.load_tw_regime", return_value=None), \
            patch("src.analyzer.load_tw_live_events", return_value={"stub": 1}) as load, \
            patch("src.analyzer.format_tw_live_block", return_value="\n### LIVE-BLOCK\n") as fmt:
        out = _make_analyzer(legacy=True)._format_prompt(ctx, "X", news_context="n", report_language="zh-TW")
    return out, load, fmt


def test_analyzer_wires_block_for_tw_when_enabled():
    out, load, fmt = _prompt("2330.TW", True)
    assert "### LIVE-BLOCK" in out
    load.assert_called_once_with("2026-03-16")
    assert fmt.call_args.args[1] == "2330.TW"
    for code, enabled in (("2330.TW", False), ("AAPL", True)):
        out, load, _ = _prompt(code, enabled)
        assert "LIVE-BLOCK" not in out
        load.assert_not_called()


_REAL_FETCH = live_mod._fetch


def test_failed_fetch_is_retried_after_window_not_cached_all_day(monkeypatch):
    # 長駐的 Web 服務第一次抓取出錯：舊版 lru_cache 把 None 留到隔天，整個交易日 prompt 都缺這段
    clock = [1000.0]
    monkeypatch.setattr(live_mod.time, "monotonic", lambda: clock[0])
    attempts = []

    def boom(as_of_iso):
        attempts.append(as_of_iso)
        return None

    monkeypatch.setattr(live_mod, "_fetch", boom)
    assert live_mod.load_tw_live_events("2026-10-20") is None
    assert live_mod.load_tw_live_events("2026-10-20") is None
    assert len(attempts) == 1                      # 窗口內不每檔重打
    clock[0] += live_mod._RETRY_SECONDS + 1
    _install(monkeypatch)
    monkeypatch.setattr(live_mod, "_fetch", _REAL_FETCH)
    assert live_mod.load_tw_live_events("2026-10-20") is not None


def test_complete_result_is_kept_for_the_whole_day(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(live_mod.time, "monotonic", lambda: clock[0])
    calls = _install(monkeypatch)
    assert live_mod.load_tw_live_events("2026-10-20") is not None
    n = len(calls)
    clock[0] += 10 * live_mod._RETRY_SECONDS
    assert live_mod.load_tw_live_events("2026-10-20") is not None
    assert len(calls) == n



@pytest.mark.parametrize("broken", ["risk", "event"])
def test_incomplete_result_is_retried_after_window(monkeypatch, broken):
    # 有一份名單（或除權息來源）這輪不可用：不能整天沿用缺這份的結果
    clock = [1000.0]
    monkeypatch.setattr(live_mod.time, "monotonic", lambda: clock[0])
    url = risk_flags.TPEX_ATTENTION_URL if broken == "risk" else events.TWT48U_URL
    calls = _install(monkeypatch, overrides={url: _resp(b"<html>maintenance</html>")})
    first = live_mod.load_tw_live_events("2026-10-20")
    assert first is not None
    assert (any(first["risk_down"].values()) if broken == "risk" else first["event_down"])
    n = len(calls)
    assert live_mod.load_tw_live_events("2026-10-20") is first     # 窗口內沿用
    assert len(calls) == n
    clock[0] += live_mod._RETRY_SECONDS + 1
    live_mod.load_tw_live_events("2026-10-20")
    assert len(calls) > n                                            # 過了窗口重抓
