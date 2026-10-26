#!/usr/bin/env python3
"""期交所籌碼：外資台指期（大台 TXF）淨未平倉＋日變化、臺指選擇權 P/C 未平倉比。

給 `make morning` 的「期交所籌碼（前一交易日）」區塊與 skill `tw-morning-call` 用。
本腳本只抓不入庫：一次 POST 就拿得到一段日期，日變化直接從回應算，不碰 DB。期貨端點、抓取與
解析和每日入庫（`market_data/taifex.py` → ``market.taifex_fut_oi``，``TAIFEX_OI_PERSIST_ENABLED``）共用。

**新鮮度規則**：回應裡最新一列的日期必須等於預期場次（`market_data.health.expected_session`，
或 ``--as-of`` 覆寫），否則**不印數字、改印原因**——期交所查非交易日／尚未公布時照樣回
200（HTML ``alert("查無資料")``，或 P/C 只回表頭），不比對日期就會把舊數字當今天的印出來。
日變化只在前一列正好是前一個交易日（`health.session_before`）時才算；中間缺日或日曆不可用
時只列水位、註明原因，不拿跨多日的差當「日變化」。日曆不可用時一律不退回週一~五。

HTTP 走 `market_data.tw_official_http.post`（短 timeout、不重試、不暖 TWSE cookie），
錯誤頁判斷也用它的 `error_reason`（錯誤頁是 UTF-8 HTML）；判定可用之後才以 cp950 解碼
CSV（正常 CSV 是 MS950，卻標成 ``text/html``）。

``queryEndDate`` 一律填預期場次，不填今天或明天：迄日落在未來時期交所整筆回
``日期時間錯誤``，連前面有資料的日子也拿不到。

資料問題一律 exit 0、只印 ⚠ 行，讓 `make morning` 後面的待觸發計畫與候選照常跑；
程式 bug 照常拋例外（Makefile 以 ``-`` 前綴吞掉）。

``--json`` 改印一個 JSON 物件，欄位對應 `journal/README.md` 的盤前判讀選填欄位，可直接照抄：
``foreign_fut_oi``（整數，負＝淨空）、``foreign_fut_oi_chg``（整數）、``pc_oi_ratio``（**小數**，66.17%
→ 0.6617），另有 ``session``、``reasons``（只列為 null 的欄位與原因）、``notes``（結算週等 ⚠ 註記）。
不可用、或日變化不能算時該欄為 null，不要自己補數字。

用法：
    uv run python scripts/taifex_positions.py
    uv run python scripts/taifex_positions.py --as-of 2026-10-20
    uv run python scripts/taifex_positions.py --json
"""

import argparse
import datetime
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_data import health  # noqa: E402
from market_data import taifex  # noqa: E402
from market_data.tw_official_http import md  # noqa: E402

FUT_URL = taifex.FUT_URL
PC_URL = "https://www.taifex.com.tw/cht/3/pcRatioDown"
# 起日往前推的曆日數（與入庫共用）：P/C 端點一次最多查約一個月，14 天裝得下長假。
LOOKBACK_DAYS = taifex.LOOKBACK_DAYS

_FUT_ITEM = "外資台指期淨未平倉"
_PC_ITEM = "臺指選擇權 P/C"
_NOTE = "說明：只列數字、不給門檻——本 repo 沒有回測支持任何 P/C 或未平倉門檻，判讀寫進 reason，不改 regime 定義。"
_SETTLEMENT = "⚠ 跨月結算，未平倉變化含結算／轉倉效應"
_NO_CALENDAR_SETTLEMENT = "⚠ 交易日曆不可用，未檢查是否落在結算週"
_NO_CALENDAR = "交易日曆不可用，期交所區塊略過（不退回週一~五猜場次）"


_parse_date = taifex.parse_date
_reader = taifex.csv_reader


