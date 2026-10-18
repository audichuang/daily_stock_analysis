# -*- coding: utf-8 -*-
"""T21：台股技術指標用前復權 OHLCV（只乘 MarketDBFetcher 列、volume 反向調整、顯示價不變）。

被測入口是 ``StockAnalysisPipeline._build_trend_input_frame``（Step 3 餵給
``trend_analyzer.analyze`` 的 df）。``market_repo.front_adjust_multipliers`` 以忠實的
假實作取代（只計入 ``date <= max(收到的 dates)`` 的事件），並記錄收到的 dates，
讓「as_of 必須是 augment 之後 df 的最大日期」可被斷言。
"""

import logging
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from src.core.pipeline import StockAnalysisPipeline
from src.core.trading_calendar import MarketPhase

_TPE = ZoneInfo("Asia/Taipei")
FACTOR = 0.335  # 6669 2026-09-02 1:3 分割的形狀
EVENT_DAY = date(2026, 10, 16)  # 假設的事件日（週五）


def _fake_front_adjust(events, calls):
    def fake(stock_id, dates, engine=None):
        idx = pd.DatetimeIndex(pd.to_datetime(pd.Series(list(dates))))
        calls.append({"stock_id": stock_id, "dates": list(idx)})
        asof = idx.max().normalize()
        out = []
        for d in idx.normalize():
            m = 1.0
            for ev_day, f in events.items():
                if d < pd.Timestamp(ev_day) <= asof:
                    m *= f
            out.append(m)
        return pd.Series(out, index=idx)

    return fake


def _history(last, n=6, source="MarketDBFetcher"):
    """n 根升序日線，最後一根日期 = last；close 100、volume 3000。"""
    days = pd.bdate_range(end=pd.Timestamp(last), periods=n)
    return pd.DataFrame(
        {
            "code": "6669.TW",
            "date": [d.date() for d in days],
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 100.0,
            "volume": 3000.0,
            "amount": 1.0,
            "pct_chg": 0.5,
            "data_source": source,
        }
    )


def _quote(price=110.0):
    return SimpleNamespace(
        price=price, open_price=105.0, high=111.0, low=104.0, volume=900,
        amount=1000.0, change_pct=1.0, pre_close=100.0,
    )


def _pipeline():
    p = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    p.config = SimpleNamespace(
        enable_realtime_quote=True, enable_realtime_technical_indicators=True
    )
    return p


class _Base(unittest.TestCase):
    def run_frame(self, df, *, market="tw", phase, now, quote=None, events=None):
        calls = []
        fake = _fake_front_adjust(events if events is not None else {EVENT_DAY: FACTOR}, calls)
        with patch("market_data.market_repo.front_adjust_multipliers", side_effect=fake), \
             patch("market_data.db.get_engine", return_value=object()), \
             patch("src.core.pipeline.get_market_now", return_value=now), \
             patch("src.core.pipeline.is_market_open", return_value=True), \
             patch("src.core.pipeline.infer_market_phase", return_value=phase):
            out = _pipeline()._build_trend_input_frame(
                df, quote, "6669.TW" if market == "tw" else "AAPL", market
            )
        return out, calls


