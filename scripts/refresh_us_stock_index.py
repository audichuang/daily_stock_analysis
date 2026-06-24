#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""增量刷新美股自动补全索引：从 NASDAQ Trader 官方清单补进缺失的新上市代码。

来源（官方公开、免 key、pipe 分隔）：
  - https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt  (NASDAQ)
  - https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt   (NYSE/AMEX 等)

策略：增量 add-missing —— 保留索引中既有 US 条目，只补进官方清单里尚未收录、
且代码不与任何市场冲突的新代码（例如刚上市的 SPCX）。不删除既有条目。

写入三处：public(build 来源)、static(服务用)、data/cache(远端缓存)。

用法：python3 scripts/refresh_us_stock_index.py
"""
import json
import re
import sys
from io import StringIO
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
SOURCES = [
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
]
TARGETS = [
    REPO / "apps" / "dsa-web" / "public" / "stocks.index.json",
    REPO / "static" / "stocks.index.json",
    REPO / "data" / "cache" / "stocks.index.json",
]
# yfinance-friendly 纯代码（含 class share 的点号，如 BRK.B）；排除权证/优先股的特殊符号
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,6}$")


def fetch_symbols() -> dict:
    """Return {symbol: security_name} from both NASDAQ Trader files (Test Issue == 'N')."""
    out = {}
    for url in SOURCES:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        reader = StringIO(resp.text)
        header = reader.readline().rstrip("\n").split("|")
        sym_col = 0  # both files: col 0 is Symbol / ACT Symbol
        name_col = header.index("Security Name")
        test_col = header.index("Test Issue")
        for line in reader:
            if line.startswith("File Creation Time"):
                break
            parts = line.rstrip("\n").split("|")
            if len(parts) <= max(name_col, test_col):
                continue
            sym = parts[sym_col].strip().upper()
            name = parts[name_col].strip()
            if parts[test_col].strip() == "Y":
                continue
            if not sym or not name or not _SYMBOL_RE.match(sym):
                continue
            out.setdefault(sym, name)
    return out


def us_entry(symbol: str, name: str) -> list:
    # mirror existing US row shape: [canonical, display, nameZh, pinyinFull, pinyinAbbr, aliases, market, type, active, popularity]
    return [symbol, symbol, name, "", "", [], "US", "stock", True, 100]


def main() -> int:
    symbols = fetch_symbols()
    print(f"官方清单代码数: {len(symbols)}")
    if len(symbols) < 5000:
        print(f"[Error] 仅解析到 {len(symbols)} 个代码，疑似来源异常，中止。", file=sys.stderr)
        return 1
    if "SPCX" not in symbols:
        print("[Warn] SPCX 不在官方清单（可能已更名/下市），继续。")

    for path in TARGETS:
        if not path.is_file():
            print(f"  [skip] 不存在: {path}")
            continue
        items = json.load(open(path, encoding="utf-8"))
        existing = {str(x[0]).upper() for x in items if isinstance(x, list) and x}
        added = [us_entry(s, n) for s, n in symbols.items() if s not in existing]
        merged = items + added
        with open(path, "w", encoding="utf-8") as f:
            f.write("[\n")
            for i, item in enumerate(merged):
                json.dump(item, f, ensure_ascii=False, separators=(",", ":"))
                f.write(",\n" if i < len(merged) - 1 else "\n")
            f.write("]\n")
        print(f"  [ok] {path.relative_to(REPO)}: {len(items)} -> {len(merged)} (+{len(added)} US)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
