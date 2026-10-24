#!/usr/bin/env python
"""逐日逐列比對 `market` schema 與 TWSE／TPEx 官方原始回應（唯讀）。

每個交易日（取自 `market.price` 的日期）向官方抓一次全市場表，與 DB 逐列比對代碼集合與數值，
一天一個來源寫一行 JSON 到 ``OUT/result.jsonl``；官方原始回應快取在 ``OUT/raw/``。
**只做 SELECT，不寫 DB**；修正走 ``market_data.cli backfill <source> --force``（見 docs/tw-data-integrity.md）。

來源（``--sources``，逗號分隔）：
- TWSE：``t86``（上市法人，2012-05-02 起）、``margin``（上市融資，MI_MARGN）、``price``（上市日線
  開高低收／量／額／筆，MI_INDEX；``change`` 欄不比，舊資料語意見 market-data-pitfalls）
- TPEx：``tpex_insti``（上櫃法人，2018-01-15 起）、``tpex_margin``、``tpex_price``

TWSE 與 TPEx 各一條執行緒、每個請求間隔 >= 4 秒（TWSE 密集請求會封 IP）。由新到舊跑，中斷後重跑會
跳過 ``result.jsonl`` 已成功記錄的 (日期, 來源)。比對結果：``miss``＝官方有 DB 沒有、``extra``＝DB 有官方
沒有、``bad``＝兩邊都有但數值不同的列數；``err``＝官方回應日期不符或格式不認得（不是資料錯，要人工看）。

    uv run --env-file .env python scripts/audit_market_vs_official.py \\
        --start 2026-01-01 --end 2026-10-23 --out data/audit/2026 --sources t86,margin,price,tpex_insti,tpex_margin,tpex_price
    uv run --env-file .env python scripts/audit_market_vs_official.py --out data/audit/2026 --summary --sources t86
（``--summary`` 只看 ``--sources`` 列出的來源，預設全部；同一天重跑過以最後一筆為準）
"""

import argparse
import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_data.db import get_engine  # noqa: E402

TWSE_SOURCES = ("t86", "margin", "price")
TPEX_SOURCES = ("tpex_insti", "tpex_margin", "tpex_price")
REQUEST_GAP_SECONDS = 4
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
T86_FIELDS = (
    ("外陸資買賣超股數(不含外資自營商)", "外資買賣超股數"),  # foreign_net：舊年份只有「外資買賣超股數」
    ("投信買賣超股數",),
    ("自營商買賣超股數",),
    ("三大法人買賣超股數",),
)
PRICE_FIELDS = ("開盤價", "最高價", "最低價", "收盤價", "成交股數", "成交金額", "成交筆數")


def num(value):
    s = re.sub(r"<[^>]*>", "", str(value)).replace(",", "").strip()
    if s in ("", "--", "---", "----", "-", "N/A"):
        return None
    try:
        return Decimal(s)
    except ArithmeticError:
        return None


