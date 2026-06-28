# -*- coding: utf-8 -*-
"""TwseFundamentalAdapter — 台股(上市/上柜)个股估值补全（免金钥）。

背景：yfinance 对台股 .TW/.TWO 不返回 PE/PB（realtime quote 的 pe_ratio/pb_ratio 恒为 None），
导致价值分析在台股缺估值。本适配器用 TWSE / TPEx 公开 OpenAPI 的「全市场每日估值快照」补上
pe_ratio / pb_ratio / dividend_yield。

数据来源（全部免金钥）：
- 上市: https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL
        字段 Code / PEratio / PBratio / DividendYield
- 上柜: https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis
        字段 SecuritiesCompanyCode / PriceEarningRatio / PriceBookRatio / YieldRatio

设计：
1. 全市场快照一次抓取、按代码索引、带 TTL 缓存（数据每日更新；一次抓取覆盖当批所有台股）。
2. 任何网络/解析失败一律 fail-open 返回 {}，绝不向上抛异常（与 TwseFetcher 同款降级哲学）。
3. PE/PB/殖利率非正数或缺失（"-" / "" / "N/A"）一律视为 None，不污染估值。
"""

import logging
import time
from threading import Lock
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_TWSE_BWIBBU_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
_TPEX_PERATIO_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
# 月营收（免金钥）：上市 TWSE t187ap05_L / 上柜 TPEx mopsfin_t187ap05_O，两者字段名相同。
_TWSE_REVENUE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
_TPEX_REVENUE_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
# ponytail: (connect, read) 收紧以贴合 fundamental 阶段预算（8s 总 / 3s 单源）。两端点循序抓，
# 最坏 ~2x8s，但 fail-open + 4h 缓存兜底：首档冷抓超时仅令该档 valuation 退回 None，后续命中缓存。
# 若日后要严格卡单源预算，再把 stage 剩余预算透传进 get_valuation。
_TIMEOUT = (3, 5)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
_CACHE_TTL_SECONDS = 4 * 3600  # 估值快照每日更新，4h 内复用同一份全市场索引


def _pos_float(value: Any) -> Optional[float]:
    """解析估值数字；缺失/非数字/非正数返回 None（估值字段 0 或负数无意义）。"""
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text or text in ("-", "--", "N/A", "n/a"):
        return None
    try:
        f = float(text)
    except (ValueError, TypeError):
        return None
    return f if f > 0 else None


def _bare_code(stock_code: str) -> str:
    """'2330.TW' / '6488.TWO' / '2330' -> '2330'（去后缀、大写）。"""
    code = str(stock_code or "").strip().upper()
    for suffix in (".TWO", ".TW"):
        if code.endswith(suffix):
            return code[: -len(suffix)]
    return code


def _index_twse_rows(rows: Any) -> Dict[str, Dict[str, Optional[float]]]:
    out: Dict[str, Dict[str, Optional[float]]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("Code") or "").strip().upper()
        if not code:
            continue
        out[code] = {
            "pe_ratio": _pos_float(row.get("PEratio")),
            "pb_ratio": _pos_float(row.get("PBratio")),
            "dividend_yield": _pos_float(row.get("DividendYield")),
        }
    return out


def _index_tpex_rows(rows: Any) -> Dict[str, Dict[str, Optional[float]]]:
    out: Dict[str, Dict[str, Optional[float]]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("SecuritiesCompanyCode") or "").strip().upper()
        if not code:
            continue
        out[code] = {
            "pe_ratio": _pos_float(row.get("PriceEarningRatio")),
            "pb_ratio": _pos_float(row.get("PriceBookRatio")),
            "dividend_yield": _pos_float(row.get("YieldRatio")),
        }
    return out


def _index_revenue_rows(rows: Any) -> Dict[str, Dict[str, Optional[float]]]:
    """月营收（上市/上柜字段名相同）→ {monthly_revenue_yoy, monthly_revenue(元), revenue_month}。
    用 distinct 字段名（monthly_*）以与 yfinance 的年度 revenue_yoy 区分——月营收是台股最受重视的即时指标。"""
    out: Dict[str, Dict[str, Optional[float]]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("公司代號") or "").strip().upper()
        if not code:
            continue
        cur = _pos_float(row.get("營業收入-當月營收"))      # 单位：千元
        prev = _pos_float(row.get("營業收入-去年當月營收"))
        yoy = round((cur - prev) / prev * 100, 2) if (cur is not None and prev) else None
        out[code] = {
            "monthly_revenue_yoy": yoy,
            "monthly_revenue": cur * 1000 if cur is not None else None,  # 千元 -> 元，对齐 yfinance 绝对币别
            "revenue_month": str(row.get("資料年月") or "").strip() or None,
        }
    return out


