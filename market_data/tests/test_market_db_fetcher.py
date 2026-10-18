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

    def fake_multipliers(sid, **kwargs):
        seen["sid"] = sid
        seen["sessions"] = kwargs.get("sessions")
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
    # 休市日事件要靠 sessions 才搬得到下一個交易日；沒傳就是舊行為（那天 pct_chg 變假跌幅）
    assert seen["sessions"] is not None
    assert list(pd.DatetimeIndex(seen["sessions"])) == list(pd.to_datetime(_frame()["date"]))


def test_normalize_data_maps_factor_query_errors_to_unavailable(monkeypatch):
    """價格抓到了但因子查詢失敗 ⇒ 整條降級 fallback，不能默默回未還原報酬。"""
    from data_provider import market_db_fetcher as mod
    from market_data import market_repo

    def boom(sid, **kwargs):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(market_repo, "adjustment_multipliers", boom)

    with pytest.raises(DataSourceUnavailableError):
        mod.MarketDBFetcher()._normalize_data(_frame(), "2458.TW")


def test_normalize_data_pct_chg_uses_closed_day_event_on_next_session(monkeypatch):
    """2891 的 07-10 颱風休市日公告因子 0.9641：07-13 的 pct_chg 是 -1.32%，不是 -4.9%。"""
    from data_provider import market_db_fetcher as mod
    from market_data import market_repo

    events = pd.DataFrame([{"date": pd.Timestamp("2026-07-10"), "factor": 0.9641,
                            "source": "twse_twt49u"}])
    monkeypatch.setattr(market_repo, "_q", lambda sql, params, engine: events.copy())
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-07-08", "2026-07-09", "2026-07-13"]),
        "open": 1.0, "high": 1.0, "low": 1.0, "volume": 1, "turnover": 1,
        "close": [70.0, 69.90, 66.50],
    })
    out = mod.MarketDBFetcher()._normalize_data(df, "2891.TW")
    assert out["pct_chg"].iloc[2] == pytest.approx(-1.32, abs=0.01)
