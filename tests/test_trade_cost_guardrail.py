# -*- coding: utf-8 -*-
"""台股價位成本檢核（src/trade_cost_guardrail.py）。

來由：2026-07~09 的台股報告照價位掛單進出，含成本 -8.50%、不計成本 -0.88%；目標價
中位只比買點高 3.69%、停損低 2.14%，扣掉約 0.88% 來回成本後淨風報比約 0.93。
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from src.trade_cost_guardrail import (  # noqa: E402
    apply_trade_cost_guardrail,
    evaluate_levels,
    format_cost_check,
)
from src.schemas.decision_action import build_action_fields  # noqa: E402
from src.schemas.decision_scale import extract_decision_guardrail_reason  # noqa: E402

# 回測裡的中位間距：目標 +3.69%、停損 -2.14%
TYPICAL = {"ideal_buy": 100.0, "stop_loss": 97.86, "take_profit": 103.69}
WIDE = {"ideal_buy": 100.0, "stop_loss": 96.0, "take_profit": 110.0}


def _result(levels, *, decision_type="buy", action="buy", advice="买入", code="2330.TW"):
    return SimpleNamespace(
        code=code, decision_type=decision_type, action=action, operation_advice=advice,
        sentiment_score=78, risk_warning="", report_language="zh-TW",
        dashboard={"core_conclusion": {"one_sentence": "回踩買入",
                                       "position_advice": {"no_position": "分批買", "has_position": "續抱"}},
                   "battle_plan": {"sniper_points": {k: f"{v}元" for k, v in levels.items()}}},
    )


class TestEvaluateLevels(unittest.TestCase):
    def test_typical_report_spacing_fails_after_costs(self):
        c = evaluate_levels("2330.TW", **TYPICAL)
        self.assertEqual(c["status"], "ok")
        self.assertGreater(c["gross_rr"], 1.5)          # 帳面看起來划算
        self.assertLess(c["net_rr"], 1.0)               # 扣完成本賠比賺多
        self.assertFalse(c["passed"])
        self.assertAlmostEqual(c["round_trip_cost_pct"], 0.882, places=2)

    def test_bond_etf_cost_drops_tax_only_inside_statutory_exemption(self):
        from datetime import date

        inside = evaluate_levels("00679B.TWO", **TYPICAL, sale_date=date(2026, 6, 30))
        after = evaluate_levels("00679B.TWO", **TYPICAL, sale_date=date(2027, 1, 1))
        etf = evaluate_levels("0050.TW", **TYPICAL, sale_date=date(2026, 6, 30))
        # 停徵期內少掉 0.1% 證交稅；期滿後與一般 ETF 相同
        self.assertAlmostEqual(after["round_trip_cost_pct"], etf["round_trip_cost_pct"], places=6)
        self.assertAlmostEqual(after["round_trip_cost_pct"] - inside["round_trip_cost_pct"], 0.1, delta=0.005)

    def test_wide_levels_pass(self):
        self.assertTrue(evaluate_levels("2330.TW", **WIDE)["passed"])

    def test_threshold_is_a_floor_in_both_directions(self):
        rr = evaluate_levels("2330.TW", **WIDE)["net_rr"]
        self.assertTrue(evaluate_levels("2330.TW", **WIDE, min_net_rr=rr - 0.01)["passed"])
        self.assertFalse(evaluate_levels("2330.TW", **WIDE, min_net_rr=rr + 0.01)["passed"])

    def test_target_inside_cost_fails_even_at_zero_threshold(self):
        c = evaluate_levels("2330.TW", ideal_buy=100, stop_loss=95, take_profit=100.5, min_net_rr=0)
        self.assertLess(c["net_upside_pct"], 0)
        self.assertFalse(c["passed"])

    def test_etf_pays_lower_tax(self):
        stock = evaluate_levels("2330.TW", **TYPICAL)["round_trip_cost_pct"]
        etf = evaluate_levels("0050.TW", **TYPICAL)["round_trip_cost_pct"]
        self.assertAlmostEqual(stock - etf, 0.2, places=1)   # 證交稅 0.3% vs 0.1%

    def test_fee_discount_lowers_cost(self):
        full = evaluate_levels("2330.TW", **TYPICAL)["round_trip_cost_pct"]
        disc = evaluate_levels("2330.TW", **TYPICAL, fee_discount=0.6)["round_trip_cost_pct"]
        self.assertLess(disc, full)

    def test_unsupported_market_and_missing_levels_are_not_passes(self):
        for code in ("AAPL", "0700.HK", "2330"):
            c = evaluate_levels(code, **TYPICAL)
            self.assertEqual(c["status"], "unsupported_market")
            self.assertIsNone(c["passed"])
        self.assertEqual(evaluate_levels("2330.TW", ideal_buy=100, stop_loss=None, take_profit=105)["status"],
                         "levels_missing")
        self.assertEqual(evaluate_levels("2330.TW", ideal_buy=100, stop_loss=101, take_profit=105)["status"],
                         "levels_missing")


class TestApplyGuardrail(unittest.TestCase):
    def test_softening_discards_buy_action_already_lifted_by_score(self):
        r = _result(TYPICAL, decision_type="hold", action="buy", advice="觀望")
        r.sentiment_score = 68

        apply_trade_cost_guardrail(r, code=r.code, report_language="zh-TW")

        self.assertEqual(build_action_fields(
            operation_advice=r.operation_advice,
            explicit_action=r.action,
            sentiment_score=r.sentiment_score,
            guardrail_reason=extract_decision_guardrail_reason({"dashboard": r.dashboard}),
            align_with_score=True,
        )["action"], "watch")

    def test_hold_with_buy_band_score_is_softened_before_final_alignment(self):
        r = _result(TYPICAL, decision_type="hold", action="watch", advice="觀望")
        r.sentiment_score = 68

        self.assertEqual(apply_trade_cost_guardrail(r, code=r.code, report_language="zh-TW"),
                         ["trade_cost_buy_softened"])
        self.assertEqual(r.sentiment_score, 59)
        reason = extract_decision_guardrail_reason({"dashboard": r.dashboard})
        self.assertTrue(reason)
        calibration = r.dashboard["decision_score_calibration"]
        self.assertEqual((calibration["raw_score"], calibration["raw_decision_type"]), (68, "hold"))
        self.assertEqual(build_action_fields(
            operation_advice=r.operation_advice,
            explicit_action=r.action,
            sentiment_score=r.sentiment_score,
            guardrail_reason=reason,
            align_with_score=True,
        )["action"], "watch")

    def test_hold_outside_buy_band_is_untouched_when_cost_check_fails(self):
        r = _result(TYPICAL, decision_type="hold", action="watch", advice="持有觀察")
        r.sentiment_score = 55

        self.assertEqual(apply_trade_cost_guardrail(r, code=r.code, report_language="zh-TW"), [])
        self.assertFalse(r.dashboard["battle_plan"]["cost_check"]["passed"])
        self.assertEqual(r.sentiment_score, 55)
        self.assertEqual((r.decision_type, r.operation_advice), ("hold", "持有觀察"))
        self.assertEqual(r.risk_warning, "")
        self.assertIsNone(extract_decision_guardrail_reason({"dashboard": r.dashboard}))
        self.assertNotIn("decision_score_calibration", r.dashboard)

    def test_sell_with_buy_band_score_is_untouched_when_cost_check_fails(self):
        # 反向檢查：分數區間只補 hold 的洞，賣出不能被成本護欄改成觀望
        r = _result(TYPICAL, decision_type="sell", action="sell", advice="卖出")
        r.sentiment_score = 68

        self.assertEqual(apply_trade_cost_guardrail(r, code=r.code, report_language="zh-TW"), [])
        self.assertEqual((r.decision_type, r.action, r.operation_advice), ("sell", "sell", "卖出"))
        self.assertEqual(r.sentiment_score, 68)
        self.assertNotIn("decision_score_calibration", r.dashboard)

    def test_failing_buy_is_softened_to_watch(self):
        r = _result(TYPICAL)
        self.assertEqual(apply_trade_cost_guardrail(r, code=r.code, report_language="zh-TW"),
                         ["trade_cost_buy_softened"])
        self.assertEqual(r.decision_type, "hold")
        self.assertEqual(r.operation_advice, "觀望")
        self.assertLessEqual(r.sentiment_score, 59)
        self.assertIn("淨風報比", r.risk_warning)
        self.assertIn("不划算", r.dashboard["core_conclusion"]["one_sentence"])
        self.assertFalse(r.dashboard["battle_plan"]["cost_check"]["passed"])

    def test_softening_persists_pre_guardrail_score(self):
        # 護欄前分數落庫給 shadow_buy_eval；前一個護欄已記的 raw_score 不得被覆蓋
        r = _result(TYPICAL)
        apply_trade_cost_guardrail(r, code=r.code, report_language="zh-TW")
        cal = r.dashboard["decision_score_calibration"]
        self.assertEqual((cal["raw_score"], cal["raw_decision_type"], cal["final_action"]), (78, "buy", "hold"))
        self.assertEqual(cal["adjusted_score"], r.sentiment_score)
        self.assertIn("淨風報比", cal["guardrail_reason"])

        r = _result(TYPICAL)
        r.dashboard["decision_score_calibration"] = {"raw_score": 85, "adjusted_score": 78}
        apply_trade_cost_guardrail(r, code=r.code, report_language="zh-TW")
        cal = r.dashboard["decision_score_calibration"]
        self.assertEqual(cal["raw_score"], 85)
        self.assertEqual(cal["adjusted_score"], r.sentiment_score)
        self.assertLessEqual(cal["adjusted_score"], 59)

    def test_passing_buy_is_untouched(self):
        r = _result(WIDE)
        self.assertEqual(apply_trade_cost_guardrail(r, code=r.code, report_language="zh-TW"), [])
        self.assertEqual((r.decision_type, r.operation_advice), ("buy", "买入"))
        self.assertTrue(r.dashboard["battle_plan"]["cost_check"]["passed"])
        self.assertNotIn("decision_score_calibration", r.dashboard)

    def test_non_buy_gets_the_check_but_keeps_its_advice(self):
        # 掛單照價位做的人看的是價位不是評級，所以觀望的報告也要有檢核
        r = _result(TYPICAL, decision_type="hold", action="watch", advice="观望")
        r.sentiment_score = 55
        self.assertEqual(apply_trade_cost_guardrail(r, code=r.code, report_language="zh-TW"), [])
        self.assertEqual(r.operation_advice, "观望")
        self.assertFalse(r.dashboard["battle_plan"]["cost_check"]["passed"])

    def test_non_tw_result_is_left_alone(self):
        r = _result(TYPICAL, code="AAPL")
        self.assertEqual(apply_trade_cost_guardrail(r, code="AAPL"), [])
        self.assertNotIn("cost_check", r.dashboard["battle_plan"])
        self.assertEqual(r.decision_type, "buy")


class TestFormatAndRender(unittest.TestCase):
    def test_line_in_each_language_and_silent_without_levels(self):
        c = evaluate_levels("2330.TW", **TYPICAL)
        self.assertIn("淨風報比", format_cost_check(c, "zh-TW"))
        self.assertIn("净风报比", format_cost_check(c, "zh"))
        self.assertIn("net R/R", format_cost_check(c, "en"))
        self.assertIn("손익비", format_cost_check(c, "ko"))
        self.assertIsNone(format_cost_check({"status": "levels_missing"}, "zh-TW"))
        self.assertIsNone(format_cost_check(None, "zh-TW"))

    @mock.patch("src.notification.get_config")
    def test_dashboard_report_prints_the_check(self, mock_get_config):
        from src.analyzer import AnalysisResult
        from src.notification import NotificationService
        from tests.test_notification import _make_config

        mock_get_config.return_value = _make_config(report_renderer_enabled=False, report_language="zh-TW")
        r = AnalysisResult(code="2330.TW", name="台積電", sentiment_score=55, trend_prediction="震盪",
                           operation_advice="觀望", analysis_summary="等回踩", decision_type="hold",
                           report_language="zh-TW",
                           dashboard={"battle_plan": {"sniper_points": {k: str(v) for k, v in TYPICAL.items()}}})
        apply_trade_cost_guardrail(r, code=r.code, report_language="zh-TW")
        out = NotificationService().generate_dashboard_report([r], report_date="2026-09-24")
        self.assertIn("成本檢核", out)
        self.assertIn("不划算", out)

    def test_markdown_template_prints_the_check(self):
        from src.analyzer import AnalysisResult
        from src.services.report_renderer import render

        r = AnalysisResult(code="2330.TW", name="台積電", sentiment_score=55, trend_prediction="震盪",
                           operation_advice="觀望", analysis_summary="等回踩", decision_type="hold",
                           report_language="zh-TW",
                           dashboard={"battle_plan": {"sniper_points": {k: str(v) for k, v in TYPICAL.items()}}})
        apply_trade_cost_guardrail(r, code=r.code, report_language="zh-TW")
        out = render("markdown", [r], report_date="2026-09-24", extra_context={"report_language": "zh-TW"})
        self.assertIsNotNone(out)
        self.assertIn("成本檢核", out)


class TestPromptAndSchema(unittest.TestCase):
    def _prompt(self, code):
        from src.analyzer import GeminiAnalyzer

        with patch.object(GeminiAnalyzer, "_init_litellm", return_value=None):
            analyzer = GeminiAnalyzer()
        context = {"code": code, "stock_name": "X", "date": "2026-09-24",
                   "today": {"close": 100, "ma5": 99, "ma10": 98, "ma20": 97}}
        return analyzer._format_prompt(context, "X", news_context=None)

    def test_tw_prompt_carries_the_cost_and_other_markets_do_not(self):
        self.assertIn("台股交易成本", self._prompt("2330.TW"))
        self.assertNotIn("台股交易成本", self._prompt("AAPL"))

    def test_pipeline_explanation_accepts_trade_cost_source(self):
        from src.schemas.report_schema import PipelineActionAdjustmentExplanation

        PipelineActionAdjustmentExplanation(source="trade_cost", from_action="buy", to_action="watch")


if __name__ == "__main__":
    unittest.main()


class TestAtr(unittest.TestCase):
    def test_atr_pct_matches_hand_computed_true_range(self):
        import pandas as pd
        from src.stock_analyzer import StockTrendAnalyzer

        # 每天高低差 4、收盤 100 不動 → TR 恆為 4 → ATR% = 4%
        df = pd.DataFrame({"high": [102.0] * 20, "low": [98.0] * 20, "close": [100.0] * 20})
        self.assertAlmostEqual(StockTrendAnalyzer._calculate_atr_pct(df), 4.0)
        # 跳空：前收 100、當日 110~106 → TR 取 |high - prev| = 10，不是 high-low 的 4
        gap = pd.concat([df, pd.DataFrame({"high": [110.0], "low": [106.0], "close": [108.0]})],
                        ignore_index=True)
        expected = (4.0 * 13 + 10.0) / 14 / 108.0 * 100
        self.assertAlmostEqual(StockTrendAnalyzer._calculate_atr_pct(gap), round(expected, 2))
        self.assertIsNone(StockTrendAnalyzer._calculate_atr_pct(df.head(10)))
        self.assertIsNone(StockTrendAnalyzer._calculate_atr_pct(df[["close"]]))

    def test_stop_inside_one_day_range_is_flagged_but_not_downgraded_alone(self):
        tight = evaluate_levels("2330.TW", **WIDE, atr_pct=5.0)     # 停損 4% < ATR 5%
        self.assertTrue(tight["stop_within_atr"])
        self.assertTrue(tight["passed"])                             # 只提示，不影響結論
        self.assertIn("ATR14", format_cost_check(tight, "zh-TW"))
        loose = evaluate_levels("2330.TW", **WIDE, atr_pct=3.0)
        self.assertFalse(loose["stop_within_atr"])
        self.assertNotIn("ATR14", format_cost_check(loose, "zh-TW"))
        self.assertFalse(evaluate_levels("2330.TW", **WIDE)["stop_within_atr"])   # 沒有讀數不警告

    def test_prompt_carries_atr_when_known(self):
        from src.analyzer import GeminiAnalyzer

        with patch.object(GeminiAnalyzer, "_init_litellm", return_value=None):
            analyzer = GeminiAnalyzer()
        context = {"code": "2330.TW", "stock_name": "X", "date": "2026-09-24",
                   "today": {"close": 100, "ma5": 99, "ma10": 98, "ma20": 97},
                   "trend_analysis": {"atr14_pct": 5.54}}
        self.assertIn("ATR14）约 5.54%", analyzer._format_prompt(context, "X", news_context=None))
