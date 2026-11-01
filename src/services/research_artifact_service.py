# -*- coding: utf-8 -*-
"""Build structured research artifacts from existing analysis reports."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional

from api.v1.schemas.research_artifact import ResearchArtifact
from src.analysis_context_pack_overview import extract_analysis_context_pack_overview
from src.report_language import normalize_report_language
from src.utils.data_processing import (
    extract_fundamental_detail_fields,
    extract_market_structure_detail_field,
)


_BULLISH_ACTIONS = {"buy", "add"}
_BEARISH_ACTIONS = {"reduce", "sell", "avoid"}
_NEUTRAL_ACTIONS = {"hold", "watch"}

# 舊版 iOS 會原樣顯示這些句子，新增文字要補齊四語。未指定語言時維持英文（既有行為）。
_ARTIFACT_TEXT: Dict[str, Dict[str, str]] = {
    "stop_loss": {
        "en": "Price breaks the report stop-loss area: {value}",
        "zh": "价格跌破报告停损区：{value}",
        "zh-TW": "股價跌破報告的停損區：{value}",
        "ko": "가격이 보고서의 손절 구간을 이탈: {value}",
    },
    "take_profit": {
        "en": "Price reaches the take-profit area and requires reassessment: {value}",
        "zh": "价格到达停利区，需要重新评估：{value}",
        "zh-TW": "股價到達停利區，需要重新評估：{value}",
        "ko": "가격이 익절 구간에 도달하여 재평가 필요: {value}",
    },
    "data_quality": {
        "en": "Input data quality limitations require reassessment when fresh data is available.",
        "zh": "输入数据有品质限制，取得新数据后需要重新评估。",
        "zh-TW": "輸入資料有品質限制，取得新資料後需要重新評估。",
        "ko": "입력 데이터 품질에 제한이 있어 새 데이터 확보 시 재평가가 필요합니다.",
    },
    "news_missing": {
        "en": "News evidence was unavailable or empty during report generation.",
        "zh": "生成报告时没有可用的新闻证据。",
        "zh-TW": "產生報告時沒有可用的新聞證據。",
        "ko": "보고서 생성 시 뉴스 근거를 확보하지 못했습니다.",
    },
    "manual": {
        "en": "Reassess when price action, news, fundamentals, or market phase conflicts with the thesis.",
        "zh": "价格走势、新闻、基本面或市场阶段与论点冲突时，重新评估。",
        "zh-TW": "股價走勢、新聞、基本面或市場階段與論點衝突時，重新評估。",
        "ko": "가격 흐름, 뉴스, 펀더멘털 또는 시장 단계가 논지와 충돌하면 재평가합니다.",
    },
    "monitor_invalidation": {
        "en": "Monitor invalidation",
        "zh": "监控失效条件",
        "zh-TW": "監控改判條件",
        "ko": "무효화 조건 모니터링",
    },
    "news_title": {"en": "News summary", "zh": "新闻摘要", "zh-TW": "新聞摘要", "ko": "뉴스 요약"},
    "financial_title": {"en": "Financial report", "zh": "财务报表", "zh-TW": "財務報表", "ko": "재무제표"},
    "dividend_title": {"en": "Dividend metrics", "zh": "股利指标", "zh-TW": "股利指標", "ko": "배당 지표"},
    "market_title": {"en": "Market structure", "zh": "市场结构", "zh-TW": "市場結構", "ko": "시장 구조"},
}


def _text(language: str, key: str, **values: Any) -> str:
    template = _ARTIFACT_TEXT[key][language]
    return template.format(**values) if values else template


def build_research_artifact(
    report: Any,
    *,
    evidence_items: Optional[Iterable[Dict[str, Any]]] = None,
    invalidation_conditions: Optional[Iterable[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a ResearchArtifact-compatible dict without mutating the source report."""
    meta = _section(report, "meta")
    language = _artifact_language(meta)
    summary = _section(report, "summary")
    strategy = _section(report, "strategy")
    details = _section(report, "details")
    context_overview = _value(details, "analysis_context_pack_overview")
    source_report_id = _as_int(_value(meta, "id"))
    query_id = _as_text(_value(meta, "query_id"))
    stock_code = _as_text(_value(meta, "stock_code")) or "UNKNOWN"
    artifact_id = (
        f"report:{source_report_id}"
        if source_report_id is not None
        else f"report:{stock_code}:{query_id}" if query_id else f"report:{stock_code}"
    )

    evidence = _build_evidence(details, context_overview, language)
    if evidence_items is not None:
        evidence.extend(dict(item) for item in evidence_items)

    invalidations = _build_invalidation_conditions(summary, strategy, details, context_overview, language)
    if invalidation_conditions is not None:
        invalidations.extend(dict(item) for item in invalidation_conditions)
    if not invalidations:
        invalidations.append(_manual_reassessment_condition(language))

    payload = {
        "artifact_id": artifact_id,
        "source_report_id": source_report_id,
        "source_query_id": query_id or None,
        "created_at": _as_text(_value(meta, "created_at")) or None,
        "subject": {
            "stock_code": stock_code,
            "stock_name": _as_text(_value(meta, "stock_name")) or None,
            "market": _subject_market(meta, context_overview),
        },
        "thesis": _build_thesis(summary),
        "evidence": evidence,
        "invalidation_conditions": invalidations,
        "next_actions": _build_next_actions(summary, invalidations, language),
        "data_quality": _build_data_quality(context_overview, evidence),
        "metadata": {
            "source": "analysis_report",
            **dict(metadata or {}),
        },
    }
    return ResearchArtifact.model_validate(payload).model_dump(exclude_none=True)


