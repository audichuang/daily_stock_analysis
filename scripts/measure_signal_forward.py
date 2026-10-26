#!/usr/bin/env python3
"""量測選股訊號的前瞻報酬分布（不做部位模擬）。

為什麼不用組合回測回答這個問題：回測會把答案綁在部位管理、成本、出場規則上，換一組
出場規則結論就翻。要先確認的是更前面的事——**訊號發生後的報酬分布,比同期同類股好多少**。

四個讓數字不虛胖的處理（都是獨立審查指出後補的）：

1. **宇宙用 `market.price` 判定,不用 `stock_info`**。`stock_info` 只有目前仍上市的約 1,100 檔,
   用它過濾歷史等於前視 + 存活偏誤。某檔在 D 日可投資 = 它在 D 日有價格列。
2. **下市結算**。訊號後 h 個交易日內停止交易時,`--delisting last` 用最後成交價結算,
   `zero` 假設 -100%（停牌後賣不掉的實況更接近後者）。舊版讓這些訊號變 NaN 被丟掉,
   等於把最壞的結果排除在分布外。
3. **事件級去重**。同一檔在 h 個交易日內連續觸發是**同一個事件**,不是多個樣本；
   統計一律以事件為單位。
4. **區塊 bootstrap**。事件在時間上聚集（同一波行情、同一個產業循環），IID 區間是假精度。
   以「交易日區塊」重抽,整塊保留同日橫斷面。

**已知未修的限制**（決定這份數字是上界還是可用估計）：
  - 月營收覆蓋:`crawl_monthly_report` 走的彙總報表只列目前仍在申報的公司,後來下市的
    公司歷史缺席。`cli revenue-pit` 能補回仍公開發行的部分,被吸收合併的補不回來
    （MOPS 回「不繼續公開發行」）。`--survivorship-bound` 會給補不回來那部分的上界。
  - 營收條件預設只用上市口徑（`screen_tw.exclude_otc_revenue`；量測當時上櫃全無月營收），
    `--include-otc-revenue` 是另一個池子，結果不可與既有基準比較。

用法：
    uv run --env-file .env python scripts/measure_signal_forward.py
    uv run --env-file .env python scripts/measure_signal_forward.py --delisting zero
    uv run --env-file .env python scripts/measure_signal_forward.py --survivorship-bound
    uv run --env-file .env python scripts/measure_signal_forward.py --lhr   # LHR 否決實驗
    uv run --env-file .env python scripts/measure_signal_forward.py --pb    # PB≥2 否決實驗
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_data.adjust import is_common_stock, load_factors  # noqa: E402
from market_data.db import get_engine  # noqa: E402
from market_data.revenue_deadline import apply_revenue_deadline  # noqa: E402
from screen_tw import exclude_otc_revenue  # noqa: E402
from tw_trade_costs import round_trip_return  # noqa: E402

DEFAULT_POSITION_NOTIONAL = 200_000.0
# 月營收保鮮期。**這個數字必須與 `screen_tw.REVENUE_STALE_DAYS` 相同**——量測與 live 用
# 不同的保鮮期,就是在量一個不會下單的訊號集。
REVENUE_STALE_DAYS = 45
WARMUP_DAYS = 400     # 算 60 日高與 60 日均量要的暖機
# `confidence` 錨點的命中門檻：第 h 日收盤淨報酬 ≥ +30%（tw-swing-research 的語意定義）。
HIT_THRESHOLD = 0.30
# 收盤漲／跌停判定（`--lhr` 實驗用）。與 `portfolio_walkforward.LIMIT_GAP` 同值：2015-06 起漲跌幅
# 10%，停板價由參考價算出後向下取到升降單位，實際收漲停的漲幅約落在 9.5%~10%。
LIMIT_HIT_THRESHOLD = 0.095
LHR_WINDOW = 20       # 漲停率減跌停率（LHR）的回看交易日數（約一個月）
# PB 否決實驗（`--pb`）：估值缺列時最多沿用幾個交易列；閘門＝否決後池子要留多少才值得檢定。
PB_FFILL_DAYS = 5
PB_GATE_MIN_KEPT = 300
PB_GATE_MIN_VETOED = 100


def load(engine, start, end, include_otc_revenue=False):
    hist = (pd.Timestamp(start) - pd.Timedelta(days=WARMUP_DAYS)).date()
    with engine.connect() as c:
        px = pd.read_sql(text(
            "select stock_id, date, open, high, close, volume, turnover from market.price "
            "where date between :s and :e"), c,
            params={"s": hist, "e": end}, parse_dates=["date"])
        rv = pd.read_sql(text(
            "select stock_id, revenue_month, announce_date as date, yoy from market.monthly_revenue "
            "where announce_date between :s and :e and yoy is not null"), c,
            params={"s": hist, "e": end}, parse_dates=["date", "revenue_month"])
        info = pd.read_sql(text("select stock_id, industry, name from market.stock_info"), c)
    # DB 公告日是佔位「次月 10 日」：套共用的法定期限（2020-01 展延、2026 起保險類 15 日），
    # 下游 pit_revenue_panel 的「公告日之後第一個交易日」語意不變；live 篩選不套。
    rv = apply_revenue_deadline(rv)
    if not include_otc_revenue:  # 與 live `screen_tw.load()` 同口徑，理由見 exclude_otc_revenue
        rv = exclude_otc_revenue(rv)
    for col in ("open", "high", "close", "volume", "turnover"):
        px[col] = px[col].astype(float)
    piv = {k: px.pivot(index="date", columns="stock_id", values=k).sort_index()
           for k in ("open", "high", "close", "volume", "turnover")}
    adj = load_factors(engine, piv["close"].index, piv["close"].columns)
    covered = (adj != 1.0).any().sum()
    if covered < 0.2 * adj.shape[1]:
        raise RuntimeError(f"price_adjustment 只覆蓋 {covered}/{adj.shape[1]} 檔，"
                           f"價格幾乎未還原——先跑 market_data.cli adjust")
    for k in ("open", "high", "close"):
        piv[k] = piv[k] * adj
    return piv, rv, info


def pit_revenue_panel(rv, index, columns, stale_days=REVENUE_STALE_DAYS):
    """月營收對齊到交易日，語意與 live 的 `screen_tw.load()` SQL 逐格相同：

        某交易日 D 可見的月營收 = announce_date < D 且 announce_date >= D - 45 **曆日**
        之中最新的那一筆。

    兩個容易寫錯的地方：

    - **保鮮期是曆日，不是交易列**。`ffill(limit=45)` 數的是 45 個交易列（約 63 個曆日），
      跟 live 的 `announce_date >= as_of - interval '45 days'` 不同（實測 44 個 signal cell
      不一致）。改為用公告日面板算實際天齡再遮罩。
    - **公告日常落在非交易日**（實測 28% 在週末），所以要 `merge_asof(direction="forward")`
      順延；且 `allow_exact_matches=False` 才等於 live 的嚴格 `< as_of`——週六公告在 live
      的週一就看得到，舊版「forward 到週一再 shift(1)」會晚一天變成週二。
    """
    if not len(rv):
        return pd.DataFrame(np.nan, index=index, columns=columns)
    cal = pd.DataFrame({"eff": index}).sort_values("eff")
    mp = pd.merge_asof(rv.sort_values("date"), cal, left_on="date", right_on="eff",
                       direction="forward", allow_exact_matches=False)
    mp = mp.dropna(subset=["eff"]).sort_values("date")
    # 天數換算一律走 pandas 的時間差，不要自己除 epoch 常數——本機 pandas 的 datetime 是
    # `[us]` 而非 `[ns]`，寫死 ns/日 會把公告日算成 20（而不是 20456）而讓遮罩全部失效。
    epoch = pd.Timestamp("1970-01-01")
    mp["adn"] = (mp["date"] - epoch).dt.days                         # 公告日（天）
    kw = dict(index="eff", columns="stock_id", aggfunc="last")       # 同日多筆取最新公告
    p = mp.pivot_table(values="yoy", **kw).reindex(index=index, columns=columns).ffill()
    ann = mp.pivot_table(values="adn", **kw).reindex(index=index, columns=columns).ffill()
    age = pd.Series((index - epoch).days, index=index)
    return p.where(ann.rsub(age, axis=0) <= stale_days)


def factors(piv, min_turnover):
    """訊號用到的四個因子面板。與門檻分離,讓組合模擬可以掃參數而不重算 rolling。"""
    close, high, vol, to = (piv[k] for k in ("close", "high", "volume", "turnover"))
    # **必須與 live 的 `screen_tw.compute_factors` 逐格相同**：live 是 `high.iloc[-66:-5]`
    # ＝ 61 根、視窗 t-65…t-5（排除最近 5 根 t-4…t）。舊版寫 `shift(6).rolling(55)` 是 55 根
    # t-60…t-6，多排除了一根、視窗也短 6 根——量到的不是會下單的那個訊號（實測 918→894
    # 事件、只有 859 重疊）。獨立審查指出。
    return {"liquid": to.rolling(20).mean() >= min_turnover,
            "d5": close.pct_change(5),
            "hi60_prior": high.shift(5).rolling(61).max(),
            "vol_r": vol.rolling(5).mean() / vol.rolling(60).mean()}


def limit_hit_net(close, window=LHR_WINDOW, threshold=LIMIT_HIT_THRESHOLD):
    """近 ``window`` 個交易日（含當日）收漲停天數減收跌停天數；LHR = 回傳值 / window。

    - 用**還原後**收盤的日報酬判定：除權息日的停板價以參考價（已扣權息）計算，還原價的
      日報酬才對得上；原始收盤在除權息日會出現假跌停。
    - 只看收盤（收在停板），不看盤中觸及——量測端沒有載入 low，觸及跌停無從判定，
      兩邊口徑一致才能相減。
    - 前一日沒有價格（停牌、未上市）的那天不算命中；新股上市前五日無漲跌幅限制、
      漲跌超過 10% 也會被算成命中，屬已知誤差。
    """
    chg = close.pct_change(fill_method=None)
    up = (chg >= threshold).astype(float)
    dn = (chg <= -threshold).astype(float)
    net = (up - dn).rolling(window, min_periods=window).sum()
    return net.where(close.notna())


def volatility20(close):
    """20 日日報酬標準差；定義與 `backtest_screen.py` 的 ``vol20`` 相同（研究過的單調因子）。"""
    return close.pct_change(fill_method=None).rolling(20).std()


def apply_thresholds(close, f, yoy, d5_min, vol_lo, vol_hi, yoy_min):
    sig = (f["liquid"] & (close > f["hi60_prior"]) & (f["d5"] >= d5_min)
           & f["vol_r"].ge(vol_lo) & f["vol_r"].le(vol_hi) & (yoy >= yoy_min))
    return sig.fillna(False)


def build_signals(piv, yoy, min_turnover, d5_min, vol_lo, vol_hi, yoy_min):
    f = factors(piv, min_turnover)
    return apply_thresholds(piv["close"], f, yoy, d5_min, vol_lo, vol_hi, yoy_min), f


def forward_returns(piv, h, delisting):
    """T+1 開盤買進、T+h 收盤賣出的報酬。回傳 (報酬, 下市結算遮罩)。

    兩種「T+h 沒有收盤價」必須分開處理，混在一起就是捏造資料：

    - **樣本右端截斷**（訊號日 + h 超過面板最後一天）：報酬**未知**，一律 NaN 排除。
      舊版把它當成下市結算，等於用「不足 h 天的報酬」冒充完整 h 天報酬，而樣本末端
      的訊號往往落在同一波行情裡，會整批偏向同一個方向。
    - **真下市**（面板還有 h 天以後的日期，但這檔沒有價格）：要結算，不能丟掉——
      丟掉等於把最壞的結果排除在分布外。`last` 用最後成交價（樂觀，停牌後其實賣不掉），
      `zero` 假設 -100%（接近詐欺下市的實況）。兩者的差距就是這個假設的影響力。
    """
    close, open_ = piv["close"], piv["open"]
    entry = open_.shift(-1)
    exit_ = close.shift(-h)
    n = len(close.index)
    # 第 i 列的 T+h 是否還在面板內
    in_panel = pd.Series(np.arange(n) + h < n, index=close.index)
    censored = pd.DataFrame(np.repeat((~in_panel).to_numpy()[:, None], close.shape[1], axis=1),
                            index=close.index, columns=close.columns)
    # 「T+h 之後再也沒有成交價」才算下市；單日暫停交易（之後復牌）不算——後者用最後
    # 成交價結算會低估。`notna()[::-1].cummax()[::-1]` 是「這一列或之後有沒有成交價」。
    has_future = close.notna()[::-1].cummax()[::-1]
    # `.astype(bool)` 不可省：`shift` 會把 bool 欄位轉成 object dtype，此時 `~True` 得到
    # 整數 -2（真值）而不是 False，整條下市判定會全部反過來。
    no_future = ~has_future.shift(-h).fillna(False).astype(bool)
    delisted = (exit_.isna() & ~censored & entry.notna() & close.notna() & no_future)
    if delisting == "zero":
        settle = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    else:
        # `close.ffill()` 在第 t+h 列 = t+h 當下的最後有效收盤（下市日的收盤），再 shift 回
        # 第 t 列。舊版直接用 `close.ffill()`（不 shift）取到的是**訊號日**收盤,不是下市價。
        settle = close.ffill().shift(-h)
    exit_filled = exit_.where(~delisted, settle)
    ret = exit_filled / entry - 1
    return ret.where(~censored), delisted


def to_events(sig, ret, h, extra, *, entry_notional=DEFAULT_POSITION_NOTIONAL,
              fee_discount=1.0):
    """把訊號攤成長格式並做事件級去重（同檔 h 個交易日內只算一個事件）。"""
    idx = {d: i for i, d in enumerate(sig.index)}
    rows = []
    for d in sig.index[sig.any(axis=1)]:
        for s in sig.columns[sig.loc[d]]:
            r = ret.at[d, s]
            if pd.isna(r):
                continue
            net = round_trip_return(
                1.0, 1.0 + float(r), entry_notional=entry_notional,
                fee_discount=fee_discount,
            )
            rows.append({"date": d, "ti": idx[d], "stock_id": s, "r": net,
                         **{k: float(v.at[d, s]) if pd.notna(v.at[d, s]) else np.nan
                            for k, v in extra.items()}})
    t = pd.DataFrame(rows)
    if not len(t):
        return t, t
    t = t.sort_values(["stock_id", "ti"])
    # **與上一個「保留的事件」相隔 > h,不是與上一個名目訊號相隔 > h**。用 diff() 比名目訊號
    # 的話,0/50/100 日這種序列只會留下第 0 日——即使第 100 日的報酬窗口與已保留事件並不重疊
    # （實測差別是 918 vs 1,003 個事件、均值 10.54% vs 10.47%）。獨立審查指出。
    keep = []
    for _, g in t.groupby("stock_id", sort=False):
        last = None
        for i, ti in zip(g.index, g["ti"]):
            if last is None or ti - last > h:
                keep.append(i)
                last = ti
    ev = t.loc[keep].copy()
    return t, ev


def paired_block_bootstrap(events, calendar, n=1000, block=60, seed=42):
    """成對差異的 circular block bootstrap 95% CI；資料不足時回傳 ``None``。

    ``events`` 每列須有 ``date`` 與已配對完成的 ``diff``。NaN 代表配對缺一臂，直接排除，
    不補零。抽樣單位是完整 ``calendar`` 上的連續交易日區塊；同日所有股票會一起被抽中。
    """
    if n < 2 or block < 1:
        return None
    calendar = pd.Index(calendar)
    rng = np.random.default_rng(seed)
    n_days = len(calendar)
    if n_days < block * 2:
        return None
    if not calendar.is_unique or not calendar.is_monotonic_increasing:
        raise ValueError("calendar must be an ordered, unique full session index")

    pairs = events.loc[:, ["date", "diff"]].dropna()
    pairs = pairs[np.isfinite(pairs["diff"].astype(float))]
    if not pairs["date"].isin(calendar).all() or pairs["date"].nunique() < 2:
        return None
    event_positions = calendar.get_indexer(pd.Index(pairs["date"].unique()))
    if event_positions.max() - event_positions.min() < block:
        return None
    by_day = {d: g["diff"].to_numpy(dtype=float) for d, g in pairs.groupby("date")}
    n_blocks = int(np.ceil(n_days / block))
    means = []
    for _ in range(n):
        vals = []
        sampled_days = 0
        for st in rng.integers(0, n_days, size=n_blocks):
            for k in range(block):
                if sampled_days == n_days:
                    break
                d = calendar[(int(st) + k) % n_days]  # circular
                if d in by_day:
                    vals.extend(by_day[d])
                sampled_days += 1
        if vals:
            means.append(np.mean(vals))
    if len(means) < 2:
        return None
    if np.all(np.asarray(means) == 0):
        return 0.0, 0.0
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def block_bootstrap(ev, calendar, n=1000, block=60, seed=42):
    """相容舊報告的單臂均值區間；取樣核心同樣使用完整交易日曆。"""
    paired = ev[["ti", "r"]].rename(columns={"ti": "date", "r": "diff"})
    return paired_block_bootstrap(paired, calendar, n=n, block=block, seed=seed)


def subset_diff_bootstrap(ev, keep, calendar, values, n=1000, block=60, seed=42):
    """「留下的子集」相對「全部事件」的差異之 circular block bootstrap 95% 區間。

    回答「套否決後池子有沒有變好」：每次重抽同一批交易日區塊，對每個 ``values`` 指標算
    ``mean(子集) − mean(全部)``。與 ``paired_block_bootstrap`` 用同一種取樣（同日橫斷面整塊
    進出、環狀、抽滿整個日曆），但兩者是獨立的亂數流——不改既有函式，錨點區間才可重現。

    ``ev["date"]`` 須是 ``calendar`` 內的值；``keep`` 為與 ``ev`` 同長的布林；``values`` 為
    ``{名稱: 與 ev 同長的數值}``。子集差 ``mean(kept) − mean(all) = (1−f)(mean(kept) − mean(vetoed))``，
    與「留下 vs 被否決」同號。資料不足（區塊不夠、子集為空、全被否決）回傳 ``None``。
    """
    if n < 2 or block < 1:
        return None
    calendar = pd.Index(calendar)
    n_days = len(calendar)
    if n_days < block * 2:
        return None
    if not calendar.is_unique or not calendar.is_monotonic_increasing:
        raise ValueError("calendar must be an ordered, unique full session index")
    keep = np.asarray(keep, dtype=bool)
    dates = pd.Index(ev["date"])
    if len(dates) != len(keep) or not keep.any() or keep.all():
        return None
    if not dates.isin(calendar).all() or dates.nunique() < 2:
        return None
    pos = calendar.get_indexer(dates)
    if pos.max() - pos.min() < block:
        return None
    vals = {k: np.asarray(v, dtype=float) for k, v in values.items()}
    rows_by_pos = {}
    for i, q in enumerate(pos):
        rows_by_pos.setdefault(int(q), []).append(i)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n_days / block))
    diffs = {k: [] for k in vals}
    for _ in range(n):
        idx = []
        sampled_days = 0
        for st in rng.integers(0, n_days, size=n_blocks):
            for k in range(block):
                if sampled_days == n_days:
                    break
                idx.extend(rows_by_pos.get((int(st) + k) % n_days, ()))
                sampled_days += 1
        if not idx:
            continue
        idx = np.asarray(idx)
        kept = keep[idx]
        if not kept.any():
            continue
        for name, v in vals.items():
            diffs[name].append(v[idx][kept].mean() - v[idx].mean())
    out = {}
    for name, d in diffs.items():
        if len(d) < 2:
            return None
        out[name] = (float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5)))
    return out


def _arm(ev):
    r = ev["r"]
    return {"n": len(ev), "mean": r.mean() if len(r) else np.nan,
            "hit": (r >= HIT_THRESHOLD).mean() if len(r) else np.nan}


def report_subset_veto(d, calendar, a, col, thresholds, rule_label):
    """事件層否決的共用報告：依 ``d[col] >= 門檻`` 切「留下／否決」，比較留下的池子與原池。

    否決在事件層做（不重跑去重），兩臂嚴格是原池子的子集；``d`` 須已去掉 ``col`` 缺值的列
    （缺值的處理由各實驗事先登記）。``rule_label(thr)`` 回傳每個門檻的標題文字。
    每個門檻印三臂的 n／均值／P(≥30%)、留下−原池的差與 block bootstrap 區間、vol20 三分位內的
    留下／否決比較（描述用、無區間）。LHR 與 PB 否決實驗共用，輸出格式不得任意改（測試釘住）。
    """
    base = _arm(d)
    for thr in thresholds:
        veto = (d[col] >= thr).to_numpy()
        kept, vetoed = _arm(d[~veto]), _arm(d[veto])
        print(f"\n-- {rule_label(thr)} --")
        for label, arm in (("原池", base), ("留下", kept), ("否決", vetoed)):
            print(f"  {label}  n={arm['n']:5d}  均值 {arm['mean'] * 100:+7.2f}%  "
                  f"P(≥30%) {arm['hit'] * 100:5.1f}%")
        print(f"  否決比例 {veto.mean() * 100:.1f}%；留下−原池：均值 "
              f"{(kept['mean'] - base['mean']) * 100:+.2f}pp、P(≥30%) "
              f"{(kept['hit'] - base['hit']) * 100:+.2f}pp")
        if a.bootstrap:
            ci = subset_diff_bootstrap(
                d.assign(date=d["ti"]), ~veto, calendar,
                {"mean": d["r"], "hit": (d["r"] >= HIT_THRESHOLD).astype(float)},
                n=a.bootstrap, block=a.horizon, seed=a.bootstrap_seed)
            if ci is None:
                print("  區塊 bootstrap：inconclusive（資料不足）")
            else:
                for name, label in (("mean", "均值"), ("hit", "P(≥30%)")):
                    lo, hi = ci[name]
                    print(f"  留下−原池 {label} 95% 區間（block={a.horizon}、{a.bootstrap} 次、"
                          f"seed={a.bootstrap_seed}）: {lo * 100:+.2f}pp ~ {hi * 100:+.2f}pp")
        # 波動控制：在 vol20 三分位內各自比較（描述用、無區間）
        q = d["vol20"].rank(pct=True, method="first")
        terc = pd.cut(q, [0, 1 / 3, 2 / 3, 1], labels=["低波動", "中波動", "高波動"])
        for t in ("低波動", "中波動", "高波動"):
            m = (terc == t).to_numpy()
            k_arm, v_arm = _arm(d[m & ~veto]), _arm(d[m & veto])
            print(f"  {t}：留下 n={k_arm['n']} 均值 {k_arm['mean'] * 100:+.2f}% "
                  f"P30 {k_arm['hit'] * 100:.1f}%｜否決 n={v_arm['n']} 均值 "
                  f"{v_arm['mean'] * 100:+.2f}% P30 {v_arm['hit'] * 100:.1f}%")


def report_lhr_veto(ev, calendar, a):
    """LHR 否決實驗（事先登記於 docs/research/2026-10-26-exp-lhr-veto.md）。

    同一批候選事件依訊號日 LHR 切成「留下／否決」，比較留下的池子與原池子；
    否決在事件層做（不重跑去重），兩臂嚴格是原池子的子集。只報告、不改 live 規則。
    """
    w = a.lhr_window
    print(f"\n=== LHR 否決（近 {w} 交易日收漲停天數 − 收跌停天數，門檻 {LIMIT_HIT_THRESHOLD:.1%}）===")
    d = ev.dropna(subset=["lhr"]).copy()
    print(f"有 LHR 的事件 {len(d)} / {len(ev)}；淨漲停天數分布：")
    print(d["lhr"].astype(int).value_counts().sort_index().to_string())
    rho = d[["lhr", "vol20"]].corr(method="spearman").iloc[0, 1]
    print(f"Spearman(LHR, vol20) = {rho:+.3f}（事件層）")
    report_subset_veto(d, calendar, a, "lhr", a.lhr_veto,
                       lambda thr: f"否決 淨漲停天數 ≥ {thr:g}（LHR ≥ {thr / w:.2f}）")


def pb_panel(rows, index, columns, ffill_limit=PB_FFILL_DAYS):
    """``market.valuation`` 的股價淨值比對齊到交易日面板（訊號日 D 用 D 當日的 PB）。

    BWIBBU_d／上櫃 peQryDate 的 D 日估值以 D 日收盤價計算、D 日盤後發布，早於 T+1 開盤
    進場，所以用 D 日值不是前視。某天估值缺列（端點漏日）時，最多沿用前 ``ffill_limit``
    個**交易列**的值；再久就是 NaN（不否決、另行計數），不無限期沿用舊估值。
    PB ≤ 0 或空白（淨值為負或無法計算）一律視為缺值。
    """
    if not len(rows):
        return pd.DataFrame(np.nan, index=index, columns=columns)
    v = rows.pivot_table(index="date", columns="stock_id", values="pb_ratio", aggfunc="last")
    v = v.astype(float).where(lambda x: x > 0)
    return v.reindex(index=index, columns=columns).ffill(limit=ffill_limit)


def report_pb_veto(ev, calendar, a):
    """PB 否決實驗（事先登記於 docs/research/2026-10-26-exp-invvol-pb.md 第 2 節）。

    先報 PB≥門檻 在突破池內的占比（整體與逐年）與「否決後池子還剩多少」的閘門；
    主門檻的留下 n ≥ ``PB_GATE_MIN_KEPT`` 且否決 n ≥ ``PB_GATE_MIN_VETOED`` 才跑否決比較，
    否則只報占比、不做檢定（池子會被掏空，或否決的樣本太少）。PB 缺值的事件不否決。
    """
    thr0 = a.pb_veto[0]
    print(f"\n=== PB 否決（訊號日股價淨值比 ≥ 門檻；主門檻 {thr0:g}）===")
    has = ev["pb"].notna()
    print(f"有 PB 的事件 {int(has.sum())} / {len(ev)}（缺 PB 的 {int((~has).sum())} 個不否決）")
    d = ev.copy()
    d["pb"] = d["pb"].fillna(-np.inf)              # 缺值一律留下
    share = (d["pb"] >= thr0)
    print(f"PB ≥ {thr0:g} 占全部事件 {share.mean() * 100:.1f}%；"
          f"占有 PB 的事件 {share[has].mean() * 100:.1f}%")
    q = ev.loc[has, "pb"].quantile([.1, .25, .5, .75, .9])
    print("有 PB 事件的分位：" + "、".join(f"P{int(k * 100)} {v:.2f}" for k, v in q.items()))
    yearly = pd.DataFrame({"y": d["date"].dt.year, "veto": share}).groupby("y")["veto"]
    print("逐年 PB ≥ 門檻 占比：" + "、".join(
        f"{y} {m * 100:.0f}%（n={c}）" for y, m, c in
        zip(yearly.mean().index, yearly.mean(), yearly.size())))
    rho = ev.loc[has, ["pb", "vol20"]].corr(method="spearman").iloc[0, 1]
    print(f"Spearman(PB, vol20) = {rho:+.3f}（有 PB 的事件層）")
    n_kept, n_vetoed = int((~share).sum()), int(share.sum())
    if n_kept < PB_GATE_MIN_KEPT or n_vetoed < PB_GATE_MIN_VETOED:
        print(f"閘門未過：主門檻留下 {n_kept}（需 ≥ {PB_GATE_MIN_KEPT}）、否決 {n_vetoed}"
              f"（需 ≥ {PB_GATE_MIN_VETOED}）——不做否決比較")
        return False
    print(f"閘門通過：主門檻留下 {n_kept}、否決 {n_vetoed}")
    report_subset_veto(d, calendar, a, "pb", a.pb_veto,
                       lambda thr: f"否決 PB ≥ {thr:g}")
    return True


def hit_rate_bootstrap(ev, calendar, threshold=HIT_THRESHOLD, n=1000, block=60, seed=42):
    """P(淨報酬 ≥ threshold) 的 circular block bootstrap 95% 區間。

    錨點用的是命中率而不是均值，所以把每個事件換成 0/1 命中指標再走同一個取樣核心；
    資料不足時同樣回傳 ``None``（inconclusive）。
    """
    hit = (ev["r"] >= threshold).astype(float)
    paired = pd.DataFrame({"date": ev["ti"], "diff": hit})
    return paired_block_bootstrap(paired, calendar, n=n, block=block, seed=seed)


# ── 處置公告延後進場（docs/research/2026-10-26-exp-disposal-delay.md）──────────────
DISPOSAL_DELAYS = (3, 4)
DISPOSAL_MIN_EVENTS = 30   # 事先登記的最低受影響事件數；不足一律 inconclusive
DISPOSAL_RULE_CHANGE = pd.Timestamp("2026-08-10")  # 處置期 10→5 日、撮合約 2 分鐘一次的新制起日


def disposal_context(ev, disp, index, h):
    """每個事件在訊號日 D 收盤後「已公告、且處置期涵蓋進場日 D+1」的處置（與 live
    `risk_flags` 以 next_session 查名單同語意）。

    ``disp`` 欄位 stock_id／announce／start／end（Timestamp）；``index`` 是面板交易日。
    公告日落在非交易日時取「之前最後一個交易日」——它在 D+1 開盤前就已公開。
    回傳與 ``ev`` 同索引的 DataFrame：``affected``、``a_idx``（涵蓋列中最晚的公告）、
    ``e_idx``（涵蓋列中最晚的處置迄日）、``later``（D 之後、D+h 之內才公告——持有中才知道，
    只描述、不是實驗組）。"""
    index = pd.DatetimeIndex(index)
    out = pd.DataFrame({"affected": False, "a_idx": np.nan, "e_idx": np.nan, "later": False},
                       index=ev.index)
    if not len(ev) or not len(disp):
        return out
    # 面板最後一天之後才公告的處置在面板內不可知；不先丟掉的話 searchsorted 會把它夾到最後一列，
    # 誤算成「持有中才公告」。
    d = disp[pd.DatetimeIndex(disp["announce"]) <= index[-1]].copy()
    if not len(d):
        return out
    d["stock_id"] = d["stock_id"].astype(str)
    d["a"] = index.searchsorted(pd.DatetimeIndex(d["announce"]), side="right") - 1
    d["s"] = index.searchsorted(pd.DatetimeIndex(d["start"]), side="left")
    d["e"] = index.searchsorted(pd.DatetimeIndex(d["end"]), side="right") - 1
    by_stock = {s: g for s, g in d.groupby("stock_id")}
    for i, sid, ti in zip(ev.index, ev["stock_id"].astype(str), ev["ti"].astype(int)):
        g = by_stock.get(sid)
        if g is None:
            continue
        cover = g[(g["a"] <= ti) & (g["s"] <= ti + 1) & (g["e"] >= ti + 1)]
        if len(cover):
            out.at[i, "affected"] = True
            out.at[i, "a_idx"] = float(cover["a"].max())
            out.at[i, "e_idx"] = float(cover["e"].max())
        out.at[i, "later"] = bool(((g["a"] > ti) & (g["a"] <= ti + h)).any())
    return out


def disposal_arm_returns(ev, ctx, ret, delays=DISPOSAL_DELAYS, *,
                         entry_notional=DEFAULT_POSITION_NOTIONAL, fee_discount=1.0):
    """受影響事件在各延後臂的淨報酬（持有長度不變：進場日往後挪幾天，出場日就挪幾天）。

    延後 k 日：以第 ``max(ti, a_idx + k)`` 列當「訊號日」，即公告後第 k+1 個交易日開盤買進、
    持有同樣 h 日；``k=0`` 等於正常進場（公告日 = 訊號日時）。處置期後：以 ``max(ti, e_idx)``
    為訊號日，處置迄日後第一個交易日開盤買進。``ret`` 是 `forward_returns` 的毛報酬面板，
    超出面板（右端截斷）留 NaN、配對時剔除。回傳 DataFrame：``delay_k`` 各欄與 ``after_end``。"""
    cols = {f"delay_{k}": [] for k in delays}
    cols["after_end"] = []
    n = len(ret.index)
    hit = ev.index[ctx["affected"].to_numpy(dtype=bool)]

    def net_at(t, sid):
        if t >= n:
            return np.nan
        r = ret.iat[t, ret.columns.get_loc(sid)]
        if pd.isna(r):
            return np.nan
        return round_trip_return(1.0, 1.0 + float(r), entry_notional=entry_notional,
                                 fee_discount=fee_discount)

    for i in hit:
        ti, sid = int(ev.at[i, "ti"]), ev.at[i, "stock_id"]
        for k in delays:
            cols[f"delay_{k}"].append(net_at(max(ti, int(ctx.at[i, "a_idx"]) + k), sid))
        cols["after_end"].append(net_at(max(ti, int(ctx.at[i, "e_idx"])), sid))
    return pd.DataFrame(cols, index=hit)


def exclusion_block_bootstrap(frame, calendar, n=1000, block=60, seed=42):
    """「剔除」對池均值的效果 = mean(未剔除) − mean(全部)，其 circular block bootstrap 95% 區間。

    ``frame`` 欄位 ``date``（``calendar`` 上的鍵）、``value``、``excluded``（bool）。取樣方式與
    `paired_block_bootstrap` 相同（整段交易日、同日橫斷面一起抽），但統計量是兩組均值差，
    不是成對差，所以另寫；資料不足或某次重抽沒有任何未剔除事件時回 ``None``。"""
    calendar = pd.Index(calendar)
    n_days = len(calendar)
    if n < 2 or block < 1 or n_days < block * 2:
        return None
    f = frame.loc[:, ["date", "value", "excluded"]].dropna(subset=["value"])
    if not f["date"].isin(calendar).all() or f["date"].nunique() < 2 or not f["excluded"].any():
        return None
    pos = calendar.get_indexer(pd.Index(f["date"].unique()))
    if pos.max() - pos.min() < block:
        return None
    by_day = {d: (g["value"].to_numpy(dtype=float), g["excluded"].to_numpy(dtype=bool))
              for d, g in f.groupby("date")}
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n_days / block))
    stats = []
    for _ in range(n):
        vals, excl = [], []
        sampled = 0
        for st in rng.integers(0, n_days, size=n_blocks):
            for k in range(block):
                if sampled == n_days:
                    break
                d = calendar[(int(st) + k) % n_days]
                if d in by_day:
                    vals.append(by_day[d][0])
                    excl.append(by_day[d][1])
                sampled += 1
        if not vals:
            continue
        v, x = np.concatenate(vals), np.concatenate(excl)
        if x.all():
            continue
        stats.append(v[~x].mean() - v.mean())
    if len(stats) < 2:
        return None
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def report_disposal(ev, disp, ret, index, h, *, delays=DISPOSAL_DELAYS, n_boot=2000, seed=42,
                    tpex_codes=frozenset(), event_args=None):
    """印出處置公告實驗（正常／延後 k 日／處置期後／剔除），只上市；回傳摘要 dict 供測試。"""
    event_args = event_args or {}
    tw = ev[~ev["stock_id"].astype(str).isin(tpex_codes)].copy()
    print(f"\n=== 處置公告實驗（只上市；h={h}）===")
    print(f"候選池事件 {len(ev)} 個，排除上櫃 {len(ev) - len(tw)} 個 → 上市 {len(tw)} 個")
    ctx = disposal_context(tw, disp, index, h)
    aff = tw[ctx["affected"]]
    pre = int((pd.DatetimeIndex(aff["date"]) < DISPOSAL_RULE_CHANGE).sum()) if len(aff) else 0
    print(f"訊號日收盤已公告、處置期涵蓋 D+1 的受影響事件 {len(aff)} 個"
          f"（訊號日在 {DISPOSAL_RULE_CHANGE:%Y-%m-%d} 新制前 {pre}、後 {len(aff) - pre}）；"
          f"持有中才公告（只描述）{int(ctx['later'].sum())} 個")
    summary = {"n_twse": len(tw), "n_affected": len(aff), "arms": {}}
    if not len(aff):
        print("受影響事件為 0：inconclusive")
        return summary
    arms = disposal_arm_returns(tw, ctx, ret, delays, **event_args)
    # 以索引對齊（不靠位置）組成各臂的配對：臂與正常進場都非 NaN 的同一批事件。
    # delayed＝實際進場日晚於正常進場（處置中的事件延後等於正常進場，成對差恆為 0）。
    actx = ctx.loc[aff.index]
    shifted = {f"delay_{k}": actx["a_idx"] + k for k in delays}
    shifted["after_end"] = actx["e_idx"]
    pairs = {}
    rows = [describe(aff, "受影響·正常進場（全部）")]
    for col in arms.columns:
        pair = pd.DataFrame({"date": aff["ti"], "arm": arms[col], "base": aff["r"],
                             "delayed": shifted[col] > aff["ti"]}).dropna(subset=["arm", "base"])
        pairs[col] = pair
        # 表格逐臂並列「同一批配對事件」的正常進場列，避免和全部受影響事件的列比出相反的方向
        rows.append(describe(pair.assign(r=pair["base"]), f"受影響·正常進場（{col} 配對）"))
        rows.append(describe(pair.assign(r=pair["arm"]), f"受影響·{col}"))
    unaff = tw[~ctx["affected"]]
    rows.append(describe(unaff, "未受影響"))
    print(pd.DataFrame(rows).set_index("組").to_string())

    cal = np.arange(len(index))
    print(f"\n成對差（臂 − 正常；同一批事件、持有長度相同；block={h}、{n_boot} 次、seed={seed}）：")
    for col in arms.columns:
        pair = pairs[col]
        n_pair = len(pair)
        n_delayed = int(pair["delayed"].sum())
        d_mean = (pair["arm"] - pair["base"]).mean() if n_pair else np.nan
        d_hit = ((pair["arm"] >= HIT_THRESHOLD).astype(float)
                 - (pair["base"] >= HIT_THRESHOLD).astype(float)).mean() if n_pair else np.nan
        ci_m = ci_h = None
        if n_boot and n_pair:
            ci_m = paired_block_bootstrap(pair.assign(diff=pair["arm"] - pair["base"]), cal,
                                          n=n_boot, block=h, seed=seed)
            ci_h = paired_block_bootstrap(pair.assign(
                diff=(pair["arm"] >= HIT_THRESHOLD).astype(float)
                - (pair["base"] >= HIT_THRESHOLD).astype(float)), cal, n=n_boot, block=h, seed=seed)
        verdict = disposal_verdict(n_pair, d_mean, d_hit, ci_m)
        fmt = (lambda c, s=100: "inconclusive" if c is None
               else f"{c[0] * s:+.2f} ~ {c[1] * s:+.2f}")
        print(f"  {col}: n={n_pair}（實際延後 {n_delayed}）  均值差 {d_mean * 100:+.2f}pp（95% {fmt(ci_m)}）  "
              f"P(≥30%) 差 {d_hit * 100:+.1f}pp（95% {fmt(ci_h)}）→ {verdict}")
        summary["arms"][col] = {"n": n_pair, "n_delayed": n_delayed, "d_mean": d_mean,
                                "d_hit": d_hit, "base_mean": pair["base"].mean(),
                                "arm_mean": pair["arm"].mean(),
                                "ci_mean": ci_m, "ci_hit": ci_h, "verdict": verdict}

    frame = pd.DataFrame({"date": tw["ti"].to_numpy(), "value": tw["r"].to_numpy(),
                          "excluded": ctx["affected"].to_numpy(dtype=bool)})
    d_mean = unaff["r"].mean() - tw["r"].mean()
    d_hit = (unaff["r"] >= HIT_THRESHOLD).mean() - (tw["r"] >= HIT_THRESHOLD).mean()
    ci_m = exclusion_block_bootstrap(frame, cal, n=n_boot, block=h, seed=seed) if n_boot else None
    ci_h = (exclusion_block_bootstrap(frame.assign(value=(frame["value"] >= HIT_THRESHOLD)
                                                   .astype(float)), cal, n=n_boot, block=h,
                                      seed=seed) if n_boot else None)
    verdict = disposal_verdict(len(aff), d_mean, d_hit, ci_m)
    fmt = (lambda c: "inconclusive" if c is None else f"{c[0] * 100:+.2f} ~ {c[1] * 100:+.2f}")
    print(f"剔除（未受影響池 − 上市全池）: 剔除 {len(aff)} 個  均值差 {d_mean * 100:+.2f}pp"
          f"（95% {fmt(ci_m)}）  P(≥30%) 差 {d_hit * 100:+.1f}pp（95% {fmt(ci_h)}）→ {verdict}")
    summary["arms"]["exclude"] = {"n": len(aff), "d_mean": d_mean, "d_hit": d_hit,
                                  "ci_mean": ci_m, "ci_hit": ci_h, "verdict": verdict}
    return summary


def disposal_verdict(n, d_mean, d_hit, ci_mean, min_events=DISPOSAL_MIN_EVENTS):
    """事先登記的判準：n ≥ 下限，均值差與 P(≥30%) 差的點估計都 > 0，且均值差區間整段 > 0。
    區間整段 < 0 且兩個點估計都 < 0 記「較差」；其餘一律 inconclusive。"""
    if n < min_events or ci_mean is None or pd.isna(d_mean) or pd.isna(d_hit):
        return "inconclusive"
    if d_mean > 0 and d_hit > 0 and ci_mean[0] > 0:
        return "通過"
    if d_mean < 0 and d_hit < 0 and ci_mean[1] < 0:
        return "較差"
    return "inconclusive"


def two_arm_block_bootstrap(arm, ref, n_days, *, threshold=HIT_THRESHOLD, n=1000, block=60,
                            seed=42, levels=(95.0,)):
    """兩組事件差（``arm`` − ``ref``）的 circular 交易日區塊 bootstrap 區間。

    回傳 ``{"mean": {level: (lo, hi)}, "hit": {level: (lo, hi)}}``；``hit`` 是
    P(淨報酬 ≥ threshold) 的差。資料不足回 ``None``（inconclusive）。

    與 ``paired_block_bootstrap`` 的差別：兩組不是逐筆配對（取代型閘門的池子與原池子
    事件集合不同、可能重疊），所以每次重抽**同一組**交易日區塊、兩組各自取落在這些日子的
    事件算統計量再相減——同日橫斷面與兩組的重疊都被一起保留，不會把重疊事件當獨立樣本。
    ``ti`` 是事件在 ``0..n_days-1`` 交易日曆上的位置（``to_events`` 的輸出）。
    """
    if n < 2 or block < 1 or n_days < block * 2:
        return None

    def per_day(ev):
        ev = ev.loc[np.isfinite(ev["r"].astype(float))]
        ti = ev["ti"].to_numpy(dtype=int)
        if not len(ti) or ti.max() - ti.min() < block:
            return None
        if ti.min() < 0 or ti.max() >= n_days:
            raise ValueError("event ti outside the session calendar")
        r = ev["r"].to_numpy(dtype=float)
        return (np.bincount(ti, minlength=n_days).astype(float),
                np.bincount(ti, weights=r, minlength=n_days),
                np.bincount(ti, weights=(r >= threshold).astype(float), minlength=n_days))

    a, b = per_day(arm), per_day(ref)
    if a is None or b is None:
        return None
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n_days / block))
    starts = rng.integers(0, n_days, size=(n, n_blocks))
    days = ((starts[:, :, None] + np.arange(block)) % n_days).reshape(n, -1)[:, :n_days]
    ca, sa, ha = (x[days].sum(axis=1) for x in a)
    cb, sb, hb = (x[days].sum(axis=1) for x in b)
    ok = (ca > 0) & (cb > 0)
    if ok.sum() < 2:
        return None
    diffs = {"mean": (sa[ok] / ca[ok]) - (sb[ok] / cb[ok]),
             "hit": (ha[ok] / ca[ok]) - (hb[ok] / cb[ok])}
    out = {}
    for k, d in diffs.items():
        out[k] = {}
        for lv in levels:
            tail = (100.0 - lv) / 2
            out[k][lv] = (float(np.percentile(d, tail)), float(np.percentile(d, 100.0 - tail)))
    return out


def describe(ev, label):
    r = ev["r"]
    win, loss = r[r > 0], r[r <= 0]
    rr = win.mean() / abs(loss.mean()) if len(loss) and loss.mean() else float("nan")
    return {
        "組": label, "事件": len(ev),
        "均值": f"{r.mean() * 100:+.2f}%", "中位": f"{r.median() * 100:+.2f}%",
        "勝率": f"{(r > 0).mean() * 100:.1f}%",
        "賺賠比": f"{rr:.2f}", "兩平勝率": f"{1 / (1 + rr) * 100:.1f}%",
        "P(≥30%)": f"{(r >= HIT_THRESHOLD).mean() * 100:.1f}%", "P(≤-20%)": f"{(r <= -.2).mean() * 100:.1f}%",
        "最差": f"{r.min() * 100:+.0f}%",
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="訊號前瞻報酬分布量測")
    p.add_argument("--start", default="2020-01-01")
    p.add_argument("--end", default="2026-07-24")
    p.add_argument("--horizon", type=int, default=60, help="前瞻交易日數")
    p.add_argument("--min-turnover", type=float, default=2.0, help="日均額門檻（億）")
    p.add_argument("--d5", type=float, default=0.05)
    p.add_argument("--vol-lo", type=float, default=1.3)
    p.add_argument("--vol-hi", type=float, default=2.0)
    p.add_argument("--yoy", type=float, default=20.0)
    p.add_argument("--delisting", default="last", choices=["last", "zero"],
                   help="訊號後 h 日內停止交易時的結算方式")
    p.add_argument("--bootstrap", type=int, default=2000, help="區塊 bootstrap 次數（0 關閉）")
    p.add_argument("--bootstrap-seed", type=int, default=42,
                   help="區塊 bootstrap 隨機種子（預設 42）")
    p.add_argument("--position-notional", type=float, default=DEFAULT_POSITION_NOTIONAL,
                   help="每筆事件的名目本金（元），用來正確套最低手續費")
    p.add_argument("--fee-discount", type=float, default=1.0,
                   help="券商手續費折數乘數，例如六折填 0.6")
    p.add_argument("--survivorship-bound", action="store_true",
                   help="加算「補不回月營收的下市公司」的上界（假設它們全部符合營收條件）")
    p.add_argument("--emit-revenue-gaps", default=None, metavar="PATH",
                   help="輸出 CSV(stock_id,year,month) 給 `cli revenue-pit --only-file`。"
                        "只列「已下市且符合價格條件」的股票在訊號當月與前一月——月營收只在"
                        "價格條件成立那幾天會被用到，全量補 3,102 個缺口要數小時，"
                        "精準補只要幾十個請求。")
    p.add_argument("--include-otc-revenue", action="store_true",
                   help="月營收放入上櫃（預設只用上市口徑，與 screen_tw 預設相同；放入後是另一個池子，數字不可與既有基準比較）")
    p.add_argument("--lhr", action="store_true",
                   help="加跑 LHR（漲停率減跌停率）否決實驗；預設輸出不變")
    p.add_argument("--lhr-window", type=int, default=LHR_WINDOW, help="LHR 回看交易日數")
    p.add_argument("--lhr-veto", type=float, nargs="+", default=[1.0, 2.0],
                   help="否決門檻（淨漲停天數 ≥ 此值即否決）；第一個為事先登記的主判準")
    p.add_argument("--disposal-cache", default=None, metavar="PATH",
                   help="TWSE 處置公告快取 CSV（scripts/fetch_twse_disposal_history.py 產生）；"
                        "加上後另印處置公告延後進場實驗（只上市）")
    p.add_argument("--pb", action="store_true",
                   help="加跑 PB（股價淨值比）否決實驗：先報池內占比與閘門；預設輸出不變")
    p.add_argument("--pb-veto", type=float, nargs="+", default=[2.0],
                   help="PB 否決門檻（PB ≥ 此值即否決）；第一個為事先登記的主判準")
    a = p.parse_args(argv)
    if a.position_notional <= 0:
        p.error("--position-notional must be positive")
    if a.fee_discount < 0:
        p.error("--fee-discount must be non-negative")

    eng = get_engine()
    piv, rv, info = load(eng, a.start, a.end, a.include_otc_revenue)
    close = piv["close"]
    # 池：四位數普通股（排除 ETF 00xx、TDR 91xx；與 live `screen_tw.funnel` 共用 `is_common_stock`）。**創新板不在這裡排除**——用今天的名稱
    # 後綴判定歷史宇宙是前視；它的影響改用敏感度分析看（下方 `--include-tib` 對照）。
    keep = [s for s in close.columns if is_common_stock(s)]
    piv = {k: v[keep] for k, v in piv.items()}
    close = piv["close"]

    yoy = pit_revenue_panel(rv, close.index, close.columns)
    sig, extra = build_signals(piv, yoy, a.min_turnover * 1e8, a.d5, a.vol_lo,
                               a.vol_hi, a.yoy)

    if a.emit_revenue_gaps:
        with eng.connect() as c:
            gone = {r[0] for r in c.execute(text("""
                select stock_id from market.price group by stock_id
                having max(date) < (select max(date) from market.price)
                                   - interval '14 days'""")).fetchall()}
        price_only = (extra["liquid"] & (close > extra["hi60_prior"])
                      & (extra["d5"] >= a.d5)
                      & extra["vol_r"].ge(a.vol_lo) & extra["vol_r"].le(a.vol_hi))
        price_only = price_only.fillna(False)
        price_only.loc[:pd.Timestamp(a.start)] = False
        cols = [s for s in price_only.columns if s in gone]
        want = set()
        for d in price_only.index[price_only[cols].any(axis=1)]:
            for s in [c2 for c2 in cols if price_only.at[d, c2]]:
                # 訊號當月與前兩月：ffill(limit=45) 讓訊號可能用到最多兩個月前的公告
                # 前三月：12 月營收於次年 1/10 公告，經 ffill(45).shift(1) 最晚可影響
                # 約 3/17 的訊號，所以較新月份缺資料時會需要往前第三個月。
                for back in (0, 1, 2, 3):
                    m = (d - pd.DateOffset(months=back))
                    want.add((s, int(m.year), int(m.month)))
        out = Path(a.emit_revenue_gaps)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(f"{s},{y},{m}\n" for s, y, m in sorted(want)),
                       encoding="utf-8")
        print(f"已下市且符合價格條件的股票 {len({w[0] for w in want})} 檔，"
              f"需補 {len(want)} 個 (stock, 月) → {out}")
        return 0
    sig.loc[:pd.Timestamp(a.start)] = False
    ret, delisted = forward_returns(piv, a.horizon, a.delisting)
    event_args = {"entry_notional": a.position_notional, "fee_discount": a.fee_discount}
    ev_extra = {k: extra[k] for k in ("d5", "vol_r")}
    if a.lhr:
        ev_extra["lhr"] = limit_hit_net(close, a.lhr_window)
    if a.lhr or a.pb:
        ev_extra["vol20"] = volatility20(close)
    if a.pb:
        hist = (pd.Timestamp(a.start) - pd.Timedelta(days=WARMUP_DAYS)).date()
        with eng.connect() as c:
            vrows = pd.read_sql(text(
                "select stock_id, date, pb_ratio from market.valuation "
                "where date between :s and :e"), c,
                params={"s": hist, "e": a.end}, parse_dates=["date"])
        ev_extra["pb"] = pb_panel(vrows, close.index, close.columns)
    raw, ev = to_events(sig, ret, a.horizon, ev_extra, **event_args)

    flat_cost = -round_trip_return(
        1.0, 1.0, entry_notional=a.position_notional, fee_discount=a.fee_discount)
    print(f"樣本 {a.start} ~ {a.end}　池 {len(keep)} 檔　前瞻 {a.horizon} 交易日　"
          f"下市結算={a.delisting}　名目本金 {a.position_notional:,.0f} 元　"
          f"平盤來回成本約 {flat_cost * 100:.3f}%")
    nominal = int(sig.sum().sum())
    print(f"名目訊號 {nominal:,} 筆 → 可量測 {len(raw):,} 筆 → **事件 {len(ev):,} 個**"
          f"（同檔 {a.horizon} 交易日內算一個）")
    n_del = int((sig & delisted).sum().sum())
    n_unavailable = nominal - len(raw)
    print(f"其中訊號後 {a.horizon} 日內真下市（已按 --delisting 結算）: {n_del} 筆；"
          f"無可用前瞻報酬而排除（本樣本為右端截斷）: {n_unavailable} 筆\n")

    rows = [describe(ev, "候選池")]
    # 同期同池的無條件基準（不套任何選股條件，只留流動性）
    base_sig = extra["liquid"].fillna(False).copy()
    base_sig.loc[:pd.Timestamp(a.start)] = False
    _, base_ev = to_events(base_sig, ret, a.horizon, {}, **event_args)
    rows.append(describe(base_ev, "全流動股基準"))
    # 有月營收資料的子集（對等基準：候選池必然有 yoy，基準也該有）
    has_rev = base_sig & yoy.notna()
    _, rev_ev = to_events(has_rev, ret, a.horizon, {}, **event_args)
    rows.append(describe(rev_ev, "基準(限有月營收)"))
    print(pd.DataFrame(rows).set_index("組").to_string())

    if a.bootstrap:
        ci = block_bootstrap(ev, np.arange(len(close.index)),
                             n=a.bootstrap, block=a.horizon, seed=a.bootstrap_seed)
        if ci is None:
            print(f"\n候選池均值的區塊 bootstrap：inconclusive（至少需要跨越兩個 "
                  f"{a.horizon} 日區塊的有效事件）")
        else:
            lo, hi = ci
            print(f"\n候選池均值的區塊 bootstrap 95% 區間（block={a.horizon} 交易日、"
                  f"{a.bootstrap} 次、seed={a.bootstrap_seed}）: {lo * 100:+.2f}% ~ {hi * 100:+.2f}%")
            iid = ev["r"].std() / np.sqrt(len(ev)) * 1.96
            print(f"（同一批事件的 IID 區間是 "
                  f"{(ev['r'].mean() - iid) * 100:+.2f}% ~ "
                  f"{(ev['r'].mean() + iid) * 100:+.2f}%——事件在時間上聚集，"
                  "IID 是假精度）")
        hit_ci = hit_rate_bootstrap(ev, np.arange(len(close.index)), n=a.bootstrap,
                                    block=a.horizon, seed=a.bootstrap_seed)
        hit = (ev["r"] >= HIT_THRESHOLD).mean()
        if hit_ci is None:
            print(f"候選池 P(≥{HIT_THRESHOLD:.0%}) {hit * 100:.1f}%：區塊 bootstrap inconclusive")
        else:
            print(f"候選池 P(≥{HIT_THRESHOLD:.0%}) {hit * 100:.1f}%（n={len(ev)}）的區塊 bootstrap "
                  f"95% 區間: {hit_ci[0] * 100:.1f}% ~ {hit_ci[1] * 100:.1f}%")

    if a.lhr:
        report_lhr_veto(ev, np.arange(len(close.index)), a)
    if a.disposal_cache:
        from fetch_twse_disposal_history import load_cache
        from screen_tw import _seed_market_map
        tpex = frozenset(s for s, m in _seed_market_map().items() if m == "tpex")
        report_disposal(ev, load_cache(a.disposal_cache), ret, close.index, a.horizon,
                        n_boot=a.bootstrap, seed=a.bootstrap_seed, tpex_codes=tpex,
                        event_args=event_args)
    if a.pb:
        report_pb_veto(ev, np.arange(len(close.index)), a)

    print("\n=== 逐年（事件級）===")
    ev["y"] = ev["date"].dt.year
    g = ev.groupby("y").agg(事件=("r", "size"), 均值=("r", "mean"), 中位=("r", "median"),
                            勝率=("r", lambda s: (s > 0).mean()))
    print(g.assign(**{c: (g[c] * 100).round(1) for c in ("均值", "中位", "勝率")}).to_string())

    srt = ev["r"].sort_values(ascending=False)
    tot = srt.sum()
    k = max(1, len(ev) // 8)
    print(f"\n集中度：前 {k} 個事件（{k / len(ev) * 100:.0f}%）貢獻總報酬 "
          f"{srt.head(k).sum() / tot * 100:.0f}%；"
          f"拿掉報酬 >100% 的 {(ev['r'] > 1).sum()} 個事件後均值 "
          f"{ev[ev['r'] <= 1]['r'].mean() * 100:+.2f}%")

    if a.survivorship_bound:
        # 補不回月營收的下市公司：假設它們在符合價格條件時也都符合營收條件（上界）
        with eng.connect() as c:
            gone = {r[0] for r in c.execute(text("""
                select stock_id from market.price group by stock_id
                having max(date) < (select max(date) from market.price) - interval '14 days'
            """)).fetchall()}
        norev = [s for s in keep if s in gone and yoy[s].notna().sum() == 0]
        price_only = (extra["liquid"] & (close > extra["hi60_prior"])
                      & (extra["d5"] >= a.d5)
                      & extra["vol_r"].ge(a.vol_lo) & extra["vol_r"].le(a.vol_hi))
        price_only = price_only.fillna(False)
        price_only.loc[:pd.Timestamp(a.start)] = False
        miss = price_only[[s for s in norev if s in price_only.columns]]
        _, miss_ev = to_events(miss, ret, a.horizon, {}, **event_args)
        print("\n=== 存活偏誤上界 ===")
        print(f"補不回月營收的已下市公司 {len(norev)} 檔，其中符合**價格條件**的事件 "
              f"{len(miss_ev)} 個")
        if len(miss_ev):
            print(pd.DataFrame([describe(miss_ev, "缺漏事件（上界）")])
                  .set_index("組").to_string())
            base = ev["r"].mean()
            allin = pd.concat([ev, miss_ev], ignore_index=True)["r"].mean()
            # **全數併入不是上界**——未知的營收條件可以只讓「較差的那些」通過。真正的
            # 歷史最差情境是逐一加入最差事件、取均值最低的那個子集。獨立審查指出。
            srt = miss_ev.sort_values("r")
            worst, k_worst = base, 0
            for k in range(1, len(srt) + 1):
                m = pd.concat([ev, srt.head(k)], ignore_index=True)["r"].mean()
                if m < worst:
                    worst, k_worst = m, k
            print(f"\n候選池均值 {base * 100:+.2f}%")
            print(f"  全部 {len(miss_ev)} 筆併入（all-pass 情境）: {allin * 100:+.2f}% "
                  f"（{(allin - base) * 100:+.2f}pp）")
            print(f"  **最差 {k_worst} 筆併入（真正的歷史最差子集）: {worst * 100:+.2f}% "
                  f"（{(worst - base) * 100:+.2f}pp）**")
            iid = miss_ev["r"].std() / np.sqrt(len(miss_ev)) * 1.96
            print(f"  缺漏事件本身只有 {len(miss_ev)} 筆、來自 "
                  f"{miss_ev['stock_id'].nunique()} 檔，均值 IID 95% 區間 "
                  f"{(miss_ev['r'].mean() - iid) * 100:+.1f}% ~ "
                  f"{(miss_ev['r'].mean() + iid) * 100:+.1f}%——**不可外推為未來上界**")
        else:
            print("（沒有任何缺漏公司符合價格條件——這個方向的偏誤上界為 0）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
