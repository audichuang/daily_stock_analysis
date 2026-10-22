#!/usr/bin/env python3
"""月營收動能轉弱（降速／斷創高／YoY 翻負）能不能當「不進場濾網」或「出場訊號」。唯讀。

三個量測：

1. **全市場橫斷面**：每月營收公布後第一個可用交易日 D，流動股之中「有旗標」與「無旗標」
   的 D+1 開盤 → D+h 收盤淨報酬差，逐月算差再平均。
2. **持有中的強勢股（出場語意）**：同 1，但只看上一期 3 個月平均 YoY ≥ 20% 的股票——
   這些是波段池會抱著的票，問的是「新營收降速時要不要走」。
3. **突破候選池**：重建 `measure_signal_forward.py` 的候選池（同參數），
   (a) 進場濾網：訊號日最新營收有旗標 vs 無旗標的 h 日淨報酬；
   (b) 出場：60 日持有期間每次營收公布後，「剩餘持有報酬」有旗標 vs 無旗標。

**公告日是假的**：`market.monthly_revenue.announce_date` 全部 = 營收月次月 10 日（法定期限）。
實際多數公司 5~9 日就公布（偏保守、晚看到），逾期申報與主管機關展延才會偷看未來；
已知的展延寫在 `KNOWN_DEADLINE_EXTENSIONS`，有效公告日取兩者較晚者。
可用日沿用 `pit_revenue_panel` 的語意：公告日之後的第一個交易日（嚴格 `<`）收盤可見，
隔日開盤進場。

CI 用月區塊 bootstrap（以月為單位重抽、區塊 3 個月）；區間跨零一律 inconclusive。

用法：
    uv run --env-file .env python scripts/measure_revenue_momentum.py
    uv run --env-file .env python scripts/measure_revenue_momentum.py --include-otc-revenue
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from market_data.db import database_url  # noqa: E402
from measure_signal_forward import (  # noqa: E402
    DEFAULT_POSITION_NOTIONAL,
    build_signals,
    forward_returns,
    load,
    paired_block_bootstrap,
    pit_revenue_panel,
    to_events,
)
from screen_tw import exclude_otc_revenue  # noqa: E402
from src.services.tw_backtest_context import revenue_features  # noqa: E402  與 live prompt 共用
from tw_trade_costs import round_trip_return  # noqa: E402

# 營收月 → 主管機關展延後的實際期限。2020-01 營收因疫情展延至 2/15（中央社 2020-02-03）。
KNOWN_DEADLINE_EXTENSIONS = {pd.Timestamp("2020-01-01"): pd.Timestamp("2020-02-15")}
FLAGS = ("decel_lt0", "decel_le20", "mom_neg", "broke_record_streak", "yoy_turn_neg")


def effective_announce(rv):
    """有效公告日 = max(DB 的佔位公告日, 已知展延期限)。"""
    ext = rv["revenue_month"].map(KNOWN_DEADLINE_EXTENSIONS)
    out = rv.copy()
    out["announce_date"] = pd.concat([rv["announce_date"], ext], axis=1).max(axis=1).astype(
        rv["announce_date"].dtype)
    return out


def candidate_yoy_frame(rv):
    """候選池用的 (stock_id, date, yoy)：date 取 effective_announce 之後的公告日。"""
    return rv.dropna(subset=["yoy"])[["stock_id", "announce_date", "yoy"]].rename(
        columns={"announce_date": "date"})


def month_diffs(df, flag, month_col="month"):
    """逐月 mean(有旗標) − mean(無旗標)；某月缺一臂就不算那個月。"""
    d = df.dropna(subset=[flag, "r"])
    g = d.groupby([month_col, flag])["r"].mean().unstack()
    if 1.0 not in g or 0.0 not in g:
        return pd.Series(dtype=float)
    return (g[1.0] - g[0.0]).dropna()


def month_ci(diffs, months, n, seed, block=3):
    ev = pd.DataFrame({"date": diffs.index, "diff": diffs.to_numpy()})
    return paired_block_bootstrap(ev, pd.Index(months), n=n, block=block, seed=seed)


def fmt_row(label, df, flag, months, a):
    d = df.dropna(subset=[flag, "r"])
    diffs = month_diffs(d, flag)
    ci = month_ci(diffs, months, a.bootstrap, a.bootstrap_seed) if a.bootstrap else None
    if ci is None:
        ci_s, verdict = "n/a", "inconclusive"
    else:
        ci_s = f"{ci[0] * 100:+.2f}~{ci[1] * 100:+.2f}"
        verdict = "inconclusive" if ci[0] <= 0 <= ci[1] else ("轉弱較差" if ci[1] < 0 else "轉弱較好")
    return {"組": label, "旗標": flag, "n旗標": int((d[flag] == 1).sum()),
            "n無": int((d[flag] == 0).sum()), "月數": len(diffs),
            "有旗標均值%": round(d.loc[d[flag] == 1, "r"].mean() * 100, 2),
            "無旗標均值%": round(d.loc[d[flag] == 0, "r"].mean() * 100, 2),
            "逐月差均值%": round(diffs.mean() * 100, 2) if len(diffs) else np.nan,
            "95%CI%": ci_s, "判定": verdict}


def net(r, a):
    """毛報酬 → 扣來回成本淨報酬（成本走共用 round_trip_return）。"""
    return r.map(lambda x: round_trip_return(
        1.0, 1.0 + float(x), entry_notional=a.position_notional) if pd.notna(x) else np.nan)


def release_cross_section(feat, piv, liquid, horizons, a):
    """每筆營收公告對齊到第一個可見交易日，取該格的 h 日前瞻報酬。"""
    cal = pd.DataFrame({"eff": piv["close"].index})
    x = pd.merge_asof(feat.dropna(subset=["announce_date"]).sort_values("announce_date"), cal,
                      left_on="announce_date", right_on="eff", direction="forward",
                      allow_exact_matches=False).dropna(subset=["eff"])
    x = x[x["stock_id"].isin(piv["close"].columns) & (x["eff"] >= pd.Timestamp(a.start))]
    liq = liquid.stack()
    liq.index.names = ["eff", "stock_id"]
    x = x.join(liq.rename("liq"), on=["eff", "stock_id"])
    x = x[x["liq"].fillna(False).astype(bool)].copy()
    x["month"] = x["announce_date"].dt.to_period("M").dt.to_timestamp()
    out = {}
    for h in horizons:
        ret, _ = forward_returns(piv, h, "last")
        s = ret.stack()
        s.index.names = ["eff", "stock_id"]
        y = x.join(s.rename("gross"), on=["eff", "stock_id"]).dropna(subset=["gross"])
        y["r"] = net(y["gross"], a)
        out[h] = y
    return out


def pool_exit_rows(ev, feat_panels, piv, h_hold, a):
    """持有期間每次營收公布後的「剩餘持有報酬」：可見日隔日開盤 → 原定出場日收盤。"""
    close, open_ = piv["close"].ffill(), piv["open"]
    idx = piv["close"].index
    n = len(idx)
    # 可見日 = 公告日之後的第一個交易日（與 pit_revenue_panel 的嚴格 < 同語意）
    ann = pd.Series(sorted(feat_panels["_ann"]))
    vis = idx.searchsorted(ann, side="right")
    vis_set = sorted({int(v) for v in vis if v < n})
    rows = []
    for _, e in ev.iterrows():
        ti, sid = int(e["ti"]), e["stock_id"]
        end = ti + h_hold
        if end >= n:
            continue
        for vi in vis_set:
            if vi <= ti or vi + 1 >= end:
                continue
            ent = open_.iat[vi + 1, open_.columns.get_loc(sid)]
            ext = close.iat[end, close.columns.get_loc(sid)]
            if pd.isna(ent) or pd.isna(ext) or ent <= 0:
                continue
            row = {"stock_id": sid, "month": idx[vi].to_period("M").to_timestamp(),
                   "r": ext / ent - 1}
            for f in FLAGS:
                row[f] = feat_panels[f].iat[vi, feat_panels[f].columns.get_loc(sid)]
            rows.append(row)
    return pd.DataFrame(rows)


def main(argv=None):
    p = argparse.ArgumentParser(description="月營收動能轉弱的前瞻報酬量測（唯讀）")
    p.add_argument("--start", default="2019-01-01")
    p.add_argument("--end", default=None, help="預設 market.price 最後一日")
    p.add_argument("--horizons", default="5,10,20")
    p.add_argument("--pool-hold", type=int, default=60, help="候選池持有交易日（出場量測）")
    p.add_argument("--min-turnover", type=float, default=2.0, help="日均額門檻（億）")
    p.add_argument("--decel-pp", type=float, default=20.0, help="大幅降速門檻（百分點）")
    p.add_argument("--strong-yoy3", type=float, default=20.0, help="強勢股：前 3 月平均 YoY 下限")
    p.add_argument("--bootstrap", type=int, default=2000)
    p.add_argument("--bootstrap-seed", type=int, default=42)
    p.add_argument("--position-notional", type=float, default=DEFAULT_POSITION_NOTIONAL)
    p.add_argument("--include-otc-revenue", action="store_true",
                   help="月營收放入上櫃（預設上市口徑，與 screen_tw 相同）")
    a = p.parse_args(argv)
    horizons = [int(h) for h in a.horizons.split(",")]

    eng = create_engine(database_url(), connect_args={
        "options": "-c default_transaction_read_only=on"})
    if a.end is None:
        with eng.connect() as c:
            a.end = str(c.execute(text("select max(date) from market.price")).scalar())
    piv, _, _ = load(eng, a.start, a.end, a.include_otc_revenue)
    keep = [s for s in piv["close"].columns
            if len(s) == 4 and s.isdigit() and not s.startswith(("00", "91"))]
    piv = {k: v[keep] for k, v in piv.items()}
    with eng.connect() as c:
        rv = pd.read_sql(text(
            "select stock_id, revenue_month, revenue, yoy, mom, announce_date "
            "from market.monthly_revenue where announce_date <= :e"), c,
            params={"e": a.end}, parse_dates=["revenue_month", "announce_date"])
    if not a.include_otc_revenue:
        rv = exclude_otc_revenue(rv)
    rv = effective_announce(rv)
    feat = revenue_features(rv, a.decel_pp)
    idx, cols = piv["close"].index, piv["close"].columns

    print(f"樣本 {a.start} ~ {a.end}　池 {len(keep)} 檔　流動門檻 {a.min_turnover} 億　"
          f"上櫃營收={'含' if a.include_otc_revenue else '不含'}")
    print(f"announce_date 日期分布：{feat['announce_date'].dt.day.value_counts().head(3).to_dict()}"
          "（佔位＝10 日；展延月已改成較晚者）\n")

    # 候選池也要用修正後的公告日：load() 回的營收是 DB 佔位日，展延月（2020-01）會提前看到營收
    sig, extra = build_signals(piv, pit_revenue_panel(candidate_yoy_frame(rv), idx, cols), a.min_turnover * 1e8,
                               0.05, 1.3, 2.0, 20.0)
    sig.loc[:pd.Timestamp(a.start)] = False
    liquid = extra["liquid"].fillna(False)

    months = pd.period_range(a.start, a.end, freq="M").to_timestamp()
    xs = release_cross_section(feat, piv, liquid, horizons, a)
    rows = []
    for h, y in xs.items():
        strong = y[y["yoy3"] >= a.strong_yoy3]
        for f in FLAGS:
            rows.append(fmt_row(f"全市場 h={h}", y, f, months, a))
            rows.append(fmt_row(f"強勢股(yoy3≥{a.strong_yoy3:g}) h={h}", strong, f, months, a))
    print("=== 1/2. 營收公布後橫斷面（逐月 有旗標−無旗標，淨報酬）===")
    print(pd.DataFrame(rows).set_index("組").to_string(), "\n")

    # PIT 旗標面板（候選池用）
    panels = {f: pit_revenue_panel(feat.assign(yoy=feat[f]).rename(
        columns={"announce_date": "date"})[["stock_id", "date", "yoy"]].dropna(),
        idx, cols) for f in FLAGS}
    rows = []
    for h in horizons + [a.pool_hold]:
        ret, _ = forward_returns(piv, h, "last")
        _, ev = to_events(sig, ret, h, panels, entry_notional=a.position_notional)
        if not len(ev):
            continue
        ev["month"] = ev["date"].dt.to_period("M").dt.to_timestamp()
        for f in FLAGS:
            rows.append(fmt_row(f"候選池進場 h={h} (事件{len(ev)})", ev, f, months, a))
    print("=== 3a. 突破候選池：訊號日最新營收有旗標 vs 無旗標（事件級去重）===")
    print(pd.DataFrame(rows).set_index("組").to_string(), "\n")

    ret, _ = forward_returns(piv, a.pool_hold, "last")
    _, ev = to_events(sig, ret, a.pool_hold, {}, entry_notional=a.position_notional)
    panels["_ann"] = feat["announce_date"].dropna().unique()
    ex = pool_exit_rows(ev, panels, piv, a.pool_hold, a)
    rows = [fmt_row(f"候選池持有中 剩餘至第{a.pool_hold}日(毛)", ex, f, months, a) for f in FLAGS]
    print("=== 3b. 突破候選池持有中：營收公布後剩餘持有報酬（下方單臂列為負才代表該出場）===")
    print(pd.DataFrame(rows).set_index("組").to_string())
    for f in FLAGS:
        s = ex.loc[ex[f] == 1]
        if len(s):
            ci = month_ci(s.groupby("month")["r"].mean(), months, a.bootstrap, a.bootstrap_seed)
            ci_s = "n/a" if ci is None else f"{ci[0] * 100:+.2f}~{ci[1] * 100:+.2f}"
            print(f"  {f}：有旗標後剩餘報酬均值 {s['r'].mean() * 100:+.2f}%（n={len(s)}），"
                  f"逐月均值 95%CI {ci_s}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
