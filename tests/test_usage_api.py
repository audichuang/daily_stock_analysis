# -*- coding: utf-8 -*-
"""Tests for LLM usage dashboard API."""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager
from api.v1.endpoints import usage as usage_endpoint
from src.services import llm_usage_analytics as analytics


class FakeUsageDbManager:
    def get_llm_usage_summary(self, from_dt, to_dt):
        return {
            "total_calls": 2,
            "total_prompt_tokens": 30,
            "total_completion_tokens": 70,
            "total_tokens": 100,
            "by_call_type": [
                {
                    "call_type": "analysis",
                    "calls": 2,
                    "prompt_tokens": 30,
                    "completion_tokens": 70,
                    "total_tokens": 100,
                }
            ],
            "by_model": [
                {
                    "model": "openai/gpt-test",
                    "calls": 2,
                    "prompt_tokens": 30,
                    "completion_tokens": 70,
                    "total_tokens": 100,
                    "max_total_tokens": 60,
                }
            ],
        }

    def get_llm_usage_breakdown(self, from_dt, to_dt):
        return []

    def count_llm_usage_records(self, from_dt, to_dt, call_type=None):
        return 1

    def get_llm_usage_records(self, from_dt, to_dt, limit=50, offset=0, call_type=None, sort="newest"):
        return [
            {
                "id": 7,
                "called_at": datetime(2026, 6, 11, 9, 30, 0),
                "call_type": "analysis",
                "model": "openai/gpt-test",
                "stock_code": "600519",
                "provider": "openai",
                "language": "zh",
                "market_group": "cn",
                "analysis_mode": "stock_analysis",
                "legacy_prompt_mode": "skill_aware",
                "skill_config_hmac": "a" * 64,
                "transport": "litellm",
                "message_count": 2,
                "estimated_total_prompt_tokens": 2000,
                "approx_common_prefix_chars": 120,
                "approx_common_prefix_tokens": 40,
                "known_dynamic_marker_positions": '[{"marker_name":"stock_code","message_role":"user","char_offset":12}]',
                "prompt_tokens": 10,
                "completion_tokens": 50,
                "total_tokens": 60,
            }
        ]


