import apiClient from './index';

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
