"""Upsert helper for writing crawled data into market.* (Postgres).

Daily increments are small (~a few thousand rows); one INSERT ... ON CONFLICT
DO UPDATE per batch keeps the tables idempotent on re-crawl.
"""

from sqlalchemy.dialects.postgresql import insert


def upsert(conn, table, records, index_elements):
    """INSERT ``records`` (list of dicts) into ``table``, updating rows that
    collide on ``index_elements`` (the primary key). Returns rows submitted."""
    if not records:
        return 0
    stmt = insert(table).values(records)
    update = {
        c.name: stmt.excluded[c.name]
        for c in table.columns
        if c.name not in index_elements
    }
    if update:
        stmt = stmt.on_conflict_do_update(index_elements=index_elements, set_=update)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=index_elements)
    conn.execute(stmt)
    return len(records)
