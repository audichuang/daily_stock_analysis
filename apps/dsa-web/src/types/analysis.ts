/**
 * Analysis-related type definitions.
 * Aligned with the API schema.
 */

import type { ResearchArtifact } from './researchArtifact';

// ============ Request Types ============

export type StockReportType = 'simple' | 'detailed' | 'full' | 'brief';
export type ReportType = StockReportType | 'market_review';
export type AnalysisPhase = 'auto' | 'premarket' | 'intraday' | 'postmarket';
export type MarketReviewRegion = 'cn' | 'hk' | 'us' | 'tw' | 'jp' | 'kr';

export interface AnalysisRequest {
  stockCode?: string;
  stockCodes?: string[];
  reportType?: StockReportType;
  forceRefresh?: boolean;
  asyncMode?: boolean;
  analysisPhase?: AnalysisPhase;
  stockName?: string;
  originalQuery?: string;
  selectionSource?: 'manual' | 'autocomplete' | 'import' | 'image';
  notify?: boolean;
  skills?: string[];
  reportLanguage?: ReportLanguage;
}

export interface MarketReviewRequest {
  sendNotification?: boolean;
  reportLanguage?: ReportLanguage;
  regions?: readonly MarketReviewRegion[];
}

export interface MarketReviewAccepted {
  status: 'accepted';
  message: string;
  sendNotification: boolean;
  region: string;
  traceId?: string;
  taskId?: string;
}

export interface MarketReviewDefaultRegion {
  defaultRegion: string;
  regions: string[];
}

// ============ Report Types ============

export type ReportLanguage = 'zh' | 'zh-TW' | 'en' | 'ko';

export type MarketPhaseValue =
  | 'premarket'
  | 'intraday'
  | 'lunch_break'
  | 'closing_auction'
  | 'postmarket'
  | 'non_trading'
  | 'unknown';

export interface MarketPhaseSummary {
  market?: string | null;
  phase: MarketPhaseValue;
  marketLocalTime?: string | null;
  sessionDate?: string | null;
  effectiveDailyBarDate?: string | null;
  isTradingDay?: boolean | null;
  isMarketOpenNow?: boolean | null;
  isPartialBar?: boolean | null;
  minutesToOpen?: number | null;
  minutesToClose?: number | null;
  triggerSource?: string | null;
  analysisIntent?: string | null;
  warnings: string[];
}

/** Report metadata */
export interface ReportMeta {
  id?: number;  // Analysis history record ID, present for persisted reports
  queryId: string;
  stockCode: string;
  stockName: string;
  reportType: ReportType;
  reportLanguage?: ReportLanguage;
  createdAt: string;
  currentPrice?: number;
  changePct?: number;
  modelUsed?: string;  // 历史元数据快照，仅用于展示，不用于运行时模型选择
  marketPhaseSummary?: MarketPhaseSummary | null;
  assetType?: 'stock' | 'index';  // 后端权威资产类型；index 用于隐藏 stock-only 自选操作
  /** 現價所屬場次（YYYY-MM-DD）；抓取時間不算資料日。 */
  priceDate?: string | null;
  priceFetchedAt?: string | null;
  currency?: string | null;
  changeAmount?: number | null;
  previousReport?: ReportPreviousSummary | null;
  /** 目前是否持有；null 是無法判定，不等於未持有。 */
  held?: boolean | null;
}

/** 同一檔的前一份報告摘要 */
export interface ReportPreviousSummary {
  id?: number | null;
  action?: DecisionAction | null;
  score?: number | null;
  createdAt?: string | null;
  stopLoss?: number | null;
}

/** 分持股狀態的建議 */
export interface ReportPositionAdvice {
  noPosition?: string | null;
  hasPosition?: string | null;
}

