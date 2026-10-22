#!/usr/bin/env python3
"""量測「大盤狀態」能不能預測接下來 3／5／10 個交易日的報酬（唯讀研究）。

`market.market_index` 只從 2026-07 開始，所以**大盤以 0050 前復權收盤代理加權指數**
（報告會標示）；市場寬度用 `market.price` 的流動普通股算。

候選狀態（全部用**固定門檻**的二元狀態；用全樣本分位數切會偷看未來）：
  - `0050>季線`：0050 收盤 > MA60
  - `季線上彎`：MA60(t) > MA60(t-10)
  - `寬度20>50%`／`寬度60>50%`：流動股中收盤 > MA20／MA60 的比例
  - `寬度20<20%`：極端超賣（看是否反向）
  - `融資增+指數跌`：上市融資餘額 5 日「價格中立」變化 > 0 且 0050 5 日報酬 < 0

三個被預測的對象（進場一律 T+1 開盤、T+h 收盤出場，沿用 `measure_signal_forward`；
融資餘額是盤後公布，所以 t 日狀態只能用在 T+1 進場，這個慣例剛好吻合）：
  (a) 0050（成本用 ETF 證交稅 0.1%）
  (b) 流動股等權（每日橫斷面平均）
  (c) `measure_signal_forward` 的突破候選事件（同檔 h 日內去重）

判讀用的是**差異** mean(r|S) − mean(r|¬S)：2011 以後台股大多是多頭，各狀態均值通常都是正的，
單看均值沒有資訊。差異用循環區塊 bootstrap（以交易日區塊重抽，保留重疊視窗的自相關）。

用法：
    uv run --env-file .env python scripts/measure_market_regime.py --out reports/market_regime.md
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import measure_signal_forward as msf  # noqa: E402
from measure_revenue_momentum import correct_pit_dates  # noqa: E402
from market_data.adjust import is_common_stock  # noqa: E402
from market_data.db import database_url  # noqa: E402
from src.services.tw_backtest_context import regime_states  # noqa: E402  與 live prompt 共用
from src.utils.tw_trade_costs import ETF_TRANSACTION_TAX_RATE, round_trip_return  # noqa: E402

PROXY = "0050"
HORIZONS = (3, 5, 10)
NOTIONAL = 200_000.0  # 名目本金夠大時手續費是比例制，成本可直接套在日均報酬上


def read_only_engine():
    # 連線層級強制唯讀：就算日後有人在這支腳本加了寫入，也會被資料庫拒絕
    return create_engine(database_url(), connect_args={
        "options": "-c default_transaction_read_only=on"})


def load_margin_delta(engine, index, adj_close):
    """上市融資餘額 5 日的「價格中立」變化（元）。

    `market.margin` 只有上市（實測對 stock_info 只有 twse 與已下市的 None）。直接加總張數會被
    分割弄壞、直接加總金額又會被股價漲跌帶著走（指數跌→金額機械性變小），所以用
    Σ bal_t·P_t/(1+r_5d) − bal_{t-5}·P_{t-5}：等於「現在的張數按 5 天前價格估值」減去
    「5 天前的融資金額」，分割與股價變動都抵銷。只加總兩端都有資料的股票，避免新上市
    被當成融資增加。
    """
    with engine.connect() as c:
        m = pd.read_sql(text(
            "select m.stock_id, m.date, m.margin_balance::float8 bal, p.close::float8 px "
            "from market.margin m join market.price p using (stock_id, date) "
            "where m.date between :s and :e"), c,
            params={"s": index[0].date(), "e": index[-1].date()}, parse_dates=["date"])
    m = m[m["stock_id"].map(is_common_stock)]
    bal = m.pivot(index="date", columns="stock_id", values="bal").reindex(index)
    px = m.pivot(index="date", columns="stock_id", values="px").reindex(index)
    return price_neutral_margin_delta(bal, px, adj_close.reindex(columns=bal.columns))


def price_neutral_margin_delta(bal, px, adj_close):
    """`bal` 張數、`px` 未還原收盤、`adj_close` 前復權收盤（同 index/columns）。"""
    r5 = adj_close.pct_change(5, fill_method=None)
    now_at_old_px = bal * px / (1 + r5)
    before = (bal * px).shift(5)
    both = now_at_old_px.notna() & before.notna()
    delta = (now_at_old_px.where(both).sum(axis=1) - before.where(both).sum(axis=1))
    return delta.where(both.sum(axis=1) > 0)


def bootstrap_diff(day_sum, day_cnt, state, n=2000, block=60, seed=42):
    """循環區塊 bootstrap：S 與 ¬S 的均值差 95% CI。

    `day_sum`／`day_cnt` 是每個交易日的報酬總和與筆數（日序列是 r 與 1；事件是當天所有事件），
    `state` 是同長度 0/1/NaN。區塊以完整交易日曆抽，重抽到的天數以權重計入。
    """
    s = np.nan_to_num(state, nan=-1)
    ins, out = (s == 1), (s == 0)
    n_days = len(s)
    if n_days < 2 * block:
        return None
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n_days / block))
    offs = np.arange(block)
    diffs = []
    for _ in range(n):
        pos = ((rng.integers(0, n_days, size=n_blocks)[:, None] + offs) % n_days).ravel()[:n_days]
        w = np.bincount(pos, minlength=n_days)
        ci, co = (w * day_cnt * ins).sum(), (w * day_cnt * out).sum()
        if ci and co:
            diffs.append((w * day_sum * ins).sum() / ci - (w * day_sum * out).sum() / co)
    if len(diffs) < n // 2:
        return None
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def summarize(values_by_day, state, n_boot, block, seed, min_n=30):
    """values_by_day: 依日期的 list/array（每天 0..k 個報酬）。回傳 S／¬S 統計與差異 CI。"""
    st = state.to_numpy()
    day_sum = np.array([np.sum(v) for v in values_by_day])
    day_cnt = np.array([len(v) for v in values_by_day], dtype=float)
    res = {}
    for name, mask in (("S", st == 1), ("¬S", st == 0)):
        vals = np.concatenate([values_by_day[i] for i in np.flatnonzero(mask)]
                              or [np.array([])])
        res[name] = {"n": len(vals), "mean": vals.mean() if len(vals) else np.nan,
                     "median": np.median(vals) if len(vals) else np.nan,
                     "hit": (vals > 0).mean() if len(vals) else np.nan,
                     "days": int(mask.sum())}
    res["diff"] = res["S"]["mean"] - res["¬S"]["mean"]
    res["ci"] = (bootstrap_diff(day_sum, day_cnt, st, n=n_boot, block=block, seed=seed)
                 if min(res["S"]["n"], res["¬S"]["n"]) >= min_n else None)
    return res


def verdict(res, cost):
    ci = res["ci"]
    if ci is None:
        return "inconclusive（樣本不足）"
    if ci[0] <= 0 <= ci[1]:
        return "inconclusive（CI 跨零）"
    sign = "S 較好" if ci[0] > 0 else "S 較差"
    return f"{sign}，" + ("|差|≥成本" if abs(res["diff"]) >= cost else "|差|<成本")


def pct(x, d=2):
    return "—" if pd.isna(x) else f"{x * 100:+.{d}f}%"


def main(argv=None):
    p = argparse.ArgumentParser(description="大盤狀態 → 前瞻 3/5/10 日報酬（唯讀）")
    p.add_argument("--start", default="2011-01-01")
    p.add_argument("--end", default=None, help="預設資料最後一天")
    p.add_argument("--min-turnover", type=float, default=2.0, help="流動股日均額門檻（億）")
    p.add_argument("--split", default="2018-01-01", help="分段穩健性檢查的切點")
    p.add_argument("--bootstrap", type=int, default=2000)
    p.add_argument("--block", type=int, default=60, help="bootstrap 區塊長度（交易日）")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-breakout", action="store_true", help="跳過 (c) 突破候選")
    p.add_argument("--out", default=None, help="輸出 markdown 路徑（建議 reports/…）")
    a = p.parse_args(argv)

    eng = read_only_engine()
    end = a.end or str(pd.Timestamp.today().date())
    piv, rv, _ = msf.load(eng, a.start, end)
    proxy = {k: v[PROXY] for k, v in piv.items()}
    keep = [s for s in piv["close"].columns if is_common_stock(s)]
    piv = {k: v[keep] for k, v in piv.items()}
    close = piv["close"]
    cal = close.index
    f = msf.factors(piv, a.min_turnover * 1e8)
    liquid = f["liquid"].fillna(False)

    mdelta = load_margin_delta(eng, cal, close)
    states, breadth = regime_states(proxy["close"], close, liquid, mdelta)
    in_window = cal >= pd.Timestamp(a.start)

    # 候選池的營收可見日要套已知展延（2020-01 → 2/15），否則會提前用到未公布營收
    yoy = (msf.pit_revenue_panel(correct_pit_dates(rv), cal, close.columns)
           if not a.no_breakout else None)
    sig = None
    if yoy is not None:
        sig, _ = msf.build_signals(piv, yoy, a.min_turnover * 1e8, 0.05, 1.3, 2.0, 20.0)
        sig.loc[~in_window] = False

    stock_cost = -round_trip_return(1.0, 1.0, entry_notional=NOTIONAL)
    etf_cost = -round_trip_return(1.0, 1.0, entry_notional=NOTIONAL,
                                  tax_rate=ETF_TRANSACTION_TAX_RATE)

    def net(r, etf=False):
        kw = {"tax_rate": ETF_TRANSACTION_TAX_RATE} if etf else {}
        return np.array([round_trip_return(1.0, 1.0 + x, entry_notional=NOTIONAL, **kw)
                         for x in r])

    L = []
    w = L.append
    last = cal[in_window][-1].date()
    w("# 大盤狀態回測（0050 代理加權指數）\n")
    w(f"- 期間：{a.start} ~ {last}（交易日 {int(in_window.sum())}）；進場 T+1 開盤、T+h 收盤出場")
    w("- **大盤代理＝0050 前復權收盤**（market_index 只從 2026-07 起）；寬度＝流動普通股"
      f"（20 日均額 ≥ {a.min_turnover:g} 億）收盤高於 MA20／MA60 的比例")
    w("- 融資只有上市；採價格中立的 5 日變化（分割與漲跌抵銷）")
    w(f"- 報酬皆為**淨報酬**：個股來回成本約 {stock_cost * 100:.3f}%、0050 約 {etf_cost * 100:.3f}%"
      "（名目 20 萬、手續費不打折、滑價每邊 0.15%）。狀態差異對常數成本不變")
    w(f"- 差異 CI：循環區塊 bootstrap，block={a.block} 交易日、{a.bootstrap} 次、seed={a.seed}；"
      "任一側 n<30 或 CI 跨零 → inconclusive")
    w("- **多重比較**：6 狀態×3 期距×3 對象＝54 格，95% 下約 2.7 格會純屬偶然顯著；"
      "只有「≥2 個期距同號且 CI 不跨零」或「前後兩段同號」才算數")
    w("- (c) 有**存活偏誤**（月營收缺已下市公司，見 measure_signal_forward 說明），數字偏樂觀；"
      "低頻狀態請看「連續段數」而不是天數")
    liq_n = liquid.sum(axis=1)[in_window]
    w(f"- 流動池每日檔數 {int(liq_n.min())}~{int(liq_n.max())}（中位 {int(liq_n.median())}），"
      "早年與近年的池子差很多\n")
    runs = {k: int(((states.loc[in_window, k] == 1).astype(int).diff() == 1).sum()
                   + (states.loc[in_window, k].iloc[0] == 1)) for k in states.columns}
    w("各狀態連續段數：" + "、".join(f"{k} {v}" for k, v in runs.items()) + "\n")
    cur = states.loc[cal[in_window][-1]]
    flags = [f"{k}={'是' if v == 1 else '否' if v == 0 else '—'}" for k, v in cur.items()]
    w("最新狀態：" + "、".join(flags)
      + f"；寬度20={breadth[20].iloc[-1] * 100:.0f}%、寬度60={breadth[60].iloc[-1] * 100:.0f}%\n")
    w("各狀態成立天數占比：" + "、".join(
        f"{k} {states.loc[in_window, k].mean() * 100:.0f}%" for k in states.columns) + "\n")

    rows_split = []
    for h in HORIZONS:
        ret, _ = msf.forward_returns(piv, h, "last")
        pr = proxy["open"].shift(-1)
        pret = proxy["close"].shift(-h) / pr - 1
        ew = ret.where(liquid).mean(axis=1)
        arms = {}
        ok = in_window & pret.notna().to_numpy()
        arms["(a) 0050"] = (ok, [np.array([x]) for x in net(pret.fillna(0).to_numpy(), etf=True)])
        ok_b = in_window & ew.notna().to_numpy()
        arms["(b) 流動股等權"] = (ok_b, [np.array([x]) for x in net(ew.fillna(0).to_numpy())])
        if sig is not None:
            _, ev = msf.to_events(sig, ret, h, {}, entry_notional=NOTIONAL)
            by_day = [np.array([])] * len(cal)
            if len(ev):
                for ti, g in ev.groupby("ti"):
                    by_day[int(ti)] = g["r"].to_numpy()
            arms["(c) 突破候選事件"] = (in_window, by_day)
        w(f"\n## 前瞻 {h} 日\n")
        w("| 對象 | 狀態 | S 天數 | S n | S 均值 | S 中位 | S 勝率 | ¬S n | ¬S 均值 | ¬S 勝率 "
          "| 差（S−¬S） | 95% CI | 判讀 |")
        w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for arm, (valid, vals) in arms.items():
            cost = etf_cost if arm.startswith("(a)") else stock_cost
            for col in states.columns:
                st = states[col].where(valid)
                r = summarize(vals, st, a.bootstrap, a.block, a.seed)
                ci = r["ci"]
                cis = "—" if ci is None else f"{pct(ci[0])} ~ {pct(ci[1])}"
                S, N = r["S"], r["¬S"]
                w(f"| {arm} | {col} | {S['days']} | {S['n']} | {pct(S['mean'])} | "
                  f"{pct(S['median'])} | {pct(S['hit'], 1)[1:]} | {N['n']} | {pct(N['mean'])} | "
                  f"{pct(N['hit'], 1)[1:]} | {pct(r['diff'])} | {cis} | {verdict(r, cost)} |")
                # 分段：只看差異方向是否兩段一致（樣本切半後 CI 只是參考）
                seg = []
                for lab, m in (("前段", cal < pd.Timestamp(a.split)),
                               ("後段", cal >= pd.Timestamp(a.split))):
                    rs = summarize(vals, st.where(m), max(a.bootstrap // 4, 200), a.block, a.seed)
                    seg.append((lab, rs["diff"], rs["ci"]))
                rows_split.append((h, arm, col, seg))

    w(f"\n## 分段穩健性（切點 {a.split}；差異 S−¬S 與 CI）\n")
    w("| h | 對象 | 狀態 | 前段差 | 前段 CI | 後段差 | 後段 CI |")
    w("|---|---|---|---|---|---|---|")
    for h, arm, col, seg in rows_split:
        cells = []
        for _, d, ci in seg:
            cells += [pct(d), "—" if ci is None else f"{pct(ci[0])} ~ {pct(ci[1])}"]
        w(f"| {h} | {arm} | {col} | " + " | ".join(cells) + " |")

    out = "\n".join(L) + "\n"
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(out, encoding="utf-8")
        print(f"→ {a.out}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
