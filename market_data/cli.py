"""CLI for the unified market crawler (writes Postgres market schema).

    python -m market_data.cli daily                 # 近幾日增量 + 快照
    python -m market_data.cli backfill price --start 2010-01-01 --end 2026-07-01
    python -m market_data.cli backfill institutional_tpex --start 2018-01-15 --end 2026-10-21 --delay 3
    python -m market_data.cli snapshot              # valuation + index + stock_info
    python -m market_data.cli backfill index --start 2010-01-01 --end 2026-10-26 --delay 3  # TAIEX 逐月回補
    python -m market_data.cli funds                 # 境內基金每日淨值
    python -m market_data.cli fund-history 18480065 # 單檔基金歷史淨值
    python -m market_data.cli holding               # 集保股權分散最新一週(全市場)
    python -m market_data.cli holding-history 3324 6191  # 個股近一年集保(每檔約 51 個請求)
    python -m market_data.cli taifex-oi             # 期交所法人台指期未平倉(近 14 曆日窗口,不看開關)
"""

import argparse
import datetime

from market_data import crawl
from market_data.db import get_engine


def _dates(start, end):
    s = datetime.date.fromisoformat(start)
    e = datetime.date.fromisoformat(end)
    return [s + datetime.timedelta(days=i) for i in range((e - s).days + 1)]


