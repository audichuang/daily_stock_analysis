"""Data-completeness / freshness checks for the market schema.

Catches the silent-partial-crawl failure mode (a day with abnormally few rows,
e.g. one market missing) and stale tables.

    python -m market_data.health
"""

from sqlalchemy import text

from market_data.db import get_engine

_DATE_TABLES = ["price", "institutional", "margin", "monthly_revenue",
                "ex_dividend", "valuation", "market_index"]
_DATE_COL = {"monthly_revenue": "revenue_month"}


def report(engine=None):
    engine = engine or get_engine()
    out = {"tables": {}, "thin_price_days": []}
    with engine.connect() as c:
        for t in _DATE_TABLES:
            col = _DATE_COL.get(t, "date")
            row = c.execute(text(
                f"SELECT count(*), min({col}), max({col}) FROM market.{t}"
            )).fetchone()
            out["tables"][t] = {"rows": row[0], "start": str(row[1]),
                                "end": str(row[2])}
        # thin price days: < 50% of the median daily row count => likely a
        # partial crawl (one market missing) worth re-crawling.
        counts = [n for (n,) in c.execute(text(
            "SELECT count(*) FROM market.price GROUP BY date")).fetchall()]
        if counts:
            counts.sort()
            med = counts[len(counts) // 2]
            thin = c.execute(text(
                "SELECT date, count(*) n FROM market.price GROUP BY date "
                "HAVING count(*) < :t ORDER BY date"), {"t": med * 0.5}).fetchall()
            out["thin_price_days"] = [(str(d)[:10], n) for d, n in thin]
    return out


if __name__ == "__main__":

    r = report()
    for t, info in r["tables"].items():
        print(f"{t:16} {info['rows']:>10,}  {info['start'][:10]}~{info['end'][:10]}")
    print(f"thin price days: {len(r['thin_price_days'])} -> {r['thin_price_days'][:10]}")
