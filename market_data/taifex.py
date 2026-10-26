"""期交所三大法人臺股期貨（大台 TXF）未平倉：抓取、解析、入庫 ``market.taifex_fut_oi``。

`scripts/taifex_positions.py`（`make morning` 的期交所籌碼區塊）與每日入庫共用這裡的
端點、抓取與解析；盤前那支仍只印、不寫 DB。入庫由 ``crawl.daily_update`` 在
``TAIFEX_OI_PERSIST_ENABLED`` 為真時呼叫（預設關，正式庫沒跑 migration 前開了也只印 WARN），
手動單跑用 ``python -m market_data.cli taifex-oi``。

**不回補歷史**：每次只查 ``LOOKBACK_DAYS`` 曆日的窗口，靠每天累積；窗口內已入庫的日子
冪等 upsert。

**資料日以回應每列自帶的日期為準**（端點停更照樣回 200，見 repo `AGENTS.md` §10）：

- 任何一列落在查詢窗口外（晚於迄日或早於起日）→ 回應對不上請求，**整包拒收**；
- 同一日三種身份別（自營商／投信／外資及陸資）不齊 → 只丟那一天、印 WARN（截斷回應）；
- 最新一列早於預期場次 → 照寫已有的日子（各自帶原日期，不會被當成今天），另印 WARN，
  這是唯一的停更訊號。

HTTP 走 `tw_official_http.post`（短 timeout、不重試）；錯誤頁判斷用它的 ``error_reason``，
判定可用之後才以 cp950 解碼 CSV（正常 CSV 是 MS950，卻標成 ``text/html``）。
``queryEndDate`` 一律填已收盤的場次，不填未來日：迄日落在未來時期交所整筆回 ``日期時間錯誤``。
"""

import csv
import datetime
import io
import os

from market_data import health, models
from market_data import tw_official_http as http

FUT_URL = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
# 起日往前推的曆日數：14 天裝得下長假，也是每日入庫的窗口（不另外回補更早的歷史）。
LOOKBACK_DAYS = 14
COMMODITY_TXF = "TXF"
_COMMODITY_NAMES = {"臺股期貨": COMMODITY_TXF}
IDENTITIES = {"自營商": "dealer", "投信": "trust", "外資及陸資": "foreign"}
_PK = ["date", "commodity_id", "identity"]
# CSV 欄名 → 表欄位（口數與契約金額千元）
_OI_COLUMNS = {
    "多方未平倉口數": "long_oi",
    "空方未平倉口數": "short_oi",
    "多空未平倉口數淨額": "net_oi",
    "多方未平倉契約金額(千元)": "long_oi_amount",
    "空方未平倉契約金額(千元)": "short_oi_amount",
    "多空未平倉契約金額淨額(千元)": "net_oi_amount",
}
_REQUIRED = ("日期", "商品名稱", "身份別", *_OI_COLUMNS)
FLAG_ENV = "TAIFEX_OI_PERSIST_ENABLED"
_TRUE = ("1", "true", "yes", "on")


def persist_enabled():
    """``TAIFEX_OI_PERSIST_ENABLED`` 是否為真；未設或其他值一律視為關（不連期交所、不寫 DB）。"""
    return os.environ.get(FLAG_ENV, "").strip().lower() in _TRUE


def parse_date(text):
    return datetime.datetime.strptime(text.strip(), "%Y/%m/%d").date()


def csv_reader(text, required):
    """依欄名讀 CSV；表頭缺必要欄位時 raise ValueError（端點可能改版）。"""
    reader = csv.DictReader(io.StringIO(text))
    missing = [name for name in required if name not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"表頭缺欄位 {missing}（端點可能改版）")
    return reader


def _int(text):
    return int((text or "").strip().replace(",", ""))


def parse_fut_rows(text):
    """期貨 CSV → 臺股期貨各身份別的未平倉 dict 清單（鍵同 ``models.TaifexFutOI``），依日期、身份別排序。

    依欄名取值、不靠欄位位置；表頭缺欄位、或出現不認得的身份別時 raise ValueError。
    其他商品的列略過（``commodityId=TXF`` 時本來就只有臺股期貨）。"""
    rows = []
    for row in csv_reader(text, _REQUIRED):
        commodity = _COMMODITY_NAMES.get((row["商品名稱"] or "").strip())
        if commodity is None:
            continue
        name = (row["身份別"] or "").strip()
        if name not in IDENTITIES:
            raise ValueError(f"不認得的身份別 {name!r}（端點可能改版）")
        rec = {"date": parse_date(row["日期"]), "commodity_id": commodity, "identity": IDENTITIES[name]}
        for column, field in _OI_COLUMNS.items():
            rec[field] = _int(row[column])
        rows.append(rec)
    return sorted(rows, key=lambda r: (r["date"], r["identity"]))


