"""scripts/taifex_positions.py：期交所外資台指期淨未平倉與 P/C 比（全離線）。

fixture 取自 2026-10-20 實測回應，原樣保留位元組（正常 CSV 是 cp950，錯誤頁是 UTF-8
HTML）。mock 接縫是 `tw_official_http._send`，所以錯誤頁判斷走的是真正的
`error_reason`，不是測試自己寫的原因字串。Content-Type 照實測給：正常 CSV 也標成
``text/html;charset=MS950``，以 Content-Type 判 HTML 的寫法會在這裡變紅。

交易日曆一律注入假的 ``is_session``（國慶 10/09、10/10 休市），不依賴本機有沒有
exchange_calendars，也不讀牆鐘。
"""

import datetime
import sys
from pathlib import Path

import pytest
import requests

from market_data import health
from market_data import tw_official_http as http

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import taifex_positions as tp  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FUT_OK = (FIXTURES / "taifex_fut_txf_20261013_20261020.bin").read_bytes()
PC_OK = (FIXTURES / "taifex_pc_20261013_20261020.bin").read_bytes()
FUT_DATEERROR = (FIXTURES / "taifex_fut_dateerror.bin").read_bytes()
FUT_NODATA = (FIXTURES / "taifex_fut_nodata.bin").read_bytes()
PC_HEADER_ONLY = PC_OK.split(b"\r\n")[0] + b"\r\n"

CSV_TYPE = "text/html;charset=MS950"
HTML_TYPE = "text/html;charset=UTF-8"
HOLIDAYS = {datetime.date(2026, 10, 9), datetime.date(2026, 10, 10)}


def fake_is_session(day):
    return day.weekday() < 5 and day not in HOLIDAYS


class _OutboundBlocked(BaseException):
    """刻意繼承 `BaseException`：生產碼的 `except` 若放寬就會把守門吞掉。"""


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    """本檔任何測試一連外就紅（只放行本機位址），也不讓測試讀到真實日曆。"""
    import socket as _socket

    real_connect = _socket.socket.connect

    def guard(self, address):
        host = address[0] if isinstance(address, tuple) and address else ""
        if isinstance(host, str) and (host.startswith("127.") or host in ("localhost", "::1")):
            return real_connect(self, address)
        raise _OutboundBlocked(f"離線測試嘗試連外 {address}")

    monkeypatch.setattr(_socket.socket, "connect", guard)
    monkeypatch.setattr(health, "_xtai_session_checker", lambda: fake_is_session)


def _resp(body, content_type):
    resp = requests.Response()
    resp.status_code = 200
    resp._content = body
    resp.headers["Content-Type"] = content_type
    resp.url = "https://www.taifex.com.tw/x"
    return resp


@pytest.fixture
def taifex(monkeypatch):
    """依 URL 派發的假期交所；回傳 (routes, calls)，測試改 routes 換回應。"""
    routes = {tp.FUT_URL: (FUT_OK, CSV_TYPE), tp.PC_URL: (PC_OK, CSV_TYPE)}
    calls = []

    def fake_send(method, url, **kwargs):
        calls.append((method, url, kwargs.get("data")))
        if url not in routes:
            raise _OutboundBlocked(f"未登記的 URL：{url}")
        route = routes[url]
        if isinstance(route, BaseException):
            raise route
        return _resp(*route)

    monkeypatch.setattr(http, "_send", fake_send)
    return routes, calls


def _run(capsys, *argv, **kwargs):
    rc = tp.main(list(argv), **kwargs)
    return rc, capsys.readouterr().out


def _drop_date(raw, date_text):
    return b"\r\n".join(line for line in raw.split(b"\r\n") if not line.startswith(date_text.encode()))


def _fut_csv(rows):
    header = FUT_OK.split(b"\r\n")[0].decode("cp950")
    lines = [header] + [f"{d},臺股期貨,外資及陸資,1,1,1,1,0,0,1,1,1,1,{net},1" for d, net in rows]
    return ("\r\n".join(lines) + "\r\n").encode("cp950")


