"""Additional TWSE / TPEx data sources: 上櫃股價、三大法人、融資融券、除權息、
股票基本資料.

Each source splits into a pure ``parse_*`` (unit-tested against captured
fixtures) and a network ``crawl_*`` that fetches then parses. The real crawlers
fetch directly (like ``crawler.py``); a proxy pool is only used for dev probing.
"""

import datetime
import json
import math
import re
from io import StringIO

import pandas as pd
import requests

from market_data import tw_official_http
from market_data.crawler import _UA, requests_get, requests_post

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


def _roc_to_date_or_none(s):
    """同 `_roc_to_date`，但無效日月、超出範圍或溢位的民國年份回 None 而不是 raise。

    官方回應自帶的日期欄只拿來比對請求日，認不得就等同「無法證明新鮮」、由呼叫端拒收；
    `OverflowError` 不是 `ValueError` 的子類，呼叫端只接 `ValueError` 的話會整段中斷。"""
    try:
        return _roc_to_date(s)
    except (ValueError, OverflowError):
        return None


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
    # 回應自帶日期（外層 ``date``、表的民國 ``date``）必須等於請求日，否則拒收：
    # 官方會回 200 卻是別天／凍結的表，直接蓋上請求日就成了不存在的一天。
    tb = _tpex_table(json.loads(raw.decode("utf-8")), date, "上櫃股價")
    if tb is None:
        return None
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


# 官方表頭(pandas 會把重複欄名加 ".1" 後綴,比對前先去掉)。位置對欄有個靜默風險:
# 來源若插欄,數值仍是數字、列數正常,整批錯位也不會報錯——所以先核對表頭順序。
_MARGIN_HEADER = [
    "代號", "名稱",
    "買進", "賣出", "現金償還", "前日餘額", "今日餘額", "次一營業日限額",
    "買進", "賣出", "現券償還", "前日餘額", "今日餘額", "次一營業日限額",
    "資券互抵", "註記",
]


def parse_margin(raw, date):
    text = raw.decode("big5", errors="replace")
    body = _csv_from(text, '"代號","名稱"')
    raw_df = pd.read_csv(StringIO(body), header=0, dtype=str)
    # 只比對前 16 欄:官方 CSV 每行尾端多一個逗號(多一個空欄),不能要求恰好 16 欄
    actual = [str(c).split(".")[0] for c in raw_df.columns[: len(_MARGIN_HEADER)]]
    if actual != _MARGIN_HEADER:
        raise ValueError(
            f"MI_MARGN 表頭與預期不符(欄位順序改了?),實際前 {len(_MARGIN_HEADER)} 欄: "
            f"{list(raw_df.columns[: len(_MARGIN_HEADER)])}"
        )
    df = raw_df.iloc[:, : len(_MARGIN_COLS)].copy()
    df.columns = _MARGIN_COLS
    df["stock_id"] = df["stock_id"].str.strip()
    df["名稱"] = df["名稱"].astype(str).str.strip()
    # 代號只收英數字:\w 在 Python 3 對中文也成立,註腳列(「備註:」「符號說明…」)要擋在外面
    df = df[df["stock_id"].str.fullmatch(r"[0-9A-Za-z]{2,10}", na=False)]
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
        print(f"**WARN: no response from {url} (連線失敗或 IP 被 TWSE 封鎖)")
        return None
    if r.status_code != 200:
        print(f"**WARN: HTTP {r.status_code} from {url}")
        return None
    return r.content


def _describe_unparsable(raw):
    """HTTP 200 卻解析不了的回覆,說明它比較像哪一種。

    短純文字(不以 ``<`` 開頭、< 500 字元)多半是 TWSE 的訊息(尚未發布、查無資料、
    日期在未來),印出前 60 字;其餘(HTML 或長內容)才是封鎖頁/改版的徵兆。
    只靠長度與是否 HTML 判斷,不依賴字串內容(18:00 當天未發布的確切回覆未觀察到)。
    解碼先 UTF-8、失敗再 cp950——cp950 能解出幾乎任何位元組,放前面會把 UTF-8 解成亂碼。"""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp950", errors="replace")
    text = " ".join(text.split())
    if text and not text.startswith("<") and len(text) < 500:
        return f"TWSE 回覆「{text[:60]}」(多半是尚未發布或查無資料)"
    return "HTTP 200 但內容不是預期的 CSV(封鎖頁/改版?)"


def _title_date_matches(raw, date, name):
    """TWSE csv 第一行自帶資料日（``115年05月22日 信用交易統計``）必須等於請求日。

    官方對沒有交易的日子（週日、停市日）有時回另一天的整份表而非「查無資料」，
    parse 會把列蓋上請求日，存成不存在的孤兒日（margin 2021-05-23／2024-09-01 即如此）。
    無法證明新鮮的資料不如沒有：標題缺日期一樣拒收。
    ``raw`` 可給 bytes（big5 解碼）或已解碼的 str（MI_INDEX 用 requests 的 ``r.text``）。"""
    text = raw if isinstance(raw, str) else raw.decode("big5", errors="replace")
    head = text.lstrip("\ufeff \r\n").split("\n", 1)[0]
    m = re.search(r"\d+年\d+月\d+日", head)
    got = _roc_to_date_or_none(m.group(0)) if m else None
    if got == date:
        return True
    print(f"**WARN: {name} 回應日期 {got or '(無)'} ≠ 請求日 {date},拒收"
          "(非交易日或尚未發布時官方會回別天的表)", flush=True)
    return False


def crawl_institutional(date):
    raw = _twse_csv(
        "https://www.twse.com.tw/rwd/zh/fund/T86"
        f"?date={date.strftime('%Y%m%d')}&selectType=ALLBUT0999&response=csv"
    )
    if not raw:
        return None
    try:
        df = parse_institutional(raw, date)
    except ValueError as exc:
        print(f"**WARN: cannot parse T86 institutional for {date} ({exc})"
              f" — {_describe_unparsable(raw)}")
        return None
    return df if _title_date_matches(raw, date, "T86") else None


def crawl_margin(date):
    raw = _twse_csv(
        "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
        f"?date={date.strftime('%Y%m%d')}&selectType=ALL&response=csv"
    )
    if not raw:
        return None
    try:
        df = parse_margin(raw, date)
    except ValueError as exc:
        print(f"**WARN: cannot parse MI_MARGN margin for {date} ({exc})"
              f" — {_describe_unparsable(raw)}")
        return None
    return df if _title_date_matches(raw, date, "MI_MARGN") else None


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
    except ValueError as exc:
        print(f"**WARN: cannot parse TWT49U ex-dividend {start}~{end} ({exc})"
              f" — HTTP 200 但內容不是預期的 CSV(封鎖頁/改版?)")
        return None


_BACKUP_PRICE_MAP = {
    "TradeVolume": "成交股數", "TradeValue": "成交金額", "Transaction": "成交筆數",
    "OpeningPrice": "開盤價", "HighestPrice": "最高價", "LowestPrice": "最低價",
    "ClosingPrice": "收盤價", "Change": "漲跌價差",
}


