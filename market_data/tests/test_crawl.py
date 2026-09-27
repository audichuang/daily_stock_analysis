from datetime import date

import pandas as pd
import pytest
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


def _revenue_frame(stock_id, revenue, announce="2024-02-10"):
    return pd.DataFrame([{
        "stock_id": stock_id, "date": pd.to_datetime(announce),
        "當月營收": revenue, "去年同月增減(%)": 12.3, "上月比較增減(%)": -1.1,
    }]).set_index(["stock_id", "date"])


def test_crawl_monthly_revenue_derives_month_key(pg_conn, monkeypatch):
    def fake(month, market):
        return _revenue_frame("2330", 2000000) if market == "sii" else None

    monkeypatch.setattr(crawl.crawler, "crawl_monthly_report", fake)
    n = crawl.crawl_monthly_revenue(pg_conn, date(2024, 1, 1))
    assert n == 1
    row = pg_conn.execute(text(
        "SELECT revenue FROM market.monthly_revenue "
        "WHERE stock_id='2330' AND revenue_month='2024-01-01'"  # 營收所屬月
    )).fetchone()
    assert row[0] == 2000000


def test_crawl_monthly_revenue_writes_both_markets_and_survives_one_failing(pg_conn, monkeypatch):
    """上櫃月營收曾整段缺席(彙總報表只抓 /sii/),`screen_tw` 的 YoY 門檻因此把整個上櫃
    靜默篩掉。兩個市場都要抓;而其中一邊抓不到時,另一邊照寫。
    種子用 1900 年:本機 pg_conn 連的是正式庫(rollback 交易),真實列不會落進這個月。"""
    asked = []

    def both(month, market):
        asked.append(market)
        return _revenue_frame("1101" if market == "sii" else "6488",
                              111 if market == "sii" else 222, announce="1900-02-10")

    monkeypatch.setattr(crawl.crawler, "crawl_monthly_report", both)
    assert crawl.crawl_monthly_revenue(pg_conn, date(1900, 1, 1)) == 2
    assert asked == ["sii", "otc"]
    rows = dict(pg_conn.execute(text(
        "SELECT stock_id, revenue FROM market.monthly_revenue "
        "WHERE revenue_month='1900-01-01' AND stock_id IN ('1101','6488')")).fetchall())
    assert rows == {"1101": 111, "6488": 222}

    def otc_down(month, market):
        return _revenue_frame("1101", 333, announce="1900-03-10") if market == "sii" else None

    monkeypatch.setattr(crawl.crawler, "crawl_monthly_report", otc_down)
    assert crawl.crawl_monthly_revenue(pg_conn, date(1900, 2, 1)) == 1


def test_crawl_monthly_report_rejects_unknown_market():
    with pytest.raises(ValueError):
        crawl.crawler.crawl_monthly_report(date(2024, 1, 1), market="tw")


def test_partial_quarter_keeps_evidence_but_forces_a_refetch(tmp_path, monkeypatch):
    """家數不足有**兩個**成因，從錯誤點分不出來：截止日前的半季發布，以及解析器
    對不上新版 markup。所以檔案要留著（後者需要它追查），但要標記，讓下次重跑
    重新下載——不標的話，「目錄已存在則沿用」會讓截止日後的重跑再失敗一次。

    實測 2026-08-09（Q2 截止日 8/14 前 5 天）只有 525 檔申報，去年同季 2582 檔。
    """
    import os

    import pandas as pd

    from market_data import crawl

    monkeypatch.chdir(tmp_path)
    directory = os.path.join("data", "financial_statement", "20262")
    os.makedirs(directory)
    open(os.path.join(directory, "2330.html"), "w").close()

    monkeypatch.setattr(
        crawl.financial_statement, "pack_htmls",
        lambda *a, **k: {"balance_sheet": pd.DataFrame(index=["2330", "2317"])},
    )
    downloads = []
    monkeypatch.setattr(crawl.crawler, "crawl_finance_statement2019",
                        lambda y, s: downloads.append((y, s)) or os.makedirs(directory, exist_ok=True))

    with pytest.raises(RuntimeError, match="looks partial or the parser is out of date"):
        crawl.crawl_financials(object(), 2026, 2)

    assert os.path.isdir(directory), "解析失敗時需要這些檔案追查，不能刪"
    assert os.path.exists(os.path.join(directory, ".partial-quarter")), "沒標記 = 重跑會沿用舊的"
    assert downloads == [], "目錄本來就在，第一次不該重新下載"

    # 重跑：標記在 ⇒ 必須重新下載，而不是沿用那份半季
    with pytest.raises(RuntimeError, match="looks partial"):
        crawl.crawl_financials(object(), 2026, 2)
    assert downloads == [(2026, 2)], "帶標記的目錄沒有觸發重新下載"
