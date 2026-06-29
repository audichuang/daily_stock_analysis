# -*- coding: utf-8 -*-
"""台股涨跌停计算 tw_price_limits 单元测试（±10% + tick 对齐）。"""

import pytest

from data_provider.shioaji_fetcher import tw_price_limits


@pytest.mark.parametrize(
    "reference, expected_up, expected_down",
    [
        (2340.0, 2570.0, 2110.0),   # 2330：>=1000，tick 5（涨停向下取 2574->2570，跌停向上取 2106->2110）
        (18.25, 20.05, 16.45),      # 6116：10-50，tick 0.05
        (164.0, 180.0, 148.0),      # 100-500，tick 0.5（180.4->180.0；147.6->148.0）
        (5.0, 5.5, 4.5),            # <10，tick 0.01
        (600.0, 660.0, 540.0),      # 500-1000，tick 1
    ],
)
def test_tw_price_limits_known(reference, expected_up, expected_down):
    up, down = tw_price_limits(reference)
    assert up == pytest.approx(expected_up)
    assert down == pytest.approx(expected_down)
    # 不可超过 ±10%
    assert up <= reference * 1.1 + 1e-9
    assert down >= reference * 0.9 - 1e-9


def test_tw_price_limits_invalid():
    assert tw_price_limits(None) == (None, None)
    assert tw_price_limits(0) == (None, None)
    assert tw_price_limits(-5) == (None, None)
