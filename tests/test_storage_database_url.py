# -*- coding: utf-8 -*-
"""STORAGE_DATABASE_URL 选库与按方言分派的 upsert。

不连真库：``create_engine`` 不建立连线就能拿到方言。两种方言编出的 ON CONFLICT
字串长得一样，所以断言构造器型别而不是 SQL 文本。
"""
import os
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql, sqlite

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import Config
from src.storage import ConversationSummary, DatabaseManager


def test_get_db_url_prefers_storage_database_url(tmp_path):
    url = "postgresql+psycopg://u:p@db.invalid:5432/stock?options=-csearch_path%3Ddsa"
    config = Config(database_path=str(tmp_path / "x.db"), storage_database_url=url)
    assert config.get_db_url() == url


def test_get_db_url_defaults_to_sqlite_path(tmp_path):
    db_path = tmp_path / "sub" / "x.db"
    config = Config(database_path=str(db_path))
    assert config.get_db_url() == f"sqlite:///{db_path.absolute()}"
    assert db_path.parent.is_dir()


def _manager_for(url: str):
    return SimpleNamespace(_engine=create_engine(url))


def test_upsert_insert_uses_postgresql_dialect():
    stmt = DatabaseManager.upsert_insert(
        _manager_for("postgresql+psycopg://u:p@db.invalid/stock"), ConversationSummary
    )
    assert isinstance(stmt, postgresql.Insert)
    assert not isinstance(stmt, sqlite.Insert)


def test_upsert_insert_keeps_sqlite_dialect():
    stmt = DatabaseManager.upsert_insert(_manager_for("sqlite:///:memory:"), ConversationSummary)
    assert isinstance(stmt, sqlite.Insert)
    assert not isinstance(stmt, postgresql.Insert)


def test_upsert_insert_rejects_unsupported_dialect():
    with pytest.raises(NotImplementedError):
        fake = SimpleNamespace(_engine=SimpleNamespace(dialect=SimpleNamespace(name="mysql")))
        DatabaseManager.upsert_insert(fake, ConversationSummary)


def test_all_storage_ddl_compiles_for_postgresql():
    """Postgres 识别字上限 63 字元，SQLite 没有；超长的显式名称只会在真的建表时炸。"""
    from sqlalchemy.schema import CreateIndex, CreateTable

    from src.storage import Base

    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        str(CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=dialect))


def test_backtest_eval_status_column_fits_engine_statuses():
    """SQLite 不检查 VARCHAR 长度，Postgres 会；回测引擎写入的状态必须放得下。"""
    from src.storage import BacktestResult

    limit = BacktestResult.__table__.c.eval_status.type.length
    for status in ("pending", "completed", "insufficient_data", "unable", "error"):
        assert len(status) <= limit, status


@pytest.mark.parametrize("key", ["STORAGE_DATABASE_URL", "DATABASE_URL"])
def test_database_url_keys_are_sensitive_in_settings(key):
    """URL 内嵌帐密；未登记的 key 只靠名称推断敏感性，漏判就会以明文欄位显示。"""
    from src.core.config_registry import get_field_definition

    assert get_field_definition(key, "postgresql+psycopg://u:p@h/db")["is_sensitive"] is True


def test_database_path_stays_non_sensitive():
    from src.core.config_registry import get_field_definition

    assert get_field_definition("DATABASE_PATH", "./data/x.db")["is_sensitive"] is False
