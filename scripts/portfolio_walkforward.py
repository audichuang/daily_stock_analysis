#!/usr/bin/env python3
"""把訊號的前瞻分布壓成「有限資金真能拿到的那條權益曲線」。

`measure_signal_forward.py` 證明的是**邊際**期望值：每個事件單獨看均值為正。它刻意不做部位
模擬，所以答不出配置真錢前的最後一關——**前 12% 的事件貢獻總報酬 106%，這些右尾能不能被
有限資金實際持有**？只要同日訊號多於空位、而排擠掉的剛好是大贏家，邊際優勢就落不了地。

因此這裡只回答三件事，其他一律不做（出場仍是固定持有 h 日，與量測一致）：

1. **同日資金競爭**：`--slots` 個空位滿了就不進場。被排擠的候選會被記錄下來並用同一組
   前瞻報酬比較——`排擠成本` 為正代表「沒買到的比買到的更好」，那是排序在傷害你。
   **兩側都要事件去重**：買到的一側因持有 h 日天然接近去重，沒買到的一側每天重複追加。
2. **排序有沒有加值**：`--rank-test N` 用 live 的 `screen_tw` 排序公式跑一次，再跑 N 次同池
   亂序，報 score 在亂序分布裡的百分位。N 太小連 permutation p 值的下限都不夠（10 次的
   下限是 1/11），所以「沒有觀察到優勢」與「檢定沒有效力」會分不開。
3. **走前驗證（walk-forward）**：門檻是在整段樣本上挑的。`--walk-forward` 改成擴張窗：
   每一折只用**該折之前、且報酬已實現**的資料從網格挑門檻,再用它交易下一折。與凍結版的
   差距是**兩套規則的樣本外績效差**，**不是選參偏誤的規模**——這裡只掃三個參數，而且用
   事件均值選參卻用組合 CAGR/Sharpe 評分（目標函數錯配），兩者不構成 paired optimism 比較。

**池子預設排除創新板**（`--include-tib` 放回）：live 的 `screen_tw.funnel` 排除它，不排除等於
讓組合買進 live 永遠不會買的標的，而全庫唯一過得了流動性門檻的 7610 是 10 倍股——單它一檔就
把全期 Sharpe 由 1.22 撐到 1.30，足以讓結論從「輸給 0050」變成「打平」。獨立審查指出。

用法：
    uv run --env-file .env python scripts/portfolio_walkforward.py
    uv run --env-file .env python scripts/portfolio_walkforward.py --rank-test 200
    uv run --env-file .env python scripts/portfolio_walkforward.py --skip-limit-gap
    uv run --env-file .env python scripts/portfolio_walkforward.py --walk-forward
"""

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from market_data.db import get_engine  # noqa: E402
from measure_signal_forward import (  # noqa: E402
    COST, apply_thresholds, factors, forward_returns, load, pit_revenue_panel, to_events,
)

SIDE_COST = COST / 2      # 量測扣的是來回 0.6%，這裡拆成買賣各一半
TRADING_DAYS = 245        # 台股年均交易日


DEAD_DAYS = 20            # 連續無報價超過這麼多交易日才當下市（PIT，不看未來）
LIMIT_GAP = 0.095         # 開盤跳空達此幅度視為貼近漲停，成交量無法證明可全額成交


def rank_candidates(cand, prev, scores, mode, rng):
    """同日候選的優先序。`scores` 是**當日完整候選池**算好的分數（見 `daily_scores`）。

    排序分數必須在**剔除已持股與無開盤價之前**算完：live 的 `screen_tw.funnel` 是在當日
    完整 pool 上取 pct-rank，若先剔除再算，其餘個股的百分位間距會改變甚至翻轉排序。
    """
    if mode == "random":
        return list(rng.permutation(list(cand)))
    if callable(mode):
        return sorted(cand, key=lambda s: -mode(prev, s))
    return sorted(cand, key=lambda s: -scores.get((prev, s), 0.0))


