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


def main(argv=None):
    p = argparse.ArgumentParser(prog="market-crawl")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("daily", help="近幾日增量 + 每日快照")
    b = sub.add_parser("backfill", help="回補某來源日期區間")
    b.add_argument("source", choices=["price", "institutional", "margin"])
    b.add_argument("--start", required=True)
    b.add_argument("--end", required=True)
    sub.add_parser("snapshot", help="valuation + index + stock_info 快照")
    args = p.parse_args(argv)

    eng = get_engine()
    if args.command == "daily":
        crawl.daily_update(eng)
    elif args.command == "backfill":
        crawl.crawl_range(eng, args.source, _dates(args.start, args.end))
    elif args.command == "snapshot":
        with eng.begin() as conn:
            crawl.crawl_valuation(conn)
            crawl.crawl_index(conn)
            crawl.crawl_stock_info(conn)


if __name__ == "__main__":
    main()
