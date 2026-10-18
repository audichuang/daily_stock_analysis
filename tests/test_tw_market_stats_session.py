# -*- coding: utf-8 -*-
"""台股大盤統計的場次對齊：統計日與複盤日不同就不採用。

2026-10-16 10:55 的複盤把 10-15 崩盤日的 201 漲／805 跌與法人 -3906 億，配上 10-16
盤中指數 +1.14%，寫出虛構的「背離盤」並存檔、推播。根因：`get_market_stats` 的數字是
TWSE 最新已發布交易日的，而 `overview.date` 在盤中就是今天，兩者沒人比對。

測試全離線：`DataFetcherManager` 換假的，市場時鐘用 `get_market_now` +
`infer_market_phase` 兩個一起釘住（見 tests/AGENTS.md）。
"""

import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.core.trading_calendar import MarketPhase
from src.market_analyzer import MarketAnalyzer, MarketOverview

_TPE = ZoneInfo("Asia/Taipei")
_MISMATCH_ZH_TW = "不得推論"


def _stats(trade_date="2026-10-16", **extra):
    stats = {
        "up_count": 201, "down_count": 805, "flat_count": 60,
        "limit_up_count": 0, "limit_down_count": 0,
        "total_amount": 5200.0,
        "foreign_net": -2500.0, "trust_net": -300.0, "dealer_net": -1106.0,
        "total_net": -3906.0,
    }
    if trade_date is not None:
        stats["trade_date"] = trade_date
    stats.update(extra)
    return stats


def _analyzer(region="tw", language="zh-TW", stats=None):
    with patch("src.market_analyzer.get_config",
               return_value=SimpleNamespace(report_language=language)), \
         patch("src.market_analyzer.DataFetcherManager") as manager_cls:
        manager_cls.return_value.get_market_stats.return_value = stats
        analyzer = MarketAnalyzer(region=region)
    return analyzer


def _fresh_overview(date_str):
    # 生產路徑是先建空物件（只給 date）、再由 _get_market_statistics 逐欄賦值，
    # 測試複製同樣形狀，不用 kwargs 一次建構。
    return MarketOverview(date=date_str)


def _now(year, month, day, hour, minute):
    return datetime.datetime(year, month, day, hour, minute, tzinfo=_TPE)


def _pin_clock(now, phase):
    """同時釘日期與 phase；只釘一個會讓測試在特定時段才紅。"""
    return (
        patch("src.market_analyzer.get_market_now", return_value=now),
        patch("src.market_analyzer.infer_market_phase", return_value=phase),
    )