def crawl_price_backup(date):
    """上市 price 備援(openapi STOCK_DAY_ALL)。端點只提供最新交易日,逐列帶
    民國 Date;僅當日期與 ``date`` 相符才可用,否則回 None(不能拿別天的資料
    冒充)。無 本益比 欄(transform 會補 NA)。"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    data = _valid_rows(_openapi_json(url),
                       {"Date", "Code", "ClosingPrice", "TradeVolume"}, url)
    if data is None:
        return None
    roc = f"{date.year - 1911}{date.month:02d}{date.day:02d}"
    # 單日快照端點:任何一列日期不符即整包拒收(不能拿別天資料冒充,也不收混日包)
    rows = [r for r in data if r.get("Date") == roc]
    if not rows or len(rows) != len(data):
        return None
    df = pd.DataFrame(rows).rename(columns={"Code": "stock_id", **_BACKUP_PRICE_MAP})
    for c in _BACKUP_PRICE_MAP.values():
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[~df["收盤價"].isnull()]
    df["date"] = pd.to_datetime(date)
    return df.set_index(["stock_id", "date"])[list(_BACKUP_PRICE_MAP.values())]


def crawl_stock_info():
    raw = _twse_csv("https://openapi.twse.com.tw/v1/opendata/t187ap03_L")
    if not raw:
        return None
    return parse_stock_info(raw)


def _openapi_json(url):
    """OpenAPI GET → 解析好的 JSON,失敗回 None **並印出原因**。

    為什麼一定要印:這裡原本把「連線失敗/IP 被封」「HTTP 非 200」「回應不是 JSON」
    三種情況全塌縮成同一個 `None`,上層再塌縮成 `return 0`,最外層又不印任何東西——
    於是「TWSE 當日還沒發布」與「抓取真的壞了」的可觀測結果完全一樣(什麼都沒印、
    DB 沒變)。踩過:2026-07-28 18:10 跑 snapshot 全無輸出,查了三層原始碼才確認是
    FMTQIK 當日尚未發布而不是壞掉。
    """
    r = requests_get(url, headers={"User-Agent": _UA})
    if r is None:
        print(f"**WARN: no response from {url} (連線失敗或 IP 被 TWSE 封鎖)")
        return None
    if r.status_code != 200:
        print(f"**WARN: HTTP {r.status_code} from {url}")
        return None
    try:
        return r.json()
    except ValueError:
        print(f"**WARN: non-JSON body from {url}: {r.text[:120]!r}")
        return None


def _valid_rows(data, required, url=""):
    """OpenAPI success = non-empty list of dicts carrying the expected keys.
    Guards against TWSE returning an error object / changed shape.

    每個拒收分支都印出**可區分**的原因:空 list 通常只是當日資料還沒發布(等入夜重跑
    即可),缺欄位則是端點改版(要改程式),兩者的處置完全不同,不能長得一樣。
    """
    where = url or "openapi"
    if data is None:
        return None                      # _openapi_json 已印過原因,不重複
    if not isinstance(data, list) or not data:
        print(f"**WARN: empty or non-list payload from {where} "
              f"(TWSE 多半是當日資料尚未發布,入夜後重跑即可)")
        return None
    if not isinstance(data[0], dict) or not required.issubset(data[0]):
        missing = (required - set(data[0])) if isinstance(data[0], dict) else required
        print(f"**WARN: unexpected shape from {where}, "
              f"missing keys {sorted(missing)} (端點可能改版)")
        return None
    return data


def fetch_valuation():
    """BWIBBU_ALL:上市個股 本益比/股價淨值比/殖利率(當日快照)。"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
    return _valid_rows(_openapi_json(url),
                       {"Code", "Date", "PEratio", "PBratio", "DividendYield"}, url)


def _roc_slash_to_date(s):
    """"113/01/22" -> 2024-01-22。TWSE 部分表用斜線而非 `_roc_to_date` 的年月日。"""
    y, m, d = str(s).strip().split("/")
    return datetime.date(int(y) + 1911, int(m), int(d))


def parse_reduction(payload):
    """TWTAUU JSON -> DataFrame(stock_id, date, close_before, reference_price, reason)。

    欄位靠回應的 ``fields`` 動態定位而非硬編索引——TWSE 各表欄位順序會隨年代變動。
    """
    fields = payload.get("fields") or []
    idx = {name: i for i, name in enumerate(fields)}
    need = ("恢復買賣日期", "股票代號", "停止買賣前收盤價格", "恢復買賣參考價")
    if not all(k in idx for k in need):
        raise ValueError(f"TWTAUU 欄位不符預期: {fields}")
    rows, skipped = [], 0
    for r in payload.get("data") or []:
        try:
            rows.append({
                "stock_id": str(r[idx["股票代號"]]).strip(),
                "date": pd.to_datetime(_roc_slash_to_date(r[idx["恢復買賣日期"]])),
                "close_before": float(str(r[idx["停止買賣前收盤價格"]]).replace(",", "")),
                "reference_price": float(str(r[idx["恢復買賣參考價"]]).replace(",", "")),
                "reason": r[idx["減資原因"]] if "減資原因" in idx else None,
            })
        except (ValueError, TypeError, IndexError):
            skipped += 1  # 個別列格式異常不該讓整批失敗
    if skipped and not rows:
        # 全數跳過幾乎必為格式改版，靜默回空會讓減資事件永久缺漏
        raise ValueError(f"TWTAUU 全部 {skipped} 列都無法解析,格式可能已變更: {fields}")
    return pd.DataFrame(rows)


def crawl_reduction(start, end):
    """TWTAUU:上市股票減資(含退還股款/彌補虧損)恢復買賣參考價格。

    這是 ``ex_dividend``(TWT49U)沒有的事件類型——減資會讓股價跳升,不還原會被
    當成真實暴漲。注意本表**不含面額變更(股票分割)**,分割走 ``crawl_twse_par_value_change``。
    """
    r = requests_get(
        "https://www.twse.com.tw/rwd/zh/reducation/TWTAUU",
        params={"response": "json",
                "startDate": start.strftime("%Y%m%d"),
                "endDate": end.strftime("%Y%m%d")},
        headers={"User-Agent": _UA},
    )
    if r is None:
        return None
    try:
        payload = r.json()
    except ValueError:
        return None
    if payload.get("stat") != "OK":
        return None
    return parse_reduction(payload)


_MOPS_REVENUE_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t05st10_ifrs"


