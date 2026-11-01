# -*- coding: utf-8 -*-
"""從已落庫的 raw_result／context_snapshot 投影報告決策欄位。

全部讀 LLM 與護欄寫下的結構化鍵，不解析句子。舊報告沒有的鍵回 None，
由客戶端決定怎麼呈現，不補近似值。
"""

from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Any, Dict, List, Mapping, Optional

from src.report_language import localize_confidence_level
from src.schemas.decision_scale import extract_decision_guardrail_reason

DECISION_FIELD_KEYS = (
    "one_sentence",
    "time_sensitivity",
    "position_advice",
    "confidence_level",
    "confidence_reason",
    "guardrail_applied",
    "guardrail_reason",
    "strongest_bullish_signal",
    "strongest_bearish_signal",
    "watch_conditions",
    "entry_conditions",
    "exit_triggers",
    "pending_events",
    "next_check_time",
)


def _mapping(source: Any, key: str) -> Mapping[str, Any]:
    value = source.get(key) if isinstance(source, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _text_list(value: Any) -> Optional[List[str]]:
    """欄位不存在回 None；模型明確給空陣列回 []，兩者語意不同。"""
    if not isinstance(value, (list, tuple)):
        return None
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def extract_report_decision_fields(raw_result: Any, report_language: Optional[str] = None) -> Dict[str, Any]:
    """回傳 DECISION_FIELD_KEYS 與 MODEL_ADVICE_FIELD_KEYS 的值；raw_result 不是 dict 時全為 None。"""
    fields: Dict[str, Any] = {key: None for key in (*DECISION_FIELD_KEYS, *MODEL_ADVICE_FIELD_KEYS)}
    if not isinstance(raw_result, Mapping):
        return fields

    dashboard = _mapping(raw_result, "dashboard")
    core = _mapping(dashboard, "core_conclusion")
    phase = _mapping(dashboard, "phase_decision")
    attribution = _mapping(dashboard, "signal_attribution")
    position = _mapping(core, "position_advice")

    no_position = _text(position.get("no_position"))
    has_position = _text(position.get("has_position"))
    confidence = _text(raw_result.get("confidence_level"))
    guardrail_reason = extract_decision_guardrail_reason(raw_result)

    fields.update(
        one_sentence=_text(core.get("one_sentence")),
        time_sensitivity=_text(core.get("time_sensitivity")),
        position_advice=(
            {"no_position": no_position, "has_position": has_position}
            if no_position or has_position
            else None
        ),
        confidence_level=(
            localize_confidence_level(confidence, report_language) if confidence and report_language else confidence
        ),
        confidence_reason=_text(phase.get("confidence_reason")),
        # 大盤複盤沒有 dashboard：不是「沒套護欄」而是不適用，回 None。
        guardrail_applied=bool(guardrail_reason) if dashboard else None,
        guardrail_reason=guardrail_reason,
        strongest_bullish_signal=_text(attribution.get("strongest_bullish_signal")),
        strongest_bearish_signal=_text(attribution.get("strongest_bearish_signal")),
        watch_conditions=_text_list(phase.get("watch_conditions")),
        entry_conditions=_text_list(phase.get("entry_conditions")),
        exit_triggers=_text_list(phase.get("exit_triggers")),
        pending_events=_text_list(phase.get("pending_events")),
        next_check_time=_text(phase.get("next_check_time")),
    )
    fields.update(_model_advice_fields(core, guardrail_applied=bool(guardrail_reason)))
    return fields


# Keys a guardrail writes into core_conclusion before rewriting the model's wording.
# Kept out of DECISION_FIELD_KEYS so the research artifact thesis contract is unchanged.
MODEL_ADVICE_FIELD_KEYS = ("model_one_sentence", "model_position_advice", "guardrail_kind")
GUARDRAIL_KINDS = ("data_unavailable", "market_logic")


def _model_advice_fields(core: Mapping[str, Any], *, guardrail_applied: bool) -> Dict[str, Any]:
    """Project the preserved model wording; None unless a guardrail was applied."""
    fields: Dict[str, Any] = {key: None for key in MODEL_ADVICE_FIELD_KEYS}
    if not guardrail_applied:
        return fields
    model_position = _mapping(core, "model_position_advice")
    no_position = _text(model_position.get("no_position"))
    has_position = _text(model_position.get("has_position"))
    kind = core.get("guardrail_kind")
    fields.update(
        model_one_sentence=_text(core.get("model_one_sentence")),
        model_position_advice=(
            {"no_position": no_position, "has_position": has_position}
            if no_position or has_position
            else None
        ),
        # Literal in the API schema: anything else must not reach ReportSummary.
        guardrail_kind=kind if kind in GUARDRAIL_KINDS else None,
    )
    return fields


def preserve_model_advice(
    core: Dict[str, Any],
    *,
    guardrail_kind: Optional[str],
    include_position_advice: bool = True,
) -> None:
    """Snapshot the model's one_sentence / position_advice before a guardrail rewrites them.

    First write wins, so re-applied guardrails keep the original model wording;
    guardrail_kind always reflects the latest rewrite.
    """
    original_sentence = core.get("one_sentence")
    if isinstance(original_sentence, str) and original_sentence.strip() and "model_one_sentence" not in core:
        core["model_one_sentence"] = original_sentence
    if include_position_advice and "model_position_advice" not in core:
        position = _mapping(core, "position_advice")
        no_position = position.get("no_position")
        has_position = position.get("has_position")
        if no_position or has_position:
            # Fresh dict: callers mutate position_advice in place right after this.
            core["model_position_advice"] = {"no_position": no_position, "has_position": has_position}
    if guardrail_kind:
        core["guardrail_kind"] = guardrail_kind


def finite_float(value: Any) -> Optional[float]:
    """讀數 0 保留；缺值與非有限值回 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def derive_change_amount(price: Optional[float], change_pct: Optional[float]) -> Optional[float]:
    """由現價與漲跌幅推算漲跌額；平盤回 0.0，缺一個或無法反推回 None。"""
    if price is None or change_pct is None:
        return None
    base = 1 + change_pct / 100
    if base <= 0:
        return None
    return round(price - price / base, 4)


def extract_report_price_fields(
    context_snapshot: Any,
    raw_result: Any,
    *,
    current_price: Any = None,
    change_pct: Any = None,
) -> Dict[str, Any]:
    """現價優先用既有即時欄位，缺時退到 dashboard；資料日取分析上下文的報價場次。

    `enhanced_context.today.date` 是報價所屬場次（見 src/AGENTS.md），線上 1104 筆個股
    報告有 1103 筆帶它；`fetched_at` 是抓取時間，不能當資料日，另外給。
    """
    price = finite_float(current_price)
    if price is None:
        perspective = _mapping(_mapping(raw_result, "dashboard"), "data_perspective")
        price = finite_float(_mapping(perspective, "price_position").get("current_price"))

    enhanced = _mapping(context_snapshot, "enhanced_context")
    realtime = _mapping(enhanced, "realtime")
    price_date = _iso_date(_mapping(enhanced, "today").get("date")) or _iso_date(enhanced.get("date"))
    return {
        "current_price": price,
        "change_amount": derive_change_amount(price, finite_float(change_pct)),
        "price_date": price_date,
        "price_fetched_at": _text(realtime.get("fetched_at")),
    }


def _iso_date(value: Any) -> Optional[str]:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def extract_one_sentence(raw_result: Any) -> Optional[str]:
    """列表用，只取一句話結論。線上大盤複盤 0/202 有這個鍵，回 None 是預期。"""
    return _text(_mapping(_mapping(raw_result, "dashboard"), "core_conclusion").get("one_sentence"))
