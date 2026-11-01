# -*- coding: utf-8 -*-
"""用量頁的彙總：每日、管道、快取命中、估算費用與前期比較。

輸入是 `DatabaseManager.get_llm_usage_breakdown` 的列；全部是純函式。
"""

from __future__ import annotations

import json
import logging
import math
import os
from typing import Any, Dict, List, Mapping, Optional

from src.llm.backend_registry import LOCAL_CLI_GENERATION_BACKEND_IDS

logger = logging.getLogger(__name__)

PRICE_ENV_KEY = "LLM_USAGE_PRICES"
COST_CURRENCY = "USD"
BILLING_METERED = "metered"
BILLING_SUBSCRIPTION = "subscription"
_TOKENS_PER_PRICE_UNIT = 1_000_000


def load_prices(raw: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """讀 ``LLM_USAGE_PRICES``（JSON，每百萬 token 的美元單價）。

    ``{"模型": {"input": 3, "output": 15, "cache_read": 0.3}}``。不設或格式錯都回空，
    費用顯示 null：用量頁不能因為單價設定而打不開。單項不合法只丟掉該模型。
    """
    text = os.getenv(PRICE_ENV_KEY, "") if raw is None else raw
    if not text.strip():
        return {}
    try:
        parsed = json.loads(text)
    except ValueError:
        logger.warning("%s 不是合法 JSON，費用不估算", PRICE_ENV_KEY)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("%s 必須是物件，費用不估算", PRICE_ENV_KEY)
        return {}
    prices: Dict[str, Dict[str, float]] = {}
    for model, entry in parsed.items():
        price = _valid_price(entry)
        if price is None:
            logger.warning("%s 的 %s 單價不合法，已略過", PRICE_ENV_KEY, model)
            continue
        prices[str(model).strip().lower()] = price
    return prices


def _valid_price(entry: Any) -> Optional[Dict[str, float]]:
    if not isinstance(entry, Mapping):
        return None
    price: Dict[str, float] = {}
    for key in ("input", "output", "cache_read"):
        value = entry.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value) or value < 0:
            return None
        price[key] = float(value)
    if "input" not in price or "output" not in price:
        return None
    return price


def channel_of(provider: Optional[str], transport: Optional[str]) -> str:
    return str(transport or provider or "unknown")


def billing_of(model: Optional[str], channel: Optional[str]) -> str:
    """本機 CLI 走訂閱，token 不計費；其餘算用量計費。"""
    if channel in LOCAL_CLI_GENERATION_BACKEND_IDS or model in LOCAL_CLI_GENERATION_BACKEND_IDS:
        return BILLING_SUBSCRIPTION
    return BILLING_METERED


def _price_for(model: str, prices: Mapping[str, Dict[str, float]]) -> Optional[Dict[str, float]]:
    key = str(model or "").strip().lower()
    # LiteLLM 的模型名帶 provider 前綴（anthropic/xxx），單價表兩種寫法都認。
    return prices.get(key) or prices.get(key.rsplit("/", 1)[-1])


def _cost(row: Mapping[str, Any], price: Mapping[str, float]) -> float:
    cache_read = min(int(row["cache_read_tokens"]), int(row["prompt_tokens"]))
    uncached = int(row["prompt_tokens"]) - cache_read
    # 沒設快取單價就照一般輸入算：寧可高估，不把快取當免費。
    cache_price = price.get("cache_read", price["input"])
    return (
        uncached * price["input"] + cache_read * cache_price + int(row["completion_tokens"]) * price["output"]
    ) / _TOKENS_PER_PRICE_UNIT


def _pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or not previous:
        return None
    return round((current - previous) / previous * 100, 2)