def parse_company_monthly_revenue(html, stock_id, year, month):
    """MOPS 個別公司月營收頁 -> dict(stock_id, revenue_month, revenue, yoy, announce_date)。

    表格是**轉置**的（項目在第 0 欄、數值在第 1 欄），而且有兩個「增減百分比」列:
    第一個是本月 YoY、第二個是累計 YoY,靠「本月」列的位置定位才不會取錯。
    KY 公司多一個功能性貨幣欄,一律取第 1 欄（新台幣）。

    回傳 (record, reason)。``reason`` 是 ``"ok"`` 或失敗原因,**四種失敗必須分開**:
      - ``not_public``:「不繼續公開發行」——被吸收合併,MOPS 不再提供歷史（2448 晶電併入富采）
      - ``foreign_exempt``:「外國發行人免申報本項資訊」
      - ``no_data``:頁面正常但該月無資料
      - ``parse_failed``:表格結構不符預期（端點改版）
    混成同一個 None 的後果:呼叫端把 HTTP／解析失敗誤判成「這家公司補不回來」,
    整檔剩餘月份全部跳過,而且「82 檔補不回」的統計會虛胖。獨立審查指出。

    **回應頁的年月要核對**,不能直接拿呼叫參數當 PK——MOPS 回舊頁或回錯月份時,
    直接寫入等於用錯誤的月份污染 `monthly_revenue`。
    """
    if "不繼續公開發行" in html:
        return None, "not_public"
    if "免申報" in html:
        return None, "foreign_exempt"
    # 核對頁面自己聲明的年月（民國），對不上就拒收
    m = re.search(r"民國\s*(\d+)\s*年\s*(\d+)\s*月", html)
    if m and (int(m.group(1)) + 1911, int(m.group(2))) != (year, month):
        return None, (f"month_mismatch(頁面={int(m.group(1)) + 1911}-"
                      f"{int(m.group(2)):02d} 請求={year}-{month:02d})")
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        return None, "no_data"
    tbl = next((t for t in tables if t.shape[1] >= 2 and t.iloc[:, 0].astype(str)
                .str.contains("本月").any()), None)
    if tbl is None:
        return None, "parse_failed"
    labels = tbl.iloc[:, 0].astype(str).str.strip()
    try:
        i_cur = labels[labels == "本月"].index[0]
    except IndexError:
        return None, "parse_failed"
    pct = labels[(labels == "增減百分比") & (labels.index > i_cur)]
    if pct.empty:
        return None, "parse_failed"

    def _num(v):
        s = str(v).replace(",", "").strip()
        try:
            return float(s)
        except ValueError:
            return None

    rev = _num(tbl.iloc[i_cur, 1])
    yoy = _num(tbl.iloc[pct.index[0], 1])
    if rev is None:
        return None, "no_data"
    rm = datetime.date(year, month, 1)
    nxt = datetime.date(year + (month == 12), month % 12 + 1, 10)
    return {"stock_id": stock_id, "revenue_month": pd.Timestamp(rm),
            "revenue": rev, "yoy": yoy, "mom": None,
            "announce_date": pd.Timestamp(nxt)}, "ok"


def crawl_company_monthly_revenue(stock_id, year, month):
    """單一公司單月的月營收（民國年由西元換算）。

    存在的理由是**存活偏誤**:`crawl_monthly_report` 走的彙總報表 `t21sc03_<roc>_<m>.html`
    是**動態產生**的,只列出目前仍在申報的公司,不是當時的快照——實測 2020-06 那份 979 家
    裡完全沒有 6452 康友、2448 晶電、2456 奇力新、5305 敦南、3698 隆達,而這五檔當時都
    還在交易。用彙總報表回補歷史,後來下市的公司會永久缺席,負尾被系統性移除。
    本函式改走個別公司查詢,對仍公開發行的下市公司仍取得到歷史。
    """
    r = requests_post(
        _MOPS_REVENUE_URL,
        data={"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1,
              "TYPEK": "all", "isnew": "false", "co_id": stock_id,
              "year": year - 1911, "month": f"{month:02d}"},
        headers={"User-Agent": _UA}, verify=False,
    )
    if r is None:
        return None, "http_failed"
    r.encoding = "utf-8"
    return parse_company_monthly_revenue(r.text, stock_id, year, month)


def parse_tpex_ex_dividend(payload):
    """TPEx ``bulletin/exDailyQ`` JSON -> DataFrame(stock_id, date, close_before, reference_price)。

    欄位靠 ``fields`` 動態定位(與 TWSE 各表同理);日期是民國斜線格式「109/01/02」。
    名稱欄有大量全角補空白,代號欄也要 strip。
    """
    tables = payload.get("tables") or []
    if not tables:
        raise ValueError("exDailyQ 回應沒有 tables")
    t = tables[0]
    idx = {name: i for i, name in enumerate(t.get("fields") or [])}
    need = ("除權息日期", "代號", "除權息前收盤價", "除權息參考價")
    if not all(k in idx for k in need):
        raise ValueError(f"exDailyQ 欄位不符預期: {t.get('fields')}")
    rows, skipped = [], 0
    for r in t.get("data") or []:
        try:
            before = float(str(r[idx["除權息前收盤價"]]).replace(",", ""))
            ref = float(str(r[idx["除權息參考價"]]).replace(",", ""))
            if before <= 0 or ref <= 0:
                skipped += 1
                continue
            rows.append({
                "stock_id": str(r[idx["代號"]]).strip(),
                "date": pd.to_datetime(_roc_slash_to_date(r[idx["除權息日期"]])),
                "close_before": before,
                "reference_price": ref,
            })
        except (ValueError, TypeError, IndexError):
            skipped += 1
    if skipped and not rows:
        # 全數跳過幾乎必為格式改版;靜默回空會讓上櫃除權息永久缺、退回不精確的價格推導
        raise ValueError(f"exDailyQ 全部 {skipped} 列都無法解析,格式可能已變更")
    return pd.DataFrame(rows)


def crawl_tpex_ex_dividend(start, end):
    """上櫃除權除息**計算結果表**(官方公告的除權息前收盤價與參考價),自 2008-01-02 起。

    這是 `ex_dividend`(TWSE TWT49U,僅上市)補不到的另一半。找端點踩過的雷:
      - openapi ``/tpex_exright_daily`` 只回**當日**(13 筆),不能回補
      - openapi ``/tpex_exright_prepost`` 是預告表,沒有參考價
      - ``bulletin/exDailyQHis`` 只涵蓋民國 89/9~96/12(頁面自己註明),2013+ 全空
      - 舊版 ``web/stock/exright/dailyquo/exDailyQ_result.php`` 忽略日期參數
    正解是新站的 ``bulletin/exDailyQ``,吃**西元** ``startDate``/``endDate``(民國格式回
    「參數錯誤」),回應本身的日期欄卻是民國斜線格式。
    """
    r = requests_get(
        "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ",
        params={"startDate": start.strftime("%Y/%m/%d"),
                "endDate": end.strftime("%Y/%m/%d"), "response": "json"},
        headers={"User-Agent": _UA},
    )
    if r is None:
        return None
    try:
        payload = r.json()
    except ValueError:
        return None
    if payload.get("stat") != "ok":
        return None
    return parse_tpex_ex_dividend(payload)


