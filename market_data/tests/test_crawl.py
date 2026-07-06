from datetime import date

import pandas as pd
from sqlalchemy import text

from market_data import crawl


def test_crawl_day_institutional_fetch_transform_upsert(pg_conn, monkeypatch):
    # fetch returns finlab-style Chinese columns; crawl should transform+store
    def fake(d):
        # real fetchers return frames indexed by (stock_id, date)
        return pd.DataFrame([{
            "stock_id": "2330", "date": pd.to_datetime(d), "名稱": "台積電",
            "外陸資買賣超股數(不含外資自營商)": 12345, "外資買賣超股數": None,
            "投信買賣超股數": 100, "自營商買賣超股數": 50, "三大法人買賣超股數": 12495,
        }]).set_index(["stock_id", "date"])

    monkeypatch.setattr(crawl.sources, "crawl_institutional", fake)
    n = crawl.crawl_day(pg_conn, "institutional", date(2024, 6, 3))
    assert n == 1
    row = pg_conn.execute(text(
        "SELECT foreign_net, total_net FROM market.institutional "
        "WHERE stock_id='2330' AND date='2024-06-03'"
    )).fetchone()
    assert row == (12345, 12495)


def test_crawl_day_skips_footer_rows(pg_conn, monkeypatch):
    def fake(d):
        return pd.DataFrame([
            {"stock_id": "2330", "date": pd.to_datetime(d), "三大法人買賣超股數": 1},
            {"stock_id": "說明：外陸資不含外資自營商", "date": pd.to_datetime(d),
             "三大法人買賣超股數": None},
        ]).set_index(["stock_id", "date"])

    monkeypatch.setattr(crawl.sources, "crawl_institutional", fake)
    n = crawl.crawl_day(pg_conn, "institutional", date(2024, 6, 4))
    assert n == 1  # footer note row dropped


def test_crawl_day_drops_null_stock_id(pg_conn, monkeypatch):
    # a null stock_id must NOT survive as the string "nan"
    def fake(d):
        return pd.DataFrame([
            {"stock_id": "2330", "date": pd.to_datetime(d), "三大法人買賣超股數": 1},
            {"stock_id": None, "date": pd.to_datetime(d), "三大法人買賣超股數": 2},
        ]).set_index(["stock_id", "date"])

    monkeypatch.setattr(crawl.sources, "crawl_institutional", fake)
    n = crawl.crawl_day(pg_conn, "institutional", date(2024, 6, 5))
    assert n == 1  # null stock_id row dropped, not stored as "nan"
    bad = pg_conn.execute(text(
        "SELECT count(*) FROM market.institutional WHERE stock_id='nan'"
    )).scalar()
    assert bad == 0


def test_price_all_requires_both_markets(monkeypatch):
    twse = pd.DataFrame([{"stock_id": "2330", "date": pd.to_datetime("2024-06-03"),
                          "收盤價": 590.0}]).set_index(["stock_id", "date"])
    otc = pd.DataFrame([{"stock_id": "6488", "date": pd.to_datetime("2024-06-03"),
                         "收盤價": 900.0}]).set_index(["stock_id", "date"])

    # both present -> merged
    monkeypatch.setattr(crawl.crawler, "crawl_price", lambda d: twse)
    monkeypatch.setattr(crawl.sources, "crawl_tpex_price", lambda d: otc)
    out = crawl._price_all(date(2024, 6, 3))
    assert set(out.reset_index()["stock_id"]) == {"2330", "6488"}

    # OTC fetch failed (None) -> skip the whole day, no partial write
    monkeypatch.setattr(crawl.sources, "crawl_tpex_price", lambda d: None)
    assert crawl._price_all(date(2024, 6, 3)) is None


def test_crawl_monthly_revenue_derives_month_key(pg_conn, monkeypatch):
    def fake(month):
        return pd.DataFrame([{
            "stock_id": "2330", "date": pd.to_datetime("2024-02-10"),
            "當月營收": 2000000, "去年同月增減(%)": 12.3, "上月比較增減(%)": -1.1,
        }]).set_index(["stock_id", "date"])

    monkeypatch.setattr(crawl.crawler, "crawl_monthly_report", fake)
    n = crawl.crawl_monthly_revenue(pg_conn, date(2024, 1, 1))
    assert n == 1
    row = pg_conn.execute(text(
        "SELECT revenue FROM market.monthly_revenue "
        "WHERE stock_id='2330' AND revenue_month='2024-01-01'"  # 營收所屬月
    )).fetchone()
    assert row[0] == 2000000
