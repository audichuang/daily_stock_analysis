"""market_data/taifex.py：期交所法人臺股期貨未平倉入庫（抓取／解析／資料日檢查離線，upsert 走 pg_conn）。

fixture 沿用 `tests/fixtures/` 下 2026-10-20 實測回應的原始位元組（cp950 CSV、UTF-8 錯誤頁），
mock 接縫是 `tw_official_http._send`，錯誤頁判斷走真正的 `error_reason`。
交易日曆一律注入假的 ``is_session``（國慶 10/09、10/10 休市），不讀牆鐘。
"""

import datetime
import importlib.util
from pathlib import Path

import pytest
import requests
from sqlalchemy import text

from market_data import taifex
from market_data import tw_official_http as http

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
FUT_OK = (FIXTURES / "taifex_fut_txf_20261013_20261020.bin").read_bytes()
FUT_NODATA = (FIXTURES / "taifex_fut_nodata.bin").read_bytes()
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "e4f7a2c9b1d3_add_taifex_fut_oi.py"
CSV_TYPE = "text/html;charset=MS950"
HTML_TYPE = "text/html;charset=UTF-8"
HOLIDAYS = {datetime.date(2026, 10, 9), datetime.date(2026, 10, 10)}
D = datetime.date
TPE = datetime.timezone(datetime.timedelta(hours=8))


def fake_is_session(day):
    return day.weekday() < 5 and day not in HOLIDAYS


def _resp(body, content_type):
    resp = requests.Response()
    resp.status_code = 200
    resp._content = body
    resp.headers["Content-Type"] = content_type
    resp.url = "https://www.taifex.com.tw/x"
    return resp


@pytest.fixture
def taifex_http(monkeypatch):
    """假期交所：``route`` 換回應，``calls`` 記錄送出的表單。"""
    state = {"route": (FUT_OK, CSV_TYPE), "calls": []}

    def fake_send(method, url, **kwargs):
        assert url == taifex.FUT_URL
        state["calls"].append(kwargs.get("data"))
        route = state["route"]
        if isinstance(route, BaseException):
            raise route
        return _resp(*route)

    monkeypatch.setattr(http, "_send", fake_send)
    return state


class _Conn:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Eng:
    def begin(self): return _Conn()


@pytest.fixture
def stored(monkeypatch):
    """攔下 `taifex.store`，記錄要寫入的列（離線測試不碰 DB）。"""
    batches = []
    monkeypatch.setattr(taifex, "store", lambda conn, recs: batches.append(list(recs)) or len(recs))
    return batches


def _update(asof=None, now=datetime.datetime(2026, 10, 20, 20, 0, tzinfo=TPE)):
    lines = []
    n = taifex.update(_Eng(), asof=asof, now=now, is_session=fake_is_session, out=lines.append)
    return n, "\n".join(lines)


def _fut_csv(rows):
    header = FUT_OK.split(b"\r\n")[0].decode("cp950")
    lines = [header] + [f"{d},臺股期貨,{who},1,1,1,1,0,0,10,100,20,200,-10,-100" for d, who in rows]
    return ("\r\n".join(lines) + "\r\n").encode("cp950")


ALL = ("自營商", "投信", "外資及陸資")


# --- 解析與資料日檢查 -----------------------------------------------------------

def test_parse_keeps_every_identity_with_oi_columns():
    rows = taifex.parse_fut_rows(FUT_OK.decode("cp950"))
    assert len(rows) == 18                       # 6 個交易日 × 3 身份別
    foreign = [r for r in rows if r["identity"] == "foreign"]
    assert foreign[-1] == {"date": D(2026, 10, 20), "commodity_id": "TXF", "identity": "foreign",
                           **{k: foreign[-1][k] for k in taifex._OI_COLUMNS.values()}}
    assert foreign[-1]["net_oi"] == -89748
    assert foreign[-1]["long_oi"] - foreign[-1]["short_oi"] == foreign[-1]["net_oi"]
    first = foreign[0]
    assert (first["date"], first["long_oi"], first["short_oi"], first["net_oi_amount"]) == \
        (D(2026, 10, 13), 10640, 97879, -844623509)


