import type { DecisionAction } from './analysis';

export type ResearchQualityLevel = 'good' | 'usable' | 'limited' | 'poor' | 'unknown';
export type ResearchDirection = 'bullish' | 'bearish' | 'neutral' | 'unknown';
export type ResearchEvidenceFreshness = 'fresh' | 'stale' | 'unknown';
export type ResearchInvalidationCategory =
  | 'price'
  | 'volume'
  | 'evidence'
  | 'market'
  | 'time'
  | 'data_quality'
  | 'manual';
export type ResearchInvalidationSeverity = 'watch' | 'warning' | 'critical';
export type ResearchInvalidationDirection = 'below' | 'above';
export type ResearchInvalidationStatus = 'pending' | 'triggered' | 'review';
export type ResearchSourceStatus = 'ok' | 'no_data' | 'fetch_failed' | 'timeout' | 'not_configured' | 'not_supported';

export interface ResearchSubject {
  stockCode: string;
  stockName?: string | null;
  market?: string | null;
  entityRef?: string | null;
}

export interface ResearchThesis {
  direction: ResearchDirection;
  summary: string;
  confidence?: number | null;
  score?: number | null;
  horizon?: string | null;
  action?: DecisionAction | null;
  actionLabel?: string | null;
  reasons: string[];
  risks: string[];
  oneSentence?: string | null;
  timeSensitivity?: string | null;
  positionAdvice?: { noPosition?: string | null; hasPosition?: string | null } | null;
  confidenceLevel?: string | null;
  confidenceReason?: string | null;
  guardrailApplied?: boolean | null;
  guardrailReason?: string | null;
  strongestBullishSignal?: string | null;
  strongestBearishSignal?: string | null;
  watchConditions?: string[] | null;
  entryConditions?: string[] | null;
  exitTriggers?: string[] | null;
  pendingEvents?: string[] | null;
  nextCheckTime?: string | null;
}

export interface ResearchEvidenceItem {
  id: string;
  sourceType: string;
  title: string;
  summary?: string | null;
  source?: string | null;
  freshness: ResearchEvidenceFreshness;
  qualityLevel: ResearchQualityLevel;
  asOf?: string | null;
  url?: string | null;
  metadata: Record<string, unknown>;
  group?: string | null;
  observedAt?: string | null;
  fetchedAt?: string | null;
  windowDays?: number | null;
  complete?: boolean | null;
  countsTowardScore?: boolean | null;
  facts?: Record<string, unknown> | null;
  excerpt?: string | null;
  series?: Array<Record<string, unknown>> | null;
}

export interface ResearchInvalidationCondition {
  id: string;
  category: ResearchInvalidationCategory;
  description: string;
  trigger?: string | null;
  severity: ResearchInvalidationSeverity;
  metric?: string | null;
  threshold?: string | null;
  dueAt?: string | null;
  metadata: Record<string, unknown>;
  direction?: ResearchInvalidationDirection | null;
  status?: ResearchInvalidationStatus;
}

export interface ResearchNextAction {
  action: string;
  label: string;
  reason?: string | null;
  dueAt?: string | null;
  metadata: Record<string, unknown>;
}

export interface ResearchDataQuality {
  level: ResearchQualityLevel;
  overallScore?: number | null;
  sourceCount: number;
  staleCount: number;
  missingBlocks: string[];
  limitations: string[];
}

/** 重大波動事件的事實；triggered 不為 true 時畫面不顯示。 */
export interface ResearchEventGap {
  triggered?: boolean | null;
  eventDate?: string | null;
  changePct?: number | null;
  eventLow?: number | null;
  sessionsSinceEvent?: number | null;
  thresholdPct?: number | null;
  latestClose?: number | null;
  postEventMinClose?: number | null;
  eventLowBroken?: boolean | null;
  newsEvidencePresent?: boolean | null;
  blockedWithoutNews?: boolean | null;
  reason?: string | null;
}

export interface ResearchArtifact {
  schemaVersion: 'research-artifact-v1';
  artifactId: string;
  sourceReportId?: number | null;
  sourceQueryId?: string | null;
  createdAt?: string | null;
  subject: ResearchSubject;
  thesis: ResearchThesis;
  evidence: ResearchEvidenceItem[];
  invalidationConditions: ResearchInvalidationCondition[];
  nextActions: ResearchNextAction[];
  dataQuality: ResearchDataQuality;
  metadata: Record<string, unknown>;
  eventGap?: ResearchEventGap | null;
  sourceStatus?: Record<string, ResearchSourceStatus>;
}
