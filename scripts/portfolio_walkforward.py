#!/usr/bin/env python3
"""把訊號的前瞻分布壓成「有限資金真能拿到的那條權益曲線」。

`measure_signal_forward.py` 證明的是**邊際**期望值：每個事件單獨看均值為正。它刻意不做部位
模擬，所以答不出配置真錢前的最後一關——**前 12% 的事件貢獻總報酬 105%，這些右尾能不能被
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
    uv run --env-file .env python scripts/portfolio_walkforward.py --weighting invvol
"""

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from market_data.adjust import is_common_stock  # noqa: E402
from market_data.db import get_engine  # noqa: E402
from measure_signal_forward import (  # noqa: E402
    HIT_THRESHOLD, apply_thresholds, factors, forward_returns, load, paired_block_bootstrap,
    pit_revenue_panel, to_events, volatility20,
)

from tw_trade_costs import (  # noqa: E402
    ETF_TRANSACTION_TAX_RATE,
    TRADING_DAYS_PER_YEAR as TRADING_DAYS,
    affordable_shares,
    buy_cash_outflow,
    buy_fill_price,
    round_trip_return,
    sell_cash_inflow,
    sell_fill_price,
)
DEFAULT_CAPITAL = 1_000_000.0


DEAD_DAYS = 20            # 連續無報價超過這麼多交易日才當下市（PIT，不看未來）
LIMIT_GAP = 0.095         # 開盤跳空達此幅度視為貼近漲停，成交量無法證明可全額成交
# 反波動加權（`--weighting`，事先登記於 docs/research/2026-10-26-exp-invvol-pb.md 第 1 節）
WEIGHT_CLIP = (0.5, 2.0)  # 單檔部位相對等權份額的倍數上下限
WEIGHT_MIN_REF = 20       # 擴張窗參考波動至少要累積幾個訊號格，之前一律等權


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


def invvol_weights(sig, vol, ref="expanding", liquid=None, clip=WEIGHT_CLIP,
                   min_ref=WEIGHT_MIN_REF):
    """訊號格的部位倍數 ``{(訊號日, stock_id): w}``，w = clip(參考波動 / 該股 vol20)。

    只用訊號日（含）以前看得到的資料：

    - ``ref="expanding"``：參考波動 = 起始以來**所有訊號格**（含當日）vol20 的中位數。
      候選池整體波動升高時全部部位一起縮小、降低時一起放大——**這是隱性的擇時**，不是
      新的選股因子；累積不到 ``min_ref`` 格之前一律 1.0。
    - ``ref="xs"``：參考波動 = 當日流動池（``liquid``）vol20 的橫斷面中位數，只看「比同日
      市場貴／便宜多少波動」。突破候選的波動多半高於市場中位，因此平均倍數會 < 1。

    vol20 缺值（新上市不足 20 日）或參考值缺值時給 1.0（等權）。
    """
    lo, hi = clip
    out = {}
    hist = []
    for d in sig.index[sig.any(axis=1)]:
        cols = list(sig.columns[sig.loc[d].to_numpy()])
        v = vol.loc[d, cols]
        if ref == "expanding":
            hist.extend(float(x) for x in v.dropna())
            r = float(np.median(hist)) if len(hist) >= min_ref else np.nan
        elif ref == "xs":
            row = vol.loc[d]
            if liquid is not None:
                row = row[liquid.loc[d].fillna(False).astype(bool)]
            r = float(row.median()) if row.notna().any() else np.nan
        else:
            raise ValueError(f"unknown ref {ref!r}")
        for s_, x in v.items():
            if pd.isna(x) or x <= 0 or pd.isna(r):
                out[(d, s_)] = 1.0
            else:
                out[(d, s_)] = float(min(hi, max(lo, r / x)))
    return out


def ma_line(close, window):
    """出場用的收盤均線。面板不 ffill：缺價日讓視窗內出現 NaN → 均線 NaN → 當天不判定。"""
    return close.rolling(window).mean()