def test_parse_rejects_unknown_identity_and_missing_column():
    with pytest.raises(ValueError, match="身份別"):
        taifex.parse_fut_rows(_fut_csv([("2026/10/20", "外資")]).decode("cp950"))
    bad = FUT_OK.decode("cp950").replace("空方未平倉口數", "空方口數")
    with pytest.raises(ValueError, match="表頭缺欄位"):
        taifex.parse_fut_rows(bad)


def _rows(*dates, who=ALL):
    return taifex.parse_fut_rows(_fut_csv([(d, w) for d in dates for w in who]).decode("cp950"))


def test_guard_rejects_whole_payload_with_date_outside_window():
    rows = _rows("2026/10/19", "2026/10/21")
    with pytest.raises(ValueError, match="窗口"):
        taifex.guard_rows(rows, D(2026, 10, 6), D(2026, 10, 20))
    with pytest.raises(ValueError, match="窗口"):
        taifex.guard_rows(_rows("2026/10/05", "2026/10/19"), D(2026, 10, 6), D(2026, 10, 20))


def test_guard_accepts_window_edges():
    """反向：邊界日（起日、迄日當天）不能被當成窗口外拒收。"""
    kept, incomplete = taifex.guard_rows(_rows("2026/10/06", "2026/10/20"), D(2026, 10, 6), D(2026, 10, 20))
    assert {r["date"] for r in kept} == {D(2026, 10, 6), D(2026, 10, 20)}
    assert incomplete == [] and len(kept) == 6


def test_guard_drops_only_dates_missing_an_identity():
    rows = _rows("2026/10/19") + _rows("2026/10/20", who=("自營商", "外資及陸資"))
    kept, incomplete = taifex.guard_rows(rows, D(2026, 10, 6), D(2026, 10, 20))
    assert incomplete == [D(2026, 10, 20)]
    assert {r["date"] for r in kept} == {D(2026, 10, 19)} and len(kept) == 3


def test_guard_rejects_conflicting_duplicates_but_tolerates_exact_ones():
    rows = _rows("2026/10/20")
    kept, _ = taifex.guard_rows(rows + [dict(rows[0])], D(2026, 10, 6), D(2026, 10, 20))
    assert len(kept) == 3
    with pytest.raises(ValueError, match="不同的值"):
        taifex.guard_rows(rows + [{**rows[0], "net_oi": 999}], D(2026, 10, 6), D(2026, 10, 20))