def _artifact_language(meta: Any) -> str:
    raw = _as_text(_value(meta, "report_language"))
    return normalize_report_language(raw) if raw else "en"


def artifact_input_from_detail(
    detail: Mapping[str, Any],
    *,
    persisted_fundamental: Any = None,
) -> Dict[str, Any]:
    """把歷史詳情 dict 組成 build_research_artifact 的輸入；個股頁與 /history/{id} 共用。"""
    context_snapshot = detail.get("context_snapshot")
    raw_result = detail.get("raw_result")
    raw_fundamental = (
        raw_result.get("fundamental_context") or raw_result
        if isinstance(raw_result, dict)
        else None
    )
    extracted_fundamental = extract_fundamental_detail_fields(context_snapshot, raw_fundamental)
    persisted_fields = extract_fundamental_detail_fields(None, persisted_fundamental)
    context_overview = extract_analysis_context_pack_overview(context_snapshot)
    market_structure = extract_market_structure_detail_field(context_snapshot, raw_result)
    report_language = raw_result.get("report_language") if isinstance(raw_result, dict) else None
    return {
        "meta": {
            "id": detail.get("id"),
            "query_id": detail.get("query_id"),
            "stock_code": detail.get("stock_code"),
            "stock_name": detail.get("stock_name"),
            "created_at": detail.get("created_at"),
            "report_language": report_language,
        },
        "summary": {
            "analysis_summary": detail.get("analysis_summary"),
            "operation_advice": detail.get("operation_advice"),
            "action": detail.get("action"),
            "action_label": detail.get("action_label"),
            "trend_prediction": detail.get("trend_prediction"),
            "sentiment_score": detail.get("sentiment_score"),
        },
        "strategy": {
            "ideal_buy": detail.get("ideal_buy"),
            "secondary_buy": detail.get("secondary_buy"),
            "stop_loss": detail.get("stop_loss"),
            "take_profit": detail.get("take_profit"),
        },
        "details": {
            "news_content": detail.get("news_content"),
            "empty_news_disclosure": detail.get("empty_news_disclosure"),
            "analysis_context_pack_overview": context_overview,
            "financial_report": detail.get("financial_report")
            or extracted_fundamental.get("financial_report")
            or persisted_fields.get("financial_report"),
            "dividend_metrics": detail.get("dividend_metrics")
            or extracted_fundamental.get("dividend_metrics")
            or persisted_fields.get("dividend_metrics"),
            "market_structure": detail.get("market_structure") or market_structure,
        },
    }


def _build_thesis(summary: Any) -> Dict[str, Any]:
    action = _as_text(_value(summary, "action")) or None
    action_label = _as_text(_value(summary, "action_label")) or _as_text(_value(summary, "operation_advice")) or None
    score = _as_int(_value(summary, "sentiment_score"))
    analysis_summary = _as_text(_value(summary, "analysis_summary"))
    trend_prediction = _as_text(_value(summary, "trend_prediction"))
    operation_advice = _as_text(_value(summary, "operation_advice"))
    reasons = [value for value in [analysis_summary, trend_prediction] if value]
    risks = []
    if action == "alert":
        risks.append(operation_advice or "Report action is alert")
    return {
        "direction": _direction_from_action_or_score(action, score),
        "summary": analysis_summary or trend_prediction or operation_advice,
        "score": score,
        "confidence": _score_to_confidence(score),
        "action": action,
        "action_label": action_label,
        "reasons": reasons,
        "risks": risks,
    }


