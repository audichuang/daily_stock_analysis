"""market_data.tw_official_http：報告當下即時抓官方端點的取用層（全離線）。

錯誤頁 fixture 取自 2026-10-20 實測回應的開頭（判別所需的部分原樣保留）：
TPEx 不存在路徑 302 到 /errors 後的 404 頁、TWSE rwd 參數不合法時的 HiNet
「網站維護中」頁、期交所 CSV 端點的 alert 頁、P/C 比查非交易日時只有表頭的 CSV。
每個錯誤 fixture 都配一個同來源的正常回應當反向檢查，免得「什麼都判成錯誤」也綠。
"""

import pytest
import requests

from market_data import crawler, tw_official_http as http


class _OutboundBlocked(BaseException):
    """刻意繼承 `BaseException`：生產程式碼的 `except` 若放寬就會把守門吞掉。"""


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    """本檔任何測試一連外就紅（只放行本機位址）。"""
    import socket as _socket

    real_connect = _socket.socket.connect

    def guard(self, address):
        host = address[0] if isinstance(address, tuple) and address else ""
        if isinstance(host, str) and (host.startswith("127.") or host in ("localhost", "::1")):
            return real_connect(self, address)
        raise _OutboundBlocked(f"離線測試嘗試連外 {address}")

    monkeypatch.setattr(_socket.socket, "connect", guard)


def _resp(body, content_type, status=200, redirected=False):
    resp = requests.Response()
    resp.status_code = status
    resp._content = body
    resp.headers["Content-Type"] = content_type
    resp.url = "https://example.invalid/x"
    if redirected:
        resp.history = [requests.Response()]
    return resp


# --- fixtures（實測回應） ----------------------------------------------------

TPEX_ERROR_PAGE = (
    '<!DOCTYPE html><html lang="zh-Hant-tw"><head><title>404 - 證券櫃檯買賣中心</title>'
    '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">'
    '</head><body></body></html>'
).encode("utf-8")
TPEX_OK_JSON = (
    '{"tables":[{"title":"上櫃處置有價證券","startDate":"115/10/20","endDate":"115/10/20",'
    '"fields":["編號","公布日期","證券代號"],"data":[[1,"115/10/20","3354"]]}],'
    '"date":"20261020~20261020","stat":"ok"}'
).encode("utf-8")

TWSE_HINET_PAGE = (
    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
    '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">\n<html lang="zh-Hant-tw">\n<head>\n'
    '<meta charset="utf-8">\n'
    '<link href="https://errorpage-twseweb.cdn.hinet.net/css/main.css" rel="stylesheet">\n'
    '<title>網站維護中 - 臺灣證券交易所</title>\n</head>\n<body><div id="layout"></div></body>\n</html>\n'
).encode("utf-8")
TWSE_OK_JSON = (
    '{"stat":"OK","title":"處置有價證券資訊 資訊更新日期：115/10/20",'
    '"fields":["編號","公布日期","證券代號"],"data":[[1,"115/10/20","2424"]]}'
).encode("utf-8")

TAIFEX_ALERT_PAGE = (
    '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">\r\n\r\n\r\n'
    '<head><meta http-equiv="X-UA-Compatible" content="IE=edge"></head>\r\n'
    '<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-Hant-TW" >\r\n<html>\r\n<head>\r\n'
    '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">\r\n</head>\r\n<body>\r\n'
    '<script>\r\n\t\t\talert("日期時間錯誤 DateTime error");\r\n'
    '\t\t\twindow.location.replace("futContractsDateView");\r\n</script>\r\n</body>\r\n</html>\r\n'
).encode("utf-8")
PC_HEADER = "日期,賣權成交量,買權成交量,買賣權成交量比率%,賣權未平倉量,買權未平倉量,買賣權未平倉量比率%\r\n"
PC_HEADER_ONLY_CSV = PC_HEADER.encode("cp950")
PC_OK_CSV = (PC_HEADER
             + "2026/10/20,287828,223022,129.06,91724,138622,66.17,\r\n"
             + "2026/10/19,183316,193910,94.54,75089,121895,61.60,\r\n").encode("cp950")

MOPS_SECURITY_PAGE = (
    '<html>\n<head>\n<meta http-equiv="Content-Type" content="text/html; charset=utf-8">\n</head>\n<body>\n'
    '因為安全性考量，您所執行的頁面無法呈現。<BR>\nFOR SECURITY REASONS, THIS PAGE CAN NOT BE ACCESSED.<BR>\n'
    '</body>\n</html>\n'
).encode("utf-8")
# 正常的期交所 HTML 頁本身就含 alert(（實測 futContractsDate 頁 7 處）
TAIFEX_NORMAL_HTML = (
    '<!DOCTYPE html><html><head><title>三大法人</title></head><body><table><tr><td>臺股期貨</td></tr></table>'
    '<script>function check(){ if(!ok){ alert("請選擇日期"); } }</script></body></html>'
).encode("utf-8")


# --- error_reason ------------------------------------------------------------