def daily_scores(sig, f, yoy):
    """live 的 breakout 排序公式：當日完整候選池上的 yoy + 0.5×量比 + 0.5×d5 的 pct-rank。"""
    out = {}
    for d in sig.index[sig.any(axis=1)]:
        cols = list(sig.columns[sig.loc[d].to_numpy()])
        if not cols:
            continue
        df = pd.DataFrame({"yoy": [yoy.at[d, s] for s in cols],
                           "vol_r": [f["vol_r"].at[d, s] for s in cols],
                           "d5": [f["d5"].at[d, s] for s in cols]}, index=cols)
        # 缺任一因子時該項給 0，而不是讓整個分數變 NaN（NaN 排序等於回到欄位順序）
        r = df.rank(pct=True).fillna(0.0)
        sc = r["yoy"] + r["vol_r"] * 0.5 + r["d5"] * 0.5
        for s, v in sc.items():
            out[(d, s)] = float(v)
    return out


def simulate(piv, sig, f, yoy, h, slots, start, end, rank="score", seed=42,
             delisting="last", skip_limit_gap=False, scores=None):
    """T+1 開盤買、持有 h 個交易日後收盤賣，同時最多 `slots` 檔、等權。

    現金流時序刻意保守：**今天開盤的買進只能用昨天收盤前就有的現金**（今天賣出的錢要到
    明天開盤才能用），否則就是用未實現的賣出款買進。

    停牌與下市一律**不看未來**：出場日無報價就順延到下一個可成交日；連續 `DEAD_DAYS` 個
    交易日沒有報價才視為下市並結算（舊版用「這一列或之後還有沒有成交價」判定，那是前視——
    會在第一個缺價日就「知道」樣本內不再有報價而提前釋放資金）。樣本結束仍未成交的部位
    列為 right-censored，不計入成交統計，但權益曲線照市值標記。
    """
    close, open_ = piv["close"], piv["open"]
    dates = close.index
    lastc = close.ffill()
    if scores is None and rank == "score":
        scores = daily_scores(sig, f, yoy)
    i0 = int(dates.searchsorted(pd.Timestamp(start)))
    i1 = int(dates.searchsorted(pd.Timestamp(end), side="right"))
    rng = np.random.default_rng(seed)

    cash, pos = 1.0, {}
    eq_idx, eq_val, trades, skipped = [], [], [], []
    counts = {"entries": 0, "already_held": 0, "no_open": 0, "limit_gap": 0}
    prev_equity = 1.0
    for i in range(max(i0, 1), i1):
        d, prev = dates[i], dates[i - 1]
        # 1) 進場：昨天收盤的訊號，今天開盤價成交
        raw = list(sig.columns[sig.loc[prev].to_numpy()])
        counts["already_held"] += sum(1 for s in raw if s in pos)
        cand = []
        for s in raw:
            if s in pos:
                continue
            op = open_.at[d, s]
            if pd.isna(op) or op <= 0:
                counts["no_open"] += 1
                continue
            pc = lastc.at[prev, s]
            if skip_limit_gap and pd.notna(pc) and pc > 0 and op / pc - 1 >= LIMIT_GAP:
                counts["limit_gap"] += 1
                continue
            cand.append(s)
        if cand:
            order = rank_candidates(cand, prev, scores, rank, rng)
            free = max(0, slots - len(pos))
            for j, s in enumerate(order):
                if j >= free or cash <= 1e-9:
                    skipped.append({"date": prev, "stock_id": s,
                                    "reason": "no_slot" if j >= free else "no_cash"})
                    continue
                alloc = min(cash, prev_equity / slots)
                px = float(open_.at[d, s])
                cash -= alloc
                counts["entries"] += 1
                pos[s] = {"qty": alloc * (1 - SIDE_COST) / px, "exit_i": i + h - 1,
                          "entry": px, "entry_date": d, "cost": alloc, "stale": 0}
        # 2) 出場：到期且當日可成交；停牌則順延，連續 DEAD_DAYS 無報價才判下市
        for s, p in list(pos.items()):
            quoted = pd.notna(close.at[d, s])
            p["stale"] = 0 if quoted else p["stale"] + 1
            dead = p["stale"] >= DEAD_DAYS
            if not dead and (p["exit_i"] > i or not quoted):
                continue
            pos.pop(s)
            px = 0.0 if (dead and delisting == "zero") else float(lastc.at[d, s])
            proceeds = p["qty"] * px * (1 - SIDE_COST)
            cash += proceeds
            trades.append({"stock_id": s, "entry_date": p["entry_date"], "exit_date": d,
                           "entry": p["entry"], "exit": px, "delisted": dead,
                           "deferred": d != dates[min(p["exit_i"], len(dates) - 1)],
                           "r": proceeds / p["cost"] - 1})
        # 3) 收盤標記
        prev_equity = cash + sum(p["qty"] * float(lastc.at[d, s]) for s, p in pos.items())
        eq_idx.append(d)
        eq_val.append(prev_equity)
    counts["closed"] = len(trades)
    counts["open_at_end"] = len(pos)
    return (pd.Series(eq_val, index=pd.DatetimeIndex(eq_idx)),
            pd.DataFrame(trades), pd.DataFrame(skipped), counts)


