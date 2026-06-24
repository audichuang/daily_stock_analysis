# -*- coding: utf-8 -*-
"""
===================================
ShioajiFetcher - 台股 Shioaji 真即时报价数据源（仅 realtime_quote）
===================================

金钥由 Doppler 注入（project shioaji, config dev）：SHIOAJI_API_KEY / SHIOAJI_SECRET_KEY。
查行情不需 CA 凭证。未安装 shioaji 套件 / 无金钥 → is_available_for_request 返回 False，
DataFetcherManager 零网络代价跳过，台股自动降级 yfinance。

设计要点（session 生命周期是本数据源最大的坑）：
1. 模组级持久 session：登入慢且有每日次数上限，绝不每次请求重登。
   - double-checked locking 防冷启并发双登入。
   - 登入/快照各有硬 timeout（futures），防 SDK 卡死拖垮 FastAPI 线程池。
   - 快照不持 _SESSION_LOCK（否则整批被序列化成一条 mutex，造成延迟悬崖）。
2. 熔断器（_login_breaker）只在 _attempt_login 这唯一一处交互：
   - is_available() 仅此处调用一次（消耗半开探测名额），与 record 一一配对。
   - is_available_for_request **不读熔断器**：CircuitBreaker 的 OPEN→HALF_OPEN 时间转移
     只发生在 is_available() 内（get_status 是惰性纯读不触发），若把 get_status=="open"
     当 gate 会永久卡在 OPEN 无法恢复。故冷却中靠 _attempt_login 内的 is_available() 拦下
     （零登入），冷却到期自动半开重试。
3. 熔断 key 以「端到端拿到 quote」为准：登入成功但快照空（午休/收盘无 tick）→
   record_inconclusive（半开转回 OPEN，避免假复原），而非 record_success。
4. 仅服务 realtime_quote：不参与日线/统计路由（_DAILY_MARKET_FETCHER_SUPPORT 映射为空集合，
   不实现真实的 _fetch_raw_data / _normalize_data）。
"""

import importlib.util
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from .base import BaseFetcher
from .realtime_types import (
    CircuitBreaker,
    RealtimeSource,
    UnifiedRealtimeQuote,
    safe_float,
    safe_int,
)

logger = logging.getLogger(__name__)

_BREAKER_KEY = "shioaji_login"
_LOGIN_TIMEOUT_S = 20.0
_SNAPSHOT_TIMEOUT_S = 8.0

# --- 模组级持久 session 状态 ---------------------------------------------
_SESSION_LOCK = threading.RLock()
_api: Optional[Any] = None
_logged_in = False
_logout_registered = False
# 专属登入熔断器（非全域 realtime breaker）：连续 2 次失败熔断、冷却 900s（对应每日登入上限场景）。
# ponytail: 进程内 in-memory breaker 对单一长驻 serve 进程足够；若实测多进程共享同一帐号燒额度，
# 再加「持久化每日登入计数」（文件/redis）——目前 YAGNI。
_login_breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=900.0, half_open_max_calls=1)
# shioaji 套件能否导入（运行时不变，一次性求值；测试可 monkeypatch 此模组全局）
_HAS_SHIOAJI = importlib.util.find_spec("shioaji") is not None
# 登入/快照的硬 deadline 执行器；线程短任务，进程退出前自然回收。
# ponytail: Future.result(timeout) 只让调用方超时返回（随后降级 yfinance），并不能 cancel/kill
# 一个真正卡死的 SDK 调用——若两个调用永久 wedge 会占满 worker、后续调用排队后超时。
# 实测出现 SDK 永久卡死再升级为「可杀的子进程隔离」；目前 YAGNI（登入有 timeout、调用序列化）。
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="shioaji")


def _credentials() -> tuple:
    """运行时读取金钥（Doppler 注入），不在 __init__ 缓存以免 worker 间状态陈旧。"""
    return (
        (os.getenv("SHIOAJI_API_KEY") or "").strip(),
        (os.getenv("SHIOAJI_SECRET_KEY") or "").strip(),
    )


