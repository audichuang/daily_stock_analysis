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
    stop_loss／take_profit 就出場，開盤就越過停損／停利以開盤價成交（與 Web 回測共用
    `src.core.backtest_engine.resolve_bar_exit`），開盤在兩者之間、同日兩者都碰算停損，未碰則同 (1)。觸發與損益都在**還原**價空間（價位乘報告日因子：報告日非交易日時取之前最後一個交易日）
    （報告價位是報告日的名目價，報告日到出場之間的除權息／分割因此不會誤觸），損益用前復權價。價位缺值或不滿足 stop < 進場開盤 < take 時不套價位。
  - 成本：`src/utils/tw_trade_costs.round_trip_return`（含雙邊滑價、手續費、賣方證交稅；
    稅率走 `tw_sell_tax_rate`，以實際出場日判斷：00 開頭用 ETF 稅率，債券 ETF 在法定停徵期內免稅），
    固定名目本金。
  - 未完成：視窗最後一個交易日沒有收盤或還原因子（停牌、下市）且沒先碰停損／停利的交易標 `incomplete`，
    **不拿最後一筆有價收盤頂替出場**（那等於假設在停牌前賣掉，卻跟走完整個視窗的 0050 比），
    不進報酬統計，在報表逐表列出筆數。進場日沒開盤的照舊直接略過。
  - 區間：以 code 群聚的 bootstrap 95% CI（同檔相鄰視窗重疊一起重抽）；
    **未處理跨檔同日的相關性，區間可能仍偏窄**。區間跨零或不足兩檔一律標 inconclusive。

用法：
    uv run --env-file .env python scripts/shadow_buy_eval.py
    uv run --env-file .env python scripts/shadow_buy_eval.py --out reports/shadow.md --horizons 1,3,5
    uv run --env-file .env python scripts/shadow_buy_eval.py --by-variant
    uv run --env-file .env python scripts/shadow_buy_eval.py --forecast   # 固定預測題 p_5d_beat_0050 計分

--forecast 模式（口徑見 docs/decision-signals.md「固定預測題後驗計分」）：
  - y＝1(個股淨報酬 − 0050 淨報酬 > 0)：T+1 開盤進、第 5 個交易日收盤出；兩腿成本**分開**
    （個股腿走 tw_sell_tax_rate(個股)，0050 腿走 tw_sell_tax_rate("0050")，ETF 稅率較低）。
  - 與 v2 口徑不同：v2 依盤前證據可以當天進場，這裡一律延到 T+1。
  - Brier 對樸素基準（252 日滾動基率、Laplace 平滑，只用 resolved_at 早於預測日的事件）；配對差
    d_i＝基準 Brier − 模型 Brier（正＝模型較好）；另報 rank-IC。
  - 區間用**日期** block bootstrap（5 日標籤重疊：block≥5，同時報 10），不是 code 群聚。
  - 0050 本身排除；ETF 與個股分開列；n 不足或 CI 跨零一律 inconclusive。
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

from src.core.backtest_engine import resolve_bar_exit  # noqa: E402
from src.utils.tw_trade_costs import (  # noqa: E402
    ETF_TRANSACTION_TAX_RATE,
    STOCK_TRANSACTION_TAX_RATE,
    is_tw_etf,
    round_trip_return,
    tw_sell_tax_rate,
)

BENCHMARK = "0050"
DEFAULT_NOTIONAL = 200_000.0  # 與 measure_signal_forward 的 DEFAULT_POSITION_NOTIONAL 一致
BUY_TYPES = ("buy", "strong_buy")
UNTAGGED_VARIANT = "untagged"
INCOMPLETE = "incomplete"  # 視窗末段沒有價格（停牌／下市），出場價未知


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
    tax_rate 可以是單一稅率，或與 o 等長的逐日稅率（第 k 天出場就用第 k 個；債券 ETF 停徵看賣出日）。
    回傳 (淨報酬, 出場類型) ；進場日沒開盤價（停牌）回傳 None；沒先碰價位、最後一天又沒收盤或還原因子
    （停牌、下市）回傳 (nan, INCOMPLETE)——不拿較早的收盤冒充期末出場。
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
    for k in range(len(o)):
        if not np.isfinite(o[k]):
            continue
        if use_levels:
            decision = resolve_bar_exit(bar_open=o[k] * adj[k], high=h[k] * adj[k], low=lo[k] * adj[k],
                                        stop_loss=stop_adj, take_profit=take_adj)
            if decision is not None:
                first_hit, exit_adj = decision
                kind = "take" if first_hit == "take_profit" else "stop"  # ambiguous 保守算停損
                return _net(entry * adj[0], exit_adj, _tax_at(tax_rate, k), notional, fee_discount), kind
    last = len(c) - 1
    if not (np.isfinite(c[last]) and np.isfinite(adj[last]) and adj[last] > 0):
        return float("nan"), INCOMPLETE
    return _net(entry * adj[0], c[last] * adj[last], _tax_at(tax_rate, last), notional, fee_discount), "time"


