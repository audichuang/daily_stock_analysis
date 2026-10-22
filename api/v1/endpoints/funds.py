# -*- coding: utf-8 -*-
"""境內基金：查詢、淨值、前十大持股，以及帳本外的基金持倉。"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Path, Query

from api.v1.errors import api_error
from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.funds import (
    FundDetailResponse,
    FundHoldingCreateRequest,
    FundHoldingItem,
    FundHoldingListResponse,
    FundHoldingUpdateRequest,
    FundNavHistoryResponse,
    FundSearchResponse,
    FundTopHoldingsResponse,
)
from src.services.fund_service import FundNotFoundError, FundService, FundUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter()

_FUND_ID = Path(..., min_length=1, max_length=16, pattern=r"^[0-9A-Za-z]+$")
_ERRORS = {404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}


def _unavailable(exc: Exception):
    return api_error(503, "fund_data_unavailable", f"基金資料庫無法使用：{str(exc)[:200]}")


def _not_found(fund_id: str):
    return api_error(404, "fund_not_found", f"查無基金：{fund_id}")


@router.get("/search", response_model=FundSearchResponse, responses=_ERRORS,
            summary="搜尋境內基金（名稱、投信、統編、ISIN）")
def search_funds(q: str = Query(..., min_length=1, max_length=64),
                 limit: int = Query(20, ge=1, le=50)) -> FundSearchResponse:
    try:
        items = FundService().search(q, limit=limit)
    except FundUnavailableError as exc:
        raise _unavailable(exc)
    return FundSearchResponse(items=items)


@router.get("/holdings", response_model=FundHoldingListResponse, summary="基金持倉（以最新淨值估值）")
def list_fund_holdings() -> FundHoldingListResponse:
    return FundHoldingListResponse(**FundService().list_holdings())


@router.post("/holdings", response_model=FundHoldingItem, responses={**_ERRORS, 409: {"model": ErrorResponse}},
             summary="新增基金持倉")
def create_fund_holding(request: FundHoldingCreateRequest) -> FundHoldingItem:
    try:
        item = FundService().create_holding(**request.model_dump())
    except FundNotFoundError:
        raise _not_found(request.fund_id)
    except FundUnavailableError as exc:
        raise _unavailable(exc)
    except ValueError:
        raise api_error(409, "duplicate_holding", "同一通路已有這檔基金的持倉，請改用編輯")
    return FundHoldingItem(**item)


@router.put("/holdings/{holding_id}", response_model=FundHoldingItem, responses=_ERRORS, summary="更新基金持倉")
def update_fund_holding(holding_id: int, request: FundHoldingUpdateRequest) -> FundHoldingItem:
    item = FundService().update_holding(holding_id, **request.model_dump(exclude_none=True))
    if item is None:
        raise api_error(404, "not_found", f"查無持倉：{holding_id}")
    return FundHoldingItem(**item)


@router.delete("/holdings/{holding_id}", responses=_ERRORS, summary="刪除基金持倉")
def delete_fund_holding(holding_id: int) -> dict:
    if not FundService().delete_holding(holding_id):
        raise api_error(404, "not_found", f"查無持倉：{holding_id}")
    return {"deleted": 1}


@router.get("/{fund_id}", response_model=FundDetailResponse, responses=_ERRORS,
            summary="基金詳情（最新淨值、報酬、風險）")
def get_fund(fund_id: str = _FUND_ID) -> FundDetailResponse:
    try:
        return FundDetailResponse(**FundService().get_detail(fund_id))
    except FundNotFoundError:
        raise _not_found(fund_id)
    except FundUnavailableError as exc:
        raise _unavailable(exc)


@router.get("/{fund_id}/nav", response_model=FundNavHistoryResponse, responses=_ERRORS, summary="淨值歷史")
def get_fund_nav(fund_id: str = _FUND_ID,
                 days: Optional[int] = Query(None, ge=1, le=366 * 30),
                 period: Optional[Literal["w1", "m1", "m3", "m6", "y1", "y3", "y5", "ytd"]] = Query(
                     None, description="與報酬卡同一個基準點起算的區間；給了就忽略 days")) -> FundNavHistoryResponse:
    try:
        return FundNavHistoryResponse(**FundService().get_nav_history(fund_id, days=days, period=period))
    except FundNotFoundError:
        raise _not_found(fund_id)
    except FundUnavailableError as exc:
        raise _unavailable(exc)


@router.get("/{fund_id}/holdings", response_model=FundTopHoldingsResponse, responses=_ERRORS,
            summary="前十大持股（鉅亨即時，非官方）")
def get_fund_top_holdings(fund_id: str = _FUND_ID) -> FundTopHoldingsResponse:
    try:
        return FundTopHoldingsResponse(**FundService().get_top_holdings(fund_id))
    except FundNotFoundError:
        raise _not_found(fund_id)
    except FundUnavailableError as exc:
        raise _unavailable(exc)
