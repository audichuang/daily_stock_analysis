# -*- coding: utf-8 -*-
"""market_data.events：未來 N 個交易日的事件日曆（全離線）。

fixture 在 `tests/fixtures/tw_live/`，取自 2026-10-20 實測回應：MOPS 法說會整年表只留少數幾檔
的列；除權息預告兩份原樣。測試窗口：as_of=10/20 → 10/21~10/27（5 個交易日）、前一交易日 10/19。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import requests

from market_data import events, tw_official_http as http

FIX = Path(__file__).resolve().parent / "fixtures" / "tw_live"
START, END, PREV = dt.date(2026, 10, 21), dt.date(2026, 10, 27), dt.date(2026, 10, 19)
WINDOW = events.EventWindow(START, END, PREV, 5)


def _win(start, end):
    return events.EventWindow(start, end, PREV, 5)


# 實測標頭：TWT48U 台北 10/20 05:28、TPEx 台北 10/20 18:00
LM_TWT48U = "Mon, 19 Oct 2026 21:28:56 GMT"
LM_TPEX = "Tue, 20 Oct 2026 10:00:12 GMT"


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


def _bytes(name):
    return (FIX / name).read_bytes()


def _resp(body, content_type="application/json", last_modified=None, status=200):
    resp = requests.Response()
    resp.status_code = status
    resp._content = body
    resp.headers["Content-Type"] = content_type
    if last_modified:
        resp.headers["Last-Modified"] = last_modified
    return resp


def _mops_page(typek, year):
    if year != 115:
        return _resp(_bytes("mops_t100sb02_nodata.html"), "text/html")
    return _resp(_bytes(f"mops_t100sb02_{typek}_115_trim.html"), "text/html")


def _install(monkeypatch, overrides=None):
    """`tw_official_http._send` 換成查表；未登記的 URL 直接 `_OutboundBlocked`。"""
    calls = []
    overrides = overrides or {}

    def fake_send(method, url, **kwargs):
        data = kwargs.get("data") or {}
        calls.append((method, url, dict(data)))
        key = (url, data.get("TYPEK"), data.get("year")) if url == events.MOPS_URL else url
        if key in overrides:
            value = overrides[key]
            if isinstance(value, BaseException):
                raise value
            return value(data) if callable(value) else value
        if url == events.MOPS_URL:
            assert kwargs.get("verify") is False      # MOPS 憑證鏈不完整，入庫爬蟲也是 verify=False
            return _mops_page(data["TYPEK"], data["year"])
        if url == events.TWT48U_URL:
            return _resp(_bytes("twt48u_all_20261020.json"), last_modified=LM_TWT48U)
        if url == events.TPEX_EXRIGHT_URL:
            return _resp(_bytes("tpex_exright_prepost_20261020.json"), last_modified=LM_TPEX)
        raise _OutboundBlocked(f"未登記的 URL：{url}")

    monkeypatch.setattr(http, "_send", fake_send)
    return calls


# ---- 法說會 -----------------------------------------------------------------------------

def _parsed():
    html = _bytes("mops_t100sb02_sii_115_trim.html").decode("utf-8")
    return {(e.stock_id, e.start): e for e in events.parse_mops_conferences(html)}


def test_mops_classifies_self_hosted_vs_invited_and_strips_invisible_marks():
    ev = _parsed()

    assert ev[("2308", dt.date(2026, 10, 29))].kind == events.CONFERENCE   # 「自辦法人說明會」
    assert ev[("2337", dt.date(2026, 10, 27))].kind == events.CONFERENCE   # 「第三季營運成果報告」
    assert ev[("3052", dt.date(2026, 10, 21))].kind == events.FORUM        # 「受邀參加元大證券」
    assert ev[("1731", dt.date(2026, 10, 21))].kind == events.FORUM        # 「受台新證券邀請」
    # 受邀說明財報仍是券商場：「受邀」優先於財報關鍵字
    assert ev[("2308", dt.date(2026, 11, 3))].kind == events.FORUM
    mtk = ev[("2454", dt.date(2026, 10, 30))]
    assert mtk.kind == events.CONFERENCE and "\u200e" not in mtk.detail
    assert ev[("2308", dt.date(2026, 10, 29))].time == "15:00"


def test_mops_keeps_six_digit_codes_as_strings():
    assert any(code == "910861" for code, _ in _parsed())


def test_mops_splits_date_ranges():
    nrd = _parsed()[("6515", dt.date(2026, 10, 19))]
    assert nrd.end == dt.date(2026, 10, 21)


def test_mops_window_uses_both_ends_of_a_range(monkeypatch):
    _install(monkeypatch)

    hits = {(e.stock_id, e.start) for e in events.fetch_mops_conferences("sii", WINDOW)}

    assert ("6515", dt.date(2026, 10, 19)) in hits    # 10/19~10/21：只有尾端落在窗口
    assert ("2337", dt.date(2026, 10, 27)) in hits    # 窗口最後一天
    assert ("3052", dt.date(2026, 10, 21)) in hits
    assert not any(code == "2308" for code, _ in hits)                 # 10/29 在窗口外
    assert ("7769", dt.date(2026, 10, 13)) not in hits                 # 10/13~10/20 已結束


def test_mops_range_that_starts_before_and_ends_after_the_window_is_included(monkeypatch):
    _install(monkeypatch)

    hits = {(e.stock_id, e.start) for e in events.fetch_mops_conferences(
        "sii", _win(dt.date(2026, 10, 14), dt.date(2026, 10, 15)))}

    assert ("7769", dt.date(2026, 10, 13)) in hits    # 10/13~10/20 涵蓋整個窗口，兩端都不在窗口內


def test_mops_zero_rows_in_the_window_start_year_is_a_failure(monkeypatch):
    _install(monkeypatch, {(events.MOPS_URL, "sii", 115): _resp(_bytes("mops_t100sb02_nodata.html"),
                                                                "text/html")})
    with pytest.raises(events.FormatChanged, match="0 列"):
        events.fetch_mops_conferences("sii", WINDOW)


def test_mops_zero_rows_in_the_following_year_is_not_a_failure(monkeypatch):
    """跨年窗口補抓的下一年還沒人申報是正常的，不能讓整個來源失敗。"""
    calls = _install(monkeypatch)

    hits = events.fetch_mops_conferences("sii", _win(dt.date(2026, 12, 28), dt.date(2027, 1, 4)))

    assert hits == []
    assert sorted(c[2]["year"] for c in calls) == [115, 116]
    # month 篩的是區間迄日，按月抓會漏跨月區間：必須一次拿整年
    mops = [c for c in calls if c[1] == events.MOPS_URL]
    assert len(mops) == 2 and all(c[2]["month"] == "" for c in mops)


def test_mops_security_page_fails_the_source(monkeypatch):
    blocked = _resp("<html><body>FOR SECURITY REASONS, THIS PAGE CAN NOT BE ACCESSED.</body></html>"
                    .encode("utf-8"), "text/html")
    _install(monkeypatch, {(events.MOPS_URL, "sii", 115): blocked})
    with pytest.raises(events.FormatChanged, match="MOPS 安全性封鎖頁"):
        events.fetch_mops_conferences("sii", WINDOW)


# ---- 除權息預告 ---------------------------------------------------------------------------

def _ex_kwargs(source="TWT48U"):
    if source == "TWT48U":
        return dict(date_key="Date", code_key="Code", kind_key="Exdividend",
                    kinds=events._TWSE_EX_KIND, source="TWT48U")
    return dict(date_key="ExRrightsExDividendDate", code_key="SecuritiesCompanyCode",
                kind_key="ExRrightsExDividend", kinds=events._TPEX_EX_KIND, source="TPEx")


def test_ex_rights_keep_only_window_rows_and_codes_with_letters(monkeypatch):
    _install(monkeypatch)

    twse, note = events.fetch_ex_rights(events.TWT48U_URL, WINDOW, **_ex_kwargs())
    tpex, _ = events.fetch_ex_rights(events.TPEX_EXRIGHT_URL, WINDOW, **_ex_kwargs("TPEx"))

    codes = {e.stock_id for e in twse}
    assert {"00408A", "0056", "2028", "6931"} <= codes
    assert all(START <= e.start <= END for e in twse + tpex)        # 滾動視窗裡的 10/19、10/20 被濾掉
    by_code = {e.stock_id: e for e in tpex}
    assert by_code["8936"].cash == 3.0 and by_code["8936"].label() == "除息 10/22（現金 3 元）"
    assert by_code["00719B"].cash is None                           # 「尚未公告」不轉數字
    assert by_code["00719B"].label() == "除息 10/22"
    assert by_code["8936"].to_dict()["cash"] == 3.0 and by_code["8936"].to_dict()["detail"] is None
    assert by_code["3691"].kind == "除權"
    assert note == "資料時間 10/20"


@pytest.mark.parametrize("last_modified, ok", [
    ("Sun, 18 Oct 2026 21:28:56 GMT", True),    # 台北 10/19 = 前一交易日：收
    ("Sat, 17 Oct 2026 21:28:56 GMT", False),   # 台北 10/18：超過 1 個交易日未更新
    (None, False),                              # 沒標頭：無法證明新鮮
])
def test_ex_rights_freshness_is_last_modified_on_or_after_the_previous_session(monkeypatch, last_modified, ok):
    stale = _resp(_bytes("twt48u_all_20261020.json"), last_modified=last_modified)
    _install(monkeypatch, {events.TWT48U_URL: stale})
    if ok:
        events.fetch_ex_rights(events.TWT48U_URL, WINDOW, **_ex_kwargs())
    else:
        with pytest.raises(events.FormatChanged, match="拒收"):
            events.fetch_ex_rights(events.TWT48U_URL, WINDOW, **_ex_kwargs())


def test_ex_rights_every_row_unparseable_is_a_format_change():
    with pytest.raises(events.FormatChanged, match="每一列"):
        events.parse_ex_rights([{"foo": 1}], window=WINDOW, **_ex_kwargs())


# ---- 月營收 -------------------------------------------------------------------------------

@pytest.mark.parametrize("start, end, expected", [
    ((2026, 10, 21), (2026, 10, 27), []),
    ((2026, 10, 27), (2026, 11, 2), [(2026, 11, 10)]),    # 期限 11/10 在窗口外，但公告期已開始
    ((2026, 11, 10), (2026, 11, 16), [(2026, 11, 10)]),
    ((2026, 11, 11), (2026, 11, 20), []),
    ((2026, 12, 28), (2027, 1, 4), [(2027, 1, 10)]),
])
def test_revenue_deadlines_follow_the_tenth_of_month_rule(start, end, expected):
    got = events.revenue_deadlines(_win(dt.date(*start), dt.date(*end)))
    assert got == [dt.date(*d) for d in expected]


# ---- upcoming（對外入口） ------------------------------------------------------------------

def test_upcoming_collects_four_sources_and_labels_mops_as_unproven(monkeypatch):
    _install(monkeypatch)

    by_stock, statuses = events.upcoming(WINDOW)

    assert [s.name for s in statuses] == ["法說會（上市 MOPS）", "法說會（上櫃 MOPS）",
                                          "除權息預告（上市 TWT48U）", "除權息預告（上櫃 TPEx）"]
    assert all(s.ok for s in statuses)
    assert "不會捏造" in statuses[0].note
    assert [e.kind for e in by_stock["6515"]] == [events.FORUM]
    assert "8936" in by_stock and "2337" in by_stock
    assert by_stock["0056"][0].to_dict()["date"] == "2026-10-22"


def test_upcoming_one_stale_source_does_not_take_the_other_down(monkeypatch):
    stale = _resp(_bytes("twt48u_all_20261020.json"), last_modified="Thu, 15 Oct 2026 21:28:56 GMT")
    _install(monkeypatch, {events.TWT48U_URL: stale})

    by_stock, statuses = events.upcoming(WINDOW)

    by_name = {s.name: s for s in statuses}
    assert not by_name["除權息預告（上市 TWT48U）"].ok
    assert "Last-Modified 10/16" in by_name["除權息預告（上市 TWT48U）"].note
    assert by_name["除權息預告（上櫃 TPEx）"].ok and "8936" in by_stock
    assert "0056" not in by_stock                     # 被拒收的來源一筆都不留


def test_upcoming_never_raises_on_connection_failure(monkeypatch):
    def boom(method, url, **kwargs):
        raise requests.ConnectTimeout("slow")

    monkeypatch.setattr(http, "_send", boom)

    by_stock, statuses = events.upcoming(WINDOW)

    assert by_stock == {} and not any(s.ok for s in statuses)


def test_network_guard_is_not_swallowed(monkeypatch):
    _install(monkeypatch, {events.TPEX_EXRIGHT_URL: _OutboundBlocked("would hit network")})
    with pytest.raises(_OutboundBlocked):
        events.upcoming(WINDOW)


def test_event_source_names_match_the_market_map(monkeypatch):
    """`upcoming()` 的狀態名稱必須都在 SOURCE_MARKET 裡，否則該來源失敗不會讓任何市場降級。"""
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(events, "fetch_mops_conferences", boom)
    monkeypatch.setattr(events, "fetch_ex_rights", boom)
    _, statuses = events.upcoming(WINDOW)
    assert len(statuses) == 4 and {s.name for s in statuses} == set(events.SOURCE_MARKET)
    assert events.checked_markets(statuses) == set()


def test_upcoming_marks_mops_unproven_so_no_market_counts_as_checked(monkeypatch):
    """四源全部可用時，MOPS 仍是「可用但未證明新鮮」：沒有任何市場能把沒命中寫成「查過、沒有」，
    只有除權息這一類算查過。"""
    _install(monkeypatch)

    _, statuses = events.upcoming(WINDOW)

    by_name = {s.name: s for s in statuses}
    assert all(s.ok for s in statuses)
    assert not by_name[events.SRC_MOPS_SII].proven and not by_name[events.SRC_MOPS_OTC].proven
    assert by_name[events.SRC_TWT48U].proven and by_name[events.SRC_TPEX_EX].proven
    assert by_name[events.SRC_MOPS_SII].label == "可用（未證明新鮮）"
    assert events.checked_markets(statuses) == set()
    assert events.checked_categories(statuses) == {"twse": ["除權息"], "tpex": ["除權息"]}


def test_upcoming_fetches_sources_concurrently(monkeypatch):
    """上市 MOPS（第一個來源）要等到上櫃除權息（最後一個來源）的請求發出才回應：依序跑會卡到逾時。"""
    import threading

    tpex_seen = threading.Event()
    _install(monkeypatch)
    standard = http._send   # 標準回應的查表 fake，外面再包一層同步點

    def fake_send(method, url, **kwargs):
        if url == events.TPEX_EXRIGHT_URL:
            tpex_seen.set()
        elif url == events.MOPS_URL and (kwargs.get("data") or {}).get("TYPEK") == "sii":
            if not tpex_seen.wait(timeout=30):
                raise AssertionError("事件來源沒有並行：上市 MOPS 等不到上櫃除權息的請求")
        return standard(method, url, **kwargs)

    monkeypatch.setattr(http, "_send", fake_send)

    _, statuses = events.upcoming(WINDOW)

    assert all(s.ok for s in statuses), [s.note for s in statuses]


def test_upcoming_order_is_stable_when_the_first_source_is_slow_and_fails(monkeypatch):
    """第一個來源最慢、最後才失敗：狀態仍依固定順序，其他來源的結果照收。"""
    import threading

    others_done = threading.Event()
    seen = set()
    _install(monkeypatch)
    standard = http._send

    def fake_send(method, url, **kwargs):
        typek = (kwargs.get("data") or {}).get("TYPEK")
        if url == events.MOPS_URL and typek == "sii":
            others_done.wait(timeout=30)
            raise requests.ConnectTimeout("slow")
        resp = standard(method, url, **kwargs)
        seen.add(typek or url)
        if {"otc", events.TWT48U_URL, events.TPEX_EXRIGHT_URL} <= seen:
            others_done.set()
        return resp

    monkeypatch.setattr(http, "_send", fake_send)

    by_stock, statuses = events.upcoming(WINDOW)

    assert [s.name for s in statuses] == list(events.SOURCE_CATEGORY)
    assert [s.ok for s in statuses] == [False, True, True, True]
    assert "ConnectTimeout" in statuses[0].note
    assert "8936" in by_stock and "0056" in by_stock
