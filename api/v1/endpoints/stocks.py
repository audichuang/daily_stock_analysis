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
5. GET /api/v1/stocks/{code}/dossier 台股四維度分析報告（HTML）
6. GET /api/v1/stocks/dossier-summary 看板用台股四維度摘要（批次）
7. POST /api/v1/stocks/{code}/level-alerts 台股 SMC 價位警報（預設關閉，dry_run 可試算）
"""

import logging
import math
import threading
import time
from typing import Optional
import re

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, Depends
from fastapi.responses import HTMLResponse

from api.deps import get_system_config_service

from api.v1.schemas.stocks import (
    DossierSummaryItem,
    DossierSummaryResponse,
    LevelAlertRequest,
    LevelAlertResponse,
    ExtractFromImageResponse,
    ExtractItem,
    IntradayTrendBatchResponse,
    IntradayTrendItem,
    KLineData,
    StockHistoryResponse,
    FinancialCommentary,
    StockFinancialsResponse,
    StockProfileResponse,
    StockQuote,
    StockQuoteBatchItem,
    StockQuoteBatchResponse,
    StockTrendResponse,
    TrendPoint,
)
from api.v1.schemas.history import WatchlistRequest, WatchlistResponse
from api.v1.schemas.common import ErrorResponse
from api.v1.errors import api_error
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
from src.services.stock_service import StockService, normalize_source_code
from src.services.stock_profile_service import InvalidStockProfileCode, StockProfileService
from src.services.stock_list_parser import ParseStatus, parse_analysis_target
from src.services.run_diagnostics import sanitize_diagnostic_text
from src.services.stock_list_parser import split_stock_list
from src.services.system_config_service import SystemConfigService
from data_provider.base import normalize_stock_code
from data_provider.us_index_mapping import us_index_zh_tw_name

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
    return split_stock_list(stock_list_str)


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
    r"|\d{4,5}\.T"                            # Japan Yahoo suffix format
    r"|\d{6}\.(?:KS|KQ)"                     # Korea Yahoo suffix format
    # 4~6 digits plus at most one letter: 槓桿 00631L / 反向 00632R / 債券 ETF
    # 00679B / 特別股 2887A。與 market_symbol_utils.strip_optional_tw_letter
    # 同語意；normalize_stock_code 會把小寫尾字母正規化成大寫。
    r"|\d{4,6}[A-Z]?\.(?:TW|TWO)"           # Taiwan Yahoo suffix format
    r"|[A-Z]{1,5}(?:\.(?:US|[A-Z]))?"         # US ticker
    r")$",
    # re.ASCII is load-bearing: Python's ``\d`` is Unicode-aware by default, so
    # without it 全形/阿拉伯数字（``６００５１９``、``００７００.HK``、``٠٠٦٣١.TW``）都会通过这道
    # 闸门并带着无效字元流进下游 fetcher，而前端 validateStockCode 的 JS ``\d``
    # 本来就只认 ASCII —— 上面那句 "aligned with frontend" 只有加了这个 flag 才成立。
    re.IGNORECASE | re.ASCII,
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
    """Return the equivalence key used for watchlist add/remove matching.

    注册指数用它自己的 canonical 当 key。`000016.SH`（上证50）与同码个股 `000016`
    是两个不同的标的，但 `normalize_stock_code` 会把 `.SH` 后缀剥掉、两者都变成
    `000016`：於是自选里已有指数时再加同码个股会被当成重复而**静默丢弃**（API 仍回
    「已加入」），删其中一个则会删掉另一个。上游 #2312 已经让 Web 按 asset type
    分别渲染两列，後端这道等价键不跟上就是前後端各说各话。

    只有 INDEX 走 canonical：个股与解析不出来的输入保持原本的键，所以既有
    STOCK_LIST 里的股票条目不会被重新编码。
    """
    stripped = code.strip()
    target = parse_analysis_target(stripped)
    if target.asset_type == ParseStatus.INDEX:
        return target.canonical_id
    normalized = normalize_stock_code(stripped)
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
        # 只用来验证格式；等价键一律走**原始输入**（见下）。
        _validate_and_normalize_stock_code(request.stock_code)
        codes = _read_watchlist_codes(service)
        existing_keys = [_watchlist_match_key(c) for c in codes]
        # 既有条目的键是拿**存进去的原始字串**算的，请求端就不能拿正规化後的值算：
        # `_validate_and_normalize_stock_code("000016.SH")` 会把 `.SH` 剥成 `000016`，
        # 指数身分在算键之前就没了，於是删 `000016.SH` 会删掉同码的**个股**那一列。
        if _watchlist_match_key(request.stock_code) not in existing_keys:
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
        # 同 add：验证与等价键分开，键走原始输入才留得住指数身分。
        _validate_and_normalize_stock_code(request.stock_code)
        codes = _read_watchlist_codes(service)
        existing_keys = [_watchlist_match_key(c) for c in codes]
        requested_key = _watchlist_match_key(request.stock_code)
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
    "/intraday-trends",
    response_model=IntradayTrendBatchResponse,
    responses={
        200: {"description": "批次當日走勢"},
        400: {"description": "请求参数错误", "model": ErrorResponse},
    },
    summary="看板迷你分時：批次當日走勢",
    description="逗號分隔代碼；伺服器端快取 3 分鐘（輪詢不會逐檔打 kbars），單檔失敗回空 points＋error，整批仍 200。",
)
def get_intraday_trends(
    codes: str = Query(..., description="逗號分隔股票代碼，如 2330.TW,AAPL"),
) -> IntradayTrendBatchResponse:
    raw = [c.strip() for c in codes.split(",") if c.strip()]
    if not raw:
        raise api_error(400, "empty_codes", "codes 不能为空")
    if len(raw) > MAX_BATCH_CODES:      # 上限用原始輸入算，重複代碼繞不過
        raise api_error(400, "too_many_codes", f"最多 {MAX_BATCH_CODES} 个代码")
    parsed = list(dict.fromkeys(raw))
    rows = StockService().get_intraday_trends(parsed)
    return IntradayTrendBatchResponse(items=[IntradayTrendItem(**row) for row in rows])


@router.get(
    "/dossier-summary",
    response_model=DossierSummaryResponse,
    responses={
        200: {"description": "批次摘要"},
        400: {"description": "请求参数错误", "model": ErrorResponse},
    },
    summary="看板用台股四維度摘要",
    description="逗號分隔代碼；非台股或讀取失敗的單檔回 summary=null＋error，整批仍 200。不查分點、不呼叫 LLM。",
)
def get_dossier_summaries(
    codes: str = Query(..., description="逗號分隔股票代碼，如 2330.TW,3324.TWO"),
) -> DossierSummaryResponse:
    from src.services.market_symbol_utils import is_tw_suffix_symbol
    from src.services.tw_stock_watch import summaries

    raw = [c.strip() for c in codes.split(",") if c.strip()]
    if not raw:
        raise api_error(400, "empty_codes", "codes 不能为空")
    if len(raw) > MAX_BATCH_CODES:      # 上限用原始輸入算，重複代碼繞不過
        raise api_error(400, "too_many_codes", f"最多 {MAX_BATCH_CODES} 个代码")
    parsed = list(dict.fromkeys(c.upper() for c in raw))
    tw = [c for c in parsed if is_tw_suffix_symbol(c)]
    done = {code: (summary, error) for code, summary, error in summaries(tw)}
    return DossierSummaryResponse(level_alerts_enabled=_level_alerts_enabled(), items=[
        DossierSummaryItem(stock_code=c, summary=done[c][0], error=done[c][1]) if c in done
        else DossierSummaryItem(stock_code=c, error="unsupported_market")
        for c in parsed])


def _level_alerts_enabled() -> bool:
    from src.config import get_config

    return bool(getattr(get_config(), "tw_level_alerts_enabled", False))


@router.post(
    "/{stock_code}/level-alerts",
    response_model=LevelAlertResponse,
    responses={
        400: {"description": "非台股或價位不在今天的 SMC 價位裡", "model": ErrorResponse},
        409: {"description": "TW_LEVEL_ALERTS_ENABLED 未開啟（dry_run 不受限），或資料基準日之後有股價調整（levels_stale）", "model": ErrorResponse},
        503: {"description": "讀取 SMC 價位或寫入警報規則失敗（舊規則保留）", "model": ErrorResponse},
    },
    summary="建立台股 SMC 價位警報",
    description="把看板上的最近支撐／壓力建成 price_cross 規則，新規則全部建好才刪掉這檔舊的價位警報（建失敗時舊規則保留）；會寫應用庫。設計見 docs/tw-level-alerts.md。",
)
def create_level_alerts(stock_code: str, body: LevelAlertRequest) -> LevelAlertResponse:
    from src.services.market_symbol_utils import is_tw_suffix_symbol
    from src.services.tw_level_alerts import LevelAlertError, plan_rules, replace_rules
    from src.services.tw_stock_watch import _one

    code = stock_code.strip().upper()
    if not is_tw_suffix_symbol(code):
        raise api_error(400, "unsupported_market", f"{code} 不是台股代號（需帶 .TW／.TWO）")
    enabled = _level_alerts_enabled()
    if not body.dry_run and not enabled:
        raise api_error(409, "feature_disabled", "價位警報尚未開啟（TW_LEVEL_ALERTS_ENABLED=false）")
    try:
        summary = _one(code)
        picks = {"support": body.support and body.support.model_dump(),
                 "resistance": body.resistance and body.resistance.model_dump()}
        rules = plan_rules(code, picks, summary, name=summary.get("name"))
    except LevelAlertError as e:
        raise api_error(400, "level_mismatch", str(e))
    except LookupError as e:
        raise api_error(404, "not_found", str(e))
    except Exception as e:
        logger.error(f"讀取 SMC 價位失敗 {code}: {e}", exc_info=True)
        raise api_error(503, "level_alerts_unavailable", "讀取 SMC 價位失敗，請稍後再試")
    if summary.get("adjusted_after"):
        # 除權息／減資當天價位還是舊基準，照建會建出錯的觸發價；盤後資料更新才重算
        raise api_error(409, "levels_stale", "資料基準日之後有除權息或減資，價位要等盤後資料更新後再建立")
    if not body.dry_run:
        from src.services.alert_service import AlertServiceError

        try:
            rules = replace_rules(code, rules)
        except AlertServiceError as e:
            raise api_error(400, "invalid_rule", str(e))
        except Exception as e:
            logger.error(f"建立價位警報失敗 {code}: {e}", exc_info=True)
            raise api_error(503, "level_alerts_unavailable", "建立價位警報失敗，請稍後再試")
    return LevelAlertResponse(enabled=enabled, dry_run=body.dry_run, rules=rules)


@router.get(
    "/{stock_code}/profile",
    response_model=StockProfileResponse,
    responses={
        400: {"description": "股票代码无效", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取个股研究聚合档案",
    description="按独立质量状态聚合行情、历史、研究产物、资讯、持仓关系和监控规则。",
)
def get_stock_profile(
    stock_code: str,
    # 上限放到 1825：iOS 個股圖表要 5Y 區間；實際回溯約 days*2 個日曆日（见 BaseFetcher.get_daily_data）。
    history_days: int = Query(60, ge=1, le=1825, description="日线历史天数"),
) -> StockProfileResponse:
    """Return partial profile data without failing on one optional block."""
    _validate_and_normalize_stock_code(stock_code)
    try:
        return StockProfileResponse(
            **StockProfileService().get_profile(stock_code, history_days=history_days)
        )
    except InvalidStockProfileCode:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_stock_code", "message": "股票代码与交易所不匹配"},
        )
    except Exception as exc:
        sanitized = sanitize_diagnostic_text(str(exc), max_length=300) or "internal profile error"
        logger.error("获取个股研究聚合档案失败: %s", sanitized)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "获取个股研究聚合档案失败"},
        )


@router.get(
    "/market-status",
    responses={200: {"description": "各市場是否在輪詢時段"}},
    summary="看板輪詢用：市場是否開盤中",
    description="依交易所日曆（含假日、颱風假）回傳各市場是否在盤中（前後留緩衝）；未知市場或日曆異常一律回 open=true，不凍結看板。",
)
def get_market_status(
    markets: str = Query("tw", description="逗號分隔市場，如 tw,us"),
) -> dict:
    from src.core.trading_calendar import is_market_polling_window

    result = {
        m: is_market_polling_window(m)
        for m in dict.fromkeys(x.strip().lower() for x in markets.split(",") if x.strip())
    }
    return {"markets": result, "open": any(result.values()) if result else True}


_INDICES_CACHE_TTL_S = 60.0
_INDICES_CACHEABLE_REGIONS = frozenset({"cn", "hk", "us", "tw", "jp", "kr"})
_INDICES_CACHE: dict = {}
_INDICES_CACHE_LOCK = threading.Lock()


def _decorate_indices(rows: list, region: str) -> list:
    """追加 source_code、美股繁中名；非有限值改 null（yfinance 缺前一場時漲跌是 NaN，JSON 會 500）。"""
    items = []
    for row in rows:
        item = {
            key: None if isinstance(value, float) and not math.isfinite(value) else value
            for key, value in row.items()
        }
        item.setdefault("as_of", None)
        item.setdefault("source", None)
        item["source_code"] = normalize_source_code(item["source"])
        if region == "us":
            item["name"] = us_index_zh_tw_name(str(item.get("code") or "")) or item.get("name")
        items.append(item)
    return items


def _index_market_status(region: str) -> dict:
    """市場狀態每次現算，不進快取：開收盤的邊界不該晚 60 秒。"""
    try:
        from src.core.trading_calendar import MarketPhase, infer_market_phase

        phase = infer_market_phase(region)
    except Exception as e:
        logger.warning(f"判斷市場狀態失敗 region={region}: {e}")
        return {"market_phase": "unknown", "market_open": None}
    if phase == MarketPhase.UNKNOWN:
        return {"market_phase": phase.value, "market_open": None}
    open_phases = {MarketPhase.INTRADAY, MarketPhase.LUNCH_BREAK, MarketPhase.CLOSING_AUCTION}
    return {"market_phase": phase.value, "market_open": phase in open_phases}


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

        now = time.monotonic()
        with _INDICES_CACHE_LOCK:
            cached = _INDICES_CACHE.get(region)
        if cached is not None and cached[0] > now:
            items = cached[1]
        else:
            items = _decorate_indices(DataFetcherManager().get_main_indices(region) or [], region)
            # 空結果不快取：來源恢復後下一次輪詢就要拿得到。只快取已知市場，鍵不會無限長。
            if items and region in _INDICES_CACHEABLE_REGIONS:
                with _INDICES_CACHE_LOCK:
                    _INDICES_CACHE[region] = (now + _INDICES_CACHE_TTL_S, items)
        return {"items": [dict(item) for item in items], "region": region, **_index_market_status(region)}
    except Exception as e:
        logger.warning(f"获取大盘指数失败 region={region}: {e}")
        return {"items": [], "region": region, **_index_market_status(region)}


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
            source_code=normalize_source_code(source),
            degraded_reason=service.last_trend_degraded_reason,
            points=[TrendPoint(**p) for p in points],
        )
    except Exception as e:
        logger.error(f"获取走势失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"获取走势失败: {str(e)}"},
        )


@router.get(
    "/{stock_code}/financials",
    response_model=StockFinancialsResponse,
    responses={400: {"description": "股票代號格式不合法", "model": ErrorResponse}},
    summary="個股季度財報與 AI 導讀快取",
    description="台股讀本地 market.financial_statement；美股即時讀 SEC companyfacts、備援 yfinance。"
                "金額一律是 1 元財報幣別。只讀導讀快取，不會呼叫 LLM；缺資料以 status 表示，HTTP 仍是 200。",
)
def get_stock_financials(stock_code: str) -> StockFinancialsResponse:
    from src.services.financial_commentary import cached_view
    from src.services.stock_financials import build_financials

    payload = build_financials(_validate_and_normalize_stock_code(stock_code))
    return StockFinancialsResponse(**payload, commentary=cached_view(payload))


@router.post(
    "/{stock_code}/financials/commentary",
    response_model=FinancialCommentary,
    responses={400: {"description": "股票代號格式不合法", "model": ErrorResponse}},
    summary="取得或生成財報 AI 導讀",
    description="同一檔、同一財報期間、同一份數字只呼叫一次 LLM（約 20~60 秒）；"
                "開關關閉回 disabled，失敗回 failed，數字不受影響。",
)
def ensure_stock_financial_commentary(stock_code: str) -> FinancialCommentary:
    from src.services.financial_commentary import ensure_commentary
    from src.services.stock_financials import build_financials

    payload = build_financials(_validate_and_normalize_stock_code(stock_code))
    return FinancialCommentary(**ensure_commentary(payload))


@router.get(
    "/{stock_code}/dossier",
    response_class=HTMLResponse,
    responses={
        200: {"description": "報告 HTML"},
        400: {"description": "不是台股代號，或 date 不是有效日期", "model": ErrorResponse},
        404: {"description": "本地行情查無此股", "model": ErrorResponse},
        503: {"description": "台股資料庫不可用", "model": ErrorResponse},
    },
    summary="台股個股四維度分析報告",
    description="基本面、合約負債、籌碼、估值、SMC 技術結構的單頁 HTML；narrative=true 時附 LLM 解讀（依資料基準日快取），失敗只降級成純數字。",
)
def get_stock_dossier(
    stock_code: str,
    narrative: bool = Query(False, description="是否附 LLM 解讀"),
    theme: Optional[str] = Query(None, pattern="^(light|dark)$", description="頁面主題"),
    date: Optional[str] = Query(None, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", description="資料基準日 YYYY-MM-DD"),
) -> HTMLResponse:
    from datetime import date as _date

    from src.services.tw_stock_report import UnsupportedMarket, report_html

    if date:
        try:
            _date.fromisoformat(date)      # 正則擋不住 2026-13-45 這種不存在的日期
        except ValueError:
            raise api_error(400, "invalid_date", f"{date} 不是有效日期")
    try:
        return HTMLResponse(report_html(stock_code, narrative=narrative, theme=theme, as_of=date))
    except UnsupportedMarket as e:
        raise api_error(400, "unsupported_market", str(e))
    except LookupError as e:
        raise api_error(404, "not_found", str(e))
    except Exception as e:
        logger.error(f"產生台股分析報告失敗 {stock_code}: {e}", exc_info=True)
        raise api_error(503, "dossier_unavailable", "產生台股分析報告失敗，請稍後再試")