def metrics(eq):
    if len(eq) < 2:
        return {}
    yrs = len(eq) / TRADING_DAYS
    dr = eq.pct_change().dropna()
    dd = eq / eq.cummax() - 1
    sharpe = dr.mean() / dr.std() * np.sqrt(TRADING_DAYS) if dr.std() else float("nan")
    return {"總報酬": f"{(eq.iloc[-1] / eq.iloc[0] - 1) * 100:+.1f}%",
            "年化": f"{((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100:+.1f}%",
            "年化波動": f"{dr.std() * np.sqrt(TRADING_DAYS) * 100:.1f}%",
            "Sharpe": f"{sharpe:.2f}", "最大回撤": f"{dd.min() * 100:.1f}%"}


def bench_0050(piv_full, eq_index):
    """0050 買進持有（前復權，含配息）。`load` 已把 price_adjustment 套上去。"""
    if "0050" not in piv_full["close"].columns:
        return None
    s = piv_full["close"]["0050"].reindex(eq_index).ffill().dropna()
    return s / s.iloc[0] if len(s) else None


GRID = {"d5": [0.03, 0.05, 0.08], "yoy": [10.0, 20.0, 30.0], "vol_hi": [2.0, 3.0]}


def walk_forward_signals(close, f, yoy, ret, h, start, end, folds, vol_lo):
    """擴張窗選參：每折只用該折之前的事件均值挑門檻，回傳拼好的樣本外訊號面板。"""
    idx = close.index
    win = idx[(idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))]
    edges = [win[int(len(win) * k / folds)] for k in range(folds)] + [win[-1]]
    combos = [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())]
    cache = {tuple(c.values()): apply_thresholds(close, f, yoy, c["d5"], vol_lo,
                                                c["vol_hi"], c["yoy"]) for c in combos}
    out = pd.DataFrame(False, index=close.index, columns=close.columns)
    picks = []
    for k in range(1, folds):                       # 第 0 折只當訓練期，不交易
        tr_end, fo_end = edges[k], edges[k + 1]
        # 訓練用的訊號還要再往前砍 h 個交易日：訊號的報酬要 h 天後才知道，用到 `tr_end`
        # 當天的訊號等於在選參時偷看了樣本外前 h 天的價格。
        cut = idx[max(0, int(idx.get_loc(tr_end)) - h)]
        best, best_m, best_n = None, -np.inf, 0
        for c in combos:
            s = cache[tuple(c.values())].copy()
            s.loc[:pd.Timestamp(start)] = False
            s.loc[cut:] = False                     # 只用報酬已實現的訊號
            _, ev = to_events(s, ret, h, {})
            if len(ev) < 20:                        # 樣本太小的門檻組不可信
                continue
            if ev["r"].mean() > best_m:
                best, best_m, best_n = c, float(ev["r"].mean()), len(ev)
        if best is None:
            continue
        sel = cache[tuple(best.values())]
        seg = (out.index > tr_end) & (out.index <= fo_end)
        out.loc[seg] = sel.loc[seg]
        picks.append({"折": k, "訓練截止": tr_end.date(), "樣本外至": fo_end.date(),
                      "選中門檻": f"d5≥{best['d5']:.0%} yoy≥{best['yoy']:.0f} "
                                  f"量比≤{best['vol_hi']}",
                      "訓練事件": best_n, "訓練均值": f"{best_m * 100:+.2f}%"})
    return out, pd.DataFrame(picks), edges[1]


