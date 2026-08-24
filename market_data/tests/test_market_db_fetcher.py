"""`MarketDBFetcher` 的日線正規化必須把除權息因子帶進 `to_daily_frame`。

`price.change` 對上市歷史列沒有正負號、除權息日的 `change` 又是對參考價的差值，
所以 pct_chg 只能由 close 自己 shift 推導；而 `price` 是未還原價，除權息日的
價格斷崖必須套 `market.price_adjustment` 才是真實報酬（P1-2）。
"""

import pandas as pd
import pytest

from data_provider.base import DataSourceUnavailableError


def _frame():
    return pd.DataFrame([
        {"date": "2026-08-20", "close": 146.0},
        {"date": "2026-08-21", "close": 140.5},
    ])


def test_normalize_data_passes_event_factors(monkeypatch):
    from data_provider import market_db_fetcher as mod
    from market_data import market_repo

    sentinels = pd.Series([0.969658], index=pd.DatetimeIndex(["2026-08-21"]))
    seen = {}

    def fake_multipliers(sid, **_kwargs):
        seen["sid"] = sid
        return sentinels

    def fake_to_daily_frame(df, event_factors=None):
        seen["factors"] = event_factors
        return "FRAME"

    monkeypatch.setattr(market_repo, "adjustment_multipliers", fake_multipliers)
    monkeypatch.setattr(market_repo, "to_daily_frame", fake_to_daily_frame)

    out = mod.MarketDBFetcher()._normalize_data(_frame(), "2458.TW")

    assert out == "FRAME"
    assert seen["sid"] == "2458"          # '2458.TW' -> '2458'
    assert seen["factors"] is sentinels   # 因子必須真的傳下去


def test_normalize_data_maps_factor_query_errors_to_unavailable(monkeypatch):
    """價格抓到了但因子查詢失敗 ⇒ 整條降級 fallback，不能默默回未還原報酬。"""
    from data_provider import market_db_fetcher as mod
    from market_data import market_repo

    def boom(sid, **_kwargs):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(market_repo, "adjustment_multipliers", boom)

    with pytest.raises(DataSourceUnavailableError):
        mod.MarketDBFetcher()._normalize_data(_frame(), "2458.TW")
