# -*- coding: utf-8 -*-
"""ShioajiFetcher 自我停用 / 解析 / 持久 session / 熔断防 relogin-storm（全 mock，无真登入）。"""

import sys
import time
import types

import pytest

import data_provider.shioaji_fetcher as sf
from data_provider.realtime_types import RealtimeSource

# Shioaji 的 ts 是「台北裸值」纳秒；必须在快照建立时取值，不能在 pytest 收集时冻结。
# 全量套件超过 10 分钟后，收集时的值会自然超过 realtime TTL，制造顺序敏感失败。

class _FakeDayTrade:
    """模拟 Shioaji DayTrade 枚举（.value 为 'Yes'/'OnlyBuy'/'No'）。"""

    def __init__(self, value):
        self.value = value


class _FakeContract:
    def __init__(self, code):
        self.code = code
        self.name = f"股票{code}"
        self.limit_up = 1100.0
        self.limit_down = 900.0
        self.day_trade = _FakeDayTrade("Yes")


class _FakeContracts:
    class _Stocks:
        def __getitem__(self, code):
            return _FakeContract(code)

    Stocks = _Stocks()


def test_fake_snapshot_timestamp_is_read_at_construction_not_at_import(monkeypatch):
    """把時戳搬進 `__init__` 是這輪修掉那個順序敏感 flaky 的**機制**，用測試釘住它。

    舊版在模組層（收集期）算一次 `_NOW_NS`：全量套件跑超過 realtime TTL（600 秒）後，
    這個檔案排在後面時時戳已經過期，`_enrich` 判 stale → 紅；單獨跑該檔只要幾秒 → 綠。
    「跑一次全量是綠的」證明不了它修好了（獨立審查指出），能證明的是這個性質：
    時戳必須跟著建構時的時鐘走。
    """
    seen = []
    for fake_now in (1_000_000.0, 1_000_700.0):        # 相隔 700 秒 > 600 秒 TTL
        monkeypatch.setattr(time, "time", lambda v=fake_now: v)
        seen.append(_FakeSnap().ts)
    assert seen[1] - seen[0] == int(700 * 1e9), (
        "時戳沒跟著建構時的時鐘走——收集期就固定的話，全量跑到後段必然過 TTL")


class _FakeSnap:
    def __init__(self):
        self.ts = int((time.time() + 8 * 3600) * 1e9)

    code = "2330"
    close = 1000.0
    change_price = 10.0
    change_rate = 1.0
    total_volume = 5000
    total_amount = 5_000_000.0
    open = 995.0
    high = 1010.0
    low = 990.0
    # 台股盘中专用字段（旧实现丢弃，现已接上）
    average_price = 1002.5
    volume_ratio = 1.8
    buy_price = 999.0
    buy_volume = 120
    sell_price = 1001.0
    sell_volume = 80
    tick_type = 1


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


def test_snapshot_maps_tw_intraday_fields(monkeypatch):
    """台股盘中关键字段（均价/涨跌停/委买委卖/内外盘/振幅/量比/当沖资格）必须从 snapshot+contract 接上。"""
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setenv("SHIOAJI_API_KEY", "k")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "s")
    module, _ = _make_fake_shioaji()
    monkeypatch.setitem(sys.modules, "shioaji", module)

    quote = sf.ShioajiFetcher().get_realtime_quote("2330.TW")
    assert quote is not None
    assert quote.average_price == 1002.5          # 均价多空分界
    # 涨跌停由 live 参考价(pre_close=990) ±10% + tick 对齐算出（tw_price_limits），
    # 取代可能与当日参考价不同步的 contract.limit_up/limit_down 静态值(1100/900)。
    assert quote.limit_up == 1085.0 and quote.limit_down == 891.0
    # total_volume 5000 張 → 5,000,000 股（UnifiedRealtimeQuote.volume 契約是股）；
    # 委買委賣量維持張、成交額不換算
    assert quote.volume == 5_000_000
    assert quote.amount == 5_000_000.0
    assert quote.best_bid == 999.0 and quote.best_bid_volume == 120
    assert quote.best_ask == 1001.0 and quote.best_ask_volume == 80
    assert quote.last_tick_type == 1              # 最后一笔外盘主买
    assert quote.volume_ratio == 1.8              # Shioaji 直接给（不触发 yfinance 补字段）
    assert quote.amplitude == 2.02                # (1010-990)/990*100 四舍五入
    assert quote.day_trade == "Yes"               # DayTrade 枚举 .value
    # to_dict 必须把新字段带出（API 序列化依赖此）
    d = quote.to_dict()
    for k in ("average_price", "limit_up", "limit_down", "best_bid", "best_ask", "day_trade"):
        assert k in d


