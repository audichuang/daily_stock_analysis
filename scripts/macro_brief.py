#!/usr/bin/env python3
"""大局儀表：從 ``market`` schema 印總經日線、Fed 利率預期路徑、台股位階與資金、未來 14 天重大事件。

給 skill ``tw-morning-call`` 的「大局」判讀用（``make morning`` 的一段）。只讀 DB、不連外；資料由
``market_data.cli daily``（或 ``cli macro``）寫入。**只列數字、不下結論**——哪個數字代表什麼
週期由判讀的人寫進 reason。

用法：
    uv run --env-file .env python scripts/macro_brief.py
    uv run --env-file .env python scripts/macro_brief.py --days 21   # 事件往後看 21 天
"""

import argparse
import datetime
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from market_data.macro import SERIES  # noqa: E402

TAIPEI = ZoneInfo("Asia/Taipei")
STALE_DAYS = 5          # 最新一列早於今天這麼多曆日就標「過期」
HORIZONS = (("1週", 5), ("1月", 21), ("3月", 63))
OUTCOME_SIDE = {"hike_gt25": "hike", "hike_25": "hike", "hold": "hold", "cut_25": "cut", "cut_gt25": "cut"}


def series_stats(points, kind):
    """``points``：依日期排序的 ``[(date, value)]``。回最新值、各期變化、距一年高、對 MA60／MA200。

    殖利率（``kind == 'yield'``）的變化用 bp（差值×100），其他用百分比；列數不足的欄位回 None。"""
    if not points:
        return None
    values = [v for _, v in points]
    last = values[-1]
    out = {"date": points[-1][0], "value": last, "changes": {}}
    for label, n in HORIZONS:
        if len(values) > n:
            base = values[-1 - n]
            out["changes"][label] = (last - base) * 100 if kind == "yield" else (last / base - 1 if base else None)
        else:
            out["changes"][label] = None
    window = values[-252:]
    hi = max(window)
    out["from_high"] = (last - hi) * 100 if kind == "yield" else (last / hi - 1 if hi else None)
    for n in (60, 200):
        out[f"ma{n}"] = (last > sum(values[-n:]) / n) if len(values) >= n else None
    return out


def rate_path(rows):
    """``[(meeting_date, outcome, prob_mid)]`` → 依會議排序的 ``{meeting, hike, hold, cut, missing}``。

    ``prob_mid`` 為 None（沒有買賣報價）的結果不計入加總，記在 ``missing``。"""
    by_meeting = {}
    for meeting, outcome, prob in rows:
        side = OUTCOME_SIDE.get(outcome)
        if side is None:
            continue
        rec = by_meeting.setdefault(meeting, {"meeting": meeting, "hike": 0.0, "hold": 0.0, "cut": 0.0,
                                              "missing": []})
        if prob is None:
            rec["missing"].append(outcome)
        else:
            rec[side] += float(prob)
    return [by_meeting[k] for k in sorted(by_meeting)]


def _fmt_change(value, kind):
    if value is None:
        return "—"
    return f"{value:+.0f}bp" if kind == "yield" else f"{value * 100:+.1f}%"


def _arrow(flag):
    return "—" if flag is None else ("上" if flag else "下")


def print_series(conn, today, out=print):
    from sqlalchemy import text

    rows = conn.execute(text(
        "SELECT series_id, date, value FROM market.macro_series WHERE date >= :since ORDER BY series_id, date"),
        {"since": today - datetime.timedelta(days=420)}).all()
    by_id = {}
    for sid, date, value in rows:
        if value is not None:
            by_id.setdefault(sid, []).append((date, float(value)))
    out("── 總經與國際盤（各序列最新一列，日期是資料自帶的交易日）──")
    out(f"{'名稱':<14}{'日期':<12}{'最新':>12}{'1週':>9}{'1月':>9}{'3月':>9}{'距1年高':>9}  MA60 MA200")
    missing = []
    for s in SERIES:
        st = series_stats(by_id.get(s.id, []), s.kind)
        if st is None:
            missing.append(s.id)
            continue
        stale = "  ⚠過期" if (today - st["date"]).days > STALE_DAYS else ""
        ch = st["changes"]
        out(f"{s.name:<14}{str(st['date']):<12}{st['value']:>12,.2f}"
            + "".join(f"{_fmt_change(ch[label], s.kind):>9}" for label, _ in HORIZONS)
            + f"{_fmt_change(st['from_high'], s.kind):>9}   {_arrow(st['ma60'])}    {_arrow(st['ma200'])}{stale}")
    if missing:
        out(f"⚠ DB 沒有這些序列：{missing}（跑 `python -m market_data.cli macro --period 2y` 回補）")


