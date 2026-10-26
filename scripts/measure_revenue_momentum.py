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
法定期限（含展延、2026 起保險類 15 日）在 `market_data.revenue_deadline`，有效公告日取兩者較晚者。
可用日沿用 `pit_revenue_panel` 的語意：公告日之後的第一個交易日（嚴格 `<`）收盤可見，
隔日開盤進場。

CI 用月區塊 bootstrap（以月為單位重抽、區塊 3 個月）；區間跨零一律 inconclusive。

用法：
    uv run --env-file .env python scripts/measure_revenue_momentum.py
    uv run --env-file .env python scripts/measure_revenue_momentum.py --include-otc-revenue
    # SUS／營收÷歷史最高 當候選池的補充或取代 YoY≥20（只跑這段，不印上面三段）
    uv run --env-file .env python scripts/measure_revenue_momentum.py --experiment surprise \
        --start 2020-01-01 --end 2026-07-24
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from market_data.adjust import is_common_stock  # noqa: E402
from market_data.db import database_url  # noqa: E402
from market_data.revenue_deadline import apply_revenue_deadline  # noqa: E402
from measure_signal_forward import (  # noqa: E402
    DEFAULT_POSITION_NOTIONAL,
    HIT_THRESHOLD,
    apply_thresholds,
    build_signals,
    forward_returns,
    load,
    paired_block_bootstrap,
    pit_revenue_panel,
    to_events,
    two_arm_block_bootstrap,
)
from screen_tw import exclude_otc_revenue  # noqa: E402
from src.services.tw_backtest_context import (  # noqa: E402  與 live prompt 共用
    RECORD_MIN_HISTORY,
    revenue_features,
)
from tw_trade_costs import round_trip_return  # noqa: E402

FLAGS = ("decel_lt0", "decel_le20", "mom_neg", "broke_record_streak", "yoy_turn_neg")

# --experiment surprise：SUS 與營收÷歷史最高（docs/research/2026-10-26-exp-revenue-sus.md 事先登記）
SUS_WINDOW = 24           # 過去 24 個月的季節差估漂移與標準差
SUS_MIN_PERIODS = 18      # 至少 18 個有效季節差才算 SUS
TOP_QUANTILE = 0.8        # 同營收月橫斷面百分位 > 80%＝前五分之一
# 閘門名 → (特徵欄, 判定方式)；前四個是主檢定用的百分位閘門與探索用的絕對門檻
SURPRISE_GATES = {
    "sus_top20": ("sus", "top"),
    "ath_top20": ("ath_ratio", "top"),
    "sus_ge1": ("sus", 1.0),
    "ath_ge1": ("ath_ratio", 1.0),
    "sus_pit_top20": ("sus_pit", "top"),
}
PRIMARY_GATES = ("sus_top20", "ath_top20")
# 事先登記的更正前視否決（研究文件 §0.5）：主檢定閘門 → 它的 PIT 穩健性變體
PIT_VETO = {"sus_top20": "sus_pit_top20"}
SURVIVED = "通過且存活"
PIT_VETOED = "通過但 SUS_pit 方向相反（更正前視污染）→ 不存活"
PRIMARY_LEVEL = 95.0
BONFERRONI_LEVEL = 98.75   # 4 個主檢定（2 訊號 × 補充／取代）


def effective_announce(rv):
    """有效公告日 = max(DB 的佔位公告日, 法定期限)；期限規則在 market_data.revenue_deadline。"""
    return apply_revenue_deadline(rv, date_col="announce_date")


def correct_pit_dates(rv_pit):
    """msf.load() 形狀的 (stock_id, date, yoy)：套共用法定期限（重複套用結果不變）。

    有 revenue_month 欄就用它，否則由佔位日「次月 10 日」推回營收月。
    """
    return apply_revenue_deadline(rv_pit, date_col="date")


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
    """持股自己的營收公布後，量「可見日隔日開盤 → 原定出場日收盤」的剩餘報酬。

    ``_ann`` 是以 stock_id 為索引的公告日 Series；同一事件、同一可見交易日只算一次。
    """
    close, open_ = piv["close"].ffill(), piv["open"]
    idx = piv["close"].index
    n = len(idx)
    # 可見日 = 公告日之後的第一個交易日（與 pit_revenue_panel 的嚴格 < 同語意）
    vis_by_stock = {}
    for sid, ann in feat_panels["_ann"].dropna().groupby(level=0):
        vis = idx.searchsorted(ann, side="right")
        vis_by_stock[sid] = sorted({int(v) for v in vis if v < n})
    rows = []
    for _, e in ev.iterrows():
        ti, sid = int(e["ti"]), e["stock_id"]
        end = ti + h_hold
        if end >= n:
            continue
        for vi in vis_by_stock.get(sid, ()):
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
    return pd.DataFrame(rows, columns=["stock_id", "month", "r", *FLAGS])


