"""事件日曆：報告當下即時抓「未來 N 個交易日」內的法說會與除權息預告，只抓不入庫。

三個來源都是滾動的「當前快照」，存歷史對「未來 N 日有什麼事」沒有幫助，所以不建表；也因此
**只能接在 DB 最新且等於預期場次的基準日上**（由呼叫端判斷），把今天的快照接到過去的基準日
是錯的，不只是沒用。窗口（`EventWindow`：起訖、``prev`` 前一交易日、``n`` 個交易日）由呼叫端用
`market_data.health.sessions_after`／`session_before` 算好傳入。

來源與新鮮度規則：

- 法說會（MOPS ``ajax_t100sb02_1``，走 mopsov 舊站；新站只是轉址過去）：上市 ``sii``、
  上櫃 ``otc`` 各打一次、``month=""`` 一次拿整年（月份篩的是區間**迄日**，按月抓會漏跨月的
  區間）；窗口跨年時加抓下一年。**表上沒有任何資料日期，新鮮度無法自證**——命中仍然照列，唯一
  理由是「凍結的表只會漏列新申報，不會捏造事件」；狀態記成 ``proven=False``（可用但未證明新鮮），
  **不算查過**：`checked_markets` 不收它，所以逐檔「沒有命中」永遠不會因為 MOPS 而寫成「查過、沒有」。
  窗口起日那一年 0 列不可能是真的，當成失敗；跨年補抓的下一年 0 列可能是
  真的還沒人申報，不算失敗。
- 除權息預告（上市 openapi ``TWT48U_ALL``、上櫃 openapi ``tpex_exright_prepost``）：內容沒有
  出表日期，只能看 HTTP ``Last-Modified``——換成台北日期須 ≥ ``prev_session``（TWT48U 約每天
  05:28 更新、TPEx 約 18:00），缺標頭或更舊就整個來源拒收。兩個端點各自判斷。兩份都是滾動
  視窗、含已過去的日期，只留落在窗口內的列。
- 月營收：沒有端點，依證券交易法第 36 條第 1 項第 3 款「每月十日以前」推算；條文沒有遇假日
  順延的規定，所以不自行順延。這是全市場一致的期限，不逐檔標。

HTTP 一律走 `market_data.tw_official_http`（短 timeout、不重試）；四個來源彼此不依賴，`upcoming`
以 ``run_sources(parallel=True)`` 同時抓（MOPS 整年表單次 2~20 秒，依序跑會疊加），狀態順序仍固定。
民國日期只用既有的 `sources._roc_slash_to_date` 與 `etl._roc_yyyymmdd`。
"""

import datetime
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from io import StringIO
from zoneinfo import ZoneInfo

import pandas as pd

from market_data import tw_official_http as http
from market_data.etl import _roc_yyyymmdd
from market_data.sources import _roc_slash_to_date
from market_data.tw_official_http import FormatChanged, Step, md, run_sources

MOPS_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"
TWT48U_URL = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"
TPEX_EXRIGHT_URL = "https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost"

_TAIPEI = ZoneInfo("Asia/Taipei")
# 台股代號：4~6 位數字加至多一個大寫字母。正則同一行要寫到 TW，tests/test_tw_code_pattern_contract.py 才掃得到它
_CODE_RE = re.compile(r"^\d{4,6}[A-Z]?$")  # 去掉 .TW／.TWO 後綴的台股代號
# 分類只分強弱兩種訊號：受邀參加券商活動是論壇（弱）；其餘看得出是公司自辦的季度／財報
# 說明才算法說（強）；看不出來的一律歸論壇——寧可低估，不把路演當成財報法說。
_FORUM_RE = re.compile(r"受邀|邀請")
_EARNINGS_RE = re.compile(r"自辦|財務報告|業績展望|營運成果|財務暨營運|財務業務|財務與業務|季度"
                          r"|第\s*[一二三四1-4１-４]\s*季|[1-4]Q|Q[1-4]")
_INVISIBLE = dict.fromkeys(map(ord, "‎‏﻿"), None)