def parse_tpex_revivt(payload):
    """TPEx ``bulletin/revivt``（減資恢復買賣）JSON -> DataFrame(stock_id, date, close_before, reference_price)。

    欄位靠 ``fields`` 動態定位；恢復日是**緊湊民國**「1151002」（不是斜線格式）。
    ``reference_price`` 取「減資恢復買賣開始日參考價格」（官方公告的恢復後參考價）。
    """
    tables = payload.get("tables") or []
    if not tables:
        raise ValueError("revivt 回應沒有 tables")
    t = tables[0]
    idx = {name: i for i, name in enumerate(t.get("fields") or [])}
    need = ("恢復買賣日期", "股票代號", "最後交易日之收盤價格", "減資恢復買賣開始日參考價格")
    if not all(k in idx for k in need):
        raise ValueError(f"revivt 欄位不符預期: {t.get('fields')}")
    rows, skipped = [], 0
    for r in t.get("data") or []:
        try:
            before = float(str(r[idx["最後交易日之收盤價格"]]).replace(",", ""))
            ref = float(str(r[idx["減資恢復買賣開始日參考價格"]]).replace(",", ""))
            if before <= 0 or ref <= 0:
                skipped += 1
                continue
            raw = str(r[idx["恢復買賣日期"]]).strip()
            rows.append({
                "stock_id": str(r[idx["股票代號"]]).strip(),
                "date": pd.Timestamp(int(raw[:-4]) + 1911, int(raw[-4:-2]), int(raw[-2:])),
                "close_before": before,
                "reference_price": ref,
            })
        except (ValueError, TypeError, IndexError):
            skipped += 1
    if skipped and not rows:
        raise ValueError(f"revivt 全部 {skipped} 列都無法解析，格式可能已變更")
    return pd.DataFrame(rows, columns=["stock_id", "date", "close_before", "reference_price"])


def crawl_tpex_revivt(start, end):
    """上櫃減資恢復買賣的官方參考價（``bulletin/revivt``，吃西元 ``startDate``/``endDate``）。

    走 ``tw_official_http``（不重試、不暖 cookie）。官方端點日期參數不合法時會靜默退回別的
    區間，所以必須核對回應自帶的 ``date``（``YYYYMMDD~YYYYMMDD``）等於請求區間，不符就回 None。
    失敗一律回 None（呼叫端 ``_fetch_by_year`` 會 raise）；區間內沒有減資是空 DataFrame。
    """
    resp, reason = tw_official_http.get(
        "https://www.tpex.org.tw/www/zh-tw/bulletin/revivt",
        params={"startDate": start.strftime("%Y/%m/%d"),
                "endDate": end.strftime("%Y/%m/%d"), "response": "json"},
        expect="json")
    if reason:
        return None
    payload = resp.json()
    if payload.get("stat") != "ok" or payload.get("date") != f"{start:%Y%m%d}~{end:%Y%m%d}":
        return None
    return parse_tpex_revivt(payload)


# ---- 分割／面額變更恢復買賣（官方「前收→參考價」，復權比例的唯一來源）----
# 回顯的請求日期只證明參數有被讀到，證明不了資料；所以每列日期都要落在請求區間內才收。
# 這幾張表的空窗口是常態（`stat` 正常、0 列），空結果不算失敗。


def _resume_rows(data, idx, label, start, end, *, code, before, ref, parse_day):
    """把恢復買賣表的列轉成 DataFrame(stock_id, date, close_before, reference_price)。

    任一列日期落在請求區間外 → ``ValueError`` 整包拒收（端點回了別段資料）。
    個別列無法解析（官方註明前收可能從缺）只跳過該列並印 ``**WARN``；全部無法解析視為改版。
    """
    rows, skipped = [], []
    for r in data:
        try:
            day = parse_day(r[idx["恢復買賣日期"]])
        except (ValueError, TypeError, IndexError):
            skipped.append(r)
            continue
        if not start <= day <= end:
            raise ValueError(f"{label} 回傳區間外的列 {day}（請求 {start} ~ {end}）")
        try:
            close_before = float(str(r[idx[before]]).replace(",", ""))
            reference = float(str(r[idx[ref]]).replace(",", ""))
        except (ValueError, TypeError, IndexError):
            skipped.append(r)
            continue
        if close_before <= 0 or reference <= 0:
            skipped.append(r)
            continue
        rows.append({"stock_id": str(r[idx[code]]).strip(), "date": pd.Timestamp(day),
                     "close_before": close_before, "reference_price": reference})
    if skipped and not rows:
        raise ValueError(f"{label} 全部 {len(skipped)} 列都無法解析，格式可能已變更")
    if skipped:
        print(f"**WARN: {label} 跳過 {len(skipped)} 列無法解析: {skipped[:3]}", flush=True)
    return pd.DataFrame(rows, columns=["stock_id", "date", "close_before", "reference_price"])


def parse_twse_resume(payload, start, end, *, code, label):
    """TWSE 恢復買賣表 JSON（TWTCAU／TWTB8U）。日期回顯位置兩表不同：前者在頂層、後者在 ``params``。"""
    if payload.get("stat") != "OK":
        raise ValueError(f"{label} stat={payload.get('stat')!r}")
    echo = payload.get("params") or payload
    want = (f"{start:%Y%m%d}", f"{end:%Y%m%d}")
    if (echo.get("startDate"), echo.get("endDate")) != want:
        raise ValueError(f"{label} 回應日期 {echo.get('startDate')}~{echo.get('endDate')} 與請求 {want} 不符")
    fields = payload.get("fields") or []
    idx = {name: i for i, name in enumerate(fields)}
    need = ("恢復買賣日期", code, "停止買賣前收盤價格", "恢復買賣參考價")
    if not all(k in idx for k in need):
        raise ValueError(f"{label} 欄位不符預期: {fields}")
    return _resume_rows(payload.get("data") or [], idx, label, start, end, code=code,
                        before="停止買賣前收盤價格", ref="恢復買賣參考價",
                        parse_day=_roc_slash_to_date)


def _compact_roc_to_date(s):
    """"1151002" -> 2026-10-02（TPEx bulletin 的緊湊民國日期）。"""
    raw = str(s).strip()
    return datetime.date(int(raw[:-4]) + 1911, int(raw[-4:-2]), int(raw[-2:]))


def parse_tpex_resume(payload, start, end, *, label):
    """TPEx 恢復買賣表 JSON（pvChgRslt／etfSplitRslt，兩表欄位相同）。"""
    if payload.get("stat") != "ok":
        raise ValueError(f"{label} stat={payload.get('stat')!r}")
    if payload.get("date") != f"{start:%Y%m%d}~{end:%Y%m%d}":
        raise ValueError(f"{label} 回應日期 {payload.get('date')} 與請求 {start}~{end} 不符")
    tables = payload.get("tables") or []
    if not tables:
        raise ValueError(f"{label} 回應沒有 tables")
    fields = tables[0].get("fields") or []
    idx = {name: i for i, name in enumerate(fields)}
    need = ("恢復買賣日期", "證券代號", "最後交易日之收盤價格", "恢復買賣開始參考價")
    if not all(k in idx for k in need):
        raise ValueError(f"{label} 欄位不符預期: {fields}")
    return _resume_rows(tables[0].get("data") or [], idx, label, start, end, code="證券代號",
                        before="最後交易日之收盤價格", ref="恢復買賣開始參考價",
                        parse_day=_compact_roc_to_date)