def _sus(d, window=SUS_WINDOW, min_periods=SUS_MIN_PERIODS):
    """季節隨機漫步含漂移：(d_t − 過去 window 個月 d 的均值) / 標準差；只用 t 之前的 d。"""
    hist = d.shift(1).rolling(window, min_periods=min_periods)
    mu, sd = hist.mean(), hist.std()
    return ((d - mu) / sd.where(sd > 0)).where(d.notna())


def revenue_surprise_features(rv, window=SUS_WINDOW, min_periods=SUS_MIN_PERIODS,
                              min_history=RECORD_MIN_HISTORY):
    """逐檔依營收月算 SUS、SUS_pit、營收÷歷史最高；資料不足為 NaN。

    與 ``revenue_features`` 分開：那支和 live prompt 共用，這裡只給量測用。
    每檔先補成連續月份，缺月不跨接（shift(12) 遇缺月自然變 NaN）。

    - ``sus``：季節差 ``R_t − R_{t−12}`` 用入庫的營收水準（歷史月份是更正後的值，見
      docs/research/2026-10-26-exp-revenue-sus.md §0.1）。
    - ``sus_pit``：季節差改用 MOPS 當時公告的 YoY 反推 ``R_t · yoy / (100 + yoy)``，
      避開上年同月的事後更正。
    - ``ath_ratio``：``R_t / 之前所有月份的最高``，至少 ``min_history`` 個月歷史。
    """
    out = []
    for sid, g in rv.sort_values("revenue_month").groupby("stock_id", sort=False):
        g = g.set_index("revenue_month").asfreq("MS")
        rev, yoy = g["revenue"].astype(float), g["yoy"].astype(float)
        d = rev - rev.shift(12)
        d_pit = (rev * yoy / (100.0 + yoy)).where(100.0 + yoy > 0)
        prior_max = rev.shift(1).expanding(min_periods=min_history).max()
        f = pd.DataFrame({
            "stock_id": sid, "announce_date": g["announce_date"],
            "sus": _sus(d, window, min_periods), "sus_pit": _sus(d_pit, window, min_periods),
            "ath_ratio": (rev / prior_max.where(prior_max > 0)).where(rev.notna()),
        })
        out.append(f[g["revenue"].notna()].reset_index())
    if not out:
        return pd.DataFrame(columns=["revenue_month", "stock_id", "announce_date",
                                     "sus", "sus_pit", "ath_ratio"])
    return pd.concat(out, ignore_index=True)


def visible_cohort_pct(x, month, announce):
    """同營收月橫斷面百分位，只和「自己可見時已可見」的同月股票比（PIT）。

    同一營收月的有效公告日不一定相同：自 2026-01 起保險類期限是 15 日、其他 10 日；
    2020-01 全面展延則整月同一天。對每個公告日 d，用該月 ``announce_date <= d`` 的列排名，
    只取 d 那批的結果——10 日那批不會被 15 日才公布的數值影響，15 日那批仍對整個月排名。
    公告日 NaT 的列沒有可見日，回 NaN。NaN 特徵不計入分母（``rank`` 的預設語意）。
    """
    pct = pd.Series(np.nan, index=x.index)
    frame = pd.DataFrame({"x": x, "m": month, "d": announce})
    for _, g in frame.dropna(subset=["d"]).groupby("m", sort=False):
        for d in g["d"].unique():
            seen = g.loc[g["d"] <= d, "x"].rank(pct=True)
            cohort = g.index[g["d"] == d]
            pct.loc[cohort] = seen.loc[cohort]
    return pct


