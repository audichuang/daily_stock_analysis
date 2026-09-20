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


def adjustment_multipliers(stock_id, start=None, end=None, engine=None):
    """單檔的復權因子：date → 該事件日的 ``factor``（Series，index=date，唯一）。

    前復權面板是 ``adj[t] = raw[t] × Π_{s>t} f_s``（見 ``adjust.factors_to_panel``），
    所以事件日 ``d`` 的真實日報酬是 ``raw[d] / (raw[d-1] × F_d) − 1``，其中 ``F_d``
    就是本函式在 ``d`` 上的值。沒有事件的日期乘 1，與未還原完全一致。

    **每檔每日至多一列**：``price_adjustment`` 的主鍵是 ``(stock_id, date)``，而同日
    多事件（除息 + 減資）在**寫入端**就被 ``adjust.merge_adjustment_rows`` 的
    ``drop_duplicates(keep="first")`` 按來源優先序收斂成一列——不是在這裡相乘。
    所以 ``.prod()`` 對 DB 讀出來的資料等價於 ``.first()``；留著它有兩個理由：
    保證回傳的 index **唯一**（``to_daily_frame`` 用 ``Series.map``，重複 index 會
    直接抛 ``InvalidIndexError``），以及與 ``factors_to_panel`` 的同日相乘語意對齊
    （那邊吃的可能是尚未 dedup 的長格式）。
    """
    sql = "SELECT date, factor FROM market.price_adjustment WHERE stock_id = :sid"
    params = {"sid": stock_id}
    if start:
        sql += " AND date >= :start"
        params["start"] = start
    if end:
        sql += " AND date <= :end"
        params["end"] = end
    rows = _q(sql, params, engine)
    if rows.empty:
        return pd.Series(dtype=float)
    rows["date"] = pd.to_datetime(rows["date"])
    return rows.groupby("date")["factor"].prod()


def to_daily_frame(df, event_factors=None):
    """Map price_history() output to the dashboard's normalized daily columns
    [date, open, high, low, close, volume, amount, pct_chg].

    ``event_factors`` 是 ``adjustment_multipliers()`` 的輸出。除權息日的價格斷崖不是
    真實跌幅——`price` 是未還原價，算報酬前一律先套 `market.price_adjustment`
    （market_data/AGENTS.md）。沒給因子時退回未還原報酬（行為同舊版）。

    **只有 `pct_chg` 被還原，OHLC 四欄仍是原始未還原價**（下游 `BaseFetcher.
    _calculate_indicators` 的 ma5/10/20 也因此是未還原均線）。所以除權息當天餵給 LLM
    的表格裡，「漲跌幅」是對的、「均線乖離」還是會被斷崖歪掉。要根治得改成回傳還原後
    的價格面板，但那會改變使用者在報告裡看到的絕對價位（與券商 App 不一致），是產品
    決策不是清理，刻意不在這裡順手做。
    """
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
    denom = prev_close
    if event_factors is not None and len(event_factors):
        factors = pd.Series(event_factors, dtype=float)
        factors.index = pd.DatetimeIndex(factors.index).normalize()
        # Series.map 以 factors 的 index 對 df 的日期查同日因子積；沒事件的日期補 1。
        mult = pd.to_datetime(df["date"]).dt.normalize().map(factors).fillna(1.0)
        denom = prev_close * mult
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"]),
        "open": df["open"], "high": df["high"], "low": df["low"],
        "close": df["close"], "volume": df["volume"], "amount": df["turnover"],
        "pct_chg": (close / denom.where(denom != 0) - 1) * 100,
    })
    return out


def stock_info(stock_id, engine=None):
    df = _q("SELECT * FROM market.stock_info WHERE stock_id = :sid",
            {"sid": stock_id}, engine)
    return None if df.empty else df.iloc[0].to_dict()


def market_index(index_id, date, engine=None):
    """單一指數在單一場次的官方收盤（`close`/`change`/`turnover`）。

    這張表是這條路上**唯一帶場次身分**的指數來源:即時報價拿不到「這根 K 棒屬於
    哪一天」,而複盤要的正是那個。`change` 帶正負號(與 `price.change` 不同,後者
    上市列只有絕對值),已逐場次對過 `close - lag(close)`。
    """
    df = _q("SELECT close, change, turnover FROM market.market_index "
            "WHERE index_id = :iid AND date = :d",
            {"iid": index_id, "d": str(date)[:10]}, engine)
    return None if df.empty else df.iloc[0].to_dict()
