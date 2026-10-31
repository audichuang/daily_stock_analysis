# -*- coding: utf-8 -*-
"""警報推播的 Markdown 版型（純函式）；TelegramSender 會轉成 Telegram 格式，其他渠道照樣看得懂。"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

QUOTE_SOURCE_LABELS = {
    "shioaji": "永豐即時（Shioaji）",
    "yfinance": "yfinance（可能延遲）",
    "fallback": "備援來源（可能延遲）",
}


def quote_source_from_result(result: Dict[str, Any]) -> Optional[str]:
    """從評估結果的 diagnostics 取實際報價來源；非即時價規則沒有這個欄位。"""
    diagnostics = result.get("diagnostics")
    if isinstance(diagnostics, str):
        try:
            diagnostics = json.loads(diagnostics)
        except (TypeError, ValueError):
            return None
    if not isinstance(diagnostics, dict):
        return None
    source = diagnostics.get("quote_source")
    return str(source) if source else None


def quote_source_line(quote_source: Optional[str], data_source: Optional[str] = None) -> Optional[str]:
    """通知裡的來源行。Shioaji 缺金鑰會靜默退回 yfinance，不寫出來收件人分不出報價可不可靠。"""
    if quote_source:
        return f"報價來源：{QUOTE_SOURCE_LABELS.get(quote_source, quote_source)}"
    if data_source == "realtime_quote":
        return "報價來源：未知"
    if data_source == "daily_data":
        return "資料來源：日線資料"
    if data_source == "market_light":
        return "資料來源：大盤紅綠燈"
    return f"資料來源：{data_source}" if data_source else None


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _headline_and_detail(target: str, rule: Any, result: Dict[str, Any]) -> tuple[str, Optional[str]]:
    alert_type = str(getattr(getattr(rule, "alert_type", None), "value", getattr(rule, "alert_type", "")) or "")
    direction = str(getattr(rule, "direction", "") or "").lower()
    observed = _number(result.get("observed_value"))
    threshold = _number(result.get("threshold"))

    if alert_type == "price_cross" and observed is not None and threshold:
        verb, icon = ("站上", "🔺") if direction == "above" else ("跌破", "🔻")
        diff = (observed / threshold - 1) * 100
        return (
            f"{icon} {target} {verb} {_price(threshold)}",
            f"現價 **{_price(observed)}**（觸發價 {_price(threshold)}，{diff:+.1f}%）",
        )
    if alert_type == "price_change_percent" and observed is not None and threshold is not None:
        verb, icon = ("漲幅達", "🔺") if direction == "up" else ("跌幅達", "🔻")
        return f"{icon} {target} {verb} {threshold:g}%", f"今日漲跌 **{observed:+.2f}%**"
    return f"🔔 {target} 警報", None


def format_generic_alert_markdown(
    *,
    target: str,
    rule: Any,
    result: Dict[str, Any],
    quote_source: Optional[str] = None,
    excerpts: Iterable[Optional[str]] = (),
) -> str:
    headline, detail = _headline_and_detail(target, rule, result)
    lines: List[str] = [f"**{headline}**", ""]
    if detail:
        lines.append(detail)
    else:
        reason = result.get("reason") or result.get("message") or getattr(rule, "description", "") or "條件已觸發"
        lines.append(str(reason))
    source_line = quote_source_line(quote_source, result.get("data_source"))
    if source_line:
        lines.append(f"- {source_line}")
    timestamp = result.get("data_timestamp")
    if timestamp:
        text = timestamp.strftime("%Y-%m-%d %H:%M") if hasattr(timestamp, "strftime") else str(timestamp)
        lines.append(f"- 資料時間：{text}")
    for excerpt in excerpts:
        if excerpt:
            lines.extend(["", str(excerpt)])
    return "\n".join(lines)
