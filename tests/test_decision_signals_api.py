# -*- coding: utf-8 -*-
"""AI 建議 API 追加行為：每檔最新一筆、優先排序、摘要、訊號當時價、統計的中性。"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

import src.auth as auth  # noqa: E402
from api.app import create_app  # noqa: E402
from src.config import Config  # noqa: E402
from src.services.decision_signal_outcome_service import DecisionSignalOutcomeService  # noqa: E402
from src.storage import (  # noqa: E402
    AnalysisHistory,
    DatabaseManager,
    PortfolioAccount,
    PortfolioPosition,
)

LIST_URL = "/api/v1/decision-signals"
SUMMARY_URL = "/api/v1/decision-signals/summary"


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


@pytest.fixture()
def client_and_db(tmp_path: Path):
    old_env_file = os.environ.get("ENV_FILE")
    old_database_path = os.environ.get("DATABASE_PATH")
    env_path = tmp_path / ".env"
    db_path = tmp_path / "decision_signals_api.db"
    static_dir = tmp_path / "empty-static"
    static_dir.mkdir()
    env_path.write_text(
        f"GEMINI_API_KEY=test\nADMIN_AUTH_ENABLED=false\nDATABASE_PATH={db_path}\n",
        encoding="utf-8",
    )
    os.environ["ENV_FILE"] = str(env_path)
    os.environ["DATABASE_PATH"] = str(db_path)
    _reset_auth_globals()
    Config.reset_instance()
    DatabaseManager.reset_instance()
    client = TestClient(create_app(static_dir=static_dir))
    db = DatabaseManager.get_instance()
    try:
        yield client, db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        _reset_auth_globals()
        for key, value in (("ENV_FILE", old_env_file), ("DATABASE_PATH", old_database_path)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


_next_report = {"id": 9000}


def _create(client, code="AAPL", action="buy", market="us", **overrides):
    _next_report["id"] += 1
    payload = {
        "stock_code": code,
        "stock_name": code,
        "market": market,
        "source_type": "manual",
        "trigger_source": "api",
        "action": action,
        "horizon": "3d",
        "trace_id": f"trace-{_next_report['id']}",
        **overrides,
    }
    response = client.post(LIST_URL, json=payload)
    assert response.status_code == 200, response.text
    return response.json()["item"]


def _save_close(db, code: str, close: float, on_date=None) -> None:
    on_date = on_date or date.today() - timedelta(days=1)
    db.save_daily_data(
        pd.DataFrame([{
            "date": on_date, "open": close, "high": close, "low": close, "close": close,
            "volume": 1.0, "amount": close, "pct_chg": 0.0,
        }]),
        code=code,
        data_source="decision-signals-test",
    )


def _hold(db, code: str, market: str = "us") -> None:
    with db.session_scope() as session:
        account = PortfolioAccount(name="Main", market=market, base_currency="USD", is_active=True)
        session.add(account)
        session.flush()
        session.add(PortfolioPosition(
            account_id=account.id, cost_method="fifo", symbol=code, market=market, currency="USD",
            quantity=10.0, avg_cost=100.0, total_cost=1000.0, last_price=100.0,
            market_value_base=1000.0, unrealized_pnl_base=0.0, valuation_currency="USD",
        ))


# ---- group_latest ----


def test_group_latest_returns_one_row_per_stock_with_older_count(client_and_db) -> None:
    client, _ = client_and_db
    _create(client, code="AAPL", action="watch")
    _create(client, code="AAPL", action="hold")
    newest = _create(client, code="AAPL", action="add")
    other = _create(client, code="MSFT", action="watch")

    body = client.get(LIST_URL, params={"group_latest": "true"}).json()
    assert body["total"] == 2  # 檔數，不是筆數
    by_code = {item["stock_code"]: item for item in body["items"]}
    assert by_code["AAPL"]["id"] == newest["id"]
    assert by_code["AAPL"]["older_count"] == 2
    assert by_code["MSFT"]["id"] == other["id"]
    assert by_code["MSFT"]["older_count"] == 0


def test_group_latest_reports_the_previous_action_only_when_older_rows_exist(client_and_db) -> None:
    client, _ = client_and_db
    _create(client, code="AAPL", action="watch")
    _create(client, code="AAPL", action="hold")
    _create(client, code="AAPL", action="add")
    _create(client, code="MSFT", action="watch")

    by_code = {
        item["stock_code"]: item
        for item in client.get(LIST_URL, params={"group_latest": "true"}).json()["items"]
    }
    # 是緊鄰的前一筆（hold），不是最舊的一筆（watch）
    assert by_code["AAPL"]["previous_action"] == "hold"
    assert by_code["MSFT"]["previous_action"] is None


def test_group_latest_dedupes_across_pages(client_and_db) -> None:
    client, _ = client_and_db
    for code in ("AAPL", "MSFT", "NVDA"):
        _create(client, code=code, action="watch")
        _create(client, code=code, action="hold")

    first = client.get(LIST_URL, params={"group_latest": "true", "page_size": 2}).json()
    second = client.get(LIST_URL, params={"group_latest": "true", "page_size": 2, "page": 2}).json()
    assert first["total"] == second["total"] == 3
    codes = [item["stock_code"] for item in first["items"] + second["items"]]
    assert sorted(codes) == ["AAPL", "MSFT", "NVDA"]


def test_default_list_is_not_grouped(client_and_db) -> None:
    client, _ = client_and_db
    _create(client, code="AAPL", action="watch")
    _create(client, code="AAPL", action="hold")

    body = client.get(LIST_URL).json()
    assert body["total"] == 2
    assert all(item["older_count"] is None for item in body["items"])


def test_same_code_in_two_markets_is_not_merged(client_and_db) -> None:
    client, _ = client_and_db
    _create(client, code="AAPL", market="us", action="watch")
    _create(client, code="600519", market="cn", action="watch")

    assert client.get(LIST_URL, params={"group_latest": "true"}).json()["total"] == 2


def test_group_latest_honours_holding_only(client_and_db) -> None:
    client, db = client_and_db
    _hold(db, "AAPL")
    _create(client, code="AAPL", action="watch")
    _create(client, code="MSFT", action="watch")

    body = client.get(LIST_URL, params={"group_latest": "true", "holding_only": "true"}).json()
    assert [item["stock_code"] for item in body["items"]] == ["AAPL"]
    assert body["items"][0]["is_held"] is True


# ---- 停損與排序 ----


def test_stop_triggered_at_or_below_stop(client_and_db) -> None:
    client, db = client_and_db
    _save_close(db, "AAPL", 90.0)
    _save_close(db, "MSFT", 100.0)
    _save_close(db, "NVDA", 100.01)
    _create(client, code="AAPL", action="hold", stop_loss=100)
    _create(client, code="MSFT", action="hold", stop_loss=100)
    _create(client, code="NVDA", action="hold", stop_loss=100)

    items = client.get(LIST_URL, params={"group_latest": "true"}).json()["items"]
    state = {item["stock_code"]: item["stop_triggered"] for item in items}
    assert state == {"AAPL": True, "MSFT": True, "NVDA": False}


def test_stop_state_null_without_stop_or_price(client_and_db) -> None:
    client, db = client_and_db
    _save_close(db, "AAPL", 90.0)
    _create(client, code="AAPL", action="hold")  # 沒有停損價
    _create(client, code="MSFT", action="hold", stop_loss=100)  # 沒有收盤

    items = client.get(LIST_URL, params={"group_latest": "true"}).json()["items"]
    assert all(item["stop_triggered"] is None for item in items)


def test_inactive_signal_never_counts_as_stop_triggered(client_and_db) -> None:
    client, db = client_and_db
    _save_close(db, "AAPL", 90.0)
    created = _create(client, code="AAPL", action="hold", stop_loss=100)
    assert client.patch(f"{LIST_URL}/{created['id']}/status", json={"status": "closed"}).status_code == 200

    item = client.get(LIST_URL, params={"group_latest": "true"}).json()["items"][0]
    assert item["stop_triggered"] is None
    assert client.get(SUMMARY_URL, params={"status": "closed"}).json()["stop_triggered_count"] == 0


def test_priority_orders_stop_then_held_then_action(client_and_db) -> None:
    client, db = client_and_db
    _hold(db, "HELD")
    _save_close(db, "STOP", 90.0)
    _create(client, code="STOP", action="watch", stop_loss=100)
    _create(client, code="BUYS", action="buy")
    _create(client, code="SELL", action="sell")
    _create(client, code="HELD", action="watch")

    items = client.get(LIST_URL, params={"group_latest": "true", "sort": "priority"}).json()["items"]
    assert [item["stock_code"] for item in items] == ["STOP", "HELD", "SELL", "BUYS"]


def test_priority_paginates_after_sorting(client_and_db) -> None:
    client, db = client_and_db
    _save_close(db, "STOP", 90.0)
    _create(client, code="STOP", action="watch", stop_loss=100)  # 最舊，建立順序會排最後
    _create(client, code="AAAA", action="watch")
    _create(client, code="BBBB", action="watch")

    first = client.get(LIST_URL, params={"group_latest": "true", "sort": "priority", "page_size": 1}).json()
    assert first["items"][0]["stock_code"] == "STOP"
    assert first["total"] == 3


def test_default_sort_is_newest_first(client_and_db) -> None:
    client, db = client_and_db
    _save_close(db, "STOP", 90.0)
    _create(client, code="STOP", action="watch", stop_loss=100)
    _create(client, code="NEWS", action="watch")

    items = client.get(LIST_URL, params={"group_latest": "true"}).json()["items"]
    assert [item["stock_code"] for item in items] == ["NEWS", "STOP"]


def test_priority_requires_group_latest(client_and_db) -> None:
    client, _ = client_and_db
    assert client.get(LIST_URL, params={"sort": "priority"}).status_code == 400


def test_unknown_sort_is_rejected(client_and_db) -> None:
    client, _ = client_and_db
    assert client.get(LIST_URL, params={"sort": "score"}).status_code == 422


def test_close_lookup_failure_does_not_break_list(client_and_db) -> None:
    client, _ = client_and_db
    _create(client, code="AAPL", action="hold", stop_loss=100)
    with patch(
        "src.repositories.portfolio_repo.PortfolioRepository.get_latest_close_with_date",
        side_effect=RuntimeError("boom"),
    ):
        response = client.get(LIST_URL, params={"group_latest": "true", "sort": "priority"})
    assert response.status_code == 200
    assert response.json()["items"][0]["stop_triggered"] is None


# ---- 摘要 ----


def test_summary_counts_latest_row_per_stock(client_and_db) -> None:
    client, db = client_and_db
    _hold(db, "AAPL")
    _save_close(db, "AAPL", 90.0)
    _create(client, code="AAPL", action="watch")
    _create(client, code="AAPL", action="hold", stop_loss=100)
    _create(client, code="MSFT", action="buy")
    _create(client, code="NVDA", action="buy", stop_loss=100)  # 沒有收盤：無法判定

    body = client.get(SUMMARY_URL).json()
    assert body["total"] == 3
    assert body["held_count"] == 1
    assert body["actions"] == {"hold": 1, "buy": 2}
    assert body["stop_triggered_count"] == 1
    assert body["stop_price_unavailable_count"] == 1
    triggered = body["stop_triggered"][0]
    assert triggered["stock_code"] == "AAPL"
    assert triggered["is_held"] is True
    assert triggered["last_close"] == 90.0


def test_summary_route_is_not_swallowed_by_signal_id(client_and_db) -> None:
    client, _ = client_and_db
    assert client.get(SUMMARY_URL).status_code == 200


def test_summary_empty_when_holding_only_without_holdings(client_and_db) -> None:
    client, _ = client_and_db
    _create(client, code="AAPL", action="buy")

    body = client.get(SUMMARY_URL, params={"holding_only": "true"}).json()
    assert body["total"] == 0
    assert body["actions"] == {}


def test_summary_excludes_inactive_by_default(client_and_db) -> None:
    client, _ = client_and_db
    created = _create(client, code="AAPL", action="buy")
    client.patch(f"{LIST_URL}/{created['id']}/status", json={"status": "closed"})

    assert client.get(SUMMARY_URL).json()["total"] == 0


# ---- 訊號當時價 ----


def _report(db, price) -> int:
    with db.session_scope() as session:
        record = AnalysisHistory(
            query_id="q", code="AAPL", name="AAPL", report_type="simple",
            raw_result=json.dumps({"current_price": price}),
        )
        session.add(record)
        session.flush()
        return record.id


def test_signal_price_comes_from_source_report(client_and_db) -> None:
    client, db = client_and_db
    report_id = _report(db, 123.5)
    created = _create(client, source_type="analysis", source_report_id=report_id)

    listed = client.get(LIST_URL).json()["items"][0]
    assert listed["signal_price"] == 123.5
    assert client.get(f"{LIST_URL}/{created['id']}").json()["signal_price"] == 123.5
    grouped = client.get(LIST_URL, params={"group_latest": "true"}).json()["items"][0]
    assert grouped["signal_price"] == 123.5


@pytest.mark.parametrize("price", [None, 0, "n/a"])
def test_signal_price_is_null_for_unusable_report_values(client_and_db, price) -> None:
    client, db = client_and_db
    report_id = _report(db, price)
    _create(client, source_type="analysis", source_report_id=report_id)

    assert client.get(LIST_URL).json()["items"][0]["signal_price"] is None


def test_signal_price_is_null_without_source_report(client_and_db) -> None:
    client, _ = client_and_db
    _create(client)

    assert client.get(LIST_URL).json()["items"][0]["signal_price"] is None


# ---- 統計 ----


def test_outcome_aggregate_reports_neutral_outside_hit_rate() -> None:
    rows = [
        type("Row", (), {"eval_status": "completed", "outcome": outcome, "stock_return_pct": 1.0, "unable_reason": None})
        for outcome in ("hit", "miss", "neutral", "neutral")
    ]
    aggregate = DecisionSignalOutcomeService._aggregate(rows)
    assert aggregate["neutral"] == 2
    assert aggregate["hit_rate_pct"] == 50.0  # 中性不進分母