def main(argv=None):
    p = argparse.ArgumentParser(description="訊號的組合層驗證（資金競爭 + 走前驗證）")
    p.add_argument("--start", default="2020-01-01")
    p.add_argument("--end", default="2026-07-24")
    p.add_argument("--horizon", type=int, default=60, help="固定持有交易日數")
    p.add_argument("--slots", type=int, default=5, help="同時最多持有幾檔（等權）")
    p.add_argument("--min-turnover", type=float, default=2.0)
    p.add_argument("--d5", type=float, default=0.05)
    p.add_argument("--vol-lo", type=float, default=1.3)
    p.add_argument("--vol-hi", type=float, default=2.0)
    p.add_argument("--yoy", type=float, default=20.0)
    p.add_argument("--rank", default="score", choices=["score", "random"],
                   help="同日候選多於空位時的優先序")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--seeds", type=int, default=1,
                   help="`--rank random` 重跑幾個 seed。只比一個亂序 seed 是在比雜訊——"
                        "百餘筆成交的年化差異幾十 pp 都可能只是抽樣")
    p.add_argument("--rank-test", type=int, default=0, metavar="N",
                   help="排序檢定：score 跑一次 + 亂序跑 N 次，報 score 在亂序分布裡的"
                        "百分位。N 太小連 permutation p 值的下限都不夠（10 次的下限是 1/11）")
    p.add_argument("--delisting", default="last", choices=["last", "zero"])
    p.add_argument("--include-tib", action="store_true",
                   help="把創新板（名稱後綴 -創）放回池子。**預設排除**，因為 live 的 "
                        "`screen_tw.funnel` 就排除它（一般帳戶要簽風險預告書並符合資格條件）"
                        "——不排除的話組合會買進 live 永遠不會買的標的，而全庫唯一過得了流動性"
                        "門檻的 7610 是 10 倍股，單它一檔就能把 Sharpe 撐高 0.2")
    p.add_argument("--skip-limit-gap", action="store_true",
                   help=f"跳過開盤跳空 ≥{LIMIT_GAP:.1%} 的進場（貼近漲停，開盤有一筆成交不代表"
                        f"整個部位吃得到那個價）。用來看 headline 對這個假設有多敏感")
    p.add_argument("--walk-forward", action="store_true",
                   help="擴張窗選參，只計樣本外")
    p.add_argument("--folds", type=int, default=5)
    a = p.parse_args(argv)

    eng = get_engine()
    piv_full, rv, info = load(eng, a.start, a.end)
    close_full = piv_full["close"]
    keep = [s for s in close_full.columns
            if len(s) == 4 and s.isdigit() and not s.startswith(("00", "91"))]
    if not a.include_tib:
        # 用**今天**的名稱後綴判定歷史板別是近似（PIT 板別表還沒建），但方向是保守的：
        # 創新板從掛牌就在創新板，且不排除等於讓組合買進 live 不會買的標的。
        tib = {s for s, n in zip(info["stock_id"], info["name"])
               if str(n).endswith("-創")}
        keep = [s for s in keep if s not in tib]
    piv = {k: v[keep] for k, v in piv_full.items()}
    close = piv["close"]
    yoy = pit_revenue_panel(rv, close.index, close.columns)
    f = factors(piv, a.min_turnover * 1e8)
    ret, _ = forward_returns(piv, a.horizon, a.delisting)

    start = a.start
    if a.walk_forward:
        sig, picks, start = walk_forward_signals(close, f, yoy, ret, a.horizon,
                                                 a.start, a.end, a.folds, a.vol_lo)
        print("=== 擴張窗選參（第 0 折只訓練不交易）===")
        print(picks.to_string(index=False) if len(picks) else "（沒有任何折有足夠事件）")
        print()
    else:
        sig = apply_thresholds(close, f, yoy, a.d5, a.vol_lo, a.vol_hi, a.yoy)
        sig.loc[:pd.Timestamp(a.start)] = False

    scores = daily_scores(sig, f, yoy)
    run = dict(rank=a.rank, seed=a.seed, delisting=a.delisting,
               skip_limit_gap=a.skip_limit_gap, scores=scores)
    eq, tr, sk, cn = simulate(piv, sig, f, yoy, a.horizon, a.slots, start, a.end, **run)
    n_sig = int(sig.loc[eq.index[0]:eq.index[-1]].sum().sum())
    print(f"樣本 {eq.index[0].date()} ~ {eq.index[-1].date()}　池 {len(keep)} 檔"
          f"{'（含創新板）' if a.include_tib else '（排除創新板）'}　"
          f"持有 {a.horizon} 交易日　空位 {a.slots}　排序={a.rank}　"
          f"成本 {COST * 100:.1f}%（買賣各 {SIDE_COST * 100:.2f}%）")
    print(f"名目訊號 {n_sig:,} 筆 → 進場 {cn['entries']} 次（已平倉 {cn['closed']}、"
          f"期末仍持有 {cn['open_at_end']}）；訊號落在已持股 {cn['already_held']} 筆、"
          f"無 T+1 開盤價 {cn['no_open']} 筆"
          + (f"、貼近漲停跳過 {cn['limit_gap']} 筆" if a.skip_limit_gap else "")
          + f"；因空位不足放棄 {len(sk):,} 筆")

    if a.rank_test:
        base = float(eq.iloc[-1] / eq.iloc[0])
        rs = []
        for k in range(a.rank_test):
            e2, t2, _, _ = simulate(piv, sig, f, yoy, a.horizon, a.slots, start, a.end,
                                    rank="random", seed=a.seed + k,
                                    delisting=a.delisting,
                                    skip_limit_gap=a.skip_limit_gap, scores=scores)
            rs.append(float(e2.iloc[-1] / e2.iloc[0]))
        rs = np.array(rs)
        pct = float((rs < base).mean() * 100)
        # permutation p 值的下限是 1/(N+1)：N 太小的話「沒有優勢」與「檢定沒有效力」分不開
        print(f"\n=== 排序檢定：score vs {a.rank_test} 次亂序 ===")
        print(f"score 期末權益 {base:.2f}x；亂序中位 {np.median(rs):.2f}x、"
              f"5~95 百分位 {np.percentile(rs, 5):.2f}x ~ {np.percentile(rs, 95):.2f}x")
        print(f"score 落在亂序分布的第 {pct:.0f} 百分位（單尾 permutation p = "
              f"{(1 + (rs >= base).sum()) / (a.rank_test + 1):.3f}，下限 "
              f"{1 / (a.rank_test + 1):.3f}）")
    elif a.seeds > 1:
        rs = []
        for k in range(a.seeds):
            e2, t2, _, _ = simulate(piv, sig, f, yoy, a.horizon, a.slots, start, a.end,
                                    rank=a.rank, seed=a.seed + k,
                                    delisting=a.delisting,
                                    skip_limit_gap=a.skip_limit_gap, scores=scores)
            rs.append({"seed": a.seed + k, **metrics(e2),
                       "成交": len(t2), "均值": f"{t2['r'].mean() * 100:+.2f}%"})
        print(f"\n=== {a.rank} 排序的 {a.seeds} 個 seed ===")
        print(pd.DataFrame(rs).to_string(index=False))

    rows = {"組合": metrics(eq)}
    b = bench_0050(piv_full, eq.index)
    if b is not None:
        rows["0050 買進持有"] = metrics(b)
    print("\n" + pd.DataFrame(rows).T.to_string())

    if len(tr):
        print(f"\n成交筆數 {len(tr)}　均值 {tr['r'].mean() * 100:+.2f}%　"
              f"中位 {tr['r'].median() * 100:+.2f}%　勝率 {(tr['r'] > 0).mean() * 100:.1f}%　"
              f"最差 {tr['r'].min() * 100:+.0f}%　下市結算 {int(tr['delisted'].sum())} 筆")
        print(f"報酬 >100% 的成交 {int((tr['r'] > 1).sum())} 筆，拿掉後均值 "
              f"{tr[tr['r'] <= 1]['r'].mean() * 100:+.2f}%")

    # === 排擠成本：沒買到的比買到的好嗎 ===
    if len(sk):
        di = {d: i for i, d in enumerate(close.index)}

        def _r(pairs):
            v = [ret.at[d, s] for d, s in pairs
                 if s in ret.columns and d in ret.index and pd.notna(ret.at[d, s])]
            return pd.Series(v, dtype=float)

        def _dedupe(pairs):
            """同檔 h 個交易日內只算一個事件——買到的一側因為持有 h 日天然接近去重，
            沒買到的一側每天都會重複追加，不去重就是拿名目訊號比事件，口徑不同。"""
            out, last = [], {}
            for d, s in sorted(pairs, key=lambda x: (x[1], x[0])):
                ti = di.get(d)
                if ti is None:
                    continue
                if s not in last or ti - last[s] > a.horizon:
                    out.append((d, s))
                    last[s] = ti
            return out

        # 成交筆的訊號日 = 進場日的前一個交易日
        took_p = [(close.index[di[d] - 1], s)
                  for d, s in zip(tr["entry_date"], tr["stock_id"])] if len(tr) else []
        miss_p = list(zip(sk["date"], sk["stock_id"]))
        took = _r(took_p) - COST
        miss_raw = _r(miss_p) - COST
        miss = _r(_dedupe(miss_p)) - COST
        print(f"\n=== 排擠成本（同一組前瞻報酬、扣 {COST * 100:.1f}%）===")
        print(f"買到的 {len(took)} 筆均值 {took.mean() * 100:+.2f}%　"
              f"P(≥30%) {(took >= .3).mean() * 100:.1f}%")
        print(f"沒買到的（事件去重）{len(miss)} 個均值 {miss.mean() * 100:+.2f}%　"
              f"P(≥30%) {(miss >= .3).mean() * 100:.1f}%")
        print(f"沒買到的（名目訊號，口徑不可比，僅供對照）{len(miss_raw)} 筆均值 "
              f"{miss_raw.mean() * 100:+.2f}%")
        print(f"**排擠成本 {(miss.mean() - took.mean()) * 100:+.2f}pp**"
              f"（>0 = 排序把好的擠掉了；用去重後的那一列）")

    print("\n=== 逐年（組合權益）===")
    yr = eq.resample("YE").last()
    yr = pd.concat([eq.iloc[:1], yr]).pct_change().dropna() * 100
    out = pd.DataFrame({"組合%": yr.round(1)})
    if b is not None:
        yb = pd.concat([b.iloc[:1], b.resample("YE").last()]).pct_change().dropna() * 100
        out["0050%"] = yb.round(1).reindex(out.index)
    out.index = [d.year for d in out.index]
    print(out.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
