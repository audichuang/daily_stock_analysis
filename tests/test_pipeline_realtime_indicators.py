# -*- coding: utf-8 -*-
"""
Issue #234 盘中实时技术指标的单元测试。

覆盖范围：
- _augment_historical_with_realtime：追加/更新逻辑和防护条件
- _compute_ma_status：均线排列文案
- _enhance_context：使用 realtime + trend_result 覆盖 today
"""

import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from data_provider.realtime_types import UnifiedRealtimeQuote, RealtimeSource
from src.stock_analyzer import StockTrendAnalyzer, TrendAnalysisResult, TrendStatus
from src.core.pipeline import StockAnalysisPipeline
from src.core.trading_calendar import MarketPhase


def _make_realtime_quote(
    price: float = 15.72,
    open_price: float = 15.62,
    high: float = 16.29,
    low: float = 15.55,
    volume: int = 13995600,
    amount: float = None,
    change_pct: float = 0.96,
    **overrides,
) -> UnifiedRealtimeQuote:
    overrides.setdefault("source", RealtimeSource.TENCENT)
    return UnifiedRealtimeQuote(
        code="600519",
        name="贵州茅台",
        price=price,
        open_price=open_price,
        high=high,
        low=low,
        volume=volume,
        amount=amount,
        change_pct=change_pct,
        **overrides,
    )


def _make_historical_df(days: int = 25, last_date: date = None) -> pd.DataFrame:
    """构造历史 OHLCV DataFrame。"""
    if last_date is None:
        last_date = date.today() - timedelta(days=1)
    dates = [last_date - timedelta(days=i) for i in range(days - 1, -1, -1)]
    base = 100.0
    data = []
    for i, d in enumerate(dates):
        close = base + i * 0.5
        data.append({
            "code": "600519",
            "date": d,
            "open": close - 0.2,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 1000000 + i * 10000,
            "amount": close * (1000000 + i * 10000),
            "pct_chg": 0.5,
            "ma5": close,
            "ma10": close - 0.1,
            "ma20": close - 0.2,
            "volume_ratio": 1.0,
        })
    return pd.DataFrame(data)


class TestAugmentHistoricalWithRealtime(unittest.TestCase):
    """_augment_historical_with_realtime 的测试。"""

    def setUp(self) -> None:
        self._db_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "test_issue234.db"
        )
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with patch.dict(os.environ, {"DATABASE_PATH": self._db_path}):
            from src.config import Config
            Config._instance = None
            self.config = Config._load_from_env()
        self.pipeline = StockAnalysisPipeline(config=self.config)

    def test_returns_unchanged_when_realtime_none(self) -> None:
        df = _make_historical_df()
        result = self.pipeline._augment_historical_with_realtime(df, None, "600519")
        self.assertIs(result, df)
        self.assertEqual(len(result), len(df))

    def test_returns_unchanged_when_price_invalid(self) -> None:
        df = _make_historical_df()
        quote = _make_realtime_quote(price=0)
        result = self.pipeline._augment_historical_with_realtime(df, quote, "600519")
        self.assertEqual(len(result), len(df))
        quote2 = MagicMock()
        quote2.price = None
        result2 = self.pipeline._augment_historical_with_realtime(df, quote2, "600519")
        self.assertEqual(len(result2), len(df))

    def test_returns_unchanged_when_df_empty(self) -> None:
        df = pd.DataFrame()
        quote = _make_realtime_quote()
        result = self.pipeline._augment_historical_with_realtime(df, quote, "600519")
        self.assertTrue(result.empty)

    def test_returns_unchanged_when_df_missing_close(self) -> None:
        df = pd.DataFrame({"date": [date.today()], "open": [100]})
        quote = _make_realtime_quote()
        result = self.pipeline._augment_historical_with_realtime(df, quote, "600519")
        self.assertEqual(len(result), 1)
        self.assertNotIn("close", result.columns)

    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.is_market_open", return_value=True)
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    @patch("src.core.pipeline.infer_market_phase", return_value=MarketPhase.INTRADAY)
    def test_appends_row_when_last_date_before_today(
        self, _mock_phase, _mock_market, _mock_open, mock_now
    ) -> None:
        today = date.today()
        # 固定市场时钟为 UTC 当日，使 pipeline 的 market_today 等于 date.today()，
        # 不受 get_market_now 通常使用的市场时区影响（例如 CST=UTC+8）。
        mock_now.return_value = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc
        )
        df = _make_historical_df(last_date=today - timedelta(days=1))
        quote = _make_realtime_quote(price=15.72)
        result = self.pipeline._augment_historical_with_realtime(df, quote, "600519")
        self.assertEqual(len(result), len(df) + 1)
        last = result.iloc[-1]
        self.assertEqual(last["close"], 15.72)
        self.assertEqual(last["date"], today)

    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.is_market_open", return_value=True)
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    @patch("src.core.pipeline.infer_market_phase", return_value=MarketPhase.INTRADAY)
    def test_updates_last_row_when_last_date_is_today(
        self, _mock_phase, _mock_market, _mock_open, mock_now
    ) -> None:
        today = date.today()
        # 固定市场时钟为当日，使 last_date >= market_today，从而更新最后一行而不是追加。
        # 这可以避免 CI 在 CST 收盘后运行时出现日期边界偏移。
        mock_now.return_value = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc
        )
        df = _make_historical_df(last_date=today, days=25)
        df.loc[df.index[-1], "date"] = today
        quote = _make_realtime_quote(price=16.0)
        result = self.pipeline._augment_historical_with_realtime(df, quote, "600519")
        self.assertEqual(len(result), len(df))
        self.assertEqual(result.iloc[-1]["close"], 16.0)


