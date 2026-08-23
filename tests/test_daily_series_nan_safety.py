# -*- coding: utf-8 -*-
"""日线序列 API 的 NaN 安全。

`market_repo.to_daily_frame` 现在从 close 自己 shift 推 pct_chg，视窗第一列因此是
NaN（缺资料）。原来的 `float(x) if x else None` 对 NaN 是 True（`bool(nan)` 为真），
会把 NaN 原封不动送进 JSON——那是非法 JSON。0 是合法读数，不能当缺资料一起吞掉。
"""

import math
import unittest

from src.services.stock_service import _opt_float


class OptFloatTestCase(unittest.TestCase):
    def test_nan_becomes_none(self):
        self.assertIsNone(_opt_float(float("nan")))

    def test_none_stays_none(self):
        self.assertIsNone(_opt_float(None))

    def test_zero_is_a_reading_not_missing_data(self):
        """反向守门：把 falsy 一律当缺资料会让这个测试红。"""
        self.assertEqual(_opt_float(0), 0.0)
        self.assertEqual(_opt_float(0.0), 0.0)

    def test_negative_and_positive_pass_through(self):
        self.assertEqual(_opt_float(-1.26), -1.26)
        self.assertEqual(_opt_float("1.47"), 1.47)

    def test_unparseable_becomes_none(self):
        self.assertIsNone(_opt_float("n/a"))
        self.assertIsNone(_opt_float(object()))

    def test_infinity_is_kept_as_is(self):
        """只处理 NaN；inf 若真的出现应由上游判定，不在这里静默改语义。"""
        self.assertTrue(math.isinf(_opt_float(float("inf"))))


if __name__ == "__main__":
    unittest.main()
