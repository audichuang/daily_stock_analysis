# -*- coding: utf-8 -*-
"""Helpers for parsing report sniper-point price values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Dict, Optional


SNIPER_KEYS = ("ideal_buy", "secondary_buy", "stop_loss", "take_profit")

# 可選的欄位標籤（「理想買入點：」）之後，開頭就寫明沒有價位才算；句中的「跌破…暫不進場」「暫不建議追高，回測X元再買」不算
_END = r"(?:[。；;，,（(]|$)"
_NOT_SET_RE = re.compile(
    r"^\s*(?:[^：:\d]{0,10}[：:])?\s*(?:目前|現在|现在|現階段|现阶段)?\s*(?:"
    r"[暫暂]?不(?:設定|设定|設置|设置|設|设|給|给|提供|[買买]|進場|进场|入場|入场)"
    r"|[暫暂]?不(?:建議|建议)(?:[買买進进入]|做多|" + _END + r")"
    r"|[暫暂]不(?:適用|适用|成立)"
    r"|[無无](?:理想|" + _END + r")"
    r"|N/A)",
    re.IGNORECASE,
)
# 冒號後第一個價位緊接「進場／買進／成交」（如「如果在1909元進場」）才是條件式進場句，此時改取欄位錨點後的價位
_ENTRY_AFTER_RE = re.compile(r"[^，,。；;]{0,6}?(?:進場|进场|買進|买进|買入|买入|成交|承接)")
# 欄位專屬錨點：只有 stop_loss／take_profit 會走錨點路徑
_VERB = r"(?:於|于|設在|设在|設定在|设定在|設定為|设定为|設|设|在)"
_FIELD_ANCHOR_RE = {
    "stop_loss": re.compile(r"(?:停損|止損|止损)(?:價|价|位)?" + _VERB),
    "take_profit": re.compile(r"(?:停利|停盈|止盈|目標價|目标价)(?:位)?" + _VERB + "?"),
}
_PRICE_RE = re.compile(r"[^\d\-]{0,6}(\d+(?:\.\d+)?)\s*元")


def parse_sniper_value(value: Any, field: Optional[str] = None) -> Optional[float]:
    """Parse a sniper point value from report text into a positive price.

    ``field`` (one of SNIPER_KEYS) enables the field-specific anchor path.
    """

    if value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if parsed > 0 else None

    text = str(value).replace(",", "").replace("，", "").strip()
    if not text or text in {"-", "—", "N/A"}:
        return None

    try:
        parsed = float(text)
        return parsed if parsed > 0 else None
    except ValueError:
        pass

    if _NOT_SET_RE.search(text):
        return None

    # 條件式進場句才取該欄位自己的第一個錨點（買點欄位不走這條）
    anchor_re = _FIELD_ANCHOR_RE.get(field or "")
    if anchor_re:
        first_colon = min((i for i in (text.find("："), text.find(":")) if i != -1), default=-1)
        lead_yuan = text.find("元", first_colon + 1)
        if lead_yuan != -1 and _ENTRY_AFTER_RE.match(text, lead_yuan + 1):
            for anchor in anchor_re.finditer(text, lead_yuan):
                m = _PRICE_RE.match(text, anchor.end())
                if m:
                    parsed = float(m.group(1))
                    return parsed if parsed > 0 else None

    colon_pos = max(text.rfind("："), text.rfind(":"))
    yuan_pos = text.find("元", colon_pos + 1 if colon_pos != -1 else 0)
    if yuan_pos != -1:
        segment_start = colon_pos + 1 if colon_pos != -1 else 0
        segment = text[segment_start:yuan_pos]
        valid_numbers = []
        for match in re.finditer(r"-?\d+(?:\.\d+)?", segment):
            start_idx = match.start()
            if start_idx >= 2 and segment[start_idx - 2:start_idx].upper() == "MA":
                continue
            valid_numbers.append(match.group())
        if valid_numbers:
            try:
                parsed = abs(float(valid_numbers[-1]))
                return parsed if parsed > 0 else None
            except ValueError:
                pass

    paren_pos = len(text)
    for paren_char in ("(", "（"):
        pos = text.find(paren_char)
        if pos != -1:
            paren_pos = min(paren_pos, pos)
    search_text = text[:paren_pos].strip() or text

    valid_numbers = []
    for match in re.finditer(r"\d+(?:\.\d+)?", search_text):
        start_idx = match.start()
        if start_idx >= 2 and search_text[start_idx - 2:start_idx].upper() == "MA":
            continue
        valid_numbers.append(match.group())
    if valid_numbers:
        try:
            parsed = float(valid_numbers[-1])
            return parsed if parsed > 0 else None
        except ValueError:
            pass
    return None


def extract_sniper_points(result: Any) -> Dict[str, Optional[float]]:
    """Extract normalized sniper-point prices from a completed analysis result."""

    raw_points: Mapping[str, Any] = {}

    if hasattr(result, "get_sniper_points"):
        candidate = result.get_sniper_points() or {}
        if isinstance(candidate, Mapping):
            raw_points = candidate

    if not _has_any_sniper_value(raw_points):
        dashboard = getattr(result, "dashboard", None)
        if isinstance(dashboard, Mapping):
            raw_points = find_sniper_points(dashboard) or raw_points

    if not _has_any_sniper_value(raw_points):
        raw_response = getattr(result, "raw_response", None)
        if isinstance(raw_response, Mapping):
            raw_points = find_sniper_points(raw_response) or raw_points

    return {key: parse_sniper_value(raw_points.get(key), key) for key in SNIPER_KEYS}


def _has_any_sniper_value(points: Mapping[str, Any]) -> bool:
    return any(points.get(key) not in (None, "") for key in SNIPER_KEYS)


def find_sniper_points(data: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    if not isinstance(data, Mapping):
        return None

    if any(key in data for key in SNIPER_KEYS):
        return data

    sniper_points = data.get("sniper_points")
    if isinstance(sniper_points, Mapping) and sniper_points:
        return sniper_points

    battle_plan = data.get("battle_plan")
    if isinstance(battle_plan, Mapping):
        sniper_points = battle_plan.get("sniper_points")
        if isinstance(sniper_points, Mapping) and sniper_points:
            return sniper_points

    inner_dashboard = data.get("dashboard")
    if isinstance(inner_dashboard, Mapping):
        found = find_sniper_points(inner_dashboard)
        if found:
            return found

    return None
