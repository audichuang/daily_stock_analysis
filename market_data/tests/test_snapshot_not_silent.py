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


class _FakeConn:
    """只需要應付 `_snapshot_latest` 的一句 SELECT max(date)。"""

    def __init__(self, latest):
        self._latest = latest

    def execute(self, *a, **k):
        return self

    def scalar(self):
        return self._latest


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

    out_map = crawl.crawl_snapshots(conn=_FakeConn("2026-07-27"))
    printed = capsys.readouterr().out
    assert out_map == {"valuation": rows, "index": rows, "stock_info": rows}
    for name in ("valuation", "index", "stock_info"):
        assert f"{name} {rows:,} rows" in printed
    # 有日期維度的兩張表要一併報最新日期,否則列數相同時分不出當日有沒有進來
    assert printed.count("latest 2026-07-27") == 2


def test_snapshot_latest_failure_does_not_break_the_crawl(capsys):
    """稽核查詢自己壞掉時只降級成 `latest unknown`,不能讓整個快照失敗。"""

    class _Boom:
        def execute(self, *a, **k):
            raise RuntimeError("no such table")

    assert crawl._snapshot_latest(_Boom(), "index") == ", latest unknown (RuntimeError)"
    assert crawl._snapshot_latest(_Boom(), "stock_info") == ""   # 本來就無日期欄
