"""總經日線、Fed 利率預期、重大事件行事曆：抓取、解析、入庫 ``market`` schema 三張表。

- ``macro_series``：yfinance 日線（美債殖利率、美元、匯率、原油、黃金、費半、韓股…）與 FRED
  的 2／10 年期美債。**代號清單只有一份，就是這裡的 ``SERIES``**；``scripts/overnight.py`` 取
  ``overnight=True`` 的那幾列，不另外維護清單。
- ``rate_expectations``：Kalshi ``KXFEDDECISION`` 各會議各結果的買賣價中點，每天一份快照。
- ``event_calendar``：FOMC 決議日（Fed 官網為主、Kalshi 補官網還沒列的會議）、watchlist 的
  財報日（yfinance，一律標 ``estimated``——它不給確認狀態，實測 MSFT 給的日期比公司公告晚一天）、
  美國經濟數據（CPI／非農＋失業率／零售／PCE／初領，FRED 行事曆為主、BEA 與 Census 備援）、
  ISM 製造業（規則日 ``estimated``）、央行理監事會（repo 內常數表）。經濟數據公布後由 ALFRED 的
  首發 vintage 寫入實際值與前值（first-write-wins）。**不寫「高於／低於預期」：沒有 PIT 共識。**

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
CHICAGO = ZoneInfo("America/Chicago")  # FRED 行事曆的時間是美中，不是美東
UTC = datetime.timezone.utc

# id：yfinance 代號或 FRED:<代號>；kind：yield 的變化用 bp 表示；overnight：給 scripts/overnight.py 用；
# group：overnight 的市場分組（us/kr/cont），其餘為 macro；why：overnight 印出的理由；
# freq：daily／weekly——非 daily 的序列不進儀表的日線表（1週／1月／3月是列數 5／21／63）
Series = namedtuple("Series", "id name group kind overnight why freq", defaults=("daily",))
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
    Series("FRED:ICSA", "初領失業金", "macro", "index", False,
           "就業唯一週頻序列；FRED 值會被修訂，首發看事件段", "weekly"),
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
# ALFRED 免金鑰 CSV：參數是 vintage_date（單數）。複數 vintage_dates、或 fredgraph 加 vintage_date 都會被
# 靜默忽略、回傳最新值（2026-10-27 實測），不要用。表頭後綴 ``<代號>_YYYYMMDD`` 就是實際生效的 vintage。
ALFRED_URL = "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={id}&cosd={start}&vintage_date={vintage}"
FRED_CALENDAR_URL = "https://fred.stlouisfed.org/releases/calendar?rid={rid}&y={year}"
BEA_ICS_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
CENSUS_CALENDAR_URL = "https://www.census.gov/economic-indicators/calendar-listview.html"
FIRST_RELEASE_PER_RUN = 60   # 每次最多補幾筆首發值（首跑回補歷史用；失敗的下次再試）
FIRST_RELEASE_LOOKBACK = 12  # fetch_first_release 往前抓幾週（足夠含前值）
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


def parse_alfred_csv(code, text):
    """ALFRED alfredgraph.csv（單一 vintage）→ ``(vintage_date, [(obs_date, value)])``；缺值略過。

    表頭必須是 ``observation_date,<代號>_YYYYMMDD``，後綴就是 vintage；沒有後綴（例如參數被靜默忽略、
    回的是最新值）一律 raise——拿到修訂後的值當首發值比沒有值更糟。不放寬 ``parse_fred_csv``
    的表頭檢查，那條是改版偵測。"""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    m = re.fullmatch(rf"{re.escape(code)}_(\d{{8}})", header[1].strip()) if header and len(header) >= 2 else None
    if not m:
        raise ValueError(f"ALFRED {code} 表頭不符 {header!r}（vintage 參數可能被忽略或端點改版）")
    vintage = datetime.datetime.strptime(m.group(1), "%Y%m%d").date()
    points = []
    for rec in reader:
        if len(rec) < 2 or rec[1].strip() in ("", "."):
            continue
        points.append((datetime.date.fromisoformat(rec[0].strip()), float(rec[1])))
    return vintage, points


def fetch_first_release(code, release_date):
    """某筆經濟數據的首發值：ALFRED 以公布日（美東日期）當 vintage，取最後一個 observation。

    回 ``{obs_date, actual, prior, vintage}``；``prior`` 是**那個 vintage 裡的前值**（已含當次修訂）。
    ALFRED 可能比公布時間晚幾小時才收進來：公布日 vintage 的最後一筆日期若沒有比前一天 vintage 更新，
    代表新值還沒進來，回 None（呼叫端留 NULL、之後再補）——vintage 釘在公布日，晚抓也不會拿到修訂值。"""
    start = release_date - datetime.timedelta(weeks=FIRST_RELEASE_LOOKBACK)

    def pull(vintage):
        url = ALFRED_URL.format(id=code, start=start, vintage=vintage)
        return parse_alfred_csv(code, http_get(url).text)

    got_vintage, points = pull(release_date)
    if not points:
        return None
    _, before = pull(release_date - datetime.timedelta(days=1))
    if before and before[-1][0] >= points[-1][0]:
        return None
    return {"obs_date": points[-1][0], "actual": points[-1][1],
            "prior": points[-2][1] if len(points) > 1 else None, "vintage": got_vintage}


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

# 經濟數據：event_type → (FRED release id, 名稱, ALFRED 序列, 預設公布時間 ET)。FRED 行事曆的欄位叫
# release id；ISM 不在 FRED 上。UNRATE 與 NFP 同一天公布，由 nfp 衍生另一列 ``unrate``。
RELEASES = {
    "cpi": (10, "美國 CPI", "FRED:CPIAUCSL"),
    "nfp": (50, "美國非農就業(NFP)", "FRED:PAYEMS"),
    "retail": (9, "美國零售銷售(advance)", "FRED:RSAFS"),
    "pce": (54, "美國 PCE（個人所得與支出）", "FRED:PCEPI"),
    "claims": (180, "美國初領失業金", "FRED:ICSA"),
}
UNRATE = ("美國失業率", "FRED:UNRATE")
DEFAULT_RELEASE_TIME = datetime.time(8, 30)  # 以上五類都是 08:30 ET；ISM 是 10:00 ET
ISM_TIME = datetime.time(10, 0)

# 央行理監事會：repo 內維護的常數表（每年 4 場，台北日期）。**日期只放官方已確認的**：
# - 已開過的會：cbc.gov.tw/tw/lp-357-1.html 的「N 年 M 月 D 日央行理監事會後記者會」標題；
# - 未來場次：央行新聞稿「115年中央銀行理監事聯席會議預定日期」（114-12-18 發布，
#   cbc.gov.tw/tw/cp-302-189514-82841-1.html，列 115 年 3/19、6/18、9/17、12/17）。
# 116 年尚無公告，**不得推算**——待補：116 年全年（央行約在前一年 12 月公告後再加）。
# 公布時間（會後記者會）沒有核實，released_at 用 16:00 台北當佔位，time_note 已標待確認。
CBC_BOARD_MEETINGS = (
    datetime.date(2025, 9, 18),   # 114-09-18
    datetime.date(2025, 12, 18),  # 114-12-18
    datetime.date(2026, 3, 19),   # 115-03-19
    datetime.date(2026, 6, 18),   # 115-06-18
    datetime.date(2026, 9, 17),   # 115-09-17
    datetime.date(2026, 12, 17),  # 115-12-17（預定日期公告；改期要依央行新公告更新）
)
CBC_TIME_NOTE = "會後記者會（台北下午，時間待確認）"

_FRED_DAY = re.compile(r'font-weight:\s*bold;">[A-Za-z]+day\s+([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})</span>')
_FRED_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*([ap]m)", re.I)
_CENSUS_RETAIL = re.compile(
    r'href="/retail">Advance Monthly Sales for Retail and Food Services</a></td>\s*'
    r'<td[^>]*sorttable_customkey="(\d{12})"', re.S)
_ICS_FOLD = re.compile(r"\r?\n[ \t]")


def parse_fred_release_calendar(html, tz=CHICAGO, default_time=DEFAULT_RELEASE_TIME, default_tz=NEW_YORK):
    """FRED ``releases/calendar`` 頁 → 排序後的公布時間（aware datetime）。

    頁面上的時間是**美中時間**（America/Chicago）：``7:30 am`` ＝ 08:30 ET ＝ 13:30Z（CPI 實測對過 BEA
    ICS 的 UTC 時間）。某天沒有時間欄就套 ``default_time``（``default_tz`` 時區）。"""
    heads = list(_FRED_DAY.finditer(html))
    out = []
    for i, h in enumerate(heads):
        month = _MONTHS.get(h.group(1).lower())
        if month is None:
            continue
        day = datetime.date(int(h.group(3)), month, int(h.group(2)))
        chunk = html[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(html)]
        t = _FRED_TIME.search(chunk)
        if t:
            hour = int(t.group(1)) % 12 + (12 if t.group(3).lower() == "pm" else 0)
            out.append(datetime.datetime.combine(day, datetime.time(hour, int(t.group(2))), tzinfo=tz))
        else:
            out.append(datetime.datetime.combine(day, default_time, tzinfo=default_tz))
    return sorted(set(out))


def parse_bea_ics(text, summary_prefix="Personal Income and Outlays"):
    """BEA 行事曆 ICS → ``[(摘要, UTC datetime)]``，只留摘要以 ``summary_prefix`` 開頭的事件。
    DTSTART 是 UTC（結尾 Z）；沒有 Z 的略過，不猜時區。"""
    out = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", _ICS_FOLD.sub("", text), re.S):
        summary = re.search(r"^SUMMARY:(.*)$", block, re.M)
        start = re.search(r"^DTSTART[^:\n]*:(\d{8}T\d{6})Z\s*$", block, re.M)
        if not summary or not start:
            continue
        name = summary.group(1).strip().replace("\\,", ",")
        if name.startswith(summary_prefix):
            out.append((name, datetime.datetime.strptime(start.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=UTC)))
    return sorted(out, key=lambda x: x[1])


def parse_census_retail(html):
    """Census 經濟指標行事曆 → 零售 advance 的公布時間（美東 aware datetime）。
    ``sorttable_customkey="202701150830"`` 是美東的 YYYYMMDDHHMM。"""
    return sorted({datetime.datetime.strptime(k, "%Y%m%d%H%M").replace(tzinfo=NEW_YORK)
                   for k in _CENSUS_RETAIL.findall(html)})


def _release_row(event_type, title, series_id, released_at, source, now, status="confirmed", note=None):
    et = released_at.astimezone(NEW_YORK)
    return {"event_type": event_type, "symbol": "US", "label": et.date().isoformat(), "event_date": et.date(),
            "status": status, "title": title[:128], "time_note": note or f"{et:%H:%M} ET", "source": source,
            "updated_at": now, "released_at": released_at, "series_id": series_id}


def release_events(kind, released_ats, source, now=None):
    """某類經濟數據的公布時間 → ``event_calendar`` 列（``symbol='US'``）。

    ``label`` 用公布日（美東）ISO——FRED 行事曆不給參考月份，且日期當 label 讓三個來源對同一場公布
    寫到同一列。``nfp`` 同時衍生同日的 ``unrate`` 列。"""
    now = now or _now()
    _, title, series_id = RELEASES[kind]
    rows = [_release_row(kind, title, series_id, t, source, now) for t in released_ats]
    if kind == "nfp":
        rows += [_release_row("unrate", UNRATE[0], UNRATE[1], t, source, now) for t in released_ats]
    return rows


def ism_events(year, now=None):
    """ISM 製造業 PMI：每月第一個美國營業日 10:00 ET 的**規則推估**（``estimated``／``rule``）。
    ismworld.org 行事曆是 reCAPTCHA、不可機器讀取，所以只能用規則；營業日用美國聯邦假日日曆算。"""
    import pandas as pd
    from pandas.tseries.holiday import USFederalHolidayCalendar
    from pandas.tseries.offsets import CustomBusinessDay

    now = now or _now()
    bday = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    rows = []
    for month in range(1, 13):
        first = bday.rollforward(pd.Timestamp(year, month, 1)).date()
        released = datetime.datetime.combine(first, ISM_TIME, tzinfo=NEW_YORK)
        row = _release_row("ism", "ISM 製造業 PMI（規則推估日）", None, released, "rule", now, status="estimated",
                           note="10:00 ET（規則推估：每月第一個營業日）")
        rows.append(row)
    return rows


def cbc_events(now=None, meetings=None):
    """央行理監事會常數表 → ``event_calendar`` 列（``symbol='TW'``，``confirmed``／``cbc``）。"""
    now = now or _now()
    rows = []
    for d in meetings if meetings is not None else CBC_BOARD_MEETINGS:
        released = datetime.datetime.combine(d, datetime.time(16, 0), tzinfo=TAIPEI)
        rows.append({"event_type": "cbc", "symbol": "TW", "label": d.isoformat(), "event_date": d,
                     "status": "confirmed", "title": "央行理監事會", "time_note": CBC_TIME_NOTE,
                     "source": "cbc", "updated_at": now, "released_at": released, "series_id": None})
    return rows


def collect_release_events(today, now=None, out=print):
    """FRED 行事曆（主）＋ BEA／Census（備援）＋ ISM 規則＋央行表 → 事件列。各來源單獨 try，只印 WARN。

    備援只在 FRED 沒有給出「今天以後的下一筆」時才補（FRED 只有當年資料，12 月下旬會變空），
    而且只補晚於 FRED 最後一筆的日期。"""
    now = now or _now()
    rows, fred_ok = [], {}
    for kind, (rid, _title, _series) in RELEASES.items():
        try:
            times = parse_fred_release_calendar(http_get(FRED_CALENDAR_URL.format(rid=rid, year=today.year)).text)
            if not times:
                raise ValueError("FRED 行事曆解析不到任何公布日（頁面可能改版）")
            fred_ok[kind] = times
            rows.extend(release_events(kind, times, "fred", now))
        except Exception as exc:  # noqa: BLE001
            out(f"**WARN event_calendar {kind}（FRED 行事曆）: {type(exc).__name__} {exc}")

    def needs_backup(kind):
        times = fred_ok.get(kind)
        return not times or max(t.astimezone(NEW_YORK).date() for t in times) < today

    def newer(kind, times):
        last = max((t for t in fred_ok.get(kind, [])), default=None)
        return [t for t in times if t.astimezone(NEW_YORK).date() >= today and (last is None or t > last)]

    if needs_backup("pce"):
        try:
            times = [t for _, t in parse_bea_ics(http_get(BEA_ICS_URL).text)]
            rows.extend(release_events("pce", newer("pce", times), "bea", now))
        except Exception as exc:  # noqa: BLE001
            out(f"**WARN event_calendar pce（BEA 備援）: {type(exc).__name__} {exc}")
    if needs_backup("retail"):
        try:
            times = parse_census_retail(http_get(CENSUS_CALENDAR_URL).text)
            rows.extend(release_events("retail", newer("retail", times), "census", now))
        except Exception as exc:  # noqa: BLE001
            out(f"**WARN event_calendar retail（Census 備援）: {type(exc).__name__} {exc}")
    for year in (today.year, today.year + 1):
        rows.extend(ism_events(year, now))
    rows.extend(cbc_events(now))
    return rows


def fill_first_releases(engine, now=None, out=print, fetch=None):
    """公布時間已過、有 ``series_id``、實際值還是 NULL 的列：向 ALFRED 取首發值寫回。

    first-write-wins：UPDATE 帶 ``actual_value IS NULL``，已有值就不改。ALFRED 還沒收進來的列留 NULL，
    下次再補；單筆失敗只印 WARN。每次最多 ``FIRST_RELEASE_PER_RUN`` 筆（新的優先）。回寫入筆數。"""
    from sqlalchemy import text

    now = now or _now()
    fetch = fetch or fetch_first_release
    with engine.begin() as conn:
        pending = conn.execute(text(
            "SELECT event_type, symbol, label, released_at, series_id FROM market.event_calendar "
            "WHERE released_at <= :now AND series_id IS NOT NULL AND actual_value IS NULL "
            "ORDER BY released_at DESC LIMIT :n"), {"now": now, "n": FIRST_RELEASE_PER_RUN}).all()
    done = []
    for etype, symbol, label, released_at, series_id in pending:
        try:
            got = fetch(series_id.split(":", 1)[1], released_at.astimezone(NEW_YORK).date())
        except Exception as exc:  # noqa: BLE001
            out(f"**WARN event_calendar 首發值 {etype} {label}: {type(exc).__name__} {exc}")
            continue
        if got:
            done.append((etype, symbol, label, got))
    if done:
        with engine.begin() as conn:
            for etype, symbol, label, got in done:
                conn.execute(text(
                    "UPDATE market.event_calendar SET actual_value = :a, prior_value = :p, observation_date = :o, "
                    "actual_vintage = :v, actual_source = 'alfred' "
                    "WHERE event_type = :t AND symbol = :s AND label = :l AND actual_value IS NULL"),
                    {"a": got["actual"], "p": got["prior"], "o": got["obs_date"], "v": got["vintage"],
                     "t": etype, "s": symbol, "l": label})
    return len(done)


# 首發值欄位只由 ``fill_first_releases`` 寫（first-write-wins）；行事曆每天重抓，upsert 不能把它們蓋回 NULL
_ACTUAL_COLS = ("observation_date", "actual_value", "prior_value", "actual_vintage", "actual_source")
_OPTIONAL_COLS = ("released_at", "series_id") + _ACTUAL_COLS
# 公布日期會改、且 FRED 是該類型的權威來源：只有這幾類做「同年改期刪舊 label」
_FRED_TYPES = ("cpi", "nfp", "unrate", "retail", "pce", "claims")


def store_events(conn, rows, today):
    """upsert 事件，回寫入列數。

    - 財報：同一 symbol 今天以後、但這次沒抓到的 label 刪掉（改期跨季時舊的那筆不留著當幽靈事件）；
      只動這次有抓到的 symbol，已經過去的事件不刪。
    - FOMC、ISM、央行：不刪任何列（官網掛掉時只剩 Kalshi，那不是完整行事曆）；``estimated`` 不覆蓋
      已經是 ``confirmed`` 的同一場——條件寫在 ON CONFLICT 的 WHERE 裡，兩個更新同時跑也不會降級。
    - 經濟數據（``_FRED_TYPES``）：只有某 ``(event_type, 年)`` 這次由 FRED 行事曆抓成功時，才刪掉
      該類型、該年度、今天以後、這次沒抓到的 label（改期）；FRED 掛掉或只剩備援時什麼都不刪。
    - 首發值欄位（``_ACTUAL_COLS``）不在 upsert 的更新欄位內，每天重抓行事曆不會洗掉它們。"""
    from sqlalchemy import or_, text
    from sqlalchemy.dialects.postgresql import insert

    from market_data.writer import dedupe

    if not rows:
        return 0
    rows = [{**{c: None for c in _OPTIONAL_COLS}, **r} for r in rows]
    keep = {}
    for r in rows:
        if r["event_type"] == "earnings":
            keep.setdefault(r["symbol"], []).append(r["label"])
    for symbol, labels in keep.items():
        conn.execute(text(
            "DELETE FROM market.event_calendar WHERE event_type = 'earnings' AND symbol = :s "
            "AND event_date >= :today AND NOT (label = ANY(:labels))"),
            {"s": symbol, "today": today, "labels": labels})
    fred = {}
    for r in rows:
        if r["event_type"] in _FRED_TYPES and r["source"] == "fred":
            fred.setdefault((r["event_type"], r["event_date"].year), []).append(r["label"])
    for (etype, year), labels in fred.items():
        conn.execute(text(
            "DELETE FROM market.event_calendar WHERE event_type = :t AND symbol = 'US' "
            "AND event_date >= :today AND event_date >= :a AND event_date < :b AND NOT (label = ANY(:labels))"),
            {"t": etype, "today": today, "a": datetime.date(year, 1, 1), "b": datetime.date(year + 1, 1, 1),
             "labels": labels})
    table = models.EventCalendar.__table__
    pk = ["event_type", "symbol", "label"]
    rows = dedupe(rows, pk)
    stmt = insert(table).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=pk,
        set_={c.name: stmt.excluded[c.name] for c in table.columns if c.name not in pk + list(_ACTUAL_COLS)},
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
        events.extend(collect_release_events(today, out=out))
        with engine.begin() as conn:
            result["event_calendar"] = store_events(conn, events, today)
        upcoming = sorted(e["event_date"] for e in events if e["event_date"] >= today)
        out(f"event_calendar {result['event_calendar']:,} rows, next {upcoming[0] if upcoming else None}")
        try:
            out(f"event_calendar 首發值補 {fill_first_releases(engine, out=out)} 筆")
        except Exception as exc:  # noqa: BLE001 — 補不到留 NULL，之後再補
            out(f"**WARN event_calendar 首發值: {type(exc).__name__} {exc}")
    except Exception as exc:  # noqa: BLE001
        out(f"**WARN event_calendar: {type(exc).__name__} {exc}")
    return result
