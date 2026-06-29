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
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
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


# 台股升降单位（价格区间 -> tick）；>=1000 为 5。
_TW_TICK_BANDS = ((10.0, 0.01), (50.0, 0.05), (100.0, 0.1), (500.0, 0.5), (1000.0, 1.0))


def _tw_tick_size(price: float) -> float:
    for bound, tick in _TW_TICK_BANDS:
        if price < bound:
            return tick
    return 5.0


def tw_price_limits(reference: Optional[float]) -> tuple[Optional[float], Optional[float]]:
    """由参考价（昨收/参考价）算台股当日涨跌停（±10%，按 tick 对齐：涨停向下取、跌停向上取）。

    用 live 推得的参考价计算，取代 shioaji contract.limit_up/limit_down——后者来自每日
    contract 静态档，若缓存过期会与当日参考价不同步（实测 2330 contract 给 2625/2155，
    而昨收 2340 的正确涨跌停是 2570/2110）。台股 ±10% 规则对一般股可靠；IPO 前 5 日无涨跌停
    等特例不适用，但本计算仅供盘口显示，且优于过期的 contract 值。
    """
    if not reference or reference <= 0:
        return None, None
    up_raw = reference * 1.1
    down_raw = reference * 0.9
    up_tick = _tw_tick_size(up_raw)
    down_tick = _tw_tick_size(down_raw)
    limit_up = math.floor(up_raw / up_tick + 1e-9) * up_tick     # 不超过 +10%
    limit_down = math.ceil(down_raw / down_tick - 1e-9) * down_tick  # 不低于 -10%
    return round(limit_up, 2), round(limit_down, 2)


_BREAKER_KEY = "shioaji_login"
_LOGIN_TIMEOUT_S = 20.0
_SNAPSHOT_TIMEOUT_S = 8.0
# Shioaji 的 snapshot.ts / kbars.ts 是「台北时间的裸值（纳秒）」，不是 UTC。
# 必须按 +08:00 还原绝对时刻，否则 as_of/走势时间轴会差 8 小时、is_stale 也算错。
_TAIPEI_TZ = timezone(timedelta(hours=8))

# --- 模组级持久 session 状态 ---------------------------------------------
_SESSION_LOCK = threading.RLock()
# 快照专用锁：看板并发分批刷新会从多个请求线程并发调用同一 api.snapshots，
# Shioaji SDK 的并发安全性未知；快照很快（~数十 ms），用独立锁串行化即可保证安全，
# 又不与 _SESSION_LOCK（登入/重连）耦合。yfinance 等其他源不经此锁，仍可并发。
# ponytail: 若日后改用单次批量 snapshot([...500 档])，此锁可去除。
_SNAPSHOT_LOCK = threading.RLock()
# 批次预热快照缓存：prime_snapshots 一次 api.snapshots([...N]) 写入，per-code 取价命中即零网络。
# TTL 极短——看板一次刷新内的同批 code 都命中同一次批次结果；下次轮询（~30s 后）已过期重新预热，
# 不会跨刷新喂旧值。键为台股裸码（2330），值为 (snap, contract, 写入时刻)。
_SNAPSHOT_CACHE: dict = {}
_SNAPSHOT_CACHE_LOCK = threading.RLock()
_SNAPSHOT_CACHE_TTL = 5.0
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


def _ns_to_iso(ns: Any) -> Optional[str]:
    """Shioaji 台北裸值纳秒 -> ISO8601(+08:00)。失败回 None。"""
    try:
        # ts 的 wall-clock 是台北时间：先按 UTC 取出裸 wall-clock，再贴上 +08:00 还原绝对时刻。
        naive = datetime.fromtimestamp(int(ns) / 1e9, tz=timezone.utc).replace(tzinfo=_TAIPEI_TZ)
        return naive.isoformat()
    except (ValueError, OSError, OverflowError, TypeError):
        return None


