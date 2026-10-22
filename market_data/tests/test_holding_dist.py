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
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


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


def test_query_page_without_data_date_warns(capsys):
    """作廢 token 的回應沒有「資料日期」：拒收之外要印 WARN，不能讓整週靜默消失。"""
    assert sources.parse_tdcc_query('<input name="SYNCHRONIZER_TOKEN" value="T9" />', "3324",
                                    "20260911") is None
    assert "**WARN: 集保查詢 3324 20260911 回應沒有資料日期" in capsys.readouterr().out

def test_crawl_holding_dist_fetch_failure_writes_nothing(pg_conn, monkeypatch):
    monkeypatch.setattr(crawl.sources, "fetch_tdcc_latest", lambda: None)
    assert crawl.crawl_holding_dist(pg_conn) == (0, None)
