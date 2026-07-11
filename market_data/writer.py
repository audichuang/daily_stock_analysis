"""Upsert helper for writing crawled data into market.* (Postgres).

Daily increments are small (~a few thousand rows); one INSERT ... ON CONFLICT
DO UPDATE per batch keeps the tables idempotent on re-crawl.
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert


def dedupe(records, index_elements):
    """按 PK 去重取最後一筆(來源偶有重複列)。"""
    return list({tuple(r[k] for k in index_elements): r for r in records}.values())


def upsert(conn, table, records, index_elements, coalesce=()):
    """INSERT ``records`` (list of dicts) into ``table``, updating rows that
    collide on ``index_elements`` (the primary key). Returns rows submitted.

    ``coalesce`` 欄位在衝突更新時保留舊值優先於 NULL(新值非 NULL 才覆蓋)——
    給「備援來源缺欄」用,避免重爬把既有完整資料抹成 NULL。"""
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
    if update:
        stmt = stmt.on_conflict_do_update(index_elements=index_elements, set_=update)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=index_elements)
    conn.execute(stmt)
    return len(records)
