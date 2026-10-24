#!/usr/bin/env python
"""印出使用者目前持有的台股／台股 ETF 代號清單（JSON），給 23:00 媒體點名排程標出「你的持股被點名」。

唯讀：走 ``PortfolioService.get_portfolio_snapshot(include_realtime=False, read_only=True)``，不抓即時價、不寫快照表
（應用庫 `dsa` schema 本機與 NAS 正式 Web 共用，這裡一個字都不能寫）。只收所有啟用中帳戶裡 market 為 tw、
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


def _snapshot() -> dict:
    from src.services.portfolio_service import PortfolioService

    return PortfolioService().get_portfolio_snapshot(include_realtime=False, read_only=True)


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
