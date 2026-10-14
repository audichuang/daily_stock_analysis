# -*- coding: utf-8 -*-
"""持仓帐本写锁按方言分派：SQLite 用 BEGIN IMMEDIATE，Postgres 用 advisory lock。

Postgres 不认得 ``BEGIN IMMEDIATE``，写死它会让正式库上的每一笔持仓写入都 SyntaxError。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.repositories.portfolio_repo import PORTFOLIO_WRITE_ADVISORY_LOCK_KEY, PortfolioRepository


def _session(dialect: str) -> MagicMock:
    session = MagicMock()
    session.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name=dialect))
    return session


def _issued_sql(session: MagicMock) -> list:
    return [c.args[0] for c in session.connection.return_value.exec_driver_sql.call_args_list]


def test_sqlite_takes_begin_immediate():
    session = _session("sqlite")
    PortfolioRepository._acquire_portfolio_write_lock(session)
    assert _issued_sql(session) == ["BEGIN IMMEDIATE"]


def test_postgres_takes_transaction_scoped_advisory_lock_not_begin_immediate():
    session = _session("postgresql")
    PortfolioRepository._acquire_portfolio_write_lock(session)
    assert _issued_sql(session) == [f"SELECT pg_advisory_xact_lock({PORTFOLIO_WRITE_ADVISORY_LOCK_KEY})"]


@pytest.mark.parametrize("dialect", ["mysql", "mssql"])
def test_other_dialects_issue_nothing(dialect):
    session = _session(dialect)
    PortfolioRepository._acquire_portfolio_write_lock(session)
    assert _issued_sql(session) == []