def _build_evidence(details: Any, context_overview: Any, language: str = "en") -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    blocks = _value(context_overview, "blocks") or []
    for index, block in enumerate(blocks):
        key = _as_text(_value(block, "key")) or f"context_{index + 1}"
        status = _as_text(_value(block, "status"))
        evidence.append({
            "id": f"context:{key}",
            "source_type": "analysis_context",
            "title": _as_text(_value(block, "label")) or key,
            "source": _as_text(_value(block, "source")) or None,
            "as_of": _as_timestamp(_value(block, "provider_timestamp")),
            "freshness": _freshness_from_status(status),
            "quality_level": _quality_from_status(status),
            "metadata": {
                "status": status,
                **_evidence_timestamps(block),
                "warnings": _value(block, "warnings") or [],
                "missing_reasons": _value(block, "missing_reasons") or [],
            },
        })

    if _value(details, "news_content") or _value(details, "empty_news_disclosure"):
        has_news_content = bool(_value(details, "news_content"))
        evidence.append({
            "id": "news:summary",
            "source_type": "news",
            "title": _text(language, "news_title"),
            "summary": _as_text(_value(details, "empty_news_disclosure"))
            or _compact(_as_text(_value(details, "news_content"))),
            "freshness": "unknown",
            "quality_level": "usable" if has_news_content else "limited",
            "metadata": {"status": "available" if has_news_content else "missing"},
        })

    if _value(details, "financial_report"):
        evidence.append({
            "id": "fundamental:financial_report",
            "source_type": "fundamental",
            "title": _text(language, "financial_title"),
            "freshness": "unknown",
            "quality_level": "usable",
        })

    if _value(details, "dividend_metrics"):
        evidence.append({
            "id": "fundamental:dividend_metrics",
            "source_type": "fundamental",
            "title": _text(language, "dividend_title"),
            "freshness": "unknown",
            "quality_level": "usable",
        })

    market_structure = _value(details, "market_structure")
    if market_structure:
        status = _as_text(_value(market_structure, "status"))
        evidence.append({
            "id": "market:structure",
            "source_type": "market_structure",
            "title": _text(language, "market_title"),
            "freshness": _freshness_from_status(status),
            "quality_level": _quality_from_status(status),
            "metadata": {"status": status},
        })

    return evidence


def _build_invalidation_conditions(
    summary: Any,
    strategy: Any,
    details: Any,
    context_overview: Any,
    language: str = "en",
) -> List[Dict[str, Any]]:
    conditions: List[Dict[str, Any]] = []
    stop_loss = _as_text(_value(strategy, "stop_loss"))
    if stop_loss:
        conditions.append({
            "id": "price:stop_loss",
            "category": "price",
            "description": _text(language, "stop_loss", value=stop_loss),
            "trigger": stop_loss,
            "severity": "critical",
            "metric": "price",
            "threshold": stop_loss,
        })

    take_profit = _as_text(_value(strategy, "take_profit"))
    if take_profit:
        conditions.append({
            "id": "price:take_profit_review",
            "category": "price",
            "description": _text(language, "take_profit", value=take_profit),
            "trigger": take_profit,
            "severity": "watch",
            "metric": "price",
            "threshold": take_profit,
        })

    limitations = _quality_limitations(context_overview)
    if limitations:
        conditions.append({
            "id": "data_quality:limitations",
            "category": "data_quality",
            "description": _text(language, "data_quality"),
            "trigger": "; ".join(limitations[:3]),
            "severity": "warning",
            "metadata": {"limitations": limitations},
        })

    disclosure = _as_text(_value(details, "empty_news_disclosure"))
    if disclosure:
        conditions.append({
            "id": "evidence:news_missing",
            "category": "evidence",
            "description": _text(language, "news_missing"),
            "trigger": disclosure,
            "severity": "watch",
        })

    thesis_text = _as_text(_value(summary, "analysis_summary")) or _as_text(_value(summary, "trend_prediction"))
    if thesis_text and not conditions:
        conditions.append(_manual_reassessment_condition(language))

    return conditions


def _manual_reassessment_condition(language: str = "en") -> Dict[str, Any]:
    return {
        "id": "manual:thesis_reassessment",
        "category": "manual",
        "description": _text(language, "manual"),
        "severity": "warning",
    }


