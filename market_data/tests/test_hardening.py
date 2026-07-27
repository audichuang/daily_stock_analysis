"""Regressions for the audit hardening: partial-day repair, financials
fail-fast, duplicate-key dedupe, CLI validation, local-median thin days."""

import contextlib
from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import text

from market_data import cli, crawl, health


def _price_frame(stocks, d):
    return pd.DataFrame({
        "stock_id": stocks,
        "date": pd.to_datetime(d),
        "收盤價": [100.0] * len(stocks),
    }).set_index(["stock_id", "date"])


def test_crawl_day_replace_repairs_partial_day(pg_conn, monkeypatch):
    d = date(1900, 3, 1)  # 遠古日期,与真實資料隔離
    pg_conn.execute(text(
        "INSERT INTO market.price (stock_id, date, close) VALUES ('JUNK', :d, 227)"),
        {"d": d})
    monkeypatch.setattr(crawl, "_price_all",
                        lambda day, expected=None: _price_frame(["2330", "2317"], day))
    n = crawl.crawl_day(pg_conn, "price", d, replace=True)
    assert n == 2
    rows = pg_conn.execute(text(
        "SELECT stock_id FROM market.price WHERE date = :d ORDER BY stock_id"),
        {"d": d}).fetchall()
    # 舊的錯位殘留列必須被換血清掉,upsert 蓋不掉鍵不同的髒列
    assert [r[0] for r in rows] == ["2317", "2330"]


def test_crawl_day_replace_keeps_data_when_fetch_fails(pg_conn, monkeypatch):
    d = date(1900, 3, 2)
    pg_conn.execute(text(
        "INSERT INTO market.price (stock_id, date, close) VALUES ('KEEP', :d, 1)"),
        {"d": d})
    monkeypatch.setattr(crawl, "_price_all", lambda day, expected=None: None)
    assert crawl.crawl_day(pg_conn, "price", d, replace=True) == 0
    kept = pg_conn.execute(text(
        "SELECT COUNT(*) FROM market.price WHERE date = :d"), {"d": d}).scalar()
    assert kept == 1  # 來源掛掉不得清掉既有資料


def test_crawl_day_replace_refuses_garbage_payload(pg_conn, monkeypatch):
    # 來源回非空但全是壞 stock_id -> 有效列為 0,不得先刪好資料
    d = date(1900, 3, 4)
    pg_conn.execute(text(
        "INSERT INTO market.price (stock_id, date, close) VALUES ('GOOD', :d, 1)"),
        {"d": d})
    monkeypatch.setattr(crawl, "_price_all",
                        lambda day, expected=None: _price_frame(["電子工業合計指數彙總"], day))
    assert crawl.crawl_day(pg_conn, "price", d, replace=True) == 0
    assert pg_conn.execute(text(
        "SELECT COUNT(*) FROM market.price WHERE date=:d"), {"d": d}).scalar() == 1


def test_crawl_day_replace_refuses_massive_shrink(pg_conn, monkeypatch):
    d = date(1900, 3, 5)
    for s in ("A100", "A200", "A300", "A400"):
        pg_conn.execute(text(
            "INSERT INTO market.price (stock_id, date, close) VALUES (:s, :d, 1)"),
            {"s": s, "d": d})
    monkeypatch.setattr(crawl, "_price_all",
                        lambda day, expected=None: _price_frame(["2330"], day))
    assert crawl.crawl_day(pg_conn, "price", d, replace=True) == 0  # 1 < 4*0.5
    assert pg_conn.execute(text(
        "SELECT COUNT(*) FROM market.price WHERE date=:d"), {"d": d}).scalar() == 4


def test_upsert_dedupes_at_writer_level(pg_conn):
    # 去重在 upsert 本體:valuation/index 等直呼路徑同樣受保護
    from market_data import models
    from market_data.writer import upsert

    n = upsert(pg_conn, models.Price.__table__,
               [{"stock_id": "T901", "date": "1900-03-06", "close": 1},
                {"stock_id": "T901", "date": "1900-03-06", "close": 2}],
               ["stock_id", "date"])
    assert n == 1
    val = pg_conn.execute(text(
        "SELECT close FROM market.price WHERE stock_id='T901'")).scalar()
    assert float(val) == 2.0  # keep last


def _fake_frames(stocks, d):
    df = pd.DataFrame({"stock_id": stocks, "date": pd.to_datetime(d),
                       "營業收入合計": 1.0}).set_index(["stock_id", "date"])
    cum = df.copy()
    cum.columns = ["累計營業收入合計"]
    return {"balance_sheet": df, "income_sheet": df.iloc[0:0],
            "income_sheet_cumulate": cum, "cash_flows": df}


