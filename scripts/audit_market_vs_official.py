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
沒有、``bad``＝兩邊都有但數值不同的列數；``err``＝官方回應日期不符或格式不認得（不是資料錯，要人工看；
TPEx 另比對資料表自帶的民國日期，凍結的舊表也記 err），``crash <例外>``＝解析或查 DB 時出例外。跑完的彙總
另列 ``missing``＝該比卻沒有任何紀錄的日子；有 diff／err／missing 任一項，結束碼都是 1。
預期的 (日期, 來源) 存在 ``OUT/expected.json``（同目錄重跑時累積），``--summary`` 離線彙總也據此檢查缺漏。

    uv run --env-file .env python scripts/audit_market_vs_official.py \\
        --start 2026-01-01 --end 2026-10-23 --out data/audit/2026 --sources t86,margin,price,tpex_insti,tpex_margin,tpex_price
    uv run --env-file .env python scripts/audit_market_vs_official.py --out data/audit/2026 --summary --sources t86
（``--summary`` 只看 ``--sources`` 列出的來源，預設全部；同一天重跑過以最後一筆為準）
"""

import argparse
import datetime
import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_data.db import get_engine  # noqa: E402
from market_data.sources import _tpex_table  # noqa: E402

TWSE_SOURCES = ("t86", "margin", "price")
TPEX_SOURCES = ("tpex_insti", "tpex_margin", "tpex_price")
# 官方開始提供的日子；更早的日子不抓、也不算缺
SOURCE_SINCE = {"t86": "2012-05-02", "tpex_insti": "2018-01-15"}
FILE_PREFIX = {"tpex_insti": "tpi", "tpex_margin": "tpm", "tpex_price": "tpp"}
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


def latest_results(out):
    """重跑與彙總共用：同 (日期, 來源) 以最後一筆為準，較早的成功不能蓋過後來的錯誤。"""
    path = out / "result.jsonl"
    latest = {}
    if path.exists():
        for line in path.read_text().splitlines():
            r = json.loads(line)
            latest[(r["date"], r["source"])] = r
    return latest


def expected_pairs(dates, sources):
    """應該要有紀錄的 (日期, 來源)：``sources`` × ``dates``，扣掉來源開始提供之前的日子。"""
    return {(d, s) for d in dates for s in sources if d >= SOURCE_SINCE.get(s, "")}


def load_expected(out):
    path = out / "expected.json"
    return {tuple(pair) for pair in json.loads(path.read_text())} if path.exists() else None


class Audit:
    def __init__(self, engine, out: Path, sources: set):
        self.engine = engine
        self.out = out
        self.sources = sources
        self.raw = out / "raw"
        self.raw.mkdir(parents=True, exist_ok=True)
        self.result = out / "result.jsonl"
        self.lock = threading.Lock()
        self.done = {pair for pair, r in latest_results(out).items() if r.get("err") is None}

    def audit(self, dates) -> int:
        """先把預期範圍寫進 ``expected.json``，再兩個市場平行跑；任一 worker 例外回 1。

        單格例外已在 ``run`` 記成 err；這裡接的是 ``run`` 之外（例如寫 ``result.jsonl``）的失敗——
        ``Thread.join`` 不會把例外往外拋，所以改用 future 取回。"""
        expected = (load_expected(self.out) or set()) | expected_pairs(dates, self.sources)
        (self.out / "expected.json").write_text(json.dumps(sorted(expected)))
        failed = False
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {}
            if self.sources & set(TWSE_SOURCES):
                futures[pool.submit(self.twse, dates)] = "TWSE"
            if self.sources & set(TPEX_SOURCES):
                futures[pool.submit(self.tpex, dates)] = "TPEx"
            for future, market in futures.items():
                try:
                    future.result()
                except Exception as exc:
                    failed = True
                    print(f"{market} worker failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return int(failed)

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
        return (source in self.sources and d >= SOURCE_SINCE.get(source, "")
                and (d, source) not in self.done)

    def run(self, dates, sources):
        """逐日跑 ``sources``；單一 (日期, 來源) 出例外記成 err 繼續下一個。

        執行緒裡沒接住的例外 ``join`` 不會往外拋，整條執行緒默默死掉、剩下的日子都沒比；
        所以每一格都要接住，記成 err 讓彙總結束碼為 1。"""
        for d in dates:
            for source in sources:
                if not self.want(d, source):
                    continue
                try:
                    getattr(self, f"_{source}")(d)
                except Exception as exc:  # 欄位改版、短列、DB 錯都要記下來，不能殺掉執行緒
                    self.record(d, source, err=f"crash {type(exc).__name__}: {exc}")

    def twse(self, dates):
        self.run(dates, TWSE_SOURCES)

    def tpex(self, dates):
        self.run(dates, TPEX_SOURCES)

    def _t86(self, d):
        ymd = d.replace("-", "")
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

    def _margin(self, d):
        ymd = d.replace("-", "")
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

    def _price(self, d):
        ymd = d.replace("-", "")
        j = self.get(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=ALLBUT0999&response=json",
                     f"mi_{ymd}.json")
        tbls = [t for t in (j or {}).get("tables", []) if "證券代號" in (t.get("fields") or [])]
        if not j or j.get("stat") != "OK" or j.get("date") != ymd or not tbls:
            self.record(d, "price", err=f"{(j or {}).get('stat')}")
            return
        f = tbls[0]["fields"]
        off = {}
        for r in tbls[0]["data"]:
            row = dict(zip(f, r))
            if num(row["收盤價"]) is not None:  # 無成交（收盤 --）不入庫，是設計
                off[row["證券代號"].strip()] = [num(row[c]) for c in PRICE_FIELDS]
        db = self.db("select stock_id, open, high, low, close, volume, turnover, transactions "
                     "from market.price where date = :d", d=d)
        self.record(d, "price", off, {k: v for k, v in db.items() if k in off})

    def _tpex_get(self, d, source, url, what):
        """抓 TPEx 表並核對自帶日期；回資料表或 None（已記 err）。

        與正式爬蟲共用 ``_tpex_table``：外層 ``date`` 之外還比對資料表自己的民國日期——TPEx 凍結時
        外層照填請求日、表卻是舊表，只看外層會把凍結資料（DB 若也是同一份舊表）判成乾淨。"""
        j = self.get(url, f"{FILE_PREFIX[source]}_{d.replace('-', '')}.json")
        j = j if isinstance(j, dict) else {}
        tb = _tpex_table(j, datetime.date.fromisoformat(d), what)
        if tb is None:
            table_day = ((j.get("tables") or [{}])[0] or {}).get("date")
            self.record(d, source, err=f"{j.get('stat')} {j.get('date')} table={table_day}")
        return tb

    def _tpex_insti(self, d):
        tb = self._tpex_get(d, "tpex_insti", "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?" + urllib.parse.urlencode(
            {"type": "Daily", "sect": "EW", "date": d.replace("-", "/"), "response": "json"}), "三大法人")
        if tb is None:
            return
        off = {str(r[0]).strip(): [num(r[i]) for i in (4, 13, 22, 23)] for r in tb.get("data") or []}
        self.record(d, "tpex_insti", off, self.db(
            "select stock_id, foreign_net, trust_net, dealer_net, total_net from market.institutional "
            "where date = :d and market = 'tpex'", d=d))

    def _tpex_margin(self, d):
        tb = self._tpex_get(d, "tpex_margin", "https://www.tpex.org.tw/www/zh-tw/margin/balance?" + urllib.parse.urlencode(
            {"date": d.replace("-", "/"), "response": "json"}), "融資融券")
        if tb is None:
            return
        f = tb.get("fields") or []
        if len(f) < 15 or f[3] != "資買" or f[6] != "資餘額" or f[11] != "券賣" or f[14] != "券餘額":
            self.record(d, "tpex_margin", err=f"header {f}")
            return
        off = {str(r[0]).strip(): [num(r[i]) for i in (3, 4, 6, 12, 11, 14)] for r in tb.get("data") or []}
        self.record(d, "tpex_margin", off, self.db(
            "select stock_id, margin_buy, margin_sell, margin_balance, short_buy, short_sell, short_balance "
            "from market.margin where date = :d and market = 'tpex'", d=d))

    def _tpex_price(self, d):
        tb = self._tpex_get(d, "tpex_price", "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?"
                            f"date={d.replace('-', '/')}&type=EW&response=json", "上櫃股價")
        if tb is None:
            return
        # 代號、名稱、收盤、漲跌、開盤、最高、最低、成交股數、成交金額、成交筆數
        off = {str(r[0]).strip(): [num(r[i]) for i in (4, 5, 6, 2, 7, 8, 9)]
               for r in tb.get("data") or [] if num(r[2]) is not None}
        db = self.db("select stock_id, open, high, low, close, volume, turnover, transactions "
                     "from market.price where date = :d", d=d)
        self.record(d, "tpex_price", off, {k: v for k, v in db.items() if k in off})


def summarize(out: Path, sources=None) -> int:
    """逐來源回報已記錄、差異、無法讀取與缺漏日數；任一異常以結束碼 1 回報（``sources`` 給定時只看這些來源）。

    缺漏比對 ``expected.json``：該比卻沒有任何紀錄的日子（worker 中斷、行程被砍）一樣算不乾淨。
    舊目錄沒有 ``expected.json`` 時只彙總已記錄的結果，並印出 ``coverage unverified``。"""
    latest = latest_results(out)
    expected = load_expected(out)
    if expected is None:
        print("coverage unverified: expected.json missing; summarizing recorded results only")
    by_source = {}
    for d, source in sorted(set(latest) | (expected or set())):
        if sources is not None and source not in sources:
            continue
        s = by_source.setdefault(source, {"days": 0, "err": [], "diff": [], "missing": []})
        r = latest.get((d, source))
        if r is None:
            s["missing"].append(d)
            continue
        s["days"] += 1
        if r.get("err"):
            s["err"].append(d)
        elif r.get("miss") or r.get("extra") or r.get("bad"):
            s["diff"].append(d)
    for source, s in sorted(by_source.items()):
        print(f"{source}: {s['days']} days, differing {len(s['diff'])}, "
              f"unreadable {len(s['err'])}, missing {len(s['missing'])}")
        for label in ("diff", "err", "missing"):
            if s[label]:
                print(f"  {label}: {' '.join(s[label])}")
    if not by_source:
        print("coverage incomplete: no audit results for requested sources")
        return 1
    return int(any(s["diff"] or s["err"] or s["missing"] for s in by_source.values()))


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
    status = Audit(engine, out, sources).audit(dates)
    print(f"requested {len(dates)} trading days", flush=True)
    return max(status, summarize(out, sources))


if __name__ == "__main__":
    sys.exit(main())
