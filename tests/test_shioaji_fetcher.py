# -*- coding: utf-8 -*-
"""ShioajiFetcher 自我停用 / 解析 / 持久 session / 熔断防 relogin-storm（全 mock，无真登入）。"""

import sys
import time
import types

import pytest

import data_provider.shioaji_fetcher as sf
from data_provider.realtime_types import RealtimeSource

# 快照时间用「当下」，确保经 _enrich 后落在 ttl 内被判为 fresh
_NOW_NS = int(time.time() * 1e9)


class _FakeContract:
    def __init__(self, code):
        self.code = code
        self.name = f"股票{code}"


class _FakeContracts:
    class _Stocks:
        def __getitem__(self, code):
            return _FakeContract(code)

    Stocks = _Stocks()


class _FakeSnap:
    code = "2330"
    close = 1000.0
    change_price = 10.0
    change_rate = 1.0
    total_volume = 5000
    total_amount = 5_000_000.0
    open = 995.0
    high = 1010.0
    low = 990.0
    ts = _NOW_NS  # epoch 纳秒（当下）


def _make_fake_shioaji(*, login_raises=False, snaps=None):
    """返回 (fake_module, counter)；counter['login'] 记录登入次数。"""
    counter = {"login": 0}
    snap_list = [_FakeSnap()] if snaps is None else snaps

    class _FakeApi:
        def __init__(self):
            self.Contracts = _FakeContracts()

        def login(self, api_key=None, secret_key=None, **kw):
            counter["login"] += 1
            if login_raises:
                raise RuntimeError("login limit exceeded")

        def snapshots(self, contracts):
            return list(snap_list)

        def logout(self):
            pass

    module = types.ModuleType("shioaji")
    module.Shioaji = _FakeApi
    return module, counter


@pytest.fixture(autouse=True)
def _reset():
    sf._reset_for_tests()
    yield
    sf._reset_for_tests()


def test_disabled_without_package(monkeypatch):
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", False)
    monkeypatch.setenv("SHIOAJI_API_KEY", "k")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "s")
    fetcher = sf.ShioajiFetcher()
    assert fetcher.is_available_for_request("realtime_quote") is False
    assert fetcher.is_available_for_request("daily_data") is False
    # 未安装时不应尝试任何登入
    module, counter = _make_fake_shioaji()
    monkeypatch.setitem(sys.modules, "shioaji", module)
    assert fetcher.get_realtime_quote("2330.TW") is None
    assert counter["login"] == 0


def test_disabled_without_keys(monkeypatch):
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.delenv("SHIOAJI_API_KEY", raising=False)
    monkeypatch.delenv("SHIOAJI_SECRET_KEY", raising=False)
    fetcher = sf.ShioajiFetcher()
    assert fetcher.is_available_for_request("realtime_quote") is False


def test_parses_snapshot_with_provider_timestamp(monkeypatch):
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setenv("SHIOAJI_API_KEY", "k")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "s")
    module, _ = _make_fake_shioaji()
    monkeypatch.setitem(sys.modules, "shioaji", module)

    fetcher = sf.ShioajiFetcher()
    quote = fetcher.get_realtime_quote("2330.TW")
    assert quote is not None
    assert quote.source is RealtimeSource.SHIOAJI
    assert quote.price == 1000.0
    assert quote.pre_close == 990.0  # close - change_price
    assert quote.has_basic_data() is True
    # provider_timestamp 必须可被 _enrich 解析且 is_stale 计算正确（不被 None 掉）
    assert quote.provider_timestamp is not None


def test_persistent_session_logs_in_once(monkeypatch):
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setenv("SHIOAJI_API_KEY", "k")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "s")
    module, counter = _make_fake_shioaji()
    monkeypatch.setitem(sys.modules, "shioaji", module)

    fetcher = sf.ShioajiFetcher()
    fetcher.get_realtime_quote("2330.TW")
    fetcher.get_realtime_quote("2317.TW")
    assert counter["login"] == 1  # 持久 session，仅登入一次


def test_login_failures_open_breaker_no_relogin_storm(monkeypatch):
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setenv("SHIOAJI_API_KEY", "k")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "s")
    module, counter = _make_fake_shioaji(login_raises=True)
    monkeypatch.setitem(sys.modules, "shioaji", module)

    fetcher = sf.ShioajiFetcher()
    # 连续 2 次失败 -> 熔断 OPEN（failure_threshold=2）
    assert fetcher.get_realtime_quote("2330.TW") is None
    assert fetcher.get_realtime_quote("2330.TW") is None
    # 第三次：熔断 OPEN 且未到冷却 -> 零登入（关键：不 relogin-storm）
    assert fetcher.get_realtime_quote("2330.TW") is None
    assert counter["login"] == 2


def test_login_ok_but_empty_snapshot_is_inconclusive(monkeypatch):
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setenv("SHIOAJI_API_KEY", "k")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "s")
    module, counter = _make_fake_shioaji(snaps=[])  # 登入成功但快照空
    monkeypatch.setitem(sys.modules, "shioaji", module)

    fetcher = sf.ShioajiFetcher()
    assert fetcher.get_realtime_quote("2330.TW") is None
    assert fetcher.get_realtime_quote("2330.TW") is None
    # 持久 session 不因空快照重登；inconclusive 不会被当成功重置熔断
    assert counter["login"] == 1


def test_stale_snapshot_failure_does_not_kill_newer_session(monkeypatch):
    # race 守卫：旧 api 的延迟快照失败不应作废另一线程刚登入的新 _api
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setenv("SHIOAJI_API_KEY", "k")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "s")

    class _OldApi:
        Contracts = _FakeContracts()

        def snapshots(self, contracts):
            raise RuntimeError("stale session dead")

    new_api = object()  # 模拟另一线程已登入的新 session
    sf._api = new_api
    sf._logged_in = True
    # 让本次调用使用 OLD api（而模组 _api 已是 new_api）
    monkeypatch.setattr(sf, "_ensure_session", lambda: _OldApi())
    before = sf._login_breaker.get_status().copy()

    assert sf.ShioajiFetcher().get_realtime_quote("2330.TW") is None
    # 新 session 未被旧失败清掉，熔断器也未被旧失败计入
    assert sf._api is new_api
    assert sf._logged_in is True
    assert sf._login_breaker.get_status() == before


def test_availability_probe_does_not_consume_breaker(monkeypatch):
    # gate 是纯读：多次探测不应改变熔断器状态（闭 adversary 头号洞）
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setenv("SHIOAJI_API_KEY", "k")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "s")
    fetcher = sf.ShioajiFetcher()
    before = sf._login_breaker.get_status().copy()
    for _ in range(5):
        fetcher.is_available_for_request("realtime_quote")
    assert sf._login_breaker.get_status() == before


def test_enrich_keeps_provider_timestamp(monkeypatch):
    # pin：Shioaji 报价经 DataFetcherManager._enrich_realtime_quote 后 provider_timestamp 不被 None 掉
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setenv("SHIOAJI_API_KEY", "k")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "s")
    module, _ = _make_fake_shioaji()
    monkeypatch.setitem(sys.modules, "shioaji", module)

    quote = sf.ShioajiFetcher().get_realtime_quote("2330.TW")
    from data_provider.base import DataFetcherManager

    enriched = DataFetcherManager(fetchers=[])._enrich_realtime_quote(quote, realtime_cache_ttl=600)
    assert enriched.provider_timestamp is not None
    assert enriched.is_stale is False  # 快照 ts 为当下，ttl(600s) 内判为 fresh
