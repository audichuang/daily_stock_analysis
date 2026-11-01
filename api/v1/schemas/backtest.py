# -*- coding: utf-8 -*-
"""Backtest API schemas."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from api.v1.schemas.market_phase import MarketPhaseSummary
from src.schemas.decision_action import DecisionAction


class BacktestRunRequest(BaseModel):
    code: Optional[str] = Field(None, description="仅回测指定股票")
    force: bool = Field(False, description="强制重新计算")
    eval_window_days: Optional[int] = Field(None, ge=1, le=120, description="评估窗口（交易日数）")
    min_age_days: Optional[int] = Field(None, ge=0, le=365, description="分析记录最小天龄（0=不限）")
    analysis_date_from: Optional[date] = Field(None, description="分析日期起始（含）")
    analysis_date_to: Optional[date] = Field(None, description="分析日期结束（含）")
    limit: int = Field(200, ge=1, le=2000, description="最多处理的分析记录数")


class BacktestRunResponse(BaseModel):
    processed: int = Field(..., description="候选记录数")
    saved: int = Field(..., description="写入回测结果数")
    completed: int = Field(..., description="完成回测数")
    insufficient: int = Field(..., description="数据不足数")
    errors: int = Field(..., description="错误数")
    applied_eval_window_days: Optional[int] = Field(
        ...,
        description="实际生效的评估窗口（交易日数）",
    )
    message: Optional[str] = Field(None, description="空结果或降级时的诊断说明")
    diagnostics: Dict[str, Any] = Field(default_factory=dict, description="回测筛选与诊断信息")


class BacktestResultItem(BaseModel):
    analysis_history_id: int
    code: str
    stock_name: Optional[str] = None
    analysis_date: Optional[str] = None
    eval_window_days: int
    engine_version: str
    eval_status: str
    evaluated_at: Optional[str] = None
    operation_advice: Optional[str] = None
    action: Optional[DecisionAction] = None
    action_label: Optional[str] = None
    trend_prediction: Optional[str] = None
    market_phase: Optional[str] = None
    market_phase_summary: Optional[MarketPhaseSummary] = None
    position_recommendation: Optional[str] = None
    start_price: Optional[float] = None
    end_close: Optional[float] = None
    max_high: Optional[float] = None
    min_low: Optional[float] = None
    stock_return_pct: Optional[float] = None
    actual_return_pct: Optional[float] = None
    actual_movement: Optional[str] = None
    direction_expected: Optional[str] = None
    direction_correct: Optional[bool] = None
    outcome: Optional[str] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    hit_stop_loss: Optional[bool] = None
    hit_take_profit: Optional[bool] = None
    first_hit: Optional[str] = None
    first_hit_date: Optional[str] = None
    first_hit_trading_days: Optional[int] = None
    simulated_entry_price: Optional[float] = None
    simulated_exit_price: Optional[float] = None
    simulated_exit_reason: Optional[str] = None
    simulated_return_pct: Optional[float] = None
    # H2：台股比例式淨報酬（不含最低手續費與二代健保），價格基準與進場日；舊版本列為 null。
    simulated_net_return_pct: Optional[float] = None
    entry_date: Optional[str] = None
    price_basis: Optional[str] = None
    adjustment_reason: Optional[str] = None
    # eval_status 把「窗口還沒走完」也寫成 insufficient_data；這裡才分得開。舊欄位語意不變。
    maturity_status: Optional[str] = Field(None, description="completed/pending/insufficient_data 等分流狀態")
    matures_by: Optional[str] = Field(None, description="未到期時，窗口最晚走完的日期")
    market: Optional[str] = None


class BacktestResultsResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: List[BacktestResultItem] = Field(default_factory=list)
    status_counts: Dict[str, int] = Field(default_factory=dict, description="各分流的筆數，不受 status 參數影響")


class BacktestSeriesPoint(BaseModel):
    point_date: str = Field(..., serialization_alias="date", validation_alias="date")
    analysis_history_id: int
    code: str
    return_pct: float
    cumulative_return_pct: float


class BacktestMonthlyWinRate(BaseModel):
    month: str = Field(..., description="YYYY-MM")
    completed: int
    win: int
    loss: int
    neutral: int
    win_rate_pct: Optional[float] = Field(None, description="勝／(勝＋負)；沒有勝負時為 null")


class BacktestSeriesResponse(BaseModel):
    chart_title: str = "逐筆累計（非資金曲線）"
    eval_window_days: Optional[int] = None
    truncated: bool = Field(False, description="超過上限時只含最新的列，累計值不含更早的部分")
    points: List[BacktestSeriesPoint] = Field(default_factory=list)
    monthly: List[BacktestMonthlyWinRate] = Field(default_factory=list)


class PerformanceMetrics(BaseModel):
    scope: str
    code: Optional[str] = None
    eval_window_days: int
    engine_version: str
    computed_at: Optional[str] = None

    total_evaluations: int
    completed_count: int
    insufficient_count: int
    long_count: int
    cash_count: int
    win_count: int
    loss_count: int
    neutral_count: int

    direction_accuracy_pct: Optional[float] = None
    win_rate_pct: Optional[float] = None
    neutral_rate_pct: Optional[float] = None
    avg_stock_return_pct: Optional[float] = None
    avg_simulated_return_pct: Optional[float] = None

    stop_loss_trigger_rate: Optional[float] = None
    take_profit_trigger_rate: Optional[float] = None
    ambiguous_rate: Optional[float] = None
    avg_days_to_first_hit: Optional[float] = None

    advice_breakdown: Dict[str, Any] = Field(default_factory=dict)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
