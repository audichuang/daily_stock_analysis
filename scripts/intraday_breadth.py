#!/usr/bin/env python
"""盤中即時 breadth：Shioaji 批次 snapshot × market schema 的前復權均線。

盤前判讀（skill `tw-morning-call`）的數字全是前一交易日收盤；被問「今天怎麼買」時
需要的是現在。這支就補那一格：流動性池的即時漲跌家數、站上 MA20／MA60 比例、
漲停鎖死檔數、距 60 日高中位。

    doppler run -p shioaji -c dev -- uv run --env-file .env python scripts/intraday_breadth.py
    ... scripts/intraday_breadth.py --codes 2344,2408,2337   # 只看指定族群，逐檔明細

**盤中值不是收盤值**：2026-08-03 盤中 09:50 中位 +3.37%，收盤 +0.66%。引用時標時點。
收盤並更新 DB 之後跑會看到「今日%」全歸零——那時 DB 基準日就是今天，`prev` 與 snapshot 是同一根。
用輸出的「DB 基準日」辨識這件事。
需要 Doppler 注入 SHIOAJI_API_KEY／SHIOAJI_SECRET_KEY；缺金鑰時 Shioaji 靜默降級，
本腳本改為直接失敗（延遲報價算 breadth 沒有意義）。
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_provider.shioaji_fetcher import _ensure_session  # noqa: E402
from market_data.adjust import load_factors  # noqa: E402
from market_data.db import get_engine  # noqa: E402

BATCH = 300  # 單次 snapshots 的 contract 數


def load_panel(engine, codes=None):
    """回傳 (前復權面板, 前一交易日未還原收盤, 20 日均額/億)。"""
    where = "and stock_id = any(:codes)" if codes else ""
    with engine.connect() as c:
        px = pd.read_sql(
            text(
                f"""select stock_id, date, close, volume from market.price
                    where date > (select max(date) from market.price) - interval '120 days' {where}"""
            ),
            c,
            params={"codes": codes} if codes else {},
            parse_dates=["date"],
        )
    piv = px.pivot(index="date", columns="stock_id", values="close").sort_index()
    vol = px.pivot(index="date", columns="stock_id", values="volume").sort_index()
    padj = piv * load_factors(engine, piv.index, piv.columns)
    amt = (piv * vol).tail(20).mean() / 1e8
    return padj, piv.iloc[-1], amt, piv.index[-1]


def snap(api, codes):
    """批次抓 snapshot，回傳 {code: (現價, 是否漲停鎖死)}。"""
    out = {}
    for i in range(0, len(codes), BATCH):
        contracts, limits = [], {}
        for cd in codes[i : i + BATCH]:
            ct = api.Contracts.Stocks[cd]
            if ct is None:
                continue
            contracts.append(ct)
            limits[cd] = getattr(ct, "limit_up", None)  # 漲跌停價只在 contract 上
        for s in api.snapshots(contracts):
            d = dict(s)  # builtins.Snapshot 沒有 _asdict
            cd, close = str(d["code"]), float(d["close"] or 0)
            if not close:
                continue
            up = limits.get(cd)
            # 鎖死 = 觸漲停且一檔委賣掛量歸零（本路徑無五檔，只能到「掛量歸零」）
            locked = bool(up) and abs(close - float(up)) < 1e-9 and not d.get("sell_volume")
            out[cd] = (close, locked)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--min-turnover", type=float, default=1.0, help="流動性池門檻，20 日均額（億），預設 1.0")
    ap.add_argument("--codes", help="逗號分隔代碼，只看這幾檔並印逐檔明細")
    a = ap.parse_args()

    codes = [c.strip() for c in a.codes.split(",")] if a.codes else None
    engine = get_engine()
    padj, prev, amt, as_of = load_panel(engine, codes)

    pool = codes or [
        s for s in padj.columns if s.isdigit() and len(s) == 4 and amt.get(s, 0) >= a.min_turnover
    ]
    pool = [s for s in pool if s in padj.columns and prev.get(s)]
    ma20, ma60 = padj[pool].tail(20).mean(), padj[pool].tail(60).mean()
    h60 = padj[pool].tail(60).max()

    api = _ensure_session()
    if api is None:
        sys.exit("no Shioaji session — 檢查 Doppler 是否注入 SHIOAJI_API_KEY／SHIOAJI_SECRET_KEY")
    live = snap(api, pool)

    have = [s for s in pool if s in live]
    cur = pd.Series({s: live[s][0] for s in have})
    pct = cur / prev[have] - 1
    locked = [s for s in have if live[s][1]]

    print(f"as of {datetime.now():%Y-%m-%d %H:%M:%S}（盤中值，非收盤）　DB 基準日 {as_of:%Y-%m-%d}")
    print(f"流動性池 {len(have)} 檔（20 日均額 >= {a.min_turnover} 億）")
    print(f"  前一交易日收盤　站上 MA20 {(prev[have] >= ma20[have]).mean():.1%}　站上 MA60 {(prev[have] >= ma60[have]).mean():.1%}")
    print(f"  即時　　　　　　站上 MA20 {(cur >= ma20[have]).mean():.1%}　站上 MA60 {(cur >= ma60[have]).mean():.1%}")
    print(f"  上漲 {(pct > 0).sum()} / 下跌 {(pct < 0).sum()}　中位 {pct.median() * 100:+.2f}%　漲逾 3% {(pct > 0.03).sum()} 檔　跌逾 3% {(pct < -0.03).sum()} 檔")
    print(f"  距 60 日高中位 {(cur / h60[have] - 1).median() * 100:+.1f}%　距 MA20 中位 {(cur / ma20[have] - 1).median() * 100:+.1f}%")
    print(f"  漲停鎖死（委賣掛量為 0，下單排不到）{len(locked)} 檔: {sorted(locked)}")

    if codes:
        with engine.connect() as c:
            names = dict(c.execute(text("select stock_id, name from market.stock_info where stock_id = any(:i)"), {"i": have}).fetchall())
        print(f"\n{'代碼':7}{'名稱':10}{'現價':>10}{'今日%':>8}{'距60日高':>10}{'距MA20':>9}{'鎖死':>6}")
        for s in sorted(have, key=lambda x: -pct[x]):
            print(f"{s:7}{names.get(s, ''):10}{cur[s]:>10.2f}{pct[s] * 100:>7.2f}%{(cur[s] / h60[s] - 1) * 100:>9.1f}%{(cur[s] / ma20[s] - 1) * 100:>8.1f}%{'  鎖死' if live[s][1] else '':>6}")


if __name__ == "__main__":
    main()