def _logout_at_exit() -> None:
    """best-effort 登出：非阻塞取锁，拿不到就放弃（避免 kill 时持锁卡住 shutdown）。"""
    global _api, _logged_in
    if not _SESSION_LOCK.acquire(blocking=False):
        return
    try:
        if _api is not None:
            try:
                _api.logout()
            except Exception:
                pass
        _api = None
        _logged_in = False
    finally:
        _SESSION_LOCK.release()


def _attempt_login() -> Optional[Any]:
    """唯一碰熔断器与真正 login 的地方；必须在 _SESSION_LOCK 内调用。

    返回可用 api 或 None。半开探测名额在此消耗，与下游 record_* 一一配对。
    """
    global _api, _logged_in, _logout_registered
    # 先验金钥：无金钥的直呼/竞态不应消耗熔断器半开探测名额（否则 is_available 占用名额却无 record 配对）。
    api_key, secret_key = _credentials()
    if not api_key or not secret_key:
        return None
    # 冷却中/半开名额已用尽 → 立即 None（零登入），这也是冷却期不 relogin-storm 的关键。
    if not _login_breaker.is_available(_BREAKER_KEY):
        return None
    try:
        import shioaji as sj
    except ImportError as e:
        logger.warning("[ShioajiFetcher] shioaji 套件导入失败: %s", e)
        _login_breaker.record_failure(_BREAKER_KEY, str(e)[:200])
        return None
    try:
        api = sj.Shioaji()
        fut = _executor.submit(api.login, api_key=api_key, secret_key=secret_key)
        fut.result(timeout=_LOGIN_TIMEOUT_S)
    except Exception as e:
        logger.warning("[ShioajiFetcher] 登入失败/超时: %s", type(e).__name__)
        _login_breaker.record_failure(_BREAKER_KEY, str(e)[:200])
        _api = None
        _logged_in = False
        return None
    _api = api
    _logged_in = True
    if not _logout_registered:
        import atexit

        atexit.register(_logout_at_exit)
        _logout_registered = True
    logger.info("[ShioajiFetcher] 登入成功，建立持久 session")
    # 不在此 record_success：成功与否以最终拿到合法 quote 为准（见 get_realtime_quote）。
    return api


def _ensure_session() -> Optional[Any]:
    """double-checked locking：无锁快路径 + 锁内复查，避免冷启并发双登入。"""
    if _logged_in and _api is not None:
        return _api
    with _SESSION_LOCK:
        if _logged_in and _api is not None:
            return _api
        return _attempt_login()


def _reset_for_tests() -> None:
    """清模组级状态 + 熔断器（供测试隔离）。"""
    global _api, _logged_in, _logout_registered
    with _SESSION_LOCK:
        _api = None
        _logged_in = False
        _logout_registered = False
    _login_breaker.reset()


