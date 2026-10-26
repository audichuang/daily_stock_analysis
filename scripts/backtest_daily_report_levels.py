#!/usr/bin/env python3
"""每日個股報告「照價位執行」的回測：理想買點成交就買，停損／目標價觸發就賣。

與 `docs/daily-report-backtest-2026-07.md` 的差別：那份照**標籤**（買入／賣出）執行；這支只看
報告給的**價位**（`analysis_history.ideal_buy / stop_loss / take_profit`），是「掛單照做」的口徑。

口徑（每一條都會改變數字，改之前先想清楚）：
  - 範圍：台股（`.TW` / `.TWO`）。美股不在 `market` schema；裸代號（如 `2330`）略過。
  - 時點：D 日的報告，價位從 **D 之後的第一個交易日**起生效（多數報告在 14:0x 盤後產出）。
    同股同日多份取最後一份。
  - 價位壽命：每檔永遠用**最新一份**報告的價位；新報告整組替換（停損因此逐日移動）。
    **買點不沿用**：最新一份沒給 `ideal_buy`（常見於「賣出」報告）就代表沒有買單——沿用舊買點
    會在報告喊賣的那天買進（踩過：聯電 07-29 報告「賣出」、無買點，沿用舊值買到大跌低點，
    一筆 +55% 撐起整組結果）。停損與目標價缺值時才沿用上一份。
    `stop_loss < ideal_buy < take_profit` 不成立的那份整份不用。
  - 進場：空手且當日 `low <= ideal_buy` → 成交價 `min(open, ideal_buy)`。每檔最多一個部位。
    **開盤已在停損價之下不進場**——價位本身已失效，照做只是開盤買進、當場停損，白吃一趟成本。
    `--respect-advice` 時，最新報告的 `operation_advice` 是賣出／減倉就不進場。
    `--min-net-rr` 時，價位沒過每日報告同一支成本檢核（`src/trade_cost_guardrail.evaluate_levels`）
    就不進場。**這個門檻是看了這批報告才加的，在同一批報告上跑只能說明成本拖累縮小多少，
    不能拿來驗證門檻本身**（in-sample）。
  - 出場：持有中，`low <= stop_loss` → `min(open, stop_loss)`；`high >= take_profit` →
    `max(open, take_profit)`；同一天兩者都碰到 → 算停損（沒有盤中資料，取保守）。
    進場當天只檢查停損：不知道先碰買點還是先碰目標價，當天停利會高估（`--same-day-tp` 放寬）。只做多。
  - 報酬率：以**固定帳本**（檔數 × 每筆本金）為分母。「÷ 累計投入」會因資金周轉而稀釋，只當參考。
  - 價格：觸發一律比**未還原**的 OHLC（報告價位是未還原價）；損益用前復權因子換算（含除權息）。
  - 成本：`scripts/tw_trade_costs.py`，含買賣各 0.15% 滑價（限價單實務上未必吃得到，保留是為了與
    既有回測可比）。每筆固定名目本金，允許零股。
  - 期末：仍持有的用資料最後一日收盤結算。

用法：
    uv run --env-file .env python scripts/backtest_daily_report_levels.py
    uv run --env-file .env python scripts/backtest_daily_report_levels.py --respect-advice
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_data.adjust import load_factors  # noqa: E402
from market_data.db import get_engine  # noqa: E402
from src.trade_cost_guardrail import evaluate_levels  # noqa: E402
from tw_trade_costs import (  # noqa: E402
    affordable_shares,
    buy_cash_outflow,
    buy_fill_price,
    sell_cash_inflow,
    sell_fill_price,
    tw_sell_tax_rate,
)

REPO = Path(__file__).resolve().parent.parent
BEARISH_ADVICE = ("賣出", "減倉", "卖出", "减仓")


def load_reports(source: str) -> pd.DataFrame:
    """source 是 SQLAlchemy URL（如 STORAGE_DATABASE_URL）或 SQLite 档路径（唯读开启）。"""
    url = source if "://" in source else f"sqlite:///file:{Path(source).resolve()}?mode=ro&uri=true"
    with create_engine(url).connect() as c:
        df = pd.read_sql(text(
            "select code, name, created_at, operation_advice, ideal_buy, stop_loss, take_profit "
            "from analysis_history where report_type = 'simple' "
            "and (code like '%.TW' or code like '%.TWO')"), c, parse_dates=["created_at"])
    df["stock_id"] = df["code"].str.split(".").str[0]
    df["day"] = df["created_at"].dt.normalize()
    return df.sort_values("created_at").groupby(["stock_id", "day"], as_index=False).last()


def load_bars(engine, stock_ids, start):
    with engine.connect() as c:
        px = pd.read_sql(text(
            "select stock_id, date, open, high, low, close from market.price "
            "where stock_id = any(:ids) and date >= :s order by date"),
            c, params={"ids": list(stock_ids), "s": start}, parse_dates=["date"])
    for col in ("open", "high", "low", "close"):
        px[col] = px[col].astype(float)
    close = px.pivot(index="date", columns="stock_id", values="close")
    adj = load_factors(engine, close.index, close.columns)
    return px, adj


def active_levels(reports: pd.DataFrame):
    """逐份報告套用「缺值沿用、不合理整份丟棄」後的有效價位，回傳 [(生效日下限, 價位 dict)]。"""
    out, cur = [], {}
    for _, r in reports.iterrows():
        new = {k: v for k, v in cur.items() if k != "ideal_buy"}
        for k in ("ideal_buy", "stop_loss", "take_profit"):
            if pd.notna(r[k]):
                new[k] = float(r[k])
        new["advice"] = r["operation_advice"]
        if all(k in new for k in ("ideal_buy", "stop_loss", "take_profit")) and \
                not (new["stop_loss"] < new["ideal_buy"] < new["take_profit"]):
            new.pop("ideal_buy")   # 價位自相矛盾：不掛買單，但保留停損／目標給持倉用
        cur = new
        out.append((r["day"], dict(cur)))
    return out


def simulate(stock_id, reports, bars, adj, notional, respect_advice, same_day_tp=False, min_net_rr=None,
             freeze=False, hold_days=None, stop_atr=None, no_tp=False, no_stop=False, ignore_entry=False):
    """預設是「每天用最新報告的價位」。放慢節奏的四個旋鈕（可疊加）：
    freeze    出場價位鎖在進場那天的報告，之後的新報告不再移動停損／目標
    hold_days 持有滿 N 個交易日就在收盤出場（時間出場）
    stop_atr  停損至少放在進場價下方 K×ATR14（取報告停損與它較低者）
    no_tp / no_stop  不用目標價／不用停損（只剩時間出場或期末結算）
    ignore_entry     對照組：不看理想買點，空手就在開盤買——用來分辨賺的是訊號還是出場規則
    """
    levels = active_levels(reports)
    prev = bars["close"].shift()
    tr = pd.concat([bars["high"] - bars["low"], (bars["high"] - prev).abs(),
                    (bars["low"] - prev).abs()], axis=1).max(axis=1, skipna=False)
    atr = tr.rolling(14).mean().shift()   # 只用前一日以前的 K 棒
    trades, pos, li, lv = [], None, 0, None
    for i, b in bars.iterrows():
        d = b["date"]
        while li < len(levels) and levels[li][0] < d:   # 只用 D 日之前（含 D-1 盤後）的報告
            lv = levels[li][1]
            li += 1
        if lv is None:
            continue
        a = float(adj.at[d, stock_id]) if d in adj.index else 1.0
        entered_today = False
        entry_ok = True if ignore_entry else (
            "ideal_buy" in lv and b["low"] <= lv["ideal_buy"]
            and not ("stop_loss" in lv and b["open"] <= lv["stop_loss"]))
        if pos is None and entry_ok:
            blocked = respect_advice and any(x in str(lv["advice"]) for x in BEARISH_ADVICE)
            if min_net_rr is not None and not blocked:
                check = evaluate_levels(f"{stock_id}.TW", ideal_buy=lv.get("ideal_buy"),
                                        stop_loss=lv.get("stop_loss"), take_profit=lv.get("take_profit"),
                                        min_net_rr=min_net_rr, sale_date=d.date())
                blocked = check["passed"] is not True
            if not blocked:
                entered_today = True
                raw = b["open"] if ignore_entry else min(b["open"], lv["ideal_buy"])
                fill = buy_fill_price(raw)
                shares = affordable_shares(notional, fill)
                stop = lv.get("stop_loss")
                if stop_atr is not None and pd.notna(atr.iloc[i]) and stop is not None:
                    stop = min(stop, raw - stop_atr * float(atr.iloc[i]))
                pos = {"entry_date": d, "entry_raw": raw, "entry_adj": a, "shares": shares,
                       "cost": buy_cash_outflow(shares, fill), "bars": 0,
                       "stop": stop, "tp": lv.get("take_profit")}
        if pos is not None:
            stop = pos["stop"] if freeze else lv.get("stop_loss")
            if not freeze and stop_atr is not None and stop is not None and pd.notna(atr.iloc[i]):
                stop = min(stop, pos["entry_raw"] - stop_atr * float(atr.iloc[i]))
            tp = pos["tp"] if freeze else lv.get("take_profit")
            hit_stop = not no_stop and stop is not None and b["low"] <= stop
            hit_tp = not no_tp and tp is not None and b["high"] >= tp \
                and (same_day_tp or not entered_today)
            if hit_stop or hit_tp:
                raw = min(b["open"], stop) if hit_stop else max(b["open"], tp)
                trades.append(_close(stock_id, pos, d, raw, a, "stop" if hit_stop else "take_profit"))
                pos = None
            elif hold_days is not None and pos["bars"] >= hold_days:
                trades.append(_close(stock_id, pos, d, b["close"], a, "time"))
                pos = None
            else:
                pos["bars"] += 1
    if pos is not None:
        last = bars.iloc[-1]
        trades.append(_close(stock_id, pos, last["date"], last["close"],
                             float(adj.at[last["date"], stock_id]), "open_at_end"))
    return trades


def _close(stock_id, pos, d, raw, a, kind):
    # 前復權：把出場價換到與進場同一個基準，差額即除權息的貢獻
    exit_equiv = raw * a / pos["entry_adj"]
    fill = sell_fill_price(exit_equiv) if kind != "open_at_end" else exit_equiv
    # 證交稅看賣出日：債券 ETF 只在法定停徵期內免稅
    proceeds = sell_cash_inflow(pos["shares"], fill, tax_rate=tw_sell_tax_rate(stock_id, d))
    return {"stock_id": stock_id, "entry_date": pos["entry_date"].date(), "entry": round(pos["entry_raw"], 2),
            "exit_date": d.date(), "exit": round(raw, 2), "exit_type": kind,
            "days": None, "cost": pos["cost"], "pnl": proceeds - pos["cost"],
            "ret": proceeds / pos["cost"] - 1}


def buy_and_hold(stock_id, bars, adj, notional):
    b0, b1 = bars.iloc[0], bars.iloc[-1]
    fill = buy_fill_price(b0["open"])
    shares = affordable_shares(notional, fill)
    cost = buy_cash_outflow(shares, fill)
    exit_equiv = b1["close"] * float(adj.at[b1["date"], stock_id]) / float(adj.at[b0["date"], stock_id])
    tax = tw_sell_tax_rate(stock_id, b1["date"])
    return sell_cash_inflow(shares, exit_equiv, tax_rate=tax) / cost - 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--db", default=os.environ.get("STORAGE_DATABASE_URL") or str(REPO / "data" / "stock_analysis.db"),
                   help="分析歷史：SQLAlchemy URL 或 SQLite 檔（預設 STORAGE_DATABASE_URL，未設才用 data/stock_analysis.db）")
    p.add_argument("--notional", type=float, default=100_000, help="每筆名目本金（元）")
    p.add_argument("--respect-advice", action="store_true",
                   help="最新報告建議為賣出／減倉時不進場（預設只看價位）")
    p.add_argument("--same-day-tp", action="store_true", help="進場當天也允許停利出場（偏樂觀）")
    p.add_argument("--min-net-rr", type=float, default=None,
                   help="只在價位通過成本檢核（扣成本後淨風報比 >= 此值）時進場；同批報告上屬 in-sample")
    p.add_argument("--freeze", action="store_true", help="出場價位鎖在進場當天的報告")
    p.add_argument("--hold-days", type=int, default=None, help="持有滿 N 個交易日收盤出場")
    p.add_argument("--stop-atr", type=float, default=None, help="停損至少放在進場價下方 K×ATR14")
    p.add_argument("--no-tp", action="store_true", help="不用目標價出場")
    p.add_argument("--no-stop", action="store_true", help="不用停損出場")
    p.add_argument("--ignore-entry", action="store_true",
                   help="對照組：不看理想買點，空手就在開盤買（出場規則照舊）")
    p.add_argument("--csv", default=None, help="逐筆成交另存 CSV")
    a = p.parse_args(argv)

    reports = load_reports(a.db)
    start = (reports["day"].min() - pd.Timedelta(days=1)).date()
    engine = get_engine()
    px, adj = load_bars(engine, reports["stock_id"].unique(), start)
    first_signal = reports.groupby("stock_id")["day"].min()

    trades, bh = [], {}
    for sid, rep in reports.groupby("stock_id"):
        bars = px[px["stock_id"] == sid].reset_index(drop=True)
        if bars.empty:
            continue
        trades += simulate(sid, rep, bars, adj, a.notional, a.respect_advice, a.same_day_tp, a.min_net_rr,
                           a.freeze, a.hold_days, a.stop_atr, a.no_tp, a.no_stop, a.ignore_entry)
        held = bars[bars["date"] > first_signal[sid]].reset_index(drop=True)
        if len(held):
            bh[sid] = buy_and_hold(sid, held, adj, a.notional)
    bh_0050 = buy_and_hold("0050", px[(px["stock_id"] == "0050") & (px["date"] > reports["day"].min())]
                           .reset_index(drop=True), adj, a.notional) if "0050" in set(px["stock_id"]) else None

    t = pd.DataFrame(trades)
    names = reports.groupby("stock_id")["name"].last()
    mode = "看建議" if a.respect_advice else "只看價位"
    if a.min_net_rr is not None:
        mode += f"＋成本檢核 淨風報比≥{a.min_net_rr:g}（in-sample）"
    print(f"# 每日報告照價位執行（{mode}）")
    print(f"報告 {len(reports)} 份、{reports['stock_id'].nunique()} 檔；行情至 {px['date'].max():%Y-%m-%d}；"
          f"每筆 {a.notional:,.0f} 元\n")
    if t.empty:
        print("沒有任何成交")
        return 0
    days = {d: i for i, d in enumerate(sorted(px["date"].dt.date.unique()))}
    t["days"] = [days[x] - days[e] for e, x in zip(t["entry_date"], t["exit_date"])]
    t["name"] = t["stock_id"].map(names)
    show = t[["stock_id", "name", "entry_date", "entry", "exit_date", "exit", "exit_type", "days", "pnl", "ret"]]
    print(show.to_string(index=False, formatters={"pnl": "{:+,.0f}".format, "ret": "{:+.2%}".format}))
    print("\n## 彙總")
    closed = t[t["exit_type"] != "open_at_end"]
    print(f"- 成交 {len(t)} 筆（已出場 {len(closed)}：停損 {int((t.exit_type == 'stop').sum())}、"
          f"停利 {int((t.exit_type == 'take_profit').sum())}、時間 {int((t.exit_type == 'time').sum())}；"
          f"期末持有 {int((t.exit_type == 'open_at_end').sum())}）")
    book = a.notional * reports["stock_id"].nunique()
    print(f"- 淨損益 {t['pnl'].sum():+,.0f} 元；固定帳本 {book:,.0f} 元 → **報酬率 {t['pnl'].sum() / book:+.2%}**"
          f"（參考：÷累計投入 {t['cost'].sum():,.0f} 元 = {t['pnl'].sum() / t['cost'].sum():+.2%}）")
    with engine.connect() as c:
        exd = pd.read_sql(text("select stock_id, date from market.price_adjustment "
                               "where stock_id = any(:ids) and date >= :s"),
                          c, params={"ids": list(t["stock_id"].unique()), "s": start})
    exd_keys = set(zip(exd["stock_id"], pd.to_datetime(exd["date"]).dt.date))
    on_ex = t[[(s, d) in exd_keys for s, d in zip(t["stock_id"], t["exit_date"])]]
    print(f"- 除權息日：期間 {len(exd)} 個（{', '.join(f'{r.stock_id} {r.date}' for r in exd.itertuples())}）；"
          f"落在除權息日的出場 {len(on_ex)} 筆"
          + (f"（{', '.join(f'{r.stock_id} {r.exit_date} {r.exit_type}' for r in on_ex.itertuples())}）" if len(on_ex) else ""))
    print(f"- 勝率 {(t['pnl'] > 0).mean():.0%}；單筆中位 {t['ret'].median():+.2%}；"
          f"平均持有 {t['days'].mean():.1f} 交易日")
    print("\n## 逐檔")
    per = t.groupby("stock_id").agg(trades=("pnl", "size"), pnl=("pnl", "sum"), cost=("cost", "sum"))
    per["ret"] = per["pnl"] / per["cost"]
    per["buy_hold"] = pd.Series(bh)
    per["name"] = names
    print(per[["name", "trades", "pnl", "ret", "buy_hold"]].to_string(
        formatters={"pnl": "{:+,.0f}".format, "ret": "{:+.2%}".format, "buy_hold": "{:+.2%}".format}))
    never = sorted(set(reports["stock_id"]) - set(t["stock_id"]))
    print(f"\n- 從未成交：{', '.join(f'{s} {names[s]}' for s in never) or '無'}")
    print("\n## 對照（同期、同名目本金、含成本）")
    print(f"- 各檔自首份報告次日開盤買進抱到最後：等權平均 {pd.Series(bh).mean():+.2%}")
    if bh_0050 is not None:
        print(f"- 0050 自第一份報告次日開盤買進抱到最後：{bh_0050:+.2%}")
    if a.csv:
        t.to_csv(a.csv, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
