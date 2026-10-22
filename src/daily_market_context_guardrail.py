# -*- coding: utf-8 -*-
"""Decision guardrail using daily market context for Issue #1381."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, List

from src.schemas.decision_scale import record_guardrail_score_adjustment
from src.report_language import (
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
_AGGRESSIVE_BUY_MARKERS_ZH = (
    "立即买入",
    "马上买入",
    "建议买入",
    "分批买入",
    "分批低吸",
    "回踩买入",
    "积极买入",
    "激进买入",
    "追高",
    "加仓",
    # 繁體（zh-TW 報告）
    "立即買入",
    "馬上買入",
    "建議買入",
    "分批買入",
    "回踩買入",
    "積極買入",
    "激進買入",
    "加倉",
)
_AGGRESSIVE_BUY_MARKERS_EN = ("buy now", "strong buy", "aggressive buy", "chase", "add aggressively")
_AGGRESSIVE_BUY_MARKERS_KO = (
    "즉시 매수",
    "지금 매수",
    "매수 추천",
    "분할 매수",
    "적극 매수",
    "공격적 매수",
    "추격 매수",
    "비중 확대",
)
_NEGATION_HINTS_ZH = (
    "暂不",
    "不建议",
    "不应",
    "不宜",
    "不能",
    "无法",
    "不允许",
    "禁止",
    "避免",
    "不要",
    "别",
    "先不",
    # 繁體：補了繁體買進詞就必須補否定詞，否則「暫不建議買入」會被誤判成激進買進
    "暫不",
    "不建議",
    "不應",
    "無法",
    "不允許",
    "別",
    # 「持有，不需要加倉」這類整句：否定詞不緊貼買進詞，緊貼單字規則看不到，要整詞列出（繁簡並列）。
    # 只收帶否定字的整詞，不收裸的「需要／必要／考慮」，否則「需要加倉」會逃過護欄
    "不需要",
    "不需",
    "无需",
    "無需",
    "毋须",
    "毋須",
    "不必",
    "不用",
    "不考虑",
    "不考慮",
    "没必要",
    "沒必要",
    "不适合",
    "不適合",
    "不急于",
    "不急於",
    "不再",
)
_NEGATION_HINTS_EN = (" not ", "do not", "don't", "no ", "never", "avoid")
_NEGATION_HINTS_KO = ("권하지 않", "하지 않", "하지 마", "불가", "금지", "피하", "보류", "않", "말")
_NEGATION_LOOKBACK = 16
# 否定詞與買進詞共用字時（「不建議買入」的「建議買入」、「不加倉」），回看窗只剩一個「不」，上面的詞表對不到；
# 只認緊貼在買進詞前面的單字，避免「股價不貴，建議買入」這類句子被當成否定
_NEGATION_IMMEDIATE_ZH = ("不", "勿", "没", "沒", "未")
# 雙重否定與反問：「不得不加倉」「沒有理由不加倉」「何不加倉」是要買，緊貼的「不」不算否定
_DOUBLE_NEGATION_ZH = ("不得", "没有理由", "沒有理由", "无", "無", "非")
# 「何不加倉」是反問（要買），但「無論如何不／不管如何不／為何不」是明確否定，所以「何」只認不接在這些字後面時
_RHETORICAL_HE_EXCLUDED = ("如", "為", "为", "論", "论", "管")
_CHASE_MARKERS = ("追高", "chase")
# 含「別／别」但不是否定的詞：「特別建議買入」不能因為「別」就逃過護欄
_NEGATION_FALSE_COMPOUNDS_ZH = (
    "特別", "特别", "區別", "区别", "個別", "个别", "分別", "分别", "類別", "类别", "級別", "级别", "差別", "差别",
    "識別", "识别",
)
_GUARDRAIL_SENTIMENT_SCORE = 52


def _softened_operation_advice(language: str) -> str:
    return localize_operation_advice("观望", language)


def _negation_hints_for(language: str) -> tuple[str, ...]:
    if language == "en":
        return _NEGATION_HINTS_EN
    if language == "ko":
        return _NEGATION_HINTS_KO
    return _NEGATION_HINTS_ZH


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
    if not _has_aggressive_buy_signal(result, language=language):
        return []

    adjustments: List[str] = []
    # 護欄前的原始分數／動作：落庫給 scripts/shadow_buy_eval.py 回推 LLM 原判
    raw_score = getattr(result, "sentiment_score", None)
    raw_decision_type = str(getattr(result, "decision_type", "") or "").lower() or None
    if str(getattr(result, "decision_type", "") or "").lower() == "buy":
        result.decision_type = "hold"
        adjustments.append("daily_market_context_buy_softened")
    elif _contains_any(str(getattr(result, "operation_advice", "") or ""), _buy_markers(language)):
        adjustments.append("daily_market_context_buy_softened")

    softened_advice = _softened_operation_advice(language)
    result.operation_advice = softened_advice

    if _is_high_confidence(getattr(result, "confidence_level", "")):
        result.confidence_level = localize_confidence_level("medium", language)
        adjustments.append("confidence_capped_daily_market_context")

    result.sentiment_score = _cap_conservative_sentiment_score(
        getattr(result, "sentiment_score", 0)
    )

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


def _has_aggressive_buy_signal(result: Any, *, language: str) -> bool:
    decision_type = str(getattr(result, "decision_type", "") or "").lower()
    if decision_type == "buy":
        advice = str(getattr(result, "operation_advice", "") or "")
        markers = _buy_markers(language)
        if _contains_any(advice, markers, language=language):
            return True
        # 「不追高」否定的是追價，不是買進本身：「逢低買進，不追高」仍是買進，不能因此跳過護欄
        buy_markers = tuple(m for m in markers if m not in _CHASE_MARKERS)
        if _contains_any(advice, buy_markers, language=language, require_negation=True):
            return False
        return True
    advice = str(getattr(result, "operation_advice", "") or "")
    return _contains_any(advice, _buy_markers(language), language=language)


def _buy_markers(language: str) -> tuple[str, ...]:
    if language == "en":
        return _AGGRESSIVE_BUY_MARKERS_EN
    if language == "ko":
        return _AGGRESSIVE_BUY_MARKERS_KO
    return _AGGRESSIVE_BUY_MARKERS_ZH


def _contains_any(
    text: str,
    markers: tuple[str, ...],
    *,
    language: str = "zh",
    require_negation: bool = False,
) -> bool:
    lowered = text.lower()
    negation_hints = _negation_hints_for(language)
    for marker in markers:
        marker_lower = marker.lower()
        marker_pos = 0
        while True:
            marker_pos = lowered.find(marker_lower, marker_pos)
            if marker_pos == -1:
                break
            context = lowered[max(0, marker_pos - _NEGATION_LOOKBACK):marker_pos]
            has_negation = _contains_negation_near_marker(context, negation_hints, zh=language not in ("en", "ko"))
            if require_negation:
                if has_negation:
                    return True
            elif not has_negation:
                return True
            marker_pos += len(marker_lower)
    return False


def _contains_negation_near_marker(context: str, negation_hints: tuple[str, ...], *, zh: bool = False) -> bool:
    separators = ("，", ",", "。", "；", ";", "：", ":", "？", "!", "！", "）", ")", "（", "(")
    tail = context
    sep_pos = -1
    for separator in separators:
        candidate = context.rfind(separator)
        if candidate > sep_pos:
            sep_pos = candidate
    if sep_pos >= 0:
        tail = context[sep_pos + 1 :]
    if zh:
        if tail.endswith(_NEGATION_IMMEDIATE_ZH):
            head = tail[:-1]
            rhetorical = head.endswith("何") and not head[:-1].endswith(_RHETORICAL_HE_EXCLUDED)
            return not (head.endswith(_DOUBLE_NEGATION_ZH) or rhetorical)
        for compound in _NEGATION_FALSE_COMPOUNDS_ZH:
            tail = tail.replace(compound, "")
    return any(hint in tail for hint in negation_hints)


def _cap_conservative_sentiment_score(value: Any) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        return _GUARDRAIL_SENTIMENT_SCORE
    return min(_GUARDRAIL_SENTIMENT_SCORE, max(0, score))

def _is_high_confidence(value: Any) -> bool:
    return str(value or "").strip().lower() in {"高", "high", "높음"}
