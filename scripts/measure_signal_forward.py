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


def describe(ev, label):
    r = ev["r"]
    win, loss = r[r > 0], r[r <= 0]
    rr = win.mean() / abs(loss.mean()) if len(loss) and loss.mean() else float("nan")
    return {
        "組": label, "事件": len(ev),
        "均值": f"{r.mean() * 100:+.2f}%", "中位": f"{r.median() * 100:+.2f}%",
        "勝率": f"{(r > 0).mean() * 100:.1f}%",
        "賺賠比": f"{rr:.2f}", "兩平勝率": f"{1 / (1 + rr) * 100:.1f}%",
        "P(≥30%)": f"{(r >= .3).mean() * 100:.1f}%", "P(≤-20%)": f"{(r <= -.2).mean() * 100:.1f}%",
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
    raw, ev = to_events(sig, ret, a.horizon,
                        {k: extra[k] for k in ("d5", "vol_r")}, **event_args)

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