def test_prime_snapshots_batches_then_cache_hit_skips_per_code_snapshot(monkeypatch):
    """prime 一次 snapshots([N]) 写缓存；随后 per-code get 命中缓存，不再各发一次快照。"""
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setenv("SHIOAJI_API_KEY", "k")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "s")

    snap_calls = {"n": 0, "batch_sizes": []}

    class _Snap:
        def __init__(self, code):
            self.code = code
            self.close = 1000.0
            self.change_price = 10.0
            self.change_rate = 1.0
            self.total_volume = 5000
            self.total_amount = 5_000_000.0
            self.open = 995.0
            self.high = 1010.0
            self.low = 990.0
            self.ts = int((time.time() + 8 * 3600) * 1e9)
            self.average_price = 1002.5

    class _Api:
        def __init__(self):
            self.Contracts = _FakeContracts()

        def login(self, api_key=None, secret_key=None, **kw):
            pass

        def snapshots(self, contracts):
            snap_calls["n"] += 1
            snap_calls["batch_sizes"].append(len(contracts))
            return [_Snap(c.code) for c in contracts]

        def logout(self):
            pass

    module = types.ModuleType("shioaji")
    module.Shioaji = _Api
    monkeypatch.setitem(sys.modules, "shioaji", module)

    codes = ["2330.TW", "2317.TW", "00878.TW"]
    written = sf.prime_snapshots(codes)
    assert written == 3
    assert snap_calls["n"] == 1            # 仅一次批次网络往返
    assert snap_calls["batch_sizes"] == [3]  # 一次带 3 档

    fetcher = sf.ShioajiFetcher()
    for code in codes:
        q = fetcher.get_realtime_quote(code)
        assert q is not None and q.source is RealtimeSource.SHIOAJI
        assert q.average_price == 1002.5
    assert snap_calls["n"] == 1            # 命中缓存，未再发任何单档快照


def test_prime_snapshots_noop_without_keys(monkeypatch):
    """无金钥时 prime no-op（不登入、不抛错）。"""
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.delenv("SHIOAJI_API_KEY", raising=False)
    monkeypatch.delenv("SHIOAJI_SECRET_KEY", raising=False)
    assert sf.prime_snapshots(["2330.TW"]) == 0


def test_normalize_day_trade_variants():
    """day_trade 规范化：枚举 .value、裸字符串、未知值、None。"""
    assert sf._normalize_day_trade(_FakeDayTrade("OnlyBuy")) == "OnlyBuy"
    assert sf._normalize_day_trade("yes") == "Yes"     # 大小写规范化
    assert sf._normalize_day_trade("No") == "No"
    assert sf._normalize_day_trade(None) is None


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


def test_shioaji_trend_month_resamples_sorts_and_uses_taipei_date(monkeypatch):
    import datetime as dt

    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)

    def taipei_ns(y, mo, d, h, mi):
        # 模拟「台北裸值」：以 UTC 取该 wall-clock 的 epoch（_ns_to_iso 会再贴 +08:00 还原）
        return int(dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc).timestamp() * 1e9)

    # 故意乱序、跨两个交易日；每日末根(13:30)即收盘
    ts = [
        taipei_ns(2026, 6, 24, 13, 30),  # d24 收 130
        taipei_ns(2026, 6, 23, 9, 0),    # d23 开 100
        taipei_ns(2026, 6, 24, 9, 0),    # d24 开 120
        taipei_ns(2026, 6, 23, 13, 30),  # d23 收 110
    ]
    close = [130.0, 100.0, 120.0, 110.0]

    class _Api:
        Contracts = _FakeContracts()

        def kbars(self, contract, start, end):
            return {"ts": ts, "Close": close}

    monkeypatch.setattr(sf, "_ensure_session", lambda: _Api())

    pts = sf.shioaji_trend("2330.TW", "month")
    assert [p["t"] for p in pts] == ["2026-06-23", "2026-06-24"]  # 台北日期、升序
    assert [p["price"] for p in pts] == [110.0, 130.0]  # 每日末根=收盘


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


def test_snap_to_quote_volume_none_stays_none():
    """total_volume 缺值不能被換算成 0 股（0 與 None 語意不同）。"""
    class _NoVol:
        close = 100.0
        change_price = 1.0
        total_volume = None

    quote = sf.ShioajiFetcher._snap_to_quote("2330", _NoVol())
    assert quote is not None and quote.volume is None


def test_snap_volume_matches_db_daily_unit_cross_source():
    """跨來源單位契約：同一場次 3008 的 Shioaji 4441 張，要與 DB 日線 4,812,882 股同量級。

    修前 quote.volume=4441（張）→ 比值 0.0009，pipeline 覆蓋日線後量比≈0.001、全部被判縮量。
    """
    class _Snap3008:
        close = 2000.0
        change_price = -10.0
        total_volume = 4441

    quote = sf.ShioajiFetcher._snap_to_quote("3008", _Snap3008())
    db_daily_volume_shares = 4_812_882
    ratio = quote.volume / db_daily_volume_shares
    assert 0.85 <= ratio <= 1.0


# --- 查合约连续失败 → 作废死 session（10-23 NAS 事故回归）-------------------