def update_break_streak(streak, close_px, ma_px):
    """均線跌破的連續計數（單一部位、單一交易日）。

    收盤或均線缺值（停牌、視窗不足）**不計數也不歸零**；收盤 < 均線加一；收盤 ≥ 均線歸零。
    """
    if pd.isna(close_px) or pd.isna(ma_px):
        return streak
    return streak + 1 if close_px < ma_px else 0


def simulate(piv, sig, f, yoy, h, slots, start, end, rank="score", seed=42,
             delisting="last", skip_limit_gap=False, scores=None,
             capital=DEFAULT_CAPITAL, fee_discount=1.0, weights=None,
             exit_ma=None, time_cap=True):
    """T+1 開盤買、持有 h 個交易日後收盤賣，同時最多 `slots` 檔、等權。

    ``weights``（``invvol_weights`` 的輸出）給定時，每筆的預算改成「等權份額 × 倍數」，
    仍受當下現金限制；``None`` 即原本的等權，結果逐位不變。

    ``exit_ma=(均線面板, sustain)`` 時另加均線出場（G3-25 探索，見
    docs/research/2026-10-28-explore-reversal-ma25.md）：收盤連續 ``sustain`` 個有效交易日
    低於均線 → **隔日開盤**賣（不用同一根收盤決策又成交）；隔日無開盤價就順延。
    ``time_cap=False`` 拿掉 h 日到期，只剩均線出場。``exit_ma=None`` 時結果逐位不變。

    現金流時序刻意保守：**今天開盤的買進只能用昨天收盤前就有的現金**（今天賣出的錢要到
    明天開盤才能用），否則就是用未實現的賣出款買進。

    停牌與下市一律**不看未來**：出場日無報價就順延到下一個可成交日；連續 `DEAD_DAYS` 個
    交易日沒有報價才視為下市並結算（舊版用「這一列或之後還有沒有成交價」判定，那是前視——
    會在第一個缺價日就「知道」樣本內不再有報價而提前釋放資金）。樣本結束仍未成交的部位
    列為 right-censored、不計入成交統計；為了和期末賣出 0050 的基準對等，權益曲線最後一點
    使用「以最後已知收盤全部清算」的淨值，扣掉賣出手續費與證交稅。
    """
    close, open_ = piv["close"], piv["open"]
    dates = close.index
    lastc = close.ffill()
    if scores is None and rank == "score":
        scores = daily_scores(sig, f, yoy)
    i0 = int(dates.searchsorted(pd.Timestamp(start)))
    i1 = int(dates.searchsorted(pd.Timestamp(end), side="right"))
    rng = np.random.default_rng(seed)

    cash, pos = float(capital), {}
    eq_idx, eq_val, trades, skipped = [], [], [], []
    counts = {"entries": 0, "already_held": 0, "no_open": 0, "limit_gap": 0}
    prev_equity = float(capital)
    invested = []
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
                w = 1.0 if weights is None else weights.get((prev, s), 1.0)
                alloc = min(cash, prev_equity / slots * w)
                px = buy_fill_price(float(open_.at[d, s]))
                qty = affordable_shares(alloc, px, fee_discount=fee_discount)
                cost = buy_cash_outflow(qty, px, fee_discount=fee_discount)
                if qty <= 0 or cost > cash + 1e-8:
                    continue
                cash -= cost
                counts["entries"] += 1
                pos[s] = {"qty": qty,
                          "exit_i": i + h - 1 if (time_cap or exit_ma is None) else np.inf,
                          "entry": px, "entry_date": d, "cost": cost, "stale": 0,
                          "streak": 0, "ma_exit": False}
        # 2) 出場：到期且當日可成交；停牌則順延，連續 DEAD_DAYS 無報價才判下市。
        #    均線出場是前一天收盤決定的，今天開盤成交（賣出款同樣要明天開盤才能用）。
        for s, p in list(pos.items()):
            quoted = pd.notna(close.at[d, s])
            p["stale"] = 0 if quoted else p["stale"] + 1
            dead = p["stale"] >= DEAD_DAYS
            op = open_.at[d, s]
            ma_fill = p["ma_exit"] and pd.notna(op) and op > 0
            if not dead and not ma_fill and (p["exit_i"] > i or not quoted):
                if exit_ma is not None and not p["ma_exit"]:
                    p["streak"] = update_break_streak(p["streak"], close.at[d, s],
                                                      exit_ma[0].at[d, s])
                    p["ma_exit"] = p["streak"] >= exit_ma[1]
                continue
            pos.pop(s)
            if ma_fill and not dead:
                px = float(op)
            else:
                px = 0.0 if (dead and delisting == "zero") else float(lastc.at[d, s])
            fill = sell_fill_price(px)
            proceeds = sell_cash_inflow(p["qty"], fill, fee_discount=fee_discount)
            cash += proceeds
            trades.append({"stock_id": s, "entry_date": p["entry_date"], "exit_date": d,
                           "entry": p["entry"], "exit": fill, "delisted": dead,
                           "deferred": (not ma_fill and np.isfinite(p["exit_i"])
                                        and d != dates[min(int(p["exit_i"]), len(dates) - 1)]),
                           "exit_reason": ("delisted" if dead else
                                           "ma" if ma_fill else "time"),
                           "cost": p["cost"], "r": proceeds / p["cost"] - 1})
        # 3) 收盤標記
        prev_equity = cash + sum(p["qty"] * float(lastc.at[d, s]) for s, p in pos.items())
        eq_idx.append(d)
        eq_val.append(prev_equity)
        invested.append(1 - cash / prev_equity if prev_equity > 0 else 0.0)
    counts["closed"] = len(trades)
    counts["invested_frac"] = float(np.mean(invested)) if invested else 0.0
    counts["open_at_end"] = len(pos)
    if eq_val and pos:
        terminal_day = eq_idx[-1]
        terminal = cash
        for stock_id, position in pos.items():
            terminal_price = lastc.at[terminal_day, stock_id]
            if pd.isna(terminal_price):
                terminal_price = 0.0
            terminal += sell_cash_inflow(
                position["qty"], sell_fill_price(float(terminal_price)),
                fee_discount=fee_discount)
        eq_val[-1] = terminal
    return (pd.Series(eq_val, index=pd.DatetimeIndex(eq_idx)) / float(capital),
            pd.DataFrame(trades), pd.DataFrame(skipped), counts)