def _crawl_resume(url, params, parse, label):
    """走 ``tw_official_http``；取得或解析失敗印 ``**WARN`` 回 None，合法的零列回空 DataFrame。"""
    resp, reason = tw_official_http.get(url, params=params, expect="json")
    if reason:
        print(f"**WARN: {label} {reason}", flush=True)
        return None
    try:
        return parse(resp.json())
    except ValueError as exc:
        print(f"**WARN: {label} 拒收: {exc}", flush=True)
        return None


def _crawl_twse_resume(path, code, label, start, end):
    return _crawl_resume(
        f"https://www.twse.com.tw/rwd/zh/{path}",
        {"startDate": f"{start:%Y%m%d}", "endDate": f"{end:%Y%m%d}", "response": "json"},
        lambda p: parse_twse_resume(p, start, end, code=code, label=label), label)


def _crawl_tpex_resume(action, label, start, end):
    """要用 GET：實測 POST 配 2010 起點時 ``stat ok``、日期回顯吻合卻回 0 列。"""
    return _crawl_resume(
        f"https://www.tpex.org.tw/www/zh-tw/bulletin/{action}",
        {"startDate": f"{start:%Y/%m/%d}", "endDate": f"{end:%Y/%m/%d}", "response": "json"},
        lambda p: parse_tpex_resume(p, start, end, label=label), label)


def crawl_twse_etf_split(start, end):
    """上市 ETF 分割／反分割恢復買賣參考價（``split/TWTCAU``）。``分割(反分割)`` 欄可能空白，不靠它判方向。"""
    return _crawl_twse_resume("split/TWTCAU", "ETF代號", "TWTCAU", start, end)


def crawl_twse_par_value_change(start, end):
    """上市變更股票面額恢復買賣參考價（``change/TWTB8U``）。"""
    return _crawl_twse_resume("change/TWTB8U", "股票代號", "TWTB8U", start, end)


def crawl_tpex_par_value_change(start, end):
    """上櫃變更股票面額恢復買賣參考價（``bulletin/pvChgRslt``）。"""
    return _crawl_tpex_resume("pvChgRslt", "pvChgRslt", start, end)


def crawl_tpex_etf_split(start, end):
    """上櫃 ETF 分割恢復買賣參考價（``bulletin/etfSplitRslt``）；2026-11 實測全期 0 列，欄位與 pvChgRslt 相同。"""
    return _crawl_tpex_resume("etfSplitRslt", "etfSplitRslt", start, end)


# BWIBBU_d 的中文欄名 -> valuation 表欄名。欄位順序隨年代變動,一律靠 fields 動態定位。
_BWIBBU_D_MAP = {"本益比": "pe_ratio", "股價淨值比": "pb_ratio", "殖利率(%)": "dividend_yield"}


def parse_valuation_day(payload, date):
    """BWIBBU_d JSON -> DataFrame(stock_id, date, pe_ratio, pb_ratio, dividend_yield)。

    **欄位順序隨年代變**:2015 年回 5 欄(代號/名稱/本益比/殖利率/淨值比),2026 年回 8 欄
    且把殖利率排到本益比之前。用固定索引會讓舊資料的 PE 與 PB 整欄錯位,所以靠回應的
    ``fields`` 動態定位。無值以 "-" 表示,轉成 None。
    """
    fields = payload.get("fields") or []
    idx = {name: i for i, name in enumerate(fields)}
    if "證券代號" not in idx:
        raise ValueError(f"BWIBBU_d 欄位不符預期: {fields}")
    # 端點改版時 valuation 的 upsert **不做 coalesce**,寫進去的 NULL 會直接洗掉既有的
    # PE/PB/殖利率,而該日期又被 resume 視為完成 → 永久遺失且無聲。所以擋兩層:
    # (1) 欄名層:三個估值欄全不在 = 改版
    if not any(zh in idx for zh in _BWIBBU_D_MAP):
        raise ValueError(f"BWIBBU_d 三個估值欄全部消失,格式可能已變更: {fields}")
    missing = [zh for zh in _BWIBBU_D_MAP if zh not in idx]
    if missing:
        raise ValueError(f"BWIBBU_d 缺少估值欄 {missing},格式可能已變更(單欄改名也會"
                         f"讓該欄整批寫成 NULL 蓋掉既有值): {fields}")

    def _num(raw):
        s = str(raw).replace(",", "").strip()
        try:
            return float(s)
        except ValueError:
            return None  # "-" / "" / "N/A"

    rows = []
    for r in payload.get("data") or []:
        try:
            rec = {"stock_id": str(r[idx["證券代號"]]).strip(), "date": pd.to_datetime(date)}
        except IndexError:
            continue
        for zh, en in _BWIBBU_D_MAP.items():
            rec[en] = _num(r[idx[zh]]) if zh in idx and idx[zh] < len(r) else None
        rows.append(rec)
    if not rows:
        return None
    df = pd.DataFrame(rows).set_index(["stock_id", "date"])
    # (2) 值層:欄名都在但整欄變 "-"(來源當日故障)同樣是 NULL-wash。實測正常日 PB 與
    # 殖利率的非空率都在九成以上、PE 約六成(虧損公司無 PE),故門檻取 50% 只擋整欄失效。
    for zh, en in _BWIBBU_D_MAP.items():
        if en == "pe_ratio":
            continue                      # PE 正常就有大量空值(虧損公司),不設門檻
        if df[en].notna().mean() < 0.5:
            raise ValueError(
                f"BWIBBU_d {date}: {zh} 只有 {df[en].notna().mean() * 100:.0f}% 有值,"
                f"來源疑似故障;整批不發布以免把既有值洗成 NULL")
    return df


def crawl_valuation_day(date):
    """BWIBBU_d:**帶日期**的估值三率,可回補歷史。

    `fetch_valuation` 走的 BWIBBU_ALL 沒有 date 參數、只給當日,所以 valuation 表原本
    只能從第一次跑 daily 起累積(踩過:整張表只有 3 週)。本函式是回補用的來源。
    """
    r = requests_get(
        "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d",
        params={"date": date.strftime("%Y%m%d"), "selectType": "ALL", "response": "json"},
        headers={"User-Agent": _UA},
    )
    if r is None:
        return None
    try:
        payload = r.json()
    except ValueError:
        return None
    if payload.get("stat") != "OK":
        return None  # 非交易日回 "很抱歉,沒有符合條件的資料!"
    # `parse_valuation_day` 會把列蓋上「請求的日期」。TWSE 若對尚未發布的日子回 stat OK
    # 加前一日的表,D-1 的值就會被存成 D、resume 再把 D 視為已完成而永不重抓。
    # 所以一律比對回應自帶的日期;沒有日期欄也拒收(無法證明新鮮的數字不如沒有)。
    want = date.strftime("%Y%m%d")
    got = str(payload.get("date") or "")
    if got != want:
        print(f"**WARN: BWIBBU_d 回應日期 {got or '(無)'} ≠ 請求日 {want},拒收"
              "(多半是尚未發布)", flush=True)
        return None
    return parse_valuation_day(payload, date)