class FrontAdjustTrendFrameTestCase(_Base):
    def test_intraday_today_event_adjusts_all_earlier_marketdb_rows_last_row_unchanged(self):
        df = _history(date(2026, 10, 15))  # DB 止於 T-1，今天（10-16）是事件日、盤中追加今天
        out, calls = self.run_frame(
            df, phase=MarketPhase.INTRADAY,
            now=datetime(2026, 10, 16, 10, 30, tzinfo=_TPE), quote=_quote(110.0),
        )
        # as_of 必須是 augment 之後的最大日期（今天）
        self.assertEqual(calls[0]["stock_id"], "6669")
        self.assertEqual(max(calls[0]["dates"]).date(), EVENT_DAY)
        self.assertEqual(len(out), len(df) + 1)
        hist, last = out.iloc[:-1], out.iloc[-1]
        for col, base in (("open", 100.0), ("high", 102.0), ("low", 98.0), ("close", 100.0)):
            self.assertTrue(((hist[col] - base * FACTOR).abs() < 1e-9).all(), col)
        self.assertTrue(((hist["volume"] - 3000.0 / FACTOR).abs() < 1e-6).all())
        # 最新價（即時追加列）不變
        self.assertEqual(last["close"], 110.0)
        self.assertEqual(last["volume"], 900)
        # 非 OHLCV 欄位不動
        self.assertTrue((out["pct_chg"].iloc[:-1] == 0.5).all())
        # 呼叫端的 df 不被原地修改
        self.assertTrue((df["close"] == 100.0).all())

    def test_premarket_today_event_does_not_touch_any_row(self):
        df = _history(date(2026, 10, 15))
        out, calls = self.run_frame(
            df, phase=MarketPhase.PREMARKET,
            now=datetime(2026, 10, 16, 8, 0, tzinfo=_TPE), quote=_quote(110.0),
        )
        # 開盤前不追加今天 → as_of ＝ 10-15，今天的因子不作用
        self.assertEqual(max(calls[0]["dates"]).date(), date(2026, 10, 15))
        self.assertEqual(len(out), len(df))
        pd.testing.assert_frame_equal(out, df)

    def test_event_inside_history_adjusts_only_rows_before_it_last_unchanged(self):
        df = _history(date(2026, 10, 19))  # 事件日 10-16 在歷史內，無即時報價
        out, _ = self.run_frame(
            df, phase=MarketPhase.POSTMARKET,
            now=datetime(2026, 10, 19, 19, 0, tzinfo=_TPE), quote=None,
        )
        before = out[out["date"] < EVENT_DAY]
        after = out[out["date"] >= EVENT_DAY]
        self.assertFalse(before.empty)
        self.assertTrue(((before["close"] - 100.0 * FACTOR).abs() < 1e-9).all())
        self.assertTrue(((before["volume"] - 3000.0 / FACTOR).abs() < 1e-6).all())
        self.assertTrue((after["close"] == 100.0).all())
        self.assertTrue((after["volume"] == 3000.0).all())
        self.assertEqual(out.iloc[-1]["close"], 100.0)

    def test_yfinance_rows_are_not_multiplied(self):
        df = _history(date(2026, 10, 19))
        df.loc[1, "data_source"] = "YfinanceFetcher"  # 其中一根是 yfinance 備援列
        with self.assertLogs("src.core.pipeline", level=logging.WARNING) as cm:
            out, _ = self.run_frame(
                df, phase=MarketPhase.POSTMARKET,
                now=datetime(2026, 10, 19, 19, 0, tzinfo=_TPE), quote=None,
            )
        self.assertEqual(out.loc[1, "close"], 100.0)
        self.assertEqual(out.loc[1, "volume"], 3000.0)
        self.assertAlmostEqual(out.loc[0, "close"], 100.0 * FACTOR)
        self.assertAlmostEqual(out.loc[2, "close"], 100.0 * FACTOR)
        self.assertTrue(any("非 MarketDB" in m for m in cm.output))

    def test_front_adjust_failure_passes_original_values_without_raising(self):
        df = _history(date(2026, 10, 19))
        with patch("market_data.market_repo.front_adjust_multipliers", side_effect=RuntimeError("db down")), \
             patch("market_data.db.get_engine", return_value=object()), \
             patch("src.core.pipeline.get_market_now", return_value=datetime(2026, 10, 19, 19, 0, tzinfo=_TPE)), \
             patch("src.core.pipeline.is_market_open", return_value=True), \
             patch("src.core.pipeline.infer_market_phase", return_value=MarketPhase.POSTMARKET):
            with self.assertLogs("src.core.pipeline", level=logging.WARNING):
                out = _pipeline()._build_trend_input_frame(df, None, "6669.TW", "tw")
        pd.testing.assert_frame_equal(out, df)

    def test_non_tw_market_never_calls_front_adjust(self):
        df = _history(date(2026, 10, 19))
        calls = []
        with patch("market_data.market_repo.front_adjust_multipliers",
                   side_effect=_fake_front_adjust({EVENT_DAY: FACTOR}, calls)):
            out = _pipeline()._build_trend_input_frame(df, None, "AAPL", "us")
        self.assertEqual(calls, [])
        pd.testing.assert_frame_equal(out, df)


class AnalyzeStockWiringTestCase(unittest.TestCase):
    """Step 3 真的把前復權後的 df 交給 ``trend_analyzer.analyze``（接線，不只 helper）。"""

    def _run(self, code):
        from unittest.mock import MagicMock

        from src.enums import ReportType
        from tests.test_pipeline_market_phase_context import _make_pipeline

        pipeline = _make_pipeline(agent_mode=False, save_context_snapshot=False)
        hist = _history(date(2026, 10, 19))
        pipeline.db.get_data_range.return_value = [
            SimpleNamespace(to_dict=(lambda r=r: r.to_dict())) for _, r in hist.iterrows()
        ]
        seen = []
        pipeline.trend_analyzer = MagicMock()
        pipeline.trend_analyzer.analyze.side_effect = lambda df, c: seen.append(df.copy()) or MagicMock()
        calls = []
        with patch("market_data.market_repo.front_adjust_multipliers",
                   side_effect=_fake_front_adjust({EVENT_DAY: FACTOR}, calls)), \
             patch("market_data.db.get_engine", return_value=object()):
            pipeline.analyze_stock(code, ReportType.SIMPLE, "q-t21",
                                   current_time=datetime(2026, 10, 19, 19, 0, tzinfo=_TPE))
        return seen, calls

    def test_tw_stock_trend_input_is_front_adjusted(self):
        seen, calls = self._run("6669.TW")
        self.assertEqual(len(seen), 1)
        self.assertEqual(len(calls), 1)
        df = seen[0]
        self.assertAlmostEqual(df.iloc[0]["close"], 100.0 * FACTOR)
        self.assertAlmostEqual(df.iloc[0]["volume"], 3000.0 / FACTOR)
        self.assertEqual(df.iloc[-1]["close"], 100.0)

    def test_us_stock_trend_input_is_untouched(self):
        seen, calls = self._run("AAPL")
        self.assertEqual(calls, [])
        self.assertTrue((seen[0]["close"] == 100.0).all())


if __name__ == "__main__":
    unittest.main()