def metrics(eq):
    """Metrics for an end-of-session equity curve normalized by original capital."""
    if len(eq) < 2:
        return {}
    yrs = len(eq) / TRADING_DAYS
    # The first point is already after that session's trades. Prepending original
    # capital keeps an entry commission on day one from disappearing in eq/eq[0].
    curve = pd.Series(np.r_[1.0, eq.astype(float).to_numpy()])
    dr = curve.pct_change().dropna()
    dd = curve / curve.cummax() - 1
    sharpe = dr.mean() / dr.std() * np.sqrt(TRADING_DAYS) if dr.std() else float("nan")
    return {"總報酬": f"{(eq.iloc[-1] - 1) * 100:+.1f}%",
            "年化": f"{(eq.iloc[-1] ** (1 / yrs) - 1) * 100:+.1f}%",
            "年化波動": f"{dr.std() * np.sqrt(TRADING_DAYS) * 100:.1f}%",
            "Sharpe": f"{sharpe:.2f}", "最大回撤": f"{dd.min() * 100:.1f}%"}


def yearly_returns(curve):
    """逐年報酬（%）。第一年的分母是**原始本金 1.0**，不是第一列權益。

    用第一列當分母會把首日進場成本從第一年抵掉——`metrics()` 已經是本金口徑，這裡不跟上
    就會兩張表對不起來。
    """
    yearly = curve.resample("YE").last()
    return (yearly / yearly.shift(1).fillna(1.0) - 1) * 100