class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _dead_contract_env(monkeypatch, *, fail=True):
    """登入成功的 fake SDK；fail 开关控制查合约是否丢 SessionNotEstablished 类例外。"""
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setenv("SHIOAJI_API_KEY", "k")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "s")
    state = {"fail": fail, "login": 0}
    clock = _Clock()
    monkeypatch.setattr(sf.time, "monotonic", clock)

    class _Table:
        def __getitem__(self, key):
            if state["fail"]:
                raise RuntimeError("Session error ... SessionNotEstablished")
            return _FakeContract(key)

    class _Contracts:
        Stocks = _Table()

        class Indexs:
            TSE = _Table()
            OTC = _Table()

    class _Api:
        def __init__(self):
            self.Contracts = _Contracts()

        def login(self, api_key=None, secret_key=None, **kw):
            state["login"] += 1

        def snapshots(self, contracts):
            return [_FakeSnap()]

        def logout(self):
            pass

    module = types.ModuleType("shioaji")
    module.Shioaji = _Api
    monkeypatch.setitem(sys.modules, "shioaji", module)
    return state, clock


def test_contract_lookup_failing_past_window_invalidates_session_and_relogins(monkeypatch):
    state, clock = _dead_contract_env(monkeypatch)
    f = sf.ShioajiFetcher()
    assert f.get_realtime_quote("2330.TW") is None
    assert state["login"] == 1
    first_api = sf._api
    clock.t += sf._CONTRACT_FAIL_WINDOW_S - 1
    assert f.get_realtime_quote("2330.TW") is None
    assert sf._api is first_api  # 未达门槛不作废
    clock.t += 2
    assert f.get_realtime_quote("2330.TW") is None
    assert sf._api is None and sf._logged_in is False  # 作废
    state["fail"] = False
    assert f.get_realtime_quote("2330.TW") is not None
    assert state["login"] == 2  # 下一次请求自然重登一次


def test_contract_lookup_recovering_before_window_does_not_relogin(monkeypatch):
    state, clock = _dead_contract_env(monkeypatch)
    f = sf.ShioajiFetcher()
    for _ in range(30):  # 10-14 型：一分钟内几十次失败，次数多但时间短
        f.get_realtime_quote("2330.TW")
        clock.t += 1
    state["fail"] = False
    assert f.get_realtime_quote("2330.TW") is not None
    clock.t += 1000
    assert f.get_realtime_quote("2330.TW") is not None
    assert state["login"] == 1


def test_contract_lookup_success_resets_failure_clock(monkeypatch):
    state, clock = _dead_contract_env(monkeypatch)
    f = sf.ShioajiFetcher()
    f.get_realtime_quote("2330.TW")
    clock.t += 50
    f.get_realtime_quote("2330.TW")
    state["fail"] = False
    assert f.get_realtime_quote("2330.TW") is not None
    assert sf._contract_fail_since is None
    state["fail"] = True
    clock.t += 50  # 距首次失败已 >60s，但成功过一次，计时应重来
    f.get_realtime_quote("2330.TW")
    assert sf._api is not None
    assert state["login"] == 1


def test_prime_snapshots_and_indices_also_accumulate(monkeypatch):
    state, clock = _dead_contract_env(monkeypatch)
    assert sf.prime_snapshots(["2330.TW"]) == 0
    assert sf._contract_fail_since is not None
    clock.t += sf._CONTRACT_FAIL_WINDOW_S + 1
    assert sf.prime_snapshots(["2330.TW"]) == 0
    assert sf._api is None  # 批次路径作废

    sf._ensure_session()
    clock.t += 0
    assert sf.shioaji_main_indices() is None
    clock.t += sf._CONTRACT_FAIL_WINDOW_S + 1
    assert sf.shioaji_main_indices() is None
    assert sf._api is None  # 指数路径作废
    assert state["login"] == 2


def test_contract_lookup_miss_is_not_a_failure(monkeypatch):
    state, clock = _dead_contract_env(monkeypatch, fail=False)
    api = sf._ensure_session()
    assert sf._lookup_contract(api, lambda a: None) is None
    assert sf._lookup_contract(api, lambda a: {}["x"]) is None  # KeyError = 查无
    assert sf._contract_fail_since is None


def test_contract_failure_on_replaced_session_does_not_kill_new_session(monkeypatch):
    state, clock = _dead_contract_env(monkeypatch)
    old_api = sf._ensure_session()
    sf._contract_fail_since = clock.t - 1000  # 已超门槛
    new_api = object()
    sf._api = new_api  # 别的线程已换新 session
    assert sf._lookup_contract(old_api, lambda a: a.Contracts.Stocks["2330"]) is None
    assert sf._api is new_api and sf._logged_in is True
    assert sf._contract_fail_since == clock.t - 1000  # untouched: stale failures are ignored, not counted


def test_invalidate_skips_when_api_swapped_between_check_and_invalidate(monkeypatch):
    _dead_contract_env(monkeypatch)
    old_api = object()
    new_api = object()
    sf._api, sf._logged_in = new_api, True
    sf._invalidate_dead_session(old_api, RuntimeError("dead"))
    assert sf._api is new_api and sf._logged_in is True
