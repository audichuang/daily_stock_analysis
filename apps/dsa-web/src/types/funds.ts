// 境內基金：與 api/v1/schemas/funds.py 手動同步（toCamelCase 轉換後的鍵名）

export interface FundSearchItem {
  fundId: string;
  name: string;
  company?: string | null;
  isin?: string | null;
  typeCode?: string | null;
  typeName?: string | null;
  currency?: string | null;
  nav?: number | null;
  navDate?: string | null;
}

export interface FundSearchResponse {
  items: FundSearchItem[];
}

/** 各期間報酬率（%），未含配息；期間不足為 null */
export interface FundReturns {
  w1: number | null;
  m1: number | null;
  m3: number | null;
  m6: number | null;
  ytd: number | null;
  y1: number | null;
  y3: number | null;
  y5: number | null;
}

/** 淨值走勢區間：後端以報酬卡同一個基準點起算。 */
export type FundNavPeriod = keyof FundReturns;

export interface FundRisk {
  maxDrawdown: number | null;
  volatility: number | null;
}

export interface FundDetail {
  fundId: string;
  name: string;
  company?: string | null;
  isin?: string | null;
  sitcaCode?: string | null;
  typeCode?: string | null;
  typeName?: string | null;
  investArea?: string | null;
  currency?: string | null;
  inceptionDate?: string | null;
  aum?: number | null;
  aumCurrency?: string | null;
  aumDate?: string | null;
  dividendPolicy?: string | null;
  nav: number | null;
  navDate: string | null;
  navChange: number | null;
  navChangePct: number | null;
  navSource: string | null;
  isStale: boolean;
  historyStart: string | null;
  historyPoints: number;
  historyError: string | null;
  returns: FundReturns;
  risk: FundRisk;
}

export interface FundNavPoint {
  date: string;
  nav: number;
}

export interface FundBenchmarkPoint {
  date: string;
  close: number;
}

export interface FundNavHistoryResponse {
  fundId: string;
  points: FundNavPoint[];
  benchmark?: { indexId: string; points: FundBenchmarkPoint[] } | null;
  benchmarkError?: string | null;
}

export interface FundTopHolding {
  name: string | null;
  sector: string | null;
  weight: number | null;
  country: string | null;
  /** 名稱唯一對到帳本持股才有；對不到就不標。 */
  ledgerSymbol?: string | null;
}

export interface FundOverlapItem {
  symbol: string;
  name?: string | null;
  weight?: number | null;
}

export interface FundTopHoldingsResponse {
  fundId: string;
  items: FundTopHolding[];
  error: 'source_unavailable' | 'not_mapped' | null;
  /** 持股資料月份 YYYY-MM；來源沒給為 null。 */
  asOfMonth?: string | null;
  overlap?: FundOverlapItem[];
}

export interface FundHoldingItem {
  id: number;
  platform: string;
  fundId: string;
  fundName: string;
  units: number;
  costTotal: number;
  currency: string;
  asOf: string;
  note?: string | null;
  nav: number | null;
  navDate: string | null;
  isStale: boolean;
  marketValue: number | null;
  pnl: number | null;
  pnlPct: number | null;
  navChangePct?: number | null;
  dayPnl?: number | null;
}

export interface FundHoldingTotal {
  currency: string;
  costTotal: number;
  marketValue: number | null;
  pnl: number | null;
  pnlPct: number | null;
  /** 有一檔算不出就是 null。 */
  dayPnl?: number | null;
}

export interface FundHoldingListResponse {
  items: FundHoldingItem[];
  totals: FundHoldingTotal[];
  navError: string | null;
}

export interface FundHoldingCreateRequest {
  fundId: string;
  units: number;
  costTotal: number;
  asOf: string;
  platform?: string;
  note?: string;
}

export type FundHoldingUpdateRequest = Partial<Omit<FundHoldingCreateRequest, 'fundId'>>;
