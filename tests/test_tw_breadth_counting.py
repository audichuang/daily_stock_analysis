# -*- coding: utf-8 -*-
"""`tw_breadth.count_advance_decline` 的純函式守門（不需要 DB，CI 也跑得到）。

DB 接線那一半在 `market_data/tests/test_tw_breadth_db.py`（需要 `DATABASE_URL`，
CI 會 skip），所以計數語意本身必須在這裡守住。
"""

import unittest

import pandas as pd

from data_provider.tw_breadth import count_advance_decline


def _s(mapping):
    return pd.Series(mapping, dtype="float64")


class CountAdvanceDeclineTestCase(unittest.TestCase):
    def test_counts_up_down_and_flat(self):
        today = _s({"2330": 2410.0, "2615": 80.0, "2317": 200.0})
        prev = _s({"2330": 2375.0, "2615": 82.0, "2317": 200.0})
        self.assertEqual(
            count_advance_decline(today, prev),
            {"up_count": 1, "down_count": 1, "flat_count": 1},
        )

    def test_missing_price_is_no_comparison_basis_not_flat(self):
        """TWSE 官方另有「無比價」一欄；把缺價算進平盤會虛增分母。"""
        today = _s({"2330": 2410.0, "9999": float("nan"), "8888": 50.0})
        prev = _s({"2330": 2375.0, "9999": 100.0, "8888": float("nan")})
        counts = count_advance_decline(today, prev)
        self.assertEqual(counts, {"up_count": 1, "down_count": 0, "flat_count": 0})
        # 反向守門：把 dropna 拿掉會讓 flat_count 變 2
        self.assertEqual(sum(counts.values()), 1)

    def test_stocks_absent_from_one_side_are_excluded(self):
        """新上市／當日停牌只出現在一邊，對齊後是 NaN，同樣不計入。"""
        today = _s({"2330": 2410.0, "6666": 30.0})
        prev = _s({"2330": 2375.0})
        self.assertEqual(
            count_advance_decline(today, prev),
            {"up_count": 1, "down_count": 0, "flat_count": 0},
        )

    def test_all_missing_returns_none_rather_than_zeroes(self):
        """全缺要回 None 讓呼叫端降級；回 {0,0,0} 會被下游當成真讀數。"""
        today = _s({"2330": float("nan")})
        prev = _s({"2330": float("nan")})
        self.assertIsNone(count_advance_decline(today, prev))

    def test_empty_input_returns_none(self):
        self.assertIsNone(count_advance_decline(_s({}), _s({})))

    def test_float_noise_counts_as_flat(self):
        """前復權是浮點乘法，1e-13 的殘差不是漲跌（台股最小跳動 0.01）。"""
        today = _s({"2330": 100.0 + 1e-13})
        prev = _s({"2330": 100.0})
        self.assertEqual(
            count_advance_decline(today, prev),
            {"up_count": 0, "down_count": 0, "flat_count": 1},
        )

    def test_a_real_one_cent_move_is_not_swallowed_by_the_epsilon(self):
        """反向守門：把 eps 放大到吃掉真實跳動會讓這個測試紅。"""
        today = _s({"2330": 100.01, "2317": 99.99})
        prev = _s({"2330": 100.00, "2317": 100.00})
        self.assertEqual(
            count_advance_decline(today, prev),
            {"up_count": 1, "down_count": 1, "flat_count": 0},
        )


if __name__ == "__main__":
    unittest.main()