class TestPremarketGuard(unittest.TestCase):
    """開盤前不得補當日 K 棒（`src/core/pipeline.py` 的 PREMARKET 早退）。

    這道 guard 之前**零覆蓋**，所以上面兩個測試漏 patch `infer_market_phase` 才會
    一直沒被發現——它們的成敗取決於真實時鐘落在哪個盤別。
    """

    def setUp(self) -> None:
        # 與 TestAugmentHistoricalWithRealtime 同款：Config 走隔離的 sqlite 路徑。
        self._db_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "test_issue234.db"
        )
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with patch.dict(os.environ, {"DATABASE_PATH": self._db_path}):
            from src.config import Config
            Config._instance = None
            self.config = Config._load_from_env()
        self.pipeline = StockAnalysisPipeline(config=self.config)

    def _premarket_augment(self, *, db_last_offset: int, session_offset: int, provider_offset=None, **quote_kw):
        """盤前補 K：DB 最新列在 today-db_last_offset、上一場在 today-session_offset。"""
        today = date.today()
        now = datetime(today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc)
        quote = _make_realtime_quote(price=999.0, **quote_kw)
        if provider_offset is not None:
            quote.provider_timestamp = (today - timedelta(days=provider_offset)).isoformat()
        df = _make_historical_df(last_date=today - timedelta(days=db_last_offset))
        with patch("src.core.pipeline.get_market_now", return_value=now), \
                patch("src.core.pipeline.is_market_open", return_value=True), \
                patch("src.core.pipeline.get_market_for_stock", return_value="us"), \
                patch("src.core.pipeline.infer_market_phase", return_value=MarketPhase.PREMARKET), \
                patch(
                    "src.core.pipeline.get_effective_trading_date",
                    return_value=today - timedelta(days=session_offset),
                ):
            result = self.pipeline._augment_historical_with_realtime(df, quote, "AAPL")
        return today, df, result

    def test_premarket_does_not_fabricate_today_bar(self) -> None:
        """盤前的「即時價」其實是昨收，疊上去會造出一根假日線讓指標全錯。"""
        _, df, result = self._premarket_augment(db_last_offset=1, session_offset=1)
        self.assertEqual(len(result), len(df))
        self.assertNotEqual(result.iloc[-1]["close"], 999.0)

    def test_premarket_fills_missing_prior_session_bar_with_quote(self) -> None:
        """DB 缺 T-1（10/22 紐約盤前 Yahoo 的 10-21 空白）：報價就是 T-1 收盤，補成 T-1 那根。

        只改 today 的日期標籤不夠——均線等指標仍算在停在 T-2 的序列上。
        """
        today, df, result = self._premarket_augment(db_last_offset=2, session_offset=1)
        self.assertEqual(len(result), len(df) + 1)
        self.assertEqual(result.iloc[-1]["close"], 999.0)
        self.assertEqual(result.iloc[-1]["date"], today - timedelta(days=1))

    def test_premarket_never_appends_bar_dated_today(self) -> None:
        """反向：日曆查詢失敗（fail-open 回今天）或報價自稱今天，盤前都不得補今天的 K 棒。"""
        _, df, result = self._premarket_augment(db_last_offset=2, session_offset=0)
        self.assertEqual(len(result), len(df))
        _, df, result = self._premarket_augment(db_last_offset=2, session_offset=1, provider_offset=0)
        self.assertEqual(result.iloc[-1]["date"], date.today() - timedelta(days=1))

    def test_premarket_undated_stooq_quote_is_not_appended_as_prior_session(self) -> None:
        """Stooq 兜底不帶日期、可能和 DB 一樣停在 T-2：不能憑日曆把它補成 T-1 那根。

        實測 2026-10-22 08:00 紐約、DB 與 Stooq 都停在 10/20：舊行為補出 10/21 假 K，MA5 102.0→102.8。
        """
        _, df, result = self._premarket_augment(db_last_offset=2, session_offset=1, source=RealtimeSource.STOOQ)
        self.assertEqual(len(result), len(df))
        self.assertNotEqual(result.iloc[-1]["close"], 999.0)

    def test_premarket_dated_stooq_quote_for_prior_session_is_appended(self) -> None:
        """反向：Stooq 報價自帶的日期就是缺的那一場時照補。"""
        today, df, result = self._premarket_augment(
            db_last_offset=2, session_offset=1, provider_offset=1, source=RealtimeSource.STOOQ
        )
        self.assertEqual(len(result), len(df) + 1)
        self.assertEqual(result.iloc[-1]["date"], today - timedelta(days=1))

    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.is_market_open", return_value=True)
    @patch("src.core.pipeline.get_market_for_stock", return_value="us")
    @patch("src.core.pipeline.infer_market_phase", return_value=MarketPhase.POSTMARKET)
    def test_postmarket_still_augments(
        self, _mock_phase, _mock_market, _mock_open, mock_now
    ) -> None:
        """反向守門：只擋 PREMARKET。收盤後那筆即時價就是當日收盤，仍該補。

        把 guard 寫成「非盤中一律擋」會讓這條紅。
        """
        today = date.today()
        mock_now.return_value = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc
        )
        df = _make_historical_df(last_date=today - timedelta(days=1))
        result = self.pipeline._augment_historical_with_realtime(
            df, _make_realtime_quote(price=999.0), "AAPL"
        )
        self.assertEqual(len(result), len(df) + 1)
        self.assertEqual(result.iloc[-1]["close"], 999.0)


