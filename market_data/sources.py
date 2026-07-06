"""Additional TWSE / TPEx data sources: 上櫃股價、三大法人、融資融券、除權息、
股票基本資料.

Each source splits into a pure ``parse_*`` (unit-tested against captured
fixtures) and a network ``crawl_*`` that fetches then parses. The real crawlers
fetch directly (like ``crawler.py``); a proxy pool is only used for dev probing.
"""

import datetime
import json
from io import StringIO

import pandas as pd

from market_data.crawler import _UA, requests_get

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _to_num(df, keep):
    """Coerce every column except ``keep`` to numeric, stripping thousands
    separators. Columns that are all-null after coercion are dropped."""
    for c in df.columns:
        if c in keep:
            continue
        df[c] = pd.to_numeric(
            df[c].astype(str).str.replace(",", "").str.strip(), errors="coerce"
        )
    return df[[c for c in df.columns if c in keep or not df[c].isnull().all()]]


def _roc_to_date(s):
    # "113年06月03日" -> 2024-06-03
    s = s.strip()
    y, rest = s.split("年")
    m, rest = rest.split("月")
    d = rest.replace("日", "")
    return datetime.date(int(y) + 1911, int(m), int(d))


def _csv_from(text, header_startswith):
    """Slice a TWSE csv blob to the table whose header row starts with the
    given prefix, returning a clean csv string (header + data)."""
    lines = text.replace("=", "").split("\n")
    for i, line in enumerate(lines):
        if line.startswith(header_startswith):
            return "\n".join(lines[i:])
    raise ValueError(f"header {header_startswith!r} not found")


# ---------------------------------------------------------------------------
# 上櫃股價 (TPEx, JSON)
# ---------------------------------------------------------------------------

_TPEX_RENAME = {
    "收盤": "收盤價",
    "開盤": "開盤價",
    "最高": "最高價",
    "最低": "最低價",
    "漲跌": "漲跌價差",
    "成交金額(元)": "成交金額",
}


def parse_tpex_price(raw, date):
    tb = json.loads(raw.decode("utf-8"))["tables"][0]
    fields = [f.replace("<br>", "").strip() for f in tb["fields"]]
    df = pd.DataFrame(tb["data"], columns=fields)
    df = df.rename(columns={"代號": "stock_id", "名稱": "名稱", **_TPEX_RENAME})
    df["date"] = pd.to_datetime(date)
    keep = {"stock_id", "date", "名稱"}
    df = _to_num(df, keep)
    df = df[~df["收盤價"].isnull()]
    return df.set_index(["stock_id", "date"])


# ---------------------------------------------------------------------------
# 三大法人 (TWSE T86, Big5 csv)
# ---------------------------------------------------------------------------


def parse_institutional(raw, date):
    text = raw.decode("big5", errors="replace")
    df = pd.read_csv(StringIO(_csv_from(text, '"證券代號"')), dtype=str)
    df = df.rename(columns={"證券代號": "stock_id", "證券名稱": "名稱"})
    df["stock_id"] = df["stock_id"].str.strip()
    df["名稱"] = df["名稱"].str.strip()
    df = df.dropna(subset=["stock_id"])
    df["date"] = pd.to_datetime(date)
    df = _to_num(df, {"stock_id", "date", "名稱"})
    return df.set_index(["stock_id", "date"])


# ---------------------------------------------------------------------------
# 融資融券 (TWSE MI_MARGN, Big5 csv, two sections)
# ---------------------------------------------------------------------------

_MARGIN_COLS = [
    "stock_id", "名稱",
    "融資買進", "融資賣出", "融資現金償還", "融資前日餘額", "融資今日餘額", "融資次一營業日限額",
    "融券買進", "融券賣出", "融券現券償還", "融券前日餘額", "融券今日餘額", "融券次一營業日限額",
    "資券互抵", "註記",
]


def parse_margin(raw, date):
    text = raw.decode("big5", errors="replace")
    body = _csv_from(text, '"代號","名稱"')
    raw_df = pd.read_csv(StringIO(body), header=0, dtype=str)
    df = raw_df.iloc[:, : len(_MARGIN_COLS)].copy()
    df.columns = _MARGIN_COLS
    df["stock_id"] = df["stock_id"].str.strip()
    df["名稱"] = df["名稱"].astype(str).str.strip()
    df = df[df["stock_id"].str.match(r"^\w+$", na=False)]
    df["date"] = pd.to_datetime(date)
    df = _to_num(df, {"stock_id", "date", "名稱", "註記"})
    return df.set_index(["stock_id", "date"])


