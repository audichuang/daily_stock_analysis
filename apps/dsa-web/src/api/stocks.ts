import apiClient from './index';
import { toCamelCase } from './utils';
import { attachParsedApiError } from './error';

export type ExtractItem = {
  code?: string | null;
  name?: string | null;
  confidence: string;
};

export type ExtractFromImageResponse = {
  codes: string[];
  items?: ExtractItem[];
  rawText?: string;
};

export type StockQuote = {
  stockCode: string;
  stockName?: string | null;
  currentPrice: number;
  change?: number | null;
  changePercent?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  prevClose?: number | null;
  volume?: number | null;
  amount?: number | null;
  volumeRatio?: number | null;
  amplitude?: number | null;
  // 台股盘中专用（仅 Shioaji 有值，其他源为 null）
  averagePrice?: number | null;
  limitUp?: number | null;
  limitDown?: number | null;
  bestBid?: number | null;
  bestBidVolume?: number | null;
  bestAsk?: number | null;
  bestAskVolume?: number | null;
  dayTrade?: string | null;
  lastTickType?: number | null;
  updateTime?: string | null;
  source?: string | null;
  asOf?: string | null;
  isStale?: boolean | null;
};

export type StockQuoteBatchItem = {
  stockCode: string;
  quote?: StockQuote | null;
  error?: string | null;
};

export type MarketIndex = {
  code: string;
  name: string;
  current: number | null;
  change: number | null;
  changePct: number | null;
  /** 後端取值路徑：`shioaji` 即時快照、`official_close` 本地官方收盤（前一場）；缺省是 yfinance 延遲。 */
  source: string | null;
  asOf: string | null;
};

export type MarketIndexSnapshot = {
  items: MarketIndex[];
  /** 後端 MarketPhase 值：premarket／intraday／lunch_break／closing_auction／postmarket／non_trading／unknown。 */
  marketPhase: string | null;
  marketOpen: boolean | null;
};

type RawIndex = {
  code?: string;
  name?: string;
  current?: number | null;
  change?: number | null;
  change_pct?: number | null;
  source?: string | null;
  as_of?: string | null;
};

// 后端字段为 snake_case，这里转成前端 camelCase
type RawQuote = {
  stock_code: string;
  stock_name?: string | null;
  current_price: number;
  change?: number | null;
  change_percent?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  prev_close?: number | null;
  volume?: number | null;
  amount?: number | null;
  volume_ratio?: number | null;
  amplitude?: number | null;
  average_price?: number | null;
  limit_up?: number | null;
  limit_down?: number | null;
  best_bid?: number | null;
  best_bid_volume?: number | null;
  best_ask?: number | null;
  best_ask_volume?: number | null;
  day_trade?: string | null;
  last_tick_type?: number | null;
  update_time?: string | null;
  source?: string | null;
  as_of?: string | null;
  is_stale?: boolean | null;
};

function toQuote(raw: RawQuote): StockQuote {
  return {
    stockCode: raw.stock_code,
    stockName: raw.stock_name,
    currentPrice: raw.current_price,
    change: raw.change,
    changePercent: raw.change_percent,
    open: raw.open,
    high: raw.high,
    low: raw.low,
    prevClose: raw.prev_close,
    volume: raw.volume,
    amount: raw.amount,
    volumeRatio: raw.volume_ratio,
    amplitude: raw.amplitude,
    averagePrice: raw.average_price,
    limitUp: raw.limit_up,
    limitDown: raw.limit_down,
    bestBid: raw.best_bid,
    bestBidVolume: raw.best_bid_volume,
    bestAsk: raw.best_ask,
    bestAskVolume: raw.best_ask_volume,
    dayTrade: raw.day_trade,
    lastTickType: raw.last_tick_type,
    updateTime: raw.update_time,
    source: raw.source,
    asOf: raw.as_of,
    isStale: raw.is_stale,
  };
}

