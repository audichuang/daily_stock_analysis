# -*- coding: utf-8 -*-
"""Structured research artifact schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from src.schemas.decision_action import DecisionAction


ResearchQualityLevel = Literal["good", "usable", "limited", "poor", "unknown"]
ResearchDirection = Literal["bullish", "bearish", "neutral", "unknown"]
ResearchEvidenceFreshness = Literal["fresh", "stale", "unknown"]
ResearchInvalidationCategory = Literal[
    "price",
    "volume",
    "evidence",
    "market",
    "time",
    "data_quality",
    "manual",
]
ResearchInvalidationSeverity = Literal["watch", "warning", "critical"]
ResearchInvalidationDirection = Literal["below", "above"]
ResearchInvalidationStatus = Literal["pending", "triggered", "review"]
ResearchSourceStatus = Literal["ok", "no_data", "fetch_failed", "timeout", "not_configured", "not_supported"]


class ResearchSubject(BaseModel):
    """The entity being researched."""

    stock_code: str = Field(..., min_length=1)
    stock_name: Optional[str] = None
    market: Optional[str] = None
    entity_ref: Optional[str] = Field(None, description="Optional EntityLink ref when available")


class ResearchThesis(BaseModel):
    """Structured investment thesis extracted from a report."""

    direction: ResearchDirection = "unknown"
    summary: str = Field("", description="Concise thesis statement")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    score: Optional[int] = Field(None, description="Original sentiment score when available")
    horizon: Optional[str] = None
    action: Optional[DecisionAction] = None
    action_label: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    one_sentence: Optional[str] = None
    time_sensitivity: Optional[str] = None
    position_advice: Optional[Dict[str, Optional[str]]] = None
    confidence_level: Optional[str] = None
    confidence_reason: Optional[str] = None
    guardrail_applied: Optional[bool] = None
    guardrail_reason: Optional[str] = None
    strongest_bullish_signal: Optional[str] = None
    strongest_bearish_signal: Optional[str] = None
    watch_conditions: Optional[List[str]] = None
    entry_conditions: Optional[List[str]] = None
    exit_triggers: Optional[List[str]] = None
    pending_events: Optional[List[str]] = None
    next_check_time: Optional[str] = None


class ResearchEvidenceItem(BaseModel):
    """One evidence item with freshness and quality status."""

    id: str = Field(..., min_length=1)
    source_type: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    summary: Optional[str] = None
    source: Optional[str] = None
    freshness: ResearchEvidenceFreshness = "unknown"
    quality_level: ResearchQualityLevel = "unknown"
    as_of: Optional[str] = None
    url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    group: Optional[str] = Field(None, description="畫面分組鍵")
    observed_at: Optional[str] = Field(None, description="資料本身的觀測日")
    fetched_at: Optional[str] = Field(None, description="抓取時間，不代表觀測日")
    window_days: Optional[int] = Field(None, description="統計窗口天數")
    complete: Optional[bool] = Field(None, description="false 表示只涵蓋部分資料")
    counts_toward_score: Optional[bool] = Field(None, description="是否計入評分；純資訊為 false")
    facts: Optional[Dict[str, Any]] = Field(None, description="結構化數值；鍵名不含「數字接字母」")
    excerpt: Optional[str] = Field(None, description="原文摘錄")
    series: Optional[List[Dict[str, Any]]] = Field(None, description="逐期資料")


class ResearchInvalidationCondition(BaseModel):
    """Condition that should invalidate or force reassessment of the thesis."""

    id: str = Field(..., min_length=1)
    category: ResearchInvalidationCategory
    description: str = Field(..., min_length=1)
    trigger: Optional[str] = None
    severity: ResearchInvalidationSeverity = "warning"
    metric: Optional[str] = None
    threshold: Optional[str] = None
    due_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    direction: Optional[ResearchInvalidationDirection] = Field(None, description="價格往哪個方向穿越才成立")
    status: ResearchInvalidationStatus = Field(
        "review",
        description="triggered 只由分析當下的事實設定；其餘為 pending（等價格）或 review（等人判斷）",
    )


class ResearchNextAction(BaseModel):
    """Suggested next action for a human or workflow."""

    action: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    reason: Optional[str] = None
    due_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResearchDataQuality(BaseModel):
    """Low-sensitive quality summary for the artifact inputs."""

    level: ResearchQualityLevel = "unknown"
    overall_score: Optional[int] = Field(None, ge=0, le=100)
    source_count: int = Field(0, ge=0)
    stale_count: int = Field(0, ge=0)
    missing_blocks: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class ResearchEventGap(BaseModel):
    """重大波動事件的事實；鍵名與 dashboard.event_gap 相同。"""

    triggered: Optional[bool] = None
    event_date: Optional[str] = None
    change_pct: Optional[float] = None
    event_low: Optional[float] = None
    sessions_since_event: Optional[int] = None
    threshold_pct: Optional[float] = None
    latest_close: Optional[float] = None
    post_event_min_close: Optional[float] = None
    event_low_broken: Optional[bool] = None
    news_evidence_present: Optional[bool] = None
    blocked_without_news: Optional[bool] = None
    reason: Optional[str] = None


class ResearchArtifact(BaseModel):
    """Structured report artifact for dashboard, stock detail, monitor and copilot reuse."""

    schema_version: Literal["research-artifact-v1"] = "research-artifact-v1"
    artifact_id: str = Field(..., min_length=1)
    source_report_id: Optional[int] = None
    source_query_id: Optional[str] = None
    created_at: Optional[str] = None
    subject: ResearchSubject
    thesis: ResearchThesis
    evidence: List[ResearchEvidenceItem] = Field(default_factory=list)
    invalidation_conditions: List[ResearchInvalidationCondition] = Field(..., min_length=1)
    next_actions: List[ResearchNextAction] = Field(default_factory=list)
    data_quality: ResearchDataQuality = Field(default_factory=ResearchDataQuality)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    event_gap: Optional[ResearchEventGap] = None
    source_status: Dict[str, ResearchSourceStatus] = Field(
        default_factory=dict,
        description="各補充來源的取得結果；舊報告為空",
    )