# --- 開關與場次 ----------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (None, False), ("", False), ("false", False), ("0", False), ("no", False),
    ("true", True), ("1", True), (" TRUE ", True), ("on", True),
])
def test_persist_flag_defaults_off(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv(taifex.FLAG_ENV, raising=False)
    else:
        monkeypatch.setenv(taifex.FLAG_ENV, value)
    assert taifex.persist_enabled() is expected


def test_target_session_never_uses_unclosed_today():
    morning = datetime.datetime(2026, 10, 20, 7, 30, tzinfo=TPE)
    # daily 傳 asof=今天，但 07:30 還沒收盤：迄日要退到前一交易日，否則期交所回「日期時間錯誤」
    assert taifex.target_session(D(2026, 10, 20), now=morning, is_session=fake_is_session) == D(2026, 10, 19)
    evening = datetime.datetime(2026, 10, 20, 20, 0, tzinfo=TPE)
    assert taifex.target_session(D(2026, 10, 20), now=evening, is_session=fake_is_session) == D(2026, 10, 20)
    # asof 較早：取 asof 當天或之前最近的交易日（休市日退到前一個）
    assert taifex.target_session(D(2026, 10, 16), now=evening, is_session=fake_is_session) == D(2026, 10, 16)
    assert taifex.target_session(D(2026, 10, 10), now=evening, is_session=fake_is_session) == D(2026, 10, 8)
    assert taifex.target_session(None, now=evening, is_session=fake_is_session) == D(2026, 10, 20)


# --- update：抓取 → 檢查 → 寫入 ---------------------------------------------------

def test_update_writes_rows_under_their_own_dates(taifex_http, stored):
    n, out = _update(asof=D(2026, 10, 20))
    assert taifex_http["calls"] == [{"queryStartDate": "2026/10/06", "queryEndDate": "2026/10/20",
                                     "commodityId": "TXF"}]
    assert n == 18 and len(stored) == 1
    assert sorted({r["date"] for r in stored[0]}) == [D(2026, 10, d) for d in (13, 14, 15, 16, 19, 20)]
    assert "taifex_fut_oi 18 rows, latest 2026-10-20" in out
    assert "WARN" not in out


def test_update_stale_payload_keeps_old_dates_and_warns(taifex_http, stored):
    """端點停在 10/20、但預期場次已是 10/21：照寫 10/20 以前（帶原日期），另印停更 WARN。"""
    n, out = _update(now=datetime.datetime(2026, 10, 21, 20, 0, tzinfo=TPE))
    assert taifex_http["calls"][0]["queryEndDate"] == "2026/10/21"
    assert n == 18 and max(r["date"] for r in stored[0]) == D(2026, 10, 20)
    assert "**WARN taifex_fut_oi: 最新一列 2026-10-20 ≠ 預期場次 2026-10-21" in out


@pytest.mark.parametrize("route, reason", [
    ((FUT_NODATA, HTML_TYPE), "查無資料"),
    (requests.ConnectionError("boom"), "連線失敗"),
    ((_fut_csv([("2026/10/22", w) for w in ALL]), CSV_TYPE), "窗口"),
])
def test_update_data_problems_warn_and_write_nothing(taifex_http, stored, route, reason):
    taifex_http["route"] = route
    n, out = _update()
    assert n == 0 and stored == []
    assert "**WARN taifex_fut_oi" in out and reason in out


def test_update_without_calendar_skips_before_any_request(monkeypatch, taifex_http, stored):
    from market_data import health
    monkeypatch.setattr(health, "_xtai_session_checker", lambda: None)
    lines = []
    assert taifex.update(_Eng(), out=lines.append) == 0
    assert taifex_http["calls"] == [] and stored == []
    assert "交易日曆不可用" in lines[0]


def test_update_db_error_propagates(taifex_http, monkeypatch):
    """DB 錯誤（例如正式庫未 migration）不吞：由 daily_update 那層決定只報不擋。"""
    def boom(conn, recs):
        raise RuntimeError("relation market.taifex_fut_oi does not exist")
    monkeypatch.setattr(taifex, "store", boom)
    with pytest.raises(RuntimeError, match="does not exist"):
        _update()


# --- migration 降版護欄 -----------------------------------------------------------

def _load_migration(monkeypatch, rows):
    spec = importlib.util.spec_from_file_location("_mig_taifex", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dropped = []

    class _Bind:
        def execute(self, stmt):
            class _R:
                def scalar_one(self): return rows
            return _R()

    class _Op:
        def get_bind(self): return _Bind()
        def drop_table(self, name, schema=None): dropped.append((schema, name))

    monkeypatch.setattr(mod, "op", _Op())
    return mod, dropped


def test_downgrade_refuses_non_empty_table(monkeypatch):
    mod, dropped = _load_migration(monkeypatch, 3)
    with pytest.raises(RuntimeError, match="拒絕降版"):
        mod.downgrade()
    assert dropped == []


def test_downgrade_drops_empty_table(monkeypatch):
    mod, dropped = _load_migration(monkeypatch, 0)
    mod.downgrade()
    assert dropped == [("market", "taifex_fut_oi")]


# --- 真的 upsert（pg_conn rollback；本機要先開 scratch 庫並跑到 head） -----------------

def _stored_rows(conn):
    return conn.execute(text(
        "SELECT date, identity, net_oi FROM market.taifex_fut_oi "
        "WHERE date BETWEEN '2099-01-01' AND '2099-12-31' ORDER BY date, identity")).fetchall()


def test_store_upserts_idempotently_and_takes_corrections(pg_conn):
    rows = _rows("2099/10/19", "2099/10/20")
    assert taifex.store(pg_conn, rows) == 6
    assert taifex.store(pg_conn, rows) == 6           # 重跑同一窗口不重複
    got = _stored_rows(pg_conn)
    assert len(got) == 6 and got[0] == (D(2099, 10, 19), "dealer", -10)
    corrected = [{**r, "net_oi": -42} if r["identity"] == "foreign" and r["date"] == D(2099, 10, 20) else r
                 for r in rows]
    taifex.store(pg_conn, corrected)
    assert (D(2099, 10, 20), "foreign", -42) in _stored_rows(pg_conn)
    assert len(_stored_rows(pg_conn)) == 6
