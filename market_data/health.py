"""Data-completeness / freshness checks for the market schema.

Catches the silent-partial-crawl failure mode (a day with abnormally few rows,
e.g. one market missing) and stale tables.

    python -m market_data.health
"""

import argparse
import datetime
import statistics

from sqlalchemy import text

from market_data.adjust import ADJUSTMENT_WINDOW_DAYS
from market_data.crawl import RECENT_SESSIONS
from market_data.db import get_engine
from market_data.financial_statement import afterIFRS

_DATE_TABLES = ["price", "institutional", "margin", "monthly_revenue",
                "ex_dividend", "valuation", "market_index",
                "financial_statement"]
_DATE_COL = {"monthly_revenue": "revenue_month"}
_REQUIRED_TABLES = (
    "price", "institutional", "margin", "monthly_revenue", "ex_dividend",
    "valuation", "market_index")


def missing_dates(reference, observed):
    """Return reference dates that have no rows in the observed source."""
    reference_keys = {str(value)[:10] for value in reference}
    observed_keys = {str(value)[:10] for value in observed}
    return sorted(reference_keys - observed_keys)


def missing_adjustments(expected, stored):
    """Return valid ex-dividend keys that have no adjustment event."""
    def keys(rows):
        return {(str(stock_id), str(day)[:10]) for stock_id, day in rows}

    return sorted(keys(expected) - keys(stored))


def stale_financial_quarters(stored_dates, today):
    """已過公告截止日、但一列都沒有的財報季,回 ``(year, season, deadline)``。

    財報季更**不在 `daily` 裡**(見 `market_data/AGENTS.md`),漏一季不會有任何
    東西喊——這裡是唯一會喊的地方。截止日對映直接用
    `financial_statement.afterIFRS`,不另抄一份日期表,避免兩份漂移。

    只檢查**涵蓋範圍之內**的季:早於庫內第一季的不報(那是「還沒回補」不是
    「停更」)、尚未到截止日的也不報。回傳的 ``season`` 是**會計期間**,Q4 的
    截止日在隔年 3/31——`financials --year 2019 --season 4` 寫進去的是
    `2020-03-31`,所以兩個都印出來,免得照著日期去猜參數猜錯年份。
    """
    stored = {str(value)[:10] for value in stored_dates}
    if not stored:
        return []
    first = min(stored)
    missing = []
    for year in range(int(first[:4]) - 1, today.year + 1):
        for season in (1, 2, 3, 4):
            deadline = str(afterIFRS(year, season).date())
            if deadline > str(today) or deadline < first:
                continue
            if deadline not in stored:
                missing.append((year, season, deadline))
    return missing


def recent_thin_days(thin_by_table, since):
    """只回傳 ``since`` 之後的 thin day。

    `thin_days` 掃全歷史，是稽核用的完整清單；但 strict gate 只能擋 `daily` 修得到的視窗。
    否則 2014 年的一個半日交易會讓 `make morning` 每天早上死在門口，而重跑 daily 永遠沒用。
    """
    if not since:
        return []
    cutoff = str(since)[:10]
    return sorted((table, day, rows)
                  for table, days in thin_by_table.items()
                  for day, rows in days if day >= cutoff)


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

        # 視窗與 `crawl.daily_update` 的自動修復視窗**同一個常數**：檢查得比修復得遠，
        # gate 就會擋在一個 daily 補不到的缺口上，而錯誤訊息叫你重跑的正是 daily。
        recent_price_dates = [row[0] for row in c.execute(text(
            "SELECT DISTINCT date FROM market.price ORDER BY date DESC LIMIT :n"
        ), {"n": RECENT_SESSIONS}).fetchall()]
        recent_index_dates = []
        source_dates = {}
        if recent_price_dates:
            recent_index_dates = [row[0] for row in c.execute(text(
                "SELECT DISTINCT date FROM market.market_index "
                "WHERE index_id = 'TAIEX' AND date >= :start"
            ), {"start": min(recent_price_dates)}).fetchall()]

            for table in ("institutional", "margin"):
                source_dates[table] = [row[0] for row in c.execute(text(
                    f"SELECT DISTINCT date FROM market.{table} WHERE date >= :start"
                ), {"start": min(recent_price_dates)}).fetchall()]
        else:
            source_dates = {"institutional": [], "margin": []}
        today = datetime.date.today()
        window = datetime.timedelta(days=ADJUSTMENT_WINDOW_DAYS)
        expected_adjustments = c.execute(text(
            "SELECT stock_id, date FROM market.ex_dividend "
            "WHERE close_before > 0 AND reference_price > 0 "
            "AND date BETWEEN :start AND :end"
        ), {"start": today - window, "end": today + window}).fetchall()
        stored_adjustments = c.execute(text(
            "SELECT stock_id, date FROM market.price_adjustment WHERE date >= :start"
        ), {"start": today - window}).fetchall()
        out["integrity"] = {
            # Price and TAIEX are independent official feeds; check both
            # directions so a stale calendar cannot certify another stale table.
            "missing_price_dates": missing_dates(
                recent_index_dates, recent_price_dates),
            "missing_index_dates": missing_dates(
                recent_price_dates, recent_index_dates),
            # 法人／融資是 T+1 資料；最新一個 price 交易日尚未發布屬正常延遲。
            "missing_institutional_dates": missing_dates(
                recent_price_dates[1:], source_dates["institutional"]),
            "missing_margin_dates": missing_dates(
                recent_price_dates[1:], source_dates["margin"]),
            "missing_price_adjustments": missing_adjustments(
                expected_adjustments, stored_adjustments),
            # 全歷史 thin day 留在 out["thin_days"] 供稽核；strict 只擋這一段。
            "thin_recent_days": recent_thin_days(
                out["thin_days"],
                min(recent_price_dates) if recent_price_dates else None),
            # 只報不擋:財報要手動跑 `financials`(整季 IFRS html 包 1-2 GB),
            # 擋住 `make morning` 只會讓人學會忽略 gate。
            "stale_financial_quarters": stale_financial_quarters(
                [row[0] for row in c.execute(text(
                    "SELECT DISTINCT date FROM market.financial_statement"
                )).fetchall()], today),
        }
    return out


