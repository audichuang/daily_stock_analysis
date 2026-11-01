# -*- coding: utf-8 -*-
"""報告 payload 追加的 previous_report：前次判斷要給個股、不給大盤複盤。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from src.services.history_service import HistoryService


def _service() -> HistoryService:
    now = datetime.now()
    db = Mock()
    db.get_analysis_history_by_id.return_value = SimpleNamespace(created_at=now)
    db.get_previous_analysis_history.return_value = SimpleNamespace(
        id=7,
        raw_result='{"operation_advice": "减仓", "action": "reduce"}',
        operation_advice="减仓",
        sentiment_score=40,
        created_at=now - timedelta(days=3),
        ideal_buy=None,
        secondary_buy=None,
        stop_loss=None,
        take_profit=None,
        analysis_summary="",
        trend_prediction="",
    )
    service = HistoryService.__new__(HistoryService)
    service.db = db
    return service


def test_stock_report_gets_previous_summary() -> None:
    summary = _service().get_previous_report_summary({"id": 9, "stock_code": "2330.TW", "report_type": "full"})
    assert summary["id"] == 7
    assert summary["action"] == "reduce"
    assert summary["score"] == 40


def test_market_review_has_no_previous_summary() -> None:
    service = _service()
    assert service.get_previous_report_summary({"id": 9, "report_type": "market_review"}) is None
    service.db.get_previous_analysis_history.assert_not_called()
