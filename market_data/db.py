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


@lru_cache(maxsize=4)
def _engine_for(url: str):
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800, future=True)


def get_engine(url: str | None = None):
    # cache per URL so repeated dashboard reads reuse one pool (no leak)
    return _engine_for(url or database_url())


def get_sessionmaker(engine=None):
    return sessionmaker(bind=engine or get_engine(), future=True)