class UsageDashboardApiTestCase(unittest.TestCase):
    def test_dashboard_returns_token_summary_and_recent_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(static_dir=Path(temp_dir))
            app.dependency_overrides[get_database_manager] = lambda: FakeUsageDbManager()
            client = TestClient(app)

            response = client.get("/api/v1/usage/dashboard?period=today&limit=10")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["period"], "today")
        self.assertEqual(body["total_tokens"], 100)
        self.assertEqual(body["by_model"][0]["model"], "openai/gpt-test")
        self.assertEqual(body["by_model"][0]["max_total_tokens"], 60)
        self.assertNotIn("provider", body["by_model"][0])
        self.assertNotIn("context_window", body["by_model"][0])
        self.assertNotIn("context_usage_ratio", body["by_model"][0])
        self.assertEqual(body["recent_calls"][0]["stock_code"], "600519")
        p05a_internal_fields = {
            "provider",
            "language",
            "market_group",
            "analysis_mode",
            "legacy_prompt_mode",
            "skill_config_hmac",
            "transport",
            "message_count",
            "estimated_total_prompt_tokens",
            "approx_common_prefix_chars",
            "approx_common_prefix_tokens",
            "known_dynamic_marker_positions",
        }
        self.assertTrue(p05a_internal_fields.isdisjoint(body["recent_calls"][0]))
        self.assertNotIn("context_window", body["recent_calls"][0])
        self.assertNotIn("context_usage_ratio", body["recent_calls"][0])
        # channel 是追加欄位；provider／transport 原欄位仍不外露。
        self.assertEqual(body["recent_calls"][0]["channel"], "litellm")
        self.assertEqual(body["recent_calls"][0]["billing"], "metered")
        self.assertEqual(body["recent_total"], 1)

    def test_dashboard_day_narrows_records_but_keeps_period_totals(self):
        seen = {}

        class RecordingDb(FakeUsageDbManager):
            def get_llm_usage_records(self, from_dt, to_dt, **kwargs):
                seen["records"] = (from_dt, to_dt)
                return super().get_llm_usage_records(from_dt, to_dt, **kwargs)

            def count_llm_usage_records(self, from_dt, to_dt, **kwargs):
                seen["count"] = (from_dt, to_dt)
                return super().count_llm_usage_records(from_dt, to_dt, **kwargs)

            def get_llm_usage_summary(self, from_dt, to_dt, **kwargs):
                seen["summary"] = (from_dt, to_dt)
                return super().get_llm_usage_summary(from_dt, to_dt, **kwargs)

        # 全部期間的上界是現在，取昨天才不會被上界夾住。
        day = (datetime.now() - timedelta(days=1)).date()
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(static_dir=Path(temp_dir))
            app.dependency_overrides[get_database_manager] = lambda: RecordingDb()
            response = TestClient(app).get(f"/api/v1/usage/dashboard?period=all&day={day.isoformat()}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["records"][0].date(), day)
        self.assertEqual(seen["records"][1].date(), day)
        self.assertEqual(seen["records"], seen["count"])
        self.assertEqual(seen["summary"][0].year, 2000)

    def test_dashboard_rejects_invalid_day(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(static_dir=Path(temp_dir))
            app.dependency_overrides[get_database_manager] = lambda: FakeUsageDbManager()
            response = TestClient(app).get("/api/v1/usage/dashboard?day=not-a-date")
        self.assertEqual(response.status_code, 422)

    def test_dashboard_rejects_unknown_sort(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(static_dir=Path(temp_dir))
            app.dependency_overrides[get_database_manager] = lambda: FakeUsageDbManager()
            response = TestClient(app).get("/api/v1/usage/dashboard?sort=random")
        self.assertEqual(response.status_code, 422)


def _row(day="2099-01-02", model="m", transport="litellm", prompt=1000, completion=500, cache=0, known=0, calls=1):
    return {
        "day": day,
        "model": model,
        "provider": None,
        "transport": transport,
        "calls": calls,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "cache_read_tokens": cache,
        "cache_known_prompt_tokens": known,
    }


class UsageAnalyticsTestCase(unittest.TestCase):
    def test_no_price_means_null_not_zero(self):
        cost = analytics.build_cost([_row()], {})
        self.assertIsNone(cost["estimated_total"])
        self.assertFalse(cost["complete"])
        self.assertEqual(cost["unpriced_models"], ["m"])

    def test_price_applies_cache_rate_to_cached_prompt_only(self):
        prices = {"m": {"input": 10.0, "output": 20.0, "cache_read": 1.0}}
        cost = analytics.build_cost([_row(cache=400, known=1000)], prices)
        expected = (600 * 10 + 400 * 1 + 500 * 20) / 1_000_000
        self.assertAlmostEqual(cost["estimated_total"], expected)
        self.assertTrue(cost["complete"])

    def test_missing_cache_price_falls_back_to_input_rate(self):
        prices = {"m": {"input": 10.0, "output": 0.0}}
        cost = analytics.build_cost([_row(cache=400, known=1000)], prices)
        self.assertAlmostEqual(cost["estimated_total"], 1000 * 10 / 1_000_000)

    def test_price_matches_with_or_without_provider_prefix(self):
        prices = {"sonnet": {"input": 1.0, "output": 1.0}}
        cost = analytics.build_cost([_row(model="anthropic/Sonnet")], prices)
        self.assertIsNotNone(cost["estimated_total"])

    def test_subscription_path_is_marked_and_never_priced(self):
        prices = {"claude_code_cli": {"input": 10.0, "output": 10.0}}
        rows = [_row(model="claude_code_cli", transport="claude_code_cli")]
        cost = analytics.build_cost(rows, prices)
        self.assertEqual(cost["by_model"][0]["billing"], "subscription")
        self.assertIsNone(cost["estimated_total"])
        # 訂閱路徑不算缺單價。
        self.assertTrue(cost["complete"])
        self.assertEqual(cost["subscription_tokens"], 1500)

    def test_partial_prices_report_incomplete_total(self):
        prices = {"priced": {"input": 1.0, "output": 1.0}}
        cost = analytics.build_cost([_row(model="priced"), _row(model="other")], prices)
        self.assertIsNotNone(cost["estimated_total"])
        self.assertFalse(cost["complete"])
        self.assertEqual(cost["unpriced_models"], ["other"])

    def test_invalid_price_settings_do_not_raise(self):
        self.assertEqual(analytics.load_prices(""), {})
        self.assertEqual(analytics.load_prices("{not json"), {})
        self.assertEqual(analytics.load_prices("[1]"), {})
        self.assertEqual(analytics.load_prices('{"m":{"input":1}}'), {})
        self.assertEqual(analytics.load_prices('{"m":{"input":-1,"output":1}}'), {})
        self.assertEqual(analytics.load_prices('{"M":{"input":1,"output":2}}'), {"m": {"input": 1.0, "output": 2.0}})

    def test_cache_hit_ratio_ignores_calls_without_cache_report(self):
        result = analytics.build_analytics([_row(cache=250, known=1000), _row(day="2099-01-03")], {})
        self.assertEqual(result["cache"]["hit_ratio"], 0.25)
        self.assertIsNone(analytics.build_analytics([_row()], {})["cache"]["hit_ratio"])

    def test_by_day_is_sorted_and_summed(self):
        result = analytics.build_analytics(
            [_row(day="2099-01-03"), _row(day="2099-01-02"), _row(day="2099-01-02", model="n")], {},
        )
        self.assertEqual([item["date"] for item in result["by_day"]], ["2099-01-02", "2099-01-03"])
        self.assertEqual(result["by_day"][0]["calls"], 2)
        self.assertEqual(result["by_day"][0]["total_tokens"], 3000)

    def test_change_pct_is_null_without_previous_reading(self):
        previous = analytics.build_previous(
            from_date="a", to_date="b", current={"total_calls": 3, "total_tokens": 30},
            current_cost=None, previous_rows=[], prices={},
        )
        self.assertIsNone(previous["calls_change_pct"])
        self.assertEqual(previous["total_calls"], 0)
        compared = analytics.build_previous(
            from_date="a", to_date="b", current={"total_calls": 2, "total_tokens": 3000},
            current_cost=None, previous_rows=[_row()], prices={},
        )
        self.assertEqual(compared["calls_change_pct"], 100.0)
        self.assertEqual(compared["tokens_change_pct"], 100.0)


class UsagePreviousRangeTestCase(unittest.TestCase):
    def test_today_shifts_one_day(self):
        now = datetime(2099, 3, 2, 10, 0)
        start, end = usage_endpoint._previous_range("today", now.replace(hour=0), now)
        self.assertEqual((start.day, end.day, end.hour), (1, 1, 10))

    def test_month_clamps_to_previous_month_end(self):
        now = datetime(2099, 3, 31, 10, 0)
        start, end = usage_endpoint._previous_range("month", now.replace(day=1), now)
        self.assertEqual((start.month, start.day), (2, 1))
        self.assertEqual((end.month, end.day), (2, 28))

    def test_january_wraps_year_and_all_has_no_previous(self):
        now = datetime(2099, 1, 15)
        start, _ = usage_endpoint._previous_range("month", now.replace(day=1), now)
        self.assertEqual((start.year, start.month), (2098, 12))
        self.assertIsNone(usage_endpoint._previous_range("all", datetime(2000, 1, 1), now))


if __name__ == "__main__":
    unittest.main()
