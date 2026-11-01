import { create } from 'zustand';
import { stocksApi, type MarketIndexSnapshot } from '../api/stocks';

/** 後端 /stocks/indices 也有 60 秒快取，前端同頻率即可。 */
export const MARKET_INDEX_TTL_MS = 60_000;

type LoadOptions = {
  /** 輪詢用：略過 TTL。掛載與切回分頁不帶，60 秒內不重抓。 */
  force?: boolean;
};

type MarketIndexState = {
  tw: MarketIndexSnapshot | null;
  us: MarketIndexSnapshot | null;
  fetchedAt: number | null;
  load: (options?: LoadOptions) => Promise<void>;
};

let inFlight: Promise<void> | null = null;

/** 全站共用的大盤指數。單一市場失敗保留上一筆，兩邊都失敗才算沒更新。 */
export const useMarketIndexStore = create<MarketIndexState>((set, get) => ({
  tw: null,
  us: null,
  fetchedAt: null,
  load: ({ force = false } = {}) => {
    const { fetchedAt } = get();
    if (!force && fetchedAt !== null && Date.now() - fetchedAt < MARKET_INDEX_TTL_MS) {
      return Promise.resolve();
    }
    if (inFlight) {
      return inFlight;
    }
    inFlight = Promise.allSettled([
      stocksApi.getIndicesSnapshot('tw'),
      stocksApi.getIndicesSnapshot('us'),
    ])
      .then(([tw, us]) => {
        if (tw.status === 'rejected' && us.status === 'rejected') {
          return;
        }
        set((state) => ({
          tw: tw.status === 'fulfilled' ? tw.value : state.tw,
          us: us.status === 'fulfilled' ? us.value : state.us,
          fetchedAt: Date.now(),
        }));
      })
      .finally(() => {
        inFlight = null;
      });
    return inFlight;
  },
}));
