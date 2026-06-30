# -*- coding: utf-8 -*-
"""
===================================
股票数据接口
===================================

职责：
1. POST /api/v1/stocks/extract-from-image 从图片提取股票代码
2. POST /api/v1/stocks/parse-import 解析 CSV/Excel/剪贴板
3. GET /api/v1/stocks/{code}/quote 实时行情接口
4. GET /api/v1/stocks/{code}/history 历史行情接口
"""

import logging
from typing import Optional
import re

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, Depends

from api.deps import get_system_config_service

from api.v1.schemas.stocks import (
    ExtractFromImageResponse,
    ExtractItem,
    KLineData,
    StockHistoryResponse,
    StockQuote,
    StockQuoteBatchItem,
    StockQuoteBatchResponse,
    StockTrendResponse,
    TrendPoint,
)
from api.v1.schemas.history import WatchlistRequest, WatchlistResponse
from api.v1.schemas.common import ErrorResponse
from src.services.image_stock_extractor import (
    ALLOWED_MIME,
    MAX_SIZE_BYTES,
    extract_stock_codes_from_image,
)
from src.services.import_parser import (
    MAX_FILE_BYTES,
    parse_import_from_bytes,
    parse_import_from_text,
)
from src.services.stock_service import StockService
from src.services.system_config_service import SystemConfigService
from data_provider.base import normalize_stock_code

logger = logging.getLogger(__name__)

router = APIRouter()

# 须在 /{stock_code} 路由之前定义
ALLOWED_MIME_STR = ", ".join(ALLOWED_MIME)

# 批次行情单次最大代码数（看板 watchlist 量级；超出回 400 而非静默截断）
MAX_BATCH_CODES = 50


def _read_watchlist_codes(service: SystemConfigService) -> list:
    """Read STOCK_LIST codes as-is (no normalization)."""
    config_data = service.get_config(include_schema=False)
    stock_list_str = ""
    for item in config_data.get("items", []):
        if item.get("key") == "STOCK_LIST":
            stock_list_str = str(item.get("value", ""))
            break
    return [c.strip() for c in stock_list_str.split(",") if c.strip()]


def _write_watchlist_codes(service: SystemConfigService, codes: list) -> None:
    """Persist stock codes to STOCK_LIST as-is (no normalization)."""
    config_data = service.get_config(include_schema=False)
    config_version = config_data.get("config_version", "")
    service.update(
        config_version=config_version,
        items=[{"key": "STOCK_LIST", "value": ",".join(codes)}],
        mask_token="******",
        reload_now=True,
    )


# Stock code validation patterns (aligned with frontend validateStockCode)
_STOCK_CODE_RE = re.compile(
    r"^(?:\d{6}"                              # A-share 6-digit
    r"|(?:SH|SZ|BJ)\d{6}"                     # exchange-prefixed A-share
    r"|\d{6}\.(?:SH|SZ|SS|BJ)"                # exchange-suffixed A-share
    r"|\d{1,5}\.HK"                           # HK suffix format
    r"|HK\d{1,5}"                             # HK prefix format
    r"|\d{5}"                                 # bare 5-digit HK code
    r"|\d{4}\.(?:TW|TWO)"                      # Taiwan Yahoo suffix format
    r"|[A-Z]{1,5}(?:\.(?:US|[A-Z]))?"         # US ticker
    r")$",
    re.IGNORECASE,
)


def _validate_and_normalize_stock_code(code: str) -> str:
    """Validate stock code format and return canonical form.

    Raises HTTPException(400) if the code does not match supported formats.
    """
    stripped = code.strip()
    if not stripped:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_stock_code", "message": "股票代码不能为空"},
        )
    if not _STOCK_CODE_RE.match(stripped):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_stock_code",
                "message": f"'{stripped}' 不是合法的股票代码格式",
            },
        )
    return normalize_stock_code(stripped)


def _watchlist_match_key(code: str) -> str:
    """Return the equivalence key used for watchlist add/remove matching."""
    normalized = normalize_stock_code(code.strip())
    if re.fullmatch(r"\d{5}", normalized):
        return f"HK{normalized}"
    return normalized.upper()


