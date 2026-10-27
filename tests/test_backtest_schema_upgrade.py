# -*- coding: utf-8 -*-
"""H2：既有的 backtest_results／decision_signal_outcomes 表在初始化時補上新欄位。"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql

from src.config import Config
from src.storage import AnalysisHistory, BacktestResult, DatabaseManager, DecisionSignalOutcomeRecord

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


FORECAST_NEW = ("prompt_hash", "input_snapshot_hash", "model_version", "p_5d_beat_0050", "llm_attempts")


def test_existing_analysis_history_gains_forecast_columns_and_keeps_rows(db_env):
    db = DatabaseManager.get_instance()
    with db._engine.begin() as conn:
        for name in FORECAST_NEW:
            conn.exec_driver_sql(f"ALTER TABLE analysis_history DROP COLUMN {name}")
        conn.execute(text(
            "INSERT INTO analysis_history (query_id, code, name, sentiment_score) VALUES ('q', '2330.TW', 'x', 61)"
        ))
    assert not set(FORECAST_NEW) & _columns(db, "analysis_history")

    db = _reopen()
    assert set(FORECAST_NEW) <= _columns(db, "analysis_history")
    db = _reopen()  # 冪等
    with db.get_session() as session:
        row = session.query(AnalysisHistory).one()
        assert (row.code, row.sentiment_score) == ("2330.TW", 61)
        assert all(getattr(row, name) is None for name in FORECAST_NEW)


def test_postgres_add_column_ddl_for_analysis_history_forecast_columns():
    old = {c.name for c in AnalysisHistory.__table__.columns} - set(FORECAST_NEW)
    ddl = DatabaseManager._postgres_add_column_ddl(AnalysisHistory.__table__, old, postgresql.dialect())
    assert ddl == (
        "ALTER TABLE analysis_history "
        "ADD COLUMN IF NOT EXISTS prompt_hash VARCHAR(64), "
        "ADD COLUMN IF NOT EXISTS input_snapshot_hash VARCHAR(64), "
        "ADD COLUMN IF NOT EXISTS model_version VARCHAR(96), "
        "ADD COLUMN IF NOT EXISTS p_5d_beat_0050 FLOAT, "
        "ADD COLUMN IF NOT EXISTS llm_attempts TEXT"
    )


def test_save_analysis_history_persists_forecast_fields_and_nulls_when_absent(db_env):
    from types import SimpleNamespace

    db = DatabaseManager.get_instance()
    base = dict(code="2330.TW", name="x", sentiment_score=60, operation_advice="買入", trend_prediction="看多",
                analysis_summary="s", dashboard=None, raw_response="r")
    full = SimpleNamespace(**base, prompt_hash="a" * 64, input_snapshot_hash="b" * 64, model_version="m" * 200,
                           p_5d_beat_0050=0.7, llm_attempts=[{"attempt": 1, "model": "m", "response_text": "r"}])
    bare = SimpleNamespace(**base)  # market_review 等其他呼叫端：沒有這些屬性
    nan_p = SimpleNamespace(**base, p_5d_beat_0050=float("nan"))
    big_p = SimpleNamespace(**base, p_5d_beat_0050=1.7)
    for r in (full, bare, nan_p, big_p):
        assert db.save_analysis_history(r, "q", "simple", None) > 0
    with db.get_session() as session:
        rows = session.query(AnalysisHistory).order_by(AnalysisHistory.id).all()
    assert rows[0].p_5d_beat_0050 == 0.7 and rows[0].prompt_hash == "a" * 64
    assert rows[0].model_version == "m" * 96  # 截到欄位長度
    assert '"response_text"' in rows[0].llm_attempts
    assert all(getattr(rows[1], n) is None for n in FORECAST_NEW)
    assert rows[2].p_5d_beat_0050 is None and rows[3].p_5d_beat_0050 is None  # 非有限值／超界不落庫
