#!/usr/bin/env python3
"""探索性回測佇列（final-decision 第 11 項）：兩個事先寫定判準的實驗。

- ``reversal``：C6-21(1) 五日產業相對輸家反轉。每 h 個交易日一期、不重疊：訊號日 t 選出
  「過去 L 日報酬減同產業中位數」最差的分位，t+1 開盤買、t+h 收盤賣，扣一次來回成本；
  與 0050 同窗報酬逐期配對。
- ``ma-exit``：G3-25 跌破 25MA 出場＋sustain 3 日。進場與池子完全沿用
  ``portfolio_walkforward.py`` 預設，只換出場（``simulate(exit_ma=...)``）。

判準（三項全勝才算支持）、規格、偏誤寫在 ``docs/research/2026-10-28-explore-reversal-ma25.md``
第 0 節，跑之前就已 commit。敏感度只描述，不從中挑最好的一組改寫結論。

資料唯讀：連線一律 ``default_transaction_read_only=on``（本腳本另掛 connect 事件，不靠呼叫端）。

用法（``DATABASE_URL`` 由主 checkout 的 ``.env`` 匯出；``STORAGE_DATABASE_URL=''``）：
    uv run --frozen python scripts/research_explore_queue.py reversal
    uv run --frozen python scripts/research_explore_queue.py ma-exit
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import event

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from market_data.adjust import is_common_stock  # noqa: E402
from market_data.db import get_engine  # noqa: E402
from measure_signal_forward import (  # noqa: E402
    apply_thresholds, factors, forward_returns, load, paired_block_bootstrap,
    pit_revenue_panel,
)
from portfolio_walkforward import (  # noqa: E402
    bench_0050, build_parser as walkforward_parser, daily_diff_ci, daily_scores,
    ma_line, pool_codes, simulate,
)
from tw_trade_costs import TRADING_DAYS_PER_YEAR as TRADING_DAYS, round_trip_return  # noqa: E402

BENCH = "0050"
DR_INDUSTRY = "91"                      # 存託憑證，不是本地普通股產業
# 2025-04-07～05-23 借券融券暫時管制：只旗標分列，不切分（registry 註記）
RESTRICTED = (pd.Timestamp("2025-04-07"), pd.Timestamp("2025-05-23"))
ENTRY_NOTIONAL = 200_000.0              # 平盤來回 0.882%（見 docs 第 0.3 節）


# ---------------------------------------------------------------- 純函式

def industry_relative(r, industry, eligible, min_group=5):
    """單日的產業相對報酬：``r − 同日同產業 r 的中位數``。

    ``r``／``eligible`` 是以 stock_id 為索引的 Series，``industry`` 是 stock_id→產業別。
    只用合格（``eligible`` 為真且 ``r`` 有值、有產業別）的股票；當日合格家數 < ``min_group``
    的產業整個剔除（中位數由兩三檔算出來，「相對」就只是彼此互減）。
    """
    ok = eligible.reindex(r.index).fillna(False).astype(bool) & r.notna()
    ind = industry.reindex(r.index)
    ok &= ind.notna()
    df = pd.DataFrame({"r": r[ok], "ind": ind[ok]})
    if not len(df):
        return pd.Series(dtype=float)
    size = df.groupby("ind")["r"].transform("size")
    df = df[size >= min_group]
    med = df.groupby("ind")["r"].transform("median")
    return (df["r"] - med).astype(float)


def bottom_quantile(rel, q):
    """``rel`` 最低的 ``q`` 比例（至少一檔）；同值以 stock_id 排序，結果可重現。"""
    if not len(rel):
        return []
    n = max(1, int(np.floor(len(rel) * q)))
    order = rel.sort_index().sort_values(kind="mergesort")
    return list(order.index[:n])


def rebalance_dates(index, start, step, offset=0):
    """從 ``start`` 之後第一個交易日起、偏移 ``offset`` 後每 ``step`` 個交易日一個訊號日。"""
    i0 = int(index.searchsorted(pd.Timestamp(start)))
    return index[i0 + offset::step]


def overlaps_restricted(index, t, h, window=RESTRICTED):
    """持有窗口 t+1 … t+h 是否碰到借券融券暫時管制期。"""
    i = int(index.get_loc(t))
    lo, hi = index[min(i + 1, len(index) - 1)], index[min(i + h, len(index) - 1)]
    return bool(lo <= window[1] and hi >= window[0])


def period_stats(rets, periods_per_year):
    """期報酬序列的總報酬、年化 Sharpe、最大回撤（皆為小數，回撤為負值）。"""
    rets = pd.Series(rets, dtype=float).dropna()
    if len(rets) < 2:
        return {"total": np.nan, "sharpe": np.nan, "mdd": np.nan}
    curve = pd.Series(np.r_[1.0, (1 + rets).cumprod().to_numpy()])
    sd = rets.std()
    return {"total": float(curve.iloc[-1] - 1),
            "sharpe": float(rets.mean() / sd * np.sqrt(periods_per_year)) if sd else np.nan,
            "mdd": float((curve / curve.cummax() - 1).min())}


def curve_stats(eq):
    """組合權益曲線（原始本金正規化）的 Sharpe 與最大回撤，口徑同 ``portfolio_walkforward.metrics``。"""
    return period_stats(pd.Series(np.r_[1.0, eq.astype(float).to_numpy()]).pct_change().dropna(),
                        TRADING_DAYS)


def verdict(mean_diff, ci, strat, bench):
    """事先寫定的三項全勝判準（docs 第 0.2 節）。

    任一點估計輸（超額 ≤ 0、Sharpe 不高於、回撤不淺於 0050）→ 不支持；三項點估計都贏但
    成對超額區間下界 ≤ 0 或算不出區間 → inconclusive；全部成立 → 探索性支持。
    """
    if not (mean_diff > 0 and strat["sharpe"] > bench["sharpe"] and strat["mdd"] > bench["mdd"]):
        return "不支持"
    if ci is None or not ci[0] > 0:
        return "inconclusive"
    return "探索性支持"


# ---------------------------------------------------------------- reversal

def reversal_periods(piv, industry, *, start, lookback, hold, q, min_turnover,
                     offset=0, min_group=5, entry_notional=ENTRY_NOTIONAL):
    """逐期的策略淨報酬、0050 同窗報酬、選股數、合格覆蓋率與管制旗標。"""
    close = piv["close"]
    idx = close.index
    common = [s for s in close.columns if is_common_stock(s)]
    sub = {k: v[common] for k, v in piv.items()}
    f = factors(sub, min_turnover)
    r = sub["close"].pct_change(lookback, fill_method=None)
    ret, _ = forward_returns(sub, hold, "last")
    bret, _ = forward_returns({k: v[[BENCH]] for k, v in piv.items()}, hold, "last")
    has_ind = industry.reindex(common).notna()
    rows = []
    for t in rebalance_dates(idx, start, hold, offset):
        if pd.isna(bret.at[t, BENCH]):
            continue                                   # 右端截斷：報酬未知，不補
        live = f["liquid"].loc[t].fillna(False).astype(bool) & sub["close"].loc[t].notna()
        elig = live & has_ind
        rel = industry_relative(r.loc[t], industry, elig, min_group)
        picks = bottom_quantile(rel, q)
        net = [round_trip_return(1.0, 1.0 + float(ret.at[t, s]), entry_notional=entry_notional)
               for s in picks if pd.notna(ret.at[t, s])]
        gross = [float(ret.at[t, s]) for s in picks if pd.notna(ret.at[t, s])]
        rows.append({"date": t, "strat": float(np.mean(net)) if net else 0.0,
                     "gross": float(np.mean(gross)) if gross else 0.0,
                     "bench": float(bret.at[t, BENCH]), "n_pick": len(net),
                     "coverage": float(len(rel) / live.sum()) if live.sum() else np.nan,
                     "restricted": overlaps_restricted(idx, t, hold)})
    df = pd.DataFrame(rows)
    if len(df):
        df["diff"] = df["strat"] - df["bench"]
    return df


def evaluate_periods(df, hold, n_boot=2000, block=4, seed=42):
    ppy = TRADING_DAYS / hold
    s, b = period_stats(df["strat"], ppy), period_stats(df["bench"], ppy)
    ci = paired_block_bootstrap(df[["date", "diff"]], pd.Index(df["date"]),
                                n=n_boot, block=block, seed=seed)
    return {"periods": len(df), "mean_diff": float(df["diff"].mean()), "ci": ci,
            "strat": s, "bench": b, "verdict": verdict(df["diff"].mean(), ci, s, b),
            "mean_gross_diff": float((df["gross"] - df["bench"]).mean()),
            "mean_diff_ex_restricted": float(df.loc[~df["restricted"], "diff"].mean()),
            "n_restricted": int(df["restricted"].sum()),
            "median_picks": float(df["n_pick"].median()),
            "median_coverage": float(df["coverage"].median())}


def _fmt(label, e):
    ci = e["ci"]
    ci_s = "n/a" if ci is None else f"[{ci[0] * 100:+.2f}, {ci[1] * 100:+.2f}]"
    return (f"{label:<28} 期數 {e['periods']:>4}  超額 {e['mean_diff'] * 100:+.2f}%/期 {ci_s}  "
            f"Sharpe {e['strat']['sharpe']:.2f} vs {e['bench']['sharpe']:.2f}  "
            f"MDD {e['strat']['mdd'] * 100:.1f}% vs {e['bench']['mdd'] * 100:.1f}%  "
            f"總報酬 {e['strat']['total'] * 100:+.0f}% vs {e['bench']['total'] * 100:+.0f}%  "
            f"→ {e['verdict']}  （未扣成本超額 {e['mean_gross_diff'] * 100:+.2f}%/期；不含管制期超額 {e['mean_diff_ex_restricted'] * 100:+.2f}%，"
            f"管制期 {e['n_restricted']} 期；中位選股 {e['median_picks']:.0f}、覆蓋 "
            f"{e['median_coverage'] * 100:.0f}%）")


REVERSAL_PRIMARY = dict(lookback=5, hold=5, q=0.20, min_turnover=2e8, offset=0)
REVERSAL_SENSITIVITY = [
    ("分位 10%", dict(q=0.10)), ("分位 30%", dict(q=0.30)),
    ("回看 3 日", dict(lookback=3)), ("回看 10 日", dict(lookback=10)),
    ("持有 3 日（3 日一期）", dict(hold=3)),
    ("日均額 ≥1 億", dict(min_turnover=1e8)), ("日均額 ≥5 億", dict(min_turnover=5e8)),
    ("起算偏移 1", dict(offset=1)), ("起算偏移 2", dict(offset=2)),
    ("起算偏移 3", dict(offset=3)), ("起算偏移 4", dict(offset=4)),
]


def run_reversal(a):
    eng = _readonly_engine()
    piv, _, info = load(eng, a.sub_start, a.end)
    info = info[info["industry"].notna() & (info["industry"].astype(str) != DR_INDUSTRY)]
    industry = info.set_index("stock_id")["industry"].astype(str)
    common_n = sum(is_common_stock(s) for s in piv["close"].columns)
    print(f"價格面板 {piv['close'].index[0].date()} ~ {piv['close'].index[-1].date()}；"
          f"四位數普通股 {common_n} 檔，stock_info 有產業別者 "
          f"{sum(s in industry.index for s in piv['close'].columns if is_common_stock(s))} 檔"
          f"（今天的上市快照：存活偏誤＋產業別前視，上櫃不在宇宙內）")
    print(f"平盤來回成本 {-round_trip_return(1.0, 1.0, entry_notional=ENTRY_NOTIONAL) * 100:.3f}%"
          f"；bootstrap {a.bootstrap} 次、block=4 期、seed {a.seed}\n")

    def one(label, _start=None, _end=None, **over):
        spec = {**REVERSAL_PRIMARY, **over}
        start, end = _start or a.start, _end
        df = reversal_periods(piv, industry, start=start, **spec)
        if end is not None:
            df = df[df["date"] <= pd.Timestamp(end)]
        else:
            df = df[df["date"] >= pd.Timestamp(a.start)]
        print(_fmt(label, evaluate_periods(df, spec["hold"], a.bootstrap, seed=a.seed)))

    print("=== 主規格（事前寫定）===")
    one("主：回看5 持有5 分位20% 2億")
    print("\n=== 敏感度（只描述）===")
    for label, over in REVERSAL_SENSITIVITY:
        one(label, **over)
    one("子期 2016～2019", _start=a.sub_start, _end="2019-12-31")
    return 0


# ---------------------------------------------------------------- ma-exit

MA_SENSITIVITY = [
    ("25MA sustain 1", dict(window=25, sustain=1, cap=True)),
    ("25MA sustain 5", dict(window=25, sustain=5, cap=True)),
    ("20MA sustain 3", dict(window=20, sustain=3, cap=True)),
    ("60MA sustain 3", dict(window=60, sustain=3, cap=True)),
    ("25MA sustain 3 無到期上限", dict(window=25, sustain=3, cap=False)),
]


def run_ma_exit(a):
    w = walkforward_parser().parse_args(["--start", a.wf_start, "--end", a.wf_end])
    eng = _readonly_engine()
    piv_full, rv, info = load(eng, w.start, w.end, w.include_otc_revenue)
    keep = pool_codes(piv_full["close"].columns, info, w.include_tib)
    piv = {k: v[keep] for k, v in piv_full.items()}
    close = piv["close"]
    yoy = pit_revenue_panel(rv, close.index, close.columns)
    f = factors(piv, w.min_turnover * 1e8)
    sig = apply_thresholds(close, f, yoy, w.d5, w.vol_lo, w.vol_hi, w.yoy)
    sig.loc[:pd.Timestamp(w.start)] = False
    run = dict(rank=w.rank, seed=w.seed, delisting=w.delisting, scores=daily_scores(sig, f, yoy),
               capital=w.capital, fee_discount=w.fee_discount)

    def sim(exit_ma=None, cap=True):
        return simulate(piv, sig, f, yoy, w.horizon, w.slots, w.start, w.end,
                        exit_ma=exit_ma, time_cap=cap, **run)

    eq0, tr0, _, _ = sim()
    bench = bench_0050(piv_full, eq0.index, capital=w.capital, fee_discount=w.fee_discount)
    bstats = curve_stats(bench)
    print(f"樣本 {eq0.index[0].date()} ~ {eq0.index[-1].date()}　池 {len(keep)} 檔　"
          f"空位 {w.slots}　本金 {w.capital:,.0f}　bootstrap {a.bootstrap} 次、block=60、seed {w.seed}")
    print(f"0050 買進持有：Sharpe {bstats['sharpe']:.2f}　MDD {bstats['mdd'] * 100:.1f}%　"
          f"總報酬 {bstats['total'] * 100:+.0f}%\n")

    def report(label, eq, tr):
        s = curve_stats(eq)
        diff, ci = daily_diff_ci(eq, bench, 60, a.bootstrap, w.seed)
        d0, ci0 = daily_diff_ci(eq, eq0, 60, a.bootstrap, w.seed)
        ex = diff[~((diff.index >= RESTRICTED[0]) & (diff.index <= RESTRICTED[1]))]
        reasons = tr["exit_reason"].value_counts().to_dict() if len(tr) else {}
        hold = ((tr["exit_date"] - tr["entry_date"]).dt.days.median() if len(tr) else np.nan)
        fmt = (lambda c: "n/a" if c is None else f"[{c[0] * 1e4:+.2f}, {c[1] * 1e4:+.2f}]")
        print(f"{label:<26} Sharpe {s['sharpe']:.2f}  MDD {s['mdd'] * 100:.1f}%  "
              f"總報酬 {s['total'] * 100:+.0f}%  對0050 {diff.mean() * 1e4:+.2f}bp/日 {fmt(ci)}"
              f"（不含管制期 {ex.mean() * 1e4:+.2f}）  對固定60日 {d0.mean() * 1e4:+.2f}bp/日 "
              f"{fmt(ci0)}  成交 {len(tr)}  出場 {reasons}  持有中位 {hold:.0f} 曆日  "
              f"→ {verdict(diff.mean(), ci, s, bstats)}")

    print("=== 基準：現行固定 60 日持有（先重現 Sharpe≈1.19 vs 0050 1.23）===")
    report("固定 60 日", eq0, tr0)
    print("\n=== 主規格（事前寫定）===")
    eq, tr, _, _ = sim((ma_line(close, 25), 3), True)
    report("25MA sustain 3（60 日上限）", eq, tr)
    print("\n=== 敏感度（只描述）===")
    for label, o in MA_SENSITIVITY:
        eq, tr, _, _ = sim((ma_line(close, o["window"]), o["sustain"]), o["cap"])
        report(label, eq, tr)
    return 0


# ---------------------------------------------------------------- CLI

def _readonly_engine():
    eng = get_engine()

    @event.listens_for(eng, "connect")
    def _ro(dbapi_conn, _rec):  # pragma: no cover - 需要真實連線
        cur = dbapi_conn.cursor()
        cur.execute("SET default_transaction_read_only = on")
        cur.close()
    return eng


def build_parser():
    p = argparse.ArgumentParser(description="探索性回測佇列：產業相對輸家反轉、均線出場（唯讀）")
    p.add_argument("--bootstrap", type=int, default=2000)
    p.add_argument("--seed", type=int, default=42)
    sp = p.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("reversal", help="C6-21(1) 五日產業相對輸家反轉 vs 0050")
    r.add_argument("--start", default="2020-01-01", help="主樣本訊號起日")
    r.add_argument("--sub-start", default="2016-01-01", help="資料載入起日／2016～2019 子期起日")
    r.add_argument("--end", default=None, help="資料迄日（預設＝今天）")
    m = sp.add_parser("ma-exit", help="G3-25 跌破均線出場 vs 固定 60 日與 0050")
    m.add_argument("--wf-start", default="2020-01-01")
    m.add_argument("--wf-end", default="2026-07-24")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.cmd == "reversal":
        a.end = a.end or pd.Timestamp.today().strftime("%Y-%m-%d")
        return run_reversal(a)
    return run_ma_exit(a)


if __name__ == "__main__":
    raise SystemExit(main())
