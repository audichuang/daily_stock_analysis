from __future__ import annotations

import builtins
import sys
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, call, patch

import main
from src.brokers.futu.portfolio import FutuPortfolioError
from src.services.runtime_scheduler import RuntimeSchedulerService


class MainPortfolioTest(unittest.TestCase):
    def test_parse_arguments_accepts_futu_portfolio(self):
        with patch.object(sys, "argv", ["main.py", "--portfolio", "FUTU"]):
            args = main.parse_arguments()

        self.assertEqual(args.portfolio, "futu")

    def test_resolve_portfolio_stock_codes_uses_futu_loader(self):
        args = SimpleNamespace(portfolio="futu")
        with patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=["aapl", "HK01810", "005930"],
        ) as loader, patch.object(
            main,
            "resolve_index_stock_code_for_analysis",
            side_effect=AssertionError("broker codes must not be remapped"),
        ):
            result = main._resolve_portfolio_stock_codes(args)

        self.assertEqual(result, ["AAPL", "HK01810", "005930"])
        loader.assert_called_once_with()

    def test_resolve_portfolio_stock_codes_returns_none_when_disabled(self):
        self.assertIsNone(main._resolve_portfolio_stock_codes(SimpleNamespace()))

    def test_analysis_lock_propagates_requested_portfolio_failures(self):
        config = SimpleNamespace()
        args = SimpleNamespace(portfolio="futu")
        error = FutuPortfolioError("OpenD unavailable")

        with patch.object(
            main,
            "run_full_analysis",
            side_effect=error,
        ) as runner, self.assertRaisesRegex(FutuPortfolioError, "OpenD unavailable"):
            main._run_analysis_with_runtime_scheduler_lock(
                config,
                args,
                ["600519"],
            )

        runner.assert_called_once_with(config, args, ["600519"])

    def test_run_full_analysis_propagates_futu_portfolio_load_failure(self):
        config = SimpleNamespace()
        args = SimpleNamespace(portfolio="futu")
        error = FutuPortfolioError("OpenD unavailable")

        with patch.object(
            main,
            "_refresh_stock_index_cache_for_analysis",
        ), patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            side_effect=error,
        ), self.assertRaisesRegex(FutuPortfolioError, "OpenD unavailable"):
            main.run_full_analysis(config, args)

    def test_run_full_analysis_keeps_downstream_failures_non_propagating(self):
        config = SimpleNamespace()
        args = SimpleNamespace(portfolio="futu")

        with patch.object(
            main,
            "_refresh_stock_index_cache_for_analysis",
        ), patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=["AAPL"],
        ), patch.object(
            main,
            "_compute_trading_day_filter",
            side_effect=RuntimeError("calendar unavailable"),
        ):
            result = main.run_full_analysis(config, args)

        self.assertFalse(result)

    def test_run_full_analysis_returns_false_when_stock_analysis_generates_no_reports(self):
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=False,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=False,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=(["600519"], "cn", False),
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager, patch.object(
            main,
            "_run_auto_backtest",
        ) as run_auto_backtest:
            feishu_manager.return_value.is_configured.return_value = False
            result = main.run_full_analysis(config, args, ["600519"])

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "no_report")
        pipeline.run.assert_called_once()
        run_auto_backtest.assert_called_once_with(config)

    def test_run_full_analysis_returns_false_when_stock_list_is_empty_without_market_review(self):
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=False,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            stock_list=[],
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=False,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            side_effect=AssertionError("empty STOCK_LIST must fail before trading-day filter"),
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
        ) as pipeline_cls, patch.object(
            main,
            "_run_auto_backtest",
        ) as run_auto_backtest:
            result = main.run_full_analysis(config, args)

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "empty_stock_list")
        pipeline_cls.assert_not_called()
        run_auto_backtest.assert_called_once_with(config)

    def test_run_full_analysis_returns_false_when_local_report_save_fails(self):
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=False,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=False,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )
        pipeline = MagicMock()
        pipeline.run.return_value = [
            SimpleNamespace(
                code="600519",
                success=True,
                sentiment_score=90,
                name="贵州茅台",
                operation_advice="持有",
                trend_prediction="震荡上行",
                get_emoji=MagicMock(return_value="📈"),
            )
        ]
        pipeline._last_local_report_path = None
        pipeline._last_local_report_error = "permission denied"

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=(["600519"], "cn", False),
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager, patch.object(
            main,
            "_run_auto_backtest",
        ) as run_auto_backtest:
            feishu_manager.return_value.is_configured.return_value = False
            result = main.run_full_analysis(config, args, ["600519"])

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "report_save_failed")
        pipeline.run.assert_called_once()
        run_auto_backtest.assert_called_once_with(config)

    def test_run_full_analysis_still_exports_feishu_doc_when_local_report_save_fails(self):
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=False,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=False,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
            report_type="simple",
        )
        result_item = SimpleNamespace(
            code="600519",
            success=True,
            sentiment_score=90,
            name="贵州茅台",
            operation_advice="持有",
            trend_prediction="震荡上行",
            get_emoji=MagicMock(return_value="📈"),
        )
        pipeline = MagicMock()
        pipeline.run.return_value = [result_item]
        pipeline._last_local_report_path = None
        pipeline._last_local_report_error = "permission denied"
        pipeline.notifier = MagicMock(
            generate_aggregate_report=MagicMock(return_value="dashboard")
        )

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=(["600519"], "cn", False),
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager, patch.object(
            main,
            "_run_auto_backtest",
        ) as run_auto_backtest:
            feishu_instance = feishu_manager.return_value
            feishu_instance.is_configured.return_value = True
            feishu_instance.create_daily_doc.return_value = "https://feishu.example/doc"

            result = main.run_full_analysis(config, args, ["600519"])

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "report_save_failed")
        pipeline.run.assert_called_once()
        pipeline.notifier.generate_aggregate_report.assert_called_once_with(
            [result_item],
            "simple",
        )
        feishu_instance.create_daily_doc.assert_called_once()
        _, doc_content = feishu_instance.create_daily_doc.call_args.args
        self.assertIn("# 🚀 个股决策仪表盘\n\ndashboard", doc_content)
        run_auto_backtest.assert_called_once_with(config)

    def test_run_full_analysis_still_sends_merged_notification_before_report_save_failure(self):
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=False,
            workers=1,
            dry_run=False,
            no_notify=False,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=True,
            market_review_enabled=True,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
            report_type="simple",
        )
        pipeline = MagicMock()
        pipeline.run.return_value = [
            SimpleNamespace(
                code="600519",
                success=True,
                sentiment_score=90,
                name="贵州茅台",
                operation_advice="持有",
                trend_prediction="震荡上行",
                get_emoji=MagicMock(return_value="📈"),
            )
        ]
        pipeline._last_local_report_path = None
        pipeline._last_local_report_error = "permission denied"
        pipeline.notifier = MagicMock(
            is_available=MagicMock(return_value=True),
            generate_aggregate_report=MagicMock(return_value="dashboard"),
            send=MagicMock(return_value=True),
        )

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=(["600519"], "cn", False),
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch.object(
            main,
            "_run_market_review_with_shared_lock",
            return_value=SimpleNamespace(report="market review"),
        ), patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager, patch.object(
            main,
            "_run_auto_backtest",
        ) as run_auto_backtest:
            feishu_manager.return_value.is_configured.return_value = False
            result = main.run_full_analysis(config, args, ["600519"])

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "report_save_failed")
        pipeline.notifier.send.assert_called_once()
        combined_content = pipeline.notifier.send.call_args.args[0]
        self.assertIn("# 📈 大盘复盘\n\nmarket review", combined_content)
        self.assertIn("# 🚀 个股决策仪表盘\n\ndashboard", combined_content)
        run_auto_backtest.assert_called_once_with(config)

    def test_run_full_analysis_returns_false_when_market_review_only_run_generates_no_report(self):
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=False,
            workers=1,
            dry_run=False,
            no_notify=True,
            schedule=True,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=True,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=([], "cn", False),
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch.object(
            main,
            "_run_market_review_with_shared_lock",
            return_value=None,
        ) as run_with_lock, patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager, patch.object(
            main,
            "_run_auto_backtest",
        ) as run_auto_backtest:
            feishu_manager.return_value.is_configured.return_value = False
            result = main.run_full_analysis(config, args, [])

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "no_report")
        pipeline.run.assert_called_once()
        run_with_lock.assert_called_once()
        run_auto_backtest.assert_called_once_with(config)

    def test_run_full_analysis_uses_futu_holdings_and_reloads_each_run(self):
        args = SimpleNamespace(
            portfolio="futu",
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=True,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=False,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []
        trading_day_filter = MagicMock(
            return_value=(["AAPL", "HK00700"], "us,hk", False)
        )

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            trading_day_filter,
        ), patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=["AAPL", "HK00700"],
        ) as loader, patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager:
            feishu_manager.return_value.is_configured.return_value = False
            cli_target = MagicMock()
            first_result = main.run_full_analysis(
                config, args, ["600519"], analysis_targets=[cli_target]
            )
            second_result = main.run_full_analysis(
                config, args, ["600519"], analysis_targets=[cli_target]
            )

        self.assertTrue(first_result)
        self.assertTrue(second_result)
        self.assertEqual(loader.call_count, 2)
        config.refresh_stock_list.assert_not_called()
        self.assertEqual(trading_day_filter.call_count, 2)
        trading_day_filter.assert_has_calls(
            [
                call(config, args, ["AAPL", "HK00700"]),
                call(config, args, ["AAPL", "HK00700"]),
            ]
        )
        self.assertEqual(pipeline.run.call_count, 2)
        for invocation in pipeline.run.call_args_list:
            self.assertEqual(invocation.kwargs["stock_codes"], ["AAPL", "HK00700"])
            self.assertIsNone(invocation.kwargs["analysis_targets"])

    def test_run_full_analysis_skips_empty_futu_portfolio_without_fallback(self):
        args = SimpleNamespace(
            portfolio="futu",
            force_run=True,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=True,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=True,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )
        real_import = builtins.__import__

        def reject_pipeline_import(name, *args, **kwargs):
            if name in {"src.core.market_review", "src.core.pipeline"}:
                raise AssertionError(f"empty portfolio must not import {name}")
            return real_import(name, *args, **kwargs)

        with patch.object(
            main,
            "_refresh_stock_index_cache_for_analysis",
        ) as refresh_stock_index, patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=([], None, False),
        ) as trading_day_filter, patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=[],
        ), patch.object(
            builtins,
            "__import__",
            side_effect=reject_pipeline_import,
        ), self.assertLogs(main.logger, level="INFO") as captured:
            result = main.run_full_analysis(config, args, ["600519"])

        self.assertTrue(result)
        config.refresh_stock_list.assert_not_called()
        refresh_stock_index.assert_not_called()
        trading_day_filter.assert_not_called()
        log_text = "\n".join(captured.output)
        self.assertIn("无符合条件的 Futu 持仓", log_text)
        self.assertNotIn("未配置自选股列表", log_text)

    def test_empty_futu_portfolio_is_noop_when_trading_day_check_is_disabled(self):
        args = SimpleNamespace(
            portfolio="futu",
            force_run=False,
            no_market_review=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            market_review_enabled=False,
            trading_day_check_enabled=False,
        )

        with patch.object(
            main,
            "_refresh_stock_index_cache_for_analysis",
        ) as refresh_stock_index, patch.object(
            main,
            "_compute_trading_day_filter",
        ) as trading_day_filter, patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=[],
        ), self.assertLogs(main.logger, level="INFO") as captured:
            result = main.run_full_analysis(config, args, ["600519"])

        self.assertTrue(result)
        config.refresh_stock_list.assert_not_called()
        refresh_stock_index.assert_not_called()
        trading_day_filter.assert_not_called()
        self.assertIn("无符合条件的 Futu 持仓", "\n".join(captured.output))

    def test_empty_futu_portfolio_preserves_enabled_auto_backtest(self):
        args = SimpleNamespace(
            portfolio="futu",
            no_market_review=True,
        )
        config = SimpleNamespace(
            market_review_enabled=True,
            backtest_enabled=True,
            backtest_eval_window_days=10,
            backtest_min_age_days=14,
        )
        backtest_service = MagicMock()
        backtest_service.run_backtest.return_value = {
            "processed": 1,
            "saved": 1,
            "completed": 1,
            "insufficient": 0,
            "errors": 0,
        }
        real_import = builtins.__import__

        def reject_pipeline_import(name, *args, **kwargs):
            if name in {"src.core.market_review", "src.core.pipeline"}:
                raise AssertionError(f"empty portfolio must not import {name}")
            return real_import(name, *args, **kwargs)

        with patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=[],
        ), patch(
            "src.services.backtest_service.BacktestService",
            return_value=backtest_service,
        ) as backtest_class, patch.object(
            builtins,
            "__import__",
            side_effect=reject_pipeline_import,
        ):
            result = main.run_full_analysis(config, args)

        self.assertTrue(result)
        backtest_class.assert_called_once_with()
        backtest_service.run_backtest.assert_called_once_with(
            force=False,
            eval_window_days=10,
            min_age_days=14,
            limit=200,
        )

    def test_empty_futu_portfolio_uses_an_accurate_skip_reason(self):
        args = SimpleNamespace(portfolio="futu")
        config = SimpleNamespace(refresh_stock_list=MagicMock())

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=([], "", True),
        ), patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=[],
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
        ) as pipeline_class, patch(
            "src.core.market_review.run_market_review",
        ), self.assertLogs(main.logger, level="INFO") as captured:
            result = main.run_full_analysis(config, args)

        self.assertTrue(result)
        pipeline_class.assert_not_called()
        log_text = "\n".join(captured.output)
        self.assertIn("无符合条件的 Futu 持仓", log_text)
        self.assertNotIn("所有相关市场均为非交易日", log_text)

    def test_futu_portfolio_without_effective_codes_still_runs_market_review(self):
        args = SimpleNamespace(
            portfolio="futu",
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=False,
            workers=1,
            dry_run=True,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=True,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )
        for holdings in ([], ["AAPL"]):
            with self.subTest(holdings=holdings):
                pipeline = MagicMock()
                run_market_review = MagicMock()

                with patch.object(
                    main,
                    "_refresh_stock_index_cache_for_analysis",
                ), patch.object(
                    main,
                    "_compute_trading_day_filter",
                    return_value=([], "cn", False),
                ), patch(
                    "src.brokers.futu.portfolio.load_futu_stock_codes",
                    return_value=holdings,
                ), patch(
                    "src.core.pipeline.StockAnalysisPipeline",
                    return_value=pipeline,
                ), patch(
                    "src.core.market_review.run_market_review",
                    run_market_review,
                ), patch.object(
                    main,
                    "_run_market_review_with_shared_lock",
                    return_value=SimpleNamespace(report="market review"),
                ) as run_with_lock, patch(
                    "src.feishu_doc.FeishuDocManager",
                ) as feishu_manager:
                    feishu_manager.return_value.is_configured.return_value = False
                    result = main.run_full_analysis(config, args)

                self.assertTrue(result)
                pipeline.run.assert_not_called()
                run_with_lock.assert_called_once()

    def test_runtime_scheduler_preserves_futu_portfolio_override(self):
        scheduler = RuntimeSchedulerService(
            owns_schedule=False,
            schedule_args_overrides={"portfolio": "futu"},
        )

        self.assertEqual(scheduler._make_schedule_args().portfolio, "futu")

    def test_runtime_scheduler_records_futu_load_failure_and_keeps_running(self):
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        error = FutuPortfolioError("OpenD unavailable")

        def runner(config_arg, args, stock_codes):
            raise error

        scheduler = RuntimeSchedulerService(
            config_provider=lambda: config,
            task_runner=runner,
        )
        scheduler._reload_config = lambda: config

        self.assertTrue(scheduler._run_analysis_once())
        status = scheduler.status()
        self.assertIsNone(status["last_success_at"])
        self.assertEqual(status["last_error"], "OpenD unavailable")


