# -*- coding: utf-8 -*-
"""
data_provider/yfinance_fetcher 中美股指数获取逻辑的单元测试

使用 unittest.mock 模拟 yfinance API 响应，覆盖：
- _fetch_yf_ticker_data 单指数数据解析
- _get_us_main_indices 美股指数批量获取及异常场景
"""
import math
import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd

# 在导入 data_provider 前 mock 可能缺失的依赖，避免环境差异导致测试无法运行
if 'fake_useragent' not in sys.modules:
    sys.modules['fake_useragent'] = MagicMock()

# 确保能导入项目模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _make_mock_hist(close: float, prev_close: float, high: float = None, low: float = None) -> pd.DataFrame:
    """构造模拟的 history DataFrame，包含计算涨跌幅所需字段"""
    high = high if high is not None else close + 1
    low = low if low is not None else close - 1
    return pd.DataFrame({
        'Close': [prev_close, close],
        'Open': [prev_close - 0.5, close - 0.3],
        'High': [prev_close + 1, high],
        'Low': [prev_close - 1, low],
        'Volume': [1000000.0, 1200000.0],
    }, index=pd.DatetimeIndex(['2025-02-16', '2025-02-17']))


def _make_mock_yf(hist_df: pd.DataFrame):
    """构造模拟的 yf 模块，Ticker().history() 返回给定 DataFrame"""
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist_df
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker
    return mock_yf