/** Sentiment label */
export type SentimentLabel =
  | '极度悲观'
  | '悲观'
  | '中性'
  | '乐观'
  | '极度乐观'
  | '極度悲觀'
  | '悲觀'
  | '樂觀'
  | '極度樂觀'
  | 'Very Bearish'
  | 'Bearish'
  | 'Neutral'
  | 'Bullish'
  | 'Very Bullish'
  | '매우 비관'
  | '비관'
  | '중립'
  | '낙관'
  | '매우 낙관';

export type DecisionAction = 'buy' | 'add' | 'hold' | 'reduce' | 'sell' | 'watch' | 'avoid' | 'alert';

/** Report summary section */
export interface ReportSummary {
  analysisSummary: string;
  operationAdvice: string;
  action?: DecisionAction | null;
  actionLabel?: string | null;
  trendPrediction: string;
  sentimentScore: number;
  sentimentLabel?: SentimentLabel;
  oneSentence?: string | null;
  timeSensitivity?: string | null;
  positionAdvice?: ReportPositionAdvice | null;
  confidenceLevel?: string | null;
  confidenceReason?: string | null;
  guardrailApplied?: boolean | null;
  guardrailReason?: string | null;
  /** 護欄介入前模型原本的一句話（後端 B02）。 */
  modelOneSentence?: string | null;
  /** 護欄介入前模型原本的分持股建議（後端 B02）。 */
  modelPositionAdvice?: { noPosition?: string | null; hasPosition?: string | null } | null;
  /** 護欄類型：資料缺而降級，或市場邏輯調整（後端 B02）。 */
  guardrailKind?: 'data_unavailable' | 'market_logic' | null;
  strongestBullishSignal?: string | null;
  strongestBearishSignal?: string | null;
  phaseWatchConditions?: string[] | null;
  entryConditions?: string[] | null;
  exitTriggers?: string[] | null;
  pendingEvents?: string[] | null;
  nextCheckTime?: string | null;
}

export interface SniperPrices {
  idealBuy?: number | null;
  secondaryBuy?: number | null;
  stopLoss?: number | null;
  takeProfit?: number | null;
}

/** Strategy section */
export interface ReportStrategy {
  sniperPrices?: SniperPrices | null;
  idealBuy?: string;
  secondaryBuy?: string;
  stopLoss?: string;
  takeProfit?: string;
  /** structured＝模型給的數字；legacy＝舊報告由文字解析，不拿來算距現價。 */
  sniperPricesSource?: 'structured' | 'legacy' | null;
}

export interface RelatedBoard {
  name: string;
  code?: string;
  type?: string;
}

export interface SectorRankingItem {
  name: string;
  code?: string;
  changePct?: number;
  source?: string;
  updatedAt?: string;
}

export interface SectorRankings {
  top?: SectorRankingItem[];
  bottom?: SectorRankingItem[];
}

export type MarketStructureStatus = 'ok' | 'partial' | 'unknown' | 'not_supported';
export type MarketStructureThemeSource = 'industry' | 'concept' | 'mixed' | 'unknown';
export type MarketStructureThemePhase = 'warming' | 'accelerating' | 'cooling' | 'unknown';
export type MarketStructureStockRole = 'leader' | 'follower' | 'edge' | 'unknown';

export interface MarketStructureSource {
  provider: string;
  dataset: string;
  status: string;
  message?: string | null;
}

export interface MarketStructureDataQuality {
  status: MarketStructureStatus;
  missingFields?: string[];
  sources?: MarketStructureSource[];
  errors?: string[];
}

export interface RankedThemeItem {
  name: string;
  changePct?: number | null;
  rank?: number | null;
  source?: MarketStructureThemeSource;
  code?: string | null;
  updatedAt?: string | null;
}

export interface MarketThemeItem extends RankedThemeItem {
  phase?: MarketStructureThemePhase;
  strengthScore?: number | null;
  reason?: string | null;
}

export interface ThemeBreadth {
  activeCount?: number;
  leadingIndustryCount?: number;
  leadingConceptCount?: number;
  laggingCount?: number;
}

