# -*- coding: utf-8 -*-
"""境內基金 API schemas。缺值一律 null，不用 0 冒充。"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field

FUND_ID = Field(..., min_length=1, max_length=16, pattern=r"^[0-9A-Za-z]+$")


class FundSearchItem(BaseModel):
    fund_id: str
    name: str
    company: Optional[str] = None
    isin: Optional[str] = None
    type_code: Optional[str] = None
    type_name: Optional[str] = None
    currency: Optional[str] = None
    nav: Optional[float] = None
    nav_date: Optional[date] = None


class FundSearchResponse(BaseModel):
    items: List[FundSearchItem] = Field(default_factory=list)


class FundReturns(BaseModel):
    """各期間報酬率（%），以淨值日對淨值日計算、未含配息；期間不足為 null。"""

    w1: Optional[float] = None
    m1: Optional[float] = None
    m3: Optional[float] = None
    m6: Optional[float] = None
    ytd: Optional[float] = None
    y1: Optional[float] = None
    y3: Optional[float] = None
    y5: Optional[float] = None


class FundRisk(BaseModel):
    """近一年最大回撤（%，負值）與年化波動率（%）。"""

    max_drawdown: Optional[float] = None
    volatility: Optional[float] = None


class FundDetailResponse(BaseModel):
    fund_id: str
    name: str
    company: Optional[str] = None
    isin: Optional[str] = None
    sitca_code: Optional[str] = None
    type_code: Optional[str] = None
    type_name: Optional[str] = None
    invest_area: Optional[str] = None
    currency: Optional[str] = None
    inception_date: Optional[date] = None
    aum: Optional[float] = None
    aum_currency: Optional[str] = None
    aum_date: Optional[date] = None
    dividend_policy: Optional[str] = None
    nav: Optional[float] = None
    nav_date: Optional[date] = None
    nav_change: Optional[float] = None
    nav_change_pct: Optional[float] = None
    nav_source: Optional[str] = None
    is_stale: bool = True
    history_start: Optional[date] = None
    history_points: int = 0
    history_error: Optional[str] = None
    returns: FundReturns
    risk: FundRisk


class FundNavPoint(BaseModel):
    date: date
    nav: float


class FundBenchmarkPoint(BaseModel):
    date: date
    close: float


class FundBenchmark(BaseModel):
    index_id: str
    points: List[FundBenchmarkPoint] = Field(default_factory=list)


class FundNavHistoryResponse(BaseModel):
    fund_id: str
    points: List[FundNavPoint] = Field(default_factory=list)
    benchmark: Optional[FundBenchmark] = None  # 帶 benchmark=taiex 才有；同區間的指數收盤，未重設基期
    benchmark_error: Optional[str] = None  # source_unavailable | no_data


class FundTopHolding(BaseModel):
    name: Optional[str] = None
    sector: Optional[str] = None
    weight: Optional[float] = None
    country: Optional[str] = None
    ledger_symbol: Optional[str] = None  # 名稱唯一對到帳本持股才有；對不到就不標


class FundOverlapItem(BaseModel):
    symbol: str
    name: Optional[str] = None
    weight: Optional[float] = None


class FundTopHoldingsResponse(BaseModel):
    fund_id: str
    items: List[FundTopHolding] = Field(default_factory=list)
    error: Optional[str] = None  # source_unavailable | not_mapped
    as_of_month: Optional[str] = None  # 持股資料月份 YYYY-MM；來源沒給為 null
    overlap: List[FundOverlapItem] = Field(default_factory=list)


class FundHoldingCreateRequest(BaseModel):
    fund_id: str = FUND_ID
    units: float = Field(..., gt=0)
    cost_total: float = Field(..., ge=0)
    as_of: date
    platform: str = Field("", max_length=64)
    note: Optional[str] = Field(None, max_length=255)


class FundHoldingUpdateRequest(BaseModel):
    units: Optional[float] = Field(None, gt=0)
    cost_total: Optional[float] = Field(None, ge=0)
    as_of: Optional[date] = None
    platform: Optional[str] = Field(None, max_length=64)
    note: Optional[str] = Field(None, max_length=255)


class FundHoldingItem(BaseModel):
    id: int
    platform: str
    fund_id: str
    fund_name: str
    units: float
    cost_total: float
    currency: str
    as_of: date
    note: Optional[str] = None
    nav: Optional[float] = None
    nav_date: Optional[date] = None
    is_stale: bool = True
    market_value: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    nav_change_pct: Optional[float] = None  # 最新淨值相對前一筆；過期或缺前一筆為 null
    day_pnl: Optional[float] = None


class FundHoldingTotal(BaseModel):
    currency: str
    cost_total: float
    market_value: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    day_pnl: Optional[float] = None  # 有一檔算不出就是 null


class FundHoldingListResponse(BaseModel):
    items: List[FundHoldingItem] = Field(default_factory=list)
    totals: List[FundHoldingTotal] = Field(default_factory=list)
    nav_error: Optional[str] = None