MOPS_NOTE = "MOPS 表上沒有資料日期，凍結只會漏列新申報、不會捏造事件；只列已申報者，未列不代表沒有"

CONFERENCE = "法說"
FORUM = "論壇"

# 來源名稱（也是報告與 JSON 的顯示字串）→ 所屬市場。逐檔 ``events`` 只有在該檔市場的
# 每個來源都可用時才算「查過」，見 `checked_markets`。
SRC_MOPS_SII = "法說會（上市 MOPS）"
SRC_MOPS_OTC = "法說會（上櫃 MOPS）"
SRC_TWT48U = "除權息預告（上市 TWT48U）"
SRC_TPEX_EX = "除權息預告（上櫃 TPEx）"
SOURCE_MARKET = {SRC_MOPS_SII: "twse", SRC_TWT48U: "twse", SRC_MOPS_OTC: "tpex", SRC_TPEX_EX: "tpex"}
# 來源 → 事件類別（逐檔 ``events_checked`` 的值，依此順序列出）
CAT_CONFERENCE = "法說會"
CAT_EX_RIGHTS = "除權息"
SOURCE_CATEGORY = {SRC_MOPS_SII: CAT_CONFERENCE, SRC_MOPS_OTC: CAT_CONFERENCE,
                   SRC_TWT48U: CAT_EX_RIGHTS, SRC_TPEX_EX: CAT_EX_RIGHTS}
_TWSE_EX_KIND = {"息": "除息", "權": "除權", "權息": "除權息"}
_TPEX_EX_KIND = {"除息": "除息", "除權": "除權", "除權息": "除權息"}


@dataclass(frozen=True)
class EventWindow:
    """事件窗口：基準日之後第 1～第 ``n`` 個交易日（``start``～``end``），``prev`` 為基準日前一交易日
    （除權息預告的 Last-Modified 新鮮度門檻）。"""

    start: datetime.date
    end: datetime.date
    prev: datetime.date
    n: int

    def overlaps(self, start, end):
        return start <= self.end and end >= self.start

    def contains(self, day):
        return self.start <= day <= self.end


@dataclass(frozen=True)
class Event:
    """單一事件。``start == end`` 為單日；``time`` 只有法說會有；``cash`` 只有除權息預告有
    （每股現金股利，尚未公告或 0 為 None）。``detail`` 是來源原文（MOPS 擇要），除權息為空字串。"""

    stock_id: str
    kind: str          # 法說／論壇／除息／除權／除權息
    start: datetime.date
    end: datetime.date
    detail: str
    source: str
    time: str = ""
    cash: float | None = None

    @property
    def span(self):
        return md(self.start) if self.start == self.end else f"{md(self.start)}~{md(self.end)}"

    def label(self):
        """報告事件日曆的一段，例如「法說 10/23 14:00（自辦）」「除息 10/26（現金 1.5 元）」。"""
        if self.kind == CONFERENCE:
            return f"法說 {self.span}" + (f" {self.time}" if self.time else "") + "（自辦）"
        if self.kind == FORUM:
            return f"法說 {self.span}（券商論壇或未明）"
        return f"{self.kind} {self.span}" + (f"（現金 {self.cash:g} 元）" if self.cash else "")

    def short_tag(self):
        """候選表標籤欄用的短標，例如「📅法說10/23」；論壇是弱訊號，回 None（不上標籤）。"""
        if self.kind == FORUM:
            return None
        return f"📅{self.kind}{md(self.start)}"

    def to_dict(self):
        return {"kind": self.kind, "date": self.start.isoformat(), "end": self.end.isoformat(),
                "time": self.time or None, "detail": self.detail or None, "cash": self.cash,
                "source": self.source}


def _clean(value):
    return " ".join(str(value).translate(_INVISIBLE).split())


# ---- 法說會（MOPS） -------------------------------------------------------------------

