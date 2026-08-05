# -*- coding: utf-8 -*-
"""釘住 `fast_info` 的前收欄位選擇——選錯會讓美股個股的漲跌幅**方向相反**。

2026-08-03 實測（週一台北、美股未開盤）：MU 的 `previousClose` 是 812.48 而 `lastPrice`
是 823.03，算出 **+1.30%**；正規前收 `regularMarketPreviousClose` 是 874.66，算出 **−5.90%**
——後者才是真值。AAPL 同樣是 **+0.51% vs −7.35%**。

這個錯誤不報錯、不缺欄位，只給一個反向的數字，而下游拿它當「隔夜美股方向」判 regime。
指數與韓股的兩個欄位相同，所以只有美股個股會顯形——這也是它能潛伏的原因。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_provider.yfinance_fetcher import YfinanceFetcher  # noqa: E402

prev_close = YfinanceFetcher._prev_close_from_fast_info


def test_regular_market_previous_close_wins_when_both_exist():
    """MU 的真實形狀：兩個欄位都在、值差 7.6%，必須取正規收盤那個。"""
    info = SimpleNamespace(previous_close=812.48, regular_market_previous_close=874.66)
    assert prev_close(info) == 874.66
    # 拿錯的那個會把 -5.90% 算成 +1.30%
    assert (823.03 / prev_close(info) - 1) < 0


def test_falls_back_to_previous_close_when_regular_absent():
    """舊版 yfinance 或某些標的只有 previousClose，仍要能算出漲跌幅。"""
    assert prev_close(SimpleNamespace(previous_close=100.0)) == 100.0


def test_returns_none_when_fast_info_has_no_close_field():
    """全缺時回 None，讓上層走 history 兜底而不是算出一個假的漲跌幅。"""
    assert prev_close(SimpleNamespace(last_price=1.0)) is None


def test_camel_case_keys_are_also_accepted():
    """`fast_info` 是 dict-like——屬性存取走 snake_case，但別讓 camelCase 物件失效。"""
    assert prev_close(SimpleNamespace(regularMarketPreviousClose=874.66)) == 874.66


def test_zero_is_not_treated_as_a_valid_close():
    """0 會讓下游的 `prev_close > 0` 守門擋掉；這裡確認它不會蓋掉真正的候選。"""
    info = SimpleNamespace(regular_market_previous_close=0, previous_close=812.48)
    assert prev_close(info) == 812.48
