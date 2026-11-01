# -*- coding: utf-8 -*-
"""Decision action taxonomy helpers for Issue #1390 P0.

This module is deliberately separate from ``src.agent.protocols``:
``DecisionAction`` is the new eight-state display taxonomy, while
``decision_type`` remains the existing buy/hold/sell statistics contract.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional, TypedDict, get_args

from src.report_language import localize_operation_advice, normalize_report_language
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
    # zh-TW 依 docs/glossary-zh-tw.md；舊報告存的買入、減倉、預警等由 zh 欄折疊後解析。
    "buy": {"zh": "买入", "zh-TW": "買進", "en": "Buy", "ko": "매수"},
    "add": {"zh": "加仓", "zh-TW": "加碼", "en": "Add", "ko": "추가 매수"},
    "hold": {"zh": "持有", "zh-TW": "續抱", "en": "Hold", "ko": "보유"},
    "reduce": {"zh": "减仓", "zh-TW": "減碼", "en": "Reduce", "ko": "비중축소"},
    "sell": {"zh": "卖出", "zh-TW": "賣出", "en": "Sell", "ko": "매도"},
    "watch": {"zh": "观望", "zh-TW": "觀望", "en": "Watch", "ko": "관망"},
    "avoid": {"zh": "回避", "zh-TW": "迴避", "en": "Avoid", "ko": "회피"},
    "alert": {"zh": "预警", "zh-TW": "警報", "en": "Alert", "ko": "경고"},
}

_EXPLICIT_ALIASES: Dict[str, DecisionAction] = {
    "strong buy": "buy",
    "accumulate": "add",
    "trim": "reduce",
    "strong sell": "sell",
    "wait": "watch",
}

# 自由文字的 operation_advice 只供顯示：動作必須由 LLM／agent 在結構化 `action` 欄位給出。
# 結構化欄位缺席時，只接受「整段就是一個動作標籤」的建議（去頭尾空白後完全相等），
# 不做片語、否定或子字串判讀——「不建議現在買入」這類句子一律回 None，交給呼叫端既有預設。
# 標籤來源只有既有列舉：八態動作的各語系顯示標籤，與 operation_advice 列舉的強烈買入／賣出。
_EXTRA_EXACT_LABELS: Dict[str, DecisionAction] = {
    "强烈买入": "buy",
    "强烈买进": "buy",
    "적극 매수": "buy",
    "强烈卖出": "sell",
    "적극 매도": "sell",
    # 台灣用語的加碼／減碼是加倉／減倉的同義標籤
    "加码": "add",
    "减码": "reduce",
}


def _normalize_key(value: Any) -> str:
    # 繁體標籤（「觀望」「減倉」）先逐字折成簡體再查表，否則 zh-TW 報告的標籤會落空。
    text = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    return fold_traditional(" ".join(text.split()))


def _build_exact_label_table() -> Dict[str, DecisionAction]:
    table: Dict[str, DecisionAction] = {}
    for action, labels in _ACTION_LABELS.items():
        for label in labels.values():
            table[_normalize_key(label)] = action  # type: ignore[assignment]
    for label, action in _EXTRA_EXACT_LABELS.items():
        table[_normalize_key(label)] = action
    return table


_EXACT_LABEL_ACTIONS: Dict[str, DecisionAction] = _build_exact_label_table()


def _explicit_action(value: Any) -> Optional[DecisionAction]:
    normalized = _normalize_key(value)
    if not normalized:
        return None
    if normalized in _ACTION_VALUES:
        return normalized  # type: ignore[return-value]
    return _EXPLICIT_ALIASES.get(normalized)


def normalize_decision_action(value: Any) -> Optional[DecisionAction]:
    """Return the eight-state action for an enum value or an exact action label.

    Free-text advice (sentences, negations, mixed wording) is display-only and
    returns ``None``; callers fall back to their existing defaults.
    """

    explicit = _explicit_action(value)
    if explicit:
        return explicit
    return _EXACT_LABEL_ACTIONS.get(_normalize_key(value))


def decision_type_for_action(value: Any, default: str = "hold") -> str:
    """將結構化八態動作（或完整標籤）投影到三態 decision_type；未知時回 default。"""
    action = normalize_decision_action(value)
    if action in {"buy", "add"}:
        return "buy"
    if action in {"reduce", "sell"}:
        return "sell"
    return "hold" if action is not None else default


def localize_action_label(action: Any, language: Optional[str] = "zh") -> Optional[str]:
    """Return a localized display label for a decision action."""

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