class Audit:
    def __init__(self, engine, out: Path, sources: set):
        self.engine = engine
        self.out = out
        self.sources = sources
        self.raw = out / "raw"
        self.raw.mkdir(parents=True, exist_ok=True)
        self.result = out / "result.jsonl"
        self.lock = threading.Lock()
        self.done = set()
        if self.result.exists():
            for line in self.result.read_text().splitlines():
                r = json.loads(line)
                if r.get("err") is None:
                    self.done.add((r["date"], r["source"]))

    def db(self, sql, **params):
        with self.engine.connect() as c:
            rows = c.execute(text(sql), params).fetchall()
        return {str(r[0]): [None if v is None else Decimal(str(v)) for v in r[1:]] for r in rows}

    def get(self, url, name):
        path = self.raw / name
        if path.exists() and path.stat().st_size > 50:
            return json.loads(path.read_text())
        for _ in range(3):
            try:
                body = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
                data = json.loads(body)
                path.write_text(json.dumps(data, ensure_ascii=False))
                time.sleep(REQUEST_GAP_SECONDS)
                return data
            except (OSError, ValueError) as exc:
                print(f"retry {url}: {exc}", flush=True)
                time.sleep(30)
        return None

    def record(self, d, source, off=None, db=None, err=None):
        r = {"date": d, "source": source, "err": err}
        if err is None:
            bad = {k: [i for i, (a, b) in enumerate(zip(off[k], db[k])) if a != b] for k in set(off) & set(db)}
            bad = {k: v for k, v in bad.items() if v}
            miss, extra = sorted(set(off) - set(db)), sorted(set(db) - set(off))
            r.update(off=len(off), db=len(db), miss=len(miss), extra=len(extra), bad=len(bad),
                     ex=list(bad.items())[:3] + miss[:3] + extra[:3])
        with self.lock:
            with self.result.open("a") as f:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        if err or r.get("miss") or r.get("extra") or r.get("bad"):
            print(json.dumps(r, ensure_ascii=False, default=str)[:300], flush=True)

    def want(self, d, source):
        return source in self.sources and (d, source) not in self.done

    def twse(self, dates):
        for d in dates:
            ymd = d.replace("-", "")
            if self.want(d, "t86") and d >= "2012-05-02":
                j = self.get(f"https://www.twse.com.tw/rwd/zh/fund/T86?date={ymd}&selectType=ALLBUT0999&response=json",
                             f"t86_{ymd}.json")
                fields = (j or {}).get("fields") or []
                ix = [next((fields.index(n) for n in names if n in fields), None) for names in T86_FIELDS]
                if not j or j.get("stat") != "OK" or j.get("date") != ymd:
                    self.record(d, "t86", err=f"{(j or {}).get('stat')} {(j or {}).get('date')}")
                elif None in ix:
                    self.record(d, "t86", err=f"fields {fields}")
                else:
                    off = {r[0].strip().lstrip("=").strip('"').strip(): [num(r[i]) for i in ix] for r in j["data"]}
                    self.record(d, "t86", off, self.db(
                        "select stock_id, foreign_net, trust_net, dealer_net, total_net from market.institutional "
                        "where date = :d and market is null", d=d))
            if self.want(d, "margin"):
                j = self.get(f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ymd}&selectType=ALL&response=json",
                             f"mar_{ymd}.json")
                tbl = [t for t in (j or {}).get("tables", []) if t.get("fields") and t["fields"][0] == "代號"]
                f = tbl[0]["fields"] if tbl else []
                if not j or j.get("date") != ymd or not tbl:
                    self.record(d, "margin", err=f"{(j or {}).get('stat')} {(j or {}).get('date')} tables={len(tbl)}")
                elif f[2] != "買進" or f[6] != "今日餘額" or f[12] != "今日餘額":
                    self.record(d, "margin", err=f"header {f}")
                else:
                    off = {r[0].strip(): [num(r[i]) for i in (2, 3, 6, 8, 9, 12)] for r in tbl[0]["data"]}
                    self.record(d, "margin", off, self.db(
                        "select stock_id, margin_buy, margin_sell, margin_balance, short_buy, short_sell, short_balance "
                        "from market.margin where date = :d and market is null", d=d))
            if self.want(d, "price"):
                j = self.get(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=ALLBUT0999&response=json",
                             f"mi_{ymd}.json")
                tbls = [t for t in (j or {}).get("tables", []) if "證券代號" in (t.get("fields") or [])]
                if not j or j.get("stat") != "OK" or j.get("date") != ymd or not tbls:
                    self.record(d, "price", err=f"{(j or {}).get('stat')}")
                    continue
                f = tbls[0]["fields"]
                off = {}
                for r in tbls[0]["data"]:
                    row = dict(zip(f, r))
                    if num(row["收盤價"]) is not None:  # 無成交（收盤 --）不入庫，是設計
                        off[row["證券代號"].strip()] = [num(row[c]) for c in PRICE_FIELDS]
                db = self.db("select stock_id, open, high, low, close, volume, turnover, transactions "
                             "from market.price where date = :d", d=d)
                self.record(d, "price", off, {k: v for k, v in db.items() if k in off})

    def tpex(self, dates):
        for d in dates:
            ds, ymd = d.replace("-", "/"), d.replace("-", "")
            if self.want(d, "tpex_insti") and d >= "2018-01-15":
                j = self.get("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?" + urllib.parse.urlencode(
                    {"type": "Daily", "sect": "EW", "date": ds, "response": "json"}), f"tpi_{ymd}.json")
                if not j or j.get("date") != ymd:
                    self.record(d, "tpex_insti", err=f"{(j or {}).get('stat')} {(j or {}).get('date')}")
                else:
                    off = {r[0].strip(): [num(r[i]) for i in (4, 13, 22, 23)]
                           for tb in j.get("tables", []) for r in tb.get("data", [])}
                    self.record(d, "tpex_insti", off, self.db(
                        "select stock_id, foreign_net, trust_net, dealer_net, total_net from market.institutional "
                        "where date = :d and market = 'tpex'", d=d))
            if self.want(d, "tpex_margin"):
                j = self.get("https://www.tpex.org.tw/www/zh-tw/margin/balance?" + urllib.parse.urlencode(
                    {"date": ds, "response": "json"}), f"tpm_{ymd}.json")
                tb = ((j or {}).get("tables") or [{}])[0]
                f = tb.get("fields") or []
                if not j or j.get("date") != ymd:
                    self.record(d, "tpex_margin", err=f"{(j or {}).get('stat')} {(j or {}).get('date')}")
                elif len(f) < 15 or f[3] != "資買" or f[6] != "資餘額" or f[11] != "券賣" or f[14] != "券餘額":
                    self.record(d, "tpex_margin", err=f"header {f}")
                else:
                    off = {str(r[0]).strip(): [num(r[i]) for i in (3, 4, 6, 12, 11, 14)] for r in tb.get("data") or []}
                    self.record(d, "tpex_margin", off, self.db(
                        "select stock_id, margin_buy, margin_sell, margin_balance, short_buy, short_sell, short_balance "
                        "from market.margin where date = :d and market = 'tpex'", d=d))
            if self.want(d, "tpex_price"):
                j = self.get(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date={ds}&type=EW&response=json",
                             f"tpp_{ymd}.json")
                if not j or j.get("date") != ymd:
                    self.record(d, "tpex_price", err=f"{(j or {}).get('stat')}")
                    continue
                # 代號、名稱、收盤、漲跌、開盤、最高、最低、成交股數、成交金額、成交筆數
                off = {r[0].strip(): [num(r[i]) for i in (4, 5, 6, 2, 7, 8, 9)]
                       for tb in j.get("tables", []) for r in tb.get("data", []) if num(r[2]) is not None}
                db = self.db("select stock_id, open, high, low, close, volume, turnover, transactions "
                             "from market.price where date = :d", d=d)
                self.record(d, "tpex_price", off, {k: v for k, v in db.items() if k in off})


