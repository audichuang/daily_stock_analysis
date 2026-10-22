"""Upsert helper for writing crawled data into market.* (Postgres).

Daily increments are small (~a few thousand rows); one INSERT ... ON CONFLICT
DO UPDATE per batch keeps the tables idempotent on re-crawl.
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert


def dedupe(records, index_elements):
    """按 PK 去重取最後一筆(來源偶有重複列)。"""
    return list({tuple(r[k] for k in index_elements): r for r in records}.values())


def upsert(conn, table, records, index_elements, coalesce=(), market_guard=False):
    """INSERT ``records`` (list of dicts) into ``table``, updating rows that
    collide on ``index_elements`` (the primary key). Returns rows written
    (submitted minus rows skipped by the cross-market guard below).

    ``coalesce`` 欄位在衝突更新時保留舊值優先於 NULL(新值非 NULL 才覆蓋)——
    給「備援來源缺欄」用,避免重爬把既有完整資料抹成 NULL。

    ``market_guard``：上市／上櫃共表（``crawl.MARKET_SPLIT_TABLES``）寫入時開啟，衝突列的
    ``market`` 不同就不覆蓋、印 ``**WARN``。``stock_info`` 這類 market 本來就會隨轉市場改變的表不要開。"""
    if not records:
        return 0
    # 同批同鍵會讓 ON CONFLICT DO UPDATE 直接報 cardinality violation
    records = dedupe(records, index_elements)
    stmt = insert(table).values(records)
    update = {
        c.name: (func.coalesce(stmt.excluded[c.name], table.c[c.name])
                 if c.name in coalesce else stmt.excluded[c.name])
        for c in table.columns
        if c.name not in index_elements
    }
    guard = market_guard and bool(update)
    if update:
        # 上市與上櫃共表但 PK 不含 market：撞號（例：TPEx 把 006201 吐成 '6201'）時，
        # 不能讓另一個市場的列整列蓋掉既有列並改標市場。NULL（上市）要用 IS NOT DISTINCT FROM 比。
        where = table.c.market.is_not_distinct_from(stmt.excluded.market) if guard else None
        stmt = stmt.on_conflict_do_update(index_elements=index_elements, set_=update, where=where)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=index_elements)
    if not guard:
        conn.execute(stmt)
        return len(records)
    # multi-row INSERT 的 rowcount 不可靠，用 RETURNING 數實際寫入／更新的鍵
    stmt = stmt.returning(*(table.c[k] for k in index_elements))
    done = {tuple(str(v) for v in row) for row in conn.execute(stmt)}
    skipped = [r for r in records if tuple(str(_key(r[k])) for k in index_elements) not in done]
    if skipped:
        sample = ", ".join(
            f"{'/'.join(str(_key(r[k])) for k in index_elements)}({r.get('market') or 'twse'})"
            for r in skipped[:5])
        print(f"**WARN {table.name}: {len(skipped)} rows skipped — key already stored under "
              f"another market (PK has no market): {sample}", flush=True)
    return len(records) - len(skipped)


def _key(v):
    """把 records 的鍵值正規化成與 RETURNING 回來的值同樣的字串（日期可能是 str／Timestamp）。"""
    if hasattr(v, "date") and callable(v.date):
        return v.date()
    return v
