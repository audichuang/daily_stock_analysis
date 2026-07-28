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
