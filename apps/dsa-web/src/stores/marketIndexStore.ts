import { create } from 'zustand';
import { stocksApi, type MarketIndex } from '../api/stocks';

/** 60 秒內重複載入直接用快取：總覽、盯盤、狀態列共用同一份，不各打一次。 */
export const MARKET_INDEX_TTL_MS = 60_000;

interface RegionState {
  items: MarketIndex[];
  fetchedAt: number;
  isLoading: boolean;
  failed: boolean;
}

interface MarketIndexState {
  regions: Record<string, RegionState>;
  load: (region: string) => Promise<void>;
  reset: () => void;
}

const inFlight = new Map<string, Promise<void>>();

const EMPTY_REGION: RegionState = { items: [], fetchedAt: 0, isLoading: false, failed: false };

export const useMarketIndexStore = create<MarketIndexState>((set, get) => ({
  regions: {},

  load: (region) => {
    const current = get().regions[region];
    if (current && current.fetchedAt > 0 && !current.failed && Date.now() - current.fetchedAt < MARKET_INDEX_TTL_MS) {
      return Promise.resolve();
    }
    const running = inFlight.get(region);
    if (running) {
      return running;
    }

    const update = (patch: Partial<RegionState>) => set((state) => ({
      regions: { ...state.regions, [region]: { ...(state.regions[region] ?? EMPTY_REGION), ...patch } },
    }));
    update({ isLoading: true });
    const request = stocksApi.getIndices(region)
      .then((items) => update({ items, fetchedAt: Date.now(), isLoading: false, failed: false }))
      // 失敗保留上一次讀數，並讓下一次掛載可以重試。
      .catch(() => update({ isLoading: false, failed: true }))
      .finally(() => {
        inFlight.delete(region);
      });
    inFlight.set(region, request);
    return request;
  },

  reset: () => {
    inFlight.clear();
    set({ regions: {} });
  },
}));
