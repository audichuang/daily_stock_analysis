"""持倉即時快照：帳本持股 × 即時價 → 各帳戶權重與損益，最後合併所有帳戶換成台幣看整體集中度。

用法（Doppler 注入 Shioaji 金鑰；少了它台股會靜默退回延遲的 yfinance）：
    doppler run -p shioaji -c dev -- uv run python .claude/skills/portfolio-check/snapshot.py [account_id]
不帶 account_id 時列出全部啟用中的帳戶，再列基金持倉（應用庫 `portfolio_fund_holdings`，以最新淨值估值）並併入合併表。
最後附上每檔持股最近一次系統分析（應用庫 analysis_history）的建議與時間，看報告日期判斷是不是今天的。
"""
import os
import sys
from collections import defaultdict
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from data_provider.base import DataFetcherManager  # noqa: E402
from src.services.fund_service import FundService  # noqa: E402
from src.services.portfolio_service import PortfolioService  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
account_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
snap = PortfolioService().get_portfolio_snapshot(account_id=account_id, include_realtime=False, read_only=True)
fetcher = DataFetcherManager()
try:
    usd_twd = float(yf.Ticker("TWD=X").fast_info["last_price"])
except Exception:
    usd_twd = None
to_twd = {"TWD": 1.0, "USD": usd_twd}

combined = defaultdict(float)
names = {}
for acc in snap["accounts"]:
    rows = []
    for p in acc["positions"]:
        q = fetcher.get_realtime_quote(p["symbol"])
        live = bool(q and q.price)
        price = q.price if live else p["last_price"]
        source = str(q.source).split(".")[-1] if live else f"{p['price_source']}@{p['price_date']}"
        rows.append((p["symbol"], p.get("name") or "", p["quantity"], p["avg_cost"], price, q.change_pct if live else None, source))
    total = sum(r[2] * r[4] for r in rows)
    print(f"== 帳戶 {acc['account_id']} {acc['account_name']}（{acc['base_currency']}）總市值 {total:,.0f}")
    print(f"{'代碼':10}{'名稱':10}{'股數':>10}{'均價':>9}{'現價':>9}{'今日%':>7}{'權重':>7}{'損益%':>8}  來源")
    for sym, name, qty, cost, price, chg, src in sorted(rows, key=lambda r: -r[2] * r[4]):
        chg_s = f"{chg:+.2f}" if chg is not None else "-"
        print(f"{sym:10}{name[:5]:10}{qty:>10g}{cost:>9.2f}{price:>9.2f}{chg_s:>7}{qty * price / total:>7.1%}{price / cost - 1:>+8.1%}  {src}")
        rate = to_twd.get(acc["base_currency"])
        if rate:
            combined[sym] += qty * price * rate
            names[sym] = name
    print()

if account_id is None:
    try:
        fund_snap = FundService().list_holdings()
    except Exception as exc:  # noqa: BLE001 - 基金段失敗不擋股票快照
        fund_snap = None
        print(f"== 基金持倉讀取失敗：{exc}（合併表不含基金）\n")
    if fund_snap and fund_snap["items"]:
        if fund_snap["nav_error"]:
            print(f"**基金淨值庫無法讀取：{fund_snap['nav_error']}")
        print("== 基金（帳本外，淨值為最新淨值日）")
        print(f"{'基金':16}{'單位數':>10}{'淨值':>9}{'淨值日':>12}{'市值':>11}{'損益%':>8}  通路")
        for f in fund_snap["items"]:
            value, nav = f["market_value"], f["nav"]
            stale = "（逾期）" if f["is_stale"] else ""
            print(f"{f['fund_name'][:8]:16}{f['units']:>10g}{(nav or 0):>9.2f}{str(f['nav_date'] or '-'):>12}"
                  f"{(value or 0):>11,.0f}{(f['pnl_pct'] or 0):>+8.1f}  {f['platform']}{stale}")
            rate = to_twd.get(f["currency"])
            if value is not None and rate:
                key = f"F:{f['fund_id']}"
                combined[key] += value * rate
                names[key] = f["fund_name"]
            else:
                print(f"  **{f['fund_name']} 沒有淨值或匯率，未計入合併表")
        print()
        # 基金每天的判斷基準：跟 0050（含息）比相對強弱，SKILL.md 第 4 節的減碼條件看「近6月落後」
        bench = {}
        try:
            from src.services.fund_service import compute_returns, compute_risk
            closes = yf.Ticker("0050.TW").history(period="2y", auto_adjust=True)["Close"].dropna()
            series = [{"date": i.date(), "nav": float(v)} for i, v in closes.items()]
            bench = {**compute_returns(series), **compute_risk(series), "date": series[-1]["date"]}
        except Exception as exc:  # noqa: BLE001 - 基準取不到只少比較欄
            print(f"**0050 基準取不到：{exc}")

        def _p(v):
            return f"{v:>+8.1f}" if v is not None else f"{'-':>8}"

        print(f"== 基金對照 0050（含息，{bench.get('date', '-')}）")
        print(f"{'基金':16}{'近1月':>8}{'近6月':>8}{'近1年':>8}{'1年回撤':>8}{'距1年高':>8}{'6月落後':>8}")
        if bench:
            print(f"{'0050':16}{_p(bench['m1'])}{_p(bench['m6'])}{_p(bench['y1'])}{_p(bench['max_drawdown'])}")
        fund_svc = FundService()
        for f in fund_snap["items"]:
            try:
                det = fund_svc.get_detail(f["fund_id"])
                pts = fund_svc.get_nav_history(f["fund_id"], days=365)["points"]
            except Exception as exc:  # noqa: BLE001
                print(f"{f['fund_name'][:8]:16}取不到：{exc}")
                continue
            ret = det["returns"]
            off_high = (det["nav"] / max(p["nav"] for p in pts) - 1) * 100 if pts and det["nav"] else None
            lag = ret["m6"] - bench["m6"] if ret["m6"] is not None and bench.get("m6") is not None else None
            print(f"{f['fund_name'][:8]:16}{_p(ret['m1'])}{_p(ret['m6'])}{_p(ret['y1'])}"
                  f"{_p(det['risk']['max_drawdown'])}{_p(off_high)}{_p(lag)}")
        print()

grand = sum(combined.values())
print(f"== 全部帳戶合併（台幣，USD/TWD={usd_twd or '取不到，美股未計入'}）總市值 {grand:,.0f}")
for sym, value in sorted(combined.items(), key=lambda kv: -kv[1]):
    print(f"{sym:10}{names[sym][:5]:10}{value:>12,.0f}{value / grand:>7.1%}")

print()
print("== 最近一次系統分析（每日報告／Web）")
engine = create_engine(os.environ["STORAGE_DATABASE_URL"])
with engine.connect() as conn:
    for sym in sorted(combined, key=lambda k: -combined[k]):
        if sym.startswith("F:"):  # 基金沒有每日個股分析
            continue
        row = conn.execute(
            text(
                "SELECT created_at, operation_advice, sentiment_score, analysis_summary FROM dsa.analysis_history "
                "WHERE code = :c ORDER BY created_at DESC LIMIT 1"
            ),
            {"c": sym},
        ).fetchone()
        if row is None:
            print(f"{sym:10}（尚無分析）")
            continue
        summary = (row[3] or "").replace("\n", " ")[:80]
        print(f"{sym:10}{row[0]:%m-%d %H:%M}  {row[1]}（{row[2]}）  {summary}")
