"""Crawl orchestration: fetch (finlab logic) -> etl transform -> upsert Postgres.

Replaces finlab's sqlite pipeline. Daily/date-based sources go through
``crawl_day``; ``crawl_range`` loops dates and skips ones already stored.
"""

import os
import shutil

import pandas as pd
from sqlalchemy import BigInteger, Integer, text

from market_data import crawler, etl, financial_statement, models, sources
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


_FINANCIAL_PK = ["stock_id", "date", "statement_type", "account"]


def _q4_income_sheet(conn, year, annual_cum):
    """Q4 單季損益 = 年報累計 − Q3 累計(讀 DB)。原 fill_season4 的增量版:
    年報 html 只有累計欄,單季值必須用同年度 Q3 累計(date=year-11-14)回推。"""
    q3 = pd.read_sql(
        text("SELECT stock_id, account, value FROM market.financial_statement "
             "WHERE statement_type='income_sheet_cumulate' AND date = :d"),
        conn, params={"d": f"{year}-11-14"})
    if q3.empty:
        print(f"**WARN: no Q3 {year} cumulate in DB, cannot derive Q4 income sheet")
        return None
    q3w = q3.pivot(index="stock_id", columns="account", values="value").astype(float)
    ann = annual_cum.reset_index().drop(columns=["date"]).set_index("stock_id")
    cols = [c for c in ann.columns if c in q3w.columns]  # 兩邊都是 累計X
    diff = ann[cols].apply(pd.to_numeric, errors="coerce").sub(
        q3w.reindex(ann.index)[cols])
    diff.columns = [c[2:] for c in cols]  # strip 累計 prefix
    diff["date"] = pd.to_datetime(f"{year + 1}-03-31")
    return diff.reset_index().set_index(["stock_id", "date"])


def crawl_financials(engine, year, season, keep_files=False):
    """財報季更:下載該季 IFRS html 包(目錄已存在則沿用)→ 解析成寬表 →
    melt 長格式 upsert 進 market.financial_statement。冪等,可重跑。"""
    directory = os.path.join("data", "financial_statement", f"{year}{season}")
    if not os.path.isdir(directory):
        if year < 2019:
            raise NotImplementedError("僅支援 2019 年(含)以後的 IFRS 財報")
        crawler.crawl_finance_statement2019(year, season)
    frames = financial_statement.pack_htmls(year, season, directory)
    table = models.FinancialStatement.__table__
    total = 0
    with engine.begin() as conn:
        if season == 4:
            frames["income_sheet"] = _q4_income_sheet(
                conn, year, frames["income_sheet_cumulate"])
        for name, df in frames.items():
            if df is None or not len(df):
                continue
            recs = _records(etl.melt_financial(df.reset_index(), name), table)
            # 一季約 35 萬列,單條 INSERT 會超出參數上限,分批送
            for i in range(0, len(recs), 5000):
                total += upsert(conn, table, recs[i:i + 5000], _FINANCIAL_PK)
    if not keep_files:
        shutil.rmtree(directory, ignore_errors=True)
        if os.path.exists("temp.zip"):
            os.remove("temp.zip")
    return total


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
        # 月營收(上月整月)與除權息(滾動窗)順帶保鮮:各一個請求,upsert 冪等
        prev_month = (asof.replace(day=1) - _dt.timedelta(days=1)).replace(day=1)
        crawl_monthly_revenue(conn, prev_month)
        crawl_ex_dividend(conn, asof - _dt.timedelta(days=30),
                          asof + _dt.timedelta(days=90))


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