export interface MarketThemeContext {
  schemaVersion: 'market-theme-v1';
  status: MarketStructureStatus;
  market: string;
  tradeDate?: string | null;
  activeThemes?: MarketThemeItem[];
  leadingIndustries?: RankedThemeItem[];
  leadingConcepts?: RankedThemeItem[];
  laggingThemes?: RankedThemeItem[];
  themeBreadth?: ThemeBreadth;
  dataQuality?: MarketStructureDataQuality;
}

export interface StockBoardPosition {
  name: string;
  type?: string | null;
  code?: string | null;
  rank?: number | null;
  changePct?: number | null;
  source?: MarketStructureThemeSource;
}

export interface PrimaryTheme {
  name: string;
  source?: MarketStructureThemeSource;
  phase?: MarketStructureThemePhase;
  rank?: number | null;
  changePct?: number | null;
}

export interface MarketStructureRiskTag {
  code: string;
  message: string;
}

export interface StockMarketPosition {
  schemaVersion: 'stock-market-position-v1';
  status: MarketStructureStatus;
  stockCode: string;
  stockName?: string | null;
  market: string;
  primaryTheme?: PrimaryTheme | null;
  relatedBoards?: StockBoardPosition[];
  stockRole?: MarketStructureStockRole;
  themePhase?: MarketStructureThemePhase;
  riskTags?: MarketStructureRiskTag[];
  missingFields?: string[];
}

export interface MarketStructureContext {
  schemaVersion: 'market-structure-v1';
  status: MarketStructureStatus;
  market: string;
  tradeDate?: string | null;
  marketThemeContext: MarketThemeContext;
  stockMarketPosition: StockMarketPosition;
}

export interface MarketReviewPayloadSection {
  key?: string;
  title: string;
  markdown: string;
}

export interface MarketReviewIndex {
  code: string;
  name: string;
  current?: number;
  change?: number;
  changePct?: number;
  open?: number;
  high?: number;
  low?: number;
  volume?: number;
  amount?: number;
  amplitude?: number;
}

export interface MarketReviewBreadth {
  upCount?: number;
  downCount?: number;
  flatCount?: number;
  limitUpCount?: number;
  limitDownCount?: number;
  totalAmount?: number;
  turnoverUnit?: string;
  /** 三大法人買賣超（僅台股），單位與成交額相同；任一格缺值時後端整組不給。 */
  institutionalNet?: {
    foreignNet?: number;
    trustNet?: number;
    dealerNet?: number;
    totalNet?: number;
  };
}

export type MarketLightStatus = 'green' | 'yellow' | 'red' | 'unavailable';

export interface MarketReviewLight {
  region?: string;
  tradeDate?: string;
  status?: MarketLightStatus | string;
  score?: number;
  label?: string;
  temperatureLabel?: string;
  reasons?: string[];
  guidance?: string;
  dimensions?: Partial<Record<'breadth' | 'index' | 'limit', { score?: number; available?: boolean }>>;
}

export interface MarketReviewIndexTrend {
  asOf?: string;
  series?: Array<{ date: string; close: number }>;
  ma20?: number | null;
  ma60?: number | null;
  distanceMa20Pct?: number | null;
  distanceMa60Pct?: number | null;
}

export interface MarketReviewSectorRank {
  sessionDate?: string;
  source?: string;
  basis?: string;
  items?: Array<{ name: string; changePct: number; turnover?: number; stockCount?: number }>;
}

export interface MarketReviewNextDayPlan {
  stance?: 'offensive' | 'balanced' | 'defensive' | null;
  summary?: string | null;
  focus?: string[];
  risks?: string[];
  keyLevels?: Array<{ label: string; price: number }>;
}