def _build_next_actions(summary: Any, invalidations: List[Dict[str, Any]], language: str = "en") -> List[Dict[str, Any]]:
    action = _as_text(_value(summary, "action")) or "watch"
    label = _as_text(_value(summary, "action_label")) or _as_text(_value(summary, "operation_advice")) or action
    next_actions = [{
        "action": action,
        "label": label,
        "reason": _as_text(_value(summary, "analysis_summary")) or None,
    }]
    if invalidations:
        next_actions.append({
            "action": "monitor_invalidation",
            "label": _text(language, "monitor_invalidation"),
            "reason": invalidations[0]["description"],
            "metadata": {"condition_id": invalidations[0]["id"]},
        })
    return next_actions


def _build_data_quality(context_overview: Any, evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    data_quality = _value(context_overview, "data_quality")
    counts = _value(context_overview, "counts")
    missing_blocks = [
        _as_text(_value(block, "key"))
        for block in (_value(context_overview, "blocks") or [])
        if _as_text(_value(block, "status")) in {"missing", "fetch_failed", "not_supported"}
    ]
    return {
        "level": _as_text(_value(data_quality, "level")) or _infer_quality_level(evidence),
        "overall_score": _as_int(_value(data_quality, "overall_score")),
        "source_count": sum(1 for item in evidence if _evidence_has_usable_source(item)),
        "stale_count": sum(1 for item in evidence if item.get("freshness") == "stale"),
        "missing_blocks": [block for block in missing_blocks if block],
        "limitations": _quality_limitations(context_overview),
        "metadata": {"counts": counts} if counts else {},
    }


def _quality_limitations(context_overview: Any) -> List[str]:
    data_quality = _value(context_overview, "data_quality")
    limitations = _value(data_quality, "limitations") or []
    return [_as_text(item) for item in limitations if _as_text(item)]


def _direction_from_action_or_score(action: Optional[str], score: Optional[int]) -> str:
    if action in _BULLISH_ACTIONS:
        return "bullish"
    if action in _BEARISH_ACTIONS:
        return "bearish"
    if action in _NEUTRAL_ACTIONS:
        return "neutral"
    if score is not None:
        if score >= 65:
            return "bullish"
        if score <= 35:
            return "bearish"
        return "neutral"
    return "unknown"


def _score_to_confidence(score: Optional[int]) -> Optional[float]:
    if score is None:
        return None
    bounded = max(0, min(100, score))
    return round(abs(bounded - 50) / 50, 2)


def _freshness_from_status(status: str) -> str:
    # Availability is not a freshness assessment. In particular a recent
    # fetch can return old observations, and different markets/data types need
    # different age policies. Only preserve an explicit upstream stale marker.
    if status == "stale":
        return "stale"
    return "unknown"


def _evidence_timestamps(block: Any) -> Dict[str, str]:
    result = {}
    for source_key, target_key in (("timestamp", "context_timestamp"), ("fetched_at", "fetched_at")):
        value = _as_timestamp(_value(block, source_key))
        if value:
            result[target_key] = value
    return result


def _as_timestamp(value: Any) -> Optional[str]:
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _quality_from_status(status: str) -> str:
    if status in {"available", "ok"}:
        return "good"
    if status in {"fallback", "estimated"}:
        return "usable"
    if status in {"partial", "stale"}:
        return "limited"
    if status in {"missing", "fetch_failed"}:
        return "poor"
    return "unknown"


def _evidence_has_usable_source(item: Dict[str, Any]) -> bool:
    metadata = item.get("metadata")
    status = _as_text(metadata.get("status")) if isinstance(metadata, dict) else ""
    return status not in {"missing", "fetch_failed", "not_supported", "unavailable", "unknown"}


def _infer_quality_level(evidence: List[Dict[str, Any]]) -> str:
    if not evidence:
        return "unknown"
    levels = {str(item.get("quality_level") or "unknown") for item in evidence}
    if "poor" in levels:
        return "poor"
    if "limited" in levels:
        return "limited"
    if "usable" in levels:
        return "usable"
    if levels == {"good"}:
        return "good"
    return "unknown"


def _subject_market(meta: Any, context_overview: Any) -> Optional[str]:
    market = _value(_value(context_overview, "subject"), "market")
    return _as_text(market) or _as_text(_value(meta, "market")) or None


def _section(report: Any, key: str) -> Any:
    return _value(report, key) or {}


def _value(source: Any, key: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        if key in source:
            return source[key]
        camel_key = _snake_to_camel(key)
        return source.get(camel_key)
    if hasattr(source, key):
        return getattr(source, key)
    return getattr(source, _snake_to_camel(key), None)


def _snake_to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item[:1].upper() + item[1:] for item in tail)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return re.sub(r"\s+", " ", text)


def _as_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _compact(value: str, limit: int = 180) -> str:
    text = _as_text(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."
