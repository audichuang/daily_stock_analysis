# -*- coding: utf-8 -*-
"""美股顯示名稱：只用 NASDAQ Trader 官方清單（前端股票索引），查無就用代號。

上游 `stock_mapping.STOCK_NAME_MAP` 把十幾檔美股寫死成簡體中文名（英伟达、微软），
不是任何公開 API 的資料，也沒有繁體版本。本 fork 的美股名稱一律以
`scripts/refresh_us_stock_index.py` 從官方清單刷新的索引為準；索引沒有的代碼
顯示代號本身，不另外猜中文名。
"""

from typing import Any, Optional

from data_provider.us_index_mapping import is_us_stock_code
from src.data.stock_index_loader import get_index_stock_name


def official_us_stock_name(code: Any) -> Optional[str]:
    """美股代碼回官方清單名，清單沒有回代號；非美股回 None（呼叫端照原邏輯）。"""
    text = str(code or "").strip().upper()
    if not text or not is_us_stock_code(text):
        return None
    return get_index_stock_name(text) or text


def display_stock_name(code: Any, stored_name: Any) -> Any:
    """讀取端用：美股改顯示官方名（含已存進歷史的舊簡體名），其他市場原樣。"""
    return official_us_stock_name(code) or stored_name