export interface MarketReviewPayload {
  version?: number;
  kind?: 'market_review' | string;
  region?: string;
  language?: ReportLanguage | string;
  title?: string;
  rootTitle?: string;
  generatedAt?: string;
  date?: string;
  marketScope?: string;
  marketLight?: MarketReviewLight;
  /** 鍵是指數代號，但經 toCamelCase 後大小寫已變（TAIEX → taiex），查表要先正規化。 */
  indexTrends?: Record<string, MarketReviewIndexTrend>;
  sectorRank?: MarketReviewSectorRank;
  nextDayPlan?: MarketReviewNextDayPlan;
  breadth?: MarketReviewBreadth;
  indices?: MarketReviewIndex[];
  sectors?: SectorRankings;
  concepts?: SectorRankings;
  news?: Array<Record<string, unknown>>;
  sections?: MarketReviewPayloadSection[];
  markets?: Record<string, MarketReviewPayload>;
  markdownReport?: string;
}

export type AnalysisContextPackBlockStatus =
  | 'available'
  | 'missing'
  | 'not_supported'
  | 'fallback'
  | 'stale'
  | 'estimated'
  | 'partial'
  | 'fetch_failed';

export interface AnalysisContextPackOverviewSubject {
  code: string;
  stockName?: string | null;
  market?: string | null;
}

export interface AnalysisContextPackOverviewBlock {
  /** Recorded context time; may be retrieval time, not market observation time. */
  timestamp?: string | null;
  providerTimestamp?: string | null;
  fetchedAt?: string | null;
  key: string;
  label: string;
  status: AnalysisContextPackBlockStatus;
  source?: string | null;
  warnings: string[];
  missingReasons: string[];
}

export interface AnalysisContextPackOverviewCounts {
  available: number;
  missing: number;
  notSupported: number;
  fallback: number;
  stale: number;
  estimated: number;
  partial: number;
  fetchFailed: number;
}

export interface AnalysisContextPackOverviewMetadata {
  triggerSource?: string | null;
  newsResultCount?: number | null;
}

export type AnalysisContextPackDataQualityLevel = 'good' | 'usable' | 'limited' | 'poor';

export interface AnalysisContextPackOverviewDataQuality {
  overallScore?: number | null;
  level?: AnalysisContextPackDataQualityLevel | null;
  blockScores: Record<string, number>;
  limitations: string[];
}

export interface AnalysisContextPackOverview {
  packVersion: string;
  createdAt?: string | null;
  subject: AnalysisContextPackOverviewSubject;
  blocks: AnalysisContextPackOverviewBlock[];
  counts: AnalysisContextPackOverviewCounts;
  dataQuality?: AnalysisContextPackOverviewDataQuality | null;
  warnings: string[];
  metadata: AnalysisContextPackOverviewMetadata;
}

/** Details section */
export interface ReportDetails {
  newsContent?: string;
  emptyNewsDisclosure?: string;
  rawResult?: Record<string, unknown>;
  contextSnapshot?: Record<string, unknown> & { marketReviewPayload?: MarketReviewPayload };
  analysisContextPackOverview?: AnalysisContextPackOverview | null;
  financialReport?: Record<string, unknown>;
  dividendMetrics?: Record<string, unknown>;
  belongBoards?: RelatedBoard[];
  sectorRankings?: SectorRankings;
  conceptRankings?: SectorRankings;
  marketStructure?: MarketStructureContext | null;
}

export type EventExpectation = 'beat' | 'inline' | 'miss' | 'insufficient_data';

export interface EventOutlookScenario {
  case: 'beat' | 'inline' | 'miss';
  expectedReaction?: string | null;
  actionIfHolding?: string | null;
  actionIfFlat?: string | null;
}

/** 事件展望；附近沒有事件或舊報告時後端回 null */
export interface EventOutlook {
  event?: string | null;
  eventType?: 'earnings' | 'investor_conference' | 'other' | null;
  eventDate?: string | null;
  consensus?: {
    eps?: number | null;
    revenue?: number | null;
    analysts?: number | null;
    epsCurrency?: string | null;
    revenueCurrency?: string | null;
  } | null;
  trackRecord?: string | null;
  revisionTrend?: string | null;
  expectation?: EventExpectation | null;
  confidence?: 'high' | 'medium' | 'low' | null;
  reasoning?: string | null;
  scenarios?: EventOutlookScenario[];
  newsImpact?: string | null;
  verifyAfter?: string | null;
}