def bench_0050(piv_full, eq_index, *, capital=DEFAULT_CAPITAL, fee_discount=1.0):
    """0050 買進持有，买卖两端使用和策略相同的現金流成本。

    唯一刻意不同的是證交稅：0050 是 ETF，賣方稅率 **0.1%**（個股是 0.3%）。沿用個股稅率
    會高估基準成本，而本策略的結論是「風險調整後輸給 0050」——那個偏誤方向對策略有利。
    """
    if "0050" not in piv_full["close"].columns:
        return None
    s = piv_full["close"]["0050"].reindex(eq_index).ffill().dropna()
    if not len(s):
        return None
    entry = buy_fill_price(s.iloc[0])
    shares = affordable_shares(capital, entry, fee_discount=fee_discount)
    paid = buy_cash_outflow(shares, entry, fee_discount=fee_discount)
    cash = float(capital) - paid
    value = cash + shares * s
    value.iloc[-1] = cash + sell_cash_inflow(
        shares, sell_fill_price(s.iloc[-1]), fee_discount=fee_discount,
        tax_rate=ETF_TRANSACTION_TAX_RATE)
    return value / float(capital)


GRID = {"d5": [0.03, 0.05, 0.08], "yoy": [10.0, 20.0, 30.0], "vol_hi": [2.0, 3.0]}


def walk_forward_signals(close, f, yoy, ret, h, start, end, folds, vol_lo, *,
                         entry_notional=200_000.0, fee_discount=1.0):
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
            _, ev = to_events(s, ret, h, {}, entry_notional=entry_notional,
                              fee_discount=fee_discount)
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
                      "選中門檻": (
                          f"d5≥{best['d5']:.0%} yoy≥{best['yoy']:.0f} "
                          f"量比≤{best['vol_hi']}"),
                      "訓練事件": best_n, "訓練均值": f"{best_m * 100:+.2f}%"})
    return out, pd.DataFrame(picks), edges[1]


def daily_returns(eq):
    """權益曲線的逐日報酬；第一天以原始本金 1.0 為前值（與 `metrics()` 同口徑）。"""
    curve = pd.Series(np.r_[1.0, eq.astype(float).to_numpy()])
    return pd.Series(curve.pct_change().to_numpy()[1:], index=eq.index)


def weighted_trade_stats(tr):
    """依投入成本加權的成交均值與 P(≥30%)。

    反波動加權不只改每筆的份量，也可能改成交集合：倍數 > 1 的部位先吃掉現金，同日排在
    後面的候選會因 no_cash 被擠掉。兩臂比較時要一併看成交筆數 ``n``。
    """
    if not len(tr):
        return {"n": 0, "mean": np.nan, "hit": np.nan}
    w = tr["cost"].astype(float)
    r = tr["r"].astype(float)
    return {"n": len(tr), "mean": float((w * r).sum() / w.sum()),
            "hit": float((w * (r >= HIT_THRESHOLD)).sum() / w.sum())}


def daily_diff_ci(eq_a, eq_b, block, n_boot, seed):
    """兩條權益曲線的逐日報酬差（a − b）與交易日區塊 circular bootstrap 95% 區間。"""
    diff = (daily_returns(eq_a) - daily_returns(eq_b)).dropna()
    ci = paired_block_bootstrap(pd.DataFrame({"date": np.arange(len(diff)), "diff": diff.to_numpy()}),
                                np.arange(len(diff)), n=n_boot, block=block, seed=seed)
    return diff, ci