def _tax_at(tax_rate, k):
    return float(tax_rate) if np.ndim(tax_rate) == 0 else float(tax_rate[k])


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
        for hz in horizons:
            if i0 + hz > len(cal):
                continue  # 視窗還沒走完
            win = slice(i0, i0 + hz)
            tax = [tw_sell_tax_rate(r.stock_id, d) for d in cal[win]]  # 逐日：停徵看實際賣出日

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
            inc = e[e["exit"] == INCOMPLETE]
            e = e[e["exit"] != INCOMPLETE]
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
            if len(inc):
                out.append(f"未完成（視窗末段停牌／下市、出場價未知，已排除）：raw-buy "
                           f"{int((inc['group'] == 'raw_buy').sum())} 筆、others "
                           f"{int((inc['group'] == 'others').sum())} 筆")
            out.append("")
    return out


# ---- --forecast：固定預測題 p_5d_beat_0050 的後驗計分（純函式；DB 只在 main 讀）----

FORECAST_H = 5            # 固定題的持有交易日數（T+1 開盤進、第 5 個交易日收盤出）
FORECAST_MIN_N = 30       # 配對樣本下限；不足一律 inconclusive
FORECAST_MIN_HIST = 20    # 基率歷史下限；不足的預測日不進 Brier 比較（Laplace 後的 0.5 不是有意義的基準）
BASE_RATE_WINDOW_DAYS = 252
FORECAST_BLOCKS = (5, 10)


def forecast_outcome(stock_bars, bench_bars, *, stock_tax, bench_tax, fee_discount=1.0):
    """一則預測的實現值：(個股淨報酬, 0050 淨報酬, y)；任一腿沒進場／出場價未知回 None。

    兩腿各用自己的稅率：個股約 0.3%、0050 是 ETF 的 0.1%。兩腿都用個股稅率會低估 0050 淨報酬、
    高估 y 的基率。bars＝(o, h, lo, c, adj)，長度 = FORECAST_H，進場日為第 1 天；不套停損停利。"""
    s = trade_return(*stock_bars, tax_rate=stock_tax, fee_discount=fee_discount)
    b = trade_return(*bench_bars, tax_rate=bench_tax, fee_discount=fee_discount)
    if s is None or b is None:
        return None
    if s[1] == INCOMPLETE or b[1] == INCOMPLETE or not (np.isfinite(s[0]) and np.isfinite(b[0])):
        return None
    return float(s[0]), float(b[0]), int(s[0] - b[0] > 0)


def macro_ctx_label(raw_result) -> str:
    """dashboard.experiments.macro_ctx（on/off）；沒有標籤（實驗前或比例為 0）歸 none。"""
    try:
        d = json.loads(raw_result) if isinstance(raw_result, str) else (raw_result or {})
    except ValueError:
        return "none"
    dash = d.get("dashboard") if isinstance(d.get("dashboard"), dict) else {}
    exp = dash.get("experiments") if isinstance(dash.get("experiments"), dict) else {}
    label = str(exp.get("macro_ctx") or "").strip()
    return label or "none"


