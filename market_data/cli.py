"""CLI for the unified market crawler (writes Postgres market schema).

    python -m market_data.cli daily                 # 近幾日增量 + 快照
    python -m market_data.cli backfill price --start 2010-01-01 --end 2026-07-01
    python -m market_data.cli snapshot              # valuation + index + stock_info
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
    b = sub.add_parser("backfill", help="回補某來源日期區間")
    b.add_argument("source", choices=["price", "institutional", "margin"])
    b.add_argument("--start", required=True)
    b.add_argument("--end", required=True)
    b.add_argument("--force", action="store_true",
                   help="忽略 resume 並整日換血(先刪該日再寫);修 partial/髒日用")
    sub.add_parser("snapshot", help="valuation + index + stock_info 快照")
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
    args = p.parse_args(argv)

    eng = get_engine()
    if args.command == "daily":
        crawl.daily_update(eng)
    elif args.command == "backfill":
        crawl.crawl_range(eng, args.source, _dates(args.start, args.end),
                          resume=not args.force, replace=args.force)
    elif args.command == "snapshot":
        with eng.begin() as conn:
            crawl.crawl_valuation(conn)
            crawl.crawl_index(conn)
            crawl.crawl_stock_info(conn)
    elif args.command == "financials":
        n = crawl.crawl_financials(eng, args.year, args.season,
                                   keep_files=args.keep_files)
        print(f"financial_statement rows upserted: {n:,}")
    elif args.command == "revenue":
        with eng.begin() as conn:
            n = crawl.crawl_monthly_revenue(conn, args.month)
        print(f"monthly_revenue rows upserted: {n:,}")
    elif args.command == "ex-dividend":
        with eng.begin() as conn:
            n = crawl.crawl_ex_dividend(conn,
                                        datetime.date.fromisoformat(args.start),
                                        datetime.date.fromisoformat(args.end))
        print(f"ex_dividend rows upserted: {n:,}")


if __name__ == "__main__":
    main()
