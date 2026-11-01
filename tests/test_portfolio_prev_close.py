# -*- coding: utf-8 -*-
"""今日損益只能用相鄰場次的價差：過期現價、前收盤太舊都要回 None。"""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from src.services.portfolio_service import PortfolioService, _ResolvedPositionPrice


def _resolve(*, stale=False, pre_close=None, close_age_days=1):
    day = date(2025, 3, 12)
    service = PortfolioService.__new__(PortfolioService)
    service.repo = Mock()
    service.repo.get_latest_close_with_date.return_value = (100.0, day - timedelta(days=close_age_days))
    price = _ResolvedPositionPrice(
        price=110.0, source="close", price_date=day, is_stale=stale, is_available=True, pre_close=pre_close,
    )
    return service._resolve_prev_close(symbol="2330.TW", market="tw", price_info=SimpleNamespace(**price.__dict__))


def test_adjacent_session_close_is_used() -> None:
    assert _resolve() == 100.0


def test_long_holiday_gap_still_counts() -> None:
    assert _resolve(close_age_days=10) == 100.0


def test_close_too_old_is_unknown() -> None:
    assert _resolve(close_age_days=30) is None


def test_stale_price_is_unknown_even_with_quote_pre_close() -> None:
    assert _resolve(stale=True, pre_close=105.0) is None


def test_quote_pre_close_wins() -> None:
    assert _resolve(pre_close=105.0) == 105.0