def _month(value):
    """YYYY-MM -> 該月 1 日;在 argparse 層擋格式錯誤(連 DB 之前)。"""
    try:
        y, m = value.split("-")
        return datetime.date(int(y), int(m), 1)
    except (ValueError, AttributeError):
        raise argparse.ArgumentTypeError(
            f"invalid month {value!r}, expected YYYY-MM (e.g. 2026-06)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="market-crawl")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("daily", help="近幾日增量 + 每日快照")
    h = sub.add_parser("health", help="資料完整性與近期缺口稽核")
    h.add_argument("--strict", action="store_true",
                   help="近期交易日或復權事件有缺口時回傳非零")
    b = sub.add_parser("backfill", help="回補某來源日期區間")
    b.add_argument("source", choices=[*crawl.DAILY, "index"],
                   help="*_tpex 為上櫃;institutional_tpex 自 2018-01-15 起才有資料")
    b.add_argument("--start", required=True)
    b.add_argument("--end", required=True)
    b.add_argument("--force", action="store_true",
                   help="忽略 resume 並整日換血；index 僅更新官方 OHLC，不刪其他欄位")
    b.add_argument("--delay", type=float, default=0.0,
                   help="每日（index 為每月）抓取間隔秒數。長區間回補務必給(建議 3)——TWSE 密集請求會封 IP,"
                        "且失敗是靜默的(該日直接跳過不報錯)")
    sub.add_parser("snapshot", help="valuation + index + stock_info 快照")
    sub.add_parser("funds", help="境內基金:公會每日淨值/基本資料 + 已追蹤基金近期補缺")
    sub.add_parser("holding", help="集保股權分散:開放資料最新一週(全市場)")
    hh = sub.add_parser("holding-history", help="集保股權分散:從 TDCC 個股查詢頁補近一年")
    hh.add_argument("stock_id", nargs="+", help="不帶後綴的代號,如 3324")
    hh.add_argument("--weeks", type=int, default=None, help="只補最近 N 週,預設查詢頁提供的全部(約 51 週)")
    hh.add_argument("--delay", type=float, default=1.0, help="每週請求間隔秒數")
    tx = sub.add_parser("taifex-oi", help="期交所三大法人臺股期貨未平倉:近 14 曆日窗口 upsert"
                        "(手動單跑,不看 TAIFEX_OI_PERSIST_ENABLED;不回補更早歷史)")
    tx.add_argument("--asof", type=datetime.date.fromisoformat, default=None,
                    help="迄日上限 YYYY-MM-DD,預設取已收盤的預期場次")
    fh = sub.add_parser("fund-history", help="從鉅亨補單檔基金的歷史淨值(不覆蓋公會官方值)")
    fh.add_argument("fund_id", nargs="+", help="公會基金統編,如 18480065")
    fh.add_argument("--start", default=None, help="起日 YYYY-MM-DD,預設全期")
    adj = sub.add_parser("adjust", help="重建 price_adjustment 前復權因子(除權息+減資+分割)")
    adj.add_argument("--start", default="2013-01-01",
                     help="推導起點。預設 2013：price 表 2010 上半年混有權證,見 adjust.py")
    adj.add_argument("--no-reductions", action="store_true",
                     help="跳過兩個需要網路的官方來源(TWTAUU 減資 + TPEx 上櫃除權息),"
                          "改為沿用 DB 既有的那些列;離線重算價格推導部分時用,不會清空官方值")
    f = sub.add_parser("financials", help="財報季更(下載 IFRS html → financial_statement)")
    f.add_argument("--year", type=int, required=True, help="會計年度,如 2026")
    f.add_argument("--season", type=int, required=True, choices=[1, 2, 3, 4])
    f.add_argument("--keep-files", action="store_true", help="保留下載的 html(預設用完即刪)")
    r = sub.add_parser("revenue", help="月營收(該月全股票一次)")
    r.add_argument("--month", required=True, type=_month,
                   help="營收月份 YYYY-MM(該月 10 日後才完整)")
    e = sub.add_parser("ex-dividend", help="除權息公告(日期區間)")
    e.add_argument("--start", required=True)
    e.add_argument("--end", required=True)
    rp = sub.add_parser("revenue-pit",
                        help="補下市公司的月營收(修存活偏誤;月營收彙總報表只列現存公司)")
    rp.add_argument("--start", required=True)
    rp.add_argument("--end", required=True)
    rp.add_argument("--delay", type=float, default=3.0, help="每次請求間隔秒數(MOPS 會擋)")
    rp.add_argument("--limit", type=int, default=None, help="只跑前 N 個缺口(試跑用)")
    rp.add_argument("--dry-run", action="store_true", help="只列出缺口數量,不發請求")
    rp.add_argument("--only-file", default=None,
                    help="CSV(stock_id,year,month) 指定要補的缺口。月營收只在價格條件成立"
                         "那幾天會被用到,全量補要數小時,精準補只要幾十個請求"
                         "(用 scripts/measure_signal_forward.py --emit-revenue-gaps 產生)")
    args = p.parse_args(argv)

    eng = get_engine()
    if args.command == "daily":
        crawl.daily_update(eng)
    elif args.command == "health":
        from market_data import health
        raise SystemExit(health.run(eng, strict=args.strict))
    elif args.command == "backfill":
        if args.source == "index":
            res = crawl.backfill_index(eng, datetime.date.fromisoformat(args.start),
                                       datetime.date.fromisoformat(args.end),
                                       resume=not args.force, delay=args.delay)
            print(f"market_index rows upserted: {res['written']:,}  months fetched: "
                  f"{res['months']}  skipped (complete): {res['skipped']}", flush=True)
            if res["failed"] or res["partial"] or res["short"]:
                print(f"  **抓不到的月份: {res['failed']}  只拿到單一來源: {res['partial']}  "
                      f"缺日的月份: {sorted(res['short'])}", flush=True)
                raise SystemExit(1)
        else:
            crawl.crawl_range(eng, args.source, _dates(args.start, args.end),
                              resume=not args.force, replace=args.force, delay=args.delay)
    elif args.command == "snapshot":
        crawl.crawl_snapshots(eng)      # 自己管交易:每步一個,印出即代表已 commit
    elif args.command == "holding":
        with eng.begin() as conn:
            n, latest = crawl.crawl_holding_dist(conn)
        print(f"holding_dist {n:,} rows, latest {latest}")
    elif args.command == "holding-history":
        n = crawl.backfill_holding_dist(eng, args.stock_id, weeks=args.weeks, delay=args.delay)
        print(f"holding_dist rows upserted: {n:,}")
    elif args.command == "taifex-oi":
        from market_data import taifex
        taifex.update(eng, asof=args.asof)
    elif args.command == "funds":
        from market_data import funds
        funds.daily_update(eng)
    elif args.command == "fund-history":
        from market_data import funds
        start = datetime.date.fromisoformat(args.start) if args.start else None
        for fid in args.fund_id:
            n = funds.backfill_history(eng, fid, start=start)
            print(f"fund_nav {fid} {n:,} new rows")
    elif args.command == "adjust":
        from market_data import adjust
        res = adjust.rebuild(eng, start=args.start, with_reductions=not args.no_reductions)
        print(f"price_adjustment rows upserted: {res.pop('written'):,}")
        print(f"  by source: {res.pop('by_kind', {})}")
        print(f"  {res}")
    elif args.command == "financials":
        n = crawl.crawl_financials(eng, args.year, args.season,
                                   keep_files=args.keep_files)
        print(f"financial_statement rows upserted: {n:,}")
    elif args.command == "revenue":
        with eng.begin() as conn:
            n = crawl.crawl_monthly_revenue(conn, args.month)
        print(f"monthly_revenue rows upserted: {n:,}")
    elif args.command == "revenue-pit":
        s = datetime.date.fromisoformat(args.start)
        e2 = datetime.date.fromisoformat(args.end)
        only = None
        if args.only_file:
            import csv as _csv
            with open(args.only_file, newline="") as f:
                only = [(r[0], int(r[1]), int(r[2])) for r in _csv.reader(f)
                        if r and not r[0].startswith("#")]
        if args.dry_run:
            with eng.begin() as conn:
                gaps = crawl.pit_revenue_gaps(conn, s, e2, only=only)
            stocks = sorted({g[0] for g in gaps})
            print(f"缺口 {len(gaps):,} 個 (公司 {len(stocks)} 檔)")
            print(f"預估耗時 {len(gaps) * (args.delay + 1.5) / 60:.0f} 分鐘"
                  f" (delay={args.delay}s)")
            print("公司:", " ".join(stocks))
        else:
            res = crawl.backfill_pit_revenue(eng, s, e2, delay=args.delay,
                                             limit=args.limit, only=only)
            print(f"\nmonthly_revenue rows upserted: {res['written']:,}"
                  f"  requests: {res['requested']:,}")
            print(f"  取得到的公司 ({len(res['stocks_ok'])}): {' '.join(res['stocks_ok'])}")
            term = res["stocks_terminal"]
            print(f"  硬邊界·不繼續公開發行/免申報 ({len(term)}): "
                  f"{' '.join(sorted(term))}")
            if res["retryable"]:
                print(f"  **可重試 {len(res['retryable'])} 個（HTTP/解析/月份不符,"
                      f"下次執行會再列出）**: {res['retryable'][:8]}")
            print(f"  原因分布: {dict(res['reasons'])}")
    elif args.command == "ex-dividend":
        with eng.begin() as conn:
            n = crawl.crawl_ex_dividend(conn,
                                        datetime.date.fromisoformat(args.start),
                                        datetime.date.fromisoformat(args.end))
        print(f"ex_dividend rows upserted: {n:,}")


if __name__ == "__main__":
    main()