/** Full analysis report */
export interface AnalysisReport {
  meta: ReportMeta;
  summary: ReportSummary;
  strategy?: ReportStrategy;
  details?: ReportDetails;
  structuredReport?: ResearchArtifact | null;
  eventOutlook?: EventOutlook | null;
}

// ============ Analysis Result Types ============

export type RunDiagnosticStatus = 'normal' | 'degraded' | 'failed' | 'unknown';

export type RunDiagnosticComponentStatus =
  | 'ok'
  | 'degraded'
  | 'failed'
  | 'unknown'
  | 'not_configured'
  | 'skipped';

export interface RunDiagnosticComponent {
  key: string;
  label: string;
  status: RunDiagnosticComponentStatus;
  message: string;
  details?: Record<string, unknown>;
}

export interface RunDiagnosticSummary {
  traceId?: string;
  taskId?: string;
  queryId?: string;
  stockCode?: string;
  triggerSource?: string;
  status: RunDiagnosticStatus;
  statusLabel: string;
  reason: string;
  components: Record<string, RunDiagnosticComponent>;
  copyText: string;
}

/** Sync analysis response */
export interface AnalysisResult {
  queryId: string;
  traceId?: string;
  stockCode: string;
  stockName: string;
  report: AnalysisReport;
  diagnosticSummary?: RunDiagnosticSummary;
  createdAt: string;
}

/** Async task accepted response */
export interface TaskAccepted {
  taskId: string;
  traceId?: string;
  status: 'pending' | 'processing';
  message?: string;
  analysisPhase?: AnalysisPhase;
}

export interface BatchTaskAcceptedItem {
  taskId: string;
  traceId?: string;
  stockCode: string;
  status: 'pending' | 'processing';
  message?: string;
  analysisPhase?: AnalysisPhase;
  assetType?: 'stock' | 'index';
}

export interface BatchDuplicateTaskItem {
  stockCode: string;
  existingTaskId: string;
  message: string;
}

export interface BatchRejectedTaskItem {
  stockCode: string;
  message: string;
}

export interface BatchTaskAcceptedResponse {
  accepted: BatchTaskAcceptedItem[];
  duplicates: BatchDuplicateTaskItem[];
  rejected?: BatchRejectedTaskItem[];
  message: string;
}

export type AnalyzeAsyncResponse = TaskAccepted | BatchTaskAcceptedResponse;

export type AnalyzeResponse = AnalysisResult | AnalyzeAsyncResponse;

/** Task status */
export interface TaskStatus {
  taskId: string;
  traceId?: string;
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancel_requested' | 'cancelled';
  progress?: number;
  result?: AnalysisResult;
  marketReviewReport?: string;
  marketReviewPayload?: MarketReviewPayload;
  region?: string;
  error?: string;
  stockName?: string;
  originalQuery?: string;
  selectionSource?: string;
  analysisPhase?: AnalysisPhase | null;
  skills?: string[];
}

/** Task details used by task list and SSE events */
export interface TaskInfo {
  taskId: string;
  traceId?: string;
  stockCode: string;
  stockName?: string;
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancel_requested' | 'cancelled';
  progress: number;
  message?: string;
  reportType: string;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  error?: string;
  originalQuery?: string;
  selectionSource?: string;
  analysisPhase?: AnalysisPhase;
  skills?: string[];
  region?: string;
  assetType?: 'stock' | 'index';
}

/** Task list response */
export interface TaskListResponse {
  total: number;
  pending: number;
  processing: number;
  tasks: TaskInfo[];
}

/** Duplicate task error response */
export interface DuplicateTaskError {
  error: 'duplicate_task';
  message: string;
  stockCode: string;
  existingTaskId: string;
}

// ============ History Types ============

