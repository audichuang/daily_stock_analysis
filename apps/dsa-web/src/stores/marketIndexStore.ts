import { create } from 'zustand';
import { stocksApi, type MarketIndex } from '../api/stocks';

export type MarketIndexRegion = 'tw' | 'us';

/** 60 秒內重複載入直接用快取：總覽、盯盤、狀態列共用同一份，不各打一次。與後端 /stocks/indices 的快取對齊。 */
export const MARKET_INDEX_TTL_MS = 60_000;

export interface MarketIndexRegionState {
  items: MarketIndex[];
  /** 後端 MarketPhase 值，狀態列顯示交易狀態用。 */
  marketPhase: string | null;
  marketOpen: boolean | null;
  fetchedAt: number;
  isLoading: boolean;
  failed: boolean;
}

interface MarketIndexState {
  regions: Partial<Record<MarketIndexRegion, MarketIndexRegionState>>;
  /** force 給輪詢與手動重新整理用，略過 TTL。失敗保留上一次讀數。 */
  load: (target?: MarketIndexRegion | MarketIndexRegion[], options?: { force?: boolean }) => Promise<void>;
  reset: () => void;
}

const inFlight = new Map<MarketIndexRegion, Promise<void>>();

const EMPTY_REGION: MarketIndexRegionState = {
  items: [],
  marketPhase: null,
  marketOpen: null,
  fetchedAt: 0,
  isLoading: false,
  failed: false,
};

export const useMarketIndexStore = create<MarketIndexState>((set, get) => {
  const loadRegion = (region: MarketIndexRegion, force: boolean): Promise<void> => {
    const current = get().regions[region];
    if (!force && current && current.fetchedAt > 0 && !current.failed && Date.now() - current.fetchedAt < MARKET_INDEX_TTL_MS) {
      return Promise.resolve();
    }
    const running = inFlight.get(region);
    if (running) {
      return running;
    }

    const update = (patch: Partial<MarketIndexRegionState>) => set((state) => ({
      regions: { ...state.regions, [region]: { ...(state.regions[region] ?? EMPTY_REGION), ...patch } },
    }));
    update({ isLoading: true });
    const request = stocksApi.getIndicesSnapshot(region)
      .then((snapshot) => update({ ...snapshot, fetchedAt: Date.now(), isLoading: false, failed: false }))
      // 失敗保留上一次讀數，並讓下一次掛載可以重試。
      .catch(() => update({ isLoading: false, failed: true }))
      .finally(() => {
        inFlight.delete(region);
      });
    inFlight.set(region, request);
    return request;
  };

  return {
    regions: {},

    load: async (target = ['tw', 'us'], { force = false } = {}) => {
      const regions = Array.isArray(target) ? target : [target];
      await Promise.all(regions.map((region) => loadRegion(region, force)));
    },

    reset: () => {
      inFlight.clear();
      set({ regions: {} });
    },
  };
});