def gate_flags(feat, gates=SURPRISE_GATES, q=TOP_QUANTILE):
    """特徵 → 1.0/0.0 閘門旗標（NaN＝資料不足，不當成「不通過」）。

    ``"top"``：同一營收月的橫斷面百分位 > q，只和自己可見當下已可見的同月股票比
    （``visible_cohort_pct``；保險類 15 日期限讓同月公告日不一致）。數字門檻：特徵 ≥ 門檻。
    """
    out = feat[["stock_id", "revenue_month", "announce_date"]].copy()
    for name, (col, rule) in gates.items():
        x = feat[col].astype(float)
        if rule == "top":
            pct = visible_cohort_pct(x, feat["revenue_month"], feat["announce_date"])
            out[name] = (pct > q).astype(float).where(x.notna() & pct.notna())
        else:
            out[name] = (x >= rule).astype(float).where(x.notna())
    return out


def gate_panels(flags, index, columns, gates=SURPRISE_GATES):
    """閘門旗標 → 交易日面板（與 YoY 閘門同一條 PIT 路徑：公告日之後第一個交易日、45 曆日保鮮）。"""
    return {g: pit_revenue_panel(flags.rename(columns={"announce_date": "date"})
                                 .assign(yoy=flags[g])[["stock_id", "date", "yoy"]].dropna(),
                                 index, columns) for g in gates}


def compare_arm(label, arm, ref, n_days, h, a, primary=False):
    """一個組相對候選池（ref）的均值差、P(≥30%) 差與區塊 bootstrap 區間、判定。"""
    row = {"組": label, "n": len(arm), "均值%": np.nan, "P30%": np.nan}
    if len(arm):
        row["均值%"] = round(arm["r"].mean() * 100, 2)
        row["P30%"] = round((arm["r"] >= HIT_THRESHOLD).mean() * 100, 1)
    dm = arm["r"].mean() - ref["r"].mean() if len(arm) else np.nan
    dh = ((arm["r"] >= HIT_THRESHOLD).mean() - (ref["r"] >= HIT_THRESHOLD).mean()
          if len(arm) else np.nan)
    row["均值差pp"] = round(dm * 100, 2)
    row["P30差pp"] = round(dh * 100, 1)
    ci = (two_arm_block_bootstrap(arm, ref, n_days, n=a.bootstrap, block=h,
                                  seed=a.bootstrap_seed,
                                  levels=(PRIMARY_LEVEL, BONFERRONI_LEVEL))
          if a.bootstrap and len(arm) else None)
    for k, name in (("mean", "均值差"), ("hit", "P30差")):
        for lv in (PRIMARY_LEVEL, BONFERRONI_LEVEL):
            row[f"{name}{lv:g}%CI"] = (
                "n/a" if ci is None else f"{ci[k][lv][0] * 100:+.2f}~{ci[k][lv][1] * 100:+.2f}")
    row["判定"] = verdict(dm, dh, ci, len(arm), a.min_events) if primary else "探索"
    return row


def verdict(dm, dh, ci, n, min_events):
    """事先登記的判準：點估計兩者 > 0、95% 區間兩者下界 > 0、n ≥ min_events；
    再加 Bonferroni 98.75% 區間兩者下界 > 0 才算「存活」。其餘一律 inconclusive。"""
    if ci is None or n < min_events or not (dm > 0 and dh > 0):
        return "inconclusive"
    if not all(ci[k][PRIMARY_LEVEL][0] > 0 for k in ("mean", "hit")):
        return "inconclusive"
    if all(ci[k][BONFERRONI_LEVEL][0] > 0 for k in ("mean", "hit")):
        return SURVIVED
    return "通過（未過 Bonferroni）"


def apply_pit_veto(rows):
    """事先登記的否決：主檢定「通過且存活」但同一組（補充／取代）的 PIT 變體方向相反 → 不存活。

    ``rows`` 是 ``{(組別, 閘門): compare_arm 的列}``，就地改 ``判定``。「方向相反」採保守口徑：
    PIT 變體的均值差或 P30 差點估計任一不 > 0（與判準 (a) 同一條線）。只降級「通過且存活」，
    其他判定本來就不寫進長期文件，不動。
    """
    for (arm, gate), row in rows.items():
        pit = rows.get((arm, PIT_VETO.get(gate)))
        if pit is None or row.get("判定") != SURVIVED:
            continue
        if not (pit["均值差pp"] > 0 and pit["P30差pp"] > 0):
            row["判定"] = PIT_VETOED
    return rows


