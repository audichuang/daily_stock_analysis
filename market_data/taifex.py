"""期交所共用 CSV 取數／解析與外資大台 TXF 淨未平倉每日累積。"""

import csv
import datetime
import io
import os

from market_data import tw_official_http as http
from market_data.models import TaifexForeignFuturesOi
from market_data.writer import upsert

FUT_URL = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
PC_URL = "https://www.taifex.com.tw/cht/3/pcRatioDown"
# 起日往前推的曆日數：P/C 端點一次最多查約一個月，14 天裝得下長假。
LOOKBACK_DAYS = 14


def _parse_date(text):
    return datetime.datetime.strptime(text.strip(), "%Y/%m/%d").date()


def _reader(text, required):
    reader = csv.DictReader(io.StringIO(text))
    missing = [name for name in required if name not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"表頭缺欄位 {missing}（端點可能改版）")
    return reader


def parse_fut(text):
    """期貨 CSV → ``[(日期, 外資及陸資 臺股期貨 多空未平倉口數淨額)]``，依日期由舊到新。

    依欄名取值、不靠欄位位置；表頭缺必要欄位時 raise ValueError。"""
    reader = _reader(text, ("日期", "商品名稱", "身份別", "多空未平倉口數淨額"))
    rows = []
    for row in reader:
        if (row["商品名稱"] or "").strip() != "臺股期貨" or (row["身份別"] or "").strip() != "外資及陸資":
            continue
        rows.append((_parse_date(row["日期"]), int(row["多空未平倉口數淨額"].strip())))
    return sorted(rows)


def parse_pc(text):
    """P/C CSV → ``[(日期, 未平倉比%, 成交量比%)]``，依日期由舊到新。

    回應本身由新到舊、每列結尾多一個逗號（落在 DictReader 的 key None，忽略）。"""
    reader = _reader(text, ("日期", "買賣權未平倉量比率%", "買賣權成交量比率%"))
    rows = []
    for row in reader:
        rows.append((_parse_date(row["日期"]), float(row["買賣權未平倉量比率%"]),
                     float(row["買賣權成交量比率%"])))
    return sorted(rows)


def pick(rows, session):
    """新鮮度：最新一列日期必須＝場次。回 ``((最新列, 前一列或 None), None)`` 或 ``(None, 原因)``。"""
    if not rows:
        return None, "無資料列（非交易日或尚未公布）"
    latest = rows[-1]
    if latest[0] != session:
        return None, f"最新一列 {latest[0]} ≠ 預期場次 {session}，無法證明新鮮，不採用"
    return (latest, rows[-2] if len(rows) >= 2 else None), None


def _fetch(url, data):
    """回 ``(CSV 文字, None)`` 或 ``(None, 原因)``。錯誤頁先交給 `tw_official_http.error_reason` 判斷，可用才以 cp950 解碼。"""
    resp, reason = http.post(url, data=data, expect="csv")
    if reason is not None:
        return None, (f"期交所回應：{reason}" if resp is not None else reason)
    return resp.content.decode("cp950", errors="replace"), None


def query_dates(session):
    """只查官方近期窗口，迄日固定為已選定的場次，不拿今天冒充資料日。"""
    start = session - datetime.timedelta(days=LOOKBACK_DAYS)
    return {"queryStartDate": start.strftime("%Y/%m/%d"),
            "queryEndDate": session.strftime("%Y/%m/%d")}


def fetch_rows(url, data, parser):
    """共用取數／解析接縫；來源失敗回原因，不影響另一端點或每日其他來源。"""
    text, reason = _fetch(url, data)
    if reason is not None:
        return None, reason
    try:
        return parser(text), None
    except ValueError as error:
        return None, f"格式不符：{error}"


def daily_update(engine, asof=None):
    """每日增量：預設關閉；啟用後只存官方 14 天窗口內已自證日期的 TXF 外資淨額。

    未指定 asof 時沿用 health 的台北時間／17:00 門檻；指定時取該日或之前最近場次。
    不建表、不補造歷史、不存日變化；重跑以 date upsert 吃進官方修正。
    """
    if os.getenv("TAIFEX_OI_ACCUMULATE_ENABLED", "false").strip().lower() != "true":
        return 0
    # 惰性 import：health 也依賴 crawl，避免形成模組初始化循環。
    from market_data import health

    now = datetime.datetime.combine(asof, health.SESSION_COMPLETE_AFTER) if asof is not None else None
    session = health.expected_session(now=now)
    name = TaifexForeignFuturesOi.__tablename__
    if session is None:
        print(f"**WARN {name}: 交易日曆不可用，略過（不猜場次）", flush=True)
        return 0
    rows, reason = fetch_rows(FUT_URL, {**query_dates(session), "commodityId": "TXF"}, parse_fut)
    if reason is None:
        _, reason = pick(rows, session)
    if reason is None:
        start = session - datetime.timedelta(days=LOOKBACK_DAYS)
        if any(not start <= row[0] <= session for row in rows):
            reason = f"回應資料日超出查詢窗口 {start}..{session}，拒收"
    if reason is not None:
        print(f"**WARN {name}: {reason}", flush=True)
        return 0
    records = [{"date": day, "foreign_fut_oi": value} for day, value in rows]
    with engine.begin() as conn:
        written = upsert(conn, TaifexForeignFuturesOi.__table__, records, ["date"])
    # 離開交易後才報數；失敗由 crawl.daily_update 捕捉並繼續其他來源。
    print(f"{name} {written:,} rows, latest {session}", flush=True)
    return written