export const stocksApi = {
  async extractFromImage(file: File): Promise<ExtractFromImageResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
    const response = await apiClient.post(
      '/api/v1/stocks/extract-from-image',
      formData,
      {
        headers,
        timeout: 60000, // Vision API can be slow; 60s
      },
    );

    const data = response.data as { codes?: string[]; items?: ExtractItem[]; raw_text?: string };
    return {
      codes: data.codes ?? [],
      items: data.items,
      rawText: data.raw_text,
    };
  },

  async parseImport(file?: File, text?: string): Promise<ExtractFromImageResponse> {
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
      const response = await apiClient.post('/api/v1/stocks/parse-import', formData, { headers });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    if (text) {
      const response = await apiClient.post('/api/v1/stocks/parse-import', { text });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    throw new Error('请提供文件或粘贴文本');
  },

  async getQuotes(codes: string[]): Promise<StockQuoteBatchItem[]> {
    if (codes.length === 0) return [];
    const response = await apiClient.get('/api/v1/stocks/quotes', {
      params: { codes: codes.join(',') },
    });
    const data = response.data as { items?: Array<{ stock_code: string; quote?: RawQuote | null; error?: string | null }> };
    return (data.items ?? []).map((item) => ({
      stockCode: item.stock_code,
      quote: item.quote ? toQuote(item.quote) : null,
      error: item.error,
    }));
  },

  /** 看板輪詢閘門：各市場是否在盤中（含前後緩衝）；後端依交易所日曆判斷休市，未知市場回 true。 */
  async getMarketStatus(markets: string[]): Promise<Record<string, boolean>> {
    const response = await apiClient.get('/api/v1/stocks/market-status', {
      params: { markets: markets.join(',') },
    });
    return (response.data as { markets?: Record<string, boolean> }).markets ?? {};
  },

  async getIndices(region = 'tw'): Promise<MarketIndex[]> {
    const response = await apiClient.get('/api/v1/stocks/indices', { params: { region } });
    const data = response.data as { items?: RawIndex[] };
    return (data.items ?? []).map((r) => ({
      code: r.code ?? '',
      name: r.name ?? '',
      current: r.current ?? null,
      change: r.change ?? null,
      changePct: r.change_pct ?? null,
      source: r.source ?? null,
      asOf: r.as_of ?? null,
    }));
  },

  /** 全站狀態列用：指數之外連同後端判定的市場時段一起回傳（getIndices 只回列表）。 */
  async getIndicesSnapshot(region: string): Promise<MarketIndexSnapshot> {
    const response = await apiClient.get('/api/v1/stocks/indices', { params: { region } });
    const data = response.data as { items?: RawIndex[]; market_phase?: string | null; market_open?: boolean | null };
    return {
      items: (data.items ?? []).map((r) => ({
        code: r.code ?? '',
        name: r.name ?? '',
        current: r.current ?? null,
        change: r.change ?? null,
        changePct: r.change_pct ?? null,
        source: r.source ?? null,
        asOf: r.as_of ?? null,
      })),
      marketPhase: data.market_phase ?? null,
      marketOpen: data.market_open ?? null,
    };
  },

  /** 看板用台股四維度摘要（不查分點、不呼叫 LLM）；非台股或失敗的單檔回 summary=null。 */
  async getDossierSummaries(codes: string[]): Promise<DossierSummaryBatch> {
    if (codes.length === 0) return { items: [], levelAlertsEnabled: false };
    const response = await apiClient.get('/api/v1/stocks/dossier-summary', { params: { codes: codes.join(',') } });
    const data = toCamelCase<{ items?: DossierSummaryItem[]; levelAlertsEnabled?: boolean }>(response.data);
    return { items: data.items ?? [], levelAlertsEnabled: Boolean(data.levelAlertsEnabled) };
  },

  /** 把看板顯示的最近支撐／壓力建成價位警報（會先刪這檔既有的價位警報）。功能預設關閉。 */
  async createLevelAlerts(code: string, picks: { support?: DossierLevel | null; resistance?: DossierLevel | null }): Promise<number> {
    const response = await apiClient.post(`/api/v1/stocks/${encodeURIComponent(code)}/level-alerts`, {
      support: picks.support ?? null,
      resistance: picks.resistance ?? null,
    });
    return ((response.data as { rules?: unknown[] }).rules ?? []).length;
  },

  /** 台股四維度分析報告（伺服器渲染的完整 HTML 文件）。narrative=true 會等 LLM 解讀，約 20~60 秒。 */
  async getDossierHtml(code: string, options: { narrative?: boolean; theme?: 'light' | 'dark' } = {}): Promise<string> {
    try {
      const response = await apiClient.get(`/api/v1/stocks/${encodeURIComponent(code)}/dossier`, {
        params: { narrative: options.narrative ?? false, theme: options.theme },
        responseType: 'text',
        timeout: 180000,
      });
      return String(response.data ?? '');
    } catch (err) {
      // responseType 'text' 讓錯誤回應也變成字串；轉回 JSON 再重新解析，畫面才顯示 detail 而不是整串大括號
      const res = (err as { response?: { data?: unknown } } | null)?.response;
      if (res && typeof res.data === 'string') {
        try {
          res.data = JSON.parse(res.data);
          attachParsedApiError(err);
        } catch {
          /* 不是 JSON（例如代理回的 HTML），保留原樣 */
        }
      }
      throw err;
    }
  },

  async getTrend(code: string, range: TrendRange): Promise<TrendPoint[]> {
    const response = await apiClient.get(`/api/v1/stocks/${encodeURIComponent(code)}/trend`, {
      params: { range },
    });
    const data = response.data as { points?: Array<{ t: string; price: number }> };
    return (data.points ?? []).map((p) => ({ t: p.t, price: p.price }));
  },
};

export type TrendRange = 'day' | 'month' | 'year';
export type TrendPoint = { t: string; price: number };

export type DossierBias = 'bull' | 'bear' | null;
export type DossierLevel = {
  label: string;
  low: number;
  high: number;
  kind: 'bsl' | 'ssl' | 'ob' | 'fvg' | 'ote';
  bias: DossierBias;
};
export type DossierTone = 'pos' | 'neg' | 'neu' | 'watch';
export type DossierSummary = {
  name?: string | null;
  asOf: string;
  close: number | null;
  structure: { kind: string; bias: 'bull' | 'bear'; date: string; level: number } | null;
  levels: DossierLevel[];
  changes: Array<{ kind: string; tone: DossierTone; text: string }>;
  verdicts: Record<string, { badge?: string | null; tone?: DossierTone | null }> | null;
  /** 資料基準日之後有除權息／分割／減資：價位還是舊基準，不能拿即時價量距離。舊後端沒有這欄。 */
  adjustedAfter?: boolean;
};
export type DossierSummaryItem = { stockCode: string; summary: DossierSummary | null; error?: string | null };
export type DossierSummaryBatch = { items: DossierSummaryItem[]; levelAlertsEnabled: boolean };
