import { beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { QUOTE_BATCH_SIZE, stocksApi } from '../stocks';

vi.mock('../index', () => ({
  default: { get: vi.fn() },
}));

const codesOf = (count: number) => Array.from({ length: count }, (_, index) => `T${index}`);

describe('stocksApi.getQuotesBatched', () => {
  beforeEach(() => {
    vi.mocked(apiClient.get).mockReset();
  });

  it('splits requests at the backend limit so every code gets a quote', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (_url, config) => {
      const codes = String(config?.params?.codes).split(',');
      expect(codes.length).toBeLessThanOrEqual(QUOTE_BATCH_SIZE);
      return { data: { items: codes.map((code) => ({ stock_code: code, quote: null })) } };
    });

    const items = await stocksApi.getQuotesBatched(codesOf(QUOTE_BATCH_SIZE * 2 + 1));

    expect(apiClient.get).toHaveBeenCalledTimes(3);
    expect(items).toHaveLength(QUOTE_BATCH_SIZE * 2 + 1);
  });

  it('keeps the other batches when one batch fails', async () => {
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce(new Error('down'))
      .mockResolvedValueOnce({ data: { items: [{ stock_code: 'T50', quote: null }] } });

    const items = await stocksApi.getQuotesBatched(codesOf(QUOTE_BATCH_SIZE + 1));

    expect(items.map((item) => item.stockCode)).toEqual(['T50']);
  });
});