class TestFetchYfTickerData(unittest.TestCase):
    """_fetch_yf_ticker_data 单指数取数逻辑测试"""

    def setUp(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        self.fetcher = YfinanceFetcher()

    def test_returns_dict_with_correct_fields(self):
        """正常数据应返回包含 code/name/current/change_pct 等字段的字典"""
        mock_hist = _make_mock_hist(close=5100.0, prev_close=5000.0)
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._fetch_yf_ticker_data(mock_yf, '^GSPC', '标普500指数', 'SPX')

        self.assertIsNotNone(result)
        self.assertEqual(result['code'], 'SPX')
        self.assertEqual(result['name'], '标普500指数')
        self.assertEqual(result['current'], 5100.0)
        self.assertEqual(result['prev_close'], 5000.0)
        self.assertEqual(result['change'], 100.0)
        self.assertAlmostEqual(result['change_pct'], 2.0)
        self.assertIn('open', result)
        self.assertIn('high', result)
        self.assertIn('low', result)
        self.assertIn('volume', result)
        self.assertIn('amount', result)
        self.assertIn('amplitude', result)

    def test_returns_none_when_history_empty(self):
        """history 为空时应返回 None"""
        mock_yf = _make_mock_yf(pd.DataFrame())

        result = self.fetcher._fetch_yf_ticker_data(mock_yf, '^GSPC', '标普500指数', 'SPX')

        self.assertIsNone(result)

    def test_single_row_history_has_no_change_reading(self):
        """僅一行數據時沒有前收：漲跌留 NaN（沒有讀數不是 0），現價照常給"""
        mock_hist = _make_mock_hist(close=5000.0, prev_close=5000.0)
        mock_hist = mock_hist.iloc[[-1]]
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._fetch_yf_ticker_data(mock_yf, '^GSPC', '标普500指数', 'SPX')

        self.assertIsNotNone(result)
        self.assertEqual(result['current'], 5000.0)
        self.assertTrue(math.isnan(result['change_pct']))
        self.assertTrue(math.isnan(result['change']))

    @staticmethod
    def _hist_with_blank_latest_row() -> pd.DataFrame:
        """2026-10-22 紐約盤前的形狀：最新一列 OHLC 全空、只有成交量。"""
        nan = float('nan')
        return pd.DataFrame({
            'Close': [7690.73, 7712.57, nan],
            'Open': [7680.0, 7695.0, nan],
            'High': [7700.0, 7720.0, nan],
            'Low': [7670.0, 7690.0, nan],
            'Volume': [2.7e9, 2.8e9, 2889474000.0],
        }, index=pd.DatetimeIndex(['2026-10-19', '2026-10-20', '2026-10-21']))

    def test_blank_latest_close_uses_fast_info_price_against_previous_close(self):
        mock_yf = _make_mock_yf(self._hist_with_blank_latest_row())
        mock_yf.Ticker.return_value.fast_info.last_price = 7750.0

        result = self.fetcher._fetch_yf_ticker_data(mock_yf, '^GSPC', '标普500指数', 'SPX')

        self.assertEqual(result['current'], 7750.0)
        # 基準是前一個有價格的交易日，不是空列本身
        self.assertEqual(result['prev_close'], 7712.57)
        self.assertAlmostEqual(result['change'], 7750.0 - 7712.57)
        self.assertTrue(math.isfinite(result['change_pct']))

    @staticmethod
    def _hist_with_blank_middle_row(volume: float) -> pd.DataFrame:
        """2026-10-23 實測 ^GSPC：10-21 整場 OHLC 為空（keepna=True 才看得到這列）。"""
        nan = float('nan')
        return pd.DataFrame({
            'Close': [7690.73, 7712.57, nan, 7663.43],
            'Open': [7680.0, 7695.0, nan, 7700.0],
            'High': [7700.0, 7720.0, nan, 7710.0],
            'Low': [7670.0, 7690.0, nan, 7650.0],
            'Volume': [4.5e9, 5.0e9, volume, 3.5e9],
        }, index=pd.DatetimeIndex(['2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22']))

    def test_requests_history_with_blank_rows_kept(self):
        # keepna=False（預設）會把整場空白的 10-21 丟掉，缺一場就看不出來。
        mock_yf = _make_mock_yf(_make_mock_hist(close=5100.0, prev_close=5000.0))
        self.fetcher._fetch_yf_ticker_data(mock_yf, '^GSPC', '标普500指数', 'SPX')
        self.assertTrue(mock_yf.Ticker.return_value.history.call_args.kwargs.get('keepna'))

    def test_blank_previous_session_leaves_change_empty_instead_of_using_two_sessions_back(self):
        for volume in (0.0, 1.2e9):  # 整列空白／只剩成交量（1102 的形狀）都一樣
            with self.subTest(volume=volume):
                mock_yf = _make_mock_yf(self._hist_with_blank_middle_row(volume))
                with self.assertLogs('data_provider.yfinance_fetcher', level='WARNING'):
                    result = self.fetcher._fetch_yf_ticker_data(mock_yf, '^GSPC', '标普500指数', 'SPX')
                self.assertEqual(result['current'], 7663.43)
                # 不得拿 10-20 的 7712.57 當「昨收」報出 -0.64%
                self.assertTrue(math.isnan(result['prev_close']))
                self.assertTrue(math.isnan(result['change_pct']))
                self.assertTrue(math.isnan(result['amplitude']))

    def test_trailing_all_blank_row_is_not_taken_as_latest_session(self):
        # 反向：結尾整列空白（keepna=False 本來就丟的形狀）不當最新列、也不去 fast_info 補價，
        # 最新列仍是最後一場有價格的，漲跌對它緊鄰的前一場；但要留警告。
        hist = self._hist_with_blank_middle_row(0.0).iloc[[0, 1, 2]]
        mock_yf = _make_mock_yf(hist)
        mock_yf.Ticker.return_value.fast_info.last_price = 9999.0
        with self.assertLogs('data_provider.yfinance_fetcher', level='WARNING') as logs:
            result = self.fetcher._fetch_yf_ticker_data(mock_yf, '^GSPC', '标普500指数', 'SPX')
        self.assertEqual(result['current'], 7712.57)
        self.assertEqual(result['prev_close'], 7690.73)
        self.assertTrue(any('整列為空' in line for line in logs.output))

    def test_blank_latest_close_never_substitutes_previous_session_close(self):
        """反向：fast_info 也拿不到時寧可沒有讀數，不得把上一場收盤當成這一場。"""
        mock_yf = _make_mock_yf(self._hist_with_blank_latest_row())
        type(mock_yf.Ticker.return_value).fast_info = property(
            lambda _self: (_ for _ in ()).throw(RuntimeError('no quote'))
        )

        result = self.fetcher._fetch_yf_ticker_data(mock_yf, '^GSPC', '标普500指数', 'SPX')

        self.assertTrue(math.isnan(result['current']))
        self.assertTrue(math.isnan(result['change_pct']))
        self.assertNotEqual(result['current'], 7712.57)


class TestGetUsMainIndices(unittest.TestCase):
    """_get_us_main_indices 美股指数批量获取测试"""

    def setUp(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        self.fetcher = YfinanceFetcher()

    @patch('data_provider.yfinance_fetcher.get_us_index_yf_symbol')
    def test_returns_list_when_mock_succeeds(self, mock_get_symbol):
        """当映射与取数均成功时返回指数列表"""
        def get_symbol(code):
            mapping = {
                'SPX': ('^GSPC', '标普500指数'),
                'IXIC': ('^IXIC', '纳斯达克综合指数'),
                'DJI': ('^DJI', '道琼斯工业指数'),
                'VIX': ('^VIX', 'VIX恐慌指数'),
            }
            return mapping.get(code, (None, None))

        mock_get_symbol.side_effect = get_symbol
        mock_hist = _make_mock_hist(close=5100.0, prev_close=5000.0)
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._get_us_main_indices(mock_yf)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 1)
        for item in result:
            self.assertIn('code', item)
            self.assertIn('name', item)
            self.assertIn('current', item)
            self.assertIn('change_pct', item)

    @patch('data_provider.yfinance_fetcher.get_us_index_yf_symbol')
    def test_handles_empty_history_gracefully(self, mock_get_symbol):
        """部分指数 history 为空时仍返回能取到数据的指数"""
        call_count = [0]

        def get_symbol(code):
            return ('^GSPC', '标普500指数') if code == 'SPX' else (
                ('^IXIC', '纳斯达克综合指数') if code == 'IXIC' else (None, None)
            )

        def history_side_effect(period, **_kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_mock_hist(close=5100.0, prev_close=5000.0)
            return pd.DataFrame()

        mock_get_symbol.side_effect = get_symbol
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = history_side_effect
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        result = self.fetcher._get_us_main_indices(mock_yf)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)

    @patch('data_provider.yfinance_fetcher.get_us_index_yf_symbol')
    def test_returns_none_when_all_fail(self, mock_get_symbol):
        """全部取数失败时返回 None"""
        mock_get_symbol.return_value = (None, None)
        mock_yf = _make_mock_yf(pd.DataFrame())

        result = self.fetcher._get_us_main_indices(mock_yf)

        self.assertIsNone(result)

    @patch('data_provider.yfinance_fetcher.get_us_index_yf_symbol')
    def test_handles_ticker_exception(self, mock_get_symbol):
        """Ticker.history 抛异常时跳过该指数，不整体失败"""
        mock_get_symbol.return_value = ('^GSPC', '标普500指数')
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = Exception("Network error")
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        result = self.fetcher._get_us_main_indices(mock_yf)

        self.assertIsNone(result)

    @patch('data_provider.yfinance_fetcher.get_us_index_yf_symbol')
    def test_skips_unknown_index_code(self, mock_get_symbol):
        """get_us_index_yf_symbol 返回 (None, None) 的代码应被跳过"""
        def get_symbol(code):
            if code == 'SPX':
                return ('^GSPC', '标普500指数')
            return (None, None)

        mock_get_symbol.side_effect = get_symbol
        mock_hist = _make_mock_hist(close=5100.0, prev_close=5000.0)
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._get_us_main_indices(mock_yf)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['code'], 'SPX')


if __name__ == '__main__':
    unittest.main()
