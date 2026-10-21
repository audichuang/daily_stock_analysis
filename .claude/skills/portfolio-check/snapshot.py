"""持倉即時快照：帳本持股 × 即時價 → 各帳戶權重與損益，最後合併所有帳戶換成台幣看整體集中度。

用法（Doppler 注入 Shioaji 金鑰；少了它台股會靜默退回延遲的 yfinance）：
    doppler run -p shioaji -c dev -- uv run python .claude/skills/portfolio-check/snapshot.py [account_id]
不帶 account_id 時列出全部啟用中的帳戶。帳本外的資產（基金）不在這裡，見 SKILL.md。
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

grand = sum(combined.values())
print(f"== 全部帳戶合併（台幣，USD/TWD={usd_twd or '取不到，美股未計入'}）總市值 {grand:,.0f}")
for sym, value in sorted(combined.items(), key=lambda kv: -kv[1]):
    print(f"{sym:10}{names[sym][:5]:10}{value:>12,.0f}{value / grand:>7.1%}")

print()
print("== 最近一次系統分析（每日報告／Web）")
engine = create_engine(os.environ["STORAGE_DATABASE_URL"])
with engine.connect() as conn:
    for sym in sorted(combined, key=lambda k: -combined[k]):
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
