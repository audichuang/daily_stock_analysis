"""月營收的法定公告申報期限（point-in-time 回測用的「最早可見日」下界）。

`market.monthly_revenue.announce_date` 是佔位值（營收月次月 10 日），不是實際公告日。
回測讀取端一律以 ``effective_announce_dates`` 取「佔位公告日」與「法定期限」較晚者，
再沿用各自的「公告日之後第一個交易日」語意；DB 既有列不改寫。

期限規則（取較晚者）：

1. 一般：營收月次月 10 日（證券交易法第 36 條第 1 項第 3 款）。
2. 2020-01 營收：主管機關因疫情全面展延至 2020-02-15（中央社 2020-02-03）。
3. 保險業及具保險子公司之公開發行公司：自 2026 年 2 月申報 1 月份營收起，期限放寬為
   次月 15 日（《公開發行公司財務報告及營運情形公告申報特殊適用範圍辦法》第 3 條修正；
   https://money.udn.com/money/story/5607/9162636 、
   https://uanalyze.com.tw/articles/9242343173 ）。
   適用名單會變動（例：玉山金要等合併三商壽後才適用），本模組不追蹤逐家名單，採**保守假設**：
   代號 28xx 全部（含純銀行、票券，對它們只是晚看 5 天，方向安全）加上報導點名但不在
   28xx 的 5880 合庫金、2207 和泰車、2905 三商（三商投控，持有三商美邦人壽）。其他具保險
   子公司者若上市，需補進 ``_INSURANCE_CLASS_EXTRA``。
   三商投控適用依據：https://www.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d69c37647f019c4b9838ce0016.pdf

期限末日遇週末、國定假日或颱風假等休市日時順延（行政程序法第 48 條第 4 項：期間末日為
休息日者以其次日為末日），本模組一律順延到**當日或之後第一個台股交易日**（XTAI 日曆加
``market_data.closures`` 的本機臨時休市清單，不連網偵測）。補班週六、證交所封關日這類
「機關上班但不開盤」的日子也會被順延，只會讓可見日更晚（保守方向）。日曆取不到或超出
exchange_calendars 範圍時只順延週六日並記 warning（週六日一定不是交易日，不會順延過頭；
國定假日則無從得知）。

讀取端：回測（``backtest_screen``、``measure_signal_forward``、``measure_revenue_momentum``）
一律套；指定歷史基準日的回顧讀取（``screen_tw --date``、``tw_stock_dossier`` 帶 ``as_of``、
媒體點名的播出日快照）也套。live（基準日就是最新資料日）不套：DB 裡有的列就是已公告，
套了反而把已公布的營收藏到期限之後；個股分析的營收動能（``load_tw_revenue_momentum``）錨定
官方最新月份，同屬 live，不套。
"""

import datetime
import logging

import pandas as pd

logger = logging.getLogger(__name__)

# 營收月 → 主管機關全面展延後的期限
MARKET_WIDE_EXTENSIONS = {pd.Timestamp("2020-01-01"): pd.Timestamp("2020-02-15")}

INSURANCE_RULE_FROM = pd.Timestamp("2026-01-01")   # 適用的第一個營收月
INSURANCE_DEADLINE_DAY = 15
DEFAULT_DEADLINE_DAY = 10
_INSURANCE_CLASS_PREFIX = "28"
_INSURANCE_CLASS_EXTRA = frozenset({"5880", "2207", "2905"})
# 有效公告日最多比 DB 的佔位 10 日晚幾個曆日（15 日期限＋春節連假順延約 9 天，留餘裕）；
# 讀取端用它放寬 SQL 的公告日下界，再以有效公告日在 Python 端精確篩。
MAX_DEADLINE_LAG_DAYS = 20


def _bare(stock_id) -> str:
    s = str(stock_id).strip().upper()
    for suf in (".TWO", ".TW"):
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def is_insurance_class(stock_id) -> bool:
    """保守口徑的「保險業／具保險子公司」：28xx 或明列的例外代號。"""
    s = _bare(stock_id)
    return s.startswith(_INSURANCE_CLASS_PREFIX) or s in _INSURANCE_CLASS_EXTRA


def _session_checker(is_session):
    if is_session is not None:
        return is_session
    from market_data import health   # 延遲 import：health 牽動 db／crawl，純計算時不必載入
    return health._xtai_session_checker(autodetect=False)


def _roll_weekend(day: pd.Timestamp) -> pd.Timestamp:
    return day + pd.Timedelta(days=(7 - day.weekday()) % 7 if day.weekday() >= 5 else 0)


