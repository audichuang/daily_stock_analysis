import os
import pathlib

import pytest

# 本機 data/ 的臨時休市清單不能漏進測試的交易日判斷（見 market_data.closures）。
os.environ["TW_ADHOC_CLOSED_FILE"] = os.devnull
os.environ["TW_CLOSURE_AUTODETECT"] = "false"
# daily 的總經段預設開、會連 yfinance／Kalshi／Fed；測試一律關，要驗接線的測試自己 setenv。
os.environ["MACRO_PERSIST_ENABLED"] = "false"

# load DATABASE_URL from the repo-root .env for DB-backed tests
_envf = pathlib.Path(__file__).resolve().parents[2] / ".env"
if _envf.exists():
    for _line in _envf.read_text().splitlines():
        if _line.startswith("DATABASE_URL=") and "DATABASE_URL" not in os.environ:
            os.environ["DATABASE_URL"] = _line.split("=", 1)[1].strip()


@pytest.fixture(scope="session")
def engine():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; market_data DB-backed tests need "
                    "the market Postgres (see market_data/AGENTS.md)")
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