def parse_fut(text):
    """期貨 CSV → ``[(日期, 外資及陸資 臺股期貨 多空未平倉口數淨額)]``，依日期由舊到新。

    解析與入庫共用 `taifex.parse_fut_rows`（依欄名取值；表頭缺欄位時 raise ValueError）。"""
    return sorted((r["date"], r["net_oi"]) for r in taifex.parse_fut_rows(text) if r["identity"] == "foreign")


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


def change_basis(prev, session, is_session=None):
    """日變化能不能算：前一列正好是前一交易日才回 None（可算），否則回不列日變化的原因。"""
    if prev is None:
        return "回應裡沒有前一列"
    expected_prev = health.session_before(session, is_session=is_session)
    if expected_prev is None:
        return "交易日曆不可用，無法驗證前一列是否相鄰"
    if prev[0] != expected_prev:
        return f"前一列 {prev[0]} 非前一交易日 {expected_prev}，變化跨多日"
    return None


def settlement_session(year, month, is_session=None):
    """當月台指期／臺指選擇權結算日：第三個週三，遇休市順延到下一個交易日；日曆不可用回 None。"""
    first = datetime.date(year, month, 1)
    third_wed = first + datetime.timedelta(days=(2 - first.weekday()) % 7 + 14)
    return health.sessions_after(third_wed - datetime.timedelta(days=1), 1, is_session=is_session)


def near_settlement(day, is_session=None):
    """``day`` 是否落在當月結算日前後一個交易日內；日曆不可用回 None（未檢查）。"""
    settle = settlement_session(day.year, day.month, is_session=is_session)
    if settle is None:
        return None
    before = health.session_before(settle, is_session=is_session)
    after = health.sessions_after(settle, 1, is_session=is_session)
    if before is None or after is None:
        return None
    return before <= day <= after


_fetch = taifex.fetch_csv


def _fut_line(latest, prev, basis):
    level = f"{latest[1]:,} 口"
    if basis is not None:
        return f"外資台指期淨未平倉（大台 TXF，不含小台）：{level}（{md(latest[0])}；不列日變化：{basis}）"
    diff = latest[1] - prev[1]
    if diff == 0:
        direction = "持平"
    elif latest[1] < 0:
        direction = "空單減少" if diff > 0 else "空單增加"
    else:
        direction = "多單增加" if diff > 0 else "多單減少"
    return (f"外資台指期淨未平倉（大台 TXF，不含小台）：{level}"
            f"（{md(prev[0])} {prev[1]:,} → {md(latest[0])}，{diff:+,}，{direction}）")


def _pc_line(latest, prev, basis):
    head = f"臺指選擇權 P/C 未平倉比：{latest[1]:.2f}%"
    tail = f"；成交量 P/C {latest[2]:.2f}%"
    if basis is not None:
        return f"{head}（{md(latest[0])}；不列日變化：{basis}）{tail}"
    return f"{head}（{md(prev[0])} {prev[1]:.2f}%，{latest[1] - prev[1]:+.2f}pp）{tail}"


@dataclass(frozen=True)
class Item:
    """單一端點的結果：``reason`` 非 None 表示不可用（``latest``／``prev`` 為 None）；
    ``basis`` 非 None 表示只有水位、不列日變化（值是原因）。"""

    name: str
    latest: tuple | None = None
    prev: tuple | None = None
    basis: str | None = None
    reason: str | None = None


def _section(name, url, data, parser, session, is_session):
    """單一端點：抓取 → 解析 → 新鮮度 → 日變化可否計算，回 `Item`。"""
    text, reason = _fetch(url, data)
    if reason is None:
        try:
            rows = parser(text)
        except ValueError as error:
            reason = f"格式不符：{error}"
    if reason is None:
        picked, reason = pick(rows, session)
    if reason is not None:
        return Item(name, reason=reason)
    latest, prev = picked
    return Item(name, latest, prev, change_basis(prev, session, is_session))


