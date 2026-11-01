"""SQLAlchemy engine/session + declarative Base for the ``market`` schema.

The market schema holds finlab-crawled TW market history (price, valuation,
fundamentals, chips…). The dashboard app reads these tables; the crawler writes
them. All schema changes go through Alembic migrations (see market_data/migrations).
"""

import os
from functools import lru_cache

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

MARKET_SCHEMA = "market"


class Base(DeclarativeBase):
    metadata = MetaData(schema=MARKET_SCHEMA)


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (see .env)")
    return url


@lru_cache(maxsize=8)
def _engine_for(url: str, statement_timeout_ms: int | None = None, read_only: bool = False):
    # Bound the TCP connect: a blackholed host otherwise blocks 60s+ per attempt and starves callers'
    # own budgets (e.g. the TW valuation API fallback).
    connect_args = {"connect_timeout": 5}
    options = []
    if statement_timeout_ms:
        # Postgres per-connection statement timeout (psycopg): abort runaway reads.
        options.append(f"-c statement_timeout={int(statement_timeout_ms)}")
    if read_only:
        options.append("-c default_transaction_read_only=on")
    if options:
        connect_args["options"] = " ".join(options)
    return create_engine(
        url, pool_pre_ping=True, pool_recycle=1800, future=True,
        connect_args=connect_args,
    )


def get_engine(url: str | None = None, statement_timeout_ms: int | None = None, read_only: bool = False):
    # cache per (URL, timeout, read_only) so repeated dashboard reads reuse one pool (no leak)
    return _engine_for(url or database_url(), statement_timeout_ms, read_only)


def get_sessionmaker(engine=None):
    return sessionmaker(bind=engine or get_engine(), future=True)