class SessionAlignmentTestCase(unittest.TestCase):
    def test_previous_day_stats_are_not_adopted_and_warn_with_both_dates(self):
        analyzer = _analyzer(stats=_stats(trade_date="2026-10-15"))
        overview = _fresh_overview("2026-10-16")

        with self.assertLogs("src.market_analyzer", level="WARNING") as logs:
            analyzer._get_market_statistics(overview)

        self.assertEqual(overview.up_count, 0)
        self.assertEqual(overview.down_count, 0)
        self.assertEqual(overview.total_amount, 0.0)
        self.assertIsNone(overview.institutional_net)
        self.assertEqual(
            overview.stats_session_mismatch,
            {"stats_date": "2026-10-15", "overview_date": "2026-10-16"},
        )
        joined = "\n".join(logs.output)
        self.assertIn("status=session_mismatch", joined)
        self.assertIn("stats_date=2026-10-15", joined)
        self.assertIn("overview_date=2026-10-16", joined)

    def test_mismatch_adds_do_not_infer_line_to_stats_block_and_prompt(self):
        analyzer = _analyzer(stats=_stats(trade_date="2026-10-15"))
        overview = _fresh_overview("2026-10-16")
        with self.assertLogs("src.market_analyzer", level="WARNING"):
            analyzer._get_market_statistics(overview)

        self.assertIn(_MISMATCH_ZH_TW, analyzer._build_stats_block(overview))
        self.assertIn(_MISMATCH_ZH_TW, analyzer._build_review_prompt(overview, []))

    def test_mismatch_line_is_localized(self):
        for language, needle in (("en", "do not infer"), ("zh", "不得推论")):
            with self.subTest(language=language):
                analyzer = _analyzer(language=language, stats=_stats(trade_date="2026-10-15"))
                overview = _fresh_overview("2026-10-16")
                with self.assertLogs("src.market_analyzer", level="WARNING"):
                    analyzer._get_market_statistics(overview)
                self.assertIn(needle, analyzer._build_stats_block(overview))
                self.assertIn(needle, analyzer._build_review_prompt(overview, []))

    def test_same_day_stats_are_copied_without_the_line(self):
        analyzer = _analyzer(stats=_stats(trade_date="2026-10-16"))
        overview = _fresh_overview("2026-10-16")

        analyzer._get_market_statistics(overview)

        self.assertEqual(overview.up_count, 201)
        self.assertEqual(overview.down_count, 805)
        self.assertEqual(overview.total_amount, 5200.0)
        self.assertEqual(overview.institutional_net["total_net"], -3906.0)
        self.assertIsNone(overview.stats_session_mismatch)
        self.assertNotIn(_MISMATCH_ZH_TW, analyzer._build_stats_block(overview))
        self.assertNotIn(_MISMATCH_ZH_TW, analyzer._build_review_prompt(overview, []))

    def test_tw_stats_without_trade_date_are_rejected(self):
        analyzer = _analyzer(stats=_stats(trade_date=None))
        overview = _fresh_overview("2026-10-16")

        with self.assertLogs("src.market_analyzer", level="WARNING"):
            analyzer._get_market_statistics(overview)

        self.assertEqual(overview.up_count, 0)
        self.assertIsNone(overview.institutional_net)
        self.assertEqual(
            overview.stats_session_mismatch,
            {"stats_date": None, "overview_date": "2026-10-16"},
        )

    def test_cn_stats_without_trade_date_are_still_copied(self):
        """成對守門：只有 tw 要求 trade_date，其他市場的 stats 沒有這個鍵。"""
        stats = {"up_count": 3000, "down_count": 1500, "flat_count": 200,
                 "limit_up_count": 50, "limit_down_count": 5, "total_amount": 9000.0}
        analyzer = _analyzer(region="cn", language="zh", stats=stats)
        overview = _fresh_overview("2026-10-16")

        analyzer._get_market_statistics(overview)

        self.assertEqual(overview.up_count, 3000)
        self.assertEqual(overview.total_amount, 9000.0)
        self.assertIsNone(overview.stats_session_mismatch)

    def test_intraday_review_end_to_end_rejects_yesterdays_numbers(self):
        """事故原形：10-16 10:55 盤中，統計卻是 10-15 的。"""
        analyzer = _analyzer(stats=_stats(trade_date="2026-10-15"))
        p_now, p_phase = _pin_clock(_now(2026, 10, 16, 10, 55), MarketPhase.INTRADAY)
        with p_now, p_phase, \
             patch.object(analyzer, "_get_main_indices", return_value=[]), \
             patch.object(analyzer, "_pin_tw_indices_to_session"), \
             self.assertLogs("src.market_analyzer", level="WARNING"):
            overview = analyzer.get_market_overview()

        self.assertEqual(overview.date, "2026-10-16")
        self.assertEqual(overview.up_count, 0)
        self.assertIsNone(overview.institutional_net)
        self.assertIsNotNone(overview.stats_session_mismatch)


class InstitutionalPreliminaryLabelTestCase(unittest.TestCase):
    def _block(self, overview_date, now, phase, language="zh-TW"):
        analyzer = _analyzer(language=language, stats=_stats(trade_date=overview_date))
        overview = _fresh_overview(overview_date)
        analyzer._get_market_statistics(overview)
        p_now, p_phase = _pin_clock(now, phase)
        with p_now, p_phase:
            return analyzer._build_stats_block(overview), analyzer._build_review_prompt(overview, [])

    def test_same_day_postmarket_review_labels_preliminary(self):
        block, prompt = self._block(
            "2026-10-16", _now(2026, 10, 16, 18, 0), MarketPhase.POSTMARKET)
        self.assertIn("2026-10-16 盤後初版，官方稍後可能修正", block)
        self.assertIn("2026-10-16 盤後初版，官方稍後可能修正", prompt)

    def test_premarket_review_of_a_closed_session_only_labels_the_date(self):
        block, prompt = self._block(
            "2026-10-15", _now(2026, 10, 16, 7, 30), MarketPhase.PREMARKET)
        self.assertIn("（2026-10-15）", block)
        self.assertNotIn("初版", block)
        self.assertNotIn("初版", prompt)

    def test_english_label(self):
        block, _ = self._block(
            "2026-10-16", _now(2026, 10, 16, 18, 0), MarketPhase.POSTMARKET, language="en")
        self.assertIn("2026-10-16 post-close preliminary", block)

    def test_non_tw_institutional_has_no_label(self):
        analyzer = _analyzer(region="cn", language="zh", stats=None)
        overview = _fresh_overview("2026-10-16")
        overview.institutional_net = {
            "foreign_net": 1.0, "trust_net": 1.0, "dealer_net": 1.0, "total_net": 3.0}
        p_now, p_phase = _pin_clock(_now(2026, 10, 16, 18, 0), MarketPhase.POSTMARKET)
        with p_now, p_phase:
            self.assertNotIn("初版", analyzer._build_stats_block(overview))
