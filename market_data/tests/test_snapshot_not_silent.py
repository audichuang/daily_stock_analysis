"""快照路徑不得靜默:失敗與「資料還沒發布」必須印出**可區分**的原因。

背景:2026-07-28 18:10 跑 `cli snapshot` 完全沒有輸出、DB 也沒變,得逐層讀
`cli.snapshot` → `crawl.crawl_index` → `sources._openapi_json` 三處原始碼才確認
真因是 FMTQIK 當日尚未發布,而不是 IP 被封或端點改版。三種處置完全不同的情況
不能長得一樣,所以把「印出原因」釘在測試裡。
"""

import pytest

from market_data import crawl, sources

_URL = "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK"
_REQUIRED = {"Date", "TAIEX", "Change", "TradeValue"}


class _FakeEngine:
    """`crawl_snapshots` 收 engine：`begin()` 給寫入交易、`connect()` 給稽核查詢。

    兩者刻意是**不同物件**，用來釘住「稽核不在寫入交易裡跑」——在同一個交易裡跑
    `SELECT max(date)` 而失敗會讓 Postgres 把交易標成 aborted，吞掉例外並不會修復它，
    只會讓下一句 upsert 以「current transaction is aborted」失敗並回滾全部。
    """

    def __init__(self, latest):
        self._latest = latest
        self.begun = 0
        self.connected = 0

    def begin(self):
        self.begun += 1
        return _FakeConn(self._latest)

    def connect(self):
        self.connected += 1
        return _FakeConn(self._latest)


class _FakeConn:
    def __init__(self, latest):
        self._latest = latest

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a, **k): return self
    def scalar(self): return self._latest


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_openapi_json_reports_each_failure_mode(monkeypatch, capsys):
    """連線失敗 / HTTP 非 200 / 非 JSON 三者都回 None,但訊息必須不同。"""
    seen = []
    for resp, expect in [
        (None, "no response"),
        (_Resp(status=503, text="oops"), "HTTP 503"),
        (_Resp(status=200, payload=None, text="<html>maintenance</html>"), "non-JSON"),
    ]:
        monkeypatch.setattr(sources, "requests_get", lambda *a, **k: resp)
        assert sources._openapi_json(_URL) is None
        out = capsys.readouterr().out
        assert expect in out, f"expected {expect!r} in {out!r}"
        assert _URL in out          # 訊息要指得出是哪個端點
        seen.append(out)
    assert len(set(seen)) == 3, "三種失敗模式的訊息必須互相可區分"


def test_valid_rows_distinguishes_not_published_from_shape_change(capsys):
    # 空 list = TWSE 當日還沒發布 → 入夜重跑即可
    assert sources._valid_rows([], _REQUIRED, _URL) is None
    assert "尚未發布" in capsys.readouterr().out

    # 缺欄位 = 端點改版 → 要改程式,且要點名缺哪些 key
    assert sources._valid_rows([{"Date": "1150728"}], _REQUIRED, _URL) is None
    out = capsys.readouterr().out
    assert "missing keys" in out and "TAIEX" in out

    # 正常資料原封不動放行
    ok = [{k: "x" for k in _REQUIRED}]
    assert sources._valid_rows(ok, _REQUIRED, _URL) == ok
    assert capsys.readouterr().out == ""


def test_valid_rows_does_not_double_warn(monkeypatch, capsys):
    """`_openapi_json` 已印過原因時,`_valid_rows` 不得再印第二次。"""
    monkeypatch.setattr(sources, "requests_get", lambda *a, **k: None)
    data = sources._openapi_json(_URL)
    capsys.readouterr()                       # 丟掉第一層的訊息
    assert sources._valid_rows(data, _REQUIRED, _URL) is None
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("rows", [0, 1330])
def test_crawl_snapshots_always_prints_a_line_per_source(monkeypatch, capsys, rows):
    """0 列也要印——少了這一行就退回全靜默,而 0 列正是要人去查的那個訊號。"""
    for fn in ("crawl_valuation", "crawl_index", "crawl_stock_info"):
        monkeypatch.setattr(crawl, fn, lambda conn, _n=rows: _n)

    eng = _FakeEngine("2026-07-27")
    out_map = crawl.crawl_snapshots(eng)
    printed = capsys.readouterr().out
    assert out_map == {"valuation": rows, "index": rows, "stock_info": rows}
    for name in ("valuation", "index", "stock_info"):
        assert f"{name} {rows:,} rows" in printed
    # 有日期維度的兩張表要一併報最新日期,否則列數相同時分不出當日有沒有進來
    assert printed.count("latest 2026-07-27") == 2
    # 三步各自一個交易:共用一個的話,第三步一 raise 會把前兩步已宣稱寫入的列一起回滾
    assert eng.begun == 3
    # 稽核走獨立連線(兩張有日期的表各一次),不在寫入交易裡
    assert eng.connected == 2


