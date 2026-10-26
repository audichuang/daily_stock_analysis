"""持倉即時快照：帳本持股 × 即時價 → 各帳戶權重與損益，最後合併所有帳戶換成台幣看整體集中度。

用法（Doppler 注入 Shioaji 金鑰；少了它台股會靜默退回延遲的 yfinance）：
    doppler run -p shioaji -c dev -- uv run python .claude/skills/portfolio-check/snapshot.py [account_id]
不帶 account_id 時列出全部啟用中的帳戶，再列基金持倉（應用庫 `portfolio_fund_holdings`，以最新淨值估值）並併入合併表。
最後附上每檔持股最近一次系統分析（應用庫 analysis_history）的建議與時間，看報告日期判斷是不是今天的。
各部位依自身幣別換算後，才計算帳戶本位幣總額與台幣合併值；均價與現價仍以部位幣別顯示。
缺價或缺匯率時保留持倉列，總額標為「已知市值（不完整）」並停算該表權重；零成本不計損益率。
"""
import os
import sys
from collections import defaultdict
from math import isfinite
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from data_provider.base import DataFetcherManager  # noqa: E402
from src.services.fund_service import FundService  # noqa: E402
from src.services.portfolio_service import PortfolioService  # noqa: E402


def _positive_number(value):
    """缺值、非有限值與非正數都不能當作報價或匯率。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number > 0 else None


class FxRates:
    """股票、帳戶與基金共用同一輪台幣匯率，失敗也快取避免重試。"""

    def __init__(self):
        self.rates = {"TWD": 1.0}

    def to_twd(self, currency):
        currency = currency.strip().upper()
        if currency not in self.rates:
            try:
                symbol = "TWD=X" if currency == "USD" else f"{currency}TWD=X"
                self.rates[currency] = _positive_number(yf.Ticker(symbol).fast_info["last_price"])
            except Exception:  # noqa: BLE001 - 缺匯率只讓相關估值不完整
                self.rates[currency] = None
        return self.rates[currency]

    def convert(self, amount, currency, target="TWD"):
        if amount is None:
            return None
        if currency.strip().upper() == target.strip().upper():
            return amount
        source_rate, target_rate = self.to_twd(currency), self.to_twd(target)
        if source_rate is None or target_rate is None:
            return None
        return amount * source_rate / target_rate


def _position_row(position, fetcher, rates, base_currency):
    try:
        quote = fetcher.get_realtime_quote(position["symbol"])
    except Exception:  # noqa: BLE001 - 即時價失敗仍可使用歷史補價
        quote = None
    live_price = _positive_number(quote.price) if quote else None
    stored_price = _positive_number(position["last_price"]) if position["price_available"] else None
    price = live_price if live_price is not None else stored_price
    value = position["quantity"] * price if price is not None else None
    return {
        **position,
        "name": position.get("name") or "",
        "price": price,
        "change_pct": quote.change_pct if live_price is not None else None,
        "source": (str(quote.source).split(".")[-1] if live_price is not None
                   else f"{position['price_source']}@{position['price_date']}"),
        "value_base": rates.convert(value, position["currency"], base_currency),
        "value_twd": rates.convert(value, position["currency"]),
    }


def _total_label(total, complete):
    return f"總市值 {total:,.0f}" if complete else f"已知市值 {total:,.0f}（不完整；權重無法計算）"


def _p(value):
    return f"{value:>+8.1f}" if value is not None else f"{'-':>8}"


def _print_fund_comparison(items):
    # 基金每天的判斷基準：跟 0050（含息）比相對強弱，SKILL.md 第 4 節的減碼條件看「近6月落後」
    bench = {}
    try:
        from src.services.fund_service import compute_returns, compute_risk
        closes = yf.Ticker("0050.TW").history(period="2y", auto_adjust=True)["Close"].dropna()
        series = [{"date": i.date(), "nav": float(v)} for i, v in closes.items()]
        bench = {**compute_returns(series), **compute_risk(series), "date": series[-1]["date"]}
    except Exception as exc:  # noqa: BLE001 - 基準取不到只少比較欄
        print(f"**0050 基準取不到：{exc}")

    print(f"== 基金對照 0050（含息，{bench.get('date', '-')}）")
    print(f"{'基金':16}{'近1月':>8}{'近6月':>8}{'近1年':>8}{'1年回撤':>8}{'距1年高':>8}{'6月落後':>8}")
    if bench:
        print(f"{'0050':16}{_p(bench['m1'])}{_p(bench['m6'])}{_p(bench['y1'])}{_p(bench['max_drawdown'])}")
    fund_svc = FundService()
    for f in items:
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


def main(argv=None):
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    argv = sys.argv[1:] if argv is None else argv
    account_id = int(argv[0]) if argv else None
    snap = PortfolioService().get_portfolio_snapshot(account_id=account_id, include_realtime=False, read_only=True)
    fetcher = DataFetcherManager()
    rates = FxRates()
    usd_twd = rates.to_twd("USD")
    combined = defaultdict(float)
    names = {}
    missing = set()
    combined_complete = True

    def add_value(key, name, value):
        names[key] = name
        combined[key] += value if value is not None else 0
        if value is None:
            missing.add(key)

    for acc in snap["accounts"]:
        rows = [_position_row(p, fetcher, rates, acc["base_currency"]) for p in acc["positions"]]
        total = sum(r["value_base"] for r in rows if r["value_base"] is not None)
        complete = all(r["value_base"] is not None for r in rows)
        print(f"== 帳戶 {acc['account_id']} {acc['account_name']}（{acc['base_currency']}）{_total_label(total, complete)}")
        print(f"{'代碼':10}{'名稱':10}{'幣別':>5}{'股數':>10}{'均價':>9}{'現價':>9}"
              f"{'今日%':>7}{'權重':>7}{'損益%':>8}  來源")
        for r in sorted(rows, key=lambda r: -(r["value_base"] or 0)):
            price, cost, chg = r["price"], _positive_number(r["avg_cost"]), r["change_pct"]
            price_s = f"{price:.2f}" if price is not None else "無法取得"
            cost_s = f"{r['avg_cost']:.2f}" if r["avg_cost"] is not None else "-"
            chg_s = f"{chg:+.2f}" if chg is not None else "-"
            weight = f"{r['value_base'] / total:.1%}" if complete and total > 0 else "-"
            pnl = f"{price / cost - 1:+.1%}" if price is not None and cost is not None else "-"
            print(f"{r['symbol']:10}{r['name'][:5]:10}{r['currency']:>5}{r['quantity']:>10g}"
                  f"{cost_s:>9}{price_s:>9}{chg_s:>7}{weight:>7}{pnl:>8}  {r['source']}")
            add_value(r["symbol"], r["name"], r["value_twd"])
            if price is not None and (r["value_base"] is None or r["value_twd"] is None):
                print(f"  **{r['symbol']} 缺少估值匯率（{r['currency']}／{acc['base_currency']}／TWD）")
        print()

    if account_id is None:
        try:
            fund_snap = FundService().list_holdings()
        except Exception as exc:  # noqa: BLE001 - 基金段失敗不擋股票快照
            fund_snap = None
            combined_complete = False
            print(f"== 基金持倉讀取失敗：{exc}（合併表不含基金）\n")
        if fund_snap and fund_snap["items"]:
            if fund_snap["nav_error"]:
                print(f"**基金淨值庫無法讀取：{fund_snap['nav_error']}")
            print("== 基金（帳本外，淨值為最新淨值日）")
            print(f"{'基金':16}{'幣別':>5}{'單位數':>10}{'淨值':>9}{'淨值日':>12}{'市值':>11}{'損益%':>8}  通路")
            for f in fund_snap["items"]:
                value, nav = f["market_value"], f["nav"]
                stale = "（逾期）" if f["is_stale"] else ""
                nav_s = f"{nav:.2f}" if nav is not None else "無法取得"
                value_s = f"{value:,.0f}" if value is not None else "無法取得"
                print(f"{f['fund_name'][:8]:16}{f['currency']:>5}{f['units']:>10g}{nav_s:>9}"
                      f"{str(f['nav_date'] or '-'):>12}{value_s:>11}{_p(f['pnl_pct'])}  {f['platform']}{stale}")
                converted = rates.convert(value, f["currency"])
                add_value(f"F:{f['fund_id']}", f["fund_name"], converted)
                if converted is None:
                    print(f"  **{f['fund_name']} 沒有淨值或匯率，合併估值不完整")
            print()
            _print_fund_comparison(fund_snap["items"])

    grand = sum(combined.values())
    combined_complete = combined_complete and not missing
    print(f"== 全部帳戶合併（台幣，USD/TWD={usd_twd or '取不到'}）{_total_label(grand, combined_complete)}")
    for sym, value in sorted(combined.items(), key=lambda kv: -kv[1]):
        value_s = f"{value:,.0f}"
        if sym in missing:
            value_s = f"{value_s}（不完整）" if value else "無法取得"
        weight = f"{value / grand:.1%}" if combined_complete and grand > 0 else "-"
        print(f"{sym:10}{names[sym][:5]:10}{value_s:>16}{weight:>7}")

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


if __name__ == "__main__":
    main()
