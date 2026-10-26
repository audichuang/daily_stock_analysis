"""集保股權分散：開放資料與個股查詢頁的解析、入庫，以及 daily 的只報不擋。"""

import pathlib
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import text

from market_data import crawl, sources

_FX = pathlib.Path(__file__).parent / "fixtures"


def _opendata():
    return (_FX / "tdcc_opendata.csv").read_text(encoding="utf-8-sig")


def test_opendata_parses_levels_and_strips_padded_codes():
    df = sources.parse_tdcc_opendata(_opendata())
    row = df[(df.stock_id == "3324") & (df.level == 15)].iloc[0]
    # 2026-10-16 雙鴻千張大戶：9 人、31,628,646 股、33.75%
    assert (row.date, row.holders, row.shares, row.pct) == (
        pd.Timestamp(2026, 10, 16), 9, 31628646, 33.75)
    assert set(df[df.stock_id == "3324"].level) == set(range(1, 18))


def test_opendata_rejects_changed_header():
    with pytest.raises(ValueError, match="表頭"):
        sources.parse_tdcc_opendata(_opendata().replace("持股分級", "分級", 1))


def test_query_page_maps_total_to_level_17():
    html = (_FX / "tdcc_query_3324.html").read_text()
    df = sources.parse_tdcc_query(html, "3324", "20260911")
    assert df.date.unique().tolist() == [pd.Timestamp(2026, 9, 11)]
    total = df[df.level == 17].iloc[0]
    assert total.pct == 100.0 and 16 not in set(df.level)   # 這週沒有差異數調整列
    assert df[df.level == 15].iloc[0].shares > 0


def test_query_page_rejects_a_different_week():
    html = (_FX / "tdcc_query_3324.html").read_text()
    assert sources.parse_tdcc_query(html, "3324", "20260918") is None


@pytest.mark.parametrize("invalid", [
    "115年02月30日", "115年13月11日", "10000年09月11日", "100000000000年09月11日",
])
def test_query_invalid_roc_date_is_rejected_without_raising(invalid, capsys):
    html = (_FX / "tdcc_query_3324.html").read_text()
    assert sources.parse_tdcc_query(html.replace("115年09月11日", invalid), "3324", "20260911") is None
    assert "**WARN" in capsys.readouterr().out
    # 反向：日期合法時，保留真實表格與數值。
    df = sources.parse_tdcc_query(html, "3324", "20260911")
    assert df is not None and df.date.unique().tolist() == [pd.Timestamp(2026, 9, 11)]
    assert df[df.level == 17].iloc[0].pct == 100.0


def test_crawl_holding_dist_upserts_and_warns_when_stale(pg_conn, monkeypatch, capsys):
    df = sources.parse_tdcc_opendata(_opendata())
    df["date"] = pd.Timestamp(2099, 1, 2)      # 遠離真實資料（本機連正式庫，交易會 rollback）
    monkeypatch.setattr(crawl.sources, "fetch_tdcc_latest", lambda: df)

    n, latest = crawl.crawl_holding_dist(pg_conn, asof=date(2099, 1, 5))
    assert (n, latest) == (len(df), date(2099, 1, 2))
    assert "**WARN" not in capsys.readouterr().out
    pct = pg_conn.execute(text(
        "SELECT pct FROM market.holding_dist WHERE stock_id='3324' AND date='2099-01-02' "
        "AND level=15")).scalar()
    assert float(pct) == 33.75

    crawl.crawl_holding_dist(pg_conn, asof=date(2099, 1, 2 + crawl.HOLDING_STALE_DAYS + 1))
    assert "停在 2099-01-02" in capsys.readouterr().out


def test_one_stock_backfilled_does_not_block_the_full_market_week(pg_conn, monkeypatch):
    df = sources.parse_tdcc_opendata(_opendata())
    df["date"] = pd.Timestamp(2099, 1, 9)
    # holding-history 先寫了 3324 這一週（只有一檔）
    crawl._store_holding(pg_conn, df[df.stock_id == "3324"])
    monkeypatch.setattr(crawl.sources, "fetch_tdcc_latest", lambda: df)

    n, _ = crawl.crawl_holding_dist(pg_conn, asof=date(2099, 1, 10))
    assert n == len(df), "單檔回補不能讓全市場那週被跳過"
    assert crawl.crawl_holding_dist(pg_conn, asof=date(2099, 1, 10))[0] == 0   # 整週已齊才跳過


