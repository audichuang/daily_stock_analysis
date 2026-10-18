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


def latest_close(stock_id, as_of, engine=None):
    """(close, date) of the last session on or before ``as_of``; None when absent.

    Raw (unadjusted) close — what a holding is worth that day, not a return input.
    """
    df = _q("SELECT date, close FROM market.price WHERE stock_id = :sid AND date <= :d "
            "AND close IS NOT NULL ORDER BY date DESC LIMIT 1",
            {"sid": stock_id, "d": str(as_of)[:10]}, engine)
    if df.empty:
        return None
    row = df.iloc[0]
    return float(row["close"]), pd.Timestamp(row["date"]).date()


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


def adjustment_multipliers(stock_id, start=None, end=None, engine=None, sessions=None):
    """單檔的復權因子：date → 該事件日的 ``factor``（Series，index=date，唯一）。

    前復權面板是 ``adj[t] = raw[t] × Π_{s>t} f_s``（見 ``adjust.factors_to_panel``），
    所以事件日 ``d`` 的真實日報酬是 ``raw[d] / (raw[d-1] × F_d) − 1``，其中 ``F_d``
    就是本函式在 ``d`` 上的值。沒有事件的日期乘 1，與未還原完全一致。

    ``sessions``：呼叫端手上那檔的交易日。給了就把事件日經 ``adjust.snap_events_to_sessions``
    對齊（颱風休市日公告的除權息移到下一個交易日，否則 ``to_daily_frame`` 以精確日期
    ``Series.map`` 會對不到、那天的 pct_chg 變成假跌幅）；不給就是原始事件日（舊行為）。

    **回傳的 index 永遠唯一**：``to_daily_frame`` 用 ``Series.map``，重複 index 會直接抛
    ``InvalidIndexError``。DB 的 ``(stock_id, date)`` 主鍵與寫入端
    ``adjust.merge_adjustment_rows`` 的 ``drop_duplicates(keep="first")`` 已保證原始日期唯一，
    但 snap 之後官方事件可能與該日另一筆非 inferred 事件撞日，所以 snap 後仍 ``groupby.prod()``
    （與 ``factors_to_panel`` 的同日相乘語意對齊）。
    """
    sql = "SELECT date, factor, source FROM market.price_adjustment WHERE stock_id = :sid"
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
    if sessions is not None:
        from market_data.adjust import snap_events_to_sessions

        rows = snap_events_to_sessions(rows, sessions)
        if rows.empty:
            return pd.Series(dtype=float)
    return rows.groupby("date")["factor"].prod()


def front_adjust_multipliers(stock_id, dates, engine=None):
    """``dates`` 上每一天的前復權乘數 ``Π_{t<s≤as_of} f_s``（Series，index=輸入的 dates）。

    給技術指標用：原始 OHLC 乘它、volume 除它，最新價不變。``as_of = max(dates)``，
    sessions **就是**輸入的 dates（不另外併入 as_of）——呼叫端的最後一根 K 棒就是基準日，
    晚於它的事件一律不作用（含「休市日事件 snap 後會落到 max(dates) 之後」者）；落在
    max(dates) 當天的事件作用在之前的所有日期，max(dates) 本身乘 1。同一個 snap 實作，
    見 ``adjust.snap_events_to_sessions``。
    """
    from market_data.adjust import factors_to_panel

    idx = pd.DatetimeIndex(pd.to_datetime(pd.Series(list(dates))))
    if len(idx) == 0:
        return pd.Series(dtype=float)
    sess = idx.normalize().unique().sort_values()
    ev = _q("SELECT stock_id, date, factor, source FROM market.price_adjustment "
            "WHERE stock_id = :sid AND date <= :asof",
            {"sid": stock_id, "asof": sess[-1].date()}, engine)
    ev["date"] = pd.to_datetime(ev["date"])
    panel = factors_to_panel(ev, sess, pd.Index([stock_id]))[stock_id]
    return pd.Series(panel.reindex(idx.normalize()).to_numpy(), index=idx)


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
