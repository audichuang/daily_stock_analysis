"""境內基金：投信投顧公會（SITCA）每日淨值與基本資料入庫，鉅亨（cnyes）補歷史淨值。

來源與可信度：
- **官方**：公會在政府開放資料平台發布的兩個 CSV（UTF-8 BOM）。
  - ``nav.csv``：每檔基金**最近一筆**淨值，約 4,400 列；**同一份檔案混有多個淨值日**
    （2026-10-21 23:00 實測 3,931 列是 10/20、486 列是 10/21——各投信公布時間不同），
    所以一律以每列自帶的「日期」入庫，不用抓取日。
  - 基本資料 CSV：月更，名稱、投信、類型、ISIN、規模、成立日。
- **非官方**：鉅亨 ``fund.api.cnyes.com`` 的 ``format=chart`` 一次回完整歷史淨值
  （2011 年起），另有前十大持股。只在公會資料之外補缺日，``ON CONFLICT DO NOTHING``
  不覆蓋官方值；鉅亨代碼以 ISIN 搜尋後**比對 ISIN 相符**才寫進 ``fund_info.cnyes_id``。

公會檔只有最新一筆，某天的淨值若在下一輪抓取前就被隔天的值取代，那一天就永遠抓不到；
所以 ``daily`` 另對「已有鉅亨對照」的基金（被查詢或持有過的）補近一個月歷史。

HTTP 走 ``tw_official_http``（短 timeout、不重試）；兩個來源都不是 TWSE，不需要暖 cookie。
"""

import csv
import datetime as _dt
import io
import re
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from market_data import tw_official_http as http
from market_data.models import FundInfo, FundNav
from market_data.writer import dedupe, upsert

SITCA_NAV_URL = "https://www.sitca.org.tw/MemberK0000/F/03/nav.csv"
SITCA_INFO_URL = ("https://www.sitca.org.tw/MemberK0000/F/03/"
                  "43476%E6%8A%95%E4%BF%A1%E6%8A%95%E9%A1%A7%E5%85%AC%E6%9C%83"
                  "%E5%A2%83%E5%85%A7%E5%9F%BA%E9%87%91%E5%9F%BA%E6%9C%AC%E8%B3%87%E6%96%99.csv")
CNYES_FUND_API = "https://fund.api.cnyes.com/fund/api/v1/funds"
CNYES_SEARCH_URL = "https://ess.api.cnyes.com/ess/api/v1/siteSearch/main"

NAV_REQUIRED = ("日期", "基金統編", "基金名稱", "基金淨值")
INFO_REQUIRED = ("統編", "基金名稱", "基金ISIN Code")
# 「近一個月」補缺日的窗口；公會檔被隔天取代的缺口只會是最近幾個營業日
RECENT_HISTORY_DAYS = 35
CHUNK_ROWS = 2000
TAIPEI = ZoneInfo("Asia/Taipei")

_TYPE_RE = re.compile(r"^\((\w+)\)\s*(.*)$")
_MARK_RE = re.compile(r"<[^>]+>")


class FundSourceError(RuntimeError):
    """來源回應不可用（連線失敗、錯誤頁、缺欄位）。"""


def _fit(value, column):
    """截到欄位長度：Postgres 的 VARCHAR 超長會讓整批寫入回滾（見根 AGENTS.md）。"""
    if value is None:
        return None
    limit = FundInfo.__table__.c[column].type.length
    value = value.strip()
    return (value[:limit] if limit else value) or None