def summarize(out: Path, sources=None) -> int:
    """Per source: days, differing days, unreadable days. Exit 1 if any (only ``sources`` when given)."""
    latest = {}
    for line in (out / "result.jsonl").read_text().splitlines():
        r = json.loads(line)
        if sources is None or r["source"] in sources:
            latest[(r["date"], r["source"])] = r  # 重跑後以最後一筆為準
    by_source = {}
    for (d, source), r in sorted(latest.items()):
        s = by_source.setdefault(source, {"days": 0, "err": [], "diff": []})
        s["days"] += 1
        if r.get("err"):
            s["err"].append(d)
        elif r.get("miss") or r.get("extra") or r.get("bad"):
            s["diff"].append(d)
    for source, s in by_source.items():
        print(f"{source}: {s['days']} days, differing {len(s['diff'])}, unreadable {len(s['err'])}")
        for label in ("diff", "err"):
            if s[label]:
                print(f"  {label}: {' '.join(s[label])}")
    return 1 if any(s["diff"] or s["err"] for s in by_source.values()) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="結果與官方原始回應快取的目錄（建議放 data/ 底下，gitignore）")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--sources", default=",".join(TWSE_SOURCES + TPEX_SOURCES))
    ap.add_argument("--summary", action="store_true", help="只彙總既有 result.jsonl，不連網")
    args = ap.parse_args()
    out = Path(args.out)
    sources = set(args.sources.split(","))
    if args.summary:
        return summarize(out, sources)
    if not (args.start and args.end):
        ap.error("--start 與 --end 必填（除非 --summary）")
    unknown = sources - set(TWSE_SOURCES + TPEX_SOURCES)
    if unknown:
        ap.error(f"未知來源：{sorted(unknown)}")
    engine = get_engine()
    with engine.connect() as c:
        dates = [str(r[0]) for r in c.execute(text(
            "select distinct date from market.price where date between :s and :e order by 1 desc"),
            {"s": args.start, "e": args.end})]
    audit = Audit(engine, out, sources)
    threads = []
    if sources & set(TWSE_SOURCES):
        threads.append(threading.Thread(target=audit.twse, args=(dates,)))
    if sources & set(TPEX_SOURCES):
        threads.append(threading.Thread(target=audit.tpex, args=(dates,)))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"checked {len(dates)} trading days", flush=True)
    return summarize(out, sources)


if __name__ == "__main__":
    sys.exit(main())
