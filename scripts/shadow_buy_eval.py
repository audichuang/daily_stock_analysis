#!/usr/bin/env python3
"""影子評估：被護欄壓掉的 LLM 原判「買進」，照做的話短線到底賺不賺（唯讀）。

回答 `.claude/reviews/2026-10-22-no-buy-diagnosis.md` P1 的問題：資金流護欄（R1）把台股的
買進 100% 改成觀望，那 LLM 原本的買進有沒有用？本腳本**只讀**，不改正式庫的任何建議。

口徑（每一條都會改變數字，改之前先想清楚）：
  - 範圍：`analysis_history` 的台股報告（`.TW`／`.TWO`），同股同日多份取最後一份。
  - LLM 原判：`dashboard.decision_score_calibration.raw_score`（R1 資金流／結構、大盤環境、
    交易成本護欄壓分時落庫，保留最早那份）→ `dashboard.decision_stability.raw_score` → 最終
    `sentiment_score`。原始動作取 `raw_decision_type`（後段護欄記下的護欄前動作）→
    `canonical_decision_type`（依原始分數）→ 最終 `decision_type`。
  - 提示詞版本：`dashboard.prompt_variant`（`PROMPT_VARIANT`，預設 baseline）；標籤上線前的舊報告
    沒有這欄，歸 `untagged`（不冒充 baseline）。`--by-variant` 依此分組各跑一份表。
    **已知盲區**：LLM 自己在文字裡降級的那批（calibration 只有 `guardrail_reason`）回推不出原分。
  - 分組：raw-buy＝原始分數 ≥ `--buy-threshold`（預設 60，與 canonical 量尺一致）或原始動作為 buy；
    others＝其餘；0050＝raw-buy 那些事件同一個進出場視窗的 0050。
  - 進場：報告日期**之後**第一個交易日的開盤（盤前報告也延到隔日，避免時區與前視疑慮）。
  - 出場（兩種都算）：(1) 第 h 個交易日收盤（進場日算第 1 天）；(2) 視窗內先碰報告的
    stop_loss／take_profit 就出場，開盤已觸價時以開盤成交；開盤在兩價之間且同日雙觸價才算停損，未碰則同 (1)。觸發與損益都在**還原**價空間（價位乘報告日因子：報告日非交易日時取之前最後一個交易日）
    （報告價位是報告日的名目價，報告日到出場之間的除權息／分割因此不會誤觸），損益用前復權價。價位缺值或不滿足 stop < 進場開盤 < take 時不套價位。
  - 成本：`src/utils/tw_trade_costs.round_trip_return`（含雙邊滑價、手續費、賣方證交稅；
    00 開頭用 ETF 稅率），固定名目本金。
  - 區間：以 code 群聚的 bootstrap 95% CI（同檔相鄰視窗重疊一起重抽）；
    **未處理跨檔同日的相關性，區間可能仍偏窄**。區間跨零或不足兩檔一律標 inconclusive。

用法：
    uv run --env-file .env python scripts/shadow_buy_eval.py
    uv run --env-file .env python scripts/shadow_buy_eval.py --out reports/shadow.md --horizons 1,3,5
    uv run --env-file .env python scripts/shadow_buy_eval.py --by-variant
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.core.backtest_engine import resolve_long_exit  # noqa: E402
from src.utils.tw_trade_costs import (  # noqa: E402
    ETF_TRANSACTION_TAX_RATE,
    STOCK_TRANSACTION_TAX_RATE,
    round_trip_return,
)

BENCHMARK = "0050"
DEFAULT_NOTIONAL = 200_000.0  # 與 measure_signal_forward 的 DEFAULT_POSITION_NOTIONAL 一致
BUY_TYPES = ("buy", "strong_buy")
UNTAGGED_VARIANT = "untagged"


def raw_decision(raw_result, final_score=None) -> dict:
    """從 raw_result 取 LLM 在護欄前的原始分數／動作與最終動作。"""
    try:
        d = json.loads(raw_result) if isinstance(raw_result, str) else (raw_result or {})
    except ValueError:
        d = {}
    dash = d.get("dashboard") if isinstance(d.get("dashboard"), dict) else {}
    cal = dash.get("decision_score_calibration") if isinstance(dash.get("decision_score_calibration"), dict) else {}
    st = dash.get("decision_stability") if isinstance(dash.get("decision_stability"), dict) else {}
    score = next((v for v in (cal.get("raw_score"), st.get("raw_score"), d.get("sentiment_score"), final_score)
                  if v is not None), None)
    return {
        "raw_score": float(score) if score is not None else None,
        "raw_type": cal.get("raw_decision_type") or cal.get("canonical_decision_type") or d.get("decision_type"),
        "final_type": cal.get("final_action") or st.get("final_action") or d.get("decision_type"),
        "downgraded": cal.get("raw_score") is not None or st.get("raw_score") is not None,
        "variant": str(dash.get("prompt_variant") or "").strip() or UNTAGGED_VARIANT,
    }


def is_raw_buy(raw_score, raw_type, threshold=60) -> bool:
    return (raw_score is not None and raw_score >= threshold) or raw_type in BUY_TYPES


def trade_return(o, h, lo, c, adj, *, stop=None, take=None, level_adj=None, tax_rate=STOCK_TRANSACTION_TAX_RATE,
                 notional=DEFAULT_NOTIONAL, fee_discount=1.0):
    """一筆影子交易的淨報酬。

    o/h/lo/c/adj 是從進場日（第 1 天）起、長度 = 持有天數的序列；o/h/lo/c 為未還原價，adj 為前復權因子。
    level_adj 是報告價位所屬那天（報告日）的前復權因子；未給時視為進場日（adj[0]）。
    回傳 (淨報酬, 出場類型) ；進場日沒開盤價（停牌）回傳 None。
    """
    if not np.isfinite(o[0]):
        return None
    entry = o[0]
    # 報告價位是報告日的名目價：一律換到還原價空間再比，報告日到出場之間除權息／分割才不會誤觸或失效
    f_level = adj[0] if level_adj is None or not np.isfinite(level_adj) else level_adj
    entry_adj = entry * adj[0]
    use_levels = (stop is not None and take is not None and np.isfinite(stop) and np.isfinite(take)
                  and stop * f_level < entry_adj < take * f_level)
    stop_adj = stop * f_level if use_levels else None
    take_adj = take * f_level if use_levels else None
    last = None
    for k in range(len(o)):
        if not np.isfinite(o[k]):
            continue
        if use_levels:
            o_adj, h_adj, lo_adj = o[k] * adj[k], h[k] * adj[k], lo[k] * adj[k]
            fill = resolve_long_exit(
                bar_open=o_adj, stop_loss=stop_adj, take_profit=take_adj,
                stop_hit=lo_adj <= stop_adj, tp_hit=h_adj >= take_adj,
            )
            if fill is not None:
                exit_adj, reason = fill
                kind = "take" if reason == "take_profit" else "stop"
                return _net(entry * adj[0], exit_adj, tax_rate, notional, fee_discount), kind
        if np.isfinite(c[k]):
            last = k
    if last is None:
        return None
    return _net(entry * adj[0], c[last] * adj[last], tax_rate, notional, fee_discount), "time"


def _net(entry_adj, exit_adj, tax_rate, notional, fee_discount):
    return round_trip_return(entry_adj, exit_adj, entry_notional=notional,
                             tax_rate=tax_rate, fee_discount=fee_discount)


def _boot_means(values, clusters, n, rng):
    v = np.asarray(values, dtype=float)
    g = pd.factorize(pd.Series(list(clusters)), sort=True)[0]  # 依 code 排序編號：結果不受列順序影響
    k = int(g.max()) + 1 if len(g) else 0
    if k < 2:
        return None
    sums = np.bincount(g, weights=v, minlength=k)
    cnts = np.bincount(g, minlength=k)
    idx = rng.integers(0, k, size=(n, k))
    return sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)


def cluster_bootstrap_ci(values, clusters, n=2000, seed=42, other=None):
    """以 cluster（code）為單位重抽的均值 95% CI；``other=(values, clusters)`` 時回傳兩組均值差的 CI。

    不足兩個 cluster 回傳 None（由呼叫端標 inconclusive）。
    """
    rng = np.random.default_rng(seed)
    a = _boot_means(values, clusters, n, rng)
    if a is None:
        return None
    if other is not None:
        b = _boot_means(other[0], other[1], n, rng)
        if b is None:
            return None
        a = a - b
    lo, hi = np.percentile(a, [2.5, 97.5])
    return float(lo), float(hi)


def verdict(ci) -> str:
    if ci is None or ci[0] <= 0 <= ci[1]:
        return "inconclusive"
    return "顯著為正" if ci[0] > 0 else "顯著為負"


def _pct(x):
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:+.2f}%"


def stats_row(label, vals, clusters, n_boot, seed, other=None):
    vals = np.asarray(vals, dtype=float)
    ci = cluster_bootstrap_ci(vals, clusters, n_boot, seed, other) if len(vals) else None
    ci_txt = f"[{_pct(ci[0])}, {_pct(ci[1])}]" if ci else "—"
    if other is not None:
        mean = float(vals.mean() - np.mean(other[0])) if len(vals) and len(other[0]) else float("nan")
        return f"| {label} | {len(vals)}／{len(other[0])} | {_pct(mean)} | — | — | {ci_txt} | {verdict(ci)} |"
    if not len(vals):
        return f"| {label} | 0 | — | — | — | — | inconclusive |"
    return (f"| {label} | {len(vals)}（{len(set(clusters))} 檔） | {_pct(float(vals.mean()))} | "
            f"{_pct(float(np.median(vals)))} | {(vals > 0).mean() * 100:.0f}% | {ci_txt} | {verdict(ci)} |")


# ---- DB（只在 main 執行；import 本檔不碰任何連線）----

def _read_only(conn):
    if conn.dialect.name == "postgresql":
        from sqlalchemy import text
        conn.execute(text("SET TRANSACTION READ ONLY"))
    return conn


def latest_per_code_day(df) -> pd.DataFrame:
    """同股同日只留 created_at 最晚的那一整列。

    不能用 groupby().last()：它逐欄跳過 NaN，最後一份沒填停損時會偷拿前一份的停損，
    拼出一份不存在的報告。
    """
    df = df.assign(day=df["created_at"].dt.normalize())
    return (df.sort_values("created_at", kind="stable")
            .drop_duplicates(["code", "day"], keep="last").reset_index(drop=True))


def load_reports(url) -> pd.DataFrame:
    from sqlalchemy import create_engine, text
    with create_engine(url).connect() as c:
        _read_only(c)
        df = pd.read_sql(text(
            "select code, created_at, sentiment_score, ideal_buy, stop_loss, take_profit, raw_result "
            "from analysis_history where report_type = 'simple' "
            "and (code like '%.TW' or code like '%.TWO')"), c, parse_dates=["created_at"])
    df = latest_per_code_day(df)
    dec = pd.DataFrame([raw_decision(r, s) for r, s in zip(df["raw_result"], df["sentiment_score"])],
                       index=df.index)
    df = pd.concat([df.drop(columns="raw_result"), dec], axis=1)
    df["stock_id"] = df["code"].str.split(".").str[0]
    return df


def load_bars(engine, ids, start, end):
    from sqlalchemy import text
    from market_data.adjust import load_factors
    with engine.connect() as c:
        _read_only(c)
        px = pd.read_sql(text(
            "select stock_id, date, open, high, low, close from market.price "
            "where stock_id = any(:ids) and date >= :s and date <= :e"),
            c, params={"ids": list(ids), "s": start, "e": end}, parse_dates=["date"])
        if px.empty:
            raise SystemExit("market.price 查不到這些標的——先確認 DATABASE_URL 與資料是否已更新")
        panels = {k: px.pivot(index="date", columns="stock_id", values=k).astype(float).sort_index()
                  for k in ("open", "high", "low", "close")}
        panels["adj"] = load_factors(c, panels["close"].index, panels["close"].columns, start=start)
    return panels


def build_events(reports, panels, horizons, *, threshold, fee_discount):
    cal = panels["close"].index
    rows = []
    for r in reports.itertuples(index=False):
        if r.stock_id not in panels["close"].columns:
            continue
        i0 = cal.searchsorted(r.day, side="right")  # 報告日之後第一個交易日
        adj_col = panels["adj"][r.stock_id].to_numpy()
        level_adj = adj_col[i0 - 1] if i0 >= 1 else np.nan  # 報告日（或之前最後一個交易日）的因子
        group = "raw_buy" if is_raw_buy(r.raw_score, r.raw_type, threshold) else "others"
        tax = ETF_TRANSACTION_TAX_RATE if r.stock_id.startswith("00") else STOCK_TRANSACTION_TAX_RATE
        for hz in horizons:
            if i0 + hz > len(cal):
                continue  # 視窗還沒走完
            win = slice(i0, i0 + hz)

            def seq(sid, k):
                return panels[k][sid].to_numpy()[win]

            bench = trade_return(*(seq(BENCHMARK, k) for k in ("open", "high", "low", "close", "adj")),
                                 tax_rate=ETF_TRANSACTION_TAX_RATE, fee_discount=fee_discount)
            for mode, stop, take in (("time", None, None), ("levels", r.stop_loss, r.take_profit)):
                res = trade_return(*(seq(r.stock_id, k) for k in ("open", "high", "low", "close", "adj")),
                                   stop=stop, take=take, level_adj=level_adj, tax_rate=tax,
                                   fee_discount=fee_discount)
                if res is None:
                    continue
                rows.append({"code": r.code, "day": r.day, "group": group, "h": hz, "mode": mode,
                             "ret": res[0], "exit": res[1], "bench": bench[0] if bench else np.nan,
                             "downgraded": r.downgraded, "variant": r.variant})
    return pd.DataFrame(rows)


def render(ev, reports, args) -> str:
    mask = reports.apply(lambda r: is_raw_buy(r.raw_score, r.raw_type, args.buy_threshold), axis=1)
    early = int((reports["created_at"].dt.hour < 9).sum())
    out = [f"# 影子評估：LLM 原判買進（{dt.date.today()}）", "",
           f"- 報告：{len(reports)} 個 code-day、{reports['code'].nunique()} 檔，"
           f"{reports['day'].min().date()} ～ {reports['day'].max().date()}",
           f"- raw-buy 門檻：原始分數 ≥ {args.buy_threshold} 或原始動作 buy；"
           f"raw-buy {int(mask.sum())} 筆，其中被護欄壓分（有 raw_score 落庫）"
           f"{int(reports.loc[mask, 'downgraded'].sum())} 筆",
           f"- 盤前（09:00 前）產出的報告 {early} 份：一律延到報告日隔一個交易日開盤進場（保守，會低估當日訊號）",
           "- LLM 在文字裡自行降級（calibration 只有 guardrail_reason）的報告回推不出原分，歸在 others",
           "- h=1 的絕對報酬幾乎都是成本（一趟約 0.6～0.9%）；要看的是成對的 raw-buy − 0050 與 raw-buy − others",
           f"- bootstrap：以 code 群聚、{args.bootstrap} 次、seed={args.seed}；區間跨零或不足兩檔一律 inconclusive",
           "- **只讀、樣本內**：未處理跨檔同日相關性，區間可能偏窄；結論必須過對抗審查才可寫進 docs。", ""]
    if getattr(args, "by_variant", False):
        counts = reports["variant"].value_counts()
        out += ["- 提示詞版本（code-day 數）：" + "、".join(f"{k} {v}" for k, v in counts.items()), ""]
        for variant in sorted(counts.index):
            out += [f"## 版本：{variant}", ""]
            out += _blocks(ev[ev["variant"] == variant] if not ev.empty else ev, args, level="#")
        return "\n".join(out)
    return "\n".join(out + _blocks(ev, args))


def _blocks(ev, args, level="") -> list:
    out = []
    if ev.empty:
        return ["沒有已走完視窗的事件。", ""]
    titles = {"time": "第 h 日收盤出場", "levels": "報告停損／目標價先到先出，否則第 h 日收盤"}
    for mode in ("time", "levels"):
        out += [f"{level}## {titles[mode]}", ""]
        for hz in sorted(ev["h"].unique()):
            e = ev[(ev["mode"] == mode) & (ev["h"] == hz)]
            buy, oth = e[e["group"] == "raw_buy"], e[e["group"] == "others"]
            paired = buy.dropna(subset=["bench"])
            out += [f"{level}### h = {hz}", "", "| 組別 | n | 均值 | 中位數 | 勝率 | 95% CI | 判定 |",
                    "|---|---|---|---|---|---|---|",
                    stats_row("raw-buy", buy["ret"], buy["code"], args.bootstrap, args.seed),
                    stats_row("raw-buy（僅被護欄降級者）", buy.loc[buy["downgraded"], "ret"],
                              buy.loc[buy["downgraded"], "code"], args.bootstrap, args.seed),
                    stats_row("others", oth["ret"], oth["code"], args.bootstrap, args.seed),
                    stats_row("0050（raw-buy 同視窗）", paired["bench"], paired["code"], args.bootstrap, args.seed),
                    stats_row("raw-buy − 0050（成對）", paired["ret"] - paired["bench"], paired["code"],
                              args.bootstrap, args.seed),
                    stats_row("raw-buy − others", buy["ret"], buy["code"], args.bootstrap, args.seed,
                              other=(oth["ret"].to_numpy(), oth["code"].tolist()))]
            if mode == "levels":
                out.append("")
                out.append("raw-buy 出場類型：" + "、".join(
                    f"{k} {v}" for k, v in buy["exit"].value_counts().items()))
            out.append("")
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--db", default=os.environ.get("STORAGE_DATABASE_URL"),
                   help="分析歷史的 SQLAlchemy URL（預設 STORAGE_DATABASE_URL；只做 SELECT）")
    p.add_argument("--out", default=None,
                   help="markdown 輸出路徑（預設 reports/shadow_buy_eval_<今天>.md，reports/ 不進版控）")
    p.add_argument("--horizons", default="1,2,3,5", help="持有交易日數，逗號分隔（預設 1,2,3,5）")
    p.add_argument("--buy-threshold", type=float, default=60, help="raw-buy 的原始分數門檻（預設 60）")
    p.add_argument("--fee-discount", type=float, default=1.0, help="手續費折扣（預設 1.0＝不打折）")
    p.add_argument("--bootstrap", type=int, default=2000, help="bootstrap 次數（預設 2000）")
    p.add_argument("--seed", type=int, default=42, help="bootstrap 隨機種子（預設 42）")
    p.add_argument("--by-variant", action="store_true",
                   help="依 dashboard.prompt_variant 分組各出一份表（未標記的舊報告歸 untagged）")
    a = p.parse_args(argv)
    if not a.db:
        raise SystemExit("STORAGE_DATABASE_URL 未設定：用 `uv run --env-file .env` 執行或帶 --db")
    horizons = sorted({int(x) for x in a.horizons.split(",") if x.strip()})

    from market_data.db import get_engine
    reports = load_reports(a.db)
    if reports.empty:
        raise SystemExit("analysis_history 沒有台股報告")
    ids = sorted(set(reports["stock_id"]) | {BENCHMARK})
    start = (reports["day"].min() - pd.Timedelta(days=5)).date()
    end = (reports["day"].max() + pd.Timedelta(days=max(horizons) * 2 + 10)).date()
    panels = load_bars(get_engine(), ids, start, end)
    ev = build_events(reports, panels, horizons, threshold=a.buy_threshold, fee_discount=a.fee_discount)
    out = Path(a.out) if a.out else REPO / "reports" / f"shadow_buy_eval_{dt.date.today():%Y%m%d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(ev, reports, a), encoding="utf-8")
    print(f"已寫入 {out}")


if __name__ == "__main__":
    main()
