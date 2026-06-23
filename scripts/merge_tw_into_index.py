#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把台股种子 CSV 合并进现有 stocks.index.json，保留既有 A 股/港股/美股等条目。

为什么不直接全量重生（generate_index_from_csv.py）：全量重生需要 data/stock_list_a.csv
等 Tushare 导出文件；本仓库通常只保留已生成的索引，重生会丢失 3 万+ A 股条目。本脚本
只更新台股部分，幂等可重复。

复用 generate_index_from_csv 的 parse/build/compress 逻辑，保证格式与 pinyin 一致。
写入三处：public(build 来源)、static(服务用)、data/cache(远端缓存)。

用法：
    python3 scripts/fetch_tw_stock_list.py     # 先刷新种子 CSV（可选）
    python3 scripts/merge_tw_into_index.py      # 再合并进索引
"""
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from generate_index_from_csv import (  # noqa: E402
    parse_stock_row,
    build_stock_index,
    compress_index,
    require_pypinyin,
)

TW_CSV = REPO / "scripts" / "stock_index_seeds" / "stock_list_tw.csv"
TARGETS = [
    REPO / "apps" / "dsa-web" / "public" / "stocks.index.json",
    REPO / "static" / "stocks.index.json",
    REPO / "data" / "cache" / "stocks.index.json",
]


def build_tw_rows():
    stocks = []
    with open(TW_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            parsed = parse_stock_row(row, "TW")
            if parsed:
                stocks.append(parsed)
    rows = compress_index(build_stock_index(stocks))
    for r in rows:  # 自检：必须是 TW 市场且带 .TW/.TWO 后缀
        assert r[6] == "TW", f"market 非 TW: {r}"
        assert r[0].upper().endswith((".TW", ".TWO")), f"代码缺后缀: {r}"
    return rows


def is_tw(entry):
    return (
        isinstance(entry, list)
        and len(entry) > 6
        and (entry[6] == "TW" or str(entry[0]).upper().endswith((".TW", ".TWO")))
    )


def merge_into(path: Path, tw_rows):
    if not path.is_file():
        print(f"  [skip] 不存在: {path}")
        return
    items = json.load(open(path, encoding="utf-8"))
    before = len(items)
    kept = [x for x in items if not is_tw(x)]  # 去掉旧 TW 条目（幂等）
    seen = {str(x[0]).upper() for x in kept if isinstance(x, list) and x}
    added = [r for r in tw_rows if r[0].upper() not in seen]
    merged = kept + added
    with open(path, "w", encoding="utf-8") as f:
        f.write("[\n")
        for i, item in enumerate(merged):
            json.dump(item, f, ensure_ascii=False, separators=(",", ":"))
            f.write(",\n" if i < len(merged) - 1 else "\n")
        f.write("]\n")
    print(f"  [ok] {path.relative_to(REPO)}: {before} -> {len(merged)} (+{len(added)} TW)")


def main():
    if not require_pypinyin():
        return 1
    tw_rows = build_tw_rows()
    print(f"产生 {len(tw_rows)} 笔台股条目，样本: {tw_rows[0]}")
    for t in TARGETS:
        merge_into(t, tw_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