class MergePortfolioHoldingsTest(unittest.TestCase):
    def _ledger(self, identities=None, error=None):
        """Patch the ledger replay; identities are (market, symbol) per position."""
        service = MagicMock()
        if error is not None:
            service.get_portfolio_snapshot.side_effect = error
        else:
            service.get_portfolio_snapshot.return_value = {
                "accounts": [
                    {"positions": [{"market": market, "symbol": symbol} for market, symbol in identities or []]}
                ]
            }
        return patch("src.services.portfolio_service.PortfolioService", return_value=service)

    def test_disabled_keeps_watchlist_and_skips_ledger(self):
        config = SimpleNamespace(analyze_portfolio_holdings=False)
        with self._ledger(error=AssertionError("ledger must not be read when disabled")):
            result = main._merge_portfolio_holdings(config, ["2330.TW"])

        self.assertEqual(result, ["2330.TW"])

    def test_enabled_appends_holdings_after_watchlist_without_duplicates(self):
        config = SimpleNamespace(analyze_portfolio_holdings=True)
        identities = [("tw", "2330.TW"), ("tw", "00631L.TW"), ("tw", "3324.TWO"), ("us", "tsla")]
        with self._ledger(identities):
            result = main._merge_portfolio_holdings(config, ["2330.TW", "0050.TW"])

        self.assertEqual(result, ["2330.TW", "0050.TW", "00631L.TW", "3324.TWO", "TSLA"])

    def test_exchange_prefixed_a_share_dedupes_against_bare_watchlist_code(self):
        config = SimpleNamespace(analyze_portfolio_holdings=True)
        with self._ledger([("cn", "SH600519"), ("cn", "SZ000001")]):
            result = main._merge_portfolio_holdings(config, ["600519"])

        self.assertEqual(result, ["600519", "000001"])

    def test_skips_holdings_whose_code_does_not_resolve_to_the_ledger_market(self):
        # Bare 2330 / 7203 / 005930 would be analyzed as HK / HK / A-share.
        config = SimpleNamespace(analyze_portfolio_holdings=True)
        identities = [
            ("tw", "2330"),
            ("jp", "7203"),
            ("kr", "005930"),
            ("tw", "2303.TW"),
            ("hk", "00700"),
            ("jp", "7203.T"),
        ]
        with self._ledger(identities), self.assertLogs(main.logger, level="WARNING") as logs:
            result = main._merge_portfolio_holdings(config, ["0050.TW"])

        self.assertEqual(result, ["0050.TW", "2303.TW", "00700", "7203.T"])
        self.assertEqual(sum("未并入本轮分析" in line for line in logs.output), 3)

    def test_ledger_failure_degrades_to_watchlist(self):
        config = SimpleNamespace(analyze_portfolio_holdings=True)
        with self._ledger(error=RuntimeError("db down")):
            result = main._merge_portfolio_holdings(config, ["2330.TW"])

        self.assertEqual(result, ["2330.TW"])

    def test_run_full_analysis_merges_holdings_only_for_config_watchlist(self):
        args = SimpleNamespace(dry_run=False, no_market_review=True)
        seen = []

        def _capture_filter(_config, _args, codes):
            seen.append(list(codes))
            return [], None, True

        for stock_codes, expected in ((None, ["2330.TW", "5469.TW"]), (["2317.TW"], ["2317.TW"])):
            config = SimpleNamespace(
                stock_list=["2330.TW"],
                analyze_portfolio_holdings=True,
                market_review_enabled=False,
                refresh_stock_list=MagicMock(),
            )
            seen.clear()
            with self._ledger([("tw", "5469.TW")]), patch.object(
                main, "_refresh_stock_index_cache_for_analysis"
            ), patch.object(main, "_compute_trading_day_filter", side_effect=_capture_filter), patch.object(
                main, "_run_auto_backtest"
            ):
                main.run_full_analysis(config, args, stock_codes)
            self.assertEqual(seen, [expected])

    def test_startup_gate_expected_codes_mirror_the_run_holdings_merge(self):
        # 啟動去重閘門的預期清單必須跟 run_full_analysis 一樣併入持股；
        # 少了它，當天新增的持股會被「當日全量已覆蓋」誤判而略過。
        args = SimpleNamespace(portfolio=None)

        def _passthrough(_config, _args, codes):
            return list(codes), None, False

        for stock_codes, expected in ((None, ["2330.TW", "5469.TW"]), (["2317.TW"], ["2317.TW"])):
            config = SimpleNamespace(
                stock_list=["2330.TW"],
                analyze_portfolio_holdings=True,
                refresh_stock_list=MagicMock(),
            )
            with self._ledger([("tw", "5469.TW")]), patch.object(
                main, "_compute_trading_day_filter", side_effect=_passthrough
            ):
                codes, reason = main._resolve_gate_expected_stock_codes(config, args, stock_codes=stock_codes)
            self.assertIsNone(reason)
            self.assertEqual(codes, expected)


