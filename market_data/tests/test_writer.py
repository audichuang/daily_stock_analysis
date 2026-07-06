from datetime import date

from sqlalchemy import text

from market_data.models import Price
from market_data.writer import upsert


def test_upsert_inserts_then_updates_same_key(pg_conn):
    rows = [{"stock_id": "TESTX", "date": date(2024, 1, 2), "close": 100}]
    n = upsert(pg_conn, Price.__table__, rows, ["stock_id", "date"])
    assert n == 1
    got = pg_conn.execute(
        text("SELECT close FROM market.price WHERE stock_id='TESTX'")
    ).scalar()
    assert float(got) == 100.0

    # same PK, new value -> update in place (no duplicate row)
    upsert(pg_conn, Price.__table__,
           [{"stock_id": "TESTX", "date": date(2024, 1, 2), "close": 200}],
           ["stock_id", "date"])
    rows_now = pg_conn.execute(
        text("SELECT close FROM market.price WHERE stock_id='TESTX'")
    ).fetchall()
    assert len(rows_now) == 1
    assert float(rows_now[0][0]) == 200.0


def test_upsert_empty_is_noop(pg_conn):
    assert upsert(pg_conn, Price.__table__, [], ["stock_id", "date"]) == 0