def baseline_probs(day, resolved, y, window_days=BASE_RATE_WINDOW_DAYS):
    """樸素基準：預測日當天可知的、近 window_days 日已實現事件的勝率（Laplace 平滑 (w+1)/(n+2)）。

    只用 resolved_at **早於**預測日的事件（日期層級，保守：不用預測日當天才收盤的事件）。
    回傳 (機率陣列, 歷史筆數陣列)。"""
    day = pd.to_datetime(pd.Series(list(day))).to_numpy()
    resolved = pd.to_datetime(pd.Series(list(resolved))).to_numpy()
    y = np.asarray(y, dtype=float)
    lo_off = np.timedelta64(int(window_days), "D")
    probs, counts = [], []
    for d in day:
        m = (resolved < d) & (resolved >= d - lo_off)
        n = int(m.sum())
        probs.append((y[m].sum() + 1.0) / (n + 2.0))
        counts.append(n)
    return np.asarray(probs, dtype=float), np.asarray(counts, dtype=int)


def _date_axis(dates, extra=None):
    ts = pd.to_datetime(pd.Series(list(dates)))
    if extra is not None:
        ts = pd.concat([ts, pd.to_datetime(pd.Series(list(extra)))])
    return np.sort(ts.unique())


def _per_date(values, dates, axis):
    ts = pd.to_datetime(pd.Series(list(dates))).to_numpy()
    pos = np.searchsorted(axis, ts)
    v = np.asarray(values, dtype=float)
    return np.bincount(pos, weights=v, minlength=len(axis)), np.bincount(pos, minlength=len(axis)).astype(float)


def date_block_ci(values, dates, *, block, n=2000, seed=42, other=None):
    """以**日期**為單位的 moving-block bootstrap 均值 95% CI（環狀區塊，長度 block 個相鄰日曆項）。

    5 日標籤彼此重疊、同日各檔又共用市場衝擊，所以重抽單位是日期區塊而不是個別事件或 code。
    ``other=(values, dates)`` 時回傳兩組均值差的 CI（兩組共用同一條日期軸與同一批區塊）。
    **每一組**自己的有效日期數都要 ≥ 2×block（不是兩組聯集），否則回 None（由呼叫端標 inconclusive）：
    單組日期太少時，沒抽到該組的重抽會變 NaN 被濾掉，剩下的 CI 假窄。"""
    axis = _date_axis(dates, other[1] if other is not None else None)
    d = len(axis)
    if d < 2 * block or not len(values):
        return None
    for ds in (dates, other[1] if other is not None else None):
        if ds is not None and pd.to_datetime(pd.Series(list(ds))).nunique() < 2 * block:
            return None
    rng = np.random.default_rng(seed)
    n_blocks = -(-d // block)
    starts = rng.integers(0, d, size=(n, n_blocks))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % d).reshape(n, -1)[:, :d]
    sa, ca = _per_date(values, dates, axis)
    with np.errstate(invalid="ignore", divide="ignore"):
        stat = sa[idx].sum(axis=1) / ca[idx].sum(axis=1)
        if other is not None:
            sb, cb = _per_date(other[0], other[1], axis)
            stat = stat - sb[idx].sum(axis=1) / cb[idx].sum(axis=1)
    stat = stat[np.isfinite(stat)]
    if not len(stat):
        return None
    lo, hi = np.percentile(stat, [2.5, 97.5])
    return float(lo), float(hi)


def forecast_verdict(ci, n) -> str:
    if n < FORECAST_MIN_N:
        return "inconclusive（n 不足）"
    return verdict(ci)


def rank_ic(p, realized_excess) -> float:
    """p 與實現超額報酬（個股淨 − 0050 淨）的 Spearman（秩的皮爾森；常數序列回 nan）。"""
    a, b = pd.Series(np.asarray(p, dtype=float)), pd.Series(np.asarray(realized_excess, dtype=float))
    if len(a) < 3 or a.nunique() < 2 or b.nunique() < 2:
        return float("nan")
    return float(a.rank().corr(b.rank()))


def forecast_scores(ev) -> pd.DataFrame:
    """事件表 → 加上 base（樸素基準機率）、hist_n、brier、brier_base、d（基準 − 模型，正＝模型較好）。"""
    ev = ev.sort_values("day", kind="stable").reset_index(drop=True)
    base, hist = baseline_probs(ev["day"], ev["resolved_at"], ev["y"])
    ev = ev.assign(base=base, hist_n=hist)
    ev["brier"] = (ev["p"] - ev["y"]) ** 2
    ev["brier_base"] = (ev["base"] - ev["y"]) ** 2
    ev["d"] = ev["brier_base"] - ev["brier"]
    return ev


