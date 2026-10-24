#!/usr/bin/env python
"""印出使用者目前持有的台股／台股 ETF 代號清單（JSON），給 23:00 媒體點名排程標出「你的持股被點名」。

唯讀：自己開純 SQLAlchemy 連線（Postgres 連線選項＋交易層雙重 READ ONLY）只 SELECT 帳戶／成交／公司行動，
重播出現有數量（對齊 ``PortfolioService._replay_account``）；**不碰 PortfolioService／DatabaseManager**（它的 __init__
會對正式應用庫 create_all、寫遷移紀錄、ALTER TABLE；應用庫 `dsa` schema 本機與 NAS 正式 Web 共用，這裡一個字都不能寫）。只收所有啟用中帳戶裡 market 為 tw、
數量大於 0 的部位；代號一律帶 .TW／.TWO（帳本若存裸代號，用 ``apps/dsa-web/public/stocks.index.json`` 對回後綴，
對不到的放進 ``skipped``，不猜）。基金是獨立持倉表，不在這裡。

    uv run --env-file .env python scripts/portfolio_codes.py

成功：stdout 一行 JSON ``{"as_of": ..., "codes": [{"code","name","accounts","quantity"}], "skipped": [...]}``。
任何失敗：stdout 印 ``{"error": "..."}``、結束碼 1（訊息只放例外類別與簡短原因，不含連線字串）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STOCK_INDEX = ROOT / "apps" / "dsa-web" / "public" / "stocks.index.json"
BARE_TW = re.compile(r"^[0-9]{4,6}[A-Z]?$")  # 語意真源是 src/services/market_symbol_utils.py，這裡只判斷「裸代號」


def _bare_lookup(index_path: Path) -> dict:
    """裸代號 -> .TW／.TWO 代號（列格式 [code, bare_code, name, ...]）。"""
    with index_path.open(encoding="utf-8") as f:
        return {r[1]: r[0] for r in json.load(f) if r[0].endswith((".TW", ".TWO"))}


def _canonical(symbol: str, lookup) -> str | None:
    """帶後綴且格式合法 → 正規化；裸代號 → 查索引；其餘 None。lookup 是 callable，需要時才載入索引。"""
    from src.services.market_symbol_utils import normalize_suffix_market_symbol, is_tw_suffix_symbol

    text = (symbol or "").strip().upper()
    if "." in text:
        norm = normalize_suffix_market_symbol(text)
        return norm if norm and is_tw_suffix_symbol(norm) else None
    return lookup().get(text) if BARE_TW.match(text) else None


def collect(snapshot: dict, index_path: Path = STOCK_INDEX) -> dict:
    """snapshot（get_portfolio_snapshot 的回傳）→ 輸出 dict；純函式，測試直接餵假 snapshot。"""
    cache: dict = {}

    def lookup():
        if "m" not in cache:
            cache["m"] = _bare_lookup(index_path) if index_path.exists() else {}
        return cache["m"]

    held: dict[str, dict] = {}
    skipped = []
    for acc in snapshot.get("accounts") or []:
        for p in acc.get("positions") or []:
            qty = float(p.get("quantity") or 0)
            if (p.get("market") or acc.get("market")) != "tw" or qty <= 0:
                continue
            code = _canonical(p.get("symbol"), lookup)
            if code is None:
                skipped.append(p.get("symbol"))
                continue
            row = held.setdefault(code, {"code": code, "name": p.get("name") or "", "accounts": [], "quantity": 0.0})
            if not row["name"]:
                row["name"] = p.get("name") or ""
            label = acc.get("account_name") or str(acc.get("account_id"))
            if label not in row["accounts"]:
                row["accounts"].append(label)
            row["quantity"] = round(row["quantity"] + qty, 8)
    return {"as_of": snapshot.get("as_of"), "codes": sorted(held.values(), key=lambda r: r["code"]),
            "skipped": skipped}


EPS = 1e-8  # 與 PortfolioService 的 EPS 同值
_VALID_MARKETS = {"cn", "hk", "us", "jp", "kr", "tw"}


def _position_symbol(symbol: str) -> str:
    """與 PortfolioService._normalize_symbol_for_position 同一套正規化（不能 import 它，見 _snapshot）。"""
    from data_provider.base import canonical_stock_code, normalize_stock_code

    if not (symbol or "").strip():
        return ""
    raw = canonical_stock_code(symbol)
    if len(raw) >= 8 and raw[:2] in {"SH", "SZ", "BJ"} and raw[2:].isdigit():
        return raw
    if "." in raw:
        base, suffix = raw.rsplit(".", 1)
        if base.isdigit() and suffix in {"SH", "SS", "SZ", "BJ"}:
            return f"{'SH' if suffix == 'SS' else suffix}{base}"
    return canonical_stock_code(normalize_stock_code(symbol))


def _replay_quantities(trades, actions) -> dict:
    """成交＋拆分重播出 {(symbol, market, currency): 數量}；邏輯對齊 PortfolioService._replay_account。

    同日順序 corp -> trade、再依 id；買入加、賣出減（超賣丟 ValueError，與服務一致）、拆分乘 split_ratio；
    現金股利不影響數量。成本法（fifo／avg）只影響成本，不影響總數量，所以這裡不分。
    """
    events = [("corp", a.effective_date, a.id, a) for a in actions]
    events += [("trade", t.trade_date, t.id, t) for t in trades]
    events.sort(key=lambda e: (e[1], 0 if e[0] == "corp" else 1, e[2]))
    held: dict = {}
    for kind, _date, _id, ev in events:
        market = (ev.market or "").strip().lower()
        if market not in _VALID_MARKETS:
            raise ValueError("invalid market")
        key = (_position_symbol(ev.symbol), market, (ev.currency or "").strip().upper())
        if kind == "trade":
            qty, price = float(ev.quantity or 0.0), float(ev.price or 0.0)
            if qty <= 0 or price <= 0:
                raise ValueError("invalid trade quantity or price")
            side = (ev.side or "").lower().strip()
            if side == "buy":
                held[key] = held.get(key, 0.0) + qty
            elif side == "sell":
                left = held.get(key, 0.0) - qty
                if left < -EPS:
                    raise ValueError("oversell")
                held[key] = max(left, 0.0)
            else:
                raise ValueError("unsupported trade side")
            continue
        action = (ev.action_type or "").strip().lower()
        if action == "split_adjustment":
            ratio = float(ev.split_ratio or 0.0)
            if ratio <= 0:
                raise ValueError("invalid split_ratio")
            if key in held and abs(ratio - 1.0) > EPS:
                held[key] *= ratio
        elif action != "cash_dividend":
            raise ValueError("unsupported corporate action")
    return held


def _read_only_engine(url: str):
    """純 SQLAlchemy 引擎、資料庫端強制唯讀。

    不能建 PortfolioService／DatabaseManager：後者的 __init__ 會對應用庫跑 create_all、寫遷移紀錄、
    ALTER TABLE，``read_only=True`` 之類的旗標來得太晚。Postgres 連線選項與交易層各設一次唯讀。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    if parsed.get_backend_name() == "postgresql":
        # 正式 URL 的 query 已帶 options=-csearch_path=dsa：要接在後面，不能用 connect_args 覆蓋掉
        existing = parsed.query.get("options") or ""
        if not isinstance(existing, str):
            existing = " ".join(existing)
        parsed = parsed.update_query_dict(
            {"options": f"{existing} -c default_transaction_read_only=on".strip()})
    return create_engine(parsed)