def parse_index_report(payload):
    """日期型 FMTQIK JSON -> OpenAPI 相同欄位，供既有 ETL 直接使用。"""
    fields = payload.get("fields") or []
    idx = {name: i for i, name in enumerate(fields)}
    names = ("日期", "成交金額", "發行量加權股價指數", "漲跌點數")
    if not all(name in idx for name in names):
        raise ValueError(f"FMTQIK 欄位不符預期: {fields}")
    rows = []
    for raw in payload.get("data") or []:
        day = _roc_slash_to_date(raw[idx["日期"]])
        rows.append({
            "Date": f"{day.year - 1911:03d}{day.month:02d}{day.day:02d}",
            "TradeValue": raw[idx["成交金額"]],
            "TAIEX": raw[idx["發行量加權股價指數"]],
            "Change": raw[idx["漲跌點數"]],
        })
    return rows


def _index_month_rows(rows, asof, label):
    """只信每列自帶日期；外層 date 可能只是回顯查詢參數，不能證明資料月份。"""
    for row in rows or ():
        raw = str(row.get("Date") or "").strip()
        try:
            if not re.fullmatch(r"\d{7}", raw):
                raise ValueError("missing or invalid row date")
            day = datetime.date(int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:]))
            if (day.year, day.month) != (asof.year, asof.month):
                raise ValueError(f"row date {day} outside requested month")
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"{label} {asof:%Y-%m}: {exc}") from exc
    return rows


def parse_index_ohlc_report(payload, asof):
    """MI_5MINS_HIST 月表 -> 既有指數 ETL 格式；欄名、列日期、OHLC 任一不可信就拒收。"""
    fields = payload.get("fields") or []
    idx = {name: i for i, name in enumerate(fields)}
    mapping = {"開盤指數": "Open", "最高指數": "High", "最低指數": "Low", "收盤指數": "TAIEX"}
    if not all(name in idx for name in ("日期", *mapping)):
        raise ValueError(f"MI_5MINS_HIST 欄位不符預期: {fields}")
    rows = []
    for raw in payload.get("data") or []:
        day = _roc_slash_to_date(raw[idx["日期"]])
        row = {"Date": f"{day.year - 1911:03d}{day.month:02d}{day.day:02d}"}
        for name, key in mapping.items():
            row[key] = raw[idx[name]]
        values = {k: float(str(row[k]).replace(",", "")) for k in mapping.values()}
        if not all(math.isfinite(v) and v > 0 for v in values.values()):
            raise ValueError("MI_5MINS_HIST OHLC 不是有效正數")
        if not (values["Low"] <= min(values["Open"], values["TAIEX"])
                <= max(values["Open"], values["TAIEX"]) <= values["High"]):
            raise ValueError("MI_5MINS_HIST OHLC 高低範圍不符")
        rows.append(row)
    return _index_month_rows(rows, asof, "MI_5MINS_HIST")


def fetch_index_ohlc(asof):
    """帶日期的 TAIEX 月 OHLC，自 2010-01 起可回補；失敗回 None，不以當月資料冒充。"""
    try:
        response = requests_get(
            "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST",
            params={"date": asof.strftime("%Y%m%d"), "response": "json"},
            headers={"User-Agent": _UA},
        )
        if response is not None:
            payload = response.json()
            if payload.get("stat") == "OK":
                rows = parse_index_ohlc_report(payload, asof)
                if rows:
                    return rows
    except (ValueError, TypeError, IndexError, AttributeError, OverflowError) as exc:
        print(f"**WARN MI_5MINS_HIST {asof:%Y-%m}: {exc}", flush=True)
        return None
    print(f"**WARN MI_5MINS_HIST {asof:%Y-%m}: 無回應或尚無資料", flush=True)
    return None


def fetch_index(asof=None, fallback=True):
    """FMTQIK:加權指數 TAIEX + 市場成交金額(該月整月)。

    ``fallback=False``:rwd 失敗（或該月無資料）就回 None 並印 WARN,不退到 openapi——
    openapi 只給**當月**,拿來補上個月沒有意義,還會讓 log 看起來像補到了。
    """
    asof = asof or datetime.date.today()
    r = requests_get(
        "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK",
        params={"date": asof.strftime("%Y%m%d"), "response": "json"},
        headers={"User-Agent": _UA},
    )
    if r is not None:
        try:
            payload = r.json()
            if payload.get("stat") == "OK":
                rows = _index_month_rows(parse_index_report(payload), asof, "FMTQIK")
                if rows:
                    return rows
        except (ValueError, TypeError, IndexError, AttributeError, OverflowError) as exc:
            # 印出原因:「回應月份不符(停更)」與「尚未發布」在 log 裡要分得開
            print(f"**WARN: FMTQIK rwd {asof:%Y-%m}: {exc}", flush=True)
    if not fallback:
        print(f"**WARN: FMTQIK {asof:%Y-%m} rwd 失敗或無資料,不走 openapi fallback"
              "(openapi 只給當月,補不了這個月)")
        return None
    # fallback 的 WARN 要帶 url,否則「當日未發布」與「端點改版」在 log 裡長得一樣
    url = "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK"
    rows = _valid_rows(_openapi_json(url), {"Date", "TAIEX", "Change", "TradeValue"}, url)
    try:
        return _index_month_rows(rows, asof, "FMTQIK openapi")
    except ValueError as exc:
        print(f"**WARN: {exc},拒收", flush=True)
        return None


# ---------------------------------------------------------------------------
# 上櫃三大法人／融資融券／估值 (TPEx www JSON，帶日期、全市場一次)
# ---------------------------------------------------------------------------

# 欄名重複（七組「買進／賣出／買賣超股數」），只能靠位置取值；先核對整排表頭，
# 來源插欄時整批錯位卻照樣是數字，不擋就靜默寫錯（同 _MARGIN_HEADER 的理由）。
_TPEX_INSTI_FIELDS = (
    ["代號", "名稱"] + ["買進股數", "賣出股數", "買賣超股數"] * 7 + ["三大法人買賣超股數合計"])
# 位置 -> T86 欄名：沿用 T86 欄名，etl.transform_institutional 與 crawl_day 的
# 欄位品質守門才能直接套用。分組依序：外資及陸資(不含外資自營商)、外資自營商、
# 外資及陸資合計、投信、自營商(自行買賣)、自營商(避險)、自營商合計。
_TPEX_INSTI_COLS = {
    4: "外陸資買賣超股數(不含外資自營商)",
    7: "外資自營商買賣超股數",
    13: "投信買賣超股數",
    22: "自營商買賣超股數",
    23: "三大法人買賣超股數",
}
_TPEX_MARGIN_FIELDS = [
    "代號", "名稱", "前資餘額(張)", "資買", "資賣", "現償", "資餘額", "資屬證金",
    "資使用率(%)", "資限額", "前券餘額(張)", "券賣", "券買", "券償", "券餘額",
    "券屬證金", "券使用率(%)", "券限額", "資券相抵(張)", "備註",
]
# 位置 -> MI_MARGN 欄名（etl.transform_margin 吃後者）；單位同為張
_TPEX_MARGIN_COLS = {_TPEX_MARGIN_FIELDS.index(zh): twse for zh, twse in {
    "資買": "融資買進", "資賣": "融資賣出", "資餘額": "融資今日餘額",
    "券買": "融券買進", "券賣": "融券賣出", "券餘額": "融券今日餘額",
}.items()}
_TPEX_PE_MAP = {"本益比": "pe_ratio", "股價淨值比": "pb_ratio", "殖利率(%)": "dividend_yield"}


