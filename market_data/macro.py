"""總經日線、Fed 利率預期、重大事件行事曆：抓取、解析、入庫 ``market`` schema 三張表。

- ``macro_series``：yfinance 日線（美債殖利率、美元、匯率、原油、黃金、費半、韓股…）與 FRED
  的 2／10 年期美債。**代號清單只有一份，就是這裡的 ``SERIES``**；``scripts/overnight.py`` 取
  ``overnight=True`` 的那幾列，不另外維護清單。
- ``rate_expectations``：Kalshi ``KXFEDDECISION`` 各會議各結果的買賣價中點，每天一份快照。
- ``event_calendar``：FOMC 決議日（Fed 官網為主、Kalshi 補官網還沒列的會議）與 watchlist 的
  財報日（yfinance，一律標 ``estimated``——它不給確認狀態，實測 MSFT 給的日期比公司公告晚一天）。

入庫由 ``crawl.daily_update`` 在 ``MACRO_PERSIST_ENABLED`` 不為關時呼叫（預設開：只有本機
``make morning``／``daily_report.sh`` 會跑 daily，NAS 不跑）；手動單跑 ``python -m market_data.cli macro``。
三段各自獨立，任何一段失敗（來源掛掉、正式庫沒跑 migration）只印 ``**WARN``，不 raise。

**日期以資料列自帶的為準**：yfinance 每列用它自己的交易日存，不用抓取日；Kalshi 合約的
``updated_time`` 存進 ``source_updated_at``，合約沒人交易時看得出來。
"""

import csv
import datetime
import io
import os
import re
from collections import namedtuple
from zoneinfo import ZoneInfo

from market_data import models

TAIPEI = ZoneInfo("Asia/Taipei")
NEW_YORK = ZoneInfo("America/New_York")

# id：yfinance 代號或 FRED:<代號>；kind：yield 的變化用 bp 表示；overnight：給 scripts/overnight.py 用；
# group：overnight 的市場分組（us/kr/cont），其餘為 macro；why：overnight 印出的理由
Series = namedtuple("Series", "id name group kind overnight why")
SERIES = (
    Series("^DJI", "道瓊", "us", "index", True, "分辨全面承壓還是族群輪動"),
    Series("^GSPC", "標普500", "us", "index", True, "同上"),
    Series("^IXIC", "那斯達克", "us", "index", True, "科技股整體"),
    Series("^SOX", "費城半導體", "us", "index", True, "台股是半導體權重市場，解釋力高於大盤三兄弟"),
    Series("TSM", "台積電ADR", "us", "index", True, "折算台積電開盤；它一檔佔加權指數約三成"),
    Series("MU", "美光", "us", "index", True,
           "**記憶體的隔夜代理**：台灣記憶體對它 t−1 相關 0.364，對費半同日只 0.123"),
    Series("000660.KS", "SK海力士", "kr", "index", True, "記憶體的同日代理，r=0.554（籃子 0.577）"),
    Series("005930.KS", "三星電子", "kr", "index", True, "同上"),
    Series("^KS11", "KOSPI", "kr", "index", True, "分辨韓國記憶體崩跌是族群現象還是全市場"),
    Series("^VIX", "VIX恐慌指數", "cont", "level", True,
           "分辨族群殺盤與系統性 risk-off——費半崩而 VIX 不動，是前者"),
    Series("CL=F", "西德州原油", "cont", "index", True, "對非電子（航運燃油、傳產、內需）方向常與電子相反"),
    Series("TWD=X", "美元兌台幣", "cont", "index", True, "ADR 折算與外資匯入匯出"),
    Series("^TNX", "美10年殖利率", "macro", "yield", False, "估值的分母；升＝高本益比股承壓"),
    Series("FRED:DGS2", "美2年殖利率", "macro", "yield", False, "最貼近 Fed 政策預期的天期"),
    Series("FRED:DGS10", "美10年殖利率(FRED)", "macro", "yield", False, "官方收盤，對照 ^TNX"),
    Series("DX-Y.NYB", "美元指數", "macro", "index", False, "強美元＝資金回流美國、新興市場承壓"),
    Series("JPY=X", "美元兌日圓", "macro", "index", False, "日圓套利交易的鬆緊"),
    Series("BZ=F", "布蘭特原油", "macro", "index", False, "通膨與 Fed 升息理由"),
    Series("GC=F", "黃金", "macro", "index", False, "避險與實質利率"),
    Series("HG=F", "銅", "macro", "index", False, "景氣循環"),
    Series("HYG", "高收益債ETF", "macro", "index", False, "信用壓力：跌破長均線＝風險偏好轉弱"),
    Series("EWT", "台灣ETF(EWT)", "macro", "index", False, "外資在美股時段對台股的定價"),
)
FLAG_ENV = "MACRO_PERSIST_ENABLED"
WATCHLIST_ENV = "MACRO_EARNINGS_WATCHLIST"
DEFAULT_WATCHLIST = ("MSFT", "GOOGL", "AMZN", "META", "AAPL", "NVDA", "TSM", "MU", "AVGO", "AMD", "ORCL", "TSLA")
_FALSE = ("0", "false", "no", "off")
YF_PERIOD = "2y"          # 每天整段重抓儀表會用到的窗口（一年高點、MA200）：Yahoo 的 Close 已做分割調整，
                          # 只重抓近期的話分割後新舊列會是兩種尺度；2 年以前的列可能停在舊尺度，儀表不讀那段
