# -*- coding: utf-8 -*-
"""Tests that _augment_historical_with_realtime uses market-local date."""

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from src.core.pipeline import StockAnalysisPipeline
from src.core.trading_calendar import MarketPhase


def _make_pipeline():
    p = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    p.config = SimpleNamespace(enable_realtime_technical_indicators=True)
    return p


def _make_df(dates_and_closes):
    rows = [
        {"code": "AAPL", "date": d, "open": c, "high": c, "low": c, "close": c, "volume": 100, "amount": 0, "pct_chg": 0}
        for d, c in dates_and_closes
    ]
    return pd.DataFrame(rows)


class AugmentRealtimeMarketDateTestCase(unittest.TestCase):
    """Verify _augment_historical_with_realtime uses market-local date, not server date."""

    @patch("src.core.pipeline.is_market_open", return_value=True)
    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="us")
    def test_appends_virtual_row_with_market_local_date(
        self, _mock_market, mock_now, _mock_open
    ):
        """When server is UTC and US market date differs, virtual row uses market date."""
        # Server UTC: 2026-03-28 01:00 => US ET: 2026-03-27 21:00
        us_market_now = datetime(2026, 3, 27, 21, 0)
        mock_now.return_value = us_market_now

        df = _make_df([(date(2026, 3, 26), 150.0)])
        quote = SimpleNamespace(price=155.0, open_price=151.0, high=156.0, low=149.0, volume=200, amount=None, change_pct=3.0, pre_close=None)

        pipeline = _make_pipeline()
        result = pipeline._augment_historical_with_realtime(df, quote, "AAPL")

        self.assertEqual(len(result), 2)
        appended_date = result.iloc[-1]["date"]
        if hasattr(appended_date, "date"):
            appended_date = appended_date.date()
        self.assertEqual(appended_date, date(2026, 3, 27))

    @patch("src.core.pipeline.is_market_open", return_value=True)
    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="us")
    def test_updates_existing_row_when_data_matches_market_date(
        self, _mock_market, mock_now, _mock_open
    ):
        """When latest bar date >= market_today, update in place instead of appending."""
        mock_now.return_value = datetime(2026, 3, 27, 17, 0)

        df = _make_df([(date(2026, 3, 26), 150.0), (date(2026, 3, 27), 152.0)])
        quote = SimpleNamespace(price=155.0, open_price=151.0, high=156.0, low=149.0, volume=200, amount=None, change_pct=3.0, pre_close=None)

        pipeline = _make_pipeline()
        result = pipeline._augment_historical_with_realtime(df, quote, "AAPL")

        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[-1]["close"], 155.0)

    @patch("src.core.pipeline.is_market_open", return_value=False)
    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    def test_skips_augmentation_on_non_trading_day(
        self, _mock_market, mock_now, _mock_open
    ):
        """Weekend/holiday: returns df unchanged."""
        mock_now.return_value = datetime(2026, 3, 28, 10, 0)

        df = _make_df([(date(2026, 3, 27), 30.0)])
        quote = SimpleNamespace(price=31.0, open_price=30.5, high=31.5, low=29.5, volume=100, amount=None, change_pct=1.0, pre_close=None)

        pipeline = _make_pipeline()
        result = pipeline._augment_historical_with_realtime(df, quote, "600519")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["close"], 30.0)


def _make_tw_df(rows):
    """rows: [(date, close, volume, amount)]"""
    return pd.DataFrame([
        {"code": "2330.TW", "date": d, "open": c, "high": c, "low": c, "close": c,
         "volume": v, "amount": a, "pct_chg": 0}
        for d, c, v, a in rows
    ])


class AugmentRealtimeCumulativeVolumeTestCase(unittest.TestCase):
    """同日已有 DB K 時，即時量／額只能放大不能縮小（累計量單調不減）。

    每案都斷言 close 已換成即時價：_augment 在 PREMARKET／非交易日會提早回傳原 df，
    只看量的測試會在「根本沒走進覆蓋分支」時空轉通過。
    """

    TODAY = date(2026, 10, 16)  # 週五，交易日

    def _run(self, phase, df, quote):
        with patch("src.core.pipeline.get_market_for_stock", return_value="tw"), \
                patch("src.core.pipeline.is_market_open", return_value=True), \
                patch("src.core.pipeline.infer_market_phase", return_value=phase), \
                patch("src.core.pipeline.get_market_now",
                      return_value=datetime(2026, 10, 16, 18, 0)):
            return _make_pipeline()._augment_historical_with_realtime(df, quote, "2330.TW")

    def _quote(self, **kw):
        base = dict(price=1010.0, open_price=1000.0, high=1015.0, low=995.0,
                    volume=4441000, amount=4.4e9, change_pct=1.0, pre_close=None)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_postmarket_keeps_official_volume_and_amount(self):
        df = _make_tw_df([(date(2026, 10, 15), 1000.0, 3000000, 3.0e9),
                          (self.TODAY, 1008.0, 4812882, 4.9e9)])
        result = self._run(MarketPhase.POSTMARKET, df, self._quote())
        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[-1]["close"], 1010.0)  # 證明走進覆蓋分支
        self.assertEqual(result.iloc[-1]["volume"], 4812882)
        self.assertEqual(result.iloc[-1]["amount"], 4.9e9)

    def test_intraday_partial_bar_grows_to_realtime_volume(self):
        df = _make_tw_df([(date(2026, 10, 15), 1000.0, 3000000, 3.0e9),
                          (self.TODAY, 1008.0, 1000000, 1.0e9)])
        result = self._run(MarketPhase.INTRADAY, df, self._quote(volume=2000000, amount=2.0e9))
        self.assertEqual(result.iloc[-1]["close"], 1010.0)
        self.assertEqual(result.iloc[-1]["volume"], 2000000)
        self.assertEqual(result.iloc[-1]["amount"], 2.0e9)

    def test_append_branch_uses_realtime_volume_even_if_prev_bar_larger(self):
        """追加分支（DB 沒有今天）不與前一根比：昨日量較大也不能被帶進今天。"""
        df = _make_tw_df([(date(2026, 10, 15), 1000.0, 9000000, 9.0e9)])
        result = self._run(MarketPhase.POSTMARKET, df, self._quote(volume=4441000, amount=4.4e9))
        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[-1]["close"], 1010.0)
        self.assertEqual(result.iloc[-1]["volume"], 4441000)
        self.assertEqual(result.iloc[-1]["amount"], 4.4e9)

    def test_db_row_without_volume_takes_realtime_volume(self):
        df = _make_tw_df([(date(2026, 10, 15), 1000.0, 3000000, 3.0e9),
                          (self.TODAY, 1008.0, float("nan"), float("nan"))])
        result = self._run(MarketPhase.POSTMARKET, df, self._quote())
        self.assertEqual(result.iloc[-1]["volume"], 4441000)
        self.assertEqual(result.iloc[-1]["amount"], 4.4e9)

    def test_premarket_leaves_df_untouched(self):
        """空轉守門：PREMARKET 提早回傳，close 不變——證明上面各案的 close 斷言確實依賴分支。"""
        df = _make_tw_df([(self.TODAY, 1008.0, 4812882, 4.9e9)])
        result = self._run(MarketPhase.PREMARKET, df, self._quote())
        self.assertEqual(result.iloc[-1]["close"], 1008.0)
        self.assertEqual(result.iloc[-1]["volume"], 4812882)


if __name__ == "__main__":
    unittest.main()