def compare_weighting(eq_w, tr_w, cn_w, eq_e, tr_e, cn_e, label, block, n_boot, seed):
    """反波動加權 vs 等權（同訊號、同排序）。逐日報酬差以交易日區塊做 circular bootstrap。"""
    print(f"\n=== 部位加權比較：{label} − 等權（同訊號、同排序）===")
    rows = {"等權": {**metrics(eq_e), "平均持股比重": f"{cn_e['invested_frac'] * 100:.1f}%"},
            label: {**metrics(eq_w), "平均持股比重": f"{cn_w['invested_frac'] * 100:.1f}%"}}
    print(pd.DataFrame(rows).T.to_string())
    for name, tr in (("等權", tr_e), (label, tr_w)):
        st = weighted_trade_stats(tr)
        print(f"{name}：成交 {st['n']} 筆　成本加權均值 {st['mean'] * 100:+.2f}%　"
              f"成本加權 P(≥30%) {st['hit'] * 100:.1f}%")
    diff, ci = daily_diff_ci(eq_w, eq_e, block, n_boot, seed)
    print(f"逐日報酬差均值 {diff.mean() * 1e4:+.2f}bp／日（年化約 "
          f"{diff.mean() * TRADING_DAYS * 100:+.2f}pp）")
    if ci is None:
        print("逐日報酬差的區塊 bootstrap：inconclusive（資料不足）")
    else:
        print(f"逐日報酬差 95% 區間（block={block}、{n_boot} 次、seed={seed}）: "
              f"{ci[0] * 1e4:+.2f}bp ~ {ci[1] * 1e4:+.2f}bp／日")
    return diff, ci


def pool_codes(columns, info, include_tib=False):
    """組合池：四位數普通股，預設排除創新板（理由見模組說明與 `--include-tib`）。"""
    keep = [s for s in columns if is_common_stock(s)]
    if not include_tib:
        # 用**今天**的名稱後綴判定歷史板別是近似（PIT 板別表還沒建），但方向是保守的：
        # 創新板從掛牌就在創新板，且不排除等於讓組合買進 live 不會買的標的。
        tib = {s for s, n in zip(info["stock_id"], info["name"])
               if str(n).endswith("-創")}
        keep = [s for s in keep if s not in tib]
    return keep