FRED_LOOKBACK_DAYS = 800
KALSHI_URL = ("https://api.elections.kalshi.com/trade-api/v2/markets"
              "?series_ticker=KXFEDDECISION&status=open&limit=200")
FED_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}&cosd={start}"
TIMEOUT = 20
# Kalshi 合約後綴 → 結果
OUTCOMES = {"H26": "hike_gt25", "H25": "hike_25", "H0": "hold", "C25": "cut_25", "C26": "cut_gt25"}
_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), start=1)}


def persist_enabled():
    """``MACRO_PERSIST_ENABLED`` 未設視為開；設成 0/false/no/off 才關。"""
    return os.environ.get(FLAG_ENV, "").strip().lower() not in _FALSE


def watchlist():
    raw = os.environ.get(WATCHLIST_ENV, "").strip()
    if not raw:
        return list(DEFAULT_WATCHLIST)
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def overnight_series():
    """``scripts/overnight.py`` 的清單：``(名稱, 代號, 理由, 市場組)``，順序即印出順序。"""
    return [(s.name, s.id, s.why, s.group) for s in SERIES if s.overnight]


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def http_get(url, **kwargs):
    """唯一的 HTTP 出口（測試的 mock 接縫）；非 2xx 直接 raise。"""
    import requests

    resp = requests.get(url, timeout=TIMEOUT, **kwargs)
    resp.raise_for_status()
    return resp


# ---------- macro_series ----------

def yf_rows(series_id, closes, now=None):
    """yfinance ``Close`` Series（index 為交易日）→ 入庫列；NaN 略過，日期用每列自己的交易日。"""
    now = now or _now()
    rows = []
    for ts, value in closes.items():
        if value is None or value != value:  # NaN
            continue
        rows.append({"series_id": series_id, "date": ts.date(), "value": float(value),
                     "source": "yfinance", "updated_at": now})
    return rows


def parse_fred_csv(series_id, text, now=None):
    """FRED fredgraph.csv → 入庫列；缺值（``.`` 或空白）略過。表頭不是 ``日期,代號`` 就 raise。"""
    now = now or _now()
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    code = series_id.split(":", 1)[1]
    if not header or len(header) < 2 or header[1].strip() != code:
        raise ValueError(f"FRED {code} 表頭不符 {header!r}（端點可能改版）")
    rows = []
    for rec in reader:
        if len(rec) < 2 or rec[1].strip() in ("", "."):
            continue
        rows.append({"series_id": series_id, "date": datetime.date.fromisoformat(rec[0].strip()),
                     "value": float(rec[1]), "source": "fred", "updated_at": now})
    return rows


