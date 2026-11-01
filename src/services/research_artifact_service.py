# -*- coding: utf-8 -*-
"""Build structured research artifacts from existing analysis reports."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlsplit

from api.v1.schemas.research_artifact import ResearchArtifact
from src.analysis_context_pack_overview import extract_analysis_context_pack_overview
from src.utils.zh_s2t import to_traditional
from src.report_language import normalize_report_language
from src.services.report_decision_fields import (
    DECISION_FIELD_KEYS,
    extract_report_decision_fields,
    finite_float,
    format_price,
)
from src.utils.data_processing import (
    extract_fundamental_detail_fields,
    extract_market_structure_detail_field,
    extract_realtime_detail_fields,
    parse_json_field,
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
    "stop_loss_trigger": {
        "en": "Close below {value}",
        "zh": "收盘跌破 {value}",
        "zh-TW": "收盤跌破 {value}",
        "ko": "종가가 {value} 하회",
    },
    "take_profit_trigger": {
        "en": "Close above {value}",
        "zh": "收盘站上 {value}",
        "zh-TW": "收盤站上 {value}",
        "ko": "종가가 {value} 상회",
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
    "event_low": {
        "en": "Close breaks the event-day low: {value}",
        "zh": "收盘跌破事件日低点：{value}",
        "zh-TW": "收盤跌破事件日低點：{value}",
        "ko": "종가가 이벤트일 저점을 이탈: {value}",
    },
    "short_title": {"en": "Short interest", "zh": "放空部位", "zh-TW": "放空部位", "ko": "공매도 잔고"},
    "filing_8k_title": {"en": "SEC 8-K filing", "zh": "SEC 8-K 申报", "zh-TW": "SEC 8-K 申報", "ko": "SEC 8-K 공시"},
    "filing_10q_title": {"en": "SEC 10-Q filing", "zh": "SEC 10-Q 申报", "zh-TW": "SEC 10-Q 申報", "ko": "SEC 10-Q 공시"},
    "insider_title": {"en": "Insider transactions", "zh": "内部人交易", "zh-TW": "內部人交易", "ko": "내부자 거래"},
    "ratings_title": {"en": "Analyst rating changes", "zh": "评等调整", "zh-TW": "評等調整", "ko": "투자의견 변경"},
    "estimates_title": {"en": "Analyst estimates", "zh": "法人预估", "zh-TW": "法人預估", "ko": "애널리스트 추정치"},
    "ownership_title": {"en": "Ownership", "zh": "持股结构", "zh-TW": "持股結構", "ko": "보유 구조"},
    "futu_title": {"en": "Capital flow", "zh": "资金流", "zh-TW": "資金流", "ko": "자금 흐름"},
}

# 前端 camelcase 會把「數字接字母」的鍵轉壞（max_drawdown_1y → maxDrawdown1Y），投影時直接擋掉。
_UNSAFE_FACT_KEY_RE = re.compile(r"[0-9][a-zA-Z]", re.ASCII)
# Single trend words carry no reasoning on their own; drop them from thesis.reasons.
_TREND_ONLY_WORDS = {"看多", "看空", "震盪", "bullish", "bearish"}
_SOURCE_STATUS_VALUES = {"ok", "no_data", "fetch_failed", "timeout", "not_configured", "not_supported"}


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

    evidence.extend(_build_us_evidence(details, language))

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
        "event_gap": _event_gap(details),
        "source_status": _source_status(details),
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
    snapshot = parse_json_field(context_snapshot)
    enhanced = snapshot.get("enhanced_context") if isinstance(snapshot, dict) else None
    fundamental = enhanced.get("fundamental_context") if isinstance(enhanced, dict) else None
    fundamental = fundamental if isinstance(fundamental, dict) else {}
    dashboard = raw_result.get("dashboard") if isinstance(raw_result, dict) else None
    sniper_prices = detail.get("sniper_prices")
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
            **extract_report_decision_fields(raw_result, report_language),
        },
        "strategy": {
            "stop_loss_price": sniper_prices.get("stop_loss") if isinstance(sniper_prices, Mapping) else None,
            "take_profit_price": sniper_prices.get("take_profit") if isinstance(sniper_prices, Mapping) else None,
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
            "us_evidence": fundamental.get("us_evidence"),
            "us_evidence_status": fundamental.get("us_evidence_status"),
            "evidence_fetched_at": fundamental.get("as_of"),
            "event_gap": dashboard.get("event_gap") if isinstance(dashboard, dict) else None,
            "analysis_price": extract_realtime_detail_fields(snapshot).get("current_price"),
        },
    }


def _build_thesis(summary: Any) -> Dict[str, Any]:
    action = _as_text(_value(summary, "action")) or None
    action_label = _as_text(_value(summary, "action_label")) or _as_text(_value(summary, "operation_advice")) or None
    score = _as_int(_value(summary, "sentiment_score"))
    analysis_summary = _as_text(_value(summary, "analysis_summary"))
    trend_prediction = _as_text(_value(summary, "trend_prediction"))
    operation_advice = _as_text(_value(summary, "operation_advice"))
    thesis_summary = analysis_summary or trend_prediction or operation_advice
    reasons = _thesis_reasons([analysis_summary, trend_prediction], thesis_summary)
    risks = []
    if action == "alert":
        risks.append(operation_advice or "Report action is alert")
    return {
        "direction": _direction_from_action_or_score(action, score),
        "summary": thesis_summary,
        "score": score,
        "confidence": _score_to_confidence(score),
        "action": action,
        "action_label": action_label,
        "reasons": reasons,
        "risks": risks,
        **{key: _value(summary, key) for key in DECISION_FIELD_KEYS},
    }


def _thesis_reasons(candidates: List[str], summary: str) -> List[str]:
    """Drop reasons that just repeat the summary or are a bare trend word (exact match after stripping spaces)."""
    summary_key = _squash(summary)
    reasons = []
    for value in candidates:
        key = _squash(value)
        if not key or key == summary_key or key.lower() in _TREND_ONLY_WORDS:
            continue
        reasons.append(value)
    return reasons


def _squash(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _localized_block_label(label: str, language: str) -> str:
    # 區塊標籤的正本是簡體（analysis_context_pack_prompt.BLOCK_LABELS_ZH），舊報告落庫的也是。
    return to_traditional(label) if language == "zh-TW" else label


def _build_evidence(details: Any, context_overview: Any, language: str = "en") -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    blocks = _value(context_overview, "blocks") or []
    for index, block in enumerate(blocks):
        key = _as_text(_value(block, "key")) or f"context_{index + 1}"
        status = _as_text(_value(block, "status"))
        evidence.append({
            "id": f"context:{key}",
            "source_type": "analysis_context",
            "title": _localized_block_label(_as_text(_value(block, "label")) or key, language),
            "source": _as_text(_value(block, "source")) or None,
            "as_of": _as_timestamp(_value(block, "provider_timestamp")),
            "freshness": _freshness_from_status(status),
            "quality_level": _quality_from_status(status),
            "group": "context",
            "observed_at": _as_timestamp(_value(block, "provider_timestamp")),
            "fetched_at": _as_timestamp(_value(block, "fetched_at")),
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
            "group": "news",
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
            "group": "fundamental",
            "title": _text(language, "financial_title"),
            "freshness": "unknown",
            "quality_level": "usable",
        })

    if _value(details, "dividend_metrics"):
        evidence.append({
            "id": "fundamental:dividend_metrics",
            "source_type": "fundamental",
            "group": "fundamental",
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
            "group": "market",
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
        conditions.append(_price_condition(
            details, language, "stop_loss", stop_loss, _value(strategy, "stop_loss_price"),
            condition_id="price:stop_loss", severity="critical", direction="below",
        ))

    take_profit = _as_text(_value(strategy, "take_profit"))
    if take_profit:
        conditions.append(_price_condition(
            details, language, "take_profit", take_profit, _value(strategy, "take_profit_price"),
            condition_id="price:take_profit_review", severity="watch", direction="above",
        ))

    event_condition = _event_low_condition(details, language)
    if event_condition:
        conditions.append(event_condition)

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


def _price_condition(
    details: Any,
    language: str,
    kind: str,
    text: str,
    structured_level: Any,
    *,
    condition_id: str,
    severity: str,
    direction: str,
) -> Dict[str, Any]:
    """Structured sniper price -> numeric threshold and short trigger; legacy text stays verbatim (never parsed)."""
    level = finite_float(structured_level)
    condition: Dict[str, Any] = {
        "id": condition_id,
        "category": "price",
        "description": _text(language, kind, value=text),
        "trigger": text,
        "severity": severity,
        "metric": "price",
        "threshold": text,
        "direction": direction,
        "status": _price_condition_status(details, structured_level, direction),
    }
    if level is not None:
        number = format_price(level)
        condition["threshold"] = number
        condition["trigger"] = _text(language, f"{kind}_trigger", value=number)
        condition["metadata"] = {"rationale": text}
    return condition


def _price_condition_status(details: Any, threshold: Any, direction: str) -> str:
    """只有分析當下的價格與結構化價位都是有限數才判 triggered；缺一個維持 pending。"""
    price = finite_float(_value(details, "analysis_price"))
    level = finite_float(threshold)
    if price is None or level is None:
        return "pending"
    crossed = price <= level if direction == "below" else price >= level
    return "triggered" if crossed else "pending"


def _event_low_condition(details: Any, language: str) -> Optional[Dict[str, Any]]:
    event = _value(details, "event_gap")
    if not isinstance(event, Mapping):
        return None
    low = finite_float(event.get("event_low"))
    if low is None:
        return None
    broken = event.get("event_low_broken")
    return {
        "id": "event:low_break",
        "category": "price",
        "description": _text(language, "event_low", value=f"{low:g}"),
        "trigger": f"{low:g}",
        "severity": "critical",
        "metric": "close",
        "threshold": f"{low:g}",
        "direction": "below",
        # 布林才算事實；缺值（事件後還沒有收盤）維持 pending。
        "status": "triggered" if broken is True else "pending",
    }


def _event_gap(details: Any) -> Optional[Dict[str, Any]]:
    event = _value(details, "event_gap")
    return dict(event) if isinstance(event, Mapping) else None


def _source_status(details: Any) -> Dict[str, str]:
    status = _value(details, "us_evidence_status")
    if not isinstance(status, Mapping):
        return {}
    return {str(key): str(value) for key, value in status.items() if value in _SOURCE_STATUS_VALUES}


def _safe_sec_url(value: Any) -> Optional[str]:
    """只放行 https＋sec.gov；來源字串可能被投毒，不能直接變成可點連結。"""
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme != "https" or not (host == "sec.gov" or host.endswith(".sec.gov")):
        return None
    return value.strip()


def _scalar_facts(source: Any, *keys: str) -> Dict[str, Any]:
    """取純量欄位；bool 與字串保留，鍵名含「數字接字母」的丟掉。"""
    if not isinstance(source, Mapping):
        return {}
    names = keys or tuple(str(key) for key in source)
    facts: Dict[str, Any] = {}
    for key in names:
        value = source.get(key)
        if _UNSAFE_FACT_KEY_RE.search(key) or value is None or isinstance(value, (Mapping, list, tuple)):
            continue
        facts[key] = value
    return facts


def _us_evidence_item(
    item_id: str,
    group: str,
    title: str,
    fetched_at: Optional[str],
    **fields: Any,
) -> Dict[str, Any]:
    # 美股補充證據純資訊，不參與評分（data_provider/us_evidence.py）。
    return {
        "id": item_id,
        "source_type": "us_evidence",
        "title": title,
        "group": group,
        "fetched_at": fetched_at,
        "counts_toward_score": False,
        "metadata": {"status": "available"},
        **fields,
    }


def _build_us_evidence(details: Any, language: str) -> List[Dict[str, Any]]:
    evidence = _value(details, "us_evidence")
    if not isinstance(evidence, Mapping):
        return []
    fetched = _as_text(_value(details, "evidence_fetched_at")) or None
    items: List[Dict[str, Any]] = []

    finra = evidence.get("finra_short")
    short = finra if isinstance(finra, Mapping) and finra else evidence.get("short_interest")
    if isinstance(short, Mapping) and short:
        items.append(_us_evidence_item(
            "us:short_interest", "short_interest", _text(language, "short_title"), fetched,
            source="FINRA" if short is finra else "yfinance",
            observed_at=_as_text(short.get("as_of")) or None,
            facts=_scalar_facts(short, "shares_short", "days_to_cover", "float_pct"),
        ))

    sec = evidence.get("sec_filings")
    if isinstance(sec, Mapping):
        filings = sec.get("recent_8k")
        for index, filing in enumerate(filings if isinstance(filings, list) else []):
            if not isinstance(filing, Mapping):
                continue
            excerpt_url = _safe_sec_url(filing.get("excerpt_url"))
            items.append(_us_evidence_item(
                f"sec:8k:{index + 1}", "sec_filing", _text(language, "filing_8k_title"), fetched,
                source="SEC EDGAR",
                observed_at=_as_text(filing.get("date")) or None,
                url=_safe_sec_url(filing.get("url")),
                excerpt=_as_text(filing.get("excerpt")) or None,
                facts={
                    **_scalar_facts(filing, "items", "accepted_at"),
                    **({"excerpt_url": excerpt_url} if excerpt_url else {}),
                },
            ))
        quarter = _as_text(sec.get("latest_10q_date"))
        if quarter:
            items.append(_us_evidence_item(
                "sec:10q", "sec_filing", _text(language, "filing_10q_title"), fetched,
                source="SEC EDGAR", observed_at=quarter,
            ))

    form4 = evidence.get("insider_form4")
    # 鍵名 insider_90d 會被 camelcase 轉壞，這裡一律投影成 insider:recent＋window_days。
    insider = form4 if isinstance(form4, Mapping) and form4 else evidence.get("insider_90d")
    if isinstance(insider, Mapping) and insider:
        items.append(_us_evidence_item(
            "insider:recent", "insider", _text(language, "insider_title"), fetched,
            source="SEC Form 4" if insider is form4 else "yfinance",
            observed_at=_as_text(insider.get("as_of")) or None,
            window_days=_as_int(insider.get("window_days")),
            complete=insider.get("complete") if isinstance(insider.get("complete"), bool) else None,
            facts=_scalar_facts(
                insider, "buy_shares", "sell_shares", "net_shares", "classified_count",
                "excluded_count", "filings_read", "filings_available",
            ),
        ))

    ratings = evidence.get("ratings_30d")
    if isinstance(ratings, Mapping) and ratings:
        entries = ratings.get("entries")
        items.append(_us_evidence_item(
            "ratings:recent", "ratings", _text(language, "ratings_title"), fetched,
            source="yfinance",
            observed_at=_as_text(ratings.get("as_of")) or None,
            window_days=_as_int(ratings.get("window_days")),
            facts=_scalar_facts(ratings, "count"),
            series=[dict(entry) for entry in entries if isinstance(entry, Mapping)] if isinstance(entries, list) else None,
        ))

    estimates = evidence.get("estimates")
    if isinstance(estimates, Mapping) and estimates:
        revisions = estimates.get("revisions")
        revisions = revisions if isinstance(revisions, Mapping) else {}
        track = estimates.get("track_record")
        facts = {
            "eps": _scalar_facts(estimates.get("eps")),
            "revenue": _scalar_facts(estimates.get("revenue")),
            # 來源鍵 up_7d 會被 camelcase 轉壞，改成不含數字接字母的鍵。
            "revisions": {
                target: revisions[source]
                for source, target in (
                    ("up_7d", "up_week"), ("up_30d", "up_month"),
                    ("down_7d", "down_week"), ("down_30d", "down_month"),
                )
                if source in revisions
            },
        }
        items.append(_us_evidence_item(
            "estimates:next_quarter", "estimates", _text(language, "estimates_title"), fetched,
            source="yfinance",
            facts=facts,
            series=[dict(row) for row in track if isinstance(row, Mapping)] if isinstance(track, list) else None,
        ))

    ownership = _scalar_facts(evidence, "institutions_pct", "insiders_pct")
    if ownership:
        items.append(_us_evidence_item(
            "ownership:holders", "ownership", _text(language, "ownership_title"), fetched,
            source="yfinance", facts=ownership,
        ))

    futu = evidence.get("futu")
    if isinstance(futu, Mapping) and futu:
        items.append(_us_evidence_item(
            "futu:capital_flow", "capital_flow", _text(language, "futu_title"), fetched,
            source="Futu", facts=_scalar_facts(futu),
        ))
    return items


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
    # Invalidation conditions already have their own section; do not echo them (or the
    # analysis summary) here as follow-up items.
    return [{"action": action, "label": label}]


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