def _pc_csv(rows):
    header = PC_HEADER_ONLY.decode("cp950").strip()
    lines = [header] + [f"{d},1,1,{vol},1,1,{oi}," for d, oi, vol in rows]
    return ("\r\n".join(lines) + "\r\n").encode("cp950")


# --- 解析 ---------------------------------------------------------------------

def test_parse_fut_takes_foreign_txf_net_oi_only():
    rows = tp.parse_fut(FUT_OK.decode("cp950"))
    assert rows[-2:] == [(datetime.date(2026, 10, 19), -91145), (datetime.date(2026, 10, 20), -89748)]
    assert len(rows) == 6  # 自營商、投信的列沒有混進來


def test_parse_pc_sorts_newest_first_response_and_ignores_trailing_comma():
    rows = tp.parse_pc(PC_OK.decode("cp950"))
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)
    assert rows[-1] == (datetime.date(2026, 10, 20), 66.17, 129.06)
    assert rows[-2][:2] == (datetime.date(2026, 10, 19), 61.60)


def test_header_change_is_reported_as_format_mismatch(capsys, taifex):
    routes, _ = taifex
    routes[tp.FUT_URL] = (FUT_OK.decode("cp950").replace("多空未平倉口數淨額", "淨額").encode("cp950"), CSV_TYPE)
    rc, out = _run(capsys, "--as-of", "2026-10-20")
    assert rc == 0
    assert "⚠ 外資台指期淨未平倉：不可用（格式不符" in out
    assert "66.17%" in out


# --- 主流程 -------------------------------------------------------------------

def test_happy_path_prints_level_change_and_pc(capsys, taifex):
    rc, out = _run(capsys, "--as-of", "2026-10-20")
    assert rc == 0
    assert "外資台指期淨未平倉（大台 TXF，不含小台）：-89,748 口（10/19 -91,145 → 10/20，+1,397，空單減少）" in out
    assert "臺指選擇權 P/C 未平倉比：66.17%（10/19 61.60%，+4.57pp）；成交量 P/C 129.06%" in out
    assert "不可用" not in out


def test_stale_response_prints_reason_not_numbers(capsys, taifex):
    """回應最新是 10/20、預期場次 10/21：無法證明新鮮，任何數字都不能印。"""
    rc, out = _run(capsys, "--as-of", "2026-10-21")
    assert rc == 0
    assert out.count("≠ 預期場次 2026-10-21") == 2
    assert "89,748" not in out and "66.17" not in out


@pytest.mark.parametrize("body, message", [
    (FUT_DATEERROR, "日期時間錯誤 DateTime error"),
    (FUT_NODATA, "查無資料"),
])
def test_taifex_alert_page_is_unavailable_with_its_message(capsys, taifex, body, message):
    routes, _ = taifex
    routes[tp.FUT_URL] = (body, HTML_TYPE)
    rc, out = _run(capsys, "--as-of", "2026-10-20")
    assert rc == 0
    assert f"⚠ 外資台指期淨未平倉：不可用（期交所回應：錯誤頁 alert：{message}）" in out
    assert "89,748" not in out
    assert "66.17%" in out  # 另一端點照常


def test_pc_header_only_is_not_printed_as_zero(capsys, taifex):
    routes, _ = taifex
    routes[tp.PC_URL] = (PC_HEADER_ONLY, CSV_TYPE)
    rc, out = _run(capsys, "--as-of", "2026-10-20")
    assert rc == 0
    assert "⚠ 臺指選擇權 P/C：不可用（期交所回應：只有表頭" in out
    assert "0.00%" not in out
    assert "-89,748 口" in out


