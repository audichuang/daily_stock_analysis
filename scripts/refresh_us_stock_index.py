#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷新美股自动补全索引：从 NASDAQ Trader 官方清单补进新代码，并**修正既有列**的名称与类型。

来源（官方公开、免 key、pipe 分隔）：
  - https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt  (NASDAQ)
  - https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt   (NYSE/AMEX 等)

策略：
  - 补进官方清单里尚未收录的新代码（例如刚上市的 SPCX）。不删除既有条目。
  - **同时修正既有 US 列**的 `nameZh` 与 `type`。原本是 add-only，於是最初灌进来的
    Refinitiv 缩写名（`TAIWAN SEMICON.SPN.ADR 1:5`、`APPLIED MATS.`、`ALPHABET 'A'`）
    永远留着。那串会变成报告标题、prompt 开头，以及**五个新闻检索维度的搜寻字串**
    ——没人用这种字串发新闻，所以真新闻会被相关度过滤掉。
  - `type` 从官方 ETF 栏位填，取代 `search_service` 那个靠名称关键词猜 ETF 的启发式
    （它会把 `NORTHERN TRUST` 与约 192 档 REIT 判成 ETF）。

**只动 market == "US" 的列**；台股/A股/港股增量一列都不碰（这个档案进版控，踩过一次）。

写入三处：public(build 来源)、static(服务用)、data/cache(远端缓存)。

用法：python3 scripts/refresh_us_stock_index.py [--dry-run]
"""
import argparse
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


# 官方 Security Name 的證券類別尾巴。切在**第一個**標記，因為標記之後全是證券形態
# 描述而不是公司名——SPAC 的 `Units, each consisting of one Class A ordinary share and
# one-tenth of one redeemable warrant` 整句拿去當搜尋字串，比原本的 Refinitiv 縮寫更糟。
_TYPE_TAIL_RE = re.compile(
    r"\s+(?:"
    r"Common\s+Stock"
    r"|Class\s+[A-Z]\b"
    r"|Ordinary\s+Shares?"
    r"|American\s+Depositary"
    r"|Depositary\s+(?:Receipt|Share)"
    r"|Units?,"
    r"|Preferred\s+(?:Stock|Share)"
    r"|Warrants?\b"
    r"|Subordinate\s+Voting"
    r").*$",
    re.IGNORECASE,
)
# Refinitiv 尾巴：ADR 比例、交易所後綴。官方清單查無的 OTC 列只能靠這個清。
_NAME_TAIL_RE = re.compile(
    r"[.\s]+(?:SPN\.|UNSP\.)?ADR\s*\d+:\d+$"
    r"|[.\s]+AMER\.DEPY\.\s*SHS\.\s*\d+:\d+$"
    r"|\s*\((?:NAS|NYS|OTC|ASE)\)$"
)


def clean_name(name: str) -> str:
    """官方 Security Name → 可讀的公司名（也用來清官方清單查無的 OTC 舊列）。"""
    name = (name or "").split(" - ")[0].strip()
    name = _TYPE_TAIL_RE.sub("", name).strip()
    prev = None
    while prev != name:
        prev = name
        name = _NAME_TAIL_RE.sub("", name).strip()
    return name.rstrip(" ,;-")


def fetch_symbols() -> dict:
    """Return {symbol: (security_name, is_etf)} from both NASDAQ Trader files."""
    out = {}
    for url in SOURCES:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        reader = StringIO(resp.text)
        header = reader.readline().rstrip("\n").split("|")
        sym_col = 0  # both files: col 0 is Symbol / ACT Symbol
        name_col = header.index("Security Name")
        test_col = header.index("Test Issue")
        etf_col = header.index("ETF") if "ETF" in header else None
        for line in reader:
            if line.startswith("File Creation Time"):
                break
            parts = line.rstrip("\n").split("|")
            if len(parts) <= max(name_col, test_col, etf_col or 0):
                continue
            sym = parts[sym_col].strip().upper()
            name = parts[name_col].strip()
            if parts[test_col].strip() == "Y":
                continue
            if not sym or not name or not _SYMBOL_RE.match(sym):
                continue
            is_etf = etf_col is not None and parts[etf_col].strip() == "Y"
            out.setdefault(sym, (clean_name(name), is_etf))
    return out


# 既有 US 列的栏位位置（列形状：canonical, display, nameZh, pinyinFull, pinyinAbbr,
# aliases, market, type, active, popularity）
_I_CANON, _I_NAME, _I_MARKET, _I_TYPE = 0, 2, 6, 7


def us_entry(symbol: str, name: str, is_etf: bool = False) -> list:
    return [symbol, symbol, name, "", "", [], "US", "etf" if is_etf else "stock", True, 100]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="只印出会改什么，一个字都不写（这个索引进版控，先看再写）")
    args = ap.parse_args()

    symbols = fetch_symbols()
    print(f"官方清单代码数: {len(symbols)}（其中 ETF {sum(1 for _, e in symbols.values() if e)}）")
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
        existing = {str(x[_I_CANON]).upper() for x in items if isinstance(x, list) and x}

        renamed = retyped = scrubbed = 0
        non_us_before = sum(1 for x in items
                            if isinstance(x, list) and len(x) > _I_MARKET and x[_I_MARKET] != "US")
        samples = []
        for row in items:
            if not (isinstance(row, list) and len(row) > _I_TYPE):
                continue
            if row[_I_MARKET] != "US":          # 台股/A股/港股增量一列都不碰
                continue
            official = symbols.get(str(row[_I_CANON]).upper())
            before = row[_I_NAME]
            if official:
                name, is_etf = official
                if name and name != before:
                    row[_I_NAME] = name
                    renamed += 1
                    if len(samples) < 5:
                        samples.append(f"{row[_I_CANON]}: {before!r} -> {name!r}")
                want = "etf" if is_etf else "stock"
                if row[_I_TYPE] != want:
                    row[_I_TYPE] = want
                    retyped += 1
            else:
                # 官方清单查无（多为 OTC）：**type 标成 unknown**，而不是留着预设的
                # `stock`。留 `stock` 会让下游把它当成权威的「不是 ETF」，於是官方
                # 清单外的真 ETF（Leverage Shares 那批、BLCN/KRMA/QRFT）拿不到 ETF
                # 式检索。标 unknown 才会退回名称启发式。名字只能清掉 Refinitiv 尾巴。
                if row[_I_TYPE] != "unknown":
                    row[_I_TYPE] = "unknown"
                    retyped += 1
                cleaned = clean_name(before)
                if cleaned and cleaned != before:
                    row[_I_NAME] = cleaned
                    scrubbed += 1

        added = [us_entry(s_, n, e) for s_, (n, e) in symbols.items() if s_ not in existing]
        merged = items + added
        non_us_after = sum(1 for x in merged
                           if isinstance(x, list) and len(x) > _I_MARKET and x[_I_MARKET] != "US")
        # 非美股列数必须逐字不变——这是「别把台股增量洗掉」的守门
        assert non_us_before == non_us_after, (non_us_before, non_us_after)

        print(f"  [{'dry' if args.dry_run else 'ok'}] {path.relative_to(REPO)}: "
              f"{len(items)} -> {len(merged)} (+{len(added)} 新增, "
              f"{renamed} 改名, {retyped} 改类型, {scrubbed} 清尾巴; 非美股 {non_us_after} 列不变)")
        for line in samples:
            print(f"        {line}")
        if args.dry_run:
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write("[\n")
            for i, item in enumerate(merged):
                json.dump(item, f, ensure_ascii=False, separators=(",", ":"))
                f.write(",\n" if i < len(merged) - 1 else "\n")
            f.write("]\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