def test_tpex_error_page_after_redirect_is_rejected_even_though_status_is_200():
    resp = _resp(TPEX_ERROR_PAGE, "text/html", redirected=True)

    reason = http.error_reason(resp, "json")

    assert reason is not None and "TPEx 錯誤頁" in reason and "轉址" in reason


def test_tpex_normal_json_passes():
    assert http.error_reason(_resp(TPEX_OK_JSON, "application/json;charset=UTF-8"), "json") is None


def test_twse_hinet_error_page_is_rejected_with_a_specific_reason():
    reason = http.error_reason(_resp(TWSE_HINET_PAGE, "text/html"), "json")

    assert reason is not None and "HiNet" in reason


def test_twse_normal_json_passes():
    assert http.error_reason(_resp(TWSE_OK_JSON, "application/json"), "json") is None


def test_taifex_alert_page_reason_carries_the_utf8_message():
    """錯誤頁是 UTF-8；用 cp950 或 ISO-8859-1 解會讓訊息變亂碼。"""
    resp = _resp(TAIFEX_ALERT_PAGE, "text/html;charset=UTF-8")

    assert http.error_reason(resp, "csv") == "錯誤頁 alert：日期時間錯誤 DateTime error"


# 期交所正常 CSV 實測標 `text/html;charset=MS950`（錯誤頁是 charset=UTF-8），所以不能靠標頭判 HTML。
_CSV_CONTENT_TYPES = ["text/html;charset=MS950", "application/octet-stream", "text/csv"]


@pytest.mark.parametrize("content_type", _CSV_CONTENT_TYPES)
def test_header_only_csv_is_rejected(content_type):
    reason = http.error_reason(_resp(PC_HEADER_ONLY_CSV, content_type), "csv")

    assert reason is not None and "只有表頭" in reason


@pytest.mark.parametrize("content_type", _CSV_CONTENT_TYPES)
def test_csv_with_data_rows_passes_whatever_the_content_type(content_type):
    assert http.error_reason(_resp(PC_OK_CSV, content_type), "csv") is None


def test_non_200_is_rejected():
    assert http.error_reason(_resp(TWSE_OK_JSON, "application/json", status=503), "json") == "HTTP 503"


def test_plain_text_when_json_expected_is_rejected():
    reason = http.error_reason(_resp("很抱歉，沒有符合條件的資料!".encode("utf-8"), "text/plain"), "json")

    assert reason is not None and reason.startswith("非 JSON")


def test_empty_body_is_rejected():
    assert http.error_reason(_resp(b"  \r\n", "application/json"), "json") == "空回應"


def test_html_wanted_rejects_known_error_pages_only():
    """expect=None（要的就是 HTML，例如 MOPS）：已知錯誤頁要擋，正常頁裡的 alert( 不能誤判。"""
    assert http.error_reason(_resp(MOPS_SECURITY_PAGE, "text/html"), None) == "MOPS 安全性封鎖頁"
    assert http.error_reason(_resp(TWSE_HINET_PAGE, "text/html"), None) is not None
    assert http.error_reason(_resp(TAIFEX_NORMAL_HTML, "text/html"), None) is None


def test_html_when_csv_expected_is_rejected_even_without_alert():
    page = "<!DOCTYPE html><html><body><p>系統忙碌中</p></body></html>".encode("utf-8")

    reason = http.error_reason(_resp(page, "text/html"), "csv")

    assert reason is not None and "HTML" in reason and "系統忙碌中" in reason


# --- get / post：短 timeout、不重試、不暖 cookie ---------------------------

