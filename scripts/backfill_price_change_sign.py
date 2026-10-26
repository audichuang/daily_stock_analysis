#!/usr/bin/env python
"""回補 `market.price.change` 的正負號（僅上市，2013 起）。

## 為什麼需要

TWSE `MI_INDEX` 的 `漲跌價差` 只有絕對值，方向在獨立的 `漲跌(+/-)` 欄；
`market_data/crawler.py::crawl_price` 曾把那欄 coerce 成 NaN 後整欄丟掉，
所以入庫的上市列**全部只有絕對值**。爬取端已於 2026-08-23 修好，本腳本補歷史。

## 為什麼不是 `close - lag(close)`

官方的 `漲跌價差` 比的是**當日參考價**，不是前一日收盤——除權息當天兩者不同。
用 `close - lag(close)` 重算會把除權息日的方向改成錯的（除息通常是「參考價持平、
收盤上漲」但 raw close 下跌）。所以本腳本：

- **只改符號，不動絕對值**（絕對值是官方公告值）
- 方向取 `sign(close - prev_close * factor)`，其中 `factor` 是 `price_adjustment`
  在**當日**的事件因子（無事件則 1.0）。`prev_close * factor` 就是官方參考價，
  這是等效於官方判定的最小改動。

## 已知範圍限制

`DEFAULT_START_YEAR = 2013`，與 `market_data/adjust.py` 的起算年一致（2013 之前的 `price`
混有權證，且 `price_adjustment` 也沒有那段的因子）。實測 pre-2013 有 **283,482 列**符號仍錯，
刻意不補：那段沒有復權因子，硬補會讓除權息日拿到「已知是錯的」方向——把「一律錯」換成
「大部分對、除權息日錯」。要補就得先把 `price_adjustment` 往前重建。

## 為什麼可以放心跑

`market_repo.to_daily_frame` 已改成不再讀這一欄；唯一的讀取端是 `market_data.adjust.infer_rows`
拿 `close - change` 當推導參考價，而它只信 `SIGNED_SINCE` 之後的正負號、之前的列只用絕對值
（方向由漲跌停帶證明）——本腳本只改之前的列的號，所以不影響任何計算，純屬資料衛生
（給直接寫 SQL 的人用）。可重複執行：只改「符號與判定不符」的列。

    uv run --env-file .env python scripts/backfill_price_change_sign.py            # dry-run
    uv run --env-file .env python scripts/backfill_price_change_sign.py --apply
"""

import argparse
import datetime
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_data.adjust import CHANGE_SIGNED_SINCE  # noqa: E402
from market_data.db import get_engine  # noqa: E402

# 2013 之前的 price 混有權證（5 位代號，2010 上半年每日 2,200+ 檔），
# 與 market_data/adjust.py 的起算年一致。
DEFAULT_START_YEAR = 2013

# 判定為「應為負」的門檻。台股最小跳動 0.01 元，用 1e-6 只吸收 float 誤差。
EPS = 1e-6

# 只挑「絕對值 > 0 且目前為正、但參考價比較說是跌」的列。平盤（change = 0）沒有符號
# 問題；已經是負的列表示來源本來就帶號（上櫃 TPEx JSON），不要動。
# lag() 需要前一個交易日，所以讀取視窗要往前多含 LOOKBACK_DAYS；**更新仍只限目標區間**。
# 少了這段回看，每檔每年的第一個交易日永遠拿不到 prev_close，會被靜默跳過。
LOOKBACK_DAYS = 30

# 爬取端 2026-08-23 起上市列就帶正確正負號；之後的列一律不碰。上櫃列（TPEx JSON 本來就帶號）
# 在 price 表分不出市場（market 全是 NULL），若參考價不是「前收×當日因子」（前一日無成交、
# 除權息日沒成交）會被誤翻成負號——2026-10-24 全量比對抓到過。這道截止日至少讓重跑不再污染新列。
# 唯一來源在 `market_data.adjust`：`infer_rows` 也只信這天之後的 change。
SIGNED_SINCE = CHANGE_SIGNED_SINCE

_BASE_CTE = """
with base as (
    select p.stock_id, p.date, p.close, p.change,
           lag(p.close) over (partition by p.stock_id order by p.date) as prev_close,
           coalesce(pa.factor, 1.0) as factor
    from market.price p
    left join market.price_adjustment pa
           on pa.stock_id = p.stock_id and pa.date = p.date
    where p.date >= :lookback_start
      and p.date < :end
)
"""

_PREDICATE = """
    where date >= :start
      and date < :signed_since
      and prev_close is not null
      and change is not null
      and change > :eps
      and close < prev_close * factor - :eps
"""

_SELECT = _BASE_CTE + "select stock_id, date from base" + _PREDICATE

_UPDATE = (
    "update market.price p set change = -abs(p.change) "
    "where (p.stock_id, p.date) in (select stock_id, date from ("
    + _BASE_CTE + "select stock_id, date from base" + _PREDICATE
    + ") t)"
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="真的寫入；預設只統計（dry-run）")
    ap.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    ap.add_argument("--end-year", type=int, default=None,
                    help="含（預設為 price 表最後一年）")
    args = ap.parse_args()

    eng = get_engine()
    with eng.connect() as c:
        last = c.execute(text("select max(date) from market.price")).scalar()
    if last is None:
        print("market.price 是空的，沒有東西可回補")
        return 1
    end_year = args.end_year or last.year

    total = 0
    for year in range(args.start_year, end_year + 1):
        start = datetime.date(year, 1, 1)
        params = {
            "start": start,
            "lookback_start": start - datetime.timedelta(days=LOOKBACK_DAYS),
            "end": datetime.date(year + 1, 1, 1),
            "eps": EPS,
            "signed_since": SIGNED_SINCE,
        }
        if args.apply:
            # 逐年一個 transaction：中斷只會少補幾年，不會留下半套符號。
            with eng.begin() as c:
                n = c.execute(text(_UPDATE), params).rowcount
        else:
            with eng.connect() as c:
                n = len(c.execute(text(_SELECT), params).fetchall())
        total += n
        print(f"{year}: {n:>7,} 列{'已修正' if args.apply else '需修正'}")

    verb = "已修正" if args.apply else "需修正（dry-run，未寫入）"
    print(f"\n合計 {total:,} 列{verb}")
    if not args.apply and total:
        print("加 --apply 才會實際寫入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
