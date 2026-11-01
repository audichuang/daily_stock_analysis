/**
 * Backtest API type definitions
 * Mirrors api/v1/schemas/backtest.py
 */
import type { DecisionAction, MarketPhaseSummary } from './analysis';

// ============ Request / Response ============

export type BacktestAnalysisPhase = 'premarket' | 'intraday' | 'postmarket' | 'unknown';
export type BacktestPhaseFilter = BacktestAnalysisPhase | 'all';

export interface BacktestRunRequest {
  code?: string;
  force?: boolean;
  evalWindowDays?: number;
  minAgeDays?: number;
  analysisDateFrom?: string;
  analysisDateTo?: string;
  limit?: number;
}

export interface BacktestRunResponse {
  processed: number;
  saved: number;
  completed: number;
  insufficient: number;
  errors: number;
  appliedEvalWindowDays?: number;
  message?: string | null;
  diagnostics?: Record<string, unknown>;
}

// ============ Result Item ============

export interface BacktestResultItem {
  analysisHistoryId: number;
  code: string;
  stockName?: string;
  analysisDate?: string;
  evalWindowDays: number;
  engineVersion: string;
  evalStatus: string;
  evaluatedAt?: string;
  operationAdvice?: string;
  action?: DecisionAction | null;
  actionLabel?: string | null;
  trendPrediction?: string;
  marketPhase?: string | null;
  marketPhaseSummary?: MarketPhaseSummary | null;
  positionRecommendation?: string;
  startPrice?: number;
  endClose?: number;
  maxHigh?: number;
  minLow?: number;
  stockReturnPct?: number;
  actualReturnPct?: number;
  actualMovement?: string;
  directionExpected?: string;
  directionCorrect?: boolean;
  outcome?: string;
  stopLoss?: number;
  takeProfit?: number;
  hitStopLoss?: boolean;
  hitTakeProfit?: boolean;
  firstHit?: string;
  firstHitDate?: string;
  firstHitTradingDays?: number;
  simulatedEntryPrice?: number;
  simulatedExitPrice?: number;
  simulatedExitReason?: string;
  simulatedReturnPct?: number;
  entryDate?: string | null;
  priceBasis?: string | null;
  adjustmentReason?: string | null;
  simulatedNetReturnPct?: number | null;
  /** 分流狀態：completed／pending（未到期）／insufficient_data 等；舊後端沒有這欄就看 evalStatus。 */
  maturityStatus?: string | null;
  /** 未到期時，評估窗口最晚走完的日期。 */
  maturesBy?: string | null;
  market?: string | null;
}

export interface BacktestResultsResponse {
  total: number;
  page: number;
  limit: number;
  items: BacktestResultItem[];
  /** 各分流的筆數，不受 status 參數影響。 */
  statusCounts?: Record<string, number>;
}

// ============ Performance Metrics ============

export interface PerformanceMetrics {
  scope: string;
  code?: string;
  evalWindowDays: number;
  engineVersion: string;
  computedAt?: string;

  totalEvaluations: number;
  completedCount: number;
  insufficientCount: number;
  longCount: number;
  cashCount: number;
  winCount: number;
  lossCount: number;
  neutralCount: number;

  directionAccuracyPct?: number;
  winRatePct?: number;
  neutralRatePct?: number;
  avgStockReturnPct?: number;
  avgSimulatedReturnPct?: number;

  stopLossTriggerRate?: number;
  takeProfitTriggerRate?: number;
  ambiguousRate?: number;
  avgDaysToFirstHit?: number;

  adviceBreakdown: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
}

// ============ Series ============

export type BacktestStatusFilter = 'completed' | 'pending' | 'insufficient_data' | 'error' | 'unable';
export type BacktestSort = 'completed_first' | 'date_desc' | 'date_asc' | 'return_desc' | 'return_asc';

export interface BacktestSeriesPoint {
  date: string;
  analysisHistoryId: number;
  code: string;
  returnPct: number;
  cumulativeReturnPct: number;
  stockReturnPct?: number | null;
  cumulativeStockReturnPct?: number | null;
}

export interface BacktestMonthlyWinRate {
  month: string;
  completed: number;
  win: number;
  loss: number;
  neutral: number;
  /** 沒有勝負的月份是 null，不是 0%。 */
  winRatePct?: number | null;
}

export interface BacktestSeriesResponse {
  chartTitle?: string;
  evalWindowDays?: number | null;
  truncated: boolean;
  updatedAt?: string | null;
  points: BacktestSeriesPoint[];
  monthly: BacktestMonthlyWinRate[];
}
