# -*- coding: utf-8 -*-
"""Tests for history fallback published_date hard filtering (Issue #697)."""

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.services.history_service import HistoryService


class HistoryNewsFallbackTestCase(unittest.TestCase):
    def test_fallback_filters_by_published_date_window(self) -> None:
        now = datetime.now()
        analysis = SimpleNamespace(code="600519", created_at=now)

        # All entries are within fetched_at window; only one should pass published_date window.
        candidates = [
            SimpleNamespace(
                fetched_at=now,
                published_date=now - timedelta(days=20),  # too old
                title="old",
            ),
            SimpleNamespace(
                fetched_at=now,
                published_date=None,  # unknown -> drop
                title="unknown",
            ),
            SimpleNamespace(
                fetched_at=now,
                published_date=now - timedelta(days=1),  # valid
                title="fresh",
            ),
        ]

        mock_db = MagicMock()
        mock_db.get_analysis_history.return_value = [analysis]
        mock_db.get_recent_news.return_value = candidates

        svc = HistoryService(db_manager=mock_db)
        fake_cfg = SimpleNamespace(news_max_age_days=30, news_strategy_profile="short")
        with patch("src.services.history_service.get_config", return_value=fake_cfg):
            result = svc._fallback_news_by_analysis_context("q-1", limit=20)

        self.assertEqual([item.title for item in result], ["fresh"])

    def test_fallback_uses_analysis_date_as_window_anchor(self) -> None:
        analysis_time = datetime.now() - timedelta(days=40)
        analysis = SimpleNamespace(code="600519", created_at=analysis_time)

        candidates = [
            SimpleNamespace(
                fetched_at=analysis_time,
                published_date=analysis_time - timedelta(days=10),  # too old for short profile
                title="too_old_for_analysis_window",
            ),
            SimpleNamespace(
                fetched_at=analysis_time,
                published_date=analysis_time - timedelta(days=1),  # valid around analysis date
                title="valid_near_analysis_date",
            ),
        ]

        mock_db = MagicMock()
        mock_db.get_analysis_history.return_value = [analysis]
        mock_db.get_recent_news.return_value = candidates

        svc = HistoryService(db_manager=mock_db)
        fake_cfg = SimpleNamespace(news_max_age_days=30, news_strategy_profile="short")
        with patch("src.services.history_service.get_config", return_value=fake_cfg):
            result = svc._fallback_news_by_analysis_context("q-1", limit=20)

        self.assertEqual([item.title for item in result], ["valid_near_analysis_date"])


if __name__ == "__main__":
    unittest.main()


class NewsSnippetCleaningTestCase(unittest.TestCase):
    def test_removes_disclaimer_and_quote_template_only(self) -> None:
        from src.services.history_service import clean_news_snippet

        self.assertEqual(
            clean_news_snippet("公司上修財測。本文僅供參考，不構成投資建議。"),
            "公司上修財測。",
        )
        self.assertEqual(clean_news_snippet("价格: 100 USD\n涨跌: up 2%\n法說會釋出利多。"), "法說會釋出利多。")
        self.assertEqual(clean_news_snippet("Disclaimer: for informational purposes only."), "")

    def test_clean_text_is_returned_byte_for_byte(self) -> None:
        # 反向：沒有樣板的摘要不能被斷句重組改掉。
        from src.services.history_service import clean_news_snippet

        text = "營收成長 20%，  毛利率持平\n下半年看法不變"
        self.assertEqual(clean_news_snippet(text), text)

    def test_key_point_is_traditional_first_sentence_and_skips_foreign_text(self) -> None:
        from src.services.history_service import news_key_point

        self.assertEqual(news_key_point("公司发布财报。下半年持平。"), "公司發布財報。")
        self.assertIsNone(news_key_point("Apple beats estimates."))
        self.assertIsNone(news_key_point(""))
        self.assertEqual(len(news_key_point("长" * 200)), 80)