def collect(session, is_session=None):
    """抓兩個端點，回 ``(期貨 Item, P/C Item, ⚠ 註記清單)``。"""
    start = session - datetime.timedelta(days=LOOKBACK_DAYS)
    dates = {"queryStartDate": start.strftime("%Y/%m/%d"), "queryEndDate": session.strftime("%Y/%m/%d")}
    fut = _section(_FUT_ITEM, FUT_URL, {**dates, "commodityId": "TXF"}, parse_fut, session, is_session)
    pc = _section(_PC_ITEM, PC_URL, dates, parse_pc, session, is_session)
    notes = []
    picked = [item for item in (fut, pc) if item.reason is None]
    if picked:
        days = {session} | {item.prev[0] for item in picked if item.prev is not None}
        flags = [near_settlement(d, is_session) for d in sorted(days)]
        if any(flags):
            notes.append(_SETTLEMENT)
        elif None in flags:
            notes.append(_NO_CALENDAR_SETTLEMENT)
    return fut, pc, notes


def _line(item, render):
    if item.reason is not None:
        return f"⚠ {item.name}：不可用（{item.reason}）"
    return render(item.latest, item.prev, item.basis)


def run(session, is_session=None, out=print):
    out(f"預期場次 {session}（只列期交所回應日期＝此場次的數字）")
    fut, pc, notes = collect(session, is_session)
    out(_line(fut, _fut_line))
    out(_line(pc, _pc_line))
    for note in notes:
        out(note)
    if fut.reason is None or pc.reason is None:
        out(_NOTE)


def journal_values(session, fut=None, pc=None, notes=(), reason=None):
    """``--json`` 的物件：欄位名與單位照 `journal/README.md`，不可用或不能算的欄位為 null 並在 ``reasons`` 寫原因。

    ``reason`` 非 None（例如日曆不可用、沒有場次）時三個欄位都是 null、原因都是它。"""
    values = {"session": session.isoformat() if session else None,
              "foreign_fut_oi": None, "foreign_fut_oi_chg": None, "pc_oi_ratio": None}
    reasons = {}
    if reason is not None:
        reasons = dict.fromkeys(("foreign_fut_oi", "foreign_fut_oi_chg", "pc_oi_ratio"), reason)
    else:
        if fut.reason is not None:
            reasons["foreign_fut_oi"] = reasons["foreign_fut_oi_chg"] = fut.reason
        else:
            values["foreign_fut_oi"] = fut.latest[1]
            if fut.basis is None:
                values["foreign_fut_oi_chg"] = fut.latest[1] - fut.prev[1]
            else:
                reasons["foreign_fut_oi_chg"] = fut.basis
        if pc.reason is not None:
            reasons["pc_oi_ratio"] = pc.reason
        else:
            values["pc_oi_ratio"] = round(pc.latest[1] / 100, 4)   # 66.17% → 0.6617
    return {**values, "reasons": reasons, "notes": list(notes)}


def main(argv=None, *, is_session=None, now=None):
    parser = argparse.ArgumentParser(
        description="期交所外資台指期淨未平倉（含日變化）與臺指選擇權 P/C 未平倉比；只列回應日期＝預期場次的數字")
    parser.add_argument("--as-of", type=datetime.date.fromisoformat, default=None,
                        help="覆寫預期場次（YYYY-MM-DD），給重現與測試用；預設取 market_data.health.expected_session")
    parser.add_argument("--json", action="store_true",
                        help="改印一個 JSON 物件（journal 的 foreign_fut_oi／foreign_fut_oi_chg／pc_oi_ratio，可直接照抄）")
    args = parser.parse_args(argv)
    session = args.as_of or health.expected_session(now=now, is_session=is_session)
    if args.json:
        if session is None:
            values = journal_values(None, reason=_NO_CALENDAR)
        else:
            values = journal_values(session, *collect(session, is_session))
        print(json.dumps(values, ensure_ascii=False))
        return 0
    if session is None:
        print(f"⚠ {_NO_CALENDAR}")
        return 0
    run(session, is_session=is_session)
    return 0


if __name__ == "__main__":
    sys.exit(main())