def fetch_series(period=YF_PERIOD, today=None, out=print):
    """抓全部 ``SERIES``；單一序列失敗只印 WARN。回 ``(列, 失敗代號)``。"""
    import yfinance as yf

    today = today or datetime.datetime.now(TAIPEI).date()
    rows, failed = [], []
    for s in SERIES:
        try:
            if s.id.startswith("FRED:"):
                url = FRED_URL.format(id=s.id.split(":", 1)[1],
                                      start=today - datetime.timedelta(days=FRED_LOOKBACK_DAYS))
                got = parse_fred_csv(s.id, http_get(url).text)
            else:
                # auto_adjust=False：不做除息還原（還原價每次除息都改寫整段歷史）；分割調整 Yahoo 本來就做，
                # 靠每天整段重抓 YF_PERIOD 讓儀表讀到的窗口維持同一個尺度
                got = yf_rows(s.id, yf.Ticker(s.id).history(period=period, auto_adjust=False)["Close"])
            if not got:
                raise ValueError("回應沒有資料")
            rows.extend(got)
        except Exception as exc:  # noqa: BLE001 — 單一序列失敗不擋其他序列
            failed.append(s.id)
            out(f"**WARN macro_series {s.id}: {type(exc).__name__} {exc}")
    return rows, failed


def store_series(conn, rows):
    from market_data.writer import upsert

    return upsert(conn, models.MacroSeries.__table__, rows, ["series_id", "date"])


# ---------- rate_expectations ----------

def _num(value):
    if value in (None, ""):
        return None
    return float(value)


def outcome_of(ticker):
    """``KXFEDDECISION-26OCT-H25`` → ``hike_25``；不認得的後綴回 None。"""
    return OUTCOMES.get(ticker.rsplit("-", 1)[-1])


def meeting_date_of(close_time):
    """Kalshi ``close_time``（UTC ISO）→ 美東日期＝決議日（合約在決議前幾分鐘收盤）。"""
    ts = datetime.datetime.fromisoformat(close_time.replace("Z", "+00:00"))
    return ts.astimezone(NEW_YORK).date()


def prob_mid(bid, ask):
    """買賣價中點；缺一邊或 ask 為 0（沒有賣單）回 None——不拿 last_price 頂替。"""
    if bid is None or ask is None or ask <= 0:
        return None
    return round((bid + ask) / 2, 4)


def parse_kalshi(payload, snapshot_date):
    """Kalshi markets 回應 → ``rate_expectations`` 列。不認得的合約後綴略過。"""
    rows = []
    for m in payload.get("markets") or []:
        outcome = outcome_of(m.get("ticker", ""))
        if outcome is None or not m.get("close_time"):
            continue
        bid, ask = _num(m.get("yes_bid_dollars")), _num(m.get("yes_ask_dollars"))
        updated = m.get("updated_time")
        rows.append({
            "snapshot_date": snapshot_date,
            "meeting_date": meeting_date_of(m["close_time"]),
            "outcome": outcome,
            "prob_mid": prob_mid(bid, ask),
            "yes_bid": bid,
            "yes_ask": ask,
            "last_price": _num(m.get("last_price_dollars")),
            "volume": _num(m.get("volume_fp")),
            "open_interest": _num(m.get("open_interest_fp")),
            "source_updated_at": (datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
                                  if updated else None),
            "source": "kalshi",
        })
    return rows


def store_rates(conn, rows):
    from market_data.writer import upsert

    return upsert(conn, models.RateExpectation.__table__, rows, ["snapshot_date", "meeting_date", "outcome"])


# ---------- event_calendar ----------