class TestComputeMaStatus(unittest.TestCase):
    """_compute_ma_status 的测试。"""

    def test_bullish_alignment(self) -> None:
        status = StockAnalysisPipeline._compute_ma_status(11, 10, 9.5, 9)
        self.assertIn("多头", status)

    def test_bearish_alignment(self) -> None:
        status = StockAnalysisPipeline._compute_ma_status(8, 9, 9.5, 10)
        self.assertIn("空头", status)

    def test_consolidation(self) -> None:
        status = StockAnalysisPipeline._compute_ma_status(10, 10, 10, 10)
        self.assertIn("震荡", status)


class TestEnhanceContextRealtimeOverride(unittest.TestCase):
    """_enhance_context 使用实时行情和趋势结果覆盖 today 的测试。"""

    def setUp(self) -> None:
        self._db_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "test_issue234.db"
        )
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with patch.dict(os.environ, {"DATABASE_PATH": self._db_path}):
            from src.config import Config
            Config._instance = None
            self.config = Config._load_from_env()
        self.pipeline = StockAnalysisPipeline(config=self.config)

    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    def test_today_overridden_when_realtime_and_trend_exist(
        self, _mock_market, mock_now
    ) -> None:
        today = date.today()
        # 固定市场时钟，使 _enhance_context 设置 enhanced['date'] == date.today().isoformat()，
        # 不受 get_market_now 通常使用的市场时区影响（例如 CST=UTC+8）。
        mock_now.return_value = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc
        )
        context = {
            "code": "600519",
            "date": (today - timedelta(days=1)).isoformat(),
            "today": {"close": 15.0, "ma5": 14.8, "ma10": 14.5},
            "yesterday": {"close": 14.5, "volume": 1000000},
        }
        quote = _make_realtime_quote(price=15.72, volume=2000000)
        trend = TrendAnalysisResult(
            code="600519",
            trend_status=TrendStatus.BULL,
            ma5=15.5,
            ma10=15.2,
            ma20=14.9,
        )
        enhanced = self.pipeline._enhance_context(
            context, quote, None, trend, "贵州茅台"
        )
        self.assertEqual(enhanced["today"]["close"], 15.72)
        self.assertEqual(enhanced["today"]["ma5"], 15.5)
        self.assertEqual(enhanced["today"]["ma10"], 15.2)
        self.assertEqual(enhanced["today"]["ma20"], 14.9)
        self.assertIn("多头", enhanced["ma_status"])
        self.assertEqual(enhanced["date"], today.isoformat())
        self.assertEqual(enhanced["today"]["date"], today.isoformat())
        self.assertEqual(enhanced["today"]["data_source"], "realtime:tencent")
        self.assertEqual(enhanced["today"]["realtime_source"], "tencent")
        self.assertIn("price_change_ratio", enhanced)
        self.assertIn("volume_change_ratio", enhanced)

    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    def test_tencent_688691_volume_change_ratio_uses_normalized_share_volume(
        self, _mock_market, mock_now
    ) -> None:
        today = date.today()
        mock_now.return_value = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc
        )
        context = {
            "code": "688691",
            "date": (today - timedelta(days=1)).isoformat(),
            "today": {
                "close": 128.46,
                "volume": 19512753,
                "amount": 2487341983,
                "date": (today - timedelta(days=1)).isoformat(),
                "dataSource": "AkshareFetcher",
            },
            "yesterday": {"close": 128.46, "volume": 19512753},
        }
        quote = UnifiedRealtimeQuote(
            code="688691",
            name="灿芯股份",
            source=RealtimeSource.TENCENT,
            price=122.70,
            open_price=120.09,
            high=125.96,
            low=116.20,
            volume=10931723,
            amount=1327404280,
            change_pct=3.40,
        )
        trend = TrendAnalysisResult(
            code="688691",
            trend_status=TrendStatus.BULL,
            ma5=120.014,
            ma10=119.425,
            ma20=115.8305,
        )

        enhanced = self.pipeline._enhance_context(
            context, quote, None, trend, "灿芯股份"
        )

        self.assertEqual(enhanced["today"]["volume"], 10931723)
        self.assertEqual(enhanced["today"]["amount"], 1327404280)
        self.assertEqual(enhanced["volume_change_ratio"], 0.56)
        self.assertEqual(enhanced["today"]["date"], today.isoformat())
        self.assertEqual(enhanced["today"]["data_source"], "realtime:tencent")
        self.assertEqual(enhanced["today"]["realtime_source"], "tencent")
        self.assertNotIn("dataSource", enhanced["today"])

    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    def test_realtime_metadata_and_partial_estimated_fields_are_propagated(
        self, _mock_market, mock_now
    ) -> None:
        today = date.today()
        mock_now.return_value = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc
        )
        context = {
            "code": "600519",
            "date": (today - timedelta(days=1)).isoformat(),
            "today": {
                "close": 15.0,
                "amount": 999999,
                "date": (today - timedelta(days=1)).isoformat(),
                "dataSource": "AkshareFetcher",
            },
            "yesterday": {"close": 14.5, "volume": 1000000},
        }
        quote = _make_realtime_quote(
            price=15.72,
            amount=None,
            fetched_at="2026-05-31T10:00:05+00:00",
            provider_timestamp="2026-05-31T10:00:00+00:00",
            is_stale=False,
            stale_seconds=5,
            fallback_from="efinance",
        )
        trend = TrendAnalysisResult(
            code="600519",
            trend_status=TrendStatus.BULL,
            ma5=15.5,
            ma10=15.2,
            ma20=14.9,
        )

        enhanced = self.pipeline._enhance_context(
            context,
            quote,
            None,
            trend,
            "贵州茅台",
            market_phase_context={"is_partial_bar": True},
        )

        self.assertEqual(enhanced["realtime"]["source"], "tencent")
        self.assertEqual(enhanced["realtime"]["fetched_at"], "2026-05-31T10:00:05+00:00")
        self.assertEqual(enhanced["realtime"]["provider_timestamp"], "2026-05-31T10:00:00+00:00")
        self.assertIs(enhanced["realtime"]["is_stale"], False)
        self.assertEqual(enhanced["realtime"]["stale_seconds"], 5)
        self.assertEqual(enhanced["realtime"]["fallback_from"], "efinance")
        self.assertTrue(enhanced["today"]["is_partial_bar"])
        self.assertTrue(enhanced["today"]["is_estimated"])
        self.assertEqual(
            enhanced["today"]["estimated_fields"],
            ["close", "open", "high", "low", "ma5", "ma10", "ma20", "volume", "pct_chg"],
        )
        self.assertEqual(enhanced["today"]["fetched_at"], "2026-05-31T10:00:05+00:00")
        self.assertEqual(enhanced["today"]["provider_timestamp"], "2026-05-31T10:00:00+00:00")
        self.assertEqual(enhanced["today"]["fallback_from"], "efinance")
        self.assertNotIn("amount", enhanced["today"])
        self.assertNotIn("dataSource", enhanced["today"])

    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    def test_realtime_today_does_not_backfill_historical_amount_or_source(
        self, _mock_market, mock_now
    ) -> None:
        today = date.today()
        mock_now.return_value = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc
        )
        context = {
            "code": "600519",
            "date": (today - timedelta(days=1)).isoformat(),
            "today": {
                "close": 15.0,
                "amount": 999999,
                "date": (today - timedelta(days=1)).isoformat(),
                "dataSource": "AkshareFetcher",
                "code": "600519",
            },
            "yesterday": {"close": 14.5, "volume": 1000000},
        }
        quote = _make_realtime_quote(price=15.72, amount=None)
        trend = TrendAnalysisResult(
            code="600519",
            trend_status=TrendStatus.BULL,
            ma5=15.5,
            ma10=15.2,
            ma20=14.9,
        )

        enhanced = self.pipeline._enhance_context(
            context, quote, None, trend, "贵州茅台"
        )

        self.assertNotIn("amount", enhanced["today"])
        self.assertNotIn("dataSource", enhanced["today"])
        self.assertEqual(enhanced["today"]["date"], today.isoformat())
        self.assertEqual(enhanced["today"]["data_source"], "realtime:tencent")
        self.assertEqual(enhanced["today"]["code"], "600519")

    def _enhance_same_day(self, orig_date, orig_volume, orig_amount, quote, date_as_str=False):
        today = date.today()
        trend = TrendAnalysisResult(
            code="2330.TW", trend_status=TrendStatus.BULL, ma5=15.5, ma10=15.2, ma20=14.9,
        )
        context = {
            "code": "2330.TW",
            "date": orig_date.isoformat(),
            "today": {"close": 15.0, "volume": orig_volume, "amount": orig_amount,
                      "date": orig_date.isoformat() if date_as_str else orig_date},
            "yesterday": {"close": 14.5, "volume": 4000000},
        }
        with patch("src.core.pipeline.get_market_now") as mock_now, \
                patch("src.core.pipeline.get_market_for_stock", return_value="tw"), \
                patch("src.core.pipeline.is_market_open", return_value=True), \
                patch("src.core.pipeline.infer_market_phase", return_value=MarketPhase.POSTMARKET):
            mock_now.return_value = datetime(
                today.year, today.month, today.day, 18, 0, tzinfo=timezone.utc
            )
            return self.pipeline._enhance_context(context, quote, None, trend, "台積電")

    def test_same_day_postmarket_keeps_official_volume_and_amount(self) -> None:
        """DB 已有今天的官方 K（date 為 date 物件）：量／額不得被較小的即時值縮小。"""
        today = date.today()
        quote = _make_realtime_quote(price=15.72, volume=4441000, amount=4.4e9)
        enhanced = self._enhance_same_day(today, 4812882, 4.9e9, quote)
        self.assertEqual(enhanced["today"]["close"], 15.72)  # 證明走進即時覆蓋
        self.assertEqual(enhanced["today"]["volume"], 4812882)
        self.assertEqual(enhanced["today"]["amount"], 4.9e9)
        self.assertEqual(enhanced["volume_change_ratio"], round(4812882 / 4000000, 2))

    def test_same_day_intraday_takes_larger_realtime_volume(self) -> None:
        today = date.today()
        quote = _make_realtime_quote(price=15.72, volume=2000000, amount=2.0e9)
        enhanced = self._enhance_same_day(today, 1000000, 1.0e9, quote, date_as_str=True)
        self.assertEqual(enhanced["today"]["close"], 15.72)
        self.assertEqual(enhanced["today"]["volume"], 2000000)
        self.assertEqual(enhanced["today"]["amount"], 2.0e9)

    def test_prior_day_orig_today_volume_not_compared(self) -> None:
        """orig_today 是昨天（DB 還沒有今天）：今天的即時量就是今天的量，不與昨日量比。"""
        today = date.today()
        quote = _make_realtime_quote(price=15.72, volume=4441000, amount=4.4e9)
        enhanced = self._enhance_same_day(today - timedelta(days=1), 9000000, 9.0e9, quote)
        self.assertEqual(enhanced["today"]["close"], 15.72)
        self.assertEqual(enhanced["today"]["volume"], 4441000)
        self.assertEqual(enhanced["today"]["amount"], 4.4e9)

    def test_enhance_context_injects_runtime_news_window_days(self) -> None:
        context = {"code": "600519", "today": {"close": 15.0}}
        enhanced = self.pipeline._enhance_context(
            context, None, None, None, "贵州茅台"
        )
        self.assertEqual(
            enhanced["news_window_days"],
            self.pipeline.search_service.news_window_days,
        )

    def test_today_not_overridden_when_trend_missing(self) -> None:
        context = {"code": "600519", "today": {"close": 15.0}}
        quote = _make_realtime_quote(price=15.72)
        enhanced = self.pipeline._enhance_context(
            context, quote, None, None, "贵州茅台"
        )
        self.assertEqual(enhanced["today"]["close"], 15.0)

    def test_today_not_overridden_when_realtime_missing(self) -> None:
        context = {"code": "600519", "today": {"close": 15.0}}
        trend = TrendAnalysisResult(code="600519", ma5=15.0, ma10=14.8, ma20=14.5)
        enhanced = self.pipeline._enhance_context(
            context, None, None, trend, "贵州茅台"
        )
        self.assertEqual(enhanced["today"]["close"], 15.0)

    def test_today_not_overridden_when_trend_ma_zero(self) -> None:
        """StockTrendAnalyzer 因数据不足提前返回 ma5=0.0 时，不应覆盖 today。"""
        context = {"code": "600519", "today": {"close": 15.0, "ma5": 14.8}}
        quote = _make_realtime_quote(price=15.72)
        trend = TrendAnalysisResult(code="600519")  # 默认 ma5=ma10=ma20=0.0
        enhanced = self.pipeline._enhance_context(
            context, quote, None, trend, "贵州茅台"
        )
        self.assertEqual(enhanced["today"]["close"], 15.0)
        self.assertEqual(enhanced["today"]["ma5"], 14.8)


