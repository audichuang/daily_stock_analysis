"""月營收的法定公告申報期限（point-in-time 回測用的「最早可見日」下界）。

`market.monthly_revenue.announce_date` 是佔位值（營收月次月 10 日），不是實際公告日。
歷史讀取端一律以 ``effective_announce_dates`` 取「佔位公告日」與「法定期限」較晚者，
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
   28xx 的 5880 合庫金、2207 和泰車、2905 三商投控；後續名單異動須同步維護。
   三商投控適用依據：https://www.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d69c37647f019c4b9838ce0016.pdf
4. 期限落在休市日，沿用 XTAI 與本機臨時休市清單順延至下一交易日。
"""

import datetime

import pandas as pd

from market_data.health import _xtai_session_checker, sessions_after

# 營收月 → 主管機關全面展延後的期限
MARKET_WIDE_EXTENSIONS = {pd.Timestamp("2020-01-01"): pd.Timestamp("2020-02-15")}

INSURANCE_RULE_FROM = pd.Timestamp("2026-01-01")   # 適用的第一個營收月
INSURANCE_DEADLINE_DAY = 15
DEFAULT_DEADLINE_DAY = 10
_INSURANCE_CLASS_PREFIX = "28"
_INSURANCE_CLASS_EXTRA = frozenset({"5880", "2207", "2905"})


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


def publication_deadline(stock_id, revenue_month) -> pd.Timestamp:
    """某檔某營收月的法定公告期限（含展延與休市順延），只讀日曆、不連網。"""
    rm = pd.Timestamp(revenue_month).to_period("M").to_timestamp()
    return _publication_deadline(rm, is_insurance_class(stock_id), _xtai_session_checker(autodetect=False))


def _publication_deadline(rm, insurance_class, is_session) -> pd.Timestamp:
    """純量與批次共用唯一規則；批次按月份與類別去重，避免逐列查日曆。"""
    if pd.isna(rm):
        return pd.NaT
    nxt = rm + pd.DateOffset(months=1)
    day = (INSURANCE_DEADLINE_DAY
           if rm >= INSURANCE_RULE_FROM and insurance_class
           else DEFAULT_DEADLINE_DAY)
    deadline = nxt + pd.DateOffset(days=day - 1)
    ext = MARKET_WIDE_EXTENSIONS.get(rm)
    deadline = max(deadline, ext) if ext is not None else deadline
    # 從前一天起找下一場，期限本身是交易日時維持當日；不可再多延一場。
    rolled = (sessions_after(deadline.date() - datetime.timedelta(days=1), 1, is_session=is_session)
              if is_session is not None else None)
    if rolled is None:
        raise ValueError(f"無法確認月營收期限的台股交易日：{deadline.date()}")
    return pd.Timestamp(rolled)


def publication_deadline_date(stock_id, year: int, month: int) -> datetime.date:
    return publication_deadline(stock_id, pd.Timestamp(year, month, 1)).date()


def effective_announce_dates(stock_id: pd.Series, announce: pd.Series,
                             revenue_month: pd.Series = None) -> pd.Series:
    """有效公告日 = max(DB 公告日, 法定期限)，逐列；dtype 與 ``announce`` 相同。

    ``revenue_month`` 缺席時由公告日推回「前一個月」——DB 公告日一律落在營收月的次月
    （佔位 10 日或展延後日期）；若推錯成更晚的月份，結果只會更晚（保守方向）。
    公告日為 NaT 但有營收月時採法定期限；兩者皆缺才維持 NaT，避免 NULL 繞過歷史上界。
    """
    ann = pd.to_datetime(announce)
    if revenue_month is None:
        rm = (ann.dt.to_period("M") - 1).dt.to_timestamp()
    else:
        rm = pd.to_datetime(revenue_month)
    rm = rm.dt.to_period("M").dt.to_timestamp()
    sid = pd.Series(list(stock_id), index=ann.index)
    keys = list(zip(rm, sid.map(is_insurance_class)))
    checker = _xtai_session_checker(autodetect=False)
    deadlines = {key: _publication_deadline(*key, checker) for key in set(keys)}
    dl = pd.Series([deadlines[key] for key in keys], index=ann.index, dtype=ann.dtype)
    return ann.where(dl.isna() | (ann >= dl), dl)


def apply_revenue_deadline(df: pd.DataFrame, date_col: str = "date",
                           revenue_month_col: str = "revenue_month") -> pd.DataFrame:
    """回傳副本，``date_col`` 換成有效公告日；有 ``revenue_month_col`` 就用它，否則由公告日推。"""
    out = df.copy()
    if not len(out):
        return out
    rm = out[revenue_month_col] if revenue_month_col in out else None
    out[date_col] = effective_announce_dates(out["stock_id"], out[date_col], rm)
    return out


def revenue_as_of(df: pd.DataFrame, as_of, date_col: str = "announce_date",
                  stale_days: int = None) -> pd.DataFrame:
    """以共用有效公告日篩選歷史可見列；當天公告保守視為盤後，保鮮期按曆日計。"""
    out = apply_revenue_deadline(df, date_col=date_col)
    if out.empty:
        return out
    cutoff = pd.Timestamp(as_of).normalize()
    visible = out[date_col] < cutoff
    if stale_days is not None:
        visible &= out[date_col] >= cutoff - pd.Timedelta(days=stale_days)
    return out.loc[visible].copy()
