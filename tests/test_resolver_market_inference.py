# -*- coding: utf-8 -*-
"""`name_to_code_resolver` 的市场推断必须认得台股与日韩。

上游 #2245 引进的 `_infer_code_market` / `_MARKET_ORDER` 只有 a/hk/us，而
`_find_codes_for_name` 对 market 为 None 的代码是**直接丢弃**——台股与日韩代码
在那条路上等于不存在。本 fork 补齐；这个档案守住补齐后的语意。
"""

import unittest

from src.services.name_to_code_resolver import _MARKET_ORDER, _infer_code_market


class InferCodeMarketTestCase(unittest.TestCase):
    def test_taiwan_bare_four_digit_is_tw(self):
        """上游三个市场都不用 4 位（hk 5 位、a 6 位、us 字母），所以不冲突。"""
        self.assertEqual(_infer_code_market("2330"), "tw")
        self.assertEqual(_infer_code_market("0050"), "tw")

    def test_taiwan_suffixes_are_tw(self):
        for code in ("2330.TW", "6488.TWO", "0050.TW"):
            with self.subTest(code=code):
                self.assertEqual(_infer_code_market(code), "tw")

    def test_japan_and_korea_suffixes_resolve(self):
        self.assertEqual(_infer_code_market("7203.T"), "jp")
        self.assertEqual(_infer_code_market("005930.KS"), "kr")

    def test_upstream_markets_are_unchanged(self):
        """反向守门：补台股不能动到既有三个市场的判定。"""
        self.assertEqual(_infer_code_market("600519"), "a")
        self.assertEqual(_infer_code_market("00700"), "hk")
        self.assertEqual(_infer_code_market("AAPL"), "us")
        self.assertEqual(_infer_code_market("BRK.A"), "us")

    def test_bare_six_digit_stays_a_share(self):
        """裸 6 位无法区分 A 股与韩股（005930 与 000001 都是 0 开头）。

        沿用上游的 "a" 是刻意的——猜错方向比不猜更糟；要正确解析韩股得带 .KS/.KQ。
        这个断言存在是为了让「哪天有人改成 kr」变成一个需要解释的决定。
        """
        self.assertEqual(_infer_code_market("005930"), "a")

    def test_documented_gaps_stay_none(self):
        """带字母的台股 ETF 两种写法都不覆盖，docstring 有写明原因。"""
        self.assertIsNone(_infer_code_market("00631L"))
        self.assertIsNone(_infer_code_market("00631L.TW"))
        self.assertIsNone(_infer_code_market(""))

    def test_market_order_covers_every_market_the_classifier_can_return(self):
        """分类器回得出的市场，排序表都要有——否则 KeyError 或被丢弃。"""
        returned = {
            _infer_code_market(c)
            for c in ("2330", "2330.TW", "7203.T", "005930.KS", "600519", "00700", "AAPL")
        }
        returned.discard(None)
        self.assertTrue(returned <= set(_MARKET_ORDER), returned - set(_MARKET_ORDER))

    def test_upstream_market_priority_is_not_reordered(self):
        """新市场附加在尾端；既有三个的相对顺序不动（没有呼叫端可以验行为变化）。"""
        self.assertEqual(_MARKET_ORDER["a"], 0)
        self.assertEqual(_MARKET_ORDER["hk"], 1)
        self.assertEqual(_MARKET_ORDER["us"], 2)
        for market in ("tw", "jp", "kr"):
            self.assertGreater(_MARKET_ORDER[market], _MARKET_ORDER["us"])


if __name__ == "__main__":
    unittest.main()