def query_window(end, start=None):
    """``(起日, 迄日)``；起日預設 ``end - LOOKBACK_DAYS``。"""
    return (start or end - datetime.timedelta(days=LOOKBACK_DAYS)), end


def query_data(start, end, commodity=COMMODITY_TXF):
    return {"queryStartDate": start.strftime("%Y/%m/%d"), "queryEndDate": end.strftime("%Y/%m/%d"),
            "commodityId": commodity}


def fetch_csv(url, data):
    """回 ``(CSV 文字, None)`` 或 ``(None, 原因)``。錯誤頁先交給 `tw_official_http.error_reason` 判斷，可用才以 cp950 解碼。"""
    resp, reason = http.post(url, data=data, expect="csv")
    if reason is not None:
        return None, (f"期交所回應：{reason}" if resp is not None else reason)
    return resp.content.decode("cp950", errors="replace"), None


def guard_rows(rows, start, end):
    """入庫前的資料日檢查，回 ``(可寫的列, 被丟掉的不完整日期)``。

    任何一列落在 ``[start, end]`` 外就 raise ValueError（整包拒收：回應對不上請求）；
    同一日身份別不齊（截斷回應）只丟那一天。同鍵重複但數值不同也 raise。"""
    outside = sorted({r["date"] for r in rows if not start <= r["date"] <= end})
    if outside:
        raise ValueError(f"回應含查詢窗口 {start}~{end} 以外的日期 {outside}，整包拒收")
    by_key = {}
    for rec in rows:
        key = tuple(rec[k] for k in _PK)
        if key in by_key and by_key[key] != rec:
            raise ValueError(f"同一鍵 {key} 出現兩個不同的值，整包拒收")
        by_key[key] = rec
    want = set(IDENTITIES.values())
    seen = {}
    for date, _commodity, identity in by_key:
        seen.setdefault(date, set()).add(identity)
    incomplete = sorted(d for d, ids in seen.items() if ids != want)
    kept = [r for r in by_key.values() if r["date"] not in incomplete]
    return sorted(kept, key=lambda r: (r["date"], r["identity"])), incomplete


def store(conn, records):
    """upsert 進 ``market.taifex_fut_oi``，回寫入列數（期交所事後更正會覆蓋舊值）。"""
    from market_data.writer import upsert

    return upsert(conn, models.TaifexFutOI.__table__, records, _PK)


def target_session(asof=None, now=None, is_session=None):
    """要查的迄日：已收盤的預期場次，``asof`` 較早時取 ``asof`` 當天或之前最近的交易日。

    日曆不可用回 None——不退回週一~五猜，也不拿今天當迄日（未收盤時期交所整筆回日期錯誤）。"""
    expected = health.expected_session(now=now, is_session=is_session)
    if expected is None or asof is None or asof >= expected:
        return expected
    return health.session_before(asof + datetime.timedelta(days=1), is_session=is_session)


def update(engine, asof=None, now=None, is_session=None, out=print):
    """抓 ``LOOKBACK_DAYS`` 窗口 → 資料日檢查 → 一個交易 upsert，commit 後才印列數。

    資料問題（端點錯誤、格式不符、窗口外日期、日曆不可用）只印 ``**WARN`` 回 0，不 raise；
    DB 錯誤（例如正式庫還沒跑 migration）照常拋，由呼叫端決定要不要擋。"""
    end = target_session(asof, now=now, is_session=is_session)
    if end is None:
        out("**WARN taifex_fut_oi: 交易日曆不可用，略過（不退回週一~五猜場次）")
        return 0
    start, end = query_window(end)
    text, reason = fetch_csv(FUT_URL, query_data(start, end))
    try:
        if reason is not None:
            raise ValueError(reason)
        records, incomplete = guard_rows(parse_fut_rows(text), start, end)
    except ValueError as error:
        out(f"**WARN taifex_fut_oi {start}~{end}: {error}；不寫入")
        return 0
    if incomplete:
        out(f"**WARN taifex_fut_oi: {', '.join(map(str, incomplete))} 身份別不齊（回應可能截斷），這幾天不寫入")
    with engine.begin() as conn:
        n = store(conn, records)
    latest = max((r["date"] for r in records), default=None)
    out(f"taifex_fut_oi {n:,} rows, latest {latest}")
    if latest != end:
        out(f"**WARN taifex_fut_oi: 最新一列 {latest} ≠ 預期場次 {end}（尚未公布或端點停更）")
    return n
