# -*- coding: utf-8 -*-
"""Regression tests for YfinanceFetcher daily data normalization."""

import pandas as pd
import pytest

from data_provider.yfinance_fetcher import YfinanceFetcher


def test_normalize_daily_data_recovers_unnamed_datetime_index_date_column() -> None:
    fetcher = YfinanceFetcher()
    raw = pd.DataFrame(
        {
            "Open": [10.0, 10.5],
            "High": [11.0, 11.2],
            "Low": [9.8, 10.1],
            "Close": [10.8, 11.0],
            "Volume": [1000, 1200],
        },
        index=pd.DatetimeIndex(["2026-05-25", "2026-05-26"]),
    )

    normalized = fetcher._normalize_data(raw, "DRAM")
    cleaned = fetcher._clean_data(normalized)

    assert "date" in normalized.columns
    assert cleaned["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-05-25", "2026-05-26"]


def _record_download_kwargs(monkeypatch) -> dict:
    """攔下 yf.download 的 kwargs；回傳一個最小的合法 frame 讓 _fetch_raw_data 走完。"""
    import yfinance

    captured: dict = {}

    def fake_download(*args, **kwargs):
        captured.update(kwargs)
        return pd.DataFrame(
            {"Close": [10.0], "Volume": [100]},
            index=pd.DatetimeIndex(["2026-07-30"]),
        )

    monkeypatch.setattr(yfinance, "download", fake_download)
    return captured


@pytest.mark.parametrize("code", ["2330.TW", "6488.TWO"])
def test_fetch_raw_data_taiwan_uses_unadjusted_close(monkeypatch, code) -> None:
    captured = _record_download_kwargs(monkeypatch)

    YfinanceFetcher()._fetch_raw_data(code, "2026-07-01", "2026-07-31")

    assert captured["auto_adjust"] is False


def test_fetch_raw_data_us_keeps_adjusted_close(monkeypatch) -> None:
    captured = _record_download_kwargs(monkeypatch)

    YfinanceFetcher()._fetch_raw_data("AAPL", "2026-07-01", "2026-07-31")

    assert captured["auto_adjust"] is True


def test_normalize_data_drops_adj_close_column() -> None:
    raw = pd.DataFrame(
        {
            "Open": [10.0, 10.5],
            "High": [11.0, 11.2],
            "Low": [9.8, 10.1],
            "Close": [10.8, 11.0],
            "Adj Close": [10.1, 10.3],
            "Volume": [1000, 1200],
        },
        index=pd.DatetimeIndex(["2026-07-29", "2026-07-30"]),
    )

    normalized = YfinanceFetcher()._normalize_data(raw, "2330.TW")

    assert "Adj Close" not in normalized.columns
    assert "adj_close" not in normalized.columns
    assert normalized["close"].tolist() == [10.8, 11.0]