def test_history_keeps_rotating_token_after_a_week_fails_to_parse(monkeypatch):
    """TDCC 的 token 每次請求後輪換；某週解析失敗也要先換 token，否則後面每週都失敗。"""
    good = (_FX / "tdcc_query_3324.html").read_text()            # 2026-09-11 那週
    page = ('<input name="SYNCHRONIZER_TOKEN" value="T0" />'
            '<option value="20260918">x</option><option value="20260911">x</option>')
    broken = '<input name="SYNCHRONIZER_TOKEN" value="T1" />資料日期：115年09月18日 （沒有表格）'
    sent = []

    class _Resp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    class _Session:
        headers = {}

        def get(self, url, timeout):
            return _Resp(page)

        def post(self, url, data, timeout):
            sent.append(data["SYNCHRONIZER_TOKEN"])
            if data["SYNCHRONIZER_TOKEN"] != ("T0" if len(sent) == 1 else "T1"):
                return _Resp("")                                  # 作廢的 token：伺服端回空
            return _Resp(broken if len(sent) == 1 else good)

    monkeypatch.setattr(sources.requests, "Session", _Session)
    df = sources.crawl_tdcc_history("3324", delay=0)
    assert sent == ["T0", "T1"], "第一週解析失敗後，第二週要帶回應裡的新 token"
    assert df is not None and df.date.unique().tolist() == [pd.Timestamp(2026, 9, 11)]


class _TdccSession:
    """模擬 TDCC：token 每次請求（含逾時但已送達的）後輪換，只有最新的有效；GET 查詢頁給最新 token。"""

    def __init__(self, weeks, timeout_on=()):
        self.weeks, self.timeout_on = weeks, set(timeout_on)
        self.headers, self.n, self.gets, self.sent = {}, 0, 0, []
        good = (_FX / "tdcc_query_3324.html").read_text()        # 資料日期 115年09月11日
        self.pages = {w: good.replace("115年09月11日", f"{int(w[:4]) - 1911}年{w[4:6]}月{w[6:]}日")
                      for w in weeks}

    def _token(self):
        return f"T{self.n}"

    def get(self, url, timeout):
        self.gets += 1
        opts = "".join(f'<option value="{w}">x</option>' for w in self.weeks)
        return _FakeResp(f'<input name="SYNCHRONIZER_TOKEN" value="{self._token()}" />{opts}')

    def post(self, url, data, timeout):
        tok, want = data["SYNCHRONIZER_TOKEN"], data["scaDate"]
        self.sent.append(tok)
        valid = tok == self._token()
        self.n += 1                                               # 請求送達即輪換
        if want in self.timeout_on and len(self.sent) == 1:
            raise sources.requests.Timeout("Read timed out")
        head = f'<input name="SYNCHRONIZER_TOKEN" value="{self._token()}" />'
        return _FakeResp(head + (self.pages[want] if valid else ""))


class _FakeResp:
    def __init__(self, text, error=None):
        self.text, self.error = text, error

    def raise_for_status(self):
        if self.error:
            raise self.error


@pytest.mark.parametrize("invalid", ["115年02月30日", "100000000000年09月18日"])
def test_history_skips_bad_roc_week_and_keeps_both_neighbours(monkeypatch, capsys, invalid):
    ses = _TdccSession(["20260925", "20260918", "20260911"])
    ses.pages["20260918"] = ses.pages["20260918"].replace("115年09月18日", invalid)
    monkeypatch.setattr(sources.requests, "Session", lambda: ses)
    df = sources.crawl_tdcc_history("3324", delay=0)
    assert ses.sent == ["T0", "T1", "T2"] and ses.gets == 1
    assert df is not None and sorted(df.date.unique().tolist()) == [
        pd.Timestamp(2026, 9, 11), pd.Timestamp(2026, 9, 25),
    ]
    assert "**WARN" in capsys.readouterr().out


def test_history_refreshes_token_after_a_timed_out_week(monkeypatch, capsys):
    """逾時的請求已送達伺服器、token 已輪換：不重取 token，下一週會帶作廢 token 靜默遺失。"""
    ses = _TdccSession(["20260918", "20260911"], timeout_on={"20260918"})
    monkeypatch.setattr(sources.requests, "Session", lambda: ses)
    df = sources.crawl_tdcc_history("3324", delay=0)
    assert ses.sent == ["T0", "T1"], "逾時後要重新 GET 取得新 token，再送下一週"
    assert ses.gets == 2
    assert df is not None and df.date.unique().tolist() == [pd.Timestamp(2026, 9, 11)]
    assert "20260918 失敗" in capsys.readouterr().out


def test_history_does_not_refetch_token_when_every_week_succeeds(monkeypatch):
    """反向：沒有失敗就沿用回應裡輪換的 token，不該每週多打一次 GET。"""
    ses = _TdccSession(["20260918", "20260911"])
    monkeypatch.setattr(sources.requests, "Session", lambda: ses)
    df = sources.crawl_tdcc_history("3324", delay=0)
    assert ses.gets == 1 and ses.sent == ["T0", "T1"]
    assert sorted(df.date.unique().tolist()) == [pd.Timestamp(2026, 9, 11), pd.Timestamp(2026, 9, 18)]


