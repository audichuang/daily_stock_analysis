import os
import pathlib

import pytest

# load DATABASE_URL from the repo-root .env for DB-backed tests
_envf = pathlib.Path(__file__).resolve().parents[2] / ".env"
if _envf.exists():
    for _line in _envf.read_text().splitlines():
        if _line.startswith("DATABASE_URL=") and "DATABASE_URL" not in os.environ:
            os.environ["DATABASE_URL"] = _line.split("=", 1)[1].strip()


@pytest.fixture(scope="session")
def engine():
    from market_data.db import get_engine

    return get_engine()


@pytest.fixture
def pg_conn(engine):
    """A connection wrapped in a transaction that always rolls back, so tests
    never pollute the real market schema."""
    conn = engine.connect()
    tx = conn.begin()
    try:
        yield conn
    finally:
        tx.rollback()
        conn.close()