@router.post(
    "/extract-from-image",
    response_model=ExtractFromImageResponse,
    responses={
        200: {"description": "提取的股票代码"},
        400: {"description": "图片无效", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="从图片提取股票代码",
    description="上传截图/图片，通过 Vision LLM 提取股票代码。支持 JPEG、PNG、WebP、GIF，最大 5MB。",
)
def extract_from_image(
    file: Optional[UploadFile] = File(None, description="图片文件（表单字段名 file）"),
    include_raw: bool = Query(False, description="是否在结果中包含原始 LLM 响应"),
) -> ExtractFromImageResponse:
    """
    从上传的图片中提取股票代码（使用 Vision LLM）。

    表单字段请使用 file 上传图片。优先级：Gemini / Anthropic / OpenAI（首个可用）。
    """
    if not file or not file.filename:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_request", "message": "未提供文件，请使用表单字段 file 上传图片"},
        )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_type",
                "message": f"不支持的类型: {content_type}。允许: {ALLOWED_MIME_STR}",
            },
        )

    try:
        # 先读取限定大小，再检查是否还有剩余（语义清晰：超出则拒绝）
        data = file.file.read(MAX_SIZE_BYTES)
        if file.file.read(1):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_too_large",
                    "message": f"图片超过 {MAX_SIZE_BYTES // (1024 * 1024)}MB 限制",
                },
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"读取上传文件失败: {e}")
        raise HTTPException(
            status_code=400,
            detail={"error": "read_failed", "message": "读取上传文件失败"},
        )

    try:
        items, raw_text = extract_stock_codes_from_image(data, content_type)
        extract_items = [
            ExtractItem(code=code, name=name, confidence=conf) for code, name, conf in items
        ]
        codes = [i.code for i in extract_items]
        return ExtractFromImageResponse(
            codes=codes,
            items=extract_items,
            raw_text=raw_text if include_raw else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": "extract_failed", "message": str(e)})
    except Exception as e:
        logger.error(f"图片提取失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "图片提取失败"},
        )


@router.post(
    "/parse-import",
    response_model=ExtractFromImageResponse,
    responses={
        200: {"description": "解析结果"},
        400: {"description": "未提供数据或解析失败", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="解析 CSV/Excel/剪贴板",
    description="上传 CSV/Excel 文件或粘贴文本，自动解析股票代码。文件上限 2MB，文本上限 100KB。",
)
async def parse_import(request: Request) -> ExtractFromImageResponse:
    """
    解析 CSV/Excel 文件或剪贴板文本。

    - multipart/form-data + file: 上传文件
    - application/json + {"text": "..."}: 粘贴文本
    - 优先使用 file，若同时提供则忽略 text
    """
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception as e:
            logger.warning("[parse_import] JSON parse failed: %s", e)
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_json", "message": f"JSON 解析失败: {e}"},
            )
        text = body.get("text") if isinstance(body, dict) else None
        if not text or not isinstance(text, str):
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_request", "message": "未提供 text，请使用 {\"text\": \"...\"}"},
            )
        try:
            items = parse_import_from_text(text)
        except ValueError as e:
            text_bytes = len(text.encode("utf-8"))
            logger.warning(
                "[parse_import] parse_import_from_text failed: text_bytes=%d, error=%s",
                text_bytes,
                e,
            )
            raise HTTPException(status_code=400, detail={"error": "parse_failed", "message": str(e)})
    elif "multipart" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file or not hasattr(file, "read"):
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_request", "message": "未提供文件，请使用表单字段 file"},
            )
        file_size = getattr(file, "size", None)
        if isinstance(file_size, int) and file_size > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_too_large",
                    "message": f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)}MB 限制",
                },
            )
        try:
            data = file.file.read(MAX_FILE_BYTES)
            if file.file.read(1):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "file_too_large",
                        "message": f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)}MB 限制",
                    },
                )
        except HTTPException:
            raise
        except Exception as e:
            filename = getattr(file, "filename", None) or ""
            size = getattr(file, "size", None)
            logger.warning(
                "[parse_import] file read failed: filename=%r, size=%s, error=%s",
                filename,
                size,
                e,
            )
            raise HTTPException(
                status_code=400,
                detail={"error": "read_failed", "message": "读取文件失败"},
            )
        filename = getattr(file, "filename", None) or ""
        try:
            items = parse_import_from_bytes(data, filename=filename)
        except ValueError as e:
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            logger.warning(
                "[parse_import] parse_import_from_bytes failed: filename=%r, ext=%r, bytes=%d, error=%s",
                filename,
                ext,
                len(data),
                e,
            )
            raise HTTPException(status_code=400, detail={"error": "parse_failed", "message": str(e)})
    else:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": "请使用 multipart/form-data 上传文件，或 application/json 提交 {\"text\": \"...\"}",
            },
        )

    extract_items = [
        ExtractItem(code=code, name=name, confidence=conf)
        for code, name, conf in items
    ]
    codes = list(dict.fromkeys(i.code for i in extract_items if i.code))
    return ExtractFromImageResponse(codes=codes, items=extract_items, raw_text=None)


