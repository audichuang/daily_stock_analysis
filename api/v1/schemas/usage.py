# -*- coding: utf-8 -*-
"""Schemas for LLM usage tracking API."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class CallTypeBreakdown(BaseModel):
    call_type: str = Field(..., description="'analysis' | 'agent' | 'market_review' | 'stock_dossier'")
    calls: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int


class ModelBreakdown(BaseModel):
    model: str
    calls: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int
    max_total_tokens: int = 0


class UsageCallRecord(BaseModel):
    id: int
    called_at: str = Field(..., description="ISO datetime string")
    call_type: str
    model: str
    stock_code: Optional[str] = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    channel: Optional[str] = Field(None, description="LLM channel, transport first, then provider")
    billing: Optional[str] = Field(None, description="'metered' | 'subscription'")
    cache_read_tokens: Optional[int] = Field(None, description="null when the provider did not report cache usage")


class UsageDayBreakdown(BaseModel):
    date: str = Field(..., description="ISO date string")
    calls: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int


class UsageChannelBreakdown(BaseModel):
    channel: str
    billing: str = Field(..., description="'metered' | 'subscription'")
    calls: int
    total_tokens: int


class UsageCacheSummary(BaseModel):
    read_tokens: int = 0
    known_prompt_tokens: int = Field(0, description="Prompt tokens of calls that reported cache usage")
    hit_ratio: Optional[float] = Field(None, description="0-1; null when no call reported cache usage")


class UsageModelCost(BaseModel):
    model: str
    channel: str
    billing: str
    total_tokens: int
    estimated_cost: Optional[float] = Field(None, description="null when not priced or not metered")


class UsageCostSummary(BaseModel):
    currency: str = "USD"
    estimated_total: Optional[float] = Field(None, description="null when no model has a configured price")
    complete: bool = Field(True, description="False when a metered model has no configured price")
    unpriced_models: List[str] = Field(default_factory=list)
    subscription_tokens: int = Field(0, description="Tokens on subscription paths, not billed")
    by_model: List[UsageModelCost] = Field(default_factory=list)


class UsagePreviousPeriod(BaseModel):
    from_date: str
    to_date: str
    total_calls: int
    total_tokens: int
    estimated_cost: Optional[float] = None
    calls_change_pct: Optional[float] = Field(None, description="null when the previous period has no calls")
    tokens_change_pct: Optional[float] = None
    cost_change_pct: Optional[float] = None


class UsageSummaryResponse(BaseModel):
    period: str = Field(..., description="'today' | 'month' | 'all'")
    from_date: str = Field(..., description="ISO date string")
    to_date: str = Field(..., description="ISO date string")
    total_calls: int
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int
    by_call_type: List[CallTypeBreakdown]
    by_model: List[ModelBreakdown]
    by_day: List[UsageDayBreakdown] = Field(default_factory=list)
    by_channel: List[UsageChannelBreakdown] = Field(default_factory=list)
    cache: UsageCacheSummary = Field(default_factory=UsageCacheSummary)
    cost: UsageCostSummary = Field(default_factory=UsageCostSummary)
    previous: Optional[UsagePreviousPeriod] = Field(None, description="Same span one period earlier; null for 'all'")


class UsageDashboardResponse(UsageSummaryResponse):
    recent_calls: List[UsageCallRecord]
    recent_total: int = Field(0, description="Records matching the list filter, for pagination")