def test_one_endpoint_connection_failure_does_not_drop_the_other(capsys, taifex):
    routes, _ = taifex
    routes[tp.FUT_URL] = requests.ConnectionError("boom")
    rc, out = _run(capsys, "--as-of", "2026-10-20")
    assert rc == 0
    assert "⚠ 外資台指期淨未平倉：不可用（連線失敗：ConnectionError）" in out
    assert "臺指選擇權 P/C 未平倉比：66.17%" in out


def test_no_calendar_skips_block_without_any_request(capsys, taifex, monkeypatch):
    _, calls = taifex
    monkeypatch.setattr(health, "_xtai_session_checker", lambda: None)
    rc, out = _run(capsys, now=datetime.datetime(2026, 10, 20, 18, 0))
    assert rc == 0
    assert "⚠ 交易日曆不可用，期交所區塊略過" in out
    assert calls == []


def test_query_end_date_is_the_session_not_today(capsys, taifex):
    """10/20 08:00（盤前）：預期場次是 10/19，迄日填 10/19；填今天以後期交所整筆報錯。"""
    _, calls = taifex
    _run(capsys, now=datetime.datetime(2026, 10, 20, 8, 0))
    sent = {url: data for _, url, data in calls}
    assert sent[tp.FUT_URL] == {"queryStartDate": "2026/10/05", "queryEndDate": "2026/10/19", "commodityId": "TXF"}
    assert sent[tp.PC_URL] == {"queryStartDate": "2026/10/05", "queryEndDate": "2026/10/19"}


def test_expected_session_after_cutoff_accepts_same_day_data(capsys, taifex):
    rc, out = _run(capsys, now=datetime.datetime(2026, 10, 20, 18, 0))
    assert rc == 0
    assert "預期場次 2026-10-20" in out and "-89,748 口" in out


# --- 日變化只在相鄰時才算 ---------------------------------------------------------

def test_change_suppressed_when_previous_row_is_not_previous_session(capsys, taifex):
    routes, _ = taifex
    routes[tp.FUT_URL] = (_drop_date(FUT_OK, "2026/10/19"), CSV_TYPE)
    routes[tp.PC_URL] = (_drop_date(PC_OK, "2026/10/19"), CSV_TYPE)
    rc, out = _run(capsys, "--as-of", "2026-10-20")
    assert rc == 0
    assert "-89,748 口（10/20；不列日變化：前一列 2026-10-16 非前一交易日 2026-10-19，變化跨多日）" in out
    assert "66.17%（10/20；不列日變化：前一列 2026-10-16 非前一交易日 2026-10-19" in out
    assert "空單" not in out and "pp" not in out


def test_change_across_holiday_uses_injected_calendar(capsys, taifex):
    """10/09、10/10 休市：10/08 → 10/12 是相鄰場次，要算日變化（週一~五的猜法會說不相鄰）。"""
    routes, _ = taifex
    routes[tp.FUT_URL] = (_fut_csv([("2026/10/08", -1000), ("2026/10/12", -1500)]), CSV_TYPE)
    routes[tp.PC_URL] = (_pc_csv([("2026/10/12", "70.00", "90.00"), ("2026/10/08", "65.50", "80.00")]), CSV_TYPE)
    rc, out = _run(capsys, "--as-of", "2026-10-12")
    assert rc == 0
    assert "-1,500 口（10/08 -1,000 → 10/12，-500，空單增加）" in out   # 日期一律 MM/DD 補零
    assert "70.00%（10/08 65.50%，+4.50pp）" in out
    assert "跨月結算" not in out  # 非結算週不加註


def test_no_calendar_with_as_of_prints_level_without_change(capsys, taifex, monkeypatch):
    monkeypatch.setattr(health, "_xtai_session_checker", lambda: None)
    rc, out = _run(capsys, "--as-of", "2026-10-20")
    assert rc == 0
    assert "-89,748 口（10/20；不列日變化：交易日曆不可用" in out
    assert "+1,397" not in out
    assert "⚠ 交易日曆不可用，未檢查是否落在結算週" in out


