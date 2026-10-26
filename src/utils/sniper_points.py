# -*- coding: utf-8 -*-
"""模型判斷的狙擊價格契約，以及舊版純數值的相容讀取。"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any, Dict, Optional


SNIPER_KEYS = ("ideal_buy", "secondary_buy", "stop_loss", "take_profit")
SNIPER_PRICES_PROMPT = """
## 結構化狙擊價格（必填）
在 dashboard.battle_plan.sniper_points 保留原本的說明文字，並在同層輸出
sniper_prices，包含 ideal_buy、secondary_buy、stop_loss、take_profit 四個鍵。
每個值只能是有限正數或 null，不得用字串、布林值或省略鍵。
由你判斷可執行價格；null 表示你判斷目前沒有可執行價格，不能把觀察條件當成建議。
若建議區間，只輸出你實際會執行的單一價格，完整區間與觸發條件留在 sniper_points 文字。
減碼／賣出或買進前提尚未成立時，兩個買點輸出 null；有明確回測掛單價的觀望可保留買點。
stop_loss 與 take_profit 也必須分別判斷，不得從句中的任意數字猜值。
"""

# 只驗證舊資料的字面數值格式，不解讀自然語言。區間沿用右端點的舊契約。
_NUMBER = r"(?:[0-9]{1,3}(?:[,，][0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
_LEGACY_PRICE = re.compile(rf"({_NUMBER})\s*(?:元)?(?:\s*[-~～至]\s*({_NUMBER})\s*(?:元)?)?")


def structured_price(value: Any) -> Optional[float]:
    """只接受 JSON 數值；排除布林值、非有限值與非正數。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        price = float(value)
    except (OverflowError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def parse_sniper_value(value: Any, field: Optional[str] = None) -> Optional[float]:
    """舊資料只接受純數字、數字加元或純區間；field 保留呼叫相容性。"""
    if isinstance(value, (int, float)):
        return structured_price(value)
    if not isinstance(value, str):
        return None
    match = _LEGACY_PRICE.fullmatch(value.strip())
    if match is None:
        return None
    return structured_price(float((match.group(2) or match.group(1)).replace(",", "").replace("，", "")))


def _find_block(data: Any, name: str) -> Optional[Mapping[str, Any]]:
    if not isinstance(data, Mapping):
        return None
    value = data.get(name)
    if value is not None:
        # 已有新契約但格式損壞時拒收，不回退到文字猜價。
        return value if isinstance(value, Mapping) else {}
    for key in ("battle_plan", "dashboard"):
        found = _find_block(data.get(key), name)
        if found is not None:
            return found
    return None


def find_sniper_prices(data: Any) -> Optional[Mapping[str, Any]]:
    """None 表示舊版；空物件與明確 null 欄位都不可回退。"""
    return _find_block(data, "sniper_prices")


def find_sniper_points(data: Any) -> Optional[Mapping[str, Any]]:
    if not isinstance(data, Mapping):
        return None
    found = _find_block(data, "sniper_points")
    if found is not None:
        return found
    if any(key in data for key in SNIPER_KEYS):
        return data
    return None


def resolve_sniper_prices(data: Any, stored: Any = None) -> Dict[str, Optional[float]]:
    """新契約優先；舊原文存在時不讓已存的過期數值復活。"""
    prices = find_sniper_prices(data)
    if prices is not None:
        return {key: structured_price(prices.get(key)) for key in SNIPER_KEYS}
    points = find_sniper_points(data) or {}
    resolved = {}
    for key in SNIPER_KEYS:
        value = points.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            value = stored.get(key) if isinstance(stored, Mapping) else getattr(stored, key, None)
        resolved[key] = parse_sniper_value(value, key)
    return resolved


def extract_sniper_points(result: Any) -> Dict[str, Optional[float]]:
    """所有數值消費端共用：支援結果物件、原始 payload 與巢狀 dashboard。"""
    if isinstance(result, Mapping):
        return resolve_sniper_prices(result)
    candidates = (getattr(result, "dashboard", None), getattr(result, "raw_response", None))
    for candidate in candidates:
        if find_sniper_prices(candidate) is not None:
            return resolve_sniper_prices(candidate)
    if hasattr(result, "get_sniper_points"):
        points = result.get_sniper_points()
        if isinstance(points, Mapping) and any(v not in (None, "") for v in points.values()):
            return resolve_sniper_prices(points)
    for candidate in candidates:
        points = find_sniper_points(candidate)
        if points and any(v not in (None, "") for v in points.values()):
            return resolve_sniper_prices(candidate)
    return dict.fromkeys(SNIPER_KEYS)


def display_sniper_prices(data: Any) -> Dict[str, str]:
    """精簡價位卡只展示可執行數字；完整報告另保留 sniper_points 原文。"""
    return {key: str(value) if value is not None else "N/A"
            for key, value in resolve_sniper_prices(data).items()}


def missing_stop_loss_field(battle: Any) -> Optional[str]:
    """明確 null 是模型判斷；缺鍵或格式錯誤才需要補全。"""
    prices = find_sniper_prices(battle)
    if prices is not None:
        if "stop_loss" in prices and (prices["stop_loss"] is None or structured_price(prices["stop_loss"]) is not None):
            return None
        return "dashboard.battle_plan.sniper_prices.stop_loss"
    if resolve_sniper_prices(battle)["stop_loss"] is not None:
        return None
    return "dashboard.battle_plan.sniper_points.stop_loss"
