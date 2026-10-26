"""基金降版護欄：任一表有資料就保留全部資料與結構，空表仍可降版。"""

from importlib import import_module

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


migration = import_module(
    "market_data.migrations.versions.c7d2e9f41a08_add_fund_info_fund_nav"
)


@pytest.fixture
def fund_schema():
    # 只用記憶體資料庫執行真實 Alembic 操作，不讀 DATABASE_URL 或連正式庫。
    engine = sa.create_engine("sqlite://")
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS market")
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
                yield conn
    finally:
        engine.dispose()


def _snapshot(conn):
    return {
        "schema": conn.exec_driver_sql(
            "SELECT type, name, sql FROM market.sqlite_master ORDER BY type, name"
        ).fetchall(),
        "fund_info": conn.exec_driver_sql(
            "SELECT * FROM market.fund_info ORDER BY fund_id"
        ).fetchall(),
        "fund_nav": conn.exec_driver_sql(
            "SELECT * FROM market.fund_nav ORDER BY fund_id, date"
        ).fetchall(),
    }


@pytest.mark.parametrize("info_count, nav_count", [(1, 0), (0, 1), (2, 3)])
def test_downgrade_refuses_either_populated_fund_table(fund_schema, info_count, nav_count):
    for i in range(info_count):
        fund_schema.execute(sa.text(
            "INSERT INTO market.fund_info (fund_id, name) VALUES (:id, :name)"
        ), {"id": f"T{i}", "name": "測試基金"})
    for i in range(nav_count):
        fund_schema.execute(sa.text(
            "INSERT INTO market.fund_nav (fund_id, date, nav, source) "
            "VALUES (:id, '2099-01-01', 12.34, 'sitca')"
        ), {"id": f"T{i}"})
    before = _snapshot(fund_schema)

    with pytest.raises(RuntimeError, match="拒絕降版") as exc:
        migration.downgrade()

    assert f"fund_info {info_count:,}" in str(exc.value)
    assert f"fund_nav {nav_count:,}" in str(exc.value)
    assert "匯出" in str(exc.value)
    assert _snapshot(fund_schema) == before


def test_downgrade_allows_empty_fund_tables(fund_schema):
    # 其他 schema 的同名資料表不應阻擋 market 空表降版，也不應被刪除。
    for table in ("fund_info", "fund_nav"):
        fund_schema.exec_driver_sql(f"CREATE TABLE main.{table} (value INTEGER)")
        fund_schema.exec_driver_sql(f"INSERT INTO main.{table} VALUES (1)")

    migration.downgrade()

    assert fund_schema.exec_driver_sql("SELECT name FROM market.sqlite_master").fetchall() == []
    for table in ("fund_info", "fund_nav"):
        assert fund_schema.exec_driver_sql(f"SELECT value FROM main.{table}").scalar_one() == 1
