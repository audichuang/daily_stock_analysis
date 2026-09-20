# -*- coding: utf-8 -*-
"""一輪分析掉了股票,報告必須說出來。

表頭的檔數一直是 `len(results)`,也就是**成功的那幾檔**。實例:2026-09-18 的排程
請求 14 檔,2308.TW 因 `deepseek-v4-flash` 連兩次回非法 JSON 被丟棄
(`pipeline` 記 `成功: 13, 失败: 1`,但 `fail_count` 沒有任何消費者),
`reports/report_20260918.md` 寫「共分析 **13** 檔股票」、整份不含 `2308`,
Bark 推送成功——持有台達電的人完全沒有訊號。

守的是揭露那一半;LLM 那一半的槓桿是 `LITELLM_MODEL`(AGENTS.md §10)。
"""

from unittest.mock import patch

from src.core.pipeline import StockAnalysisPipeline
from src.analyzer import AnalysisResult
from src.enums import ReportType
from src.notification import NotificationService


def _result(code: str, name: str, score: int = 50) -> AnalysisResult:
    return AnalysisResult(
        code=code,
        name=name,
        sentiment_score=score,
        trend_prediction="震盪",
        operation_advice="觀望",
        analysis_summary=f"{name} summary",
        report_language="zh-TW",
    )


def _survivors():
    return [_result("2330.TW", "台積電"), _result("2317.TW", "鴻海")]


class TestAggregateReportDisclosesDroppedStocks:
    def test_dashboard_header_names_the_dropped_stock(self):
        report = NotificationService().generate_aggregate_report(
            _survivors(), ReportType.FULL, report_date="2026-09-18",
            failed_codes=["2308.TW"],
        )

        assert "共分析 **2**" in report          # 成功數不被竄改
        assert "本輪有 1 檔未產出結果" in report
        assert "2308.TW" in report

    def test_brief_header_names_the_dropped_stock(self):
        """兩種 REPORT_TYPE 都要蓋到——只修一種等於沒修。"""
        report = NotificationService().generate_aggregate_report(
            _survivors(), ReportType.BRIEF, report_date="2026-09-18",
            failed_codes=["2308.TW"],
        )

        assert "本輪有 1 檔未產出結果" in report
        assert "2308.TW" in report

    def test_a_clean_run_reads_exactly_as_before(self):
        """反向:沒有失敗時一個字都不能多,否則每天的報告都會多一行雜訊。"""
        service = NotificationService()
        with_arg = service.generate_aggregate_report(
            _survivors(), ReportType.FULL, report_date="2026-09-18", failed_codes=[])
        without_arg = service.generate_aggregate_report(
            _survivors(), ReportType.FULL, report_date="2026-09-18")

        assert with_arg == without_arg
        assert "未產出結果" not in with_arg

    def test_the_label_exists_in_every_report_language(self):
        """語言集漏一格是本 repo 的既有踩雷形狀,新增文案一律四語一起加。"""
        from src.report_language import get_report_labels

        for language in ("zh", "zh-TW", "en", "ko"):
            label = get_report_labels(language).get("failed_stocks_label")
            assert label, language
            assert "{count}" in label, language


class TestPipelineResolvesAndForwardsFailures:
    def test_failed_codes_are_requested_minus_produced_in_request_order(self):
        resolve = StockAnalysisPipeline._resolve_failed_codes
        requested = ["2330.TW", "2308.TW", "2317.TW", "6116.TW"]

        assert resolve(requested, _survivors()) == ["2308.TW", "6116.TW"]
        assert resolve(requested, []) == requested
        assert resolve([], _survivors()) == []

    def test_the_run_level_report_receives_them(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline._last_failed_codes = ["2308.TW"]
        with patch.object(pipeline, "notifier", create=True) as notifier:
            notifier.generate_aggregate_report.return_value = "R"
            pipeline._generate_aggregate_report(_survivors(), ReportType.FULL)

        assert notifier.generate_aggregate_report.call_args.kwargs["failed_codes"] == ["2308.TW"]

    def test_group_reports_do_not_inherit_the_run_wide_failure_list(self):
        """反向:失敗清單是整輪的,寫進某一組會指到不屬於那組的代碼。"""
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline._last_failed_codes = ["2308.TW"]
        with patch.object(pipeline, "notifier", create=True) as notifier:
            notifier.generate_aggregate_report.return_value = "R"
            pipeline._generate_aggregate_report(
                _survivors(), ReportType.FULL, include_failures=False)

        assert "failed_codes" not in notifier.generate_aggregate_report.call_args.kwargs

    def test_an_old_notifier_without_the_parameter_still_gets_a_report(self):
        """fail-open:舊 notifier 不認這個參數時,報告照出、只是少一行揭露。"""
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline._last_failed_codes = ["2308.TW"]

        def _legacy(results, report_type):
            return "LEGACY"

        with patch.object(pipeline, "notifier", create=True) as notifier:
            notifier.generate_aggregate_report = _legacy
            assert pipeline._generate_aggregate_report(
                _survivors(), ReportType.FULL) == "LEGACY"
