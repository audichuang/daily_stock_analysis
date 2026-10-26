#!/usr/bin/env python3
"""外資與投信「橫斷面對立極端」構念的前瞻超額量測（樣本外驗證用）。唯讀。

構念來源：`docs/tw-swing-pipeline.md`「2026-07-31 唯一从 90 臂活下来的构念」。產出原始數字的
`measure_inst.py` 沒進版控，這支依該節文字重建，事先登記與判準在
`docs/research/2026-10-26-exp-divergence-oos.md`。

口徑（全部沿用 `measure_signal_forward` 的共用元件，不另寫一套）：

- 宇宙：當日有價格 ∩ `is_common_stock` ∩ 20 日均額 ≥ 門檻 ∩ 上市法人列（`market IS NULL`）D−1 存在
  ∩ 兩腿 20 日流向都算得出來。上櫃法人列 2018 年才有，放進來宇宙會在樣本外中途改變，所以排除。
- 流向：`foreign_net`／`trust_net` 20 日加總，`--norm volume` 再除以同期成交量加總；**lag 1 交易日**。
- 排名：每日在宇宙內 `rank(pct=True, method="average")`；> 0.8 前 20%、≤ 0.2 後 20%、其餘中間帶。
- 進出場、下市結算、事件去重、成本：`forward_returns`、`to_events`、`round_trip_return`。
- 超額：事件淨報酬 − 同訊號日宇宙全體淨報酬平均；區間用 `paired_block_bootstrap`（block = h）。

用法：
    uv run --frozen python scripts/measure_inst_divergence.py --start 2013-01-02 --end 2019-12-31 \\
        --horizons 250,60 --norm volume
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from market_data.adjust import is_common_stock  # noqa: E402
from market_data.db import get_engine  # noqa: E402
from measure_signal_forward import (  # noqa: E402
    DEFAULT_POSITION_NOTIONAL,
    HIT_THRESHOLD,
    forward_returns,
    load,
    paired_block_bootstrap,
    to_events,
)
from tw_trade_costs import round_trip_return  # noqa: E402

FLOW_WINDOW = 20
FLOW_LAG = 1          # 法人資料收盤後才公布：D 日的訊號只能用到 D−1 的列
TOP, BOTTOM = 0.8, 0.2
ARMS = ("分歧臂", "鏡像臂", "同向極端", "單腿極端", "雙中間")
LEGS = ("外資前20%", "投信後20%")


def load_institutional(engine, start, end):
    """上市法人列（``market IS NULL``）→ (foreign, trust) 面板；只讀。"""
    with engine.connect() as c:
        df = pd.read_sql(text(
            "select stock_id, date, foreign_net, trust_net from market.institutional "
            "where market is null and date between :s and :e"), c,
            params={"s": start, "e": end}, parse_dates=["date"])
    return (df.pivot(index="date", columns="stock_id", values="foreign_net").astype(float),
            df.pivot(index="date", columns="stock_id", values="trust_net").astype(float))


def flow_strength(net, volume, norm, window=FLOW_WINDOW, lag=FLOW_LAG):
    """D 日可用的流向：D−lag 為止的 window 日淨買超加總（``volume`` 正規化時再除以同期成交量）。

    缺任何一天的法人列就是 NaN（``min_periods=window``），不拿殘缺窗口去排名。
    """
    s = net.rolling(window, min_periods=window).sum()
    if norm == "volume":
        v = volume.reindex(index=net.index, columns=net.columns).rolling(
            window, min_periods=window).sum()
        s = s / v.where(v > 0)
    elif norm != "raw":
        raise ValueError(f"unknown norm: {norm}")
    return s.shift(lag)


def build_universe(close, turnover, inst_present, f_flow, t_flow, min_turnover, lag=FLOW_LAG):
    """宇宙遮罩（index=交易日、columns=股票）。呼叫端須已用 ``is_common_stock`` 濾過欄位。"""
    liquid = turnover.rolling(20).mean() >= min_turnover
    prev_inst = inst_present.reindex(index=close.index, columns=close.columns).shift(lag)
    u = (close.notna() & liquid & prev_inst.fillna(False).astype(bool)
         & f_flow.notna() & t_flow.notna())
    return u.fillna(False).astype(bool)


def cross_rank(flow, universe):
    """每日只在宇宙內排名；平手取平均名次（投信大量 0 會落在中間帶，不被硬塞進極端）。"""
    return flow.where(universe).rank(axis=1, pct=True, method="average")


def classify(f_rank, t_rank):
    """互斥五臂＋兩條單腿描述用遮罩。NaN 名次（不在宇宙）一律 False。"""
    ok = f_rank.notna() & t_rank.notna()
    ft, fb = (f_rank > TOP) & ok, (f_rank <= BOTTOM) & ok
    tt, tb = (t_rank > TOP) & ok, (t_rank <= BOTTOM) & ok
    fm, tm = ok & ~ft & ~fb, ok & ~tt & ~tb
    return {
        "分歧臂": ft & tb,
        "鏡像臂": fb & tt,
        "同向極端": (ft & tt) | (fb & tb),
        "單腿極端": ((ft | fb) & tm) | ((tt | tb) & fm),
        "雙中間": fm & tm,
        "外資前20%": ft,
        "投信後20%": tb,
    }


def window_mask(sig, start, signal_end=None):
    """START 前（暖機）與 signal_end 之後的訊號歸零；舊 `measure_inst.py` 漏了前者。"""
    sig = sig.copy()
    sig.loc[sig.index < pd.Timestamp(start)] = False
    if signal_end is not None:
        sig.loc[sig.index > pd.Timestamp(signal_end)] = False
    return sig


def net_panel(ret, universe, entry_notional=DEFAULT_POSITION_NOTIONAL):
    """宇宙格的扣成本淨報酬（其餘 NaN），成本走共用 ``round_trip_return``。"""
    cells = ret.where(universe).stack()
    # 只丟缺值：下市以 0 結算的 r=-1.0（exit=0）要和臂事件（to_events）一樣算進基準；
    # <-1 不可能出現，出現就讓 round_trip_return 報錯，與 to_events 一致。
    cells = cells.dropna()
    net = cells.map(lambda r: round_trip_return(1.0, 1.0 + float(r), entry_notional=entry_notional))
    out = net.unstack()
    return out.reindex(index=ret.index, columns=ret.columns)


def same_day_excess(ev, day_mean):
    """事件淨報酬 − 同訊號日宇宙平均淨報酬；平均缺值（當日宇宙無可量報酬）就是 NaN。"""
    ev = ev.copy()
    ev["bench"] = day_mean.reindex(ev["date"]).to_numpy()
    ev["diff"] = ev["r"] - ev["bench"]
    return ev


def summarize(label, ev, calendar, a, h):
    if not len(ev):
        return {"臂": label, "事件": 0}
    span = int(ev["ti"].max() - ev["ti"].min())
    pairs = ev[["ti", "diff"]].rename(columns={"ti": "date"})
    ci = (paired_block_bootstrap(pairs, calendar, n=a.bootstrap, block=h, seed=a.bootstrap_seed)
          if a.bootstrap and span > h else None)
    return {
        "臂": label, "事件": len(ev), "檔數": ev["stock_id"].nunique(),
        "均值%": round(ev["r"].mean() * 100, 2), "中位%": round(ev["r"].median() * 100, 2),
        "P(≥30%)": round((ev["r"] >= HIT_THRESHOLD).mean() * 100, 1),
        "超額%": round(ev["diff"].mean() * 100, 2),
        "超額CI%": "n/a" if ci is None else f"[{ci[0] * 100:+.2f}, {ci[1] * 100:+.2f}]",
        "ti跨度": span,
        "_ci": ci,
    }


def verdict(rows, base):
    """事先登記的三級判定（見研究紀錄 §0.5）。"""
    d, m, mid = rows["分歧臂"], rows["鏡像臂"], rows["雙中間"]
    if not all(r.get("事件") for r in (d, m, mid)):
        return "inconclusive（有臂沒有事件）"
    if not (d["超額%"] > 0 and m["超額%"] > 0 and mid["超額%"] < 0):
        return "封存（假陽性：凍結判準的點估計不成立）"
    if min(d["事件"], m["事件"]) < 100:
        return "inconclusive（事件數 < 100）"
    cis = [d["_ci"], m["_ci"]]
    if any(ci is None or ci[0] <= 0 for ci in cis):
        return "inconclusive（點估計方向成立，但超額區間跨零或無法估計）"
    beats = all(r["均值%"] > base["均值%"] and r["P(≥30%)"] > base["P(≥30%)"] for r in (d, m))
    if not beats:
        return "inconclusive（區間排除 0，但均值與 P(≥30%) 未同時高於共同宇宙基準）"
    return "通過"


def main(argv=None):
    p = argparse.ArgumentParser(description="外資／投信對立極端的前瞻超額（唯讀）")
    p.add_argument("--start", required=True, help="訊號起日（之前為暖機）")
    p.add_argument("--end", required=True, help="面板止日：前瞻報酬不會用到這天之後的價格")
    p.add_argument("--signal-end", default=None, help="訊號止日（預設＝--end）")
    p.add_argument("--horizons", default="250,60", help="逗號分隔的前瞻交易日數")
    p.add_argument("--norm", default="volume", choices=["volume", "raw"])
    p.add_argument("--min-turnover", type=float, default=2.0, help="20 日均額門檻（億）")
    p.add_argument("--delisting", default="last", choices=["last", "zero"])
    p.add_argument("--bootstrap", type=int, default=2000)
    p.add_argument("--bootstrap-seed", type=int, default=42)
    a = p.parse_args(argv)
    horizons = [int(x) for x in a.horizons.split(",") if x.strip()]

    eng = get_engine()
    piv, _rv, _info = load(eng, a.start, a.end)  # 月營收不用（構念不含營收條件）
    keep = [s for s in piv["close"].columns if is_common_stock(s)]
    piv = {k: v[keep] for k, v in piv.items()}
    close = piv["close"]
    hist = close.index[0].date()
    fnet, tnet = load_institutional(eng, hist, a.end)
    fnet = fnet.reindex(index=close.index, columns=close.columns)
    tnet = tnet.reindex(index=close.index, columns=close.columns)
    present = fnet.notna() | tnet.notna()
    f_flow = flow_strength(fnet, piv["volume"], a.norm)
    t_flow = flow_strength(tnet, piv["volume"], a.norm)
    uni = build_universe(close, piv["turnover"], present, f_flow, t_flow, a.min_turnover * 1e8)
    arms = classify(cross_rank(f_flow, uni), cross_rank(t_flow, uni))
    arms["共同宇宙基準"] = uni
    arms = {k: window_mask(v, a.start, a.signal_end) for k, v in arms.items()}

    in_win = uni.loc[uni.index >= pd.Timestamp(a.start)]
    print(f"樣本 訊號 {a.start} ~ {a.signal_end or a.end}、面板止 {a.end}　norm={a.norm}　"
          f"宇宙每日中位 {int(in_win.sum(axis=1).median())} 檔、合計 {in_win.values.sum():,} 格　"
          f"lag={FLOW_LAG}　下市結算={a.delisting}")

    for h in horizons:
        ret, _ = forward_returns(piv, h, a.delisting)
        day_mean = net_panel(ret, arms["共同宇宙基準"]).mean(axis=1)
        valid = np.flatnonzero(day_mean.notna().to_numpy())
        calendar = np.arange(valid.min(), valid.max() + 1) if len(valid) else np.arange(0)
        rows, evs = {}, {}
        for name in ("共同宇宙基準",) + ARMS + LEGS:
            _, ev = to_events(arms[name], ret, h, {})
            if len(ev):
                ev = same_day_excess(ev, day_mean).dropna(subset=["diff"])
            evs[name] = ev
            rows[name] = summarize(name, ev, calendar, a, h)
        print(f"\n=== h{h}（事件以 {h} 交易日去重；超額＝事件淨報酬 − 同日宇宙平均淨報酬；"
              f"block={h}、{a.bootstrap} 次、seed={a.bootstrap_seed}）===")
        table = pd.DataFrame([{k: v for k, v in r.items() if k != "_ci"} for r in rows.values()])
        print(table.set_index("臂").to_string())
        print(f"判定（事先登記 §0.5）：{verdict(rows, rows['共同宇宙基準'])}")
        yr = []
        for name in ("分歧臂", "鏡像臂", "雙中間"):
            ev = evs[name]
            if len(ev):
                g = ev.groupby(ev["date"].dt.year)["diff"].agg(["size", "mean"])
                yr.append(g.rename(columns={"size": f"{name}n", "mean": f"{name}超額%"}))
        if yr:
            y = pd.concat(yr, axis=1)
            for c in [c for c in y.columns if c.endswith("%")]:
                y[c] = (y[c] * 100).round(1)
            print("逐年超額：")
            print(y.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