def build_parser():
    p = argparse.ArgumentParser(description="訊號的組合層驗證（資金競爭 + 走前驗證）")
    p.add_argument("--start", default="2020-01-01")
    p.add_argument("--capital", type=float, default=DEFAULT_CAPITAL,
                   help="組合起始本金（元），用來正確套最低手續費")
    p.add_argument("--fee-discount", type=float, default=1.0,
                   help="券商手續費折數乘數，例如六折填 0.6")
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
                   help=f"跳過開盤跳空 ≥{LIMIT_GAP * 100:.1f}%% 的進場（貼近漲停，開盤有一筆成交不代表"
                        "整個部位吃得到那個價）。用來看 headline 對這個假設有多敏感")
    p.add_argument("--walk-forward", action="store_true",
                   help="擴張窗選參，只計樣本外")
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--include-otc-revenue", action="store_true",
                   help="月營收放入上櫃（預設只用上市口徑，與 screen_tw 預設相同；放入後是另一個池子，數字不可與既有基準比較）")
    p.add_argument("--weighting", default="equal", choices=["equal", "invvol", "invvol-xs"],
                   help="部位加權：equal＝等權（預設）；invvol＝以訊號格擴張窗中位 vol20 為參考的"
                        "反波動倍數（含隱性擇時）；invvol-xs＝以當日流動池中位 vol20 為參考。"
                        "非等權時另跑一次等權並印比較")
    p.add_argument("--exit-ma", type=int, default=0, metavar="N",
                   help="另加均線出場（探索性，G3-25）：收盤連續 --exit-sustain 日低於 N 日均線就"
                        "隔日開盤賣；0＝關（預設，只有固定持有）")
    p.add_argument("--exit-sustain", type=int, default=3,
                   help="均線出場要連續幾個有效交易日收在均線下")
    p.add_argument("--no-time-cap", action="store_true",
                   help="搭配 --exit-ma：拿掉 --horizon 到期，只剩均線出場")
    p.add_argument("--bootstrap", type=int, default=2000,
                   help="加權比較的逐日報酬差區塊 bootstrap 次數（block = 持有期）")
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)

    if a.capital <= 0:
        p.error("--capital must be positive")
    if a.fee_discount < 0:
        p.error("--fee-discount must be non-negative")
    if a.slots < 1:
        p.error("--slots must be positive")
    if a.exit_ma < 0 or a.exit_sustain < 1:
        p.error("--exit-ma must be >= 0 and --exit-sustain >= 1")
    if a.no_time_cap and not a.exit_ma:
        p.error("--no-time-cap requires --exit-ma")

    eng = get_engine()
    piv_full, rv, info = load(eng, a.start, a.end, a.include_otc_revenue)
    close_full = piv_full["close"]
    keep = pool_codes(close_full.columns, info, a.include_tib)
    piv = {k: v[keep] for k, v in piv_full.items()}
    close = piv["close"]
    yoy = pit_revenue_panel(rv, close.index, close.columns)
    f = factors(piv, a.min_turnover * 1e8)
    ret, _ = forward_returns(piv, a.horizon, a.delisting)

    start = a.start
    if a.walk_forward:
        sig, picks, start = walk_forward_signals(close, f, yoy, ret, a.horizon,
                                                 a.start, a.end, a.folds, a.vol_lo,
                                                 entry_notional=a.capital / a.slots,
                                                 fee_discount=a.fee_discount)
        print("=== 擴張窗選參（第 0 折只訓練不交易）===")
        print(picks.to_string(index=False) if len(picks) else "（沒有任何折有足夠事件）")
        print()
    else:
        sig = apply_thresholds(close, f, yoy, a.d5, a.vol_lo, a.vol_hi, a.yoy)
        sig.loc[:pd.Timestamp(a.start)] = False

    scores = daily_scores(sig, f, yoy)
    weights = None
    if a.weighting != "equal":
        weights = invvol_weights(sig, volatility20(close),
                                 ref="expanding" if a.weighting == "invvol" else "xs",
                                 liquid=f["liquid"])
    exit_ma = (ma_line(close, a.exit_ma), a.exit_sustain) if a.exit_ma else None
    run = dict(rank=a.rank, seed=a.seed, delisting=a.delisting,
               skip_limit_gap=a.skip_limit_gap, scores=scores,
               capital=a.capital, fee_discount=a.fee_discount, weights=weights,
               exit_ma=exit_ma, time_cap=not a.no_time_cap)
    eq, tr, sk, cn = simulate(piv, sig, f, yoy, a.horizon, a.slots, start, a.end, **run)
    n_sig = int(sig.loc[eq.index[0]:eq.index[-1]].sum().sum())
    flat_cost = -round_trip_return(1.0, 1.0, entry_notional=a.capital / a.slots,
                                   fee_discount=a.fee_discount)
    print(f"樣本 {eq.index[0].date()} ~ {eq.index[-1].date()}　池 {len(keep)} 檔"
          f"{'（含創新板）' if a.include_tib else '（排除創新板）'}　"
          f"持有 {a.horizon} 交易日"
          + (f"（另加 {a.exit_ma}MA 跌破 sustain {a.exit_sustain} 隔日開盤出場"
             + ("、無到期上限" if a.no_time_cap else "") + "）" if a.exit_ma else "")
          + f"　空位 {a.slots}　排序={a.rank}　加權={a.weighting}　"
          f"本金 {a.capital:,.0f} 元　平盤來回成本約 {flat_cost * 100:.3f}%")
    print(f"名目訊號 {n_sig:,} 筆 → 進場 {cn['entries']} 次（已平倉 {cn['closed']}、"
          f"期末仍持有 {cn['open_at_end']}）；訊號落在已持股 {cn['already_held']} 筆、"
          f"無 T+1 開盤價 {cn['no_open']} 筆"
          + (f"、貼近漲停跳過 {cn['limit_gap']} 筆" if a.skip_limit_gap else "")
          + f"；因空位不足放棄 {len(sk):,} 筆")

    if a.rank_test:
        # eq 已用原始本金正規化，所以期末權益就是總倍數；除以 eq[0] 會把首日進場成本
        # 從分母裡抵掉（`metrics()` 同一個口徑）。
        base = float(eq.iloc[-1])
        rs = []
        for k in range(a.rank_test):
            e2, t2, _, _ = simulate(piv, sig, f, yoy, a.horizon, a.slots, start, a.end,
                                    rank="random", seed=a.seed + k,
                                    delisting=a.delisting,
                                    skip_limit_gap=a.skip_limit_gap, scores=scores,
                                    capital=a.capital, fee_discount=a.fee_discount,
                                    weights=weights, exit_ma=exit_ma,
                                    time_cap=not a.no_time_cap)
            rs.append(float(e2.iloc[-1]))
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
                                    skip_limit_gap=a.skip_limit_gap, scores=scores,
                                    capital=a.capital, fee_discount=a.fee_discount,
                                    weights=weights, exit_ma=exit_ma,
                                    time_cap=not a.no_time_cap)
            rs.append({"seed": a.seed + k, **metrics(e2),
                       "成交": len(t2), "均值": f"{t2['r'].mean() * 100:+.2f}%"})
        print(f"\n=== {a.rank} 排序的 {a.seeds} 個 seed ===")
        print(pd.DataFrame(rs).to_string(index=False))

    rows = {"組合": metrics(eq)}
    b = bench_0050(piv_full, eq.index, capital=a.capital,
                   fee_discount=a.fee_discount)
    if b is not None:
        rows["0050 買進持有"] = metrics(b)
    print("\n" + pd.DataFrame(rows).T.to_string())

    if weights is not None:
        eq_e, tr_e, _, cn_e = simulate(piv, sig, f, yoy, a.horizon, a.slots, start, a.end,
                                       **{**run, "weights": None})
        compare_weighting(eq, tr, cn, eq_e, tr_e, cn_e, a.weighting, a.horizon,
                          a.bootstrap, a.seed)

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

        def _net(raw):
            return raw.map(lambda r: round_trip_return(
                1.0, 1.0 + r, entry_notional=a.capital / a.slots,
                fee_discount=a.fee_discount))
        took = _net(_r(took_p))
        miss_raw = _net(_r(miss_p))
        miss = _net(_r(_dedupe(miss_p)))
        print("\n=== 排擠成本（同一組前瞻報酬、相同買賣現金流）===")
        print(f"買到的 {len(took)} 筆均值 {took.mean() * 100:+.2f}%　"
              f"P(≥30%) {(took >= .3).mean() * 100:.1f}%")
        print(f"沒買到的（事件去重）{len(miss)} 個均值 {miss.mean() * 100:+.2f}%　"
              f"P(≥30%) {(miss >= .3).mean() * 100:.1f}%")
        print(f"沒買到的（名目訊號，口徑不可比，僅供對照）{len(miss_raw)} 筆均值 "
              f"{miss_raw.mean() * 100:+.2f}%")
        print(f"**排擠成本 {(miss.mean() - took.mean()) * 100:+.2f}pp**"
              f"（>0 = 排序把好的擠掉了；用去重後的那一列）")

    print("\n=== 逐年（組合權益）===")
    out = pd.DataFrame({"組合%": yearly_returns(eq).round(1)})
    if b is not None:
        out["0050%"] = yearly_returns(b).round(1).reindex(out.index)
    out.index = [d.year for d in out.index]
    print(out.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
