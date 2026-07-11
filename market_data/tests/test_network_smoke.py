"""Live smoke tests against TWSE/TPEx endpoints (pytest -m network only).

Catches the two real incident classes: source endpoints changing/truncating,
and the panel silently falling back to yfinance instead of Postgres.
"""

import datetime

import pytest

from market_data import crawler, sources

pytestmark = pytest.mark.network


def _recent_days(n=10):
    today = datetime.date.today()
    return [today - datetime.timedelta(days=i) for i in range(1, n + 1)]


def test_price_both_markets_fetch_a_recent_trading_day():
    for d in _recent_days():
        twse = crawler.crawl_price(d)
        otc = sources.crawl_tpex_price(d)
        if twse is not None and len(twse) and otc is not None and len(otc):
            assert len(twse) > 500 and len(otc) > 300
            assert "2330" in twse.reset_index()["stock_id"].values
            return
    pytest.fail("no trading day with both TWSE+TPEx price in the last 10 days")


def test_price_backup_source_fetches_latest_trading_day():
    for d in _recent_days():
        df = sources.crawl_price_backup(d)
        if df is not None:
            assert len(df) > 500
            assert "2330" in df.reset_index()["stock_id"].values
            return
    pytest.fail("STOCK_DAY_ALL backup matched no day in the last 10 days")


def test_institutional_and_margin_fetch_a_recent_trading_day():
    for d in _recent_days():
        inst = sources.crawl_institutional(d)
        if inst is not None and len(inst):
            assert len(inst) > 500
            mar = sources.crawl_margin(d)
            assert mar is not None and len(mar) > 500
            return
    pytest.fail("no trading day with institutional data in the last 10 days")


def test_tw_history_routes_through_market_db():
    # 全鏈驗證:面板取台股歷史必須走本地 Postgres,而非靜默降級 yfinance。
    # 缺 psycopg 必須 fail 不能 skip——「venv 缺 psycopg -> 熔斷 -> yfinance
    # 幽靈非交易日 K 棒」正是這支測試要抓的事故;只在無 DB 連線設定(如公網
    # CI 摸不到內網 DB)時才明確 skip。
    import os

    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not configured; market DB unreachable here")
    import psycopg  # noqa: F401  缺 driver = 事故,直接 ImportError fail

    from data_provider.base import DataFetcherManager

    df, source = DataFetcherManager().get_daily_data("2330.TW", days=5)
    assert source == "MarketDBFetcher"
    assert df is not None and len(df) >= 3
