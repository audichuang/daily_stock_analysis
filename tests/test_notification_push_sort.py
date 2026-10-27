# -*- coding: utf-8 -*-
"""推播排序不得依 sentiment_score（策略決議 2026-10-27 第 2 項）。

sentiment_score 沒有對應可驗證的預測問題；推播改依操作建議的動作類別，
再依代號排序，分數旁加註「未驗證，不代表勝率」，也不再算平均分。
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.analyzer import AnalysisResult
from src.config import Config
from src.notification import (
    NotificationBuilder,
    NotificationService,
    score_text,
    sort_results_for_push,
)
from src.report_language import get_report_labels


def _result(code, advice, decision_type, score, language="zh"):
    return AnalysisResult(
        code=code,
        name=f"N{code}",
        sentiment_score=score,
        trend_prediction="震荡",
        operation_advice=advice,
        decision_type=decision_type,
        analysis_summary=f"summary {code}",
        report_language=language,
        success=True,
    )


def _results():
    # 分數與動作刻意反向：分數排序會是 sell(99) > buy(90) > hold(50) > buy(10)
    return [
        _result("600001", "买入", "buy", 10),
        _result("600002", "卖出", "sell", 99),
        _result("600003", "观望", "hold", 50),
        _result("600000", "买入", "buy", 90),
    ]


EXPECTED_CODES = ["600000", "600001", "600003", "600002"]


def _positions(text, codes):
    return [text.index(code) for code in codes]


class PushSortTest(unittest.TestCase):
    def test_sort_ignores_sentiment_score(self):
        self.assertEqual(
            [r.code for r in sort_results_for_push(_results())], EXPECTED_CODES
        )

    def test_sort_is_independent_of_input_order_and_scores(self):
        results = _results()
        for r in results:
            r.sentiment_score = 100 - r.sentiment_score
        self.assertEqual(
            [r.code for r in sort_results_for_push(reversed(results))],
            EXPECTED_CODES,
        )

    def test_hold_and_watch_order_ignores_score(self):
        # hold/watch 不得經分數校準改寫成 buy/sell：分數 10/90/50 順序不變
        for advice, dtype in (("观望", "hold"), ("持有", "hold")):
            with self.subTest(advice=advice):
                scores = {"600001": 10, "600002": 90, "600003": 50}
                results = [_result(c, advice, dtype, s) for c, s in scores.items()]
                self.assertEqual(
                    [r.code for r in sort_results_for_push(results)],
                    ["600001", "600002", "600003"],
                )
                for r in results:
                    r.sentiment_score = None
                self.assertEqual(
                    [r.code for r in sort_results_for_push(results)],
                    ["600001", "600002", "600003"],
                )

    def test_watch_vs_buy_not_flipped_by_score(self):
        for watch_score in (50, 95):
            with self.subTest(watch_score=watch_score):
                results = [
                    _result("600001", "观望", "hold", watch_score),
                    _result("600002", "买入", "buy", 70),
                ]
                self.assertEqual(
                    [r.code for r in sort_results_for_push(results)],
                    ["600002", "600001"],
                )

    def test_decision_type_fallback_when_advice_is_free_text(self):
        results = [
            _result("600001", "整體偏弱，建議保守看待", "sell", 90),
            _result("600002", "整體偏強，建議積極看待", "buy", 10),
        ]
        self.assertEqual(
            [r.code for r in sort_results_for_push(results)], ["600002", "600001"]
        )

    def test_every_renderer_uses_action_then_code_order(self):
        cfg = Config(stock_list=[], report_renderer_enabled=False)
        with mock.patch("src.notification.get_config", return_value=cfg):
            service = NotificationService()
            outputs = {
                "daily": service.generate_daily_report(_results(), report_date="2026-10-27"),
                "dashboard": service.generate_dashboard_report(_results(), report_date="2026-10-27"),
                "wechat_dashboard": service.generate_wechat_dashboard(_results()),
                "wechat_summary": service.generate_wechat_summary(_results()),
                "brief": service.generate_brief_report(_results(), report_date="2026-10-27"),
                "stock_summary": NotificationBuilder.build_stock_summary(_results()),
            }
        for name, text in outputs.items():
            with self.subTest(renderer=name):
                positions = _positions(text, EXPECTED_CODES)
                self.assertEqual(positions, sorted(positions), name)

    def test_score_is_annotated_and_average_removed(self):
        cfg = Config(stock_list=[], report_renderer_enabled=False)
        with mock.patch("src.notification.get_config", return_value=cfg):
            service = NotificationService()
            daily = service.generate_daily_report(_results(), report_date="2026-10-27")
            wechat = service.generate_wechat_dashboard(_results())
        self.assertIn("未验证，不代表胜率", daily)
        self.assertNotIn("均分", daily)
        self.assertNotIn("均分", wechat)

    def test_single_stock_quote_line_note_is_separated(self):
        cfg = Config(stock_list=[], report_renderer_enabled=False)
        for language, note in (
            ("en", "unverified, not a win rate"),
            ("ko", "미검증, 승률 아님"),
        ):
            with self.subTest(language=language):
                with mock.patch("src.notification.get_config", return_value=cfg):
                    text = NotificationService().generate_single_stock_report(
                        _result("600000", "买入", "buy", 80, language=language)
                    )
                quote = next(l for l in text.splitlines() if l.startswith("> "))
                self.assertIn(f"（{note}）", quote)
                self.assertNotIn(f"Score{note}", quote)
                self.assertNotIn(f"점수{note}", quote)

    def test_score_note_is_localized(self):
        for language, note in (
            ("zh-TW", "未驗證，不代表勝率"),
            ("en", "unverified, not a win rate"),
        ):
            with self.subTest(language=language):
                labels = get_report_labels(language)
                self.assertIn(note, score_text(labels, 70))
                self.assertNotIn(note, score_text(labels, 70, note=False))


if __name__ == "__main__":
    unittest.main()