class TestEnhanceContextYesterdayAlignment(unittest.TestCase):
    """T18：盤中拿即時價比 T-2 的錯位（實測 3008：-5.67% 被算成 -9.45%）。

    一律釘 get_market_now／is_market_open／infer_market_phase／get_market_for_stock，
    日期用相對值；並斷言 `today.close` 已被即時價覆蓋，證明測試真的走進覆蓋區塊。
    """

    def setUp(self) -> None:
        self._db_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "test_issue234.db"
        )
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with patch.dict(os.environ, {"DATABASE_PATH": self._db_path}):
            from src.config import Config
            Config._instance = None
            self.config = Config._load_from_env()
        self.pipeline = StockAnalysisPipeline(config=self.config)
        self.today = date.today()
        self.t1 = self.today - timedelta(days=1)
        self.t2 = self.today - timedelta(days=2)

    def _context(self, today_date: date, *, today_extra=None) -> dict:
        today_row = {"close": 100.0, "volume": 1000.0, "date": today_date}
        today_row.update(today_extra or {})
        return {
            "code": "3008.TW",
            "date": today_date.isoformat(),
            "today": today_row,
            # DB 的 T-2（或收盤後的 T-1）
            "yesterday": {"close": 105.0, "volume": 800.0,
                          "date": today_date - timedelta(days=1)},
            # storage.get_analysis_context 以 today 對 yesterday 算出的舊值
            "price_change_ratio": -4.76,
            "volume_change_ratio": 1.25,
        }

    def _trend(self) -> TrendAnalysisResult:
        return TrendAnalysisResult(
            code="3008.TW", trend_status=TrendStatus.BULL, ma5=99.0, ma10=98.0, ma20=97.0,
        )

    def _enhance(self, context, quote, *, market="tw", is_open=True,
                 phase=MarketPhase.INTRADAY, trend="default"):
        from zoneinfo import ZoneInfo
        now = datetime(self.today.year, self.today.month, self.today.day, 10, 53,
                       tzinfo=ZoneInfo("Asia/Taipei"))
        with patch("src.core.pipeline.get_market_now", return_value=now), \
                patch("src.core.pipeline.get_market_for_stock", return_value=market), \
                patch("src.core.pipeline.is_market_open", return_value=is_open), \
                patch("src.core.pipeline.infer_market_phase", return_value=phase):
            return self.pipeline._enhance_context(
                context, quote, None,
                self._trend() if trend == "default" else trend, "測試",
            )

    def test_intraday_shifts_prior_day_into_yesterday(self) -> None:
        ctx = self._context(self.t1)
        # 防止型別不一致讓平移靜默不觸發：輸入是 date 物件，不是字串。
        self.assertIsInstance(ctx["today"]["date"], date)
        quote = _make_realtime_quote(price=94.0, volume=500, change_pct=-5.67)
        enhanced = self._enhance(ctx, quote)
        self.assertEqual(enhanced["today"]["close"], 94.0)  # 走進覆蓋
        self.assertEqual(enhanced["yesterday"]["date"], self.t1)
        self.assertEqual(enhanced["yesterday"]["close"], 100.0)
        # 即時 pct 有值 → 直接用它（單一還原來源），不用 94 對 100 的 -6.0
        self.assertEqual(enhanced["price_change_ratio"], -5.67)
        # 量比以 T-1 量為基準，不是 T-2 的 800
        self.assertEqual(enhanced["volume_change_ratio"], 0.5)

    def test_intraday_without_pct_computes_against_shifted_close(self) -> None:
        quote = _make_realtime_quote(price=94.0, volume=500, change_pct=None)
        enhanced = self._enhance(self._context(self.t1), quote)
        self.assertEqual(enhanced["today"]["close"], 94.0)
        self.assertEqual(enhanced["yesterday"]["date"], self.t1)
        self.assertEqual(enhanced["price_change_ratio"], -6.0)  # 對 T-1 的 100，不是 T-2 的 105

    def test_shift_accepts_iso_string_and_timestamp_dates(self) -> None:
        """降級路徑（_build_analysis_context_from_daily_df）的 date 是 ISO 字串；也可能是 Timestamp。"""
        for form in (self.t1.isoformat(), pd.Timestamp(self.t1)):
            with self.subTest(form=type(form).__name__):
                ctx = self._context(self.t1)
                ctx["today"]["date"] = form
                quote = _make_realtime_quote(price=94.0, volume=500, change_pct=None)
                enhanced = self._enhance(ctx, quote)
                self.assertEqual(enhanced["today"]["close"], 94.0)
                self.assertEqual(enhanced["yesterday"]["close"], 100.0)
                self.assertEqual(enhanced["price_change_ratio"], -6.0)

    def test_postmarket_with_today_already_in_db_does_not_shift(self) -> None:
        ctx = self._context(self.today)
        quote = _make_realtime_quote(price=94.0, volume=500, change_pct=None)
        enhanced = self._enhance(ctx, quote, phase=MarketPhase.POSTMARKET)
        self.assertEqual(enhanced["today"]["close"], 94.0)
        self.assertEqual(enhanced["yesterday"], ctx["yesterday"])
        self.assertEqual(enhanced["price_change_ratio"], round((94.0 - 105.0) / 105.0 * 100, 2))

    def test_premarket_does_not_shift(self) -> None:
        """開盤前的「即時價」其實是 T-1 收盤：平移會讓 volume_change_ratio 變 1.0。"""
        ctx = self._context(self.t1)
        quote = _make_realtime_quote(price=100.0, volume=1000, change_pct=None)
        enhanced = self._enhance(ctx, quote, phase=MarketPhase.PREMARKET)
        self.assertEqual(enhanced["today"]["close"], 100.0)
        self.assertEqual(enhanced["yesterday"], ctx["yesterday"])
        self.assertEqual(enhanced["volume_change_ratio"], 1.25)  # T-1/T-2，不是 1.0

    def test_premarket_quote_is_labelled_with_its_session_and_fills_missing_prior_bar(self) -> None:
        """2026-10-22 紐約盤前 NVDA：DB 停在 T-2（T-1 日線沒入庫），報價是 T-1 收盤。

        舊行為：today 標成 T（掛鐘日）、yesterday 還是 T-3，T-1 與 T-2 的關係整個錯位。
        """
        t3 = self.today - timedelta(days=3)
        ctx = self._context(self.t2)
        ctx["yesterday"]["date"] = t3
        quote = _make_realtime_quote(price=110.0, volume=900, change_pct=None)
        with patch("src.core.pipeline.get_effective_trading_date", return_value=self.t1):
            enhanced = self._enhance(ctx, quote, market="us", phase=MarketPhase.PREMARKET)
        self.assertEqual(enhanced["today"]["close"], 110.0)  # 走進覆蓋
        self.assertEqual(enhanced["today"]["date"], self.t1.isoformat())
        self.assertEqual(enhanced["date"], self.t1.isoformat())
        self.assertEqual(enhanced["yesterday"]["date"], self.t2)
        self.assertEqual(enhanced["price_change_ratio"], 10.0)  # 對 T-2 的 100，不是 T-3 的 105

    def test_premarket_undated_stooq_quote_is_not_labelled_as_missing_prior_session(self) -> None:
        """Stooq 兜底不帶日期：場次不明就整根不覆蓋——不標成 T-1、也不拿它蓋 T-2 的官方 K。

        Codex 重現：DB 收盤 90（T-3）／100（T-2），報價 110：標成 T-1 會錯位；
        標成 T-2 又覆蓋 OHLC，漲幅算成 22.22%（110 對 90）。
        """
        t3 = self.today - timedelta(days=3)
        ctx = self._context(self.t2)
        ctx["yesterday"].update(date=t3, close=90.0)
        orig_today, orig_yesterday = dict(ctx["today"]), dict(ctx["yesterday"])
        quote = _make_realtime_quote(price=110.0, volume=900, change_pct=None, source=RealtimeSource.STOOQ)
        with patch("src.core.pipeline.get_effective_trading_date", return_value=self.t1):
            enhanced = self._enhance(ctx, quote, market="us", phase=MarketPhase.PREMARKET)
        self.assertEqual({k: enhanced["today"][k] for k in orig_today}, orig_today)
        self.assertNotIn("is_estimated", enhanced["today"])
        self.assertEqual(enhanced["yesterday"], orig_yesterday)
        self.assertEqual(enhanced["price_change_ratio"], -4.76)  # 沿用 DB 兩根官方 K 的舊值

    def test_postmarket_undated_stooq_quote_still_overrides_today(self) -> None:
        """反向：盤中／盤後的 Stooq 報價屬於今天，照常覆蓋（只擋場次不明的那段）。"""
        quote = _make_realtime_quote(price=94.0, volume=500, change_pct=None, source=RealtimeSource.STOOQ)
        enhanced = self._enhance(self._context(self.t1), quote, market="us")
        self.assertEqual(enhanced["today"]["close"], 94.0)
        self.assertEqual(enhanced["today"]["date"], self.today.isoformat())

    def test_premarket_with_prior_bar_in_db_labels_prior_session_without_shift(self) -> None:
        """反向：DB 已有 T-1 時不平移，但日期仍是 T-1 不是掛鐘日。"""
        ctx = self._context(self.t1)
        quote = _make_realtime_quote(price=100.0, volume=1000, change_pct=None)
        with patch("src.core.pipeline.get_effective_trading_date", return_value=self.t1):
            enhanced = self._enhance(ctx, quote, phase=MarketPhase.PREMARKET)
        self.assertEqual(enhanced["today"]["date"], self.t1.isoformat())
        self.assertEqual(enhanced["yesterday"], ctx["yesterday"])
        self.assertEqual(enhanced["volume_change_ratio"], 1.25)

    def test_intraday_quote_still_labelled_today(self) -> None:
        """成對守門：盤中報價屬於今天，日期照舊標今天（不能一律標成上一場）。"""
        quote = _make_realtime_quote(price=94.0, volume=500, change_pct=None)
        enhanced = self._enhance(self._context(self.t1), quote)
        self.assertEqual(enhanced["today"]["date"], self.today.isoformat())
        self.assertEqual(enhanced["date"], self.today.isoformat())

    def test_non_trading_day_does_not_shift(self) -> None:
        ctx = self._context(self.t1)
        quote = _make_realtime_quote(price=100.0, volume=1000, change_pct=None)
        # phase 刻意給非 PREMARKET，只讓交易日守門單獨擋住
        enhanced = self._enhance(ctx, quote, is_open=False, phase=MarketPhase.POSTMARKET)
        self.assertEqual(enhanced["today"]["close"], 100.0)
        self.assertEqual(enhanced["yesterday"], ctx["yesterday"])
        self.assertEqual(enhanced["volume_change_ratio"], 1.25)

    def test_weekend_quote_keeps_official_session_volume_in_prompt(self) -> None:
        """重現週日備援量 33,490,300 股覆蓋週五官方量的實測案例。"""
        from src.analyzer import GeminiAnalyzer

        self.today = date(2026, 10, 18)
        ctx = self._context(date(2026, 10, 16), today_extra={
            "volume": 43046982, "amount": 43.05e9,
        })
        ctx["yesterday"]["volume"] = 58486711
        quote = _make_realtime_quote(
            price=100.0, volume=33490300, amount=33.49e9,
            provider_timestamp="2026-10-16T13:30:00+08:00",
            fetched_at="2026-10-18T10:53:00+08:00", is_stale=True,
        )
        enhanced = self._enhance(ctx, quote, is_open=False, phase=MarketPhase.POSTMARKET)
        self.assertEqual(enhanced["today"]["close"], 100.0)
        self.assertEqual(enhanced["today"]["volume"], 43046982)
        self.assertEqual(enhanced["today"]["amount"], 43.05e9)
        self.assertEqual(enhanced["yesterday"], ctx["yesterday"])
        self.assertEqual(enhanced["volume_change_ratio"], 0.74)
        with patch.object(GeminiAnalyzer, "_tw_margin_lines", return_value=""), \
                patch.object(GeminiAnalyzer, "_tw_institutional_trend_lines", return_value=""):
            prompt = GeminiAnalyzer.__new__(GeminiAnalyzer)._format_prompt(
                enhanced, "測試", report_language="zh-TW"
            )
        self.assertIn("4304.70", prompt)
        self.assertIn("成交量較昨日變化：0.74倍", prompt)
        self.assertNotIn("3349.03", prompt)

    def test_premarket_without_provider_time_keeps_official_session_totals(self) -> None:
        """只有抓取時間時，開盤前仍用既有交易日 helper 判定報價場次。"""
        ctx = self._context(self.t1, today_extra={"amount": 100000})
        quote = _make_realtime_quote(
            price=100.0, volume=500, amount=50000,
            fetched_at=f"{self.today.isoformat()}T08:00:00+08:00",
        )
        with patch("src.core.pipeline.get_effective_trading_date", return_value=self.t1):
            enhanced = self._enhance(ctx, quote, phase=MarketPhase.PREMARKET)
        self.assertEqual(enhanced["today"]["close"], 100.0)
        self.assertEqual(enhanced["today"]["volume"], 1000)
        self.assertEqual(enhanced["today"]["amount"], 100000)
        self.assertEqual(enhanced["yesterday"], ctx["yesterday"])
        self.assertEqual(enhanced["volume_change_ratio"], 1.25)

    def test_weekend_newer_quote_session_does_not_take_old_bar_max(self) -> None:
        """反向：休市日也可能 DB 落後一場，不能把較大的舊量帶進新場次。"""
        self.today = date(2026, 10, 18)
        ctx = self._context(date(2026, 10, 15), today_extra={"amount": 100000})
        quote = _make_realtime_quote(
            price=101.0, volume=500, amount=50000,
            provider_timestamp="2026-10-16T13:30:00+08:00",
        )
        enhanced = self._enhance(ctx, quote, is_open=False, phase=MarketPhase.POSTMARKET)
        self.assertEqual(enhanced["today"]["close"], 101.0)
        self.assertEqual(enhanced["today"]["volume"], 500)
        self.assertEqual(enhanced["today"]["amount"], 50000)

    def test_intraday_stale_quote_does_not_shift_the_stored_session(self) -> None:
        """盤中仍可能拿到上一場報價；量與昨日比較必須一起按報價場次對齊。"""
        ctx = self._context(self.t1)
        quote = _make_realtime_quote(
            price=100.0, volume=500,
            provider_timestamp=f"{self.t1.isoformat()}T13:30:00+08:00", is_stale=True,
        )
        enhanced = self._enhance(ctx, quote)
        self.assertEqual(enhanced["today"]["close"], 100.0)
        self.assertEqual(enhanced["today"]["volume"], 1000)
        self.assertEqual(enhanced["yesterday"], ctx["yesterday"])
        self.assertEqual(enhanced["volume_change_ratio"], 1.25)

    def test_non_realtime_tw_uses_adjusted_pct_chg_but_other_markets_do_not(self) -> None:
        """除權息日：庫內收盤未還原相減得 -9.99，已還原 pct_chg 才是 -3.2。"""
        def ctx():
            c = self._context(self.t1, today_extra={"pct_chg": -3.2})
            c["price_change_ratio"] = -9.99
            return c

        tw = self._enhance(ctx(), None, market="tw", trend=None)
        self.assertEqual(tw["price_change_ratio"], -3.2)
        us = self._enhance(ctx(), None, market="us", trend=None)
        self.assertEqual(us["price_change_ratio"], -9.99)
        # 台股但庫內沒有 pct_chg：維持 storage 算出的值
        c = self._context(self.t1)
        c["price_change_ratio"] = -9.99
        self.assertEqual(
            self._enhance(c, None, market="tw", trend=None)["price_change_ratio"], -9.99
        )


if __name__ == "__main__":
    unittest.main()
