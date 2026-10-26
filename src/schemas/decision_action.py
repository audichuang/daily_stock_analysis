# -*- coding: utf-8 -*-
"""Decision action taxonomy helpers for Issue #1390 P0.

This module is deliberately separate from ``src.agent.protocols``:
``DecisionAction`` is the new eight-state display taxonomy, while
``decision_type`` remains the existing buy/hold/sell statistics contract.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional, TypedDict, get_args

from src.schemas.decision_scale import (
    action_for_score,
    extract_decision_guardrail_reason,
    score_action_conflicts_without_guardrail,
)
from src.utils.zh_fold import fold_traditional

DecisionAction = Literal["buy", "add", "hold", "reduce", "sell", "watch", "avoid", "alert"]


class DecisionActionFields(TypedDict):
    action: Optional[DecisionAction]
    action_label: Optional[str]


_ACTION_VALUES = set(get_args(DecisionAction))
_NON_STOCK_REPORT_TYPES = {"market_review"}

_ACTION_LABELS: Dict[str, Dict[str, str]] = {
    "buy": {"zh": "买入", "zh-TW": "買入", "en": "Buy", "ko": "매수"},
    "add": {"zh": "加仓", "zh-TW": "加倉", "en": "Add", "ko": "추가 매수"},
    "hold": {"zh": "持有", "zh-TW": "持有", "en": "Hold", "ko": "보유"},
    "reduce": {"zh": "减仓", "zh-TW": "減倉", "en": "Reduce", "ko": "비중축소"},
    "sell": {"zh": "卖出", "zh-TW": "賣出", "en": "Sell", "ko": "매도"},
    "watch": {"zh": "观望", "zh-TW": "觀望", "en": "Watch", "ko": "관망"},
    "avoid": {"zh": "回避", "zh-TW": "回避", "en": "Avoid", "ko": "회피"},
    "alert": {"zh": "预警", "zh-TW": "預警", "en": "Alert", "ko": "경고"},
}

# 僅比對完整列舉標籤；不從建議句子抽取動作或解讀否定。
_EXPLICIT_ALIASES: Dict[str, DecisionAction] = {
    "strong buy": "buy",
    "strong_buy": "buy",
    "accumulate": "add",
    "加码": "add",
    "trim": "reduce",
    "strong sell": "sell",
    "strong_sell": "sell",
    "wait": "watch",
}


def _normalize_key(value: Any) -> str:
    return fold_traditional(str(value or "").strip().lower())


_EXACT_ACTION_LABELS: Dict[str, DecisionAction] = {
    _normalize_key(label): action
    for action, labels in _ACTION_LABELS.items()
    for label in labels.values()
}


def _explicit_action(value: Any) -> Optional[DecisionAction]:
    normalized = _normalize_key(value)
    if normalized in _ACTION_VALUES:
        return normalized  # type: ignore[return-value]
    return _EXPLICIT_ALIASES.get(normalized) or _EXACT_ACTION_LABELS.get(normalized)


def normalize_decision_action(value: Any) -> Optional[DecisionAction]:
    """只接受完整動作列舉或單一標籤；自由文字回傳 None。"""
    return _explicit_action(value)


def decision_type_for_action(value: Any, default: str = "hold") -> str:
    """將結構化八態動作投影到既有三態統計欄位。"""
    action = normalize_decision_action(value)
    if action in {"buy", "add"}:
        return "buy"
    if action in {"reduce", "sell"}:
        return "sell"
    return "hold" if action is not None else default


def localize_action_label(action: Any, language: Optional[str] = "zh") -> Optional[str]:
    """Return a localized display label for a decision action."""

    from src.report_language import normalize_report_language

    normalized = _explicit_action(action)
    if not normalized:
        return None
    return _ACTION_LABELS[normalized][normalize_report_language(language)]


def build_action_fields(
    *,
    operation_advice: Any = None,
    explicit_action: Any = None,
    report_type: Any = None,
    report_language: Optional[str] = "zh",
    sentiment_score: Any = None,
    guardrail_reason: Any = None,
    align_with_score: bool = False,
) -> DecisionActionFields:
    """Build optional public action fields without mutating legacy contracts."""

    if str(report_type or "").strip().lower() in _NON_STOCK_REPORT_TYPES:
        return {"action": None, "action_label": None}

    action = normalize_decision_action(explicit_action)
    if action is None:
        advice_text = str(operation_advice or "").strip()
        if advice_text:
            action = normalize_decision_action(advice_text)

    if align_with_score and score_action_conflicts_without_guardrail(
        score=sentiment_score,
        action=action,
        guardrail_reason=guardrail_reason,
    ):
        score_action = action_for_score(sentiment_score)
        if score_action in _ACTION_VALUES:
            action = score_action  # type: ignore[assignment]

    return {
        "action": action,
        "action_label": localize_action_label(action, report_language) if action else None,
    }


def _result_guardrail_reason(result: Any) -> Optional[str]:
    return extract_decision_guardrail_reason(
        {
            "guardrail_reason": getattr(result, "guardrail_reason", None),
            "downgrade_reason": getattr(result, "downgrade_reason", None),
            "dashboard": getattr(result, "dashboard", None),
            "metadata": getattr(result, "metadata", None),
        }
    )


def display_action_fields(
    *,
    operation_advice: Any = None,
    explicit_action: Any = None,
    action_label: Any = None,
    report_type: Any = None,
    report_language: Optional[str] = "zh",
    sentiment_score: Any = None,
    guardrail_reason: Any = None,
) -> DecisionActionFields:
    """Resolve one canonical action for every public display surface."""

    action_source = explicit_action
    if normalize_decision_action(action_source) is None and str(action_label or "").strip():
        action_source = action_label
    return build_action_fields(
        operation_advice=operation_advice,
        explicit_action=action_source,
        report_type=report_type,
        report_language=report_language,
        sentiment_score=sentiment_score,
        guardrail_reason=guardrail_reason,
        align_with_score=True,
    )


def _display_result_kwargs(
    result: Any,
    *,
    report_language: Optional[str] = None,
    report_type: Any = None,
) -> dict[str, Any]:
    return {
        "operation_advice": getattr(result, "operation_advice", None),
        "explicit_action": getattr(result, "action", None),
        "action_label": getattr(result, "action_label", None),
        "report_type": report_type or getattr(result, "report_type", None),
        "report_language": report_language or getattr(result, "report_language", "zh"),
        "sentiment_score": getattr(result, "sentiment_score", None),
        "guardrail_reason": _result_guardrail_reason(result),
    }


def display_action_fields_for_result(
    result: Any,
    *,
    report_language: Optional[str] = None,
    report_type: Any = None,
) -> DecisionActionFields:
    return display_action_fields(
        **_display_result_kwargs(result, report_language=report_language, report_type=report_type)
    )


def display_operation_advice_for_result(
    result: Any,
    *,
    report_language: Optional[str] = None,
    report_type: Any = None,
) -> str:
    """Return the same localized action label used by Web/API display fields."""

    from src.report_language import localize_operation_advice

    fields = display_action_fields_for_result(
        result,
        report_language=report_language,
        report_type=report_type,
    )
    if fields["action_label"]:
        return fields["action_label"]
    language = report_language or getattr(result, "report_language", "zh")
    return localize_operation_advice(getattr(result, "operation_advice", None), language)


def display_decision_type_for_result(
    result: Any,
    *,
    report_language: Optional[str] = None,
    report_type: Any = None,
) -> str:
    """Map the displayed eight-state action to the legacy three summary buckets."""

    action = display_action_fields_for_result(
        result,
        report_language=report_language,
        report_type=report_type,
    )["action"]
    if action in {"buy", "add"}:
        return "buy"
    if action in {"reduce", "sell"}:
        return "sell"
    if action is not None:
        return "hold"
    legacy = str(getattr(result, "decision_type", "") or "").strip().lower()
    if legacy in {"buy", "hold", "sell"}:
        return legacy
    return "hold"