def select_forecast_reports(df) -> pd.DataFrame:
    """先取同股同日最後一份，再丟 p 為空的：最後一份沒作答就整天不計，不改拿較早那份（避免選擇偏誤）。"""
    return latest_per_code_day(df).dropna(subset=["p"]).reset_index(drop=True)


def forecast_scores_by_kind(ev) -> pd.DataFrame:
    """個股與 ETF 各自算 252 日基率基準（ETF 的基準不能被個股事件決定）。"""
    parts = [forecast_scores(g) for _, g in ev.groupby("kind", sort=False)]
    return pd.concat(parts, ignore_index=True) if parts else ev


def load_forecast_reports(url) -> pd.DataFrame:
    from sqlalchemy import create_engine, text
    with create_engine(url).connect() as c:
        _read_only(c)
        df = pd.read_sql(text(
            "select code, created_at, p_5d_beat_0050 as p, raw_result "
            "from analysis_history where report_type = 'simple' "
            "and (code like '%.TW' or code like '%.TWO')"), c, parse_dates=["created_at"])
    if df.empty:
        return df
    df = select_forecast_reports(df)
    df["ctx"] = [macro_ctx_label(r) for r in df["raw_result"]]
    df["stock_id"] = df["code"].str.split(".").str[0]
    return df.drop(columns="raw_result")


def build_forecast_events(reports, panels, *, fee_discount=1.0, h=FORECAST_H):
    cal = panels["close"].index
    if BENCHMARK not in panels["close"].columns:
        return pd.DataFrame()
    rows = []
    for r in reports.itertuples(index=False):
        if r.stock_id == BENCHMARK or r.stock_id not in panels["close"].columns:
            continue  # 0050 本身不評（對自己的超額恆為 0）
        i0 = cal.searchsorted(r.day, side="right")  # 報告日之後第一個交易日（T+1）
        if i0 + h > len(cal):
            continue  # 視窗還沒走完
        win = slice(i0, i0 + h)
        exit_day = cal[i0 + h - 1]

        def seq(sid):
            return tuple(panels[k][sid].to_numpy()[win] for k in ("open", "high", "low", "close", "adj"))

        res = forecast_outcome(seq(r.stock_id), seq(BENCHMARK),
                               stock_tax=tw_sell_tax_rate(r.stock_id, exit_day),
                               bench_tax=tw_sell_tax_rate(BENCHMARK, exit_day), fee_discount=fee_discount)
        if res is None:
            continue
        rows.append({"code": r.code, "day": r.day, "resolved_at": exit_day, "p": float(r.p), "y": res[2],
                     "net_stock": res[0], "net_bench": res[1], "ctx": r.ctx,
                     "kind": "etf" if is_tw_etf(r.stock_id) else "stock"})
    return pd.DataFrame(rows)


def _fmt_ci(ci):
    return f"[{ci[0]:+.4f}, {ci[1]:+.4f}]" if ci else "—"


def _forecast_table(sc, args) -> list:
    """一組事件的計分表：Brier、基準 Brier、配對差 d 的日期 block bootstrap（block 5／10）、rank-IC。"""
    n_all = len(sc)
    sc = sc[sc["hist_n"] >= FORECAST_MIN_HIST]
    out = [f"- 事件 {n_all} 筆，其中基率歷史 ≥ {FORECAST_MIN_HIST} 筆者 {len(sc)} 筆進比較（其餘基準不可靠、排除）"]
    if sc.empty:
        return out + ["- 沒有可比較的事件：inconclusive", ""]
    ic = rank_ic(sc["p"], sc["net_stock"] - sc["net_bench"])
    out += [f"- 實現勝率 {sc['y'].mean() * 100:.1f}%、平均 p {sc['p'].mean():.3f}、{sc['day'].nunique()} 個預測日、"
            f"rank-IC {'—' if math.isnan(ic) else f'{ic:+.3f}'}",
            f"- Brier：模型 {sc['brier'].mean():.4f}、252 日基率基準 {sc['brier_base'].mean():.4f}",
            "", "| 比較 | block | n | 均值 | 95% CI | 判定 |", "|---|---|---|---|---|---|"]
    for blk in FORECAST_BLOCKS:
        ci = date_block_ci(sc["d"], sc["day"], block=blk, n=args.bootstrap, seed=args.seed)
        out.append(f"| d＝基準 Brier − 模型 Brier（正＝模型較好） | {blk} | {len(sc)} | {sc['d'].mean():+.4f} | "
                   f"{_fmt_ci(ci)} | {forecast_verdict(ci, len(sc))} |")
    on, off = sc[sc["ctx"] == "on"], sc[sc["ctx"] == "off"]
    if len(on) and len(off):
        out += ["", "依 `experiments.macro_ctx` 分組（總經背景區塊 on／off，同期對照）：", "",
                "| 組別／比較 | block | n | d 均值 | 95% CI | 判定 |", "|---|---|---|---|---|---|"]
        for label, g in (("on", on), ("off", off)):
            out.append(f"| {label} | — | {len(g)} | {g['d'].mean():+.4f} | — | — |")
        for blk in FORECAST_BLOCKS:
            ci = date_block_ci(on["d"], on["day"], block=blk, n=args.bootstrap, seed=args.seed,
                               other=(off["d"], off["day"]))
            out.append(f"| on − off（d 的差） | {blk} | {len(on)}／{len(off)} | "
                       f"{on['d'].mean() - off['d'].mean():+.4f} | {_fmt_ci(ci)} | "
                       f"{forecast_verdict(ci, min(len(on), len(off)))} |")
    return out + [""]


