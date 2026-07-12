"""Read-side of the market schema for the dashboard.

The dashboard's TW historical needs read these Postgres tables instead of
fetching yfinance. All functions accept an optional engine (defaults to the
shared one) and return pandas DataFrames / dicts.
"""

import pandas as pd
from sqlalchemy import text

from market_data.db import get_engine


def _q(sql, params, engine):
    return pd.read_sql(text(sql), engine or get_engine(), params=params)


def price_history(stock_id, start=None, end=None, engine=None):
    sql = ("SELECT date, open, high, low, close, change, volume, turnover, "
           "transactions, pe_ratio FROM market.price WHERE stock_id = :sid")
    params = {"sid": stock_id}
    if start:
        sql += " AND date >= :start"
        params["start"] = start
    if end:
        sql += " AND date <= :end"
        params["end"] = end
    sql += " ORDER BY date"
    return _q(sql, params, engine)


def institutional(stock_id, start=None, end=None, engine=None):
    sql = ("SELECT date, foreign_net, trust_net, dealer_net, total_net "
           "FROM market.institutional WHERE stock_id = :sid")
    params = {"sid": stock_id}
    if start:
        sql += " AND date >= :start"
        params["start"] = start
    if end:
        sql += " AND date <= :end"
        params["end"] = end
    return _q(sql + " ORDER BY date", params, engine)


def to_daily_frame(df):
    """Map price_history() output to the dashboard's normalized daily columns
    [date, open, high, low, close, volume, amount, pct_chg]."""
    if df is None or df.empty:
        return pd.DataFrame()
    prev_close = df["close"] - df["change"]
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"]),
        "open": df["open"], "high": df["high"], "low": df["low"],
        "close": df["close"], "volume": df["volume"], "amount": df["turnover"],
        "pct_chg": df["change"] / prev_close.where(prev_close != 0) * 100,
    })
    return out


def stock_info(stock_id, engine=None):
    df = _q("SELECT * FROM market.stock_info WHERE stock_id = :sid",
            {"sid": stock_id}, engine)
    return None if df.empty else df.iloc[0].to_dict()
