#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取台湾证交所/柜买中心官方上市櫃清单，生成完整台股种子 CSV。

来源（官方公开、Big5 编码 HTML）：
  - 上市 TWSE: https://isin.twse.com.tw/isin/C_public.jsp?strMode=2  -> .TW
  - 上柜 TPEx: https://isin.twse.com.tw/isin/C_public.jsp?strMode=4  -> .TWO

只保留普通股/特别股（CFICode 以 ES 开头）与 ETF（CE 开头），排除权证(RW)、
存托凭证、债券等 yfinance 不稳定支持的标的。

输出：scripts/stock_index_seeds/stock_list_tw.csv（ts_code,symbol,name,enname,aliases）

用法：
    python3 scripts/fetch_tw_stock_list.py
    python3 scripts/fetch_tw_stock_list.py --from-cache scratchpad/twse_listed.html scratchpad/twse_otc.html
"""
import argparse
import csv
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parent.parent
OUT_CSV = REPO / "scripts" / "stock_index_seeds" / "stock_list_tw.csv"

SOURCES = [
    ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", "TW"),   # 上市
    ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", "TWO"),  # 上柜
]

# 少数大型权值股补充英文/常用别名，方便英文与简体搜索；其余仅以中文名+代码检索。
ALIAS_OVERRIDE = {
    "2330": "台积电|TSMC", "2317": "鸿海|Foxconn|Hon Hai|富士康", "2454": "联发科|MediaTek",
    "2303": "联电|UMC", "2308": "台达电|Delta", "2382": "广达|Quanta", "2412": "中华电|Chunghwa Telecom",
    "2881": "富邦金|Fubon", "2882": "国泰金|Cathay", "2891": "中信金|CTBC", "2886": "兆丰金|Mega",
    "2884": "玉山金|E.SUN", "2885": "元大金|Yuanta", "1301": "台塑|Formosa Plastics", "1303": "南亚|Nan Ya",
    "2002": "中钢|China Steel", "2603": "长荣|Evergreen", "2609": "阳明|Yang Ming", "2615": "万海|Wan Hai",
    "3008": "大立光|Largan", "2379": "瑞昱|Realtek", "3034": "联咏|Novatek", "2357": "华硕|ASUS",
    "2395": "研华|Advantech", "1216": "统一|Uni-President", "2207": "和泰车|Hotai", "2912": "统一超|7-11",
    "3711": "日月光|ASE", "2327": "国巨|Yageo", "3045": "台湾大|Taiwan Mobile", "4938": "和硕|Pegatron",
    "0050": "台湾50|台50", "0056": "高股息", "00878": "永续高股息", "006208": "富邦台50",
    "6488": "环球晶|GlobalWafers", "8069": "元太|E Ink", "3105": "稳懋|Win Semi",
}


def fetch(url: str) -> str:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    resp.encoding = "big5"
    return resp.text


def parse_rows(html: str, suffix: str):
    """从一个 ISIN 页面 HTML 中解析出 (ts_code, name) 列表。"""
    rows = BeautifulSoup(html, "html.parser").find_all("tr")
    out = []
    for r in rows:
        cells = [c.get_text(strip=True) for c in r.find_all("td")]
        if len(cells) < 6:
            continue
        parts = cells[0].split("　")  # 全角空格分隔「代号　名称」
        if len(parts) != 2:
            continue
        code, name = parts[0].strip(), parts[1].strip()
        if not code.isdigit() or not (4 <= len(code) <= 6) or not name:
            continue
        cfi = cells[5].strip()
        if not (cfi.startswith("ES") or cfi.startswith("CE")):  # 普通/特别股 + ETF
            continue
        out.append((f"{code}.{suffix}", name))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-cache", nargs=2, metavar=("LISTED_HTML", "OTC_HTML"),
                    help="改用本地 HTML 文件，跳过网络抓取")
    args = ap.parse_args()

    entries = []
    seen = set()
    for i, (url, suffix) in enumerate(SOURCES):
        if args.from_cache:
            html = Path(args.from_cache[i]).read_text(encoding="big5", errors="ignore")
        else:
            print(f"抓取 {url} ...")
            html = fetch(url)
        rows = parse_rows(html, suffix)
        print(f"  {suffix}: {len(rows)} 笔")
        for ts_code, name in rows:
            if ts_code in seen:
                continue
            seen.add(ts_code)
            bare = ts_code.split(".")[0]
            entries.append((ts_code, ts_code, name, "", ALIAS_OVERRIDE.get(bare, "")))

    if len(entries) < 1500:
        print(f"[Error] 解析结果仅 {len(entries)} 笔，疑似来源异常，中止写入。", file=sys.stderr)
        return 1

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_code", "symbol", "name", "enname", "aliases"])
        w.writerows(entries)
    print(f"✓ 写入 {len(entries)} 笔 -> {OUT_CSV.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
