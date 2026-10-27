# -*- coding: utf-8 -*-
"""Decision guardrail using daily market context for Issue #1381."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, List

from src.schemas.decision_action import decision_type_for_action
from src.schemas.decision_scale import action_for_score, record_guardrail_score_adjustment
from src.report_language import (
    infer_decision_type_from_advice,
    localize_confidence_level,
    localize_operation_advice,
    normalize_report_language,
)


# 只認「真的有風險」的訊號（高風險／退潮／明確倉位上限）。「謹慎」「觀望」這類
# 中性措辭不再觸發：yellow 日幾乎天天出現，會讓護欄在創新高日也把買進壓成觀望。
_CONSERVATIVE_TAGS = {"high_risk", "market_cooling", "low_position_cap"}
_CONSERVATIVE_TEXT_MARKERS_ZH = (
    "退潮",
    "高风险",
    "风险偏高",
    "高風險",
    "風險偏高",
    "仓位上限",
    "仓位不超过",
    "轻仓",
    "倉位上限",
    "倉位不超過",
    "輕倉",
)
_CONSERVATIVE_TEXT_MARKERS_EN = ("high risk", "elevated risk", "risk-off", "risk off", "cooling", "position cap", "position limit")
_CONSERVATIVE_TEXT_MARKERS_KO = ("고위험", "비중 상한", "비중 축소", "경량")
_GUARDRAIL_SENTIMENT_SCORE = 52


def _softened_operation_advice(language: str) -> str:
    return localize_operation_advice("观望", language)


def apply_daily_market_context_guardrail(
    result: Any,
    *,
    daily_market_context: Any,
    report_language: str = "zh",
) -> List[str]:
    """Soften aggressive buy advice when daily market context is conservative."""

    if result is None or not _is_conservative_context(daily_market_context):
        return []

    language = normalize_report_language(report_language or getattr(result, "report_language", "zh"))
    if not _is_buy_decision(result):
        return []

    adjustments: List[str] = []
    # 護欄前的原始分數／動作：落庫給 scripts/shadow_buy_eval.py 回推 LLM 原判
    raw_score = getattr(result, "sentiment_score", None)
    raw_decision_type = str(getattr(result, "decision_type", "") or "").lower() or None
    result.decision_type = "hold"
    adjustments.append("daily_market_context_buy_softened")

    softened_advice = _softened_operation_advice(language)
    result.operation_advice = softened_advice

    if _is_high_confidence(getattr(result, "confidence_level", "")):
        result.confidence_level = localize_confidence_level("medium", language)
        adjustments.append("confidence_capped_daily_market_context")

    result.sentiment_score = _cap_conservative_sentiment_score(
        getattr(result, "sentiment_score", 0)
    )
    # 將舊動作改成觀望，避免原分數提升的買入動作殘留。
    result.action = "watch"
    result.action_label = None

    dashboard = getattr(result, "dashboard", None)
    if not isinstance(dashboard, dict):
        dashboard = {}
        result.dashboard = dashboard

    _sync_softened_dashboard_fields(
        dashboard,
        softened_advice=softened_advice,
        language=language,
    )
    record_guardrail_score_adjustment(
        dashboard,
        raw_score=raw_score,
        adjusted_score=result.sentiment_score,
        final_action="hold",
        reason=_softening_reason(language),
        raw_decision_type=raw_decision_type,
    )

    phase_decision = dashboard.get("phase_decision")
    if not isinstance(phase_decision, dict):
        phase_decision = {}
        dashboard["phase_decision"] = phase_decision
    _append_softening_limitation(phase_decision, language=language)

    return adjustments


def _sync_softened_dashboard_fields(
    dashboard: dict[str, Any],
    *,
    softened_advice: str,
    language: str,
) -> None:
    dashboard["sentiment_score"] = _cap_conservative_sentiment_score(
        dashboard.get("sentiment_score", _GUARDRAIL_SENTIMENT_SCORE)
    )
    dashboard["operation_advice"] = softened_advice
    dashboard["decision_type"] = "hold"

    core = dashboard.get("core_conclusion")
    if isinstance(core, dict):
        core["one_sentence"] = softened_advice
        core["position_advice"] = _softened_position_advice(language)

    battle_plan = dashboard.get("battle_plan")
    if isinstance(battle_plan, dict):
        battle_plan["position_strategy"] = _softened_position_strategy(language)


def _softened_position_advice(language: str) -> dict[str, str]:
    if language == "en":
        return {
            "no_position": "Do not open a new position until market risk eases or confirmation appears.",
            "has_position": "Hold only a small position; do not increase exposure, and reduce if risk controls break.",
        }
    if language == "ko":
        return {
            "no_position": "시장 위험이 완화되거나 확인 신호가 나오기 전까지 신규 진입하지 마세요.",
            "has_position": "소량만 보유하고 비중을 늘리지 마세요. 리스크 관리선이 무너지면 비중을 줄이세요.",
        }
    return {
        "no_position": "大盘环境偏谨慎，暂不开新仓，等待风险缓解或确认信号。",
        "has_position": "仅保留小仓观察，暂不扩大仓位；若跌破风控位优先降低仓位。",
    }


def _softened_position_strategy(language: str) -> dict[str, str]:
    position_advice = _softened_position_advice(language)
    if language == "en":
        return {
            "suggested_position": "Small/defensive position",
            "entry_plan": position_advice["no_position"],
            "risk_control": "Do not increase exposure before market risk eases; control drawdown strictly.",
        }
    if language == "ko":
        return {
            "suggested_position": "소량/방어적 비중",
            "entry_plan": position_advice["no_position"],
            "risk_control": "시장 위험이 완화되기 전까지 비중을 늘리지 말고 낙폭을 엄격히 관리하세요.",
        }
    return {
        "suggested_position": "小仓/低仓位",
        "entry_plan": position_advice["no_position"],
        "risk_control": "大盘风险未缓解前不扩大仓位，严格控制回撤。",
    }


def _softening_reason(language: str) -> str:
    if language == "en":
        return "Daily market context is conservative/high risk; aggressive buy advice was softened."
    if language == "ko":
        return "대시장 환경이 보수적/고위험이라 공격적 매수 권고를 완화했습니다."
    return "大盘环境偏谨慎/高风险，已软化激进买入建议。"


def _append_softening_limitation(phase_decision: dict[str, Any], *, language: str) -> None:
    limitations = phase_decision.get("data_limitations")
    if not isinstance(limitations, list):
        limitations = []
    limitation = _softening_reason(language)
    if limitation not in limitations:
        limitations.append(limitation)
    phase_decision["data_limitations"] = limitations
    reason = str(phase_decision.get("confidence_reason") or "").strip()
    if language == "en":
        reason_note = "Market context requires conservative sizing."
    elif language == "ko":
        reason_note = "시장 환경상 보수적인 비중 관리가 필요합니다."
    else:
        reason_note = "大盘环境要求降低进攻性并控制仓位。"
    separator = "; " if language == "en" else "；"
    phase_decision["confidence_reason"] = (
        f"{reason}{separator}{reason_note}" if reason else reason_note
    )


def _is_conservative_context(context: Any) -> bool:
    if not isinstance(context, Mapping):
        return False
    tags = context.get("risk_tags")
    if isinstance(tags, list) and any(str(tag) in _CONSERVATIVE_TAGS for tag in tags):
        return True
    if str(context.get("position_cap") or "").strip():
        return True
    summary = str(context.get("summary") or "")
    lowered = summary.lower()
    return (
        any(marker in summary for marker in _CONSERVATIVE_TEXT_MARKERS_ZH)
        or any(marker in summary for marker in _CONSERVATIVE_TEXT_MARKERS_KO)
        or any(marker in lowered for marker in _CONSERVATIVE_TEXT_MARKERS_EN)
    )



def _is_buy_decision(result: Any) -> bool:
    """優先使用結構化三態，缺漏時讀 action／完整標籤，並保留既有分數護欄。"""
    decision_type = str(getattr(result, "decision_type", "") or "").strip().lower()
    if decision_type not in {"buy", "hold", "sell"}:
        # 合法三態優先於 action，避免先前的分數對齊把明確持有當成買入。
        decision_type = decision_type_for_action(
            getattr(result, "action", None), default="",
        ) or infer_decision_type_from_advice(getattr(result, "operation_advice", ""), default="")
    if decision_type == "buy":
        return True
    # hold＋買入區分數（≥60）：不壓分、不留 guardrail_reason 的話，下游 build_action_fields
    # 的分數對齊會把 hold/watch 升回 buy，高風險日照樣發出買入；分數區間沿用 canonical 口徑。
    # sell 不走這條：對齊不會把賣出升成買入，觸發反而把賣出改成觀望
    return decision_type == "hold" and action_for_score(getattr(result, "sentiment_score", None)) == "buy"


def _cap_conservative_sentiment_score(value: Any) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        return _GUARDRAIL_SENTIMENT_SCORE
    return min(_GUARDRAIL_SENTIMENT_SCORE, max(0, score))


def _is_high_confidence(value: Any) -> bool:
    return str(value or "").strip().lower() in {"高", "high", "높음"}
