# -*- coding: utf-8 -*-
"""market_data.risk_flags：處置股／注意股即時名單（全離線）。

fixture 在 `tests/fixtures/tw_live/`，取自 2026-10-20 台北 19:3x 實測回應（只截斷長文字欄）：
基準日 as_of=10/20、下一個交易日 next=10/21。處置名單以 next 查、注意名單以 as_of 查。
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest
import requests

from market_data import risk_flags, tw_official_http as http

FIX = Path(__file__).resolve().parent / "fixtures" / "tw_live"
AS_OF = dt.date(2026, 10, 20)
NEXT = dt.date(2026, 10, 21)


class _OutboundBlocked(BaseException):
    """刻意繼承 `BaseException`：生產碼的 `except Exception` 吞不掉，守門才有效。"""


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    import socket as _socket

    real_connect = _socket.socket.connect

    def guard(self, address):
        host = address[0] if isinstance(address, tuple) and address else ""
        if isinstance(host, str) and (host.startswith("127.") or host in ("localhost", "::1")):
            return real_connect(self, address)
        raise _OutboundBlocked(f"離線測試嘗試連外 {address}")

    monkeypatch.setattr(_socket.socket, "connect", guard)


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _resp(body: bytes, status=200, headers=None):
    resp = requests.Response()
    resp.status_code = status
    resp._content = body
    resp.headers.update(headers or {"Content-Type": "application/json"})
    return resp


def _json_resp(payload):
    return _resp(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


ROUTES = {
    risk_flags.TWSE_PUNISH_URL: "twse_punish_next_20261021.json",
    risk_flags.TWSE_NOTICE_URL: "twse_notice_20261020.json",
    risk_flags.TPEX_ATTENTION_URL: "tpex_attention_20261020.json",
    risk_flags.TPEX_DISPOSAL_URL: "tpex_disposal_next_20261021.json",
}


def _install(monkeypatch, overrides=None):
    """把 `tw_official_http._send` 換成查表；未登記的 URL 直接 `_OutboundBlocked`。"""
    calls = []
    overrides = overrides or {}

    def fake_send(method, url, **kwargs):
        calls.append((method, url, kwargs.get("params")))
        if url in overrides:
            value = overrides[url]
            if isinstance(value, BaseException):
                raise value
            return value
        if url not in ROUTES:
            raise _OutboundBlocked(f"未登記的 URL：{url}")
        return _json_resp(_load(ROUTES[url]))

    monkeypatch.setattr(http, "_send", fake_send)
    return calls


# ---- 上市處置 ---------------------------------------------------------------------------

def test_twse_punish_marks_disposal_covering_the_next_session():
    hits, note = risk_flags.parse_twse_punish(_load(ROUTES[risk_flags.TWSE_PUNISH_URL]), AS_OF, NEXT)

    # 2424 有兩列：10/16～10/22（已在處置）與 *10/20 公告的 10/21～10/28 → 處置中、期間取最晚那列
    assert hits["2424"].flag == risk_flags.DISPOSING
    assert hits["2424"].detail == "處置中 10/21～10/28，人工管制撮合"
    assert hits["3055"].flag == risk_flags.DISPOSING
    assert "053040" in hits          # 權證留在名單裡，只是永遠對不到候選
    assert note == "資訊更新 10/20"


def test_twse_punish_drops_rows_that_end_on_the_base_date_and_marks_future_ones_upcoming():
    payload = copy.deepcopy(_load(ROUTES[risk_flags.TWSE_PUNISH_URL]))
    cols = payload["fields"]
    period, code = cols.index("處置起迄時間"), cols.index("證券代號")
    payload["data"] = [r for r in payload["data"] if r[code] in ("3055", "3167")]
    payload["data"][0][period] = "115/10/14～115/10/20"   # 今天是最後一天 → 下一個交易日不受限
    payload["data"][1][period] = "115/10/21～115/10/28"   # 明天才開始 → 即將處置

    hits, _ = risk_flags.parse_twse_punish(payload, AS_OF, NEXT)

    assert "3055" not in hits
    assert hits["3167"].flag == risk_flags.UPCOMING


@pytest.mark.parametrize("updated, ok", [("115/10/19", False), ("115/10/20", True), ("115/10/21", True)])
def test_twse_punish_requires_the_update_date_to_be_on_or_after_the_base_date(updated, ok):
    """18:00 跑時更新日 = as_of；隔天 07:30 跑時可能已是隔天——兩者都要收，更早的要拒。"""
    payload = copy.deepcopy(_load(ROUTES[risk_flags.TWSE_PUNISH_URL]))
    payload["title"] = payload["title"].replace("資訊更新日期：115/10/20", f"資訊更新日期：{updated}")
    if ok:
        risk_flags.parse_twse_punish(payload, AS_OF, NEXT)
    else:
        with pytest.raises(risk_flags.Unproven, match="早於基準日"):
            risk_flags.parse_twse_punish(payload, AS_OF, NEXT)


def test_twse_punish_rejects_a_response_for_another_query_range():
    payload = copy.deepcopy(_load(ROUTES[risk_flags.TWSE_PUNISH_URL]))
    payload["title"] = payload["title"].replace("(115/10/21 至 115/10/21)", "(115/10/20 至 115/10/20)")
    with pytest.raises(risk_flags.Unproven, match="查詢區間"):
        risk_flags.parse_twse_punish(payload, AS_OF, NEXT)


# ---- 上市／上櫃注意 ------------------------------------------------------------------------

def test_twse_notice_rejects_a_response_for_another_query_range():
    """列的日期之外，title 的查詢區間也要等於基準日（防回應其實是別天的查詢）。"""
    payload = copy.deepcopy(_load(ROUTES[risk_flags.TWSE_NOTICE_URL]))
    payload["title"] = payload["title"].replace("(115年10月20日 至 115年10月20日", "(115年10月19日 至 115年10月19日")
    with pytest.raises(risk_flags.Unproven, match="查詢區間"):
        risk_flags.parse_twse_notice(payload, AS_OF)


def test_twse_notice_lists_attention_stocks_of_the_base_date():
    hits, _ = risk_flags.parse_twse_notice(_load(ROUTES[risk_flags.TWSE_NOTICE_URL]), AS_OF)

    assert hits["1802"] == risk_flags.RiskHit(risk_flags.ATTENTION, "台玻", "注意股，累計 1 次")


def test_twse_notice_empty_data_is_unproven_not_zero_stocks():
    payload = copy.deepcopy(_load(ROUTES[risk_flags.TWSE_NOTICE_URL]))
    payload["data"] = []
    with pytest.raises(risk_flags.Unproven, match="空回應"):
        risk_flags.parse_twse_notice(payload, AS_OF)


def test_twse_notice_rejects_rows_of_another_day():
    payload = copy.deepcopy(_load(ROUTES[risk_flags.TWSE_NOTICE_URL]))
    payload["data"][3][payload["fields"].index("日期")] = "115.10.19"
    with pytest.raises(risk_flags.Unproven, match="非基準日"):
        risk_flags.parse_twse_notice(payload, AS_OF)


def test_tpex_attention_lists_base_date_rows():
    hits, note = risk_flags.parse_tpex_attention(_load(ROUTES[risk_flags.TPEX_ATTENTION_URL]), AS_OF)

    assert hits["3354"].flag == risk_flags.ATTENTION and hits["1815"].name == "富喬"
    assert note == "19 列皆為 10/20"


def test_tpex_attention_rejects_the_silent_fallback_to_today():
    """日期參數不合法時 TPEx 退回今天；回應區間不是送出的值就要拒。"""
    payload = copy.deepcopy(_load(ROUTES[risk_flags.TPEX_ATTENTION_URL]))
    with pytest.raises(risk_flags.Unproven, match="不是送出的"):
        risk_flags.parse_tpex_attention(payload, dt.date(2026, 10, 19))


def test_tpex_attention_empty_is_unproven():
    payload = copy.deepcopy(_load(ROUTES[risk_flags.TPEX_ATTENTION_URL]))
    payload["tables"][0]["data"] = []
    with pytest.raises(risk_flags.Unproven, match="空回應"):
        risk_flags.parse_tpex_attention(payload, AS_OF)


# ---- 上櫃處置 ---------------------------------------------------------------------------

def test_tpex_disposal_cleans_linked_names_and_marks_upcoming():
    hits, note = risk_flags.parse_tpex_disposal(
        _load(ROUTES[risk_flags.TPEX_DISPOSAL_URL]), AS_OF, NEXT, attention_ok=False)

    assert hits["3354"].name == "律勝"
    assert hits["3354"].flag == risk_flags.UPCOMING      # 10/20 公告、10/21 起
    assert hits["6716"].flag == risk_flags.DISPOSING
    assert "有基準日公布的列" in note


def _without_base_date_rows(payload):
    payload = copy.deepcopy(payload)
    table = payload["tables"][0]
    i = table["fields"].index("公布日期")
    table["data"] = [r for r in table["data"] if r[i] != "115/10/20"]
    return payload


def test_tpex_disposal_without_any_freshness_evidence_is_unproven():
    payload = _without_base_date_rows(_load(ROUTES[risk_flags.TPEX_DISPOSAL_URL]))
    with pytest.raises(risk_flags.Unproven, match="無法證明新鮮"):
        risk_flags.parse_tpex_disposal(payload, AS_OF, NEXT, attention_ok=False)
    # 反向：同輪上櫃注意可用就當旁證收下
    hits, note = risk_flags.parse_tpex_disposal(payload, AS_OF, NEXT, attention_ok=True)
    assert "6716" in hits and "旁證" in note


def test_tpex_disposal_rejects_another_query_range():
    with pytest.raises(risk_flags.Unproven, match="不是送出的"):
        risk_flags.parse_tpex_disposal(_load(ROUTES[risk_flags.TPEX_DISPOSAL_URL]), AS_OF,
                                       dt.date(2026, 10, 22), attention_ok=True)


# ---- fetch_risk_flags（經 tw_official_http 的接縫） ------------------------------------------

def test_fetch_merges_four_lists_and_queries_disposal_by_next_session(monkeypatch):
    calls = _install(monkeypatch)

    flags, statuses = risk_flags.fetch_risk_flags(AS_OF, NEXT)

    assert [s.name for s in statuses] == ["上市處置", "上市注意", "上櫃注意", "上櫃處置"]
    assert all(s.ok for s in statuses)
    assert risk_flags.checked_markets(statuses) == {"twse", "tpex"}
    # 同時處置與注意：flag 取處置、detail 兩者都寫
    assert flags["2424"].flag == risk_flags.DISPOSING and "注意股" in flags["2424"].detail
    assert flags["3354"] == risk_flags.RiskHit(risk_flags.UPCOMING, "律勝", "即將處置 10/21～10/28，第一次處置；注意股")
    assert flags["1802"].flag == risk_flags.ATTENTION
    params = {url: p for _, url, p in calls}
    assert params[risk_flags.TWSE_PUNISH_URL]["startDate"] == "20261021"
    assert params[risk_flags.TWSE_NOTICE_URL]["startDate"] == "20261020"
    assert params[risk_flags.TPEX_DISPOSAL_URL]["startDate"] == "2026/10/21"
    assert params[risk_flags.TPEX_ATTENTION_URL]["endDate"] == "2026/10/20"


def test_fetch_degrades_one_market_when_its_attention_list_is_an_error_page(monkeypatch):
    hinet = _resp(b"<html><title>\xe7\xb6\xb2\xe7\xab\x99\xe7\xb6\xad\xe8\xad\xb7\xe4\xb8\xad</title></html>",
                  headers={"Content-Type": "text/html"})
    _install(monkeypatch, {risk_flags.TPEX_ATTENTION_URL: hinet})

    flags, statuses = risk_flags.fetch_risk_flags(AS_OF, NEXT)

    by_name = {s.name: s for s in statuses}
    assert not by_name["上櫃注意"].ok and "HiNet" in by_name["上櫃注意"].note
    assert by_name["上櫃處置"].ok            # 有基準日公布的列可當旁證
    assert risk_flags.checked_markets(statuses) == {"twse"}
    assert flags["3354"].flag == risk_flags.UPCOMING   # 可用來源的命中照樣標


def _hinet():
    return _resp(b"<html><title>\xe7\xb6\xb2\xe7\xab\x99\xe7\xb6\xad\xe8\xad\xb7\xe4\xb8\xad</title></html>",
                 headers={"Content-Type": "text/html"})


def _stale_disposal():
    """上櫃處置表沒有基準日公布的列：新鮮度只能靠同輪上櫃注意當旁證。"""
    return _json_resp(_without_base_date_rows(_load(ROUTES[risk_flags.TPEX_DISPOSAL_URL])))


def test_fetch_rejects_tpex_disposal_without_base_date_rows_when_attention_is_down(monkeypatch):
    _install(monkeypatch, {risk_flags.TPEX_ATTENTION_URL: _hinet(),
                           risk_flags.TPEX_DISPOSAL_URL: _stale_disposal()})

    flags, statuses = risk_flags.fetch_risk_flags(AS_OF, NEXT)

    by_name = {s.name: s for s in statuses}
    assert not by_name["上櫃處置"].ok and "無法證明新鮮" in by_name["上櫃處置"].note
    assert risk_flags.checked_markets(statuses) == {"twse"}
    assert "6716" not in flags


def test_fetch_accepts_tpex_disposal_without_base_date_rows_when_attention_is_up(monkeypatch):
    _install(monkeypatch, {risk_flags.TPEX_DISPOSAL_URL: _stale_disposal()})

    flags, statuses = risk_flags.fetch_risk_flags(AS_OF, NEXT)

    by_name = {s.name: s for s in statuses}
    assert by_name["上櫃處置"].ok and "旁證" in by_name["上櫃處置"].note
    assert risk_flags.checked_markets(statuses) == {"twse", "tpex"}
    assert flags["6716"].flag == risk_flags.DISPOSING


def test_fetch_never_raises_on_connection_failures(monkeypatch):
    def boom(method, url, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(http, "_send", boom)

    flags, statuses = risk_flags.fetch_risk_flags(AS_OF, NEXT)

    assert flags == {} and len(statuses) == 4 and not any(s.ok for s in statuses)
    assert all("連線失敗" in s.note for s in statuses)
    assert risk_flags.checked_markets(statuses) == set()


def test_network_guard_is_not_swallowed_by_the_per_source_except(monkeypatch):
    """守門是 BaseException：生產碼若把 `except Exception` 放寬成 bare except，這條會紅。"""
    _install(monkeypatch, {risk_flags.TWSE_NOTICE_URL: _OutboundBlocked("would hit network")})
    with pytest.raises(_OutboundBlocked):
        risk_flags.fetch_risk_flags(AS_OF, NEXT)


def test_single_stock_cli_accepts_codes_with_market_suffix(monkeypatch, capsys):
    """repo 慣例的 2424.TW 要對到名單裡的裸代號，不能在四份名單都可用時印成「不在名單」。"""
    from market_data import health

    _install(monkeypatch)
    monkeypatch.setattr(health, "sessions_after", lambda day, n: NEXT)

    assert risk_flags.main(["2424.TW", "2424", "3354.TWO", "1101", "--as-of", "2026-10-20"]) == 0

    out = dict(line.split("：", 1) for line in capsys.readouterr().out.splitlines()
               if line.split("：", 1)[0] in ("2424.TW", "2424", "3354.TWO", "1101"))
    assert out["2424.TW"] == out["2424"] and out["2424"].startswith("處置中 10/21～10/28")
    assert out["3354.TWO"].startswith("即將處置")
    assert out["1101"] == "不在可用名單中"      # 反向：真的不在名單的仍照實回，且無免責尾巴


def test_single_stock_cli_help_exits_cleanly():
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, "-m", "market_data.risk_flags", "--help"],
                       cwd=root, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-500:]
    assert "處置" in r.stdout