def test_snapshot_latest_runs_outside_the_write_transaction():
    """稽核查詢必須開自己的連線。

    在寫入交易裡跑 `SELECT max(date)` 而失敗時,Postgres 會把整個交易標成 aborted——
    吞掉例外**不會**修復它,只會讓下一句 upsert 以「current transaction is aborted」失敗
    並回滾前面所有寫入。這裡釘住它走 `engine.connect()`,不是寫入用的那條交易。
    """
    eng = _FakeEngine("2026-07-27")
    assert crawl._snapshot_latest(eng, "index") == ", latest 2026-07-27"
    assert eng.connected == 1 and eng.begun == 0
    assert crawl._snapshot_latest(eng, "stock_info") == ""   # 無日期欄,不該白開連線
    assert eng.connected == 1


def test_snapshot_latest_failure_degrades_instead_of_breaking_the_crawl():
    """稽核自己壞掉時只降級成 `latest unknown`——它是報告用的,不該拖垮爬取。"""

    class _Boom:
        def connect(self, *a, **k):
            raise RuntimeError("no such table")

    assert crawl._snapshot_latest(_Boom(), "index") == ", latest unknown (RuntimeError)"


# ---- crawl_index 依回補窗口逐月抓(T05) -------------------------------------------

from datetime import date  # noqa: E402


def _month_rows(*days):
    return [{"Date": f"{d.year - 1911:03d}{d.month:02d}{d.day:02d}", "TAIEX": "20,000.00",
             "Change": "1.00", "TradeValue": "1,000"} for d in days]


@pytest.fixture
def index_env(monkeypatch):
    """釘住「今天」、關掉月間 sleep、記錄 fetch_index 呼叫並收集被 upsert 的日期。"""
    calls, upserted = [], []
    monkeypatch.setattr(crawl, "_today", lambda: date(2026, 10, 5))
    monkeypatch.setattr(crawl, "_INDEX_MONTH_DELAY_SECONDS", 0)

    def fake_fetch(asof=None, fallback=True):
        calls.append((asof, fallback))
        return _month_rows(date(asof.year, asof.month, 1), asof)

    monkeypatch.setattr(sources, "fetch_index", fake_fetch)
    monkeypatch.setattr(crawl, "upsert",
                        lambda conn, table, recs, pk, **kw: upserted.extend(r["date"] for r in recs) or len(recs))
    return calls, upserted


def test_crawl_index_fetches_each_month_in_the_window(index_env):
    calls, upserted = index_env
    dates = [date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)]
    crawl.crawl_index(None, dates)
    # 9 月以「該月在窗口中最後一天」為 asof 且不准 openapi fallback;10 月（當月）用今天且允許
    assert calls == [(date(2026, 9, 30), False), (date(2026, 10, 5), True)]
    assert any(str(d).startswith("2026-09-30") for d in upserted)    # 9/30 的列被寫入


def test_crawl_index_same_month_fetches_once(index_env):
    calls, _ = index_env
    crawl.crawl_index(None, [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)])
    assert calls == [(date(2026, 10, 5), True)]


def test_crawl_index_without_dates_fetches_current_month_only(index_env):
    calls, _ = index_env
    crawl.crawl_index(None)
    assert calls == [(date(2026, 10, 5), True)]


def test_crawl_index_dedupes_rows_and_survives_a_failed_past_month(index_env, monkeypatch):
    calls, upserted = index_env
    monkeypatch.setattr(sources, "fetch_index",
                        lambda asof=None, fallback=True: None if asof.month == 9
                        else _month_rows(date(2026, 10, 1), date(2026, 10, 1)))
    n = crawl.crawl_index(None, [date(2026, 9, 30), date(2026, 10, 1)])
    assert n == 1 and len(upserted) == 1          # 上月失敗不拖垮當月;同日期去重


def test_crawl_snapshots_passes_dates_only_to_index(monkeypatch):
    seen = {}
    monkeypatch.setattr(crawl, "crawl_valuation", lambda conn: seen.setdefault("val", 0))
    monkeypatch.setattr(crawl, "crawl_stock_info", lambda conn: seen.setdefault("info", 0))
    monkeypatch.setattr(crawl, "crawl_index",
                        lambda conn, dates=None: seen.update(idx=dates) or 0)
    window = [date(2026, 9, 30), date(2026, 10, 1)]
    crawl.crawl_snapshots(_FakeEngine("2026-10-01"), window)
    assert seen["idx"] == window
