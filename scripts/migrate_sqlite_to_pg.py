"""One-time bulk migration: finlab sqlite (data.db) -> Postgres market.* schema.

Reads sqlite in chunks, applies market_data.etl transforms, and bulk-loads via
COPY. Idempotent: each target is TRUNCATEd before load, so it is safe to re-run.
Run AFTER the sqlite crawl has finished. Requires DATABASE_URL in env.

    uv run --with sqlalchemy --with pandas --with 'psycopg[binary]' \
        python scripts/migrate_sqlite_to_pg.py /path/to/data.db
"""

import io
import os
import sys

import pandas as pd
import psycopg

from market_data import etl

CHUNK = 500_000

# per-target column typing so COPY gets valid literals
INT_COLS = {
    "price": ["volume", "turnover", "transactions"],
    "institutional": ["foreign_net", "trust_net", "dealer_net", "total_net"],
    "margin": ["margin_balance", "margin_buy", "margin_sell",
               "short_balance", "short_buy", "short_sell"],
    "monthly_revenue": ["revenue"],
    "stock_info": ["paid_in_capital", "shares_outstanding"],
}
DATE_COLS = {
    "price": ["date"], "institutional": ["date"], "margin": ["date"],
    "ex_dividend": ["date"], "monthly_revenue": ["revenue_month", "announce_date"],
    "stock_info": ["listed_date"], "financial_statement": ["date"],
}


def _coerce(df, target):
    for c in INT_COLS.get(target, []):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    for c in DATE_COLS.get(target, []):
        if c in df:
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def _copy(cur, target, df):
    df = df.copy()
    # drop footer/note rows: real stock ids are short alphanumerics (e.g. 2330,
    # 0050, 00679B). CSV footers leak long Chinese sentences into stock_id.
    # Guard nulls explicitly — astype(str) would turn NaN into the string "nan"
    # which passes the regex.
    sid = df["stock_id"]
    df = df[sid.notna() & sid.astype(str).str.fullmatch(r"[0-9A-Za-z]{2,10}")]
    if df.empty:
        return 0
    df = _coerce(df, target)
    cols = list(df.columns)
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)
    sql = f'COPY market.{target} ({",".join(cols)}) FROM STDIN WITH (FORMAT CSV, NULL \'\')'
    with cur.copy(sql) as cp:
        cp.write(buf.read())
    return len(df)


def _truncate(cur, target):
    cur.execute(f"TRUNCATE market.{target}")


def migrate_narrow(sqlite, pg, source, target, transform):
    """Load one target atomically: TRUNCATE + all chunks in a single
    transaction, commit only on full success (else rollback -> target
    unchanged, never half-loaded)."""
    cur = pg.cursor()
    total = 0
    try:
        _truncate(cur, target)
        for chunk in pd.read_sql(f'SELECT * FROM "{source}"', sqlite, chunksize=CHUNK):
            total += _copy(cur, target, transform(chunk))
            print(f"  {target}: {total:,}", flush=True)
        pg.commit()
    except Exception:
        pg.rollback()
        raise
    return total


def migrate_financials(sqlite, pg):
    cur = pg.cursor()
    total = 0
    try:
        _truncate(cur, "financial_statement")
        for src in ("balance_sheet", "income_sheet", "income_sheet_cumulate",
                    "cash_flows"):
            for chunk in pd.read_sql(f'SELECT * FROM "{src}"', sqlite, chunksize=100_000):
                total += _copy(cur, "financial_statement", etl.melt_financial(chunk, src))
                print(f"  financial_statement({src}): {total:,}", flush=True)
        pg.commit()
    except Exception:
        pg.rollback()
        raise
    return total


def main(sqlite_path):
    url = os.environ["DATABASE_URL"].replace("+psycopg", "")
    sqlite = __import__("sqlite3").connect(sqlite_path)
    pg = psycopg.connect(url, connect_timeout=15)

    jobs = [
        ("price", "price", etl.transform_price),
        ("institutional", "institutional", etl.transform_institutional),
        ("margin", "margin", etl.transform_margin),
        ("ex_dividend", "ex_dividend", etl.transform_ex_dividend),
        ("monthly_report", "monthly_revenue", etl.transform_monthly_revenue),
        ("stock_info", "stock_info", etl.transform_stock_info),
    ]
    for source, target, fn in jobs:
        print(f"[migrate] {source} -> market.{target}", flush=True)
        migrate_narrow(sqlite, pg, source, target, fn)

    print("[migrate] financial statements -> market.financial_statement", flush=True)
    migrate_financials(sqlite, pg)

    pg.close()
    sqlite.close()
    print("[migrate] done", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/data.db")