def surprise_report(piv, rv, sig, extra, horizons, a):
    """SUS／營收÷歷史最高 當候選池的補充（切分池內事件）或取代 YoY≥20 的閘門。"""
    idx, cols = piv["close"].index, piv["close"].columns
    feat = revenue_surprise_features(rv[rv["stock_id"].map(is_common_stock)])
    flags = gate_flags(feat)
    panels = gate_panels(flags, idx, cols)
    n_days = len(idx)
    print(f"營收特徵 {len(feat):,} 列；非 NaN：SUS {feat['sus'].notna().sum():,}　"
          f"SUS_pit {feat['sus_pit'].notna().sum():,}　ATH {feat['ath_ratio'].notna().sum():,}\n")
    for h in horizons:
        ret, _ = forward_returns(piv, h, "last")
        _, pool = to_events(sig, ret, h, panels, entry_notional=a.position_notional)
        if not len(pool):
            continue
        rows = {("對照", None): {"組": "候選池（YoY≥20，對照）", "n": len(pool),
                                  "均值%": round(pool["r"].mean() * 100, 2),
                                  "P30%": round((pool["r"] >= HIT_THRESHOLD).mean() * 100, 1)}}
        for g in SURPRISE_GATES:
            primary = h == a.pool_hold and g in PRIMARY_GATES
            cover = pool[g].notna().mean() * 100
            rows[("補充", g)] = compare_arm(f"補充 {g}（池內閘門=1；池內有值 {cover:.0f}%）",
                                            pool.loc[pool[g] == 1], pool, n_days, h, a, primary)
            rep = apply_thresholds(piv["close"], extra, panels[g], a.d5, a.vol_lo, a.vol_hi, 1.0)
            rep.loc[:pd.Timestamp(a.start)] = False
            _, rep_ev = to_events(rep, ret, h, {}, entry_notional=a.position_notional)
            rows[("取代", g)] = compare_arm(f"取代 {g}（價格條件 ∩ 閘門）", rep_ev, pool, n_days,
                                            h, a, primary)
        apply_pit_veto(rows)
        tag = "主" if h == a.pool_hold else "次要"
        print(f"=== h={h}（{tag}）：組 − 候選池；雙臂交易日區塊 bootstrap block={h}、"
              f"{a.bootstrap} 次、seed={a.bootstrap_seed} ===")
        with pd.option_context("display.width", 250, "display.max_columns", 30):
            print(pd.DataFrame(list(rows.values())).set_index("組").to_string(), "\n")


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
    p.add_argument("--experiment", choices=("momentum", "surprise"), default="momentum",
                   help="momentum＝動能轉弱（預設、既有輸出）；surprise＝SUS／營收÷歷史最高 "
                        "補充或取代 YoY≥20（docs/research/2026-10-26-exp-revenue-sus.md）")
    p.add_argument("--min-events", type=int, default=300,
                   help="surprise 主檢定的組內事件數下限，不足判 inconclusive")
    a = p.parse_args(argv)
    # 候選池價格條件：與 measure_signal_forward 預設相同（surprise 的取代組要重用）
    a.d5, a.vol_lo, a.vol_hi = 0.05, 1.3, 2.0
    horizons = [int(h) for h in a.horizons.split(",")]

    eng = create_engine(database_url(), connect_args={
        "options": "-c default_transaction_read_only=on"})
    if a.end is None:
        with eng.connect() as c:
            a.end = str(c.execute(text("select max(date) from market.price")).scalar())
    piv, _, _ = load(eng, a.start, a.end, a.include_otc_revenue)
    keep = [s for s in piv["close"].columns if is_common_stock(s)]
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
                               a.d5, a.vol_lo, a.vol_hi, 20.0)
    sig.loc[:pd.Timestamp(a.start)] = False
    if a.experiment == "surprise":
        surprise_report(piv, rv, sig, extra, horizons + [a.pool_hold], a)
        return 0
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
    panels["_ann"] = feat.set_index("stock_id")["announce_date"].dropna()
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
