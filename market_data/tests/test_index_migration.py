"""指數欄位遷移以離線 PostgreSQL DDL 驗證，不連正式資料庫。"""

from importlib import import_module
from io import StringIO

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Numeric

from market_data import models

migration = import_module("market_data.migrations.versions.e8f6c2a91b04_add_market_index_ohlc")


def test_upgrade_adds_only_nullable_ohlc_with_model_precision():
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql",
                                         opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    assert migration.down_revision == "d3a8b6e15c27"
    assert "SET lock_timeout = '10s'" in sql
    assert sql.count("ALTER TABLE market.market_index ADD COLUMN") == 3
    assert "DROP" not in sql and "UPDATE" not in sql and "NOT NULL" not in sql
    for name in ("open", "high", "low"):
        assert f"ADD COLUMN {name} NUMERIC(14, 2)" in sql
        column = models.MarketIndex.__table__.c[name]
        assert isinstance(column.type, Numeric)
        assert (column.type.precision, column.type.scale, column.nullable) == (14, 2, True)


@pytest.mark.parametrize("count", [0, 1, 3])
def test_downgrade_preserves_populated_ohlc_but_allows_empty_columns(monkeypatch, count):
    calls, queries = [], []

    class Connection:
        def execute(self, statement):
            queries.append(str(statement))
            return self

        def scalar(self):
            return count

    monkeypatch.setattr(migration.op, "get_bind", Connection)
    monkeypatch.setattr(migration.op, "execute", lambda sql: calls.append(sql))
    monkeypatch.setattr(migration.op, "drop_column", lambda *a, **kw: calls.append((a, kw)))
    if count:
        with pytest.raises(RuntimeError, match="拒絕降版"):
            migration.downgrade()
        assert calls == []
    else:
        migration.downgrade()
        assert calls == ["SET lock_timeout = '10s'", *[
            (("market_index", name), {"schema": "market"}) for name in ("low", "high", "open")]]
    assert len(queries) == 1
    assert "market.market_index" in queries[0]
    assert "open IS NOT NULL OR high IS NOT NULL OR low IS NOT NULL" in queries[0]
