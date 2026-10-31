"""持股與自選的快取行事曆；GET 不刷新外部來源。"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.v1.errors import api_error
from api.v1.schemas.calendar import CalendarResponse
from src.services.calendar_service import CalendarService

router = APIRouter()


def get_calendar_service():
    return CalendarService()


@router.get("/events", response_model=CalendarResponse)
def get_events(
    start: date = Query(alias="from"),
    end: date = Query(alias="to"),
    code: Optional[str] = Query(default=None, max_length=32),
    service: CalendarService = Depends(get_calendar_service),
):
    if end < start or (end - start).days > 366:
        raise api_error(400, "invalid_calendar_range", "日期範圍須依序且不超過 366 日")
    payload = service.events(start, end, code)
    for row in payload["events"]:
        if isinstance(row.get("updated_at"), datetime):
            row["updated_at"] = row["updated_at"].isoformat() + "Z"
    return payload
