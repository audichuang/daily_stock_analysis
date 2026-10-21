# -*- coding: utf-8 -*-
"""美股顯示名稱只用官方清單索引，查無回代號；非美股不介入。"""

from unittest.mock import patch

import src.data.us_stock_name as usn
from src.analyzer import get_stock_name_multi_source


def test_us_code_uses_official_index_name():
    with patch.object(usn, "get_index_stock_name", return_value="NVIDIA Corporation"):
        assert usn.display_stock_name("NVDA", "英伟达") == "NVIDIA Corporation"


def test_us_code_missing_from_index_shows_ticker():
    with patch.object(usn, "get_index_stock_name", return_value=None):
        assert usn.display_stock_name("ZZZZ", "某个中文名") == "ZZZZ"


def test_non_us_codes_keep_stored_name():
    with patch.object(usn, "get_index_stock_name", side_effect=AssertionError("不該查美股索引")):
        assert usn.display_stock_name("2330.TW", "台積電") == "台積電"
        assert usn.display_stock_name("600519", "贵州茅台") == "贵州茅台"
        assert usn.display_stock_name("MARKET", "大盤複盤") == "大盤複盤"
        # 美股指數別名不是個股
        assert usn.display_stock_name("SPX", "标普500") == "标普500"


def test_analyzer_name_resolution_skips_hardcoded_us_chinese_name():
    with patch.object(usn, "get_index_stock_name", return_value="Microsoft Corporation"):
        assert get_stock_name_multi_source("MSFT") == "Microsoft Corporation"
