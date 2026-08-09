# -*- coding: utf-8 -*-
"""Structured Market Light snapshot schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MarketRegion = Literal["cn", "hk", "us", "tw", "jp", "kr"]
MarketLightStatus = Literal["green", "yellow", "red"]
MarketLightDataQuality = Literal["ok", "partial", "unavailable"]
# 可以「评出分数」的市场，比大盘复盘覆盖的市场窄。
# 注意评分器有三个维度（breadth／index／limit），任一可用即可评分——jp/kr 走的就是
# index-only，所以「需要涨跌家数」的说法不准确；窄的原因是这些市场的取数链路与
# 阈值校准只对这四个做过。
# **与 `src.services.market_light_service.MARKET_LIGHT_REGIONS` 同名但不同契约**
# （那个是可查询快照的市场，等于全部复盘市场）。上游就是这样命名的，改名会在每次
# 合并上游时付代价，所以两边各自注明差异。
#
# 台股在此 fork 有完整涨跌家数与成交额（TWSE/TPEx OpenAPI），足以评分；上游没有 tw。
# 上游 v3.29 把 _build_stats_block 的盘面信号改成由 _supports_market_light() 闸住
# 之后，漏掉 tw 会让台股复盘整组失去盘面信号／信号依据／操作建议，且 tw,us 组合会
# 误取美股分数当 primary。MARKET_LIGHT_ALERT_REGIONS 维持窄集合，不随此处放宽。
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