/** History item summary */
export interface HistoryItem {
  id: number;  // Record primary key ID, always present for persisted history items
  queryId: string;  // Linked analysis query ID
  stockCode: string;
  stockName?: string;
  reportType?: ReportType;
  region?: string;
  trendPrediction?: string;
  analysisSummary?: string;
  sentimentScore?: number;
  operationAdvice?: string;
  action?: DecisionAction | null;
  actionLabel?: string | null;
  currentPrice?: number;
  changePct?: number;
  volumeRatio?: number;
  turnoverRate?: number;
  modelUsed?: string;  // 历史元数据快照，仅用于列表展示，不影响运行时调用与路由
  marketPhaseSummary?: MarketPhaseSummary | null;
  assetType?: 'stock' | 'index';
  createdAt: string;
}

export type StockHistoryRange = 'all' | '30d' | '90d';

export interface StockHistoryFilters {
  range: StockHistoryRange;
  model: string;
  sort: 'desc' | 'asc';
}

/** History list response */
export interface HistoryListResponse {
  total: number;
  page: number;
  limit: number;
  items: HistoryItem[];
}

/** News item */
export interface NewsIntelItem {
  title: string;
  snippet: string;
  url: string;
  source?: string | null;
  publishedDate?: string | null;
  dimension?: string | null;
  publishedAt?: string | null;
  keyPoint?: string | null;
}

/** News response */
export interface NewsIntelResponse {
  total: number;
  items: NewsIntelItem[];
}

/** History filter parameters */
export interface HistoryFilters {
  stockCode?: string;
  reportType?: ReportType;
  startDate?: string;
  endDate?: string;
}

/** History pagination parameters */
export interface HistoryPagination {
  page: number;
  limit: number;
}

// ============ Stock Bar Types ============

export interface StockBarItem {
  id: number;
  stockCode: string;
  stockName?: string;
  reportType?: string;
  sentimentScore?: number;
  operationAdvice?: string;
  action?: DecisionAction | null;
  actionLabel?: string | null;
  analysisCount: number;
  lastAnalysisTime?: string;
  modelUsed?: string;
  marketPhaseSummary?: MarketPhaseSummary | null;
  assetType?: 'stock' | 'index';
  /** 分析當時的價格，不是現價；現價一律走批次行情。 */
  analysisPrice?: number | null;
  /** 分析當時的漲跌幅(%)。 */
  changePct?: number | null;
}

export interface StockBarResponse {
  total: number;
  items: StockBarItem[];
}

// ============ Error Types ============

export interface ApiError {
  error: string;
  message: string;
  detail?: Record<string, unknown>;
}

// ============ Helper Functions ============

/** Get sentiment label by score */
export const getSentimentLabel = (score: number, language: ReportLanguage = 'zh'): SentimentLabel => {
  if (language === 'en') {
    if (score <= 20) return 'Very Bearish';
    if (score <= 40) return 'Bearish';
    if (score <= 60) return 'Neutral';
    if (score <= 80) return 'Bullish';
    return 'Very Bullish';
  }
  if (language === 'zh-TW') {
    if (score <= 20) return '極度悲觀';
    if (score <= 40) return '悲觀';
    if (score <= 60) return '中性';
    if (score <= 80) return '樂觀';
    return '極度樂觀';
  }
  if (language === 'ko') {
    if (score <= 20) return '매우 비관';
    if (score <= 40) return '비관';
    if (score <= 60) return '중립';
    if (score <= 80) return '낙관';
    return '매우 낙관';
  }
  if (score <= 20) return '极度悲观';
  if (score <= 40) return '悲观';
  if (score <= 60) return '中性';
  if (score <= 80) return '乐观';
  return '极度乐观';
};

/** Get sentiment color by score */
export const getSentimentColor = (score: number): string => {
  if (score <= 20) return '#ef4444'; // red-500
  if (score <= 40) return '#f97316'; // orange-500
  if (score <= 60) return '#eab308'; // yellow-500
  if (score <= 80) return '#22c55e'; // green-500
  return '#10b981'; // emerald-500
};