def _normalize_day_trade(val: Any) -> Optional[str]:
    """contract.day_trade（DayTrade 枚举 / 字符串）→ 规范化 'Yes'/'OnlyBuy'/'No'。

    Shioaji 的 DayTrade 是枚举（.value 为 'Yes'/'OnlyBuy'/'No'）；防御性兼容裸字符串。
    无法识别时返回 None（前端按「未知」处理，不臆造可当沖）。
    """
    if val is None:
        return None
    raw = str(getattr(val, "value", val)).strip()
    for canonical in ("OnlyBuy", "Yes", "No"):
        if raw.lower() == canonical.lower():
            return canonical
    return raw or None


# Shioaji kbars 单次区间上限（官方限制：date range must not exceed 30 days）
_KBARS_MAX_DAYS = 30


def shioaji_trend(stock_code: str, range_: str):
    """台股走势点（真资料，经 Shioaji kbars）。

    range_: "day" 今日分钟线 / "month" 近 30 天分钟线 resample 成日线。
    "year" 超过 kbars 30 天上限 -> 返回 None（调用方用 yfinance 日线兜底）。
    非台股 / 未登入 / 失败 -> None（调用方降级）。返回 [{"t","price"}] 升序或 None。
    """
    if range_ not in ("day", "month") or not _HAS_SHIOAJI:
        return None
    api = _ensure_session()
    if api is None:
        return None
    code = ShioajiFetcher._tw_code(stock_code)
    try:
        contract = api.Contracts.Stocks[code]
    except Exception:
        return None
    if contract is None:
        return None

    # 以台北日期为准（server 可能跑在 UTC，date.today() 在台北午夜附近会抓错「今天」）
    today = datetime.now(_TAIPEI_TZ).date()
    start = today if range_ == "day" else today - timedelta(days=_KBARS_MAX_DAYS - 1)
    try:
        with _SNAPSHOT_LOCK:
            fut = _executor.submit(api.kbars, contract, start.isoformat(), today.isoformat())
            kb = fut.result(timeout=_SNAPSHOT_TIMEOUT_S)
        data = {**kb}
    except Exception as e:
        logger.warning("[ShioajiFetcher] kbars %s 失败: %s", code, type(e).__name__)
        return None

    ts_list = data.get("ts") or []
    close_list = data.get("Close") or []
    if not ts_list:
        return None

    # 按 ts 升序（不假设 SDK 已排序：day 折线需有序、month「当日末根=收盘」需正确）
    pairs = sorted(zip(ts_list, close_list), key=lambda x: x[0])

    if range_ == "day":
        points = []
        for t, c in pairs:
            iso = _ns_to_iso(t)
            if iso is not None:
                points.append({"t": iso, "price": float(c)})
        return points

    # month：分钟线 resample 成日线（按台北日期分桶，每日最后一根 Close 即当日收盘）
    by_day: dict = {}
    for t, c in pairs:
        iso = _ns_to_iso(t)
        if iso is not None:
            by_day[iso[:10]] = float(c)  # pairs 已升序 -> 同日末值即收盘
    return [{"t": d, "price": p} for d, p in sorted(by_day.items())]


def _read_snapshot_cache(bare_code: str):
    """读批次预热缓存：返回 (snap, contract) 或 None（缺失/过期）。"""
    with _SNAPSHOT_CACHE_LOCK:
        entry = _SNAPSHOT_CACHE.get(bare_code)
        if entry is None:
            return None
        snap, contract, ts = entry
        if time.time() - ts > _SNAPSHOT_CACHE_TTL:
            return None
        return snap, contract


