#!/usr/bin/env python3
"""回驗媒體點名：講者的看多／看空，以及排程 Claude 的 research／watch／avoid 判斷，之後到底有沒有跑贏 0050。

兩種事件，報酬口徑一致（唯讀 journal 與 Postgres `market` schema，不寫任何東西）：

- **verdict 事件**：`journal/media-picks-verdicts.jsonl` 每檔一行。進場 = `written_at`（台北日期）**之後第一個交易日的開盤**
  （判斷在晚上寫、隔天才能下單）。同一 (code, date) 補判多次只留最後一筆，免得重跑灌水 n。
- **call 事件**：`journal/media-picks.jsonl` 有代號且立場為 bullish／bearish／avoid 的點名。進場 = 播出日 `date`
  **之後第一個交易日的開盤**：節目可能在盤中播出，播出當天的開盤或收盤都不是播出當下能成交的價格，一律不用。
  同一 (講者，代號，播出日) 只算一次（沒有講者用節目當單位；多空互相矛盾的整組丟掉並計數）。代號覆核
  （`media-picks-review.jsonl`）沿用 `media_picks_summary._apply_reviews`：`correct` 改掛、`not_stock` 排除；`unclear` 也排除。

持有 h 個交易日（進場日算第 1 天，出場 = 進場後第 h-1 個交易日收盤，與 `verify_swing_decisions.window` 同義）；
前復權價；報酬走 `round_trip_return`（雙邊滑價、手續費、賣出證交稅；00 開頭按 ETF 稅率）；
超額 = 個股淨報酬 − 0050 同一段淨報酬（0050 也扣同一套成本）。**未走完視窗（右設限）、查不到價格、不在 market.price 的代號一律
排除並計數，絕不補值**（用最後收盤補會把還沒發生的事當成已實現）。

統計：均值超額的 95% CI 用 `shadow_buy_eval.cluster_bootstrap_ci`（以代號為單位重抽——同一檔被多位講者、多天點名的事件高度相關，
逐筆重抽會把 CI 抽得太窄）。**n < 20、CI 跨零、或進場日不足 5 個不同交易日一律標 inconclusive**（同日事件共享大盤波動，只以代號重抽的 CI 會過窄）。看空（bearish＋avoid）的「命中」是超額 < 0。
同一檔連續幾天被判斷的視窗互相重疊，所以有效樣本比 n 更少；CI 已用代號為 cluster，但仍要當作偏樂觀。

    uv run --env-file .env python scripts/verify_media_picks.py
    uv run --env-file .env python scripts/verify_media_picks.py --horizons 5,10 --json
    uv run --env-file .env python scripts/verify_media_picks.py --speaker-records   # 給 media_picks_judge 用的 JSON
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO, REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import media_picks_summary as mps  # noqa: E402
from shadow_buy_eval import (  # noqa: E402
    BENCHMARK, DEFAULT_NOTIONAL, _pct, cluster_bootstrap_ci, load_bars,
)
from src.utils.tw_trade_costs import (  # noqa: E402
    ETF_TRANSACTION_TAX_RATE, STOCK_TRANSACTION_TAX_RATE, round_trip_return,
)

JOURNAL_DIR = REPO / "journal"
HORIZONS = (5, 10, 20)
MIN_DATES = 5                   # 不同進場日少於這個數也標 inconclusive：同日事件共享大盤波動，只以代號重抽的 CI 會過窄
MIN_N = 20                      # 低於這個數量的結論一律標為 inconclusive
SPEAKER_HORIZON = 10            # 講者紀錄（餵給逐檔判斷）看的持有天數
BULL = ("bullish",)
BEAR = ("bearish", "avoid")
TAIPEI = "Asia/Taipei"
COLS = ["kind", "code", "anchor", "speaker", "show", "media_kind", "stance", "verdict", "h", "status", "ret",
        "bench", "excess", "entry_date"]
STATUSES = ("ok", "censored", "no_price", "unknown_code")


# ---- 讀 journal → 事件清單（純函式，不碰 DB）----

def _read_jsonl(path: Path) -> list:
    return mps._read_jsonl(path)


def _taipei_day(ts) -> pd.Timestamp | None:
    """帶時區的時戳 → 台北日期（無時區視為已是台北時間）；解析不了回 None。"""
    try:
        t = pd.Timestamp(ts)
    except (ValueError, TypeError):
        return None
    if pd.isna(t):
        return None
    t = t.tz_convert(TAIPEI) if t.tzinfo is not None else t
    return t.tz_localize(None).normalize()


def _voice(row: dict) -> str:
    return mps._voice(row)


def verdict_picks(rows: list) -> list:
    """verdict 列 → 事件骨架；同 (code, date) 補判多次只留最後一筆（檔案 append-only）。"""
    latest = {}
    for r in rows:
        if r.get("code") and r.get("verdict") in ("research", "watch", "avoid"):
            latest[(r["code"], r.get("date"))] = r
    out = []
    for r in latest.values():
        anchor = _taipei_day(r.get("written_at")) or _taipei_day(r.get("date"))
        if anchor is not None:
            out.append({"kind": "verdict", "code": r["code"], "anchor": anchor, "verdict": r["verdict"]})
    return out


def call_picks(rows: list, reviews: list) -> tuple[list, dict]:
    """media-picks 列 → call 事件骨架與排除計數。``rows`` 須已套用代號覆核。"""
    latest = {mps.review_key(v): v.get("verdict") for v in reviews}
    dropped = {"review_unclear": 0, "conflict": 0}
    groups: dict = {}
    for r in rows:
        if r.get("resolve") == "no_picks" or not r.get("stock_code") or r.get("stance") not in BULL + BEAR:
            continue
        if latest.get(mps.review_key(r)) == "unclear" and not r.get("corrected_from"):
            dropped["review_unclear"] += 1
            continue
        anchor = _taipei_day(r.get("date"))
        if anchor is None:
            continue
        groups.setdefault((_voice(r), r["stock_code"], anchor), []).append(r)
    out = []
    for (voice, code, anchor), rs in groups.items():
        if len({r["stance"] in BULL for r in rs}) > 1:   # 同人同日同檔又多又空：方向不明，整組丟
            dropped["conflict"] += 1
            continue
        r = rs[0]
        out.append({"kind": "call", "code": code, "anchor": anchor, "speaker": voice, "show": r.get("show"),
                    "media_kind": r.get("kind") or "tv", "stance": r["stance"]})
    return out, dropped


# ---- 價格 → 報酬（純函式，panels 由呼叫端提供）----

def _tax(stock_id: str) -> float:
    return ETF_TRANSACTION_TAX_RATE if stock_id.startswith("00") else STOCK_TRANSACTION_TAX_RATE


def build_events(picks: list, panels: dict, horizons=HORIZONS, *, fee_discount=1.0,
                 notional=DEFAULT_NOTIONAL) -> pd.DataFrame:
    """每個 pick × horizon 一列：status（ok／censored／no_price／unknown_code）、ret、bench、excess。

    ``panels``：``{"open", "close"}`` 兩個前復權面板（index=date、columns=stock_id，含 0050）。
    日曆用 0050 有收盤的日子。進場日 = 嚴格晚於 anchor 的第一個交易日。
    """
    op, cl = panels["open"], panels["close"]
    cal = cl[BENCHMARK].dropna().index if BENCHMARK in cl.columns else pd.DatetimeIndex([])
    rows = []
    for p in picks:
        code = p["code"]
        sid = code.split(".")[0] if code.endswith((".TW", ".TWO")) else None
        i0 = int(cal.searchsorted(p["anchor"], side="right"))   # side=right：anchor 當天（含）不算
        for h in horizons:
            base = {k: v for k, v in p.items()} | {"h": h, "ret": np.nan, "bench": np.nan, "excess": np.nan,
                                                   "entry_date": pd.NaT}
            if sid is None or sid not in cl.columns:
                rows.append(base | {"status": "unknown_code"})
                continue
            i1 = i0 + h - 1
            if i1 >= len(cal):                                    # 視窗還沒走完：右設限，不補值
                rows.append(base | {"status": "censored"})
                continue
            e_d, x_d = cal[i0], cal[i1]
            e, x = op.at[e_d, sid], cl.at[x_d, sid]
            be, bx = op.at[e_d, BENCHMARK], cl.at[x_d, BENCHMARK]
            if any(pd.isna(v) or v <= 0 for v in (e, be)) or any(pd.isna(v) for v in (x, bx)):
                rows.append(base | {"status": "no_price", "entry_date": e_d})
                continue
            kw = {"entry_notional": notional, "fee_discount": fee_discount}
            ret = round_trip_return(float(e), float(x), tax_rate=_tax(sid), **kw)
            bench = round_trip_return(float(be), float(bx), tax_rate=ETF_TRANSACTION_TAX_RATE, **kw)
            rows.append(base | {"status": "ok", "ret": ret, "bench": bench, "excess": ret - bench,
                                "entry_date": e_d})
    return pd.DataFrame(rows).reindex(columns=COLS)   # 欄位固定：只有一種事件時另一種的欄位也在


# ---- 統計 ----

def label(n: int, ci, min_n: int = MIN_N, dates: int | None = None) -> str:
    if n < min_n or ci is None or ci[0] <= 0 <= ci[1] or (dates is not None and dates < MIN_DATES):
        return "inconclusive"
    return "顯著為正" if ci[0] > 0 else "顯著為負"


def hit_mask(excess, side: str):
    """看多（及 verdict）命中 = 超額 > 0；看空命中 = 超額 < 0。"""
    e = np.asarray(excess, dtype=float)
    return e < 0 if side == "bear" else e > 0


def stats(df: pd.DataFrame, side: str = "bull", n_boot: int = 2000, seed: int = 42) -> dict:
    """``df`` 須是 status==ok 的列。回 n、檔數、均值／中位超額、命中率、CI、標籤。"""
    ex = df["excess"].to_numpy(dtype=float)
    n = len(ex)
    if not n:
        return {"n": 0, "codes": 0, "dates": 0, "mean": None, "median": None, "hit": None, "ci": None, "label": "inconclusive"}
    ci = cluster_bootstrap_ci(ex, df["code"].tolist(), n_boot, seed)
    dates = int(df["entry_date"].nunique()) if "entry_date" in df else None
    return {"n": n, "codes": int(df["code"].nunique()), "dates": dates, "mean": float(ex.mean()), "median": float(np.median(ex)),
            "hit": float(hit_mask(ex, side).mean()), "ci": list(ci) if ci else None, "label": label(n, ci, dates=dates)}


def spread_stats(a: pd.DataFrame, b: pd.DataFrame, n_boot: int = 2000, seed: int = 42) -> dict:
    """a 組均值超額 − b 組均值超額；CI 兩組各自以代號重抽。"""
    if not len(a) or not len(b):
        return {"n_a": len(a), "n_b": len(b), "diff": None, "ci": None, "label": "inconclusive"}
    ci = cluster_bootstrap_ci(a["excess"], a["code"].tolist(), n_boot, seed,
                              other=(b["excess"], b["code"].tolist()))
    return {"n_a": len(a), "n_b": len(b), "diff": float(a["excess"].mean() - b["excess"].mean()),
            "ci": list(ci) if ci else None, "label": label(min(len(a), len(b)), ci)}


def _ok(ev: pd.DataFrame, **filters) -> pd.DataFrame:
    m = ev["status"] == "ok"
    for k, v in filters.items():
        m &= ev[k].isin(v) if isinstance(v, (list, tuple, set)) else ev[k] == v
    return ev[m]


def speaker_records(events: pd.DataFrame, horizon: int = SPEAKER_HORIZON, min_n: int = MIN_N) -> dict:
    """{講者: {"bull": {...}, "bear": {...}}}，只看 ``horizon`` 的 call 事件（純函式）。

    每側：``n_calls``（所有點名，含尚未到期）、``n``（已到期且有價格）、``hit_rate``、``mean_excess``、
    ``enough``（n >= min_n）。看多命中 = 超額 > 0，看空（bearish＋avoid）命中 = 超額 < 0。
    """
    out: dict = {}
    if events is None or events.empty:
        return out
    ev = events[(events["kind"] == "call") & (events["h"] == horizon)]
    for (speaker, side), g in ev.assign(side=np.where(ev["stance"].isin(BULL), "bull", "bear")).groupby(
            ["speaker", "side"]):
        done = g[g["status"] == "ok"]
        rec = {"n_calls": int(len(g)), "n": int(len(done)), "hit_rate": None, "mean_excess": None,
               "enough": bool(len(done) >= min_n)}
        if len(done):
            rec["hit_rate"] = float(hit_mask(done["excess"], side).mean())
            rec["mean_excess"] = float(done["excess"].mean())
        out.setdefault(speaker, {})[side] = rec
    return out


# ---- 報告 ----

def _ci_txt(ci):
    return f"[{_pct(ci[0])}, {_pct(ci[1])}]" if ci else "—"


def _row(name, s):
    if not s["n"]:
        return f"| {name} | 0 | — | — | — | — | inconclusive（n<{MIN_N}） |"
    note = f"（n<{MIN_N}）" if s["n"] < MIN_N else (
        f"（進場日僅 {s['dates']} 天<{MIN_DATES}）" if s.get("dates") is not None and s["dates"] < MIN_DATES else "")
    days = f"、{s['dates']} 日" if s.get("dates") is not None else ""
    return (f"| {name} | {s['n']}（{s['codes']} 檔{days}） | {_pct(s['mean'])} | {_pct(s['median'])} | "
            f"{s['hit'] * 100:.0f}% | {_ci_txt(s['ci'])} | {s['label']}{note} |")


HEAD = ("| 組別 | n | 均值超額 | 中位 | 命中率 | 95% CI（以代號重抽） | 結論 |\n"
        "| --- | --- | --- | --- | --- | --- | --- |")


def analyse(ev: pd.DataFrame, horizons, n_boot=2000, seed=42, speaker_horizon=SPEAKER_HORIZON, top=30) -> dict:
    """事件表 → 結構化結果（markdown 與 --json 共用）。"""
    res = {"horizons": list(horizons), "excluded": {}, "verdict": {}, "spread": {}, "calls": {}, "speakers": {}}
    for kind in ("verdict", "call"):
        for h in horizons:
            sub = ev[(ev["kind"] == kind) & (ev["h"] == h)] if len(ev) else ev
            res["excluded"][f"{kind}@{h}"] = {s: int((sub["status"] == s).sum()) if len(sub) else 0
                                              for s in STATUSES}
    for h in horizons:
        res["verdict"][h] = {v: stats(_ok(ev, kind="verdict", h=h, verdict=v), "bull", n_boot, seed)
                             for v in ("research", "watch", "avoid")} if len(ev) else {}
        res["spread"][h] = (spread_stats(_ok(ev, kind="verdict", h=h, verdict="research"),
                                         _ok(ev, kind="verdict", h=h, verdict="avoid"), n_boot, seed)
                            if len(ev) else {})
        calls = {}
        for side, stances in (("bull", BULL), ("bear", BEAR)):
            base = _ok(ev, kind="call", h=h, stance=list(stances)) if len(ev) else ev
            calls[side] = {"all": stats(base, side, n_boot, seed)}
            for mk in sorted(base["media_kind"].unique()) if len(base) else []:
                calls[side][f"kind:{mk}"] = stats(base[base["media_kind"] == mk], side, n_boot, seed)
        res["calls"][h] = calls
    sp_h = speaker_horizon if speaker_horizon in horizons else horizons[0]
    res["speaker_horizon"] = sp_h
    if len(ev):
        for side, stances in (("bull", BULL), ("bear", BEAR)):
            base = _ok(ev, kind="call", h=sp_h, stance=list(stances))
            rows = {sp: stats(g, side, n_boot, seed) for sp, g in base.groupby("speaker")}
            order = sorted(rows, key=lambda k: (-rows[k]["n"], k))[:top]
            res["speakers"][side] = {k: rows[k] for k in order}
    return res


def render(res: dict, meta: dict) -> str:
    out = ["# 媒體點名回驗", "",
           f"- journal：{meta['verdicts']} 筆 verdict、{meta['calls']} 個去重後的講者點名事件"
           f"（原始看多／看空點名 {meta['raw_calls']} 列）",
           f"- 口徑：進場 = 嚴格晚於 written_at／播出日的第一個交易日開盤；持有 h 個交易日（進場日算第 1 天）；"
           f"前復權價、雙邊成本；超額 = 個股 − 0050（同成本）。命中：看多／verdict 超額 > 0，看空超額 < 0。",
           f"- **結論一律 inconclusive** 當 n < {MIN_N} 或 95% CI 跨零；CI 以代號為單位重抽，同檔重疊視窗仍使有效樣本偏少。",
           f"- 排除（不補值）：{meta['dropped']}", ""]
    out += ["## 排除筆數（依 事件類型@持有天數）", "",
            "| 事件@h | ok | censored（視窗未走完） | no_price | unknown_code |", "| --- | --- | --- | --- | --- |"]
    for k, c in res["excluded"].items():
        out.append(f"| {k} | {c['ok']} | {c['censored']} | {c['no_price']} | {c['unknown_code']} |")
    for h in res["horizons"]:
        out += ["", f"## 持有 {h} 個交易日", "", "### 排程 Claude 的判斷（verdict）", "", HEAD]
        for v, s in res["verdict"][h].items():
            out.append(_row(v, s))
        sp = res["spread"][h]
        if sp:
            out += ["", f"research − avoid 均值超額差：n={sp['n_a']}／{sp['n_b']}，"
                        f"{_pct(sp['diff']) if sp['diff'] is not None else '—'}，CI {_ci_txt(sp['ci'])}，"
                        f"**{sp['label']}**" + (f"（任一組 n<{MIN_N}）" if min(sp["n_a"], sp["n_b"]) < MIN_N else "")]
        for side, title in (("bull", "講者看多（bullish）"), ("bear", "講者看空／避開（bearish＋avoid，命中 = 超額 < 0）")):
            out += ["", f"### {title}", "", HEAD]
            for name, s in res["calls"].get(h, {}).get(side, {}).items():
                out.append(_row(name, s))
    sp_h = res["speaker_horizon"]
    for side, title in (("bull", "看多"), ("bear", "看空／避開")):
        rows = res["speakers"].get(side) or {}
        out += ["", f"## 依講者：{title}（持有 {sp_h} 個交易日，依 n 取前幾名）", "", HEAD]
        out += [_row(k, s) for k, s in rows.items()] or ["| （無已到期的事件） | 0 | — | — | — | — | inconclusive |"]
    return "\n".join(out) + "\n"


# ---- 載入與主程式 ----

def collect(journal_dir: Path):
    """讀 journal → (verdict 骨架, call 骨架, 計數)。"""
    media = _read_jsonl(journal_dir / "media-picks.jsonl")
    reviews = _read_jsonl(journal_dir / "media-picks-review.jsonl")
    fixed = mps._apply_reviews(media, reviews, mps.STOCK_INDEX)
    calls, dropped = call_picks(fixed, reviews)
    verdicts = verdict_picks(_read_jsonl(journal_dir / "media-picks-verdicts.jsonl"))
    raw_calls = sum(1 for r in fixed if r.get("stock_code") and r.get("stance") in BULL + BEAR)
    return verdicts, calls, {"raw_calls": raw_calls, "dropped": dropped}


def load_panels(picks: list):
    ids = sorted({p["code"].split(".")[0] for p in picks if p["code"].endswith((".TW", ".TWO"))} | {BENCHMARK})
    start = (min(p["anchor"] for p in picks) - pd.Timedelta(days=10)).date()
    raw = load_bars(get_engine(), ids, start, dt.date.today())
    adj = raw["adj"]
    return {"open": raw["open"] * adj, "close": raw["close"] * adj}


def get_engine():
    from market_data.db import get_engine as _ge
    return _ge()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--journal-dir", type=Path, default=JOURNAL_DIR, help="journal 目錄（預設 repo 的 journal/）")
    ap.add_argument("--horizons", default=",".join(map(str, HORIZONS)), help="持有交易日數，逗號分隔")
    ap.add_argument("--fee-discount", type=float, default=1.0, help="手續費折扣（1.0＝牌價）")
    ap.add_argument("--bootstrap", type=int, default=2000, help="bootstrap 次數")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, help="另存報告（markdown；加 --json 則存 JSON）")
    ap.add_argument("--json", action="store_true", help="輸出機器可讀 JSON，不印 markdown")
    ap.add_argument("--speaker-records", action="store_true",
                    help=f"只印 speaker_records（持有 {SPEAKER_HORIZON} 日）的 JSON，給 media_picks_judge 用")
    args = ap.parse_args(argv)
    horizons = tuple(sorted({int(x) for x in args.horizons.split(",") if x.strip()}))
    if not horizons or horizons[0] < 1:
        ap.error("--horizons 要是正整數")

    verdicts, calls, meta = collect(args.journal_dir)
    picks = verdicts + calls
    if picks:
        ev = build_events(picks, load_panels(picks), horizons, fee_discount=args.fee_discount)
    else:
        ev = pd.DataFrame(columns=COLS)
    if args.speaker_records:
        print(json.dumps(speaker_records(ev, SPEAKER_HORIZON), ensure_ascii=False))
        return 0
    meta |= {"verdicts": len(verdicts), "calls": len(calls)}
    res = analyse(ev, horizons, args.bootstrap, args.seed)
    text = (json.dumps({"meta": meta, "result": res}, ensure_ascii=False, indent=1, default=str)
            if args.json else render(res, meta))
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
