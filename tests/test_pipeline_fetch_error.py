# -*- coding: utf-8 -*-
"""Regression tests for pipeline data-fetch error handling."""

from datetime import date, datetime, timezone
import unittest
from unittest.mock import MagicMock, patch

from src.core.pipeline import StockAnalysisPipeline


class PipelineFetchErrorTestCase(unittest.TestCase):
    """`fetch_and_save_stock_data` should preserve the original exception."""

    def test_fetch_and_save_handles_stock_name_lookup_failure(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.db = MagicMock()
        pipeline.fetcher_manager.get_stock_name.side_effect = RuntimeError("name lookup failed")

        success, error = StockAnalysisPipeline.fetch_and_save_stock_data(pipeline, "600519")

        self.assertFalse(success)
        self.assertIn("name lookup failed", error or "")

    @patch.object(
        StockAnalysisPipeline,
        "_resolve_resume_target_date",
        return_value=date(2026, 3, 27),
    )
    def test_fetch_and_save_uses_effective_trading_date_for_resume_check(self, _mock_target):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.db = MagicMock()
        pipeline.fetcher_manager.get_stock_name.return_value = "贵州茅台"
        pipeline.db.has_today_data.return_value = True
        current_time = datetime(2026, 3, 28, 1, 0, tzinfo=timezone.utc)

        success, error = StockAnalysisPipeline.fetch_and_save_stock_data(
            pipeline,
            "600519",
            current_time=current_time,
        )

        self.assertTrue(success)
        self.assertIsNone(error)
        _mock_target.assert_called_once_with(
            "600519", current_time=current_time, analysis_target=None
        )
        pipeline.db.has_today_data.assert_called_once_with("600519", date(2026, 3, 27))
        pipeline.fetcher_manager.get_daily_data.assert_not_called()

    def _fetch_with_latest_bar(self, latest: date):
        import pandas as pd

        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.db = MagicMock()
        pipeline.fetcher_manager.get_stock_name.return_value = "NVIDIA"
        pipeline.db.has_today_data.return_value = False
        pipeline.db.save_daily_data.return_value = 1
        df = pd.DataFrame({"date": pd.to_datetime([date(2026, 10, 19), latest]), "close": [1.0, 2.0]})
        pipeline.fetcher_manager.get_daily_data.return_value = (df, "YfinanceFetcher")
        with patch.object(
            StockAnalysisPipeline, "_resolve_resume_target_date", return_value=date(2026, 10, 21)
        ), self.assertLogs("src.core.pipeline", level="INFO") as logs:
            success, error = StockAnalysisPipeline.fetch_and_save_stock_data(pipeline, "NVDA")
        self.assertTrue(success)
        self.assertIsNone(error)
        return [line for line in logs.output if "日线落后" in line]

    def test_fetch_and_save_warns_when_source_lags_target_session(self):
        # 2026-10-22 紐約盤前：應有 10-21，Yahoo 只給到 10-20，原本完全沒有訊號。
        lag_lines = self._fetch_with_latest_bar(date(2026, 10, 20))
        self.assertEqual(len(lag_lines), 1)
        self.assertIn("WARNING", lag_lines[0])
        self.assertIn("2026-10-20", lag_lines[0])

    def test_fetch_and_save_does_not_warn_when_target_session_present(self):
        self.assertEqual(self._fetch_with_latest_bar(date(2026, 10, 21)), [])

    def test_resolve_resume_target_date_normalizes_supported_a_share_formats(self):
        with patch("src.core.pipeline.get_market_for_stock", return_value="cn") as mock_market, patch(
            "src.core.pipeline.get_effective_trading_date",
            return_value=date(2026, 3, 27),
        ) as mock_target:
            for code in ("SH600519", "000001.SZ", "BJ920748"):
                result = StockAnalysisPipeline._resolve_resume_target_date(code)
                self.assertEqual(result, date(2026, 3, 27))

        self.assertEqual(
            [args.args[0] for args in mock_market.call_args_list],
            ["600519", "000001", "920748"],
        )
        self.assertEqual(mock_target.call_count, 3)


if __name__ == "__main__":
    unittest.main()
