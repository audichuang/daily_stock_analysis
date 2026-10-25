"""Transform finlab's sqlite tables (Chinese wide columns) into the typed
``market`` schema (English columns; financials in long format).

Pure functions here are unit-tested; the runner (scripts/migrate_sqlite_to_pg.py)
reads sqlite in chunks, applies these, and bulk-loads Postgres via COPY.
"""

import datetime

import pandas as pd

_PRICE_MAP = {
    "開盤價": "open", "最高價": "high", "最低價": "low", "收盤價": "close",
    "漲跌價差": "change", "成交股數": "volume", "成交金額": "turnover",
    "成交筆數": "transactions", "本益比": "pe_ratio",
}
_PRICE_COLS = ["stock_id", "date", "market", "open", "high", "low", "close",
               "change", "volume", "turnover", "transactions", "pe_ratio"]

_MARGIN_MAP = {
    "融資買進": "margin_buy", "融資賣出": "margin_sell", "融資今日餘額": "margin_balance",
    "融券買進": "short_buy", "融券賣出": "short_sell", "融券今日餘額": "short_balance",
}


def _select(df, cols):
    """Return df with exactly ``cols`` (missing ones filled with NA)."""
    out = pd.DataFrame({c: df[c] if c in df.columns else pd.NA for c in cols})
    return out


def transform_price(df):
    df = df.rename(columns=_PRICE_MAP)
    df["market"] = pd.NA  # 上市/上櫃在來源已合併,無法逐列區分;留待日後補
    return _select(df, _PRICE_COLS)


def transform_institutional(df):
    foreign = df.get("外陸資買賣超股數(不含外資自營商)")
    if foreign is None:
        foreign = df.get("外資買賣超股數")
    else:
        foreign = foreign.fillna(df["外資買賣超股數"]) if "外資買賣超股數" in df else foreign
    out = pd.DataFrame({
        "stock_id": df["stock_id"], "date": df["date"],
        "foreign_net": foreign,
        "trust_net": df.get("投信買賣超股數"),
        "dealer_net": df.get("自營商買賣超股數"),
        "total_net": df.get("三大法人買賣超股數"),
    })
    return out


def transform_margin(df):
    out = df.rename(columns=_MARGIN_MAP)
    return _select(out, ["stock_id", "date", "margin_balance", "margin_buy",
                         "margin_sell", "short_balance", "short_buy", "short_sell"])


def transform_ex_dividend(df):
    out = df.rename(columns={
        "除權息前收盤價": "close_before", "除權息參考價": "reference_price",
        "權值+息值": "value", "權/息": "rights_type",
    })
    return _select(out, ["stock_id", "date", "close_before", "reference_price",
                         "value", "rights_type"])


def transform_monthly_revenue(df):
    # announce_date 維持次月 10 日佔位不變；法定期限由回測讀取端（revenue_deadline）套用
    announce = pd.to_datetime(df["date"])
    revenue_month = announce.dt.to_period("M").dt.to_timestamp() - pd.DateOffset(months=1)
    out = pd.DataFrame({
        "stock_id": df["stock_id"],
        "revenue_month": revenue_month,
        "revenue": df.get("當月營收"),
        "yoy": df.get("去年同月增減(%)"),
        "mom": df.get("上月比較增減(%)"),
        "announce_date": announce,
    })
    return out


def transform_stock_info(df):
    def _date(s):
        return pd.to_datetime(s, format="%Y%m%d", errors="coerce")

    out = pd.DataFrame({
        "stock_id": df["stock_id"],
        "name": df.get("公司簡稱"),
        "market": "twse",  # t187ap03_L 為上市清單
        "industry": df.get("產業別"),
        "listed_date": _date(df.get("上市日期")),
        "par_value": pd.to_numeric(df.get("普通股每股面額"), errors="coerce"),
        "paid_in_capital": pd.to_numeric(df.get("實收資本額"), errors="coerce"),
        "shares_outstanding": pd.to_numeric(
            df.get("已發行普通股數或TDR原股發行股數"), errors="coerce"),
    })
    return out


def _roc_yyyymmdd(s):
    # '1150703' -> 2026-07-03
    s = str(s).strip()
    return datetime.date(int(s[:-4]) + 1911, int(s[-4:-2]), int(s[-2:]))


def transform_valuation(rows):
    """BWIBBU_ALL JSON -> valuation (估值三率)."""
    df = pd.DataFrame(rows)
    def _num(col):
        return pd.to_numeric(df[col].astype(str).str.replace(",", "").str.strip(),
                             errors="coerce")

    # 殖利率空白 = 該股利年度沒配息，存 0 而不是 NULL：帶日期的 BWIBBU_d 對同一批股票印
    # `0.00`（2020~2025 回補的歷史全是 0），只有這個快照端點留空。兩條寫入路徑語意不一
    # 會讓同一欄在快照日是 NULL、補缺日是 0，回測排序（NaN 掉出、0 墊底）隨日期變。
    # 實測 2026-10-15／16：快照留空的 234 檔在 BWIBBU_d 全為 0.00，沒有一檔非零。
    # 只換「空白」；其他非數值仍走 to_numeric 變 NULL。本益比空白是虧損無法計算，維持 NULL。
    yield_raw = df["DividendYield"].astype(str).str.strip()
    df["DividendYield"] = yield_raw.mask(yield_raw == "", "0")
    out = pd.DataFrame({
        "stock_id": df["Code"].astype(str).str.strip(),
        "date": pd.to_datetime(df["Date"].map(_roc_yyyymmdd)),
        "pe_ratio": _num("PEratio"),
        "pb_ratio": _num("PBratio"),
        "dividend_yield": _num("DividendYield"),
    })
    return out.set_index(["stock_id", "date"])


def transform_index(rows):
    """FMTQIK JSON -> market_index (加權指數 TAIEX + 成交金額)."""
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "index_id": "TAIEX",
        "date": pd.to_datetime(df["Date"].map(_roc_yyyymmdd)),
        "close": pd.to_numeric(df["TAIEX"].astype(str).str.replace(",", ""), errors="coerce"),
        "change": pd.to_numeric(df["Change"].astype(str).str.replace(",", ""), errors="coerce"),
        "turnover": pd.to_numeric(df["TradeValue"].astype(str).str.replace(",", ""), errors="coerce"),
    })
    return out.set_index(["index_id", "date"])


def melt_financial(df, statement_type):
    long = df.melt(id_vars=["stock_id", "date"], var_name="account", value_name="value")
    long = long.dropna(subset=["value"])
    long["statement_type"] = statement_type
    return long[["stock_id", "date", "statement_type", "account", "value"]]
