// 手動鏡像 api/v1/schemas/stocks.py 的 StockFinancialsResponse。金額都是 1 元財報幣別。
export type FinancialMetricKind = 'amount' | 'ratio' | 'per_share';
export type FinancialImportance = 'high' | 'medium' | 'low';
export type CommentaryStatus = 'ready' | 'missing' | 'disabled' | 'failed' | 'not_applicable';

export interface FinancialPeriod {
  key: string;
  label: string;
  fiscalYear?: number | null;
  fiscalQuarter?: number | null;
  periodEnd: string;
  announceDate?: string | null;
  announceDateKind: 'filed' | 'statutory_deadline' | 'unknown';
  filingForm?: string | null;
}

export interface FinancialMetricPoint {
  period: string;
  value: number | null;
  yoyPct: number | null;
  qoqPct: number | null;
  yoyPp: number | null;
  qoqPp: number | null;
  derived: boolean;
}

export interface FinancialMetric {
  key: string;
  label: string;
  kind: FinancialMetricKind;
  unit: string;
  definition: string;
  points: FinancialMetricPoint[];
}

export interface FinancialHighlight {
  metricKey: string;
  period: string;
  importance: FinancialImportance;
  whatHappened: string;
  whyItMatters: string;
  howToRead: string;
}

export interface FinancialCommentary {
  status: CommentaryStatus;
  period?: string | null;
  generatedAt?: string | null;
  model?: string | null;
  headline?: string | null;
  highlights: FinancialHighlight[];
  message?: string | null;
}

export interface MonthlyRevenuePoint {
  month: string;
  revenue: number | null;
  yoyPct: number | null;
  momPct: number | null;
  announceDate?: string | null;
}

export interface StockFinancials {
  stockCode: string;
  market?: 'tw' | 'us' | null;
  status: 'ok' | 'no_data' | 'not_applicable' | 'unsupported' | 'unavailable';
  statusReason?: string | null;
  stockName?: string | null;
  template: 'general' | 'financial';
  currency?: string | null;
  tradingCurrency?: string | null;
  source?: { id?: string | null; label: string; sourceUnit: string; url?: string | null } | null;
  periods: FinancialPeriod[];
  metrics: FinancialMetric[];
  notApplicable: { key: string; label: string; reason: string }[];
  monthlyRevenue: MonthlyRevenuePoint[];
  ttmRevenueYoyPct?: number | null;
  limitations: string[];
  isStale: boolean;
  commentary: FinancialCommentary;
}