def print_rates(conn, out=print):
    from sqlalchemy import text

    snap = conn.execute(text("SELECT max(snapshot_date) FROM market.rate_expectations")).scalar()
    out("\n── Fed 利率預期（Kalshi 買賣價中點；各結果是獨立合約，加總不一定是 100%）──")
    if snap is None:
        out("沒有快照（跑 `python -m market_data.cli macro`）")
        return
    rows = conn.execute(text(
        "SELECT meeting_date, outcome, prob_mid FROM market.rate_expectations "
        "WHERE snapshot_date = :s AND meeting_date >= :s ORDER BY meeting_date"), {"s": snap}).all()
    prev = conn.execute(text(
        "SELECT max(snapshot_date) FROM market.rate_expectations WHERE snapshot_date <= :s - 7"),
        {"s": snap}).scalar()
    prev_path = {}
    if prev is not None:
        prev_rows = conn.execute(text(
            "SELECT meeting_date, outcome, prob_mid FROM market.rate_expectations WHERE snapshot_date = :s"),
            {"s": prev}).all()
        prev_path = {r["meeting"]: r for r in rate_path(prev_rows)}
    out(f"快照日 {snap}" + (f"（對照 {prev}）" if prev else "（還沒有一週前的快照可對照）"))
    out(f"{'會議':<12}{'升息':>8}{'不變':>8}{'降息':>8}  一週前升息")
    for rec in rate_path(rows)[:6]:
        before = prev_path.get(rec["meeting"])
        tail = f"{before['hike'] * 100:>7.0f}%" if before else "      —"
        miss = f"  （無報價：{','.join(rec['missing'])}）" if rec["missing"] else ""
        out(f"{str(rec['meeting']):<12}{rec['hike'] * 100:>7.0f}%{rec['hold'] * 100:>7.0f}%"
            f"{rec['cut'] * 100:>7.0f}%  {tail}{miss}")


def print_taiex(conn, out=print):
    from sqlalchemy import text

    rows = conn.execute(text(
        "SELECT date, close FROM market.market_index WHERE index_id = 'TAIEX' ORDER BY date DESC LIMIT 260")).all()
    out("\n── 台股位階與資金 ──")
    if len(rows) < 240:
        out("加權指數歷史不足 240 日，略過均線位階")
    else:
        closes = [float(c) for _, c in reversed(rows)]
        last = closes[-1]
        mas = {n: sum(closes[-n:]) / n for n in (20, 60, 120, 240)}
        hi = max(closes[-250:])
        out(f"加權 {rows[0][0]} {last:,.0f}，距一年高 {last / hi - 1:+.1%}；"
            + "、".join(f"MA{n} {v:,.0f}({'上' if last > v else '下'})" for n, v in mas.items()))
    flow = conn.execute(text("""
        WITH d AS (SELECT DISTINCT date FROM market.institutional ORDER BY date DESC LIMIT 20),
        f AS (SELECT i.date, sum(i.foreign_net * p.close) / 1e8 AS fv, sum(i.trust_net * p.close) / 1e8 AS tv
              FROM market.institutional i JOIN market.price p USING (stock_id, date)
              WHERE i.date IN (SELECT date FROM d) GROUP BY i.date)
        SELECT date, fv, tv FROM f ORDER BY date DESC""")).all()
    if flow:
        f5 = sum(float(r[1] or 0) for r in flow[:5])
        f20 = sum(float(r[1] or 0) for r in flow)
        t5 = sum(float(r[2] or 0) for r in flow[:5])
        out(f"外資 近5日 {f5:+,.0f} 億、近{len(flow)}日 {f20:+,.0f} 億；投信 近5日 {t5:+,.0f} 億"
            "（股數×當日收盤估算，只看方向與相對大小）")


def print_events(conn, today, days, out=print):
    from sqlalchemy import text

    rows = conn.execute(text(
        "SELECT event_date, event_type, symbol, title, status, time_note, source FROM market.event_calendar "
        "WHERE event_date BETWEEN :a AND :b ORDER BY event_date, event_type, symbol"),
        {"a": today, "b": today + datetime.timedelta(days=days)}).all()
    out(f"\n── 未來 {days} 天重大事件（日期為美東；財報日來自 yfinance、一律 estimated，可能差一天）──")
    if not rows:
        out("沒有事件（或還沒入庫）")
    for date, etype, symbol, title, status, note, source in rows:
        out(f"{date} {'FOMC' if etype == 'fomc' else symbol:<6} {title}"
            + (f"　{note}" if note else "") + f"　[{status}/{source}]")


def main(argv=None):
    p = argparse.ArgumentParser(description="大局儀表（總經、Fed 利率預期、台股位階與資金、重大事件）")
    p.add_argument("--days", type=int, default=14, help="事件往後看幾天")
    a = p.parse_args(argv)
    from market_data.db import get_engine

    today = datetime.datetime.now(TAIPEI).date()
    failed = 0
    with get_engine().connect() as conn:
        for section in (lambda: print_series(conn, today), lambda: print_rates(conn),
                        lambda: print_taiex(conn), lambda: print_events(conn, today, a.days)):
            try:
                section()
            except Exception as exc:  # noqa: BLE001 — 一段失敗（例如表還沒建）不擋其他段
                conn.rollback()
                failed += 1
                print(f"**WARN macro_brief: {type(exc).__name__} {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