def _num(value):
    value = (value or "").strip().replace(",", "")
    if value in ("", "-", "--"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _ymd(value):
    value = (value or "").strip()
    try:
        return _dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _read_csv(raw, required, label):
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if not rows:
        raise FundSourceError(f"{label}: 沒有資料列")
    missing = [c for c in required if c not in rows[0]]
    if missing:
        raise FundSourceError(f"{label}: 缺欄位 {missing}（改版？）")
    return rows


def parse_sitca_nav(raw):
    """公會 nav.csv → (fund_info 部分欄位, fund_nav 列)。淨值為 ``-`` 的列（暫停計價級別）略過。"""
    infos, navs = [], []
    for r in _read_csv(raw, NAV_REQUIRED, "SITCA nav.csv"):
        fund_id = (r.get("基金統編") or "").strip()
        day = _ymd(r.get("日期"))
        if not fund_id or day is None or not (r.get("基金名稱") or "").strip():
            continue
        infos.append({
            "fund_id": fund_id,
            "name": _fit(r.get("基金名稱"), "name"),
            "company": _fit(r.get("公司名稱"), "company"),
            "sitca_code": _fit(r.get("基金代號"), "sitca_code"),
            "type_code": _fit(r.get("類型代號"), "type_code"),
            "currency": _fit(r.get("幣別"), "currency"),
        })
        nav = _num(r.get("基金淨值"))
        if nav is None:
            continue
        navs.append({
            "fund_id": fund_id, "date": day, "nav": nav,
            "change": _num(r.get("漲跌")), "change_pct": _num(r.get("漲跌幅")),
            "source": "sitca",
        })
    return infos, navs


def parse_sitca_info(raw):
    """公會基本資料 CSV → fund_info 列。"""
    out = []
    for r in _read_csv(raw, INFO_REQUIRED, "SITCA 基本資料"):
        fund_id = (r.get("統編") or "").strip()
        if not fund_id or not (r.get("基金名稱") or "").strip():
            continue
        type_code, type_name = None, (r.get("基金類型別") or "").strip()
        m = _TYPE_RE.match(type_name)
        if m:
            type_code, type_name = m.group(1), m.group(2)
        aum = _num(r.get("基金級別規模_金額"))
        out.append({
            "fund_id": fund_id,
            "name": _fit(r.get("基金名稱"), "name"),
            "company": _fit(r.get("公司名稱"), "company"),
            "isin": _fit(r.get("基金ISIN Code"), "isin"),
            "type_code": _fit(type_code, "type_code"),
            "type_name": _fit(type_name, "type_name"),
            "invest_area": _fit(r.get("投資地區"), "invest_area"),
            "currency": _fit(r.get("基金計價幣別"), "currency"),
            "inception_date": _ymd(r.get("基金/級別成立日期")),
            "aum": int(aum) if aum is not None else None,
            "aum_currency": _fit(r.get("基金規模幣別"), "aum_currency"),
            "aum_date": _ymd(r.get("基金規模日期")),
            "dividend_policy": _fit(r.get("基金配息規定(基金收益分配規定)"), "dividend_policy"),
        })
    return out


def _fetch(url, expect, label, params=None):
    resp, reason = http.get(url, params=params, expect=expect)
    if reason:
        raise FundSourceError(f"{label}: {reason}")
    return resp


def _upsert_info(conn, rows, columns):
    """只更新 ``columns``：兩個公會檔各給一部分欄位，互相不能用 NULL 蓋掉對方。"""
    if not rows:
        return 0
    rows = dedupe(rows, ["fund_id"])
    for chunk in _chunks(rows):
        stmt = insert(FundInfo.__table__).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["fund_id"],
            set_={c: stmt.excluded[c] for c in columns if c != "fund_id"})
        conn.execute(stmt)
    return len(rows)


def _chunks(rows, size=None):
    # 一個 INSERT 的綁定參數上限是 65,535；基本資料約 4,400 列 × 13 欄會超過，分批寫
    size = size or CHUNK_ROWS
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def store_sitca(conn, infos, detail, navs):
    """公會兩檔寫入同一個交易：淨值列以官方值覆蓋（含先前由鉅亨補的同日列）。"""
    _upsert_info(conn, infos, ["name", "company", "sitca_code", "type_code", "currency"])
    _upsert_info(conn, detail, ["name", "company", "isin", "type_code", "type_name", "invest_area",
                                "currency", "inception_date", "aum", "aum_currency", "aum_date",
                                "dividend_policy"])
    for chunk in _chunks(dedupe(navs, ["fund_id", "date"])):
        upsert(conn, FundNav.__table__, chunk, ["fund_id", "date"])


def crawl_sitca(engine, with_info=True):
    """抓公會淨值檔（與基本資料檔）入庫；回傳 dict 摘要。任一檔失敗 raise ``FundSourceError``。"""
    nav_raw = _fetch(SITCA_NAV_URL, "csv", "SITCA nav.csv").content
    infos, navs = parse_sitca_nav(nav_raw)
    detail = parse_sitca_info(_fetch(SITCA_INFO_URL, "csv", "SITCA 基本資料").content) if with_info else []
    with engine.begin() as conn:
        store_sitca(conn, infos, detail, navs)
    dates = sorted({r["date"] for r in navs})
    return {"funds": len({r["fund_id"] for r in infos}), "nav_rows": len(navs),
            "info_rows": len(detail), "latest": dates[-1] if dates else None}


def _cnyes_json(url, label, params=None):
    resp = _fetch(url, "json", label, params=params)
    return resp.json()


def resolve_cnyes_id(isin):
    """以 ISIN 搜尋鉅亨代碼；搜尋結果的 ISIN 必須完全相符才採用（搜尋是模糊比對）。"""
    if not isin:
        return None
    data = _cnyes_json(CNYES_SEARCH_URL, "鉅亨搜尋",
                       params={"q": isin, "category": "FUND", "limit": 5})
    for item in ((data.get("data") or {}).get("quoteFunds") or []):
        if _MARK_RE.sub("", item.get("isin") or "") == isin:
            return item.get("cnyesId")
    return None


