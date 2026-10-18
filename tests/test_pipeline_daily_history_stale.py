# -*- coding: utf-8 -*-
"""T19：台股日線歷史落後已收盤場次時，pipeline 在 context 標 daily_history_stale。"""

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.core.pipeline import StockAnalysisPipeline, _mark_daily_history_staleness

_TPE = ZoneInfo("Asia/Taipei")


def _tw(day, hh, mm):
    return datetime(2026, 10, day, hh, mm, tzinfo=_TPE)


def _ctx(last_date):
    return {"code": "2330.TW", "date": last_date, "today": {"close": 1.0}, "yesterday": {"close": 1.0}}


class MarkDailyHistoryStalenessTestCase(unittest.TestCase):
    def test_after_close_crawler_stuck_is_flagged(self):
        ctx = _ctx("2026-10-13")
        _mark_daily_history_staleness(ctx, "tw", _tw(16, 18, 30))
        self.assertEqual(
            ctx["daily_history_stale"],
            {"last_date": "2026-10-13", "expected": "2026-10-16", "missing_sessions": 3},
        )

    def test_just_after_close_before_crawl_tolerates_one_session(self):
        ctx = _ctx("2026-10-15")
        _mark_daily_history_staleness(ctx, "tw", _tw(16, 14, 0))
        self.assertNotIn("daily_history_stale", ctx)

    def test_just_after_close_two_sessions_behind_is_flagged(self):
        ctx = _ctx("2026-10-14")
        _mark_daily_history_staleness(ctx, "tw", _tw(16, 14, 0))
        self.assertEqual(ctx["daily_history_stale"]["missing_sessions"], 2)

    def test_intraday_one_session_behind_is_flagged_no_tolerance(self):
        # 10:30 effective 是 10-15（昨天收盤），不是「剛收盤」→ 容忍 0
        ctx = _ctx("2026-10-14")
        _mark_daily_history_staleness(ctx, "tw", _tw(16, 10, 30))
        self.assertEqual(
            ctx["daily_history_stale"],
            {"last_date": "2026-10-14", "expected": "2026-10-15", "missing_sessions": 1},
        )

    def test_intraday_up_to_date_not_flagged(self):
        ctx = _ctx("2026-10-15")
        _mark_daily_history_staleness(ctx, "tw", _tw(16, 10, 30))
        self.assertNotIn("daily_history_stale", ctx)

    def test_weekend_one_session_behind_is_flagged(self):
        # 週日 effective 10-16 != 市場今天 10-18 → 容忍 0
        ctx = _ctx("2026-10-15")
        _mark_daily_history_staleness(ctx, "tw", _tw(18, 12, 0))
        self.assertEqual(ctx["daily_history_stale"]["missing_sessions"], 1)

    def test_calendar_unavailable_does_not_flag_or_raise(self):
        ctx = _ctx("2026-10-01")
        with patch("src.core.pipeline.count_missing_sessions", return_value=None):
            _mark_daily_history_staleness(ctx, "tw", _tw(16, 18, 30))
        self.assertNotIn("daily_history_stale", ctx)

    def test_bad_date_or_missing_data_does_not_raise(self):
        for ctx in ({"date": "not-a-date"}, {"date": None}, {"data_missing": True, "date": "2026-10-01"}):
            _mark_daily_history_staleness(ctx, "tw", _tw(16, 18, 30))
            self.assertNotIn("daily_history_stale", ctx)


class ContextEntryPointTestCase(unittest.TestCase):
    """:803（一般分析）與 :1803（Agent pack）兩個呼叫點共用的入口函式。"""

    @staticmethod
    def _pipeline(stored_context):
        p = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        p.db = SimpleNamespace(get_analysis_context=lambda code: dict(stored_context))
        return p

    def test_tw_entry_sets_flag_and_agent_loader_sees_it(self):
        p = self._pipeline(_ctx("2026-10-13"))
        with patch("src.core.pipeline.count_missing_sessions", return_value=3), \
                patch("src.core.pipeline.get_effective_trading_date") as eff, \
                patch("src.core.pipeline.get_market_now") as now:
            eff.return_value = datetime(2026, 10, 16).date()
            now.return_value = _tw(16, 18, 30)
            direct = p._get_analysis_context_with_market_fallback("2330.TW")
            via_agent = p._load_agent_analysis_context("2330.TW", "台積電")
        self.assertEqual(direct["daily_history_stale"]["missing_sessions"], 3)
        self.assertEqual(via_agent["daily_history_stale"]["missing_sessions"], 3)

    def test_non_tw_is_never_flagged(self):
        p = self._pipeline({"code": "AAPL", "date": "2020-01-01", "today": {}, "yesterday": {}})
        with patch("src.core.pipeline.count_missing_sessions", return_value=99):
            ctx = p._get_analysis_context_with_market_fallback("AAPL")
        self.assertNotIn("daily_history_stale", ctx)


if __name__ == "__main__":
    unittest.main()