# --- 結算週 -------------------------------------------------------------------

def test_settlement_week_note_on_day_before_settlement(capsys, taifex):
    """2026-10-21 是十月第三個週三（結算日），10/20 的變化含轉倉效應。"""
    rc, out = _run(capsys, "--as-of", "2026-10-20")
    assert "⚠ 跨月結算，未平倉變化含結算／轉倉效應" in out


def test_settlement_postponed_when_third_wednesday_is_holiday():
    holiday = {datetime.date(2026, 10, 21)}

    def is_session(day):
        return day.weekday() < 5 and day not in holiday

    assert tp.settlement_session(2026, 10, is_session) == datetime.date(2026, 10, 22)
    assert tp.settlement_session(2026, 10, fake_is_session) == datetime.date(2026, 10, 21)
    assert tp.near_settlement(datetime.date(2026, 10, 23), is_session) is True
    assert tp.near_settlement(datetime.date(2026, 10, 23), fake_is_session) is False
    assert tp.near_settlement(datetime.date(2026, 10, 19), fake_is_session) is False


# --- --json（journal 可直接照抄的值） ----------------------------------------------

def _json(capsys, *argv, **kwargs):
    import json

    rc, out = _run(capsys, "--json", *argv, **kwargs)
    assert rc == 0
    return json.loads(out)          # stdout 只有一個 JSON 物件，否則這裡就會炸


def test_json_happy_path_matches_journal_fields(capsys, taifex):
    got = _json(capsys, "--as-of", "2026-10-20")
    assert got == {"session": "2026-10-20", "foreign_fut_oi": -89748, "foreign_fut_oi_chg": 1397,
                   "pc_oi_ratio": 0.6617, "reasons": {},
                   "notes": ["⚠ 跨月結算，未平倉變化含結算／轉倉效應"]}


def test_json_stale_response_is_null_with_reasons(capsys, taifex):
    got = _json(capsys, "--as-of", "2026-10-21")
    assert got["foreign_fut_oi"] is None and got["foreign_fut_oi_chg"] is None and got["pc_oi_ratio"] is None
    assert set(got["reasons"]) == {"foreign_fut_oi", "foreign_fut_oi_chg", "pc_oi_ratio"}
    assert all("≠ 預期場次 2026-10-21" in r for r in got["reasons"].values())


def test_json_one_endpoint_down_keeps_the_other(capsys, taifex):
    routes, _ = taifex
    routes[tp.PC_URL] = (PC_HEADER_ONLY, CSV_TYPE)
    got = _json(capsys, "--as-of", "2026-10-20")
    assert got["foreign_fut_oi"] == -89748 and got["pc_oi_ratio"] is None
    assert "只有表頭" in got["reasons"]["pc_oi_ratio"] and "foreign_fut_oi" not in got["reasons"]


def test_json_change_is_null_when_the_previous_row_is_not_adjacent(capsys, taifex):
    routes, _ = taifex
    routes[tp.FUT_URL] = (_drop_date(FUT_OK, "2026/10/19"), CSV_TYPE)
    got = _json(capsys, "--as-of", "2026-10-20")
    assert got["foreign_fut_oi"] == -89748 and got["foreign_fut_oi_chg"] is None
    assert "非前一交易日" in got["reasons"]["foreign_fut_oi_chg"]


def test_json_without_calendar_is_all_null_and_sends_nothing(capsys, taifex, monkeypatch):
    _, calls = taifex
    monkeypatch.setattr(health, "_xtai_session_checker", lambda: None)
    got = _json(capsys, now=datetime.datetime(2026, 10, 20, 18, 0))
    assert got["session"] is None and calls == []
    assert got["foreign_fut_oi"] is None and got["foreign_fut_oi_chg"] is None and got["pc_oi_ratio"] is None
    assert all("交易日曆不可用" in r for r in got["reasons"].values()) and len(got["reasons"]) == 3
