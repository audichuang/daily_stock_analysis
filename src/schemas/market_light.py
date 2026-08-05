# -*- coding: utf-8 -*-
"""Structured Market Light snapshot schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MarketRegion = Literal["cn", "hk", "us", "tw", "jp", "kr"]
MarketLightStatus = Literal["green", "yellow", "red"]
MarketLightDataQuality = Literal["ok", "partial", "unavailable"]
# 台股在此 fork 有完整涨跌家数与成交额（TWSE/TPEx OpenAPI），足以评分。
# 上游没有 tw，所以这个集合原本只有三个市场；上游 v3.29 把 _build_stats_block 的
# 盘面信号改成由 _supports_market_light() 闸住之后，漏掉 tw 会让台股复盘整组失去
# 盘面信号／信号依据／操作建议，且 tw,us 组合会误取美股分数当 primary。
# MARKET_LIGHT_ALERT_REGIONS 维持窄集合（告警范围另有文档约定），不随此处放宽。
MARKET_LIGHT_REGIONS = frozenset(("cn", "hk", "us", "tw"))


class MarketLightDimension(BaseModel):
    """A single Market Light scoring dimension."""

    score: int = Field(ge=0, le=100)
    available: bool


class MarketLightDimensions(BaseModel):
    """Canonical Market Light dimension scores."""

    breadth: MarketLightDimension
    index: MarketLightDimension
    limit: MarketLightDimension


class MarketLightSnapshot(BaseModel):
    """Structured Market Light snapshot persisted and consumed by alerts."""

    region: MarketRegion
    trade_date: str
    status: MarketLightStatus
    score: int = Field(ge=0, le=100)
    label: str
    temperature_label: str
    reasons: list[str]
    guidance: str
    dimensions: MarketLightDimensions
    data_quality: MarketLightDataQuality