# 實測 2026-10-23：代號 9999（不存在）與帶作廢 token 的 3324，回的頁面除了 token 與回填的
# 表單值之外逐字相同——「資料日期：」後面是空的，表格只有一列「查無此資料」。
_NO_DATA_PAGE = """<input type="hidden" name="SYNCHRONIZER_TOKEN" value="T9" id="SYNCHRONIZER_TOKEN" />
<span class="font" style="font-size: 0.813em;">資料日期：</span>
<table class="table"><thead><tr><th>序</th><th>持股/單位數分級</th><th>人數</th>
<th>股數/單位數</th><th>占集保庫存數比例 (%)</th></tr></thead>
<tr><td align="center" colspan="5"><span class="font" style="color: #ff0000;">查無此資料</span></td></tr>
</table>"""


def test_query_page_without_data_date_is_rejected_quietly(capsys):
    """單頁分不出原因（代號錯／無資料／token 作廢），拒收但不逐週印，由呼叫端彙總。"""
    assert sources.parse_tdcc_query(_NO_DATA_PAGE, "9999", "20260911") is None
    assert capsys.readouterr().out == ""


class _NoDataSession(_TdccSession):
    """查無此資料：每週都回「查無此資料」頁（代號打錯的實際長相）。"""

    def __init__(self, weeks, data_weeks=()):
        super().__init__(weeks)
        self.data_weeks = set(data_weeks)

    def post(self, url, data, timeout):
        self.n += 1
        want = data["scaDate"]
        head = f'<input name="SYNCHRONIZER_TOKEN" value="{self._token()}" />'
        return _FakeResp(head + (self.pages[want] if want in self.data_weeks else _NO_DATA_PAGE))


def test_history_summarises_no_data_weeks_in_one_warning(monkeypatch, capsys):
    """代號打錯時 51 週都回查無此資料：只印一條 WARN（附週數與範圍），不歸因成 token 作廢。"""
    weeks = ["20260925", "20260918", "20260911"]
    monkeypatch.setattr(sources.requests, "Session", lambda: _NoDataSession(weeks))
    assert sources.crawl_tdcc_history("9999", delay=0) is None
    warns = [ln for ln in capsys.readouterr().out.splitlines() if "**WARN" in ln]
    assert warns == ["**WARN: 集保查詢 9999 有 3 週回「查無此資料」(20260911~20260925),拒收;"
                     "請確認代號是否正確"], warns


def test_history_no_data_weeks_beside_good_weeks_still_warn(monkeypatch, capsys):
    """反向：部分週次有資料時，缺的那幾週仍要留痕，且不能把整檔說成代號錯。"""
    weeks = ["20260918", "20260911"]
    monkeypatch.setattr(sources.requests, "Session",
                        lambda: _NoDataSession(weeks, data_weeks={"20260911"}))
    df = sources.crawl_tdcc_history("3324", delay=0)
    assert df is not None and df.date.unique().tolist() == [pd.Timestamp(2026, 9, 11)]
    out = capsys.readouterr().out
    assert "**WARN: 集保查詢 3324 有 1 週回「查無此資料」(20260918~20260918)" in out
    assert "token 作廢" in out and "代號是否正確" not in out


class _RefetchFails(_TdccSession):
    """第一週逾時，之後重新 GET 查詢頁也失敗（``mode``）：raise／HTTP 錯誤／頁面沒有 token。"""

    def __init__(self, weeks, mode):
        super().__init__(weeks, timeout_on={weeks[0]})
        self.mode = mode

    def get(self, url, timeout):
        if self.gets == 0:
            return super().get(url, timeout)
        self.gets += 1
        if self.mode == "raise":
            raise sources.requests.ConnectionError("refused")
        if self.mode == "http":
            # 5xx 頁面上剛好也有 token：raise_for_status 必須擋下，不能拿這個 token 繼續送
            return _FakeResp(f'<input name="SYNCHRONIZER_TOKEN" value="{self._token()}" />',
                             error=sources.requests.HTTPError("503 Server Error"))
        return _FakeResp("<html>maintenance</html>")


@pytest.mark.parametrize("mode, reason", [
    ("raise", "refused"), ("http", "503 Server Error"), ("no_token", "查詢頁找不到 token")])
def test_history_warns_when_token_refetch_fails(monkeypatch, capsys, mode, reason):
    ses = _RefetchFails(["20260918", "20260911"], mode)
    monkeypatch.setattr(sources.requests, "Session", lambda: ses)
    sources.crawl_tdcc_history("3324", delay=0)
    assert ses.gets == 2
    assert ses.sent == ["T0", "T0"], "重取失敗就沿用舊 token（不能換成錯誤頁上的 token）"
    out = capsys.readouterr().out
    assert f"**WARN: 集保查詢 3324 無法重取 token ({reason}),後續週次可能全數拒收" in out


def test_crawl_holding_dist_fetch_failure_writes_nothing(pg_conn, monkeypatch):
    monkeypatch.setattr(crawl.sources, "fetch_tdcc_latest", lambda: None)
    assert crawl.crawl_holding_dist(pg_conn) == (0, None)