def parse_mops_conferences(html):
    """MOPS 法說會整年 HTML → `Event` 清單（未依窗口過濾）。``查無資料`` 回空清單。

    找不到 ``myTable``／缺欄位 → `FormatChanged`。"""
    if "myTable" not in html:
        if "查無資料" in html:
            return []
        raise FormatChanged("找不到 myTable（改版或封鎖頁？）")
    try:
        table = pd.read_html(StringIO(html), attrs={"id": "myTable"},
                             converters={0: str, 2: str})[0]
    except ValueError as error:
        raise FormatChanged(f"myTable 解析失敗：{error}") from error
    if isinstance(table.columns, pd.MultiIndex):
        table.columns = table.columns.get_level_values(0)
    table.columns = [_clean(c) for c in table.columns]
    wanted = ["公司代號", "召開法人說明會日期", "召開法人說明會時間", "法人說明會擇要訊息"]
    missing = [c for c in wanted if c not in table.columns]
    if missing:
        raise FormatChanged(f"缺欄位 {missing}（端點可能改版）")
    events, seen = [], set()
    for code, when, time, summary in table[wanted].itertuples(index=False):
        code, when, time, summary = _clean(code), _clean(when), _clean(time), _clean(summary)
        if not _CODE_RE.match(code):
            continue
        try:
            parts = [_roc_slash_to_date(p) for p in when.split("至")]
        except ValueError:
            continue
        start, end = min(parts), max(parts)
        key = (code, start, time)
        if key in seen:
            continue
        seen.add(key)
        if _FORUM_RE.search(summary) or not _EARNINGS_RE.search(summary):
            kind = FORUM
        else:
            kind = CONFERENCE
        events.append(Event(code, kind, start, end, summary[:80], "MOPS", time))
    return events


def _mops_year(typek, roc_year):
    resp, reason = http.post(MOPS_URL, data={
        "encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": typek,
        "year": roc_year, "month": "", "co_id": ""}, expect=None, verify=False)
    if reason:
        raise FormatChanged(reason)
    return parse_mops_conferences(resp.content.decode("utf-8", errors="replace"))


def fetch_mops_conferences(typek, window):
    """單一市場（``sii``／``otc``）落在 `EventWindow` 內的法說會。"""
    events = []
    for i, year in enumerate(sorted({window.start.year, window.end.year})):
        rows = _mops_year(typek, year - 1911)
        if i == 0 and not rows:
            raise FormatChanged(f"{year - 1911} 年整年 0 列，不可能是真的（改版或封鎖？）")
        events.extend(rows)
    # 跨年區間是否同時列在兩年的表裡未實測，保守再去重一次
    hits, seen = [], set()
    for event in events:
        key = (event.stock_id, event.start, event.time)
        if key in seen or not window.overlaps(event.start, event.end):
            continue
        seen.add(key)
        hits.append(event)
    return hits


# ---- 除權息預告 -------------------------------------------------------------------------

def last_modified_date(resp):
    """``Last-Modified`` → 台北日期；缺或解析不了回 None。"""
    raw = (resp.headers or {}).get("Last-Modified")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(_TAIPEI).date()
    except (TypeError, ValueError):
        return None


def _cash(value):
    try:
        amount = float(str(value).replace(",", ""))
    except ValueError:
        return None  # 例如「尚未公告」
    return amount if amount > 0 else None


def parse_ex_rights(rows, *, date_key, code_key, kind_key, kinds, source, window):
    """除權息預告列 → 窗口內的 `Event`。單列解析失敗就跳過，**全部列都失敗**才當改版。"""
    if not isinstance(rows, list):
        raise FormatChanged("回應不是陣列")
    events, parsed = [], 0
    for row in rows:
        try:
            day = _roc_yyyymmdd(row[date_key])
            code = str(row[code_key]).strip()
            kind = kinds[str(row[kind_key]).strip()]
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        parsed += 1
        if not _CODE_RE.match(code) or not window.contains(day):
            continue
        events.append(Event(code, kind, day, day, "", source, cash=_cash(row.get("CashDividend"))))
    if rows and not parsed:
        raise FormatChanged("每一列都解析失敗（欄位可能改版）")
    return events