def prime_snapshots(codes) -> int:
    """一次 api.snapshots([全部台股合约]) 预热快照缓存，取代逐档锁序列化。

    看板批量取价前调用：把 N 档台股的快照折叠成一次网络往返（~单档耗时），
    写入短 TTL 缓存供随后 per-code 路径零网络命中。返回写入缓存的档数。
    未安装/无金钥/无 session 时 no-op 返回 0（per-code 路径照常单档兜底/降级 yfinance）。
    熔断与失败语义对齐单档路径（见 get_realtime_quote）。
    """
    global _api, _logged_in
    if not _HAS_SHIOAJI or not codes:
        return 0
    api = _ensure_session()
    if api is None:
        return 0

    by_code: dict = {}
    contracts = []
    for raw in codes:
        bare = ShioajiFetcher._tw_code(raw)
        try:
            contract = api.Contracts.Stocks[bare]
        except Exception:
            contract = None
        if contract is not None and bare not in by_code:
            by_code[bare] = contract
            contracts.append(contract)
    if not contracts:
        return 0

    try:
        with _SNAPSHOT_LOCK:
            fut = _executor.submit(api.snapshots, contracts)
            # 批次 timeout 随档数放大但设上限，避免大 watchlist 卡死整批
            snaps = fut.result(timeout=min(30.0, max(_SNAPSHOT_TIMEOUT_S, len(contracts) * 0.5)))
    except Exception as e:
        logger.warning("[ShioajiFetcher] 批次快照失败/超时 (%d 档): %s", len(contracts), type(e).__name__)
        with _SESSION_LOCK:
            if _api is api:  # 仅当仍是本次会话才作废，避免误清他线程新 session（race）
                _api = None
                _logged_in = False
                _login_breaker.record_failure(_BREAKER_KEY, str(e)[:200])
        return 0

    if not snaps:
        _login_breaker.record_inconclusive(_BREAKER_KEY)
        return 0

    now = time.time()
    written = 0
    any_valid = False
    with _SNAPSHOT_CACHE_LOCK:
        for snap in snaps:
            scode = str(getattr(snap, "code", "") or "")
            if not scode:
                continue
            _SNAPSHOT_CACHE[scode] = (snap, by_code.get(scode), now)
            written += 1
            if safe_float(getattr(snap, "close", None)):
                any_valid = True
    # 端到端拿到合法报价才算成功；否则不确定（午休/收盘无 tick），半开转回 OPEN 避免假复原。
    _login_breaker.record_success(_BREAKER_KEY) if any_valid else _login_breaker.record_inconclusive(_BREAKER_KEY)
    return written


