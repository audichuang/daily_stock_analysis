from datetime import date

import pandas as pd
from sqlalchemy import text

from market_data import crawl


def _seed_cumulate(conn, year, rows):
    for stock_id, account, value in rows:
        conn.execute(text(
            "INSERT INTO market.financial_statement "
            "(stock_id, date, statement_type, account, value) "
            "VALUES (:s, :d, 'income_sheet_cumulate', :a, :v)"),
            {"s": stock_id, "d": date(year, 11, 14), "a": account, "v": value})


def _annual_cum(year, data):
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(f"{year + 1}-03-31")
    return df.set_index(["stock_id", "date"])


def test_q4_income_sheet_is_annual_minus_q3(pg_conn):
    _seed_cumulate(pg_conn, 2030, [("2330", "累計營業收入合計", 750.0),
                                   ("2330", "累計營業毛利", 300.0)])
    annual = _annual_cum(2030, [{"stock_id": "2330",
                                 "累計營業收入合計": 1000.0, "累計營業毛利": 420.0}])
    q4 = crawl._q4_income_sheet(pg_conn, 2030, annual)
    row = q4.loc[("2330", pd.Timestamp("2031-03-31"))]
    assert row["營業收入合計"] == 250.0
    assert row["營業毛利"] == 120.0


def test_q4_income_sheet_skips_stock_missing_q3(pg_conn):
    _seed_cumulate(pg_conn, 2030, [("2330", "累計營業收入合計", 750.0)])
    annual = _annual_cum(2030, [
        {"stock_id": "2330", "累計營業收入合計": 1000.0},
        {"stock_id": "9999", "累計營業收入合計": 500.0},  # 無 Q3 -> NaN,melt 會丟掉
    ])
    q4 = crawl._q4_income_sheet(pg_conn, 2030, annual)
    assert pd.isna(q4.loc[("9999", pd.Timestamp("2031-03-31")), "營業收入合計"])


def test_q4_income_sheet_none_when_no_q3_in_db(pg_conn):
    annual = _annual_cum(2029, [{"stock_id": "2330", "累計營業收入合計": 1.0}])
    assert crawl._q4_income_sheet(pg_conn, 2029, annual) is None
