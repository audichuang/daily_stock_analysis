from datetime import date

import pandas as pd

from market_data import crawl, etl


def _frame(n, d=date(2024, 6, 3)):
    return pd.DataFrame({
        "stock_id": [f"S{i:04d}" for i in range(n)],
        "date": pd.to_datetime(d),
        "收盤價": 100.0,
    }).set_index(["stock_id", "date"])


def test_price_all_passes_when_count_plausible(monkeypatch):
    monkeypatch.setattr(crawl.crawler, "crawl_price", lambda d: _frame(60))
    monkeypatch.setattr(crawl.sources, "crawl_tpex_price", lambda d: _frame(40))
    out = crawl._price_all(date(2024, 6, 3), expected=100)
    assert len(out) == 100


def test_price_all_truncated_twse_recovered_by_backup(monkeypatch):
    monkeypatch.setattr(crawl.crawler, "crawl_price", lambda d: _frame(30))  # 截斷
    monkeypatch.setattr(crawl.sources, "crawl_tpex_price", lambda d: _frame(40))
    monkeypatch.setattr(crawl.sources, "crawl_price_backup", lambda d: _frame(55))
    out = crawl._price_all(date(2024, 6, 3), expected=100)
    assert len(out) == 95  # 55 backup + 40 otc


def test_price_all_skips_day_when_backup_unavailable(monkeypatch):
    monkeypatch.setattr(crawl.crawler, "crawl_price", lambda d: _frame(30))
    monkeypatch.setattr(crawl.sources, "crawl_tpex_price", lambda d: _frame(40))
    monkeypatch.setattr(crawl.sources, "crawl_price_backup", lambda d: None)
    assert crawl._price_all(date(2024, 6, 3), expected=100) is None


def test_price_all_no_expected_keeps_legacy_behavior(monkeypatch):
    # 空庫回補第一天沒有中位數可比,行為同舊版:兩市場非空即收
    monkeypatch.setattr(crawl.crawler, "crawl_price", lambda d: _frame(3))
    monkeypatch.setattr(crawl.sources, "crawl_tpex_price", lambda d: _frame(2))
    assert len(crawl._price_all(date(2024, 6, 3), expected=None)) == 5


def _seed_price_days(pg_conn, days):
    from sqlalchemy import text
    for d, n in days:
        for i in range(n):
            pg_conn.execute(text(
                "INSERT INTO market.price (stock_id, date, close) "
                "VALUES (:s, :d, 1)"), {"s": f"T{i:04d}", "d": d})


# 種子放 1900 年代:真實資料最早 2010,查詢窗完全隔離,結果與 DB 現況無關
def test_recent_price_median_prefers_prior_days(pg_conn):
    _seed_price_days(pg_conn, (("1900-01-02", 3), ("1900-01-03", 5),
                               ("1900-01-04", 4), ("1900-01-05", 6),
                               ("1900-01-06", 7)))
    assert crawl._recent_price_median(pg_conn, date(1900, 1, 7)) == 5


def test_recent_price_median_falls_back_to_later_days(pg_conn):
    # daily_update 由新到舊迭代/空庫 bootstrap:之前沒資料要能用之後的日期當基準
    # (種滿 5 天,LIMIT 5 才不會撈到 2010 起的真實資料)
    _seed_price_days(pg_conn, (("1900-01-03", 5), ("1900-01-04", 4),
                               ("1900-01-05", 6), ("1900-01-06", 3),
                               ("1900-01-07", 7)))
    assert crawl._recent_price_median(pg_conn, date(1900, 1, 2)) == 5
    assert crawl._recent_price_median(pg_conn, date(1899, 1, 1)) == 5


def test_crawl_price_backup_rejects_other_days_data(monkeypatch):
    from market_data import sources
    rows = [{"Date": "1130601", "Code": "2330", "ClosingPrice": "900",
             "TradeVolume": "1", "TradeValue": "1", "Transaction": "1",
             "OpeningPrice": "1", "HighestPrice": "1", "LowestPrice": "1",
             "Change": "0"}]
    monkeypatch.setattr(sources, "_openapi_json", lambda url: rows)
    # 端點只有最新交易日;要 6/3 但端點是 6/1 -> 不可用
    assert sources.crawl_price_backup(date(2024, 6, 3)) is None


def test_crawl_price_backup_rejects_mixed_day_payload(monkeypatch):
    from market_data import sources
    good = {"Date": "1130603", "Code": "2330", "ClosingPrice": "900",
            "TradeVolume": "1", "TradeValue": "1", "Transaction": "1",
            "OpeningPrice": "1", "HighestPrice": "1", "LowestPrice": "1",
            "Change": "0"}
    stale = {**good, "Date": "1130601", "Code": "2317"}
    monkeypatch.setattr(sources, "_openapi_json",
                        lambda url: [good] * 10 + [stale])
    # 混到任何一列別天的資料 -> 整包拒收,不能只丟掉那幾列
    assert sources.crawl_price_backup(date(2024, 6, 3)) is None


