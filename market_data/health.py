"""Data-completeness / freshness checks for the market schema.

Catches the silent-partial-crawl failure mode (a day with abnormally few rows,
e.g. one market missing) and stale tables.

    python -m market_data.health
"""

import statistics

from sqlalchemy import text

from market_data.db import get_engine

_DATE_TABLES = ["price", "institutional", "margin", "monthly_revenue",
                "ex_dividend", "valuation", "market_index"]
_DATE_COL = {"monthly_revenue": "revenue_month"}


def thin_days(day_counts, window=5, ratio=0.9):
    """單日列數低於「前後 ``window`` 個交易日局部中位數 × ratio」的日子。

    列數 = 掛牌檔數,日間穩定,0.9 抓得住單邊市場缺漏(TPEx 缺 ~42%、TWSE 缺
    ~58%)與截斷寫入。不能用全域中位數:16 年上市家數成長會讓舊年代整段誤報、
    近期缺漏漏報(TPEx 整邊缺時仍有 58% 列數,舊版 0.5 門檻抓不到)。"""
    thin = []
    for i, (d, n) in enumerate(day_counts):
        lo = max(0, i - window)
        neigh = [c for j, (_, c) in enumerate(day_counts[lo:i + window + 1], lo)
                 if j != i]
        if len(neigh) >= 3 and n < ratio * statistics.median(neigh):
            thin.append((str(d)[:10], n))
    return thin


_THIN_TABLES = ["price", "institutional", "margin"]  # 每日全市場列數穩定的表

# 已逐日與來源核對一致的合法稀疏日(補班日交易,法人/信用活動天然只剩一半):
# 不是資料缺漏,白名單排除避免每次稽核重複告警。新 thin day 先跑修復流程
# (backfill --force / 對源核對),確認合法才加進來。
_VERIFIED_THIN = {
    "institutional": {
        "2012-12-22", "2013-02-23", "2013-09-14", "2014-12-27", "2016-06-04",
        "2016-09-10", "2017-02-18", "2017-09-30", "2018-03-31", "2019-01-07",
    },
}


def report(engine=None):
    engine = engine or get_engine()
    out = {"tables": {}, "thin_days": {}}
    with engine.connect() as c:
        for t in _DATE_TABLES:
            col = _DATE_COL.get(t, "date")
            row = c.execute(text(
                f"SELECT count(*), min({col}), max({col}) FROM market.{t}"
            )).fetchone()
            out["tables"][t] = {"rows": row[0], "start": str(row[1]),
                                "end": str(row[2])}
        for t in _THIN_TABLES:
            day_counts = c.execute(text(
                f"SELECT date, count(*) FROM market.{t} "
                f"GROUP BY date ORDER BY date")).fetchall()
            verified = _VERIFIED_THIN.get(t, set())
            out["thin_days"][t] = [(d, n) for d, n in thin_days(day_counts)
                                   if d not in verified]
    # 舊鍵別名,既有消費者/文件仍讀 thin_price_days
    out["thin_price_days"] = out["thin_days"]["price"]
    return out


if __name__ == "__main__":

    r = report()
    for t, info in r["tables"].items():
        print(f"{t:16} {info['rows']:>10,}  {info['start'][:10]}~{info['end'][:10]}")
    for t, days in r["thin_days"].items():
        print(f"thin {t} days: {len(days)} -> {days[:10]}")
