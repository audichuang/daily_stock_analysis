# -*- coding: utf-8 -*-
"""H2：既有的 backtest_results／decision_signal_outcomes 表在初始化時補上新欄位。"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql

from src.config import Config
from src.storage import BacktestResult, DatabaseManager, DecisionSignalOutcomeRecord

BACKTEST_NEW = ("entry_date", "price_basis", "adjustment_reason", "simulated_net_return_pct")
OUTCOME_NEW = ("entry_date", "price_basis", "adjustment_reason", "max_adverse_excursion_pct")


@pytest.fixture()
def db_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("STOCK_LIST=600519\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "upgrade.db"))
    Config._instance = None
    DatabaseManager.reset_instance()
    yield
    DatabaseManager.reset_instance()
    Config._instance = None


def _columns(db, table):
    return {column["name"] for column in inspect(db._engine).get_columns(table)}


def _reopen():
    DatabaseManager.reset_instance()
    Config._instance = None
    return DatabaseManager.get_instance()


def test_existing_sqlite_tables_gain_new_columns_and_keep_rows(db_env):
    db = DatabaseManager.get_instance()
    # 模擬舊版表：把新欄位拿掉，再寫一筆舊資料。
    with db._engine.begin() as conn:
        for name in BACKTEST_NEW:
            conn.exec_driver_sql(f"ALTER TABLE backtest_results DROP COLUMN {name}")
        for name in OUTCOME_NEW:
            conn.exec_driver_sql(f"ALTER TABLE decision_signal_outcomes DROP COLUMN {name}")
        conn.execute(text(
            "INSERT INTO backtest_results (analysis_history_id, code, analysis_date, eval_window_days, "
            "engine_version, eval_status, stock_return_pct) "
            "VALUES (1, '600519', '2024-01-02', 10, 'v1', 'completed', -3.5)"
        ))
        conn.execute(text(
            "INSERT INTO decision_signal_outcomes (signal_id, horizon, engine_version, eval_status, holding_state) "
            "VALUES (1, '3d', 'decision-signal-v1', 'completed', 'unknown')"
        ))
    assert not set(BACKTEST_NEW) & _columns(db, "backtest_results")

    db = _reopen()
    assert set(BACKTEST_NEW) <= _columns(db, "backtest_results")
    assert set(OUTCOME_NEW) <= _columns(db, "decision_signal_outcomes")

    db = _reopen()  # 第二次初始化必須冪等
    with db.get_session() as session:
        row = session.query(BacktestResult).one()
        assert (row.engine_version, row.stock_return_pct, row.analysis_date) == ("v1", -3.5, date(2024, 1, 2))
        assert row.price_basis is None
        outcome = session.query(DecisionSignalOutcomeRecord).one()
        assert outcome.engine_version == "decision-signal-v1"
        assert outcome.max_adverse_excursion_pct is None


def test_postgres_add_column_ddl_from_orm_model():
    old_columns = {c.name for c in BacktestResult.__table__.columns} - set(BACKTEST_NEW)
    ddl = DatabaseManager._postgres_add_column_ddl(BacktestResult.__table__, old_columns, postgresql.dialect())
    assert ddl == (
        "ALTER TABLE backtest_results "
        "ADD COLUMN IF NOT EXISTS entry_date DATE, "
        "ADD COLUMN IF NOT EXISTS price_basis VARCHAR(16), "
        "ADD COLUMN IF NOT EXISTS adjustment_reason VARCHAR(32), "
        "ADD COLUMN IF NOT EXISTS simulated_net_return_pct FLOAT"
    )
    all_columns = {c.name for c in BacktestResult.__table__.columns}
    assert DatabaseManager._postgres_add_column_ddl(BacktestResult.__table__, all_columns, postgresql.dialect()) is None
