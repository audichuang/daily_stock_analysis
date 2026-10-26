#!/usr/bin/env python3
"""抓 TWSE 上市處置公告歷史（rwd punish，2013 起可查）到 ``data/`` 下的快取 CSV，並列出制度沿革。

研究用、**不入庫**（`market` schema 不建表）：live 的處置旗標仍由 `market_data.risk_flags` 每輪
即時抓；這份快取只給 `scripts/measure_signal_forward.py --disposal-cache` 回測「處置公告後延後
進場」用（`docs/research/2026-10-26-exp-disposal-delay.md`）。上櫃處置的歷史端點未核實，只做上市。

端點語意（2026-10-26 實測）：

- 查詢區間是**處置期間與區間重疊**，不是公布日落在區間內——2021 上下半年各 169／183 列、
  全年 336 列，重疊的 16 列都是 6 月公布、處置期跨到 7 月。所以分段抓之後要以
  (公布日期, 代號, 處置起迄, 處置措施) 去重。
- title 帶「(民國起 至 民國迄)」，必須等於送出的區間，否則拒收（端點會靜默退回別的區間）。
- 公布日期偶有前綴 ``*``（與 `risk_flags.parse_twse_punish` 同樣 ``lstrip("*")``）。

制度沿革只做描述：處置期間長度以 ``market.price`` 的交易日曆數（唯讀查詢），不從中文
「五個營業日」反推；撮合間隔才從處置內容抽「約每 N 分鐘撮合一次」。

用法：
    uv run --frozen python scripts/fetch_twse_disposal_history.py               # 抓 2013 至今
    uv run --frozen python scripts/fetch_twse_disposal_history.py --timeline    # 只印沿革（需 DATABASE_URL）
"""

import argparse
import datetime
import hashlib
import re
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from market_data.risk_flags import TWSE_PUNISH_URL, _columns, _period  # noqa: E402
from market_data.sources import _roc_slash_to_date  # noqa: E402