def test_crawl_financials_q4_fails_without_q3_and_writes_nothing(
        engine, monkeypatch):
    frames = _fake_frames(["2330", "2317"], "1900-03-31")
    monkeypatch.setattr(crawl.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(crawl.financial_statement, "pack_htmls",
                        lambda y, s, directory: frames)
    rmtree_calls = []
    monkeypatch.setattr(crawl.shutil, "rmtree",
                        lambda *a, **k: rmtree_calls.append(a))
    with pytest.raises(RuntimeError, match="Q3"):
        crawl.crawl_financials(engine, 1899, 4, min_stocks=0)
    assert not rmtree_calls  # 失敗必須保留下載檔
    with engine.connect() as c:
        n = c.execute(text(
            "SELECT COUNT(*) FROM market.financial_statement "
            "WHERE date = '1900-03-31'")).scalar()
    assert n == 0  # 整季回滾,不留半套資料


def test_crawl_financials_partial_quarter_fails(engine, monkeypatch):
    monkeypatch.setattr(crawl.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(crawl.financial_statement, "pack_htmls",
                        lambda y, s, directory: _fake_frames(["2330"], "1900-05-15"))
    with pytest.raises(RuntimeError, match="partial"):
        crawl.crawl_financials(engine, 1900, 1)  # 預設 min_stocks=1000


def test_store_dedupes_duplicate_keys(pg_conn, monkeypatch):
    d = date(1900, 3, 3)

    def dup_fetch(day):
        return pd.DataFrame({
            "stock_id": ["2330", "2330"], "date": pd.to_datetime(d),
            "外資買賣超股數": [111, 222], "投信買賣超股數": [1, 2],
            "自營商買賣超股數": [0, 0], "三大法人買賣超股數": [112, 224],
        }).set_index(["stock_id", "date"])

    monkeypatch.setattr(crawl.sources, "crawl_institutional", dup_fetch)
    assert crawl.crawl_day(pg_conn, "institutional", d) == 1  # 去重,不炸 ON CONFLICT
    val = pg_conn.execute(text(
        "SELECT foreign_net FROM market.institutional "
        "WHERE stock_id='2330' AND date=:d"), {"d": d}).scalar()
    assert val == 222  # keep="last"


def test_cli_rejects_malformed_month():
    for bad in ("2026/06", "2026-6-1x", "junk"):
        with pytest.raises(SystemExit):  # argparse 層擋下,連 DB 都不碰
            cli.main(["revenue", "--month", bad])


def test_thin_days_uses_local_median():
    days = [(date(2026, 1, i + 1), 2000) for i in range(20)]
    days[10] = (date(2026, 1, 11), 1160)  # TPEx 整邊缺:剩 58%,舊版 0.5 門檻抓不到
    flagged = health.thin_days(days)
    assert flagged == [("2026-01-11", 1160)]


def test_thin_days_tolerates_slow_listing_growth():
    # 上市家數逐年成長不該誤報(全域中位數的舊病)
    from datetime import timedelta
    d0 = date(2026, 1, 1)
    days = [(d0 + timedelta(days=i), 1000 + i * 5) for i in range(60)]
    assert health.thin_days(days) == []


class _FakeEngine:
    """crawl_range 只用 engine.begin() 當 context manager。"""

    @contextlib.contextmanager
    def begin(self):
        yield None


def test_crawl_range_only_requests_known_trading_days(monkeypatch):
    seen = []
    # 2024 春節休市 2/6~2/14 是連續 7 個平日;只有 2/5、2/15 是交易日
    cal = {date(2024, 2, 5), date(2024, 2, 15)}
    monkeypatch.setattr(crawl, "_trading_dates", lambda conn, s, e: cal)
    monkeypatch.setattr(crawl, "crawl_day",
                        lambda conn, source, d, replace=False: seen.append(d) or 1)
    dates = [date(2024, 2, 5) + __import__("datetime").timedelta(days=i)
             for i in range(11)]
    crawl.crawl_range(_FakeEngine(), "valuation", dates, resume=False)
    assert seen == sorted(cal)  # 假日一個請求都不該發


def test_crawl_range_raises_on_blocked_streak(monkeypatch):
    """過濾掉假日之後,連續零列只剩「被封鎖/端點改版」一種解釋,不能安靜跳完。"""
    monkeypatch.setattr(crawl, "_trading_dates",
                        lambda conn, s, e: {date(2026, 3, d) for d in range(2, 21)})
    monkeypatch.setattr(crawl, "crawl_day", lambda *a, **k: 0)
    days = [date(2026, 3, d) for d in range(2, 21)]
    with pytest.raises(RuntimeError, match="consecutive trading days returned 0"):
        crawl.crawl_range(_FakeEngine(), "valuation", days, resume=False)


def test_crawl_range_streak_threshold_is_looser_without_calendar():
    """price 自己就是日曆來源,沒有日曆可過濾假日,零列還有「國定假日」這個正常解釋。

    門檻必須高過最長的連續平日休市(2024 春節 2/6~2/14 是 7 個平日),否則跨春節回補
    price 會被誤判成 IP 封鎖而中止。
    """
    assert crawl._MAX_EMPTY_STREAK_NO_CALENDAR > 7
    assert crawl._MAX_EMPTY_STREAK_NO_CALENDAR > crawl._MAX_EMPTY_STREAK

    seen = []

    def fake_day(conn, source, d, replace=False):
        seen.append(d)
        return 0

    import unittest.mock as _m
    with _m.patch.object(crawl, "crawl_day", fake_day), \
         _m.patch.object(crawl, "_trading_dates", lambda conn, s, e: set()):
        # 2/5~2/15 共 9 個平日(含春節休市的 7 個)全部零列,不該中止
        days = [date(2024, 2, 5) + timedelta(days=i) for i in range(11)]
        crawl.crawl_range(_FakeEngine(), "price", days, resume=False)
    assert len(seen) == 9                          # 週末仍然跳過,不浪費請求
    assert all(d.weekday() < 5 for d in seen)