class TwseFundamentalAdapter:
    """台股个股估值（PE/PB/殖利率）与月营收补全，免金钥、全市场快照 + TTL 缓存。"""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})
        self._lock = Lock()
        # name -> {"index": {...}, "at": monotonic}；估值与营收各一份全市场快照。
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get_valuation(self, stock_code: str) -> Dict[str, Optional[float]]:
        """返回 {pe_ratio, pb_ratio, dividend_yield}；无数据或失败返回 {}。"""
        return self._lookup(stock_code, "valuation", self._build_valuation_index, "估值")

    def get_growth(self, stock_code: str) -> Dict[str, Optional[float]]:
        """返回 {monthly_revenue_yoy, monthly_revenue, revenue_month}；无数据或失败返回 {}。"""
        return self._lookup(stock_code, "revenue", self._build_revenue_index, "营收")

    def _lookup(self, stock_code, name, build, label) -> Dict[str, Optional[float]]:
        code = _bare_code(stock_code)
        if not code:
            return {}
        try:
            index = self._cached(name, build)
        except Exception as exc:  # noqa: BLE001 - fail-open，绝不拖垮分析主流程
            logger.warning("[TwseFundamental] %s快照索引失败: %s", label, exc)
            return {}
        return dict(index.get(code, {}))

    def _build_valuation_index(self) -> Dict[str, Dict[str, Optional[float]]]:
        index = dict(self._fetch(_TWSE_BWIBBU_URL, _index_twse_rows, "上市估值"))
        # 上市优先：上柜仅补 TWSE 没有的代码（两者代码不重叠，setdefault 仅为稳妥）。
        for code, val in self._fetch(_TPEX_PERATIO_URL, _index_tpex_rows, "上柜估值").items():
            index.setdefault(code, val)
        return index

    def _build_revenue_index(self) -> Dict[str, Dict[str, Optional[float]]]:
        index = dict(self._fetch(_TWSE_REVENUE_URL, _index_revenue_rows, "上市营收"))
        for code, val in self._fetch(_TPEX_REVENUE_URL, _index_revenue_rows, "上柜营收").items():
            index.setdefault(code, val)
        return index

    def _cached(self, name: str, build) -> Dict[str, Dict[str, Optional[float]]]:
        # 锁只保护缓存读写，绝不包住网络 I/O：否则并发分析多档台股时，首档持锁 fetch 期间
        # 会把其他所有台股 thread 全部阻塞在锁上。fetch 移出锁后，冷启动偶发两 thread 同时抓
        # 属无害（全市场快照幂等，结果相同），换取不串行化。
        with self._lock:
            slot = self._cache.get(name)
            if slot and (time.monotonic() - slot["at"]) < _CACHE_TTL_SECONDS:
                return slot["index"]
            cached = slot["index"] if slot else {}  # 抓取失败时回退到上次好缓存

        index = build()  # 网络 I/O 在锁外
        if not index:  # 端点皆失败：不覆盖上次好缓存
            return cached
        with self._lock:
            self._cache[name] = {"index": index, "at": time.monotonic()}
            return index

    def _fetch(self, url: str, indexer, label: str) -> Dict[str, Dict[str, Optional[float]]]:
        try:
            resp = self._session.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            return indexer(resp.json())
        except (requests.RequestException, ValueError) as exc:
            logger.warning("[TwseFundamental] %s端点失败: %s", label, exc)
            return {}


def _self_check() -> None:
    """ponytail: 解析逻辑的离线自检（不联网）。"""
    assert _bare_code("2330.TW") == "2330"
    assert _bare_code("6488.TWO") == "6488"
    assert _bare_code(" 2330 ") == "2330"
    assert _pos_float("31.46") == 31.46
    assert _pos_float("-") is None and _pos_float("") is None and _pos_float("0") is None
    assert _pos_float("N/A") is None and _pos_float(None) is None

    twse = _index_twse_rows([
        {"Code": "2330", "Name": "台積電", "PEratio": "31.46", "PBratio": "10.30", "DividendYield": "0.94"},
        {"Code": "9999", "PEratio": "-", "PBratio": "", "DividendYield": "0"},  # 全缺
        "garbage",
    ])
    assert twse["2330"] == {"pe_ratio": 31.46, "pb_ratio": 10.30, "dividend_yield": 0.94}
    assert twse["9999"] == {"pe_ratio": None, "pb_ratio": None, "dividend_yield": None}

    tpex = _index_tpex_rows([
        {"SecuritiesCompanyCode": "6488", "PriceEarningRatio": "20.5",
         "PriceBookRatio": "5.1", "YieldRatio": "1.2"},
    ])
    assert tpex["6488"] == {"pe_ratio": 20.5, "pb_ratio": 5.1, "dividend_yield": 1.2}

    rev = _index_revenue_rows([
        {"公司代號": "2330", "資料年月": "11505",
         "營業收入-當月營收": "416975163", "營業收入-去年當月營收": "320543000"},
        {"公司代號": "1111", "資料年月": "11505",
         "營業收入-當月營收": "100", "營業收入-去年當月營收": "0"},  # 去年为0 -> yoy None
    ])
    assert rev["2330"]["monthly_revenue"] == 416975163 * 1000
    assert rev["2330"]["monthly_revenue_yoy"] == round((416975163 - 320543000) / 320543000 * 100, 2)
    assert rev["2330"]["revenue_month"] == "11505"
    assert rev["1111"]["monthly_revenue_yoy"] is None and rev["1111"]["monthly_revenue"] == 100 * 1000
    print("self-check OK")


if __name__ == "__main__":
    _self_check()