def parse_cnyes_chart(fund_id, items):
    """鉅亨 ``format=chart`` → fund_nav 列。

    ``tradeDate`` 是淨值日的**台北** 00:00：實測 1792512000（UTC 2026-10-20 16:00）
    與公會檔 20261021 同一筆淨值，用 UTC 取日期會整串早一天。"""
    dates, navs = items.get("tradeDate") or [], items.get("nav") or []
    changes, pcts = items.get("change") or [], items.get("changePercent") or []
    if len(dates) != len(navs):
        raise FundSourceError(f"鉅亨 {fund_id}: tradeDate 與 nav 長度不一致（改版？）")
    out = []
    for i, (ts, nav) in enumerate(zip(dates, navs)):
        if ts is None or nav is None:
            continue
        out.append({
            "fund_id": fund_id,
            "date": _dt.datetime.fromtimestamp(int(ts), TAIPEI).date(),
            "nav": float(nav),
            "change": changes[i] if i < len(changes) else None,
            "change_pct": pcts[i] if i < len(pcts) else None,
            "source": "cnyes",
        })
    return out


def _fund_row(conn, fund_id):
    return conn.execute(text("SELECT fund_id, isin, cnyes_id FROM market.fund_info WHERE fund_id = :f"),
                        {"f": fund_id}).mappings().first()


def ensure_cnyes_id(engine, fund_id):
    """回傳（必要時查詢並寫入）基金的鉅亨代碼；查不到回 None。"""
    with engine.connect() as conn:
        row = _fund_row(conn, fund_id)
    if row is None:
        return None
    if row["cnyes_id"]:
        return row["cnyes_id"]
    cnyes_id = resolve_cnyes_id(row["isin"])
    if cnyes_id:
        with engine.begin() as conn:
            conn.execute(text("UPDATE market.fund_info SET cnyes_id = :c WHERE fund_id = :f"),
                         {"c": cnyes_id, "f": fund_id})
    return cnyes_id


def backfill_history(engine, fund_id, start=None):
    """從鉅亨補 ``fund_id`` 的歷史淨值（``start`` 起，預設全期）；回傳新寫入的列數。

    已有的日子（含公會官方值）一律不覆蓋。"""
    cnyes_id = ensure_cnyes_id(engine, fund_id)
    if not cnyes_id:
        raise FundSourceError(f"{fund_id}: 找不到 ISIN 相符的鉅亨基金代碼")
    params = {"format": "chart"}
    if start is not None:
        params["startAt"] = int(_dt.datetime.combine(start, _dt.time(), TAIPEI).timestamp())
    items = (_cnyes_json(f"{CNYES_FUND_API}/{cnyes_id}/nav", f"鉅亨 {fund_id} 歷史淨值",
                         params=params).get("items") or {})
    with engine.begin() as conn:
        return store_history(conn, parse_cnyes_chart(fund_id, items))


def store_history(conn, rows):
    """寫入鉅亨歷史淨值：只補沒有的日子，既有列（尤其公會官方值）不動。回傳新寫入列數。"""
    rows = dedupe(rows, ["fund_id", "date"])
    if not rows:
        return 0
    added = 0
    for chunk in _chunks(rows):
        # 多列 VALUES 的 rowcount 在 psycopg 下不可靠（實測回 -2），用 RETURNING 數實際寫入的列
        result = conn.execute(insert(FundNav.__table__).values(chunk)
                              .on_conflict_do_nothing(index_elements=["fund_id", "date"])
                              .returning(FundNav.__table__.c.date))
        added += len(result.fetchall())
    return added


def fetch_top_holdings(cnyes_id):
    """鉅亨前十大持股（即時抓、不入庫）：``[{name, sector, weight, country}]``。"""
    data = _cnyes_json(f"{CNYES_FUND_API}/{cnyes_id}/holdings", f"鉅亨 {cnyes_id} 持股")
    out = []
    for item in ((data.get("items") or {}).get("data") or []):
        out.append({"name": item.get("name"), "sector": item.get("sector"),
                    "weight": item.get("value"), "country": item.get("country")})
    return out


def refresh_tracked(engine, asof=None, days=RECENT_HISTORY_DAYS):
    """對已有鉅亨對照的基金補近 ``days`` 天歷史；單檔失敗只印 WARN。回傳 (成功檔數, 新增列數)。"""
    asof = asof or _dt.date.today()
    with engine.connect() as conn:
        ids = [r[0] for r in conn.execute(text(
            "SELECT fund_id FROM market.fund_info WHERE cnyes_id IS NOT NULL ORDER BY fund_id"))]
    ok, added = 0, 0
    for fund_id in ids:
        try:
            added += backfill_history(engine, fund_id, start=asof - _dt.timedelta(days=days))
            ok += 1
        except FundSourceError as exc:
            print(f"**WARN fund history {fund_id}: {exc}")
    return ok, added


def daily_update(engine, asof=None):
    """``cli funds`` 與 ``crawl.daily_update`` 的基金段：公會快照＋已追蹤基金的近期補缺。"""
    res = crawl_sitca(engine)
    print(f"fund_nav sitca {res['nav_rows']:,} rows ({res['funds']:,} funds), latest {res['latest']}")
    ok, added = refresh_tracked(engine, asof=asof)
    print(f"fund_nav cnyes refresh {ok} funds, {added:,} new rows")
    return res