class MainMarketReviewFailureTest(unittest.TestCase):
    """T25：大盤複盤失敗不能被個股結果掩蓋（個股照推、報告照存，僅回 False）。"""

    @staticmethod
    def _args(**overrides):
        values = dict(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=False,
            workers=1,
            dry_run=False,
            no_notify=False,
            schedule=False,
        )
        values.update(overrides)
        return SimpleNamespace(**values)

    @staticmethod
    def _config(**overrides):
        values = dict(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=True,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
            report_type="simple",
        )
        values.update(overrides)
        return SimpleNamespace(**values)

    @staticmethod
    def _pipeline():
        pipeline = MagicMock()
        pipeline.run.return_value = [
            SimpleNamespace(
                code="2330.TW",
                success=True,
                sentiment_score=90,
                name="台積電",
                operation_advice="持有",
                trend_prediction="震盪上行",
                get_emoji=MagicMock(return_value="📈"),
            )
        ]
        pipeline._last_local_report_path = "/tmp/report.md"
        pipeline.notifier = MagicMock(
            is_available=MagicMock(return_value=True),
            generate_aggregate_report=MagicMock(return_value="dashboard"),
            send=MagicMock(return_value=True),
        )
        return pipeline

    def _run(self, *, args=None, config=None, pipeline=None, review_result=None,
             missing_regions=(), prime=None, region="cn"):
        args = args or self._args()
        config = config or self._config()
        pipeline = pipeline or self._pipeline()
        patches = [
            patch.object(main, "_refresh_stock_index_cache_for_analysis"),
            patch.object(
                main, "_compute_trading_day_filter",
                return_value=(["2330.TW"], region, False),
            ),
            patch("src.core.pipeline.StockAnalysisPipeline", return_value=pipeline),
            patch("src.core.market_review.run_market_review"),
            patch(
                "src.core.market_review.last_run_missing_regions",
                return_value=list(missing_regions),
            ),
            patch("src.feishu_doc.FeishuDocManager"),
            patch.object(main, "_run_auto_backtest"),
            patch.object(
                main, "_run_market_review_with_shared_lock", return_value=review_result
            ),
            patch.object(
                main, "_resolve_daily_market_context_target_date",
                return_value=date(2026, 10, 16),
            ),
        ]
        if prime is not None:
            patches.append(patch.object(main, "_prime_daily_market_context", side_effect=prime))
        mocks = []
        try:
            for p in patches:
                mocks.append(p.start())
            mocks[5].return_value.is_configured.return_value = False
            result = main.run_full_analysis(config, args, ["2330.TW"])
            review_lock = mocks[7]
        finally:
            for p in reversed(patches):
                p.stop()
        return result, pipeline, review_lock

    def test_review_none_with_stock_results_fails_but_stocks_still_pushed(self):
        result, pipeline, review = self._run(review_result=None)

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "market_review_failed")
        review.assert_called_once()
        pipeline.run.assert_called_once()
        self.assertTrue(pipeline.run.call_args.kwargs["send_notification"])

    def test_review_exception_path_fails_with_runtime_error_reason(self):
        pipeline = self._pipeline()
        with patch.object(main, "_run_market_review_with_shared_lock", side_effect=RuntimeError("boom")):
            args, config = self._args(), self._config()
            with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
                main, "_compute_trading_day_filter", return_value=(["2330.TW"], "cn", False)
            ), patch("src.core.pipeline.StockAnalysisPipeline", return_value=pipeline), patch.object(
                main, "_run_auto_backtest"
            ):
                result = main.run_full_analysis(config, args, ["2330.TW"])

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "runtime_error")

    def test_multi_market_missing_region_fails_but_partial_review_still_merged(self):
        config = self._config(merge_email_notification=True, market_review_region="tw,us")
        result, pipeline, _ = self._run(
            config=config,
            region="tw,us",
            review_result=SimpleNamespace(report="US body only"),
            missing_regions=["tw"],
        )

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "market_review_failed")
        pipeline.notifier.send.assert_called_once()
        combined = pipeline.notifier.send.call_args.args[0]
        self.assertIn("US body only", combined)
        self.assertIn("dashboard", combined)

    def test_complete_review_succeeds(self):
        result, _, _ = self._run(
            review_result=SimpleNamespace(report="full review"), missing_regions=[]
        )

        self.assertTrue(result)
        self.assertIsNone(main._LAST_ANALYSIS_FAILURE_REASON)

    def test_lock_contention_rescued_by_context_reread_is_not_a_failure(self):
        calls = {"n": 0}

        def prime(*_args, **kwargs):
            calls["n"] += 1
            full = bool(kwargs.get("return_full_report"))
            if calls["n"] < 4:
                return ("", "") if full else ""
            return ("rescued summary", "rescued full report")

        config = self._config(daily_market_context_enabled=True)
        # 殘留的缺漏清單（上一輪遺留）在鎖競爭略過複盤時不得被讀成本輪失敗。
        result, _, review = self._run(
            config=config, review_result=None, prime=prime, missing_regions=["tw"]
        )

        self.assertTrue(result)
        self.assertIsNone(main._LAST_ANALYSIS_FAILURE_REASON)
        review.assert_called_once()
        self.assertGreaterEqual(calls["n"], 4)

    def test_no_market_review_flag_never_sets_market_review_failed(self):
        result, pipeline, review = self._run(
            args=self._args(no_market_review=True), review_result=None
        )

        self.assertTrue(result)
        self.assertIsNone(main._LAST_ANALYSIS_FAILURE_REASON)
        review.assert_not_called()

    def test_dry_run_never_sets_market_review_failed(self):
        result, _, _ = self._run(args=self._args(dry_run=True), review_result=None)

        self.assertIsNone(main._LAST_ANALYSIS_FAILURE_REASON)


if __name__ == "__main__":
    unittest.main()