def _tpex_table(payload, date, what):
    """取出 TPEx 回應的資料表；未發布／日期不符回 None。

    TPEx 對未來或未發布的日子照樣回 ``stat ok`` 並**回填請求的日期**、只是 0 列，所以外層
    ``date`` 只擋得住回錯日；0 列才是未發布的訊號。資料表另帶自己的民國日期（``"115/08/28"``，
    實測 2010~2026 有資料列時一定有），外層照填請求日、表卻是舊表的情況靠它擋——缺就拒收。"""
    if str(payload.get("stat", "")).lower() != "ok":
        return None
    want = date.strftime("%Y%m%d")
    got = str(payload.get("date") or "")
    if got != want:
        print(f"**WARN: TPEx {what} 回應日期 {got or '(無)'} ≠ 請求日 {want},拒收", flush=True)
        return None
    tables = payload.get("tables") or []
    if not tables or not tables[0].get("data"):
        return None
    try:
        table_day = _roc_slash_to_date(tables[0]["date"]).strftime("%Y%m%d")
    except (KeyError, ValueError, TypeError, OverflowError):
        table_day = "(無)"
    if table_day != want:
        print(f"**WARN: TPEx {what} 資料表日期 {table_day} ≠ 請求日 {want},拒收", flush=True)
        return None
    return tables[0]


def _tpex_num(raw):
    s = str(raw).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None  # "N/A" / "" / "-"


def _parse_tpex_fixed(payload, date, what, fields, cols):
    """表頭必須與 ``fields`` 完全一致（照位置取值），``cols`` 是 位置 -> 輸出欄名。"""
    tb = _tpex_table(payload, date, what)
    if tb is None:
        return None
    if list(tb.get("fields") or []) != list(fields):
        raise ValueError(f"TPEx {what}表頭與預期不符(欄位順序改了?): {tb.get('fields')}")
    rows = [{"stock_id": str(r[0]).strip(), "名稱": str(r[1]).strip(), "date": pd.to_datetime(date),
             **{name: _tpex_num(r[i]) for i, name in cols.items()}} for r in tb["data"]]
    return pd.DataFrame(rows).set_index(["stock_id", "date"])


def parse_tpex_institutional(payload, date):
    return _parse_tpex_fixed(payload, date, "三大法人", _TPEX_INSTI_FIELDS, _TPEX_INSTI_COLS)


def parse_tpex_margin(payload, date):
    return _parse_tpex_fixed(payload, date, "融資融券", _TPEX_MARGIN_FIELDS, _TPEX_MARGIN_COLS)


def parse_tpex_valuation(payload, date):
    """peQryDate -> DataFrame(stock_id, date, pe_ratio, pb_ratio, dividend_yield)。

    欄位數隨年代變（2026 多了「財報年/季」），一律靠欄名定位。NULL-wash 守門同
    ``parse_valuation_day``：valuation 的 upsert 不 coalesce，整欄失效寫進去就洗掉既有值。"""
    tb = _tpex_table(payload, date, "本益比")
    if tb is None:
        return None
    idx = {name: i for i, name in enumerate(tb.get("fields") or [])}
    missing = [zh for zh in ("股票代號", *_TPEX_PE_MAP) if zh not in idx]
    if missing:
        raise ValueError(f"TPEx 本益比缺少欄位 {missing},格式可能已變更: {tb.get('fields')}")
    rows = []
    for r in tb["data"]:
        rec = {"stock_id": str(r[idx["股票代號"]]).strip(), "date": pd.to_datetime(date)}
        for zh, en in _TPEX_PE_MAP.items():
            rec[en] = _tpex_num(r[idx[zh]])
        rows.append(rec)
    df = pd.DataFrame(rows).set_index(["stock_id", "date"])
    for en in ("pb_ratio", "dividend_yield"):   # PE 正常就大量 N/A（虧損公司）
        if df[en].notna().mean() < 0.5:
            raise ValueError(f"TPEx 本益比 {date}: {en} 只有 {df[en].notna().mean() * 100:.0f}% "
                             "有值,來源疑似故障;整批不發布以免把既有值洗成 NULL")
    return df


_TPEX_CHIP_PATHS = {
    "institutional": ("insti/dailyTrade", {"type": "Daily", "sect": "EW"}, parse_tpex_institutional),
    "margin": ("margin/balance", {}, parse_tpex_margin),
    "valuation": ("afterTrading/peQryDate", {}, parse_tpex_valuation),
}


def crawl_tpex_chip(kind, date):
    """上櫃 ``kind``（institutional／margin／valuation）某日全市場。失敗印 WARN 回 None。

    三大法人自 2018-01-15 起才有（之前回 0 列）；融資、本益比可回到 2007。"""
    path, params, parse = _TPEX_CHIP_PATHS[kind]
    url = f"https://www.tpex.org.tw/www/zh-tw/{path}"
    r = requests_get(url, params={**params, "date": date.strftime("%Y/%m/%d"),
                                  "response": "json"}, headers={"User-Agent": _UA})
    if r is None:
        print(f"**WARN: no response from {url} (連線失敗或 IP 被 TPEx 封鎖)")
        return None
    if r.status_code != 200:
        print(f"**WARN: HTTP {r.status_code} from {url}")
        return None
    try:
        return parse(r.json(), date)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:  # 格式改版一律 WARN
        print(f"**WARN: cannot parse TPEx {kind} for {date} ({exc})")
        return None


# ---------------------------------------------------------------------------
# 集保股權分散表 (TDCC)：開放資料（最新一週、全市場）＋個股查詢頁（約 51 週歷史）
# ---------------------------------------------------------------------------

_TDCC_OPENDATA = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
_TDCC_QUERY = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
_TDCC_TOKEN = re.compile(r'name="SYNCHRONIZER_TOKEN" value="([^"]+)"')
_TDCC_DATA_DATE = re.compile(r"資料日期：(\d+年\d+月\d+日)")
_TDCC_HEADER = ["資料日期", "證券代號", "持股分級", "人數", "股數", "占集保庫存數比例%"]
# 開放資料的 16 是「差異數調整」、17 是合計。個股查詢頁的序號在有差異數調整的週同樣是
# 16／17，沒有那列的週合計卻排在 16——所以合計一律靠「合計」字樣認，統一存 17。
_TDCC_TOTAL_LEVEL = 17


