# -*- coding: utf-8 -*-
"""台股 realtime 路由：Shioaji 优先 + yfinance 补充/兜底 + honesty(is_stale) 回归（mock fetcher，无网络）。"""

import time

from data_provider.base import DataFetcherManager
from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote


def _full_quote(code, source):
    """各 supplement 字段齐全 -> 不触发补充。"""
    return UnifiedRealtimeQuote(
        code=code, name=f"股票{code}", source=source,
        price=1000.0, change_pct=1.0, change_amount=10.0, volume=5000, amount=5_000_000.0,
        open_price=995.0, high=1010.0, low=990.0, pre_close=990.0,
        provider_timestamp=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        volume_ratio=1.1, turnover_rate=0.5, pe_ratio=15.0, pb_ratio=2.0,
        total_mv=1e12, circ_mv=8e11, amplitude=2.0,
    )


def _yf_quote(code):
    """yfinance 台股：source=FALLBACK，无 provider_timestamp（用于触发 honesty is_stale=True）。"""
    return UnifiedRealtimeQuote(
        code=code, name=f"股票{code}", source=RealtimeSource.FALLBACK,
        price=999.0, change_pct=0.9, change_amount=9.0, volume=4000, amount=4_000_000.0,
        open_price=994.0, high=1005.0, low=992.0, pre_close=990.0,
        volume_ratio=1.2, turnover_rate=0.6, pe_ratio=15.0, pb_ratio=2.0,
        total_mv=1e12, circ_mv=8e11, amplitude=1.8,
    )


class _FakeFetcher:
    def __init__(self, name, quote, *, available=True, priority=50):
        self.name = name
        self.priority = priority
        self._quote = quote
        self._available = available
        self.calls = 0

    def is_available_for_request(self, capability=""):
        return self._available

    def get_realtime_quote(self, stock_code, **kw):
        self.calls += 1
        return self._quote


def _manager(shioaji, yfinance):
    return DataFetcherManager(fetchers=[shioaji, yfinance])


def test_shioaji_unavailable_falls_back_to_yfinance_marked_stale():
    sh = _FakeFetcher("ShioajiFetcher", None, available=False)
    yf = _FakeFetcher("YfinanceFetcher", _yf_quote("2330.TW"))
    q = _manager(sh, yf).get_realtime_quote("2330.TW")
    assert q is not None
    assert sh.calls == 0  # 不可用 -> 零调用
    assert yf.calls == 1
    assert q.source is RealtimeSource.FALLBACK
    assert q.is_stale is True  # honesty：非 shioaji 台股显式标延迟


def test_shioaji_full_quote_skips_yfinance_and_is_fresh():
    sh = _FakeFetcher("ShioajiFetcher", _full_quote("2330.TW", RealtimeSource.SHIOAJI))
    yf = _FakeFetcher("YfinanceFetcher", _yf_quote("2330.TW"))
    q = _manager(sh, yf).get_realtime_quote("2330.TW")
    assert q.source is RealtimeSource.SHIOAJI
    assert yf.calls == 0  # 字段齐全，无需补充
    assert q.is_stale is False


def test_shioaji_partial_supplemented_by_yfinance_keeps_source():
    partial = _full_quote("2330.TW", RealtimeSource.SHIOAJI)
    partial.volume_ratio = None  # 缺一个 supplement 字段 -> 触发补充
    sh = _FakeFetcher("ShioajiFetcher", partial)
    yf = _FakeFetcher("YfinanceFetcher", _yf_quote("2330.TW"))
    q = _manager(sh, yf).get_realtime_quote("2330.TW")
    assert q.source is RealtimeSource.SHIOAJI  # 合并不改 source
    assert yf.calls == 1
    assert q.volume_ratio == 1.2  # 来自 yfinance
    assert q.is_stale is False  # 仍为 shioaji 主源 -> 实时


def test_shioaji_none_uses_yfinance_with_fallback_from():
    sh = _FakeFetcher("ShioajiFetcher", None)  # available 但返回 None
    yf = _FakeFetcher("YfinanceFetcher", _yf_quote("2330.TW"))
    q = _manager(sh, yf).get_realtime_quote("2330.TW")
    assert sh.calls == 1
    assert q.source is RealtimeSource.FALLBACK
    assert q.fallback_from == "shioaji"
    assert q.is_stale is True


def test_both_fail_returns_none():
    sh = _FakeFetcher("ShioajiFetcher", None)
    yf = _FakeFetcher("YfinanceFetcher", None)
    q = _manager(sh, yf).get_realtime_quote("2330.TW")
    assert q is None


def test_jp_code_never_touches_shioaji():
    sh = _FakeFetcher("ShioajiFetcher", _full_quote("7203.T", RealtimeSource.SHIOAJI))
    yf = _FakeFetcher("YfinanceFetcher", _yf_quote("7203.T"))
    q = _manager(sh, yf).get_realtime_quote("7203.T")
    assert sh.calls == 0  # 日股分支只走 yfinance
    assert yf.calls == 1
    assert q.source is RealtimeSource.FALLBACK