_PANEL = re.compile(r"(\d{4}) FOMC Meetings")
_MEETING = re.compile(
    r'fomc-meeting__month[^>]*>\s*<strong>([A-Za-z/]+)</strong>.*?fomc-meeting__date[^>]*>([^<]*)<', re.S)


def parse_fed_calendar(html):
    """Fed 官網 FOMC 行事曆 → 例會決議日（會議最後一天）清單。

    跨月會議（``April/May`` + ``30-1``）取後一個月；非例會（unscheduled、notation vote）略過。"""
    dates = []
    panels = list(_PANEL.finditer(html))
    for i, panel in enumerate(panels):
        year = int(panel.group(1))
        chunk = html[panel.end():panels[i + 1].start() if i + 1 < len(panels) else len(html)]
        for month_text, day_text in _MEETING.findall(chunk):
            if re.search(r"unscheduled|notation", day_text, re.I):
                continue
            days = re.findall(r"\d+", day_text)
            month_name = month_text.split("/")[-1].strip().lower()
            month = _MONTHS.get(month_name) or next(
                (v for k, v in _MONTHS.items() if k.startswith(month_name[:3])), None)
            if not days or month is None:
                continue
            dates.append(datetime.date(year, month, int(days[-1])))
    return sorted(set(dates))


def fomc_events(fed_dates, kalshi_dates, now=None):
    """合併兩個來源的 FOMC 決議日；同月份兩邊一致＝confirmed，只有官網＝confirmed，
    只有 Kalshi＝estimated，同月份兩邊不一致以官網為準並在 source 註明。"""
    now = now or _now()
    by_month = {}
    for d in fed_dates:
        by_month[d.strftime("%Y-%m")] = {"date": d, "source": "fed", "status": "confirmed"}
    for d in kalshi_dates:
        key = d.strftime("%Y-%m")
        if key not in by_month:
            by_month[key] = {"date": d, "source": "kalshi", "status": "estimated"}
        elif by_month[key]["date"] == d:
            by_month[key]["source"] = "fed+kalshi"
        else:
            by_month[key]["source"] = "fed(kalshi不符)"
    return [{"event_type": "fomc", "symbol": "FED", "label": label, "event_date": v["date"],
             "status": v["status"], "title": "FOMC 利率決議",
             "time_note": "14:00 ET（台北隔日凌晨）", "source": v["source"], "updated_at": now}
            for label, v in sorted(by_month.items())]


def quarter_label(date):
    return f"{date.year}Q{(date.month - 1) // 3 + 1}"


def earnings_event(symbol, calendar, now=None):
    """yfinance ``Ticker.calendar`` → 一筆財報事件；沒有財報日回 None。

    給兩個日期（區間）時取前一個；一律 ``estimated``（yfinance 不給確認狀態）。"""
    dates = (calendar or {}).get("Earnings Date") or []
    dates = [d for d in dates if isinstance(d, datetime.date)]
    if not dates:
        return None
    date = min(dates)
    eps = (calendar or {}).get("Earnings Average")
    title = f"{symbol} 財報" + (f"（EPS 預估 {eps:.2f}）" if isinstance(eps, (int, float)) else "")
    return {"event_type": "earnings", "symbol": symbol, "label": quarter_label(date), "event_date": date,
            "status": "estimated", "title": title[:128],
            "time_note": "區間" if len(dates) > 1 else None, "source": "yfinance", "updated_at": now or _now()}