def test_get_sends_once_with_short_timeout_and_crawler_ua(monkeypatch):
    calls = []

    def fake_send(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _resp(TWSE_OK_JSON, "application/json")

    monkeypatch.setattr(http, "_send", fake_send)
    monkeypatch.setattr(crawler, "_find_session", lambda: pytest.fail("不該暖 TWSE cookie"))

    resp, reason = http.get("https://www.twse.com.tw/x", params={"a": "1"}, expect="json")

    assert reason is None and resp.json()["stat"] == "OK"
    assert len(calls) == 1
    method, url, kwargs = calls[0]
    assert method == "GET" and kwargs["params"] == {"a": "1"}
    assert kwargs["timeout"] == (5, 15) == http.TIMEOUT
    assert kwargs["headers"]["User-Agent"] == crawler._UA
    assert kwargs["verify"] is True


def test_post_passes_form_data_and_verify_false(monkeypatch):
    calls = []

    def fake_send(method, url, **kwargs):
        calls.append((method, kwargs))
        return _resp(PC_OK_CSV, "text/html;charset=MS950")

    monkeypatch.setattr(http, "_send", fake_send)

    resp, reason = http.post("https://www.taifex.com.tw/x", data={"queryStartDate": "2026/10/19"},
                             expect="csv", verify=False)

    assert reason is None and resp is not None
    assert calls == [("POST", {"headers": {"User-Agent": crawler._UA}, "timeout": http.TIMEOUT,
                               "verify": False, "data": {"queryStartDate": "2026/10/19"}})]


def test_connection_failure_is_one_attempt_and_returns_none(monkeypatch):
    calls = []

    def fake_send(method, url, **kwargs):
        calls.append(url)
        raise requests.ConnectionError("down")

    monkeypatch.setattr(http, "_send", fake_send)

    resp, reason = http.get("https://www.tpex.org.tw/x", expect="json")

    assert resp is None and reason == "連線失敗：ConnectionError"
    assert len(calls) == 1


def test_error_response_is_returned_alongside_the_reason(monkeypatch):
    monkeypatch.setattr(http, "_send", lambda method, url, **kw: _resp(TAIFEX_ALERT_PAGE, "text/html"))

    resp, reason = http.post("https://www.taifex.com.tw/x", expect="csv")

    assert resp is not None and reason.startswith("錯誤頁 alert")


def test_programming_errors_are_not_swallowed(monkeypatch):
    def broken(method, url, **kwargs):
        raise TypeError("bug")

    monkeypatch.setattr(http, "_send", broken)

    with pytest.raises(TypeError):
        http.get("https://www.twse.com.tw/x")


def test_network_guard_propagates_through_the_real_transport(monkeypatch):
    """不 patch `_send`：走真的 requests，連線時被守門擋下。只接 RequestException 才會往上拋；
    IP 字面值免 DNS。清掉系統代理設定，否則會連到本機代理埠而被守門放行。"""
    monkeypatch.setattr(requests.utils, "getproxies", lambda: {})
    with pytest.raises(_OutboundBlocked):
        http.get("http://203.0.113.1/", expect="json")


# --- SourceStatus -------------------------------------------------------------

def test_source_status_shape():
    status = http.SourceStatus("TWSE 處置", False, "連線失敗：ConnectionError")

    assert status.to_dict() == {"name": "TWSE 處置", "ok": False, "note": "連線失敗：ConnectionError",
                                "proven": True}
    assert http.SourceStatus("x", True).note == ""
    with pytest.raises(Exception):
        status.ok = True


@pytest.mark.parametrize("ok, proven, label, checked", [
    (True, True, "可用", True),
    (True, False, "可用（未證明新鮮）", False),
    (False, True, "不可用", False),
])
def test_source_status_label_and_checked(ok, proven, label, checked):
    status = http.SourceStatus("x", ok, "", proven)
    assert status.label == label and status.checked is checked


def test_checked_markets_requires_every_source_to_be_proven():
    """可用但未證明新鮮的來源不算查過；同市場其他來源都已證明也一樣。"""
    source_market = {"a": "twse", "b": "twse", "c": "tpex"}
    statuses = [http.SourceStatus("a", True), http.SourceStatus("b", True, "", proven=False),
                http.SourceStatus("c", True)]
    assert http.checked_markets(statuses, source_market) == {"tpex"}
    # 反向：全部已證明就兩個市場都算
    assert http.checked_markets([http.SourceStatus(n, True) for n in source_market], source_market) == {"twse", "tpex"}


# --- run_sources ----------------------------------------------------------------

def _ok(payload, note=""):
    return lambda done: (payload, note)


def _fail(done):
    raise http.FormatChanged("壞了")


@pytest.mark.parametrize("parallel", [False, True])
def test_run_sources_isolates_failures_and_keeps_step_order(parallel):
    steps = [http.Step("a", _ok(1)), http.Step("b", _fail), http.Step("c", _ok(3, "n"), proven=False)]

    results, statuses = http.run_sources(steps, parallel=parallel)

    assert results == [("a", 1), ("c", 3)]
    assert [(s.name, s.ok, s.note, s.proven) for s in statuses] == [
        ("a", True, "", True), ("b", False, "壞了", True), ("c", True, "n", False)]


def test_run_sources_sequential_passes_the_statuses_so_far():
    seen = []
    steps = [http.Step("a", _ok(1)), http.Step("b", lambda done: (seen.append([s.name for s in done]), ""))]
    http.run_sources(steps)
    assert seen == [["a"]]


def test_run_sources_parallel_runs_steps_at_the_same_time_and_orders_by_step():
    """第一步要等到最後一步開始才完成：依序跑會卡到逾時；結果仍依 steps 順序，不依完成先後。"""
    import threading

    last_started = threading.Event()

    def first(done):
        if not last_started.wait(timeout=30):
            raise AssertionError("沒有並行")
        return "first", ""

    def last(done):
        last_started.set()
        return "last", ""

    results, statuses = http.run_sources([http.Step("a", first), http.Step("b", last)], parallel=True)

    assert results == [("a", "first"), ("b", "last")] and all(s.ok for s in statuses)


def test_run_sources_parallel_does_not_swallow_the_network_guard():
    def guarded(done):
        raise _OutboundBlocked("would hit network")

    with pytest.raises(_OutboundBlocked):
        http.run_sources([http.Step("a", _ok(1)), http.Step("b", guarded)], parallel=True)


def test_md_is_zero_padded():
    import datetime
    assert http.md(datetime.date(2026, 10, 8)) == "10/08"
