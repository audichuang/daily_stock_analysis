"""snapshot migration（b8d2f4a6c0e1）：離線、記憶體 SQLite ATTACH 成 ``market``，跑 f2a7 → a6c1 → b8d2 這段鏈。

驗新表與新欄位和 model 一致、既有 ``rate_expectations`` 列補成 ``legacy``、有資料時拒絕降版（且在任何
DDL 之前）。**主鍵變更（``rate_expectations`` 換成含 ``snapshot_slot`` 的 PK）SQLite 驗不了**：它不能 drop
PK constraint，migration 在非 Postgres 上略過那一步——那段只在 ``make pg-scratch`` 的
``market_data/tests/test_snapshot_pg.py`` 驗。
"""

from importlib import import_module

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from market_data import models

f2a7 = import_module("market_data.migrations.versions.f2a7c4d8e913_add_macro_rates_events")
a6c1 = import_module("market_data.migrations.versions.a6c1e3f5b7d9_add_event_release_fields")
b8d2 = import_module("market_data.migrations.versions.b8d2f4a6c0e1_add_snapshot_tables")
taifex_mig = import_module("market_data.migrations.versions.e4f7a2c9b1d3_add_taifex_fut_oi")

NEW_TABLES = {
    "macro_series_snapshot": models.MacroSeriesSnapshot,
    "institutional_initial": models.InstitutionalInitial,
    "monthly_revenue_first_seen": models.MonthlyRevenueFirstSeen,
}


@pytest.fixture
def schema():
    """升到 a6c1（b8d2 的前一版），再放一列舊的 rate_expectations 與一列 taifex_fut_oi。"""
    engine = sa.create_engine("sqlite://")
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS market")
            with Operations.context(MigrationContext.configure(conn)):
                taifex_mig.upgrade()
                f2a7.upgrade()
                a6c1.upgrade()
                conn.exec_driver_sql(
                    "INSERT INTO market.rate_expectations (snapshot_date, meeting_date, outcome, prob_mid) "
                    "VALUES ('2026-10-26', '2026-12-09', 'hold', 0.9)")
                conn.commit()
                yield conn
    finally:
        engine.dispose()


def _cols(conn, table):
    return {r[1]: r for r in conn.exec_driver_sql(f"PRAGMA market.table_info({table})").all()}


def _snapshot_of_ddl(conn):
    return conn.exec_driver_sql("SELECT type, name, sql FROM market.sqlite_master ORDER BY name").all()


def test_revision_chain_follows_a6c1e3f5b7d9():
    assert b8d2.revision == "b8d2f4a6c0e1" and b8d2.down_revision == "a6c1e3f5b7d9"
    assert a6c1.down_revision == "f2a7c4d8e913"


def test_upgrade_creates_new_tables_matching_the_models(schema):
    b8d2.upgrade()
    for name, model in NEW_TABLES.items():
        cols = _cols(schema, name)
        assert set(cols) == {c.name for c in model.__table__.columns}, name
        pk = [c for c, row in sorted(cols.items(), key=lambda kv: kv[1][5]) if row[5]]
        assert set(pk) == {c.name for c in model.__table__.primary_key}, name
    # 初版／首次值表的欄位 = 來源表欄位 + captured_at
    assert set(_cols(schema, "institutional_initial")) == \
        {c.name for c in models.Institutional.__table__.columns} | {"captured_at"}
    assert set(_cols(schema, "monthly_revenue_first_seen")) == \
        {c.name for c in models.MonthlyRevenue.__table__.columns} | {"captured_at"}


def test_upgrade_adds_slot_with_legacy_backfill_and_nullable_taifex_stamps(schema):
    b8d2.upgrade()
    rate_cols = _cols(schema, "rate_expectations")
    assert set(rate_cols) == {c.name for c in models.RateExpectation.__table__.columns}
    assert rate_cols["snapshot_slot"][3] == 1, "snapshot_slot 必須 NOT NULL"
    assert schema.exec_driver_sql("SELECT snapshot_slot FROM market.rate_expectations").scalar_one() == "legacy"
    taifex_cols = _cols(schema, "taifex_fut_oi")
    assert set(taifex_cols) == {c.name for c in models.TaifexFutOI.__table__.columns}
    assert taifex_cols["first_seen_at"][3] == 0 and taifex_cols["captured_at"][3] == 0


@pytest.mark.parametrize("table", sorted(NEW_TABLES))
def test_downgrade_refuses_new_table_data_before_any_ddl(schema, table):
    b8d2.upgrade()
    fill = {"macro_series_snapshot": "snapshot_date, snapshot_slot, series_id, date VALUES "
                                      "('2099-01-02','premarket','ZZ','2099-01-01')",
            "institutional_initial": "stock_id, date VALUES ('2330','2099-01-02')",
            "monthly_revenue_first_seen": "stock_id, revenue_month VALUES ('2330','2099-01-01')"}[table]
    columns, values = fill.split(" VALUES ")
    schema.exec_driver_sql(f"INSERT INTO market.{table} ({columns}) VALUES {values}")
    before = _snapshot_of_ddl(schema)
    with pytest.raises(RuntimeError, match=f"拒絕降版：{table}"):
        b8d2.downgrade()
    assert _snapshot_of_ddl(schema) == before


def test_downgrade_refuses_stamped_taifex_rows_before_any_ddl(schema):
    b8d2.upgrade()
    schema.exec_driver_sql(
        "INSERT INTO market.taifex_fut_oi (date, commodity_id, identity, first_seen_at) "
        "VALUES ('2099-01-02', 'TXF', 'foreign', '2099-01-02 00:00:00')")
    before = _snapshot_of_ddl(schema)
    with pytest.raises(RuntimeError, match="拒絕降版：taifex_fut_oi"):
        b8d2.downgrade()
    assert _snapshot_of_ddl(schema) == before


def test_empty_downgrade_restores_the_previous_schema(schema):
    before = _snapshot_of_ddl(schema)
    b8d2.upgrade()
    b8d2.downgrade()
    assert set(_cols(schema, "rate_expectations")) == {
        "snapshot_date", "meeting_date", "outcome", "prob_mid", "yes_bid", "yes_ask", "last_price",
        "volume", "open_interest", "source_updated_at", "source"}
    assert not (set(NEW_TABLES) & {r[1] for r in schema.exec_driver_sql(
        "SELECT type, name FROM market.sqlite_master WHERE type = 'table'").all()})
    assert {n for _, n, _ in _snapshot_of_ddl(schema)} == {n for _, n, _ in before}
    assert schema.exec_driver_sql("SELECT count(*) FROM market.rate_expectations").scalar_one() == 1
