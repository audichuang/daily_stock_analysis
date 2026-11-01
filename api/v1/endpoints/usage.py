# -*- coding: utf-8 -*-
"""LLM usage tracking endpoint."""

from __future__ import annotations

import calendar
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query

from api.deps import get_database_manager
from api.v1.schemas.usage import UsageDashboardResponse, UsageSummaryResponse
from src.services import llm_usage_analytics
from src.storage import DatabaseManager

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))  # Beijing time (UTC+8)

router = APIRouter()

_VALID_PERIODS = {"today", "month", "all"}
UsageRecordSort = Literal["newest", "oldest", "tokens"]


def _date_range(period: str):
    """Return (from_dt, to_dt) as naive datetimes in Beijing time (UTC+8)."""
    now = datetime.now(tz=_CST).replace(tzinfo=None)  # naive, Beijing local
    if period == "today":
        from_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        from_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # all
        from_dt = datetime(2000, 1, 1)
    return from_dt, now


def _previous_range(period: str, from_dt: datetime, to_dt: datetime) -> Optional[tuple[datetime, datetime]]:
    """前一期的同一段時間；``all`` 沒有前期。月底對不上時收到上月最後一天。"""
    if period == "today":
        return from_dt - timedelta(days=1), to_dt - timedelta(days=1)
    if period == "month":
        year, month = (to_dt.year - 1, 12) if to_dt.month == 1 else (to_dt.year, to_dt.month - 1)
        day = min(to_dt.day, calendar.monthrange(year, month)[1])
        return from_dt.replace(year=year, month=month), to_dt.replace(year=year, month=month, day=day)
    return None


def _normalize_period(period: str) -> str:
    return period if period in _VALID_PERIODS else "month"


def _enrich_call_record(row: dict[str, Any]) -> dict[str, Any]:
    called_at = row.get("called_at")
    if isinstance(called_at, datetime):
        called_at_value = called_at.isoformat()
    else:
        called_at_value = str(called_at or "")
    channel = llm_usage_analytics.channel_of(row.get("provider"), row.get("transport"))
    return {
        **row,
        "called_at": called_at_value,
        "channel": channel,
        "billing": llm_usage_analytics.billing_of(row.get("model"), channel),
    }


def _build_summary_payload(
    period: str,
    from_dt: datetime,
    to_dt: datetime,
    data: dict[str, Any],
    db_manager: DatabaseManager,
) -> dict[str, Any]:
    prices = llm_usage_analytics.load_prices()
    analytics = llm_usage_analytics.build_analytics(db_manager.get_llm_usage_breakdown(from_dt, to_dt), prices)
    payload = {
        "period": period,
        "from_date": from_dt.date().isoformat(),
        "to_date": to_dt.date().isoformat(),
        "total_calls": data.get("total_calls", 0),
        "total_prompt_tokens": data.get("total_prompt_tokens", 0),
        "total_completion_tokens": data.get("total_completion_tokens", 0),
        "total_tokens": data.get("total_tokens", 0),
        "by_call_type": data.get("by_call_type", []),
        "by_model": data.get("by_model", []),
        **analytics,
        "previous": None,
    }
    previous_range = _previous_range(period, from_dt, to_dt)
    if previous_range is not None:
        previous_from, previous_to = previous_range
        payload["previous"] = llm_usage_analytics.build_previous(
            from_date=previous_from.date().isoformat(),
            to_date=previous_to.date().isoformat(),
            current=payload,
            current_cost=analytics["cost"]["estimated_total"],
            previous_rows=db_manager.get_llm_usage_breakdown(previous_from, previous_to),
            prices=prices,
        )
    return payload


@router.get(
    "/summary",
    response_model=UsageSummaryResponse,
    summary="LLM token usage summary",
    description="Aggregate token consumption by period, call type, and model.",
)
def get_usage_summary(
    period: str = Query("month", description="'today' | 'month' | 'all'"),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> UsageSummaryResponse:
    normalized_period = _normalize_period(period)
    from_dt, to_dt = _date_range(normalized_period)
    data = db_manager.get_llm_usage_summary(from_dt, to_dt)
    return UsageSummaryResponse(**_build_summary_payload(normalized_period, from_dt, to_dt, data, db_manager))


@router.get(
    "/dashboard",
    response_model=UsageDashboardResponse,
    summary="LLM token usage monitoring dashboard",
    description="Return token totals, model breakdowns, and recent LLM call records.",
)
def get_usage_dashboard(
    period: str = Query("month", description="'today' | 'month' | 'all'"),
    limit: int = Query(50, ge=1, le=200, description="Recent call records to include"),
    offset: int = Query(0, ge=0, description="Call records to skip"),
    call_type: Optional[str] = Query(None, max_length=32, description="Only list this call type"),
    sort: UsageRecordSort = Query("newest", description="'newest' | 'oldest' | 'tokens'"),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> UsageDashboardResponse:
    normalized_period = _normalize_period(period)
    from_dt, to_dt = _date_range(normalized_period)
    data = db_manager.get_llm_usage_summary(from_dt, to_dt)
    records = db_manager.get_llm_usage_records(
        from_dt, to_dt, limit=limit, offset=offset, call_type=call_type, sort=sort,
    )
    payload = _build_summary_payload(normalized_period, from_dt, to_dt, data, db_manager)
    payload["recent_calls"] = [_enrich_call_record(row) for row in records]
    payload["recent_total"] = db_manager.count_llm_usage_records(from_dt, to_dt, call_type=call_type)
    return UsageDashboardResponse(**payload)
