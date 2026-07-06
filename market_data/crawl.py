"""Crawl orchestration: fetch (finlab logic) -> etl transform -> upsert Postgres.

Replaces finlab's sqlite pipeline. Daily/date-based sources go through
``crawl_day``; ``crawl_range`` loops dates and skips ones already stored.
"""

import pandas as pd
from sqlalchemy import BigInteger, Integer, text

from market_data import crawler, etl, models, sources
from market_data.writer import upsert

_VALID_ID = r"[0-9A-Za-z]{2,10}"


def _price_all(d):
    """上市 (TWSE) + 上櫃 (TPEx) 合併。兩者都要有資料才回傳,否則回 None:
    若只有一邊成功就寫入,resume 會把該日標記完成、另一邊永久缺(TWSE/TPEx 同交易
    日),所以任一邊失敗就整天跳過,靠 date-not-in-table 下次重試。"""
    twse = crawler.crawl_price(d)
    otc = sources.crawl_tpex_price(d)
    if twse is None or not len(twse) or otc is None or not len(otc):
        return None
    return pd.concat([twse, otc])


# date-based daily sources: name -> (fetch(date), transform, model, pk)
DAILY = {
    "price": (_price_all, etl.transform_price, models.Price, ["stock_id", "date"]),
    "institutional": (lambda d: sources.crawl_institutional(d),
                      etl.transform_institutional, models.Institutional,
                      ["stock_id", "date"]),
    "margin": (lambda d: sources.crawl_margin(d), etl.transform_margin,
               models.Margin, ["stock_id", "date"]),
}


def _to_records(df, table, filter_stock_id=True):
    df = df.copy()
    if filter_stock_id:
        sid = df["stock_id"]
        mask = sid.notna() & sid.astype(str).str.fullmatch(_VALID_ID)
        df = df[mask].copy()
    if df.empty:
        return []
    for c in table.columns:
        if isinstance(c.type, (Integer, BigInteger)) and c.name in df:
            df[c.name] = pd.to_numeric(df[c.name], errors="coerce").astype("Int64")
    df = df.astype(object).where(pd.notna(df), None)
    return df.to_dict("records")


def _records(df, table):
    return _to_records(df, table, filter_stock_id=True)


def _store(conn, raw, transform, model, pk):
    if raw is None or not len(raw):
        return 0
    # finlab fetchers return frames indexed by (stock_id[, date]); the etl
    # transforms expect those as columns.
    if raw.index.names and raw.index.names[0] is not None:
        raw = raw.reset_index()
    recs = _records(transform(raw), model.__table__)
    return upsert(conn, model.__table__, recs, pk)


def crawl_day(conn, source, d):
    fetch, transform, model, pk = DAILY[source]
    return _store(conn, fetch(d), transform, model, pk)


def crawl_monthly_revenue(conn, month_date):
    return _store(conn, crawler.crawl_monthly_report(month_date),
                  etl.transform_monthly_revenue, models.MonthlyRevenue,
                  ["stock_id", "revenue_month"])


def crawl_stock_info(conn):
    return _store(conn, sources.crawl_stock_info(), etl.transform_stock_info,
                  models.StockInfo, ["stock_id"])


def crawl_ex_dividend(conn, start, end):
    return _store(conn, sources.crawl_ex_dividend(start, end),
                  etl.transform_ex_dividend, models.ExDividend, ["stock_id", "date"])


def crawl_valuation(conn):
    rows = sources.fetch_valuation()
    if not rows:
        return 0
    df = etl.transform_valuation(rows).reset_index()
    recs = _to_records(df, models.Valuation.__table__, filter_stock_id=True)
    return upsert(conn, models.Valuation.__table__, recs, ["stock_id", "date"])


def crawl_index(conn):
    rows = sources.fetch_index()
    if not rows:
        return 0
    df = etl.transform_index(rows).reset_index()
    recs = _to_records(df, models.MarketIndex.__table__, filter_stock_id=False)
    return upsert(conn, models.MarketIndex.__table__, recs, ["index_id", "date"])


def daily_update(engine=None, asof=None, days=5):
    """Operational entry (replaces finlab's backfill): refresh the last ``days``
    trading days of daily sources + the daily snapshots. Resumable/idempotent."""
    import datetime as _dt

    from market_data.db import get_engine

    eng = engine or get_engine()
    asof = asof or _dt.date.today()
    dates = [asof - _dt.timedelta(days=i) for i in range(days)]
    for source in ("price", "institutional", "margin"):
        crawl_range(eng, source, dates)
    with eng.begin() as conn:
        crawl_valuation(conn)
        crawl_index(conn)
        crawl_stock_info(conn)


def _existing_dates(conn, table):
    rows = conn.execute(text(f"SELECT DISTINCT date FROM market.{table}")).fetchall()
    return {r[0].isoformat() for r in rows}


def crawl_range(engine, source, dates, resume=True):
    """Crawl a list of dates for a daily source, upserting each; skips dates
    already present when resume=True. Returns rows written."""
    table = DAILY[source][2].__tablename__
    total = 0
    with engine.begin() as conn:
        have = _existing_dates(conn, table) if resume else set()
    for d in dates:
        if resume and d.isoformat() in have:
            continue
        with engine.begin() as conn:
            total += crawl_day(conn, source, d)
    return total
