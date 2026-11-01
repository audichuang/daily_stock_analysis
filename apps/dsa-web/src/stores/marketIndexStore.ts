import { create } from 'zustand';
import { stocksApi, type MarketIndex } from '../api/stocks';

export type MarketIndexRegion = 'tw' | 'us';

const FRESH_MS = 60_000; // 與後端 /stocks/indices 的 60 秒快取對齊，再短也拿不到新值

interface MarketIndexState {
  byRegion: Partial<Record<MarketIndexRegion, MarketIndex[]>>;
  fetchedAt: Partial<Record<MarketIndexRegion, number>>;
  /** 60 秒內抓過的市場不重抓；force 給手動重新整理用。失敗保留舊值，指數是輔助資料。 */
  load: (regions?: MarketIndexRegion[], options?: { force?: boolean }) => Promise<void>;
}

/** 大盤指數的共用來源，首頁總覽、盯盤、全站狀態列都讀這裡，不各抓一份。 */
export const useMarketIndexStore = create<MarketIndexState>((set, get) => ({
  byRegion: {},
  fetchedAt: {},
  load: async (regions = ['tw', 'us'], options = {}) => {
    await Promise.all(
      regions.map(async (region) => {
        const previous = get().fetchedAt[region];
        const now = Date.now();
        if (!options.force && previous !== undefined && now - previous < FRESH_MS) return;
        set((state) => ({ fetchedAt: { ...state.fetchedAt, [region]: now } })); // 請求中也算抓過，避免重複送出
        try {
          const items = await stocksApi.getIndices(region);
          set((state) => ({ byRegion: { ...state.byRegion, [region]: items } }));
        } catch {
          set((state) => ({ fetchedAt: { ...state.fetchedAt, [region]: previous } }));
        }
      }),
    );
  },
}));
