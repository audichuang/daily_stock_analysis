"""event_calendar 追加公布欄位的 migration（a6c1e3f5b7d9）：離線、記憶體 SQLite ATTACH 成 ``market``。

先跑真實的 ``f2a7c4d8e913``（建 event_calendar）再跑這支。驗欄位與 model 一致、全部可空、
有帶 ``released_at`` 的列時拒絕降版（且在任何 DDL 之前）。SQLite 驗得了 ADD／DROP COLUMN，
驗不了 Postgres 專屬行為——那些用 ``make pg-scratch`` 的 ``market_data/tests``。
"""

from importlib import import_module

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from market_data import models

base = import_module("market_data.migrations.versions.f2a7c4d8e913_add_macro_rates_events")
release = import_module("market_data.migrations.versions.a6c1e3f5b7d9_add_event_release_fields")

NEW_COLS = {"released_at", "series_id", "observation_date", "actual_value", "prior_value",
            "actual_vintage", "actual_source"}


@pytest.fixture
def schema():
    engine = sa.create_engine("sqlite://")
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS market")
            with Operations.context(MigrationContext.configure(conn)):
                base.upgrade()
                conn.commit()
                yield conn
    finally:
        engine.dispose()


def _columns(conn):
    return {r[1]: r for r in conn.exec_driver_sql("PRAGMA market.table_info(event_calendar)").all()}


def test_revision_chain_follows_f2a7c4d8e913():
    assert release.revision == "a6c1e3f5b7d9" and release.down_revision == "f2a7c4d8e913"


def test_upgrade_adds_exactly_the_model_columns_all_nullable(schema):
    before = set(_columns(schema))
    with Operations.context(MigrationContext.configure(schema)):
        release.upgrade()
    cols = _columns(schema)
    assert set(cols) - before == NEW_COLS
    assert all(cols[c][3] == 0 for c in NEW_COLS), "新欄位必須可空（舊的 FOMC／財報列沒有值）"
    assert set(cols) == {c.name for c in models.EventCalendar.__table__.columns}, "migration 與 model 不一致"


def test_downgrade_refuses_when_release_rows_exist_before_any_ddl(schema):
    with Operations.context(MigrationContext.configure(schema)):
        release.upgrade()
        schema.exec_driver_sql(
            "INSERT INTO market.event_calendar (event_type, symbol, label, event_date, released_at) "
            "VALUES ('nfp', 'US', '2099-11-06', '2099-11-06', '2099-11-06 13:30:00')")
        with pytest.raises(RuntimeError, match="拒絕降版"):
            release.downgrade()
    assert NEW_COLS <= set(_columns(schema)), "拒絕降版時不能已經 drop 欄位"


def test_downgrade_succeeds_without_release_rows_and_keeps_old_rows(schema):
    with Operations.context(MigrationContext.configure(schema)):
        release.upgrade()
        schema.exec_driver_sql(
            "INSERT INTO market.event_calendar (event_type, symbol, label, event_date) "
            "VALUES ('fomc', 'FED', '2099-10', '2099-10-28')")
        release.downgrade()
    assert not NEW_COLS & set(_columns(schema))
    assert schema.exec_driver_sql("SELECT count(*) FROM market.event_calendar").scalar() == 1
