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
    # 昨收由 close 自己 shift 得出，**不要**用 `close - change` 回推：`market.price.change`
    # 對上市股票沒有正負號（見 market_data/crawler.py 的 _SIGN_COL 註解），回推出來的昨收
    # 在下跌日比 close 還低 ⇒ 每個下跌日都變成上漲。實測 2330 於 2026-08-19 收 2350
    # （前日 2380，實際 -1.26%）會被算成 +1.29%。這個欄位會進台股個股分析的 LLM prompt。
    # 視窗第一列沒有前一日 ⇒ pct_chg 為 NaN（缺資料），不用 change 兜——那會把可能錯的
    # 符號放回來。消費端須以 pd.notna 判定，不能用 truthiness（`bool(nan)` 是 True）。
    close = pd.to_numeric(df["close"], errors="coerce")
    prev_close = close.shift(1)
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"]),
        "open": df["open"], "high": df["high"], "low": df["low"],
        "close": df["close"], "volume": df["volume"], "amount": df["turnover"],
        "pct_chg": (close / prev_close.where(prev_close != 0) - 1) * 100,
    })
    return out


def stock_info(stock_id, engine=None):
    df = _q("SELECT * FROM market.stock_info WHERE stock_id = :sid",
            {"sid": stock_id}, engine)
    return None if df.empty else df.iloc[0].to_dict()
