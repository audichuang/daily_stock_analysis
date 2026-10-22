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


def test_crawl_holding_dist_fetch_failure_writes_nothing(pg_conn, monkeypatch):
    monkeypatch.setattr(crawl.sources, "fetch_tdcc_latest", lambda: None)
    assert crawl.crawl_holding_dist(pg_conn) == (0, None)
