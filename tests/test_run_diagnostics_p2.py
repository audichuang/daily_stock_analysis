# -*- coding: utf-8 -*-
"""Regression tests for #1391 Phase 2 run diagnostic summaries."""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace

from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.v1.endpoints.history import get_history_diagnostics
from src.services.history_service import HistoryService
from src.services.run_diagnostics import build_run_diagnostic_summary


def _diagnostic_snapshot() -> dict:
    return {
        "trace_id": "trace-p2",
        "task_id": "task-p2",
        "query_id": "query-p2",
        "stock_code": "600519",
        "trigger_source": "api",
        "provider_runs": [
            {
                "trace_id": "trace-p2",
                "data_type": "realtime_quote",
                "provider": "FirstQuote",
                "operation": "get_realtime_quote",
                "success": False,
                "error_type": "TimeoutError",
                "error_message_sanitized": "token=<redacted>",
                "fallback_to": "SecondQuote",
            },
            {
                "trace_id": "trace-p2",
                "data_type": "realtime_quote",
                "provider": "SecondQuote",
                "operation": "get_realtime_quote",
                "success": True,
            },
            {
                "trace_id": "trace-p2",
                "data_type": "daily_data",
                "provider": "DailyFetcher",
                "operation": "get_daily_data",
                "success": True,
                "record_count": 30,
            },
        ],
        "llm_runs": [
            {
                "trace_id": "trace-p2",
                "model": "deepseek-chat",
                "call_type": "analysis",
                "success": True,
                "tokens": 1234,
            }
        ],
        "notification_runs": [
            {
                "trace_id": "trace-p2",
                "channel": "wechat",
                "status": "success",
                "success": True,
            }
        ],
        "history_runs": [
            {
                "trace_id": "trace-p2",
                "report_saved": True,
                "metadata_saved": True,
            }
        ],
    }


def _history_record(*, context_snapshot: dict | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        query_id="query-p2",
        code="600519",
        name="贵州茅台",
        report_type="detailed",
        created_at=datetime(2026, 5, 24, 12, 0, 0),
        raw_result=json.dumps(
            {
                "success": True,
                "model_used": "deepseek-chat",
                "analysis_summary": "测试摘要",
                "news_summary": "新闻摘要",
            },
            ensure_ascii=False,
        ),
        context_snapshot=(
            json.dumps(context_snapshot, ensure_ascii=False)
            if context_snapshot is not None
            else None
        ),
        sentiment_score=60,
        operation_advice="持有",
        trend_prediction="看多",
        analysis_summary="测试摘要",
        news_content="新闻摘要",
        ideal_buy=None,
        secondary_buy=None,
        stop_loss=None,
        take_profit=None,
    )


class _FakeHistoryDb:
    def __init__(self, record: SimpleNamespace | None):
        self.record = record

    def get_analysis_history_by_id(self, record_id: int):
        return self.record if record_id == 1 else None

    def get_latest_analysis_by_query_id(self, query_id: str):
        return self.record if query_id == "query-p2" else None


class _FailingHistoryDb:
    def get_analysis_history_by_id(self, record_id: int):
        raise RuntimeError("database unavailable")

    def get_latest_analysis_by_query_id(self, query_id: str):
        raise RuntimeError("database unavailable")


class RunDiagnosticsP2TestCase(unittest.TestCase):
    def test_summary_classifies_provider_fallback_as_degraded_and_copy_text_is_sanitized(self) -> None:
        summary = build_run_diagnostic_summary(
            context_snapshot={
                "diagnostics": _diagnostic_snapshot(),
                "news_content": "新闻摘要",
            },
            raw_result={
                "success": True,
                "model_used": "deepseek-chat",
                "analysis_summary": "测试摘要",
            },
            report_saved=True,
        )

        self.assertEqual(summary["status"], "degraded")
        self.assertEqual(summary["status_label"], "部分降级")
        self.assertEqual(summary["components"]["realtime_quote"]["status"], "degraded")
        self.assertEqual(summary["components"]["daily_data"]["status"], "ok")
        self.assertEqual(summary["components"]["llm"]["status"], "ok")
        self.assertEqual(summary["components"]["notification"]["status"], "ok")
        self.assertIn("trace_id: trace-p2", summary["copy_text"])
        self.assertNotIn("secret", summary["copy_text"])

    def test_summary_marks_llm_failure_as_failed(self) -> None:
        diagnostics = _diagnostic_snapshot()
        diagnostics["llm_runs"] = [
            {
                "trace_id": "trace-p2",
                "model": "deepseek-chat",
                "success": False,
                "error_type": "RuntimeError",
                "error_message_sanitized": "api_key=<redacted>",
            }
        ]

        summary = build_run_diagnostic_summary(
            context_snapshot={
                "diagnostics": diagnostics,
                "news_content": "新闻摘要",
            },
            raw_result={"success": False, "error_message": "api_key=secret-value"},
            report_saved=True,
        )

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["components"]["llm"]["status"], "failed")
        self.assertNotIn("secret-value", summary["copy_text"])

    def test_legacy_report_without_diagnostics_returns_unknown(self) -> None:
        summary = build_run_diagnostic_summary(
            context_snapshot={"news_content": "legacy news"},
            raw_result={"success": True, "model_used": "deepseek-chat"},
            report_saved=True,
            query_id="legacy-query",
            stock_code="600519",
        )

        self.assertEqual(summary["status"], "unknown")
        self.assertEqual(summary["status_label"], "未知")
        self.assertEqual(summary["query_id"], "legacy-query")

    def test_history_service_and_endpoint_return_diagnostic_summary(self) -> None:
        context_snapshot = {
            "diagnostics": _diagnostic_snapshot(),
            "news_content": "新闻摘要",
        }
        db = _FakeHistoryDb(_history_record(context_snapshot=context_snapshot))

        service_summary = HistoryService(db).resolve_and_get_diagnostics("1")
        endpoint_summary = get_history_diagnostics("1", db_manager=db)

        self.assertIsNotNone(service_summary)
        self.assertEqual(service_summary["trace_id"], "trace-p2")
        self.assertEqual(endpoint_summary.trace_id, "trace-p2")
        self.assertIn("realtime_quote", endpoint_summary.components)

    def test_history_service_returns_unknown_for_legacy_record(self) -> None:
        db = _FakeHistoryDb(_history_record(context_snapshot=None))

        summary = HistoryService(db).resolve_and_get_diagnostics("1")

        self.assertIsNotNone(summary)
        self.assertEqual(summary["status"], "unknown")
        self.assertIn("copy_text", summary)

    def test_history_diagnostics_endpoint_surfaces_lookup_errors(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            get_history_diagnostics("1", db_manager=_FailingHistoryDb())

        self.assertEqual(ctx.exception.status_code, 500)

    def test_history_diagnostics_endpoint_surfaces_malformed_payloads(self) -> None:
        record = _history_record(context_snapshot=None)
        record.context_snapshot = "{invalid-json"
        db = _FakeHistoryDb(record)

        with self.assertRaises(ValueError):
            HistoryService(db).resolve_and_get_diagnostics("1")
        with self.assertRaises(HTTPException) as ctx:
            get_history_diagnostics("1", db_manager=db)

        self.assertEqual(ctx.exception.status_code, 500)


if __name__ == "__main__":
    unittest.main()