def parse_tdcc_opendata(text):
    """開放資料 1-5 CSV -> DataFrame(stock_id, date, level, holders, shares, pct)。"""
    df = pd.read_csv(StringIO(text.lstrip("﻿")), dtype=str)
    if list(df.columns) != _TDCC_HEADER:
        raise ValueError(f"集保開放資料表頭與預期不符: {list(df.columns)}")
    out = pd.DataFrame({
        "stock_id": df["證券代號"].str.strip(),
        "date": pd.to_datetime(df["資料日期"].str.strip(), format="%Y%m%d"),
        "level": pd.to_numeric(df["持股分級"], errors="coerce"),
        "holders": pd.to_numeric(df["人數"].str.replace(",", ""), errors="coerce"),
        "shares": pd.to_numeric(df["股數"].str.replace(",", ""), errors="coerce"),
        "pct": pd.to_numeric(df["占集保庫存數比例%"], errors="coerce"),
    })
    return out.dropna(subset=["stock_id", "date", "level"])


def fetch_tdcc_latest():
    """全市場最新一週股權分散。失敗印 WARN 回 None。

    開放資料沒有日期參數、只給最新一週，列上的資料日期是唯一的新鮮度依據——呼叫端
    （``crawl.crawl_holding_dist``）印出它；資料按自帶日期入庫，停更時只是重複 upsert 同一週。"""
    r = requests_get(_TDCC_OPENDATA, headers={"User-Agent": _UA}, timeout=60)
    if r is None or r.status_code != 200:
        print(f"**WARN: 集保開放資料抓取失敗 ({getattr(r, 'status_code', 'no response')})")
        return None
    try:
        return parse_tdcc_opendata(r.content.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        print(f"**WARN: 集保開放資料解析失敗 ({exc})")
        return None


def parse_tdcc_query(html, stock_id, want):
    """TDCC 個股查詢結果頁 -> DataFrame；頁面資料日期 ≠ ``want``（YYYYMMDD）或查無資料回 None。"""
    m = _TDCC_DATA_DATE.search(html)
    if not m:
        # 「查無此資料」頁：代號打錯、該週查無資料、帶作廢 token 三種回的頁面逐字相同（實測），
        # 這裡分不出原因，拒收但不印；由 crawl_tdcc_history 彙總成一條 WARN。
        return None
    got = _roc_to_date_or_none(m.group(1))
    if got is None or got.strftime("%Y%m%d") != want:
        # 日期認不得（無效日月、溢位年份）同樣只拒收這一週，不讓整檔的歷史查詢中斷
        print(f"**WARN: 集保查詢 {stock_id} 資料日期 {got or m.group(1)} ≠ 請求 {want},拒收")
        return None
    table = next((t for t in pd.read_html(StringIO(html))
                  if "持股/單位數分級" in [str(c) for c in t.columns]), None)
    if table is None or table.empty:
        return None
    level = pd.to_numeric(table["序"], errors="coerce")
    total = table["持股/單位數分級"].astype(str).str.replace(r"\s", "", regex=True) == "合計"
    level = level.mask(total, _TDCC_TOTAL_LEVEL)

    def num(col):
        return pd.to_numeric(table[col].astype(str).str.replace(",", ""), errors="coerce")

    out = pd.DataFrame({"stock_id": stock_id, "date": pd.Timestamp(got), "level": level,
                        "holders": num("人數"), "shares": num("股數/單位數"),
                        "pct": num("占集保庫存數比例 (%)")})
    return out.dropna(subset=["level"])


def crawl_tdcc_history(stock_id, weeks=None, delay=1.0):
    """單檔近 ``weeks`` 週（預設查詢頁提供的全部，約 51 週）。每週一個 POST；回 DataFrame 或 None。

    刻意用自己的 ``requests.Session`` 而不是 ``crawler.requests_get``：表單 token 從這個
    session 取得，後者連線失敗時會重建 session（沒驗證過 token 跨 session 能不能用），
    所以整串查詢固定同一個 session。"""
    import time

    ses = requests.Session()
    ses.headers["User-Agent"] = _UA
    try:
        r = ses.get(_TDCC_QUERY, timeout=30)
        r.raise_for_status()
        page = r.text
    except requests.RequestException as exc:
        print(f"**WARN: 集保查詢頁連線失敗 ({exc})")
        return None
    token = _TDCC_TOKEN.search(page)
    dates = re.findall(r'<option value="(\d{8})"', page)
    if not token or not dates:
        print("**WARN: 集保查詢頁格式不符(找不到 token 或日期選單)")
        return None
    frames, no_data = [], []
    for i, want in enumerate(dates[:weeks]):
        if i and delay:
            time.sleep(delay)            # 成功或失敗都照節奏打，不因失敗連發
        form = {"SYNCHRONIZER_TOKEN": token.group(1), "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
                "method": "submit", "firDate": dates[0], "scaDate": want,
                "sqlMethod": "StockNo", "stockNo": stock_id, "stockName": ""}
        try:
            r = ses.post(_TDCC_QUERY, data=form, timeout=30)
            r.raise_for_status()
        except requests.RequestException as exc:
            print(f"**WARN: 集保查詢 {stock_id} {want} 失敗 ({exc})")
            # 逾時的請求可能已送達伺服器、token 已在伺服端輪換，手上這個作廢了；不換的話下一週
            # 會靜默回空。同一個 session 重新 GET 查詢頁可拿到新的可用 token（實測）。
            fresh_token, reason = None, "查詢頁找不到 token"
            try:
                fresh = ses.get(_TDCC_QUERY, timeout=30)
                fresh.raise_for_status()
                fresh_token = _TDCC_TOKEN.search(fresh.text)
            except requests.RequestException as exc2:
                reason = exc2
            if fresh_token:
                token = fresh_token
            else:
                print(f"**WARN: 集保查詢 {stock_id} 無法重取 token ({reason}),後續週次可能全數拒收")
            continue
        # token 每次請求後輪換、舊的作廢（實測沿用舊 token 回空）：一拿到回應就先換，
        # 解析失敗也不例外——否則後面每一週都帶著作廢的 token 靜默失敗。
        nxt = _TDCC_TOKEN.search(r.text)
        if nxt:
            token = nxt
        if not _TDCC_DATA_DATE.search(r.text):
            no_data.append(want)
            continue
        try:
            df = parse_tdcc_query(r.text, stock_id, want)
        except (ValueError, KeyError) as exc:
            # 單週解析失敗只少那一週（read_html 找不到表、欄名改版都在這）
            print(f"**WARN: 集保查詢 {stock_id} {want} 解析失敗 ({type(exc).__name__}: {exc})")
            continue
        if df is not None:
            frames.append(df)
    if no_data:
        # 查無此資料的頁面分不出是代號錯、該週無資料還是 token 作廢：整串只印一條，附週次範圍
        cause = "代號是否正確" if not frames else "該週是否無資料或 token 作廢"
        print(f"**WARN: 集保查詢 {stock_id} 有 {len(no_data)} 週回「查無此資料」"
              f"({no_data[-1]}~{no_data[0]}),拒收;請確認{cause}")
    return pd.concat(frames, ignore_index=True) if frames else None