def fetch_ex_rights(url, window, **parse_kwargs):
    resp, reason = http.get(url, expect="json")
    if reason:
        raise FormatChanged(reason)
    modified = last_modified_date(resp)
    if modified is None:
        raise FormatChanged("拒收：沒有 Last-Modified，無法證明新鮮")
    if modified < window.prev:
        raise FormatChanged(f"拒收：Last-Modified {md(modified)} 早於前一交易日 "
                            f"{md(window.prev)}，超過 1 個交易日未更新")
    return parse_ex_rights(resp.json(), window=window, **parse_kwargs), f"資料時間 {md(modified)}"


# ---- 月營收 -------------------------------------------------------------------------------

def revenue_deadlines(window):
    """窗口與某月 1~10 日（上月營收公告期）重疊時，回該月 10 日（法定期限）的清單。"""
    out = []
    year, month = window.start.year, window.start.month
    while (year, month) <= (window.end.year, window.end.month):
        deadline = datetime.date(year, month, 10)
        if window.overlaps(datetime.date(year, month, 1), deadline):
            out.append(deadline)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


# ---- 對外入口 -----------------------------------------------------------------------------

def upcoming(window):
    """抓 `EventWindow` 內的事件，回 ``({代號: [Event, ...]}, [SourceStatus, ...])``；**不往外拋** ``Exception``。

    ``ok=False`` 代表那個來源這一輪不可用（不是「沒有事件」）；MOPS 可用時 ``ok=True`` 但
    ``proven=False``（未證明新鮮、不算查過）。四個來源並行抓，狀態固定依 ``SOURCE_MARKET`` 的順序。"""
    steps = [
        Step(SRC_MOPS_SII, lambda done: (fetch_mops_conferences("sii", window), MOPS_NOTE),
             proven=False),
        Step(SRC_MOPS_OTC, lambda done: (fetch_mops_conferences("otc", window), MOPS_NOTE),
             proven=False),
        Step(SRC_TWT48U, lambda done: fetch_ex_rights(
            TWT48U_URL, window, date_key="Date", code_key="Code",
            kind_key="Exdividend", kinds=_TWSE_EX_KIND, source="TWT48U")),
        Step(SRC_TPEX_EX, lambda done: fetch_ex_rights(
            TPEX_EXRIGHT_URL, window,
            date_key="ExRrightsExDividendDate", code_key="SecuritiesCompanyCode",
            kind_key="ExRrightsExDividend", kinds=_TPEX_EX_KIND, source="TPEx")),
    ]
    results, statuses = run_sources(steps, parallel=True)
    by_stock = {}
    for _, found in results:
        for event in found:
            by_stock.setdefault(event.stock_id, []).append(event)
    for code in by_stock:
        by_stock[code].sort(key=lambda e: (e.start, e.time))
    return by_stock, statuses


def checked_markets(statuses):
    """該市場的每個來源都「可用且新鮮度已證明」的市場集合。

    只有這些市場的候選「沒有命中」才能寫成 ``[]``（查過沒有）；其餘一律是未經檢查。MOPS 法說會
    ``proven=False``，所以目前任何市場都進不來——``[]`` 要等到有能自證新鮮的法說來源才會出現；
    哪些類別查過見 `checked_categories`。來源失敗只代表那個來源這一輪不可用，**不是**「沒有事件」。"""
    return http.checked_markets(statuses, SOURCE_MARKET)


def checked_categories(statuses):
    """``{市場: [已證明查過的事件類別, ...]}``，類別依 ``SOURCE_CATEGORY`` 的順序。

    某市場某類別的每個來源都「可用且新鮮度已證明」才算查過。目前實務上只有「除權息」會出現。"""
    out = {market: [] for market in SOURCE_MARKET.values()}
    for category in dict.fromkeys(SOURCE_CATEGORY.values()):
        names = {n: m for n, m in SOURCE_MARKET.items() if SOURCE_CATEGORY[n] == category}
        for market in http.checked_markets(statuses, names):
            out[market].append(category)
    return out