def test_price_upsert_coalesce_preserves_pe_ratio(pg_conn):
    from sqlalchemy import text

    from market_data import models
    from market_data.writer import upsert

    t, pk = models.Price.__table__, ["stock_id", "date"]
    upsert(pg_conn, t, [{"stock_id": "T900", "date": "1900-02-01",
                         "close": 10, "pe_ratio": 15.5}], pk)
    # 備援源缺本益比(NULL);coalesce 欄位不得抹掉既有值,其他欄照常更新
    upsert(pg_conn, t, [{"stock_id": "T900", "date": "1900-02-01",
                         "close": 11, "pe_ratio": None}], pk,
           coalesce=("pe_ratio",))
    row = pg_conn.execute(text(
        "SELECT close, pe_ratio FROM market.price "
        "WHERE stock_id='T900' AND date='1900-02-01'")).fetchone()
    assert float(row[0]) == 11.0 and float(row[1]) == 15.5


def test_crawl_price_backup_maps_to_transform_compatible_frame(monkeypatch):
    from market_data import sources
    rows = [{"Date": "1130603", "Code": "2330", "ClosingPrice": "900.5",
             "TradeVolume": "1000", "TradeValue": "900500", "Transaction": "10",
             "OpeningPrice": "899", "HighestPrice": "901", "LowestPrice": "898",
             "Change": "1.5"}]
    monkeypatch.setattr(sources, "_openapi_json", lambda url: rows)
    df = sources.crawl_price_backup(date(2024, 6, 3))
    assert len(df) == 1
    out = etl.transform_price(df.reset_index())
    row = out.iloc[0]
    assert row["stock_id"] == "2330" and row["close"] == 900.5
    assert row["volume"] == 1000 and row["transactions"] == 10
    assert pd.isna(row["pe_ratio"])  # 備援無本益比,補 NA


def _backup_frame(rows):
    idx = pd.MultiIndex.from_tuples(
        [(sid, pd.Timestamp("2026-08-21")) for sid, _ in rows],
        names=["stock_id", "date"])
    return pd.DataFrame(
        {"漲跌價差": [chg for _, chg in rows], "收盤價": [140.5] * len(rows)}, index=idx)


def test_backup_x_shaped_zero_change_is_masked_to_null(pg_conn):
    """STOCK_DAY_ALL 把「無比價」列渲染成 Change='0.0000'，payload 內與真平盤
    無法區分（實測 2026-08-21 的 2458）。藉 DB 前根收盤辨識：有動 ⇒ NULL。"""
    from sqlalchemy import text
    pg_conn.execute(text(
        "INSERT INTO market.price (stock_id, date, open, high, low, close, volume) "
        "VALUES ('ZZ58', '2026-08-20', 146.0, 148.0, 144.0, 146.0, 1), "
        "       ('ZZ17', '2026-08-20', 24.5, 24.6, 24.4, 24.5, 1)"))
    backup = _backup_frame([("ZZ58", 0.0), ("ZZ17", 0.0)])
    backup.at[("ZZ17", pd.Timestamp("2026-08-21")), "收盤價"] = 24.5

    out = crawl._mask_uncomparable_backup_changes(backup.copy(), date(2026, 8, 21), pg_conn)

    # ZZ58 收盤 140.5 vs 前根 146.0 有動 ⇒ X 形狀 ⇒ NULL（對齊主路徑）
    assert pd.isna(out.at[("ZZ58", pd.Timestamp("2026-08-21")), "漲跌價差"])
    # ZZ17 收盤不動 ⇒ 真平盤是讀數，必須保留
    assert out.at[("ZZ17", pd.Timestamp("2026-08-21")), "漲跌價差"] == 0.0


def test_backup_first_day_zero_change_is_masked(pg_conn):
    """該股當天之前沒有任何列 + Change==0 ⇒ 新上市首日的 X 語意 ⇒ NULL。"""
    backup = _backup_frame([("ZZ99", 0.0)])

    out = crawl._mask_uncomparable_backup_changes(backup.copy(), date(2026, 8, 21), pg_conn)

    assert pd.isna(out.at[("ZZ99", pd.Timestamp("2026-08-21")), "漲跌價差"])


def test_backup_nonzero_change_is_never_touched(pg_conn):
    """帶號的非零 Change 是正常讀數，遮罩不得越界。"""
    from sqlalchemy import text

    pg_conn.execute(text(
        "INSERT INTO market.price (stock_id, date, open, high, low, close, volume) "
        "VALUES ('ZZ58', '2026-08-20', 146.0, 148.0, 144.0, 146.0, 1)"))
    backup = _backup_frame([("ZZ58", -5.5)])

    out = crawl._mask_uncomparable_backup_changes(backup.copy(), date(2026, 8, 21), pg_conn)

    assert out.at[("ZZ58", pd.Timestamp("2026-08-21")), "漲跌價差"] == -5.5


def test_price_all_passes_conn_to_backup_masking(monkeypatch, pg_conn):
    """crawl_day 走的呼叫鏈必須真的把 conn 帶進遮罩——否則修復只在單測裡活著。"""
    twse = _frame(30)
    twse["漲跌價差"] = 0.0
    monkeypatch.setattr(crawl.crawler, "crawl_price", lambda d: None)
    monkeypatch.setattr(crawl.sources, "crawl_tpex_price", lambda d: _frame(40))
    captured = {}

    def fake_mask(frame, d, conn):
        captured["conn"] = conn
        return frame

    monkeypatch.setattr(crawl.sources, "crawl_price_backup", lambda d: twse)
    monkeypatch.setattr(crawl, "_mask_uncomparable_backup_changes", fake_mask)
    crawl._price_all(date(2024, 6, 3), expected=None, conn=pg_conn)

    assert captured["conn"] is pg_conn