def run(engine=None, strict=False):
    """Print the report and return a process exit code."""
    result = report(engine)
    for table, info in result["tables"].items():
        print(f"{table:16} {info['rows']:>10,}  {info['start'][:10]}~{info['end'][:10]}")
    for table, days in result["thin_days"].items():
        print(f"thin {table} days: {len(days)} -> {days[:10]}")
    integrity = result.get("integrity", {})
    missing_price = integrity.get("missing_price_dates", [])
    missing_index = integrity.get("missing_index_dates", [])
    missing_institutional = integrity.get("missing_institutional_dates", [])
    missing_margin = integrity.get("missing_margin_dates", [])
    missing_events = integrity.get("missing_price_adjustments", [])
    print(f"missing price dates: {len(missing_price)} -> {missing_price[:10]}")
    print(f"missing TAIEX dates: {len(missing_index)} -> {missing_index[:10]}")
    print("missing institutional dates: "
          f"{len(missing_institutional)} -> {missing_institutional[:10]}")
    print(f"missing margin dates: {len(missing_margin)} -> {missing_margin[:10]}")
    print(f"missing price adjustments: {len(missing_events)} -> {missing_events[:10]}")
    empty_required = [table for table in _REQUIRED_TABLES
                      if not result.get("tables", {}).get(table, {}).get("rows")]
    print(f"empty required tables: {len(empty_required)} -> {empty_required}")
    # strict 只擋 daily 修得到的近期視窗；全歷史 thin day 上面已印出來供稽核。
    thin_recent = integrity.get("thin_recent_days", [])
    print(f"thin days inside the daily window: {len(thin_recent)} -> {thin_recent[:10]}")
    stale_financials = integrity.get("stale_financial_quarters", [])
    print(f"stale financial quarters: {len(stale_financials)} -> "
          + ", ".join(f"{y}Q{s} (date {d})" for y, s, d in stale_financials[:10]))
    for year, season, _ in stale_financials[:10]:
        print("  repair: uv run --env-file .env python -m market_data.cli "
              f"financials --year {year} --season {season}")
    gaps = (missing_price, missing_index, missing_institutional,
            missing_margin, missing_events, thin_recent, empty_required)
    failed = any(gaps)
    if strict and failed:
        print("repair: uv run --env-file .env python -m market_data.cli daily")
        print("verify: uv run --env-file .env python -m market_data.cli "
              "health --strict")
        print("long gaps require an explicit market_data.cli backfill date range; "
              "the daily command intentionally refuses unbounded recovery")
    return int(strict and failed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="return non-zero for thin, empty, or recent integrity gaps")
    args = parser.parse_args(argv)
    return run(strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
