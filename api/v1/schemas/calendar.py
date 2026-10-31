"""追加式行事曆回應契約。"""
from datetime import date as Date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CalendarEvent(BaseModel):
    id: str
    type: str
    code: Optional[str] = None
    name: str
    date: Date
    status: Literal["confirmed", "estimated"]
    detail: str
    source_url: str
    timezone: str
    date_kind: Literal["release", "statutory_deadline"]
    updated_at: Optional[str] = None


class UndatedCompany(BaseModel):
    code: str
    name: str
    detail: str


class CalendarResponse(BaseModel):
    events: list[CalendarEvent] = Field(default_factory=list)
    undated: list[UndatedCompany] = Field(default_factory=list)
    cache_updated_at: Optional[str] = None