def render_forecast(ev, args) -> str:
    out = [f"# 固定預測題 p_5d_beat_0050 後驗計分（{dt.date.today()}）", "",
           "- y＝1(個股淨報酬 > 0050 淨報酬)：報告日之後第一個交易日開盤進、第 5 個交易日收盤出；"
           "兩腿成本分開（個股腿 tw_sell_tax_rate(個股)、0050 腿 tw_sell_tax_rate(\"0050\")）",
           "- 與 v2 口徑不同：v2 依盤前證據可以當天進場，這裡一律延到 T+1",
           "- 基準：252 日滾動基率（Laplace 平滑），只用 resolved_at 早於預測日的事件",
           f"- 日期 block bootstrap：block {FORECAST_BLOCKS[0]}／{FORECAST_BLOCKS[1]}、{args.bootstrap} 次、seed={args.seed}；"
           f"n < {FORECAST_MIN_N}、日期數 < 2×block 或 CI 跨零一律 inconclusive",
           "- 0050 本身排除；ETF 與個股分開列。**樣本內、只讀**：結論必須過對抗審查才可寫進 docs。", ""]
    if ev.empty:
        return "\n".join(out + ["沒有已走完 5 日視窗、帶 p_5d_beat_0050 的事件：inconclusive。", ""])
    sc = forecast_scores_by_kind(ev)
    for kind, title in (("stock", "個股"), ("etf", "ETF")):
        g = sc[sc["kind"] == kind]
        if g.empty:
            continue
        out += [f"## {title}", ""] + _forecast_table(g, args)
    return "\n".join(out)


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
    p.add_argument("--forecast", action="store_true",
                   help="固定預測題 p_5d_beat_0050 的後驗計分（Brier、基率基準、日期 block bootstrap），不跑 raw-buy 影子評估")
    a = p.parse_args(argv)
    if not a.db:
        raise SystemExit("STORAGE_DATABASE_URL 未設定：用 `uv run --env-file .env` 執行或帶 --db")
    horizons = sorted({int(x) for x in a.horizons.split(",") if x.strip()})

    from market_data.db import get_engine
    if a.forecast:
        freports = load_forecast_reports(a.db)
        if freports.empty:
            raise SystemExit("analysis_history 沒有帶 p_5d_beat_0050 的台股報告")
        ids = sorted(set(freports["stock_id"]) | {BENCHMARK})
        start = (freports["day"].min() - pd.Timedelta(days=5)).date()
        end = (freports["day"].max() + pd.Timedelta(days=FORECAST_H * 2 + 10)).date()
        panels = load_bars(get_engine(), ids, start, end)
        fev = build_forecast_events(freports, panels, fee_discount=a.fee_discount)
        out = Path(a.out) if a.out else REPO / "reports" / f"shadow_forecast_{dt.date.today():%Y%m%d}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_forecast(fev, a), encoding="utf-8")
        print(f"已寫入 {out}")
        return
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