class ShioajiFetcher(BaseFetcher):
    """台股 Shioaji 真即时报价（仅 realtime_quote，不参与日线/统计路由）。"""

    name = "ShioajiFetcher"
    # 数字越小越优先；台股 realtime 优先于 yfinance（priority 4）。
    priority = 50

    def __init__(self):
        if not _HAS_SHIOAJI:
            logger.info("[ShioajiFetcher] 未安装 shioaji 套件，台股实时将降级 yfinance")

    # --- 仅服务 realtime_quote；不读熔断器（理由见模组 docstring 第 2 点） --------
    def is_available_for_request(self, capability: str = "") -> bool:
        if capability != "realtime_quote":
            return False
        if not _HAS_SHIOAJI:
            return False
        api_key, secret_key = _credentials()
        return bool(api_key and secret_key)

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError("ShioajiFetcher 仅提供实时报价，不支持日线数据")

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raise NotImplementedError("ShioajiFetcher 仅提供实时报价，不支持日线数据")

    @staticmethod
    def _tw_code(stock_code: str) -> str:
        """2330.TW / 2330.TWO / 2330 → 2330。"""
        code = (stock_code or "").strip().upper()
        for suffix in (".TWO", ".TW"):
            if code.endswith(suffix):
                return code[: -len(suffix)]
        return code

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        global _api, _logged_in
        if not _HAS_SHIOAJI:
            return None
        api = _ensure_session()
        if api is None:
            return None

        code = self._tw_code(stock_code)
        # 查合约：查无属 transient（非 session 死），不记 breaker failure。
        try:
            contract = api.Contracts.Stocks[code]
        except Exception as e:
            logger.debug("[ShioajiFetcher] 合约查询失败 %s: %s", code, e)
            return None
        if contract is None:
            return None

        # 快照：不持 _SESSION_LOCK（避免整批序列化）；硬 timeout 防 SDK 卡死。
        try:
            fut = _executor.submit(api.snapshots, [contract])
            snaps = fut.result(timeout=_SNAPSHOT_TIMEOUT_S)
        except Exception as e:
            # 可能 session 已死 → 标记重登（受 breaker 约束），记一次 failure。
            logger.warning("[ShioajiFetcher] 快照失败/超时 %s: %s", code, type(e).__name__)
            with _SESSION_LOCK:
                # 仅当当前会话仍是本次使用的 api 时才作废+记 failure，避免旧 api 的延迟失败
                # 误清掉另一线程刚登入的新 session（race）。
                if _api is api:
                    _api = None
                    _logged_in = False
                    _login_breaker.record_failure(_BREAKER_KEY, str(e)[:200])
            return None

        if not snaps:
            _login_breaker.record_inconclusive(_BREAKER_KEY)
            return None

        quote = self._snap_to_quote(stock_code, snaps[0], getattr(contract, "name", "") or "")
        if quote is not None and quote.has_basic_data():
            _login_breaker.record_success(_BREAKER_KEY)
            return quote
        # 登入成功但无有效报价（午休/收盘无 tick）→ 不确定，半开转回 OPEN 避免假复原。
        _login_breaker.record_inconclusive(_BREAKER_KEY)
        return None

    @staticmethod
    def _snap_to_quote(stock_code: str, snap: Any, name: str) -> Optional[UnifiedRealtimeQuote]:
        """Shioaji snapshot → UnifiedRealtimeQuote。全部 getattr 防御，字段名以官方 Snapshot 为准。"""
        close = safe_float(getattr(snap, "close", None))
        change_price = safe_float(getattr(snap, "change_price", None))
        # ts 为 epoch 纳秒；务必产生可被 _parse_realtime_timestamp 解析的 ISO 字符串，
        # 否则 _enrich_realtime_quote 会把 provider_timestamp 设 None → as_of 退回 fetched_at（假新鲜）。
        ts = getattr(snap, "ts", None)
        provider_ts: Optional[str] = None
        if ts:
            try:
                provider_ts = datetime.fromtimestamp(int(ts) / 1e9, tz=timezone.utc).isoformat()
            except (ValueError, OSError, OverflowError, TypeError):
                provider_ts = None
        pre_close = None
        if close is not None and change_price is not None:
            pre_close = round(close - change_price, 4)
        return UnifiedRealtimeQuote(
            code=stock_code,
            name=name,
            source=RealtimeSource.SHIOAJI,
            price=close,
            change_amount=change_price,
            change_pct=safe_float(getattr(snap, "change_rate", None)),
            volume=safe_int(getattr(snap, "total_volume", None)),
            amount=safe_float(getattr(snap, "total_amount", None)),
            open_price=safe_float(getattr(snap, "open", None)),
            high=safe_float(getattr(snap, "high", None)),
            low=safe_float(getattr(snap, "low", None)),
            pre_close=pre_close,
            provider_timestamp=provider_ts,
        )