DEFAULT_CACHE = REPO / "data" / "twse_punish_history.csv"
FIRST_YEAR = 2013
_TITLE_RANGE_RE = re.compile(r"\(\s*(\d+/\d+/\d+)\s*至\s*(\d+/\d+/\d+)\s*\)")
_CN_DIGITS = {"一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_MATCH_RE = re.compile(r"約每\s*([0-9０-９一二兩三四五六七八九十]+)\s*分鐘撮合一次")
_STATED_DAYS_RE = re.compile(r"[﹝〔（(]\s*([0-9０-９一二兩三四五六七八九十]+)\s*個營業日")
CACHE_COLUMNS = ["announce", "stock_id", "name", "count", "condition", "start", "end",
                 "measure", "match_minutes", "stated_days"]


def cn_number(text):
    """「五」「十」「十二」「二十」「20」「２０」→ int；認不得回 None。"""
    s = str(text).strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if s.isdigit():
        return int(s)
    if not s or any(ch not in _CN_DIGITS and ch != "十" for ch in s):
        return None
    if "十" not in s:
        return _CN_DIGITS[s] if len(s) == 1 else None
    tens, _, ones = s.partition("十")
    return (_CN_DIGITS.get(tens, 0) if tens else 1) * 10 + (_CN_DIGITS.get(ones, 0) if ones else 0)


def _first_number(regex, text):
    m = regex.search(str(text))
    return cn_number(m.group(1)) if m else None


def parse_punish_payload(payload, start, end):
    """一段查詢的回應 → DataFrame（``CACHE_COLUMNS``）。區間對不上或缺欄一律 raise。"""
    if payload.get("stat") != "OK":
        raise ValueError(f"stat={payload.get('stat')!r}")
    m = _TITLE_RANGE_RE.search(str(payload.get("title", "")))
    if not m or (_roc_slash_to_date(m.group(1)), _roc_slash_to_date(m.group(2))) != (start, end):
        raise ValueError(f"回應區間不是送出的 {start}~{end}：{payload.get('title')!r}")
    cols = _columns(payload.get("fields"), ["公布日期", "證券代號", "證券名稱", "累計", "處置條件",
                                            "處置起迄時間", "處置措施", "處置內容"])
    rows = []
    for row in payload.get("data") or []:
        p_start, p_end = _period(row[cols["處置起迄時間"]])
        content = row[cols["處置內容"]]
        rows.append({
            "announce": _roc_slash_to_date(str(row[cols["公布日期"]]).strip().lstrip("*")),
            "stock_id": str(row[cols["證券代號"]]).strip(),
            "name": str(row[cols["證券名稱"]]).strip(),
            "count": row[cols["累計"]],
            "condition": str(row[cols["處置條件"]]).strip(),
            "start": p_start, "end": p_end,
            "measure": str(row[cols["處置措施"]]).strip(),
            "match_minutes": _first_number(_MATCH_RE, content),
            "stated_days": _first_number(_STATED_DAYS_RE, content),
        })
    return pd.DataFrame(rows, columns=CACHE_COLUMNS)


def dedupe(frame):
    """分段查詢的重疊列（處置期跨段）去重；排序固定，讓快取的雜湊可重現。"""
    key = ["announce", "stock_id", "start", "end", "measure"]
    return (frame.drop_duplicates(subset=key)
            .sort_values(["announce", "stock_id", "start", "measure"]).reset_index(drop=True))


def fetch_all(first_year, last_day, pause=3.0):
    from market_data.crawler import requests_get  # 入庫爬蟲用的那條（暖 cookie、重試），批次抓歷史適用

    parts = []
    for year in range(first_year, last_day.year + 1):
        start = datetime.date(year, 1, 1)
        end = min(datetime.date(year, 12, 31), last_day)
        resp = requests_get(TWSE_PUNISH_URL, params={
            "response": "json", "startDate": f"{start:%Y%m%d}", "endDate": f"{end:%Y%m%d}"})
        if resp is None or resp.status_code != 200:
            raise RuntimeError(f"{year} 抓取失敗：{getattr(resp, 'status_code', None)}")
        part = parse_punish_payload(resp.json(), start, end)
        print(f"{year}: {len(part)} 列", flush=True)
        parts.append(part)
        time.sleep(pause)
    return dedupe(pd.concat(parts, ignore_index=True))


def load_cache(path=DEFAULT_CACHE):
    """讀快取；日期欄轉成 Timestamp。供 `measure_signal_forward --disposal-cache` 使用。"""
    df = pd.read_csv(path, dtype={"stock_id": str, "condition": str, "measure": str})
    for col in ("announce", "start", "end"):
        df[col] = pd.to_datetime(df[col])
    return df


def session_lengths(disp, calendar):
    """每筆處置期間 [start, end] 含幾個交易日（``calendar`` 為交易日 DatetimeIndex）。"""
    cal = pd.DatetimeIndex(calendar).sort_values()
    lo = cal.searchsorted(pd.DatetimeIndex(disp["start"]), side="left")
    hi = cal.searchsorted(pd.DatetimeIndex(disp["end"]), side="right")
    return pd.Series(hi - lo, index=disp.index)


def timeline(disp, calendar):
    """依公布年份（2026 再拆 08-10 前後）列處置期長度與撮合間隔的分布。

    只算 ``calendar`` 涵蓋的列；第一次／第二次處置分開（`measure` 欄）。"""
    cal = pd.DatetimeIndex(calendar)
    d = disp[(disp["start"] >= cal.min()) & (disp["end"] <= cal.max())].copy()
    d["sessions"] = session_lengths(d, cal)
    d["period"] = d["announce"].dt.year.astype(str)
    cut = pd.Timestamp("2026-08-10")
    d.loc[d["start"] >= cut, "period"] = "2026-08-10 起"
    d.loc[(d["announce"].dt.year == 2026) & (d["start"] < cut), "period"] = "2026（08-10 前）"
    d["kind"] = d["measure"].where(d["measure"].isin(["第一次處置", "第二次處置"]), "其他")

    def mode(s):
        s = s.dropna()
        return s.mode().iloc[0] if len(s) else None

    out = d.groupby(["period", "kind"]).agg(
        列數=("stock_id", "size"),
        交易日中位=("sessions", "median"), 交易日眾數=("sessions", mode),
        交易日最小=("sessions", "min"), 交易日最大=("sessions", "max"),
        撮合分鐘眾數=("match_minutes", mode))
    return out


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    p = argparse.ArgumentParser(description="抓 TWSE 處置公告歷史到快取 CSV（研究用、不入庫）")
    p.add_argument("--out", default=str(DEFAULT_CACHE))
    p.add_argument("--first-year", type=int, default=FIRST_YEAR)
    p.add_argument("--last-day", default=None, help="YYYY-MM-DD（預設今天）")
    p.add_argument("--pause", type=float, default=3.0, help="每段查詢之間的秒數")
    p.add_argument("--timeline", action="store_true",
                   help="不抓，讀既有快取並以 market.price 交易日曆列制度沿革（唯讀查詢）")
    a = p.parse_args(argv)
    out = Path(a.out)

    if a.timeline:
        from sqlalchemy import text

        from market_data.db import get_engine
        with get_engine().connect() as c:
            cal = pd.read_sql(text("select distinct date from market.price order by date"), c,
                              parse_dates=["date"])["date"]
        disp = load_cache(out)
        print(f"快取 {out}：{len(disp)} 列，公布日 {disp['announce'].min():%Y-%m-%d} ~ "
              f"{disp['announce'].max():%Y-%m-%d}，sha256 {file_sha256(out)[:16]}")
        print(f"交易日曆 {cal.min():%Y-%m-%d} ~ {cal.max():%Y-%m-%d}（之外的處置列不計）")
        with pd.option_context("display.width", 200, "display.max_rows", 200):
            print(timeline(disp, pd.DatetimeIndex(cal)).to_string())
        return 0

    last_day = datetime.date.fromisoformat(a.last_day) if a.last_day else datetime.date.today()
    disp = fetch_all(a.first_year, last_day, pause=a.pause)
    out.parent.mkdir(parents=True, exist_ok=True)
    disp.to_csv(out, index=False)
    print(f"共 {len(disp)} 列（去重後）→ {out}  sha256 {file_sha256(out)[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