def _reset_for_tests() -> None:
    """清模组级状态 + 熔断器 + 批次缓存（供测试隔离）。"""
    global _api, _logged_in, _logout_registered
    with _SESSION_LOCK:
        _api = None
        _logged_in = False
        _logout_registered = False
    with _SNAPSHOT_CACHE_LOCK:
        _SNAPSHOT_CACHE.clear()
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

        code = self._tw_code(stock_code)

        # 0) 命中批次预热缓存 → 零网络、零锁、零熔断交互（看板批量取价的快路径）。
        #    prime_snapshots 已对该批做过一次网络与熔断记录；此处只是读已折叠的结果。
        cached = _read_snapshot_cache(code)
        if cached is not None:
            snap, contract = cached
            quote = self._snap_to_quote(stock_code, snap, contract)
            if quote is not None and quote.has_basic_data():
                return quote
            # 缓存命中但无有效报价 → 落到下方单档兜底

        api = _ensure_session()
        if api is None:
            return None

        # 查合约：查无属 transient（非 session 死），不记 breaker failure。
        try:
            contract = api.Contracts.Stocks[code]
        except Exception as e:
            logger.debug("[ShioajiFetcher] 合约查询失败 %s: %s", code, e)
            return None
        if contract is None:
            return None

        # 快照：不持 _SESSION_LOCK（避免与登入/重连耦合）；用 _SNAPSHOT_LOCK 串行化并发快照；
        # 硬 timeout 防 SDK 卡死。
        try:
            with _SNAPSHOT_LOCK:
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

        quote = self._snap_to_quote(stock_code, snaps[0], contract)
        if quote is not None and quote.has_basic_data():
            _login_breaker.record_success(_BREAKER_KEY)
            return quote
        # 登入成功但无有效报价（午休/收盘无 tick）→ 不确定，半开转回 OPEN 避免假复原。
        _login_breaker.record_inconclusive(_BREAKER_KEY)
        return None

    @staticmethod
    def _snap_to_quote(stock_code: str, snap: Any, contract: Any = None) -> Optional[UnifiedRealtimeQuote]:
        """Shioaji snapshot(+contract) → UnifiedRealtimeQuote。全部 getattr 防御，字段名以官方 Snapshot/Contract 为准。

        除既有价量字段外，补齐台股盘中真正天天盯的字段（均价多空分界、涨跌停价、委买委卖一档、
        现股当沖资格、最后一笔内外盘方向、量比/振幅）。这些字段 Shioaji snapshot/contract 已直接返回，
        旧实现却丢弃；详见 docs/realtime-board.md。`contract` 为 None 时只缺 contract 来源字段（涨跌停/当沖）。
        """
        close = safe_float(getattr(snap, "close", None))
        change_price = safe_float(getattr(snap, "change_price", None))
        # ts 为 epoch 纳秒；务必产生可被 _parse_realtime_timestamp 解析的 ISO 字符串，
        # 否则 _enrich_realtime_quote 会把 provider_timestamp 设 None → as_of 退回 fetched_at（假新鲜）。
        # snapshot.ts 同为台北裸值纳秒，按 +08:00 还原（否则 as_of 差 8h、is_stale 恒为 0）
        provider_ts = _ns_to_iso(getattr(snap, "ts", None))
        pre_close = None
        if close is not None and change_price is not None:
            pre_close = round(close - change_price, 4)
        # 振幅(%)：(high-low)/昨收。Shioaji 不直接给振幅，按昨收基准自算（全时段可靠）。
        high = safe_float(getattr(snap, "high", None))
        low = safe_float(getattr(snap, "low", None))
        amplitude = None
        if high is not None and low is not None and pre_close:
            amplitude = round((high - low) / pre_close * 100, 2)
        name = (getattr(contract, "name", "") or "") if contract is not None else ""
        # 涨跌停：用 live 参考价(pre_close)算 ±10%；pre_close 缺失才回退 contract 静态值。
        _limit_up, _limit_down = tw_price_limits(pre_close)
        if _limit_up is None and contract is not None:
            _limit_up = safe_float(getattr(contract, "limit_up", None))
        if _limit_down is None and contract is not None:
            _limit_down = safe_float(getattr(contract, "limit_down", None))
        return UnifiedRealtimeQuote(
            code=stock_code,
            name=name,
            source=RealtimeSource.SHIOAJI,
            price=close,
            change_amount=change_price,
            change_pct=safe_float(getattr(snap, "change_rate", None)),
            volume=safe_int(getattr(snap, "total_volume", None)),
            amount=safe_float(getattr(snap, "total_amount", None)),
            # 量比 Shioaji 直接给（避免因缺此字段触发 base._quote_needs_supplement 的 yfinance 补字段往返）。
            # 注意：Shioaji 量比是当日累计量/昨量，开盘初段(约 ~10:30 前)偏低失真，前端需谨慎解读。
            volume_ratio=safe_float(getattr(snap, "volume_ratio", None)),
            amplitude=amplitude,
            open_price=safe_float(getattr(snap, "open", None)),
            high=high,
            low=low,
            pre_close=pre_close,
            provider_timestamp=provider_ts,
            # --- 台股盘中专用 ---
            average_price=safe_float(getattr(snap, "average_price", None)),
            best_bid=safe_float(getattr(snap, "buy_price", None)),
            best_bid_volume=safe_int(getattr(snap, "buy_volume", None)),
            best_ask=safe_float(getattr(snap, "sell_price", None)),
            best_ask_volume=safe_int(getattr(snap, "sell_volume", None)),
            last_tick_type=safe_int(getattr(snap, "tick_type", None)),
            # 涨跌停：优先用 live 参考价(pre_close)算 ±10%（tick 对齐），contract 静态值仅兜底
            # （contract 缓存可能与当日参考价不同步，实测会给出错误的板价）。
            limit_up=_limit_up,
            limit_down=_limit_down,
            day_trade=_normalize_day_trade(getattr(contract, "day_trade", None)) if contract is not None else None,
        )