def store_events(conn, rows, today):
    """upsert 事件，回寫入列數。

    - 財報：同一 symbol 今天以後、但這次沒抓到的 label 刪掉（改期跨季時舊的那筆不留著當幽靈事件）；
      只動這次有抓到的 symbol，已經過去的事件不刪。
    - FOMC：不刪任何列（官網掛掉時只剩 Kalshi，那不是完整行事曆）；``estimated`` 不覆蓋已經是
      ``confirmed`` 的同一場會議——條件寫在 ON CONFLICT 的 WHERE 裡，兩個更新同時跑也不會降級。"""
    from sqlalchemy import or_, text
    from sqlalchemy.dialects.postgresql import insert

    from market_data.writer import dedupe

    if not rows:
        return 0
    keep = {}
    for r in rows:
        if r["event_type"] == "earnings":
            keep.setdefault(r["symbol"], []).append(r["label"])
    for symbol, labels in keep.items():
        conn.execute(text(
            "DELETE FROM market.event_calendar WHERE event_type = 'earnings' AND symbol = :s "
            "AND event_date >= :today AND NOT (label = ANY(:labels))"),
            {"s": symbol, "today": today, "labels": labels})
    table = models.EventCalendar.__table__
    pk = ["event_type", "symbol", "label"]
    rows = dedupe(rows, pk)
    stmt = insert(table).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=pk,
        set_={c.name: stmt.excluded[c.name] for c in table.columns if c.name not in pk},
        where=or_(table.c.status.is_distinct_from("confirmed"), stmt.excluded.status == "confirmed"))
    conn.execute(stmt)
    return len(rows)


# ---------- 入口 ----------

def update(engine, period=YF_PERIOD, out=print):
    """三段各自抓、各自一個交易寫入；任何一段失敗只印 ``**WARN``、不 raise。回各段寫入列數。"""
    today = datetime.datetime.now(TAIPEI).date()
    result = {"macro_series": 0, "rate_expectations": 0, "event_calendar": 0}

    try:
        rows, failed = fetch_series(period=period, today=today, out=out)
        with engine.begin() as conn:
            result["macro_series"] = store_series(conn, rows)
        latest = max((r["date"] for r in rows), default=None)
        out(f"macro_series {result['macro_series']:,} rows, latest {latest}"
            + (f"，失敗 {failed}" if failed else ""))
    except Exception as exc:  # noqa: BLE001
        out(f"**WARN macro_series: {type(exc).__name__} {exc}")

    kalshi_dates = []
    try:
        rates = parse_kalshi(http_get(KALSHI_URL).json(), today)
        if not rates:
            raise ValueError("Kalshi 回應沒有可辨識的 Fed 合約（端點可能改版）")
        kalshi_dates = sorted({r["meeting_date"] for r in rates})
        with engine.begin() as conn:
            result["rate_expectations"] = store_rates(conn, rates)
        out(f"rate_expectations {result['rate_expectations']:,} rows, snapshot {today}, "
            f"meetings {kalshi_dates[0]}~{kalshi_dates[-1]}")
    except Exception as exc:  # noqa: BLE001
        out(f"**WARN rate_expectations: {type(exc).__name__} {exc}")

    try:
        import yfinance as yf

        events = []
        try:
            fed_dates = parse_fed_calendar(http_get(FED_CALENDAR_URL, headers={"User-Agent": "Mozilla/5.0"}).text)
            if not fed_dates:
                raise ValueError("Fed 行事曆解析不到任何會議（頁面可能改版）")
        except Exception as exc:  # noqa: BLE001 — 官網掛掉時退回只用 Kalshi（標 estimated）
            fed_dates = []
            out(f"**WARN event_calendar fomc（Fed 官網）: {type(exc).__name__} {exc}")
        events.extend(fomc_events(fed_dates, kalshi_dates))
        for symbol in watchlist():
            try:
                ev = earnings_event(symbol, yf.Ticker(symbol).calendar)
                if ev:
                    events.append(ev)
            except Exception as exc:  # noqa: BLE001
                out(f"**WARN event_calendar earnings {symbol}: {type(exc).__name__} {exc}")
        with engine.begin() as conn:
            result["event_calendar"] = store_events(conn, events, today)
        upcoming = sorted(e["event_date"] for e in events if e["event_date"] >= today)
        out(f"event_calendar {result['event_calendar']:,} rows, next {upcoming[0] if upcoming else None}")
    except Exception as exc:  # noqa: BLE001
        out(f"**WARN event_calendar: {type(exc).__name__} {exc}")
    return result