# ---------------------------------------------------------------------------
# 除權息 (TWSE TWT49U, Big5 csv, per-row date)
# ---------------------------------------------------------------------------


def parse_ex_dividend(raw):
    text = raw.decode("big5", errors="replace")
    df = pd.read_csv(StringIO(_csv_from(text, '"資料日期"')), dtype=str)
    df = df.rename(columns={"股票代號": "stock_id", "股票名稱": "名稱"})
    df = df.dropna(subset=["stock_id", "資料日期"])
    df["stock_id"] = df["stock_id"].str.strip()
    df["date"] = pd.to_datetime(df["資料日期"].map(_roc_to_date))
    df = df.drop(columns=["資料日期"])
    df = _to_num(df, {"stock_id", "date", "名稱", "權/息", "詳細資料",
                      "最近一次申報資料 季別/日期"})
    return df.set_index(["stock_id", "date"])


# ---------------------------------------------------------------------------
# 股票基本資料 (TWSE OpenAPI, UTF-8 JSON, snapshot — no date)
# ---------------------------------------------------------------------------


def parse_stock_info(raw):
    rows = json.loads(raw.decode("utf-8"))
    df = pd.DataFrame(rows).rename(columns={"公司代號": "stock_id"})
    df["stock_id"] = df["stock_id"].astype(str).str.strip()
    # keep everything as-is (產業別 "01" must stay a string, not become 1)
    return df.drop_duplicates("stock_id").set_index("stock_id")


# ---------------------------------------------------------------------------
# network crawlers (fetch + parse). Direct requests, like crawler.py.
# ---------------------------------------------------------------------------


def crawl_tpex_price(date):
    url = (
        "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
        f"?date={date.strftime('%Y/%m/%d')}&type=EW&response=json"
    )
    r = requests_get(url, headers={"User-Agent": _UA})
    if r is None or not r.text.strip():
        return None
    try:
        return parse_tpex_price(r.content, date)
    except (ValueError, KeyError, IndexError):
        return None


def _twse_csv(url):
    r = requests_get(url, headers={"User-Agent": _UA})
    if r is None:
        return None
    return r.content


def crawl_institutional(date):
    raw = _twse_csv(
        "https://www.twse.com.tw/rwd/zh/fund/T86"
        f"?date={date.strftime('%Y%m%d')}&selectType=ALLBUT0999&response=csv"
    )
    if not raw:
        return None
    try:
        return parse_institutional(raw, date)
    except ValueError:
        return None


def crawl_margin(date):
    raw = _twse_csv(
        "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
        f"?date={date.strftime('%Y%m%d')}&selectType=ALL&response=csv"
    )
    if not raw:
        return None
    try:
        return parse_margin(raw, date)
    except ValueError:
        return None


def crawl_ex_dividend(start, end):
    raw = _twse_csv(
        "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
        f"?startDate={start.strftime('%Y%m%d')}&endDate={end.strftime('%Y%m%d')}"
        "&response=csv"
    )
    if not raw:
        return None
    try:
        return parse_ex_dividend(raw)
    except ValueError:
        return None


def crawl_stock_info():
    raw = _twse_csv("https://openapi.twse.com.tw/v1/opendata/t187ap03_L")
    if not raw:
        return None
    return parse_stock_info(raw)


def _openapi_json(url):
    r = requests_get(url, headers={"User-Agent": _UA})
    if r is None:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def _valid_rows(data, required):
    """OpenAPI success = non-empty list of dicts carrying the expected keys.
    Guards against TWSE returning an error object / changed shape."""
    if not isinstance(data, list) or not data:
        return None
    if not isinstance(data[0], dict) or not required.issubset(data[0]):
        return None
    return data


def fetch_valuation():
    """BWIBBU_ALL:上市個股 本益比/股價淨值比/殖利率(當日快照)。"""
    data = _openapi_json("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL")
    return _valid_rows(data, {"Code", "Date", "PEratio", "PBratio", "DividendYield"})


def fetch_index():
    """FMTQIK:加權指數 TAIEX + 市場成交金額(近日)。"""
    data = _openapi_json("https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK")
    return _valid_rows(data, {"Date", "TAIEX", "Change", "TradeValue"})