def build_cost(rows: List[Mapping[str, Any]], prices: Mapping[str, Dict[str, float]]) -> Dict[str, Any]:
    """逐模型與管道估算。全部沒有單價時 estimated_total 是 null，不是 0。"""
    by_model: Dict[tuple, Dict[str, Any]] = {}
    for row in rows:
        channel = channel_of(row.get("provider"), row.get("transport"))
        key = (row["model"], channel)
        billing = billing_of(row["model"], channel)
        price = None if billing == BILLING_SUBSCRIPTION else _price_for(row["model"], prices)
        entry = by_model.setdefault(key, {
            "model": row["model"],
            "channel": channel,
            "billing": billing,
            "total_tokens": 0,
            "estimated_cost": None,
        })
        entry["total_tokens"] += int(row["total_tokens"])
        if price is not None:
            entry["estimated_cost"] = (entry["estimated_cost"] or 0.0) + _cost(row, price)

    items = sorted(by_model.values(), key=lambda item: -item["total_tokens"])
    priced = [item["estimated_cost"] for item in items if item["estimated_cost"] is not None]
    unpriced = sorted({
        item["model"] for item in items
        if item["billing"] == BILLING_METERED and item["estimated_cost"] is None
    })
    for item in items:
        if item["estimated_cost"] is not None:
            item["estimated_cost"] = round(item["estimated_cost"], 6)
    return {
        "currency": COST_CURRENCY,
        "estimated_total": round(sum(priced), 6) if priced else None,
        "complete": not unpriced,
        "unpriced_models": unpriced,
        "subscription_tokens": sum(i["total_tokens"] for i in items if i["billing"] == BILLING_SUBSCRIPTION),
        "by_model": items,
    }


def build_analytics(
    rows: List[Mapping[str, Any]],
    prices: Mapping[str, Dict[str, float]],
) -> Dict[str, Any]:
    days: Dict[str, Dict[str, Any]] = {}
    channels: Dict[str, Dict[str, Any]] = {}
    cache_read = 0
    cache_known_prompt = 0
    for row in rows:
        day = days.setdefault(row["day"], {
            "date": row["day"], "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        })
        channel_name = channel_of(row.get("provider"), row.get("transport"))
        channel = channels.setdefault(channel_name, {
            "channel": channel_name,
            "billing": billing_of(row["model"], channel_name),
            "calls": 0,
            "total_tokens": 0,
        })
        for target in (day, channel):
            target["calls"] += int(row["calls"])
            target["total_tokens"] += int(row["total_tokens"])
        day["prompt_tokens"] += int(row["prompt_tokens"])
        day["completion_tokens"] += int(row["completion_tokens"])
        cache_read += int(row["cache_read_tokens"])
        cache_known_prompt += int(row["cache_known_prompt_tokens"])
    return {
        "by_day": [days[key] for key in sorted(days)],
        "by_channel": sorted(channels.values(), key=lambda item: -item["total_tokens"]),
        "cache": {
            "read_tokens": cache_read,
            "known_prompt_tokens": cache_known_prompt,
            "hit_ratio": round(cache_read / cache_known_prompt, 4) if cache_known_prompt else None,
        },
        "cost": build_cost(rows, prices),
    }


def build_previous(
    *,
    from_date: str,
    to_date: str,
    current: Mapping[str, Any],
    current_cost: Optional[float],
    previous_rows: List[Mapping[str, Any]],
    prices: Mapping[str, Dict[str, float]],
) -> Dict[str, Any]:
    calls = sum(int(row["calls"]) for row in previous_rows)
    tokens = sum(int(row["total_tokens"]) for row in previous_rows)
    cost = build_cost(previous_rows, prices)["estimated_total"]
    return {
        "from_date": from_date,
        "to_date": to_date,
        "total_calls": calls,
        "total_tokens": tokens,
        "estimated_cost": cost,
        "calls_change_pct": _pct_change(current.get("total_calls"), calls),
        "tokens_change_pct": _pct_change(current.get("total_tokens"), tokens),
        "cost_change_pct": _pct_change(current_cost, cost),
    }
