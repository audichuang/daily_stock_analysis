# -*- coding: utf-8 -*-
"""台股指數（盯盤指數條）：Shioaji 快照 → 本地官方收盤 → yfinance 的順序與欄位對映。"""

import time

import pytest

import data_provider.shioaji_fetcher as sf
from data_provider.base import DataFetcherManager


class _Snap:
    def __init__(self, code, close, change, rate):
        self.code = code
        self.close = close
        self.change_price = change
        self.change_rate = rate
        self.open = close - 100
        self.high = close + 50
        self.low = close - 150
        self.total_volume = 10
        self.total_amount = 20.0
        self.ts = int((time.time() + 8 * 3600) * 1e9)


class _Group(dict):
    pass


class _Api:
    def __init__(self, snaps):
        self._snaps = snaps
        self.requested = []

        class _Indexs:
            TSE = _Group({"IX0001": "c-twii"})
            OTC = _Group({"IX0043": "c-tpex"})

        class _Contracts:
            Indexs = _Indexs

        self.Contracts = _Contracts

    def snapshots(self, contracts):
        self.requested.append(list(contracts))
        return self._snaps


@pytest.fixture(autouse=True)
def _reset():
    sf._reset_for_tests()
    yield
    sf._reset_for_tests()


def test_shioaji_main_indices_maps_taiex_and_otc(monkeypatch):
    # 快照回傳順序故意與合約相反，結果仍要加權在前
    api = _Api([_Snap("IX0043", 395.42, 7.54, 1.94), _Snap("IX0001", 46887.77, 594.84, 1.28)])
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setattr(sf, "_ensure_session", lambda: api)

    rows = sf.shioaji_main_indices()

    assert api.requested == [["c-twii", "c-tpex"]]
    assert [r["code"] for r in rows] == ["TWII", "TPEX"]
    twii = rows[0]
    assert twii["current"] == 46887.77
    assert twii["change"] == 594.84
    assert twii["change_pct"] == 1.28
    assert twii["prev_close"] == pytest.approx(46292.93)
    assert twii["as_of"].endswith("+08:00")


def test_shioaji_main_indices_none_without_session(monkeypatch):
    monkeypatch.setattr(sf, "_HAS_SHIOAJI", True)
    monkeypatch.setattr(sf, "_ensure_session", lambda: None)
    assert sf.shioaji_main_indices() is None


def _manager_with_yfinance(monkeypatch, yf_rows):
    class _Yf:
        name = "YfinanceFetcher"

        def get_main_indices(self, region="cn"):
            return yf_rows

    mgr = DataFetcherManager.__new__(DataFetcherManager)
    mgr._fetchers = [_Yf()]
    monkeypatch.setattr(DataFetcherManager, "_get_tickflow_fetcher", lambda self: None, raising=False)
    return mgr


_GHOST = [{"code": "TWII", "current": 46292.93, "change": 0.0, "change_pct": 0.0}]


def test_tw_prefers_shioaji_over_yfinance(monkeypatch):
    from market_data import market_repo
    import market_data.db as mdb

    shioaji_rows = [{"code": "TWII", "current": 46887.77}, {"code": "TPEX", "current": 395.42}]
    monkeypatch.setattr(sf, "shioaji_main_indices", lambda: shioaji_rows)
    # 官方收盤也有資料，但盤中它是前一場次，Shioaji 要優先
    monkeypatch.setattr(mdb, "get_engine", lambda **kw: object())
    monkeypatch.setattr(
        market_repo, "latest_market_index",
        lambda index_id, engine=None: {"date": "2026-10-20", "close": 46292.93, "change": -529.15},
    )
    mgr = _manager_with_yfinance(monkeypatch, _GHOST)
    assert mgr.get_main_indices("tw") == shioaji_rows


def test_tw_falls_back_to_official_close_before_yfinance(monkeypatch):
    from market_data import market_repo
    import market_data.db as mdb

    monkeypatch.setattr(sf, "shioaji_main_indices", lambda: None)
    monkeypatch.setattr(mdb, "get_engine", lambda **kw: object())
    monkeypatch.setattr(
        market_repo, "latest_market_index",
        lambda index_id, engine=None: {"date": "2026-10-21", "close": 46887.77, "change": 594.84},
    )
    mgr = _manager_with_yfinance(monkeypatch, _GHOST)

    rows = mgr.get_main_indices("tw")

    assert len(rows) == 1
    assert rows[0]["code"] == "TWII"
    assert rows[0]["current"] == 46887.77
    assert rows[0]["change_pct"] == pytest.approx(594.84 / 46292.93 * 100)
    assert rows[0]["as_of"] == "2026-10-21"


def test_tw_uses_yfinance_only_when_both_tw_sources_fail(monkeypatch):
    from market_data import market_repo
    import market_data.db as mdb

    monkeypatch.setattr(sf, "shioaji_main_indices", lambda: None)
    monkeypatch.setattr(mdb, "get_engine", lambda **kw: object())

    def _boom(index_id, engine=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(market_repo, "latest_market_index", _boom)
    mgr = _manager_with_yfinance(monkeypatch, _GHOST)
    assert mgr.get_main_indices("tw") == _GHOST


def test_non_tw_region_skips_tw_sources(monkeypatch):
    def _fail():
        raise AssertionError("台股來源不該被問")

    monkeypatch.setattr(sf, "shioaji_main_indices", _fail)
    us_rows = [{"code": "SPX", "current": 1.0}]
    mgr = _manager_with_yfinance(monkeypatch, us_rows)
    assert mgr.get_main_indices("us") == us_rows
