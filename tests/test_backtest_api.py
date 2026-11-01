# -*- coding: utf-8 -*-
"""回測未到期分流、列表參數與累計序列。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager
from src.config import Config, get_config
from src.core.backtest_engine import forward_window_calendar_days
from src.repositories.backtest_repo import maturity_status
from src.services.backtest_service import BacktestService
from src.storage import AnalysisHistory, BacktestResult, DatabaseManager

WINDOW = 10


class MaturityStatusTestCase(unittest.TestCase):
    today = date(2099, 6, 30)

    def test_insufficient_inside_window_is_pending(self):
        recent = self.today - timedelta(days=1)
        self.assertEqual(maturity_status("insufficient_data", recent, WINDOW, self.today), "pending")

    def test_insufficient_after_window_stays_insufficient(self):
        old = self.today - timedelta(days=forward_window_calendar_days(WINDOW) + 1)
        self.assertEqual(maturity_status("insufficient_data", old, WINDOW, self.today), "insufficient_data")

    def test_boundary_day_is_no_longer_pending(self):
        edge = self.today - timedelta(days=forward_window_calendar_days(WINDOW))
        self.assertEqual(maturity_status("insufficient_data", edge, WINDOW, self.today), "insufficient_data")

    def test_other_statuses_pass_through(self):
        recent = self.today - timedelta(days=1)
        self.assertEqual(maturity_status("completed", recent, WINDOW, self.today), "completed")
        self.assertEqual(maturity_status("error", recent, WINDOW, self.today), "error")

    def test_missing_analysis_date_is_insufficient(self):
        self.assertEqual(maturity_status("insufficient_data", None, WINDOW, self.today), "insufficient_data")


class BacktestListApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._saved_env = {key: os.environ.get(key) for key in ("ENV_FILE", "DATABASE_PATH")}
        env_path = os.path.join(self._temp_dir.name, ".env")
        with open(env_path, "w", encoding="utf-8") as env_file:
            env_file.write("STOCK_LIST=600519\n")
        os.environ["ENV_FILE"] = env_path
        os.environ["DATABASE_PATH"] = os.path.join(self._temp_dir.name, "backtest_api.db")
        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.engine_version = BacktestService._engine_version(get_config())
        self.today = date.today()
        self.old = self.today - timedelta(days=forward_window_calendar_days(WINDOW) + 5)
        self.recent = self.today - timedelta(days=2)
        self.client_app = create_app(static_dir=Path(self._temp_dir.name))
        self.client_app.dependency_overrides[get_database_manager] = lambda: self.db
        self.client = TestClient(self.client_app)

        self._add(1, "2330.TW", "completed", self.old, simulated=5.0, outcome="win", raw={"action": "buy"})
        self._add(2, "AAPL", "completed", self.old - timedelta(days=1), simulated=-2.0, outcome="loss",
                  raw={"action": "sell"})
        self._add(3, "2317.TW", "insufficient_data", self.recent)
        self._add(4, "6488.TWO", "insufficient_data", self.old)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config._instance = None
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._temp_dir.cleanup()

    def _add(self, history_id, code, status, analysis_date, simulated=None, outcome=None, raw=None):
        with self.db.get_session() as session:
            session.add(AnalysisHistory(
                id=history_id,
                query_id=f"q{history_id}",
                code=code,
                name=code,
                report_type="simple",
                sentiment_score=50,
                operation_advice="",
                trend_prediction="",
                analysis_summary="",
                raw_result=json.dumps(raw or {}),
                created_at=datetime.combine(analysis_date, datetime.min.time()),
            ))
            session.flush()
            session.add(BacktestResult(
                analysis_history_id=history_id,
                code=code,
                analysis_date=analysis_date,
                eval_window_days=WINDOW,
                engine_version=self.engine_version,
                eval_status=status,
                simulated_return_pct=simulated,
                outcome=outcome,
            ))
            session.commit()

    def _results(self, **params):
        response = self.client.get("/api/v1/backtest/results", params={"eval_window_days": WINDOW, **params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_pending_and_insufficient_are_separate(self):
        pending = self._results(status="pending")
        self.assertEqual([item["code"] for item in pending["items"]], ["2317.TW"])
        self.assertEqual(pending["total"], 1)
        self.assertEqual(pending["items"][0]["maturity_status"], "pending")
        self.assertEqual(pending["items"][0]["eval_status"], "insufficient_data")  # 舊欄位不變
        self.assertIsNotNone(pending["items"][0]["matures_by"])

        insufficient = self._results(status="insufficient_data")
        self.assertEqual([item["code"] for item in insufficient["items"]], ["6488.TWO"])
        self.assertIsNone(insufficient["items"][0]["matures_by"])

    def test_status_counts_ignore_the_selected_status(self):
        counts = self._results(status="pending")["status_counts"]
        self.assertEqual(counts, {"completed": 2, "pending": 1, "insufficient_data": 1})

    def test_default_sort_puts_completed_first(self):
        statuses = [item["eval_status"] for item in self._results()["items"]]
        self.assertEqual(statuses[:2], ["completed", "completed"])
        # 反向：明確要日期排序時，最新的未到期列排最前面。
        by_date = self._results(sort="date_desc")["items"]
        self.assertEqual(by_date[0]["code"], "2317.TW")

    def test_tool_callers_keep_latest_first_without_sort(self):
        data = BacktestService(self.db).get_recent_evaluations(code=None, eval_window_days=WINDOW)
        self.assertEqual(data["items"][0]["code"], "2317.TW")
        self.assertNotIn("status_counts", data)

    def test_return_sort_keeps_missing_returns_last(self):
        items = self._results(sort="return_desc")["items"]
        self.assertEqual([item["code"] for item in items[:2]], ["2330.TW", "AAPL"])
        ascending = self._results(sort="return_asc")["items"]
        self.assertEqual([item["code"] for item in ascending[:2]], ["AAPL", "2330.TW"])

    def test_market_filter(self):
        tw = {item["code"] for item in self._results(market="tw")["items"]}
        self.assertEqual(tw, {"2330.TW", "2317.TW", "6488.TWO"})
        us = {item["code"] for item in self._results(market="us")["items"]}
        self.assertEqual(us, {"AAPL"})
        self.assertEqual(self._results(market="cn")["total"], 0)

    def test_advice_filter_uses_structured_action_and_correct_total(self):
        buy = self._results(advice="buy", limit=1)
        self.assertEqual(buy["total"], 1)
        self.assertEqual(buy["items"][0]["code"], "2330.TW")
        self.assertEqual(buy["items"][0]["action"], "buy")
        # status_counts 在逐列判斷的路徑也要有。
        self.assertEqual(buy["status_counts"]["completed"], 2)

    def test_invalid_params_are_rejected(self):
        for params in ({"status": "nope"}, {"sort": "nope"}, {"market": "nope"}, {"advice": "nope"}):
            response = self.client.get("/api/v1/backtest/results", params=params)
            self.assertEqual(response.status_code, 422, params)

    def test_series_accumulates_completed_rows_oldest_first(self):
        response = self.client.get("/api/v1/backtest/series", params={"eval_window_days": WINDOW})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["chart_title"], "逐筆累計（非資金曲線）")
        self.assertEqual([point["code"] for point in body["points"]], ["AAPL", "2330.TW"])
        self.assertEqual([point["cumulative_return_pct"] for point in body["points"]], [-2.0, 3.0])
        self.assertEqual(body["points"][0]["date"], (self.old - timedelta(days=1)).isoformat())
        self.assertFalse(body["truncated"])

    def test_series_market_filter(self):
        response = self.client.get("/api/v1/backtest/series", params={"eval_window_days": WINDOW, "market": "us"})
        self.assertEqual([point["code"] for point in response.json()["points"]], ["AAPL"])


class _Row:
    def __init__(self, day, outcome, value, net=None):
        self.analysis_date = day
        self.outcome = outcome
        self.simulated_return_pct = value
        self.simulated_net_return_pct = net
        self.analysis_history_id = 1
        self.code = "2330.TW"


class BuildSeriesTestCase(unittest.TestCase):
    def test_monthly_win_rate_excludes_neutral_from_denominator(self):
        rows = [
            _Row(date(2099, 1, 2), "win", 1.0),
            _Row(date(2099, 1, 3), "loss", -1.0),
            _Row(date(2099, 1, 4), "neutral", 0.0),
            _Row(date(2099, 2, 1), "neutral", 0.0),
        ]
        monthly = BacktestService._build_series(rows)["monthly"]
        self.assertEqual(monthly[0]["win_rate_pct"], 50.0)
        self.assertEqual(monthly[0]["completed"], 3)
        # 沒有勝負是沒有讀數，不是 0%。
        self.assertIsNone(monthly[1]["win_rate_pct"])

    def test_net_return_is_preferred_and_non_finite_is_skipped(self):
        rows = [
            _Row(date(2099, 1, 2), "win", 2.0, net=1.5),
            _Row(date(2099, 1, 3), "win", float("nan")),
            _Row(date(2099, 1, 4), "loss", None),
            _Row(date(2099, 1, 5), "win", 1.0),
        ]
        result = BacktestService._build_series(rows)
        self.assertEqual([p["cumulative_return_pct"] for p in result["points"]], [1.5, 2.5])
        self.assertEqual(result["monthly"][0]["completed"], 4)


if __name__ == "__main__":
    unittest.main()