def _roll_to_sessions(days, is_session=None) -> dict:
    """``{期限: 當日或之後第一個交易日}``；日曆不可用或超出範圍的日期只順延週六日。"""
    from market_data import health

    checker = _session_checker(is_session)
    out, fallback = {}, []
    for day in days:
        day = pd.Timestamp(day).normalize()
        rolled = None
        if checker is not None:
            try:
                rolled = day if checker(day.date()) else health.sessions_after(
                    day.date(), 1, is_session=checker)
            except Exception:  # noqa: BLE001 - 超出日曆範圍：退回只順延週六日
                rolled = None
        if rolled is None:
            fallback.append(day)
            rolled = _roll_weekend(day)
        out[day] = pd.Timestamp(rolled)
    if fallback:
        logger.warning("月營收期限順延：%d 個日期無法查交易日曆（如 %s），只順延週六日",
                       len(fallback), fallback[0].date())
    return out


def _statutory_deadline(stock_id, rm: pd.Timestamp) -> pd.Timestamp:
    nxt = rm + pd.DateOffset(months=1)
    day = (INSURANCE_DEADLINE_DAY
           if rm >= INSURANCE_RULE_FROM and is_insurance_class(stock_id)
           else DEFAULT_DEADLINE_DAY)
    deadline = nxt + pd.DateOffset(days=day - 1)
    ext = MARKET_WIDE_EXTENSIONS.get(rm)
    return max(deadline, ext) if ext is not None else deadline


def publication_deadline(stock_id, revenue_month, is_session=None) -> pd.Timestamp:
    """某檔某營收月的法定公告期限（含展延），遇休市日順延到下一個交易日。

    ``is_session``（``date -> bool``）預設取 XTAI 加本機臨時休市清單；測試可注入。"""
    rm = pd.Timestamp(revenue_month).to_period("M").to_timestamp()
    deadline = _statutory_deadline(stock_id, rm)
    return _roll_to_sessions([deadline], is_session)[deadline]


def publication_deadline_date(stock_id, year: int, month: int, is_session=None) -> datetime.date:
    return publication_deadline(stock_id, pd.Timestamp(year, month, 1), is_session).date()


def effective_announce_dates(stock_id: pd.Series, announce: pd.Series,
                             revenue_month: pd.Series = None, is_session=None) -> pd.Series:
    """有效公告日 = max(DB 公告日, 法定期限（休市順延後）)，逐列；dtype 與 ``announce`` 相同。

    ``revenue_month`` 缺席時由公告日推回「前一個月」——DB 公告日一律落在營收月的次月
    （佔位 10 日或展延後日期）；若推錯成更晚的月份，結果只會更晚（保守方向）。
    公告日為 NaT 的列維持 NaT。
    """
    ann = pd.to_datetime(announce)
    if revenue_month is None:
        rm = (ann.dt.to_period("M") - 1).dt.to_timestamp()
    else:
        rm = pd.to_datetime(revenue_month)
    # 向量化版的 publication_deadline（回測一次讀十幾萬列，逐列算要數秒）
    rm = rm.dt.to_period("M").dt.to_timestamp()
    sid = pd.Series(list(stock_id), index=ann.index)
    ins = sid.map(is_insurance_class) & (rm >= INSURANCE_RULE_FROM)
    days = pd.to_timedelta(ins.map({True: INSURANCE_DEADLINE_DAY - 1,
                                    False: DEFAULT_DEADLINE_DAY - 1}), unit="D")
    dl = rm + pd.DateOffset(months=1) + days
    ext = rm.map(MARKET_WIDE_EXTENSIONS)
    dl = pd.concat([dl, ext], axis=1).max(axis=1).where(rm.notna())
    # 順延只對不重複的期限算（一次回測只有幾百個），再對回各列
    dl = dl.map(_roll_to_sessions(dl.dropna().unique(), is_session)).astype(ann.dtype)
    return ann.where(ann.isna() | dl.isna() | (ann >= dl), dl)


def apply_revenue_deadline(df: pd.DataFrame, date_col: str = "date",
                           revenue_month_col: str = "revenue_month",
                           is_session=None) -> pd.DataFrame:
    """回傳副本，``date_col`` 換成有效公告日；有 ``revenue_month_col`` 就用它，否則由公告日推。"""
    out = df.copy()
    if not len(out):
        return out
    rm = out[revenue_month_col] if revenue_month_col in out else None
    out[date_col] = effective_announce_dates(out["stock_id"], out[date_col], rm, is_session)
    return out
