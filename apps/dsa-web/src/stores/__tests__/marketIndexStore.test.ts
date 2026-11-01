import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { stocksApi } from '../../api/stocks';
import { MARKET_INDEX_TTL_MS, useMarketIndexStore } from '../marketIndexStore';

vi.mock('../../api/stocks', () => ({
  stocksApi: { getIndicesSnapshot: vi.fn() },
}));

const taiex = { code: 'TAIEX', name: '加權指數', current: 23000, change: 10, changePct: 0.1, source: null, asOf: null };

const snapshot = { items: [taiex], marketPhase: null, marketOpen: null };

describe('marketIndexStore', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(stocksApi.getIndicesSnapshot).mockReset();
    useMarketIndexStore.getState().reset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not refetch within the TTL and refetches after it', async () => {
    vi.mocked(stocksApi.getIndicesSnapshot).mockResolvedValue(snapshot);

    await useMarketIndexStore.getState().load('tw');
    await useMarketIndexStore.getState().load('tw');
    expect(stocksApi.getIndicesSnapshot).toHaveBeenCalledTimes(1);
    expect(useMarketIndexStore.getState().regions.tw?.items).toEqual([taiex]);

    vi.advanceTimersByTime(MARKET_INDEX_TTL_MS + 1);
    await useMarketIndexStore.getState().load('tw');
    expect(stocksApi.getIndicesSnapshot).toHaveBeenCalledTimes(2);
  });

  it('shares one request between concurrent callers', async () => {
    vi.mocked(stocksApi.getIndicesSnapshot).mockResolvedValue(snapshot);

    await Promise.all([useMarketIndexStore.getState().load('tw'), useMarketIndexStore.getState().load('tw')]);

    expect(stocksApi.getIndicesSnapshot).toHaveBeenCalledTimes(1);
  });

  it('keeps the last reading on failure and retries on the next load', async () => {
    vi.mocked(stocksApi.getIndicesSnapshot).mockResolvedValue(snapshot);
    await useMarketIndexStore.getState().load('tw');

    vi.advanceTimersByTime(MARKET_INDEX_TTL_MS + 1);
    vi.mocked(stocksApi.getIndicesSnapshot).mockRejectedValueOnce(new Error('down'));
    await useMarketIndexStore.getState().load('tw');
    expect(useMarketIndexStore.getState().regions.tw).toMatchObject({ items: [taiex], failed: true });

    vi.mocked(stocksApi.getIndicesSnapshot).mockResolvedValueOnce({ ...snapshot, items: [] });
    await useMarketIndexStore.getState().load('tw');
    expect(stocksApi.getIndicesSnapshot).toHaveBeenCalledTimes(3);
  });
});