def _load_snapshot(engine, as_of=None) -> dict:
    """SELECT 啟用帳戶的成交／公司行動，重播成 collect() 吃的 snapshot 形狀。"""
    from datetime import date

    from sqlalchemy import text

    from src.data.stock_index_loader import get_index_stock_name

    as_of = as_of or date.today()
    accounts = []
    with engine.connect() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SET TRANSACTION READ ONLY"))
        rows = conn.execute(text(
            "SELECT id, name, market FROM portfolio_accounts WHERE is_active ORDER BY id")).all()
        for acc_id, acc_name, acc_market in rows:
            trades = conn.execute(text(
                "SELECT id, trade_date, symbol, market, currency, side, quantity, price FROM portfolio_trades "
                "WHERE account_id = :a AND trade_date <= :d ORDER BY trade_date, id"),
                {"a": acc_id, "d": as_of}).all()
            actions = conn.execute(text(
                "SELECT id, effective_date, symbol, market, currency, action_type, split_ratio "
                "FROM portfolio_corporate_actions WHERE account_id = :a AND effective_date <= :d "
                "ORDER BY effective_date, id"), {"a": acc_id, "d": as_of}).all()
            held = _replay_quantities(trades, actions)
            accounts.append({
                "account_id": acc_id, "account_name": acc_name, "market": acc_market,
                "positions": [{"symbol": sym, "name": get_index_stock_name(sym) or "", "market": mkt,
                               "currency": cur, "quantity": round(q, 8)}
                              for (sym, mkt, cur), q in sorted(held.items()) if q > EPS],
            })
    return {"as_of": as_of.isoformat(), "accounts": accounts}


def _snapshot() -> dict:
    import os

    url = (os.environ.get("STORAGE_DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError("STORAGE_DATABASE_URL 未設定")
    engine = _read_only_engine(url)
    try:
        return _load_snapshot(engine)
    finally:
        engine.dispose()


def main(argv=None, snapshot_fn=None) -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    try:
        out = collect((snapshot_fn or _snapshot)())
    except Exception as exc:  # noqa: BLE001 - 任何失敗都要印 JSON error；不印 str(exc)，SQLAlchemy 的訊息可能帶連線字串
        print(json.dumps({"error": f"{type(exc).__name__}: 讀持倉失敗"}, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