@router.get(
    "/watchlist",
    response_model=WatchlistResponse,
    responses={
        200: {"description": "当前自选队列"},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取自选队列",
    description="返回当前 STOCK_LIST 配置中的所有股票代码。",
)
def get_watchlist(
    service: SystemConfigService = Depends(get_system_config_service),
) -> WatchlistResponse:
    try:
        codes = _read_watchlist_codes(service)
        return WatchlistResponse(stock_codes=codes, message=f"当前自选 {len(codes)} 只股票")
    except Exception as e:
        logger.error(f"获取自选队列失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"获取自选队列失败: {str(e)}"},
        )


@router.post(
    "/watchlist/add",
    response_model=WatchlistResponse,
    responses={
        200: {"description": "已加入自选"},
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="加入自选队列",
    description="将指定股票代码加入 STOCK_LIST。",
)
def add_to_watchlist(
    request: WatchlistRequest,
    service: SystemConfigService = Depends(get_system_config_service),
) -> WatchlistResponse:
    try:
        validated = _validate_and_normalize_stock_code(request.stock_code)
        codes = _read_watchlist_codes(service)
        existing_keys = [_watchlist_match_key(c) for c in codes]
        if _watchlist_match_key(validated) not in existing_keys:
            codes.append(request.stock_code.strip())
            _write_watchlist_codes(service, codes)
        return WatchlistResponse(stock_codes=codes, message=f"已加入 {request.stock_code.strip()}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"加入自选失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"加入自选失败: {str(e)}"},
        )


@router.post(
    "/watchlist/remove",
    response_model=WatchlistResponse,
    responses={
        200: {"description": "已从自选删除"},
        400: {"description": "参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="从自选队列删除",
    description="从 STOCK_LIST 中移除指定股票代码。",
)
def remove_from_watchlist(
    request: WatchlistRequest,
    service: SystemConfigService = Depends(get_system_config_service),
) -> WatchlistResponse:
    try:
        validated = _validate_and_normalize_stock_code(request.stock_code)
        codes = _read_watchlist_codes(service)
        existing_keys = [_watchlist_match_key(c) for c in codes]
        requested_key = _watchlist_match_key(validated)
        if requested_key in existing_keys:
            idx = existing_keys.index(requested_key)
            codes.pop(idx)
            _write_watchlist_codes(service, codes)
        return WatchlistResponse(stock_codes=codes, message=f"已移除 {request.stock_code.strip()}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"从自选删除失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"从自选删除失败: {str(e)}"},
        )


@router.get(
    "/quotes",
    response_model=StockQuoteBatchResponse,
    responses={
        200: {"description": "批次行情数据"},
        400: {"description": "请求参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="批量获取实时行情",
    description="逗号分隔代码批量取价，单个失败回 quote=null（看板用，永不 500 整批）"
)
def get_stock_quotes(
    codes: str = Query(..., description="逗号分隔股票代码，如 2330.TW,2317.TW,AAPL"),
) -> StockQuoteBatchResponse:
    """批量实时行情。

    单个代码无数据 -> quote=None, error="no_data"（不用 0.0 哨兵伪装真实价）。
    """
    # 解析：split -> strip -> 去空 -> 去重保序
    parsed: list = []
    seen = set()
    for raw in codes.split(","):
        code = raw.strip()
        if not code or code in seen:
            continue
        seen.add(code)
        parsed.append(code)

    if not parsed:
        raise HTTPException(
            status_code=400,
            detail={"error": "empty_codes", "message": "codes 不能为空"},
        )
    if len(parsed) > MAX_BATCH_CODES:
        raise HTTPException(
            status_code=400,
            detail={"error": "too_many_codes", "message": f"最多 {MAX_BATCH_CODES} 个代码"},
        )

    try:
        service = StockService()
        rows = service.get_realtime_quotes(parsed)
        items = []
        for code, row in zip(parsed, rows):
            if row is None:
                items.append(StockQuoteBatchItem(stock_code=code, quote=None, error="no_data"))
                continue
            try:
                items.append(StockQuoteBatchItem(stock_code=code, quote=StockQuote(**row)))
            except Exception as e:  # 单列构造失败也不拖垮整批
                logger.warning(f"批次行情构造失败 {code}: {e}")
                items.append(StockQuoteBatchItem(stock_code=code, quote=None, error=str(e)[:200]))
        return StockQuoteBatchResponse(items=items)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量获取实时行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"批量获取行情失败: {str(e)}"},
        )


@router.get(
    "/indices",
    responses={200: {"description": "大盘指数列表"}},
    summary="获取大盘指数实时行情",
    description="返回指定地区主要指数（台股：加权指数 TWII + 柜买指数 TPEX）。盯盘辅助资料，失败回空列表，永不 500。",
)
def get_main_indices(
    region: str = Query("tw", description="地区，如 tw/cn/us/hk"),
) -> dict:
    """大盘指数列表（盯盘辅助）。失败 fail-open 回空列表，不拖垮页面。"""
    try:
        # 与 StockService.get_realtime_quotes 同款：每请求自建 manager 可接受
        from data_provider.base import DataFetcherManager

        data = DataFetcherManager().get_main_indices(region)
        return {"items": data or [], "region": region}
    except Exception as e:
        logger.warning(f"获取大盘指数失败 region={region}: {e}")
        return {"items": [], "region": region}


@router.get(
    "/{stock_code}/quote",
    response_model=StockQuote,
    responses={
        200: {"description": "行情数据"},
        404: {"description": "股票不存在", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票实时行情",
    description="获取指定股票的最新行情数据"
)
def get_stock_quote(stock_code: str) -> StockQuote:
    """
    获取股票实时行情
    
    获取指定股票的最新行情数据
    
    Args:
        stock_code: 股票代码（如 600519、00700、AAPL）
        
    Returns:
        StockQuote: 实时行情数据
        
    Raises:
        HTTPException: 404 - 股票不存在
    """
    try:
        service = StockService()
        
        # 使用 def 而非 async def，FastAPI 自动在线程池中执行
        result = service.get_realtime_quote(stock_code)
        
        if result is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"未找到股票 {stock_code} 的行情数据"
                }
            )
        
        # result 来自 _map_quote_to_dict / _get_placeholder_quote，键与 StockQuote 字段一一对应
        # （含新增的 source/as_of/is_stale），直接展开，避免显式 kwargs 漏带新字段。
        result.setdefault("stock_code", stock_code)
        return StockQuote(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取实时行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取实时行情失败: {str(e)}"
            }
        )


@router.get(
    "/{stock_code}/history",
    response_model=StockHistoryResponse,
    responses={
        200: {"description": "历史行情数据"},
        422: {"description": "不支持的周期参数", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票历史行情",
    description="获取指定股票的历史 K 线数据"
)
def get_stock_history(
    stock_code: str,
    period: str = Query("daily", description="K 线周期", pattern="^(daily|weekly|monthly)$"),
    days: int = Query(30, ge=1, le=365, description="获取天数")
) -> StockHistoryResponse:
    """
    获取股票历史行情
    
    获取指定股票的历史 K 线数据
    
    Args:
        stock_code: 股票代码
        period: K 线周期 (daily/weekly/monthly)
        days: 获取天数
        
    Returns:
        StockHistoryResponse: 历史行情数据
    """
    try:
        service = StockService()
        
        # 使用 def 而非 async def，FastAPI 自动在线程池中执行
        result = service.get_history_data(
            stock_code=stock_code,
            period=period,
            days=days
        )
        
        # 转换为响应模型
        data = [
            KLineData(
                date=item.get("date"),
                open=item.get("open"),
                high=item.get("high"),
                low=item.get("low"),
                close=item.get("close"),
                volume=item.get("volume"),
                amount=item.get("amount"),
                change_percent=item.get("change_percent")
            )
            for item in result.get("data", [])
        ]
        
        return StockHistoryResponse(
            stock_code=stock_code,
            stock_name=result.get("stock_name"),
            period=period,
            data=data
        )
    
    except ValueError as e:
        # period 参数不支持的错误（如 weekly/monthly）
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_period",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"获取历史行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取历史行情失败: {str(e)}"
            }
        )


@router.get(
    "/{stock_code}/trend",
    response_model=StockTrendResponse,
    responses={
        200: {"description": "价格走势折线"},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票价格走势（折线）",
    description="range=day 今日分时 / month 近一月日线 / year 近一年日线；失败回空 points"
)
def get_stock_trend(
    stock_code: str,
    range: str = Query("month", description="走势范围", pattern="^(day|month|year)$"),
) -> StockTrendResponse:
    """价格走势折线（看板 inline 图用）。取数失败回空 points，不抛 500（除非内部异常）。"""
    try:
        service = StockService()
        points, source = service.get_price_trend(stock_code, range)
        return StockTrendResponse(
            stock_code=stock_code,
            range=range,
            source=source,
            points=[TrendPoint(**p) for p in points],
        )
    except Exception as e:
        logger.error(f"获取走势失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"获取走势失败: {str(e)}"},
        )
