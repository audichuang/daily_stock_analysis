import { beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { MAX_QUOTE_BATCH, stocksApi } from '../stocks';

vi.mock('../index', () => ({
  default: { get: vi.fn() },
}));

const respondWithEcho = () => {
  vi.mocked(apiClient.get).mockImplementation(async (_url, config) => {
    const codes = String((config?.params as { codes: string }).codes).split(',');
    return { data: { items: codes.map((code) => ({ stock_code: code, quote: { stock_code: code, current_price: 1 } })) } };
  });
};

describe('stocksApi.getQuotesBatched', () => {
  beforeEach(() => {
    vi.mocked(apiClient.get).mockReset();
  });

  it('splits requests at the backend batch limit', async () => {
    respondWithEcho();
    const codes = Array.from({ length: MAX_QUOTE_BATCH * 2 + 1 }, (_, index) => `C${index}`);

    const items = await stocksApi.getQuotesBatched(codes);

    const sizes = vi.mocked(apiClient.get).mock.calls.map(([, config]) => (
      String((config?.params as { codes: string }).codes).split(',').length
    ));
    expect(sizes).toEqual([MAX_QUOTE_BATCH, MAX_QUOTE_BATCH, 1]);
    expect(items).toHaveLength(codes.length);
  });

  it('does not exceed the limit with duplicates, and makes no request without codes', async () => {
    respondWithEcho();

    await stocksApi.getQuotesBatched(Array.from({ length: MAX_QUOTE_BATCH + 10 }, () => '2330.TW'));
    expect(apiClient.get).toHaveBeenCalledTimes(1);

    vi.mocked(apiClient.get).mockClear();
    expect(await stocksApi.getQuotesBatched([])).toEqual([]);
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it('keeps the other batches when one batch fails', async () => {
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce(new Error('boom'))
      .mockImplementationOnce(async (_url, config) => {
        const code = String((config?.params as { codes: string }).codes);
        return { data: { items: [{ stock_code: code, quote: { stock_code: code, current_price: 9 } }] } };
      });
    const codes = Array.from({ length: MAX_QUOTE_BATCH + 1 }, (_, index) => `C${index}`);

    const items = await stocksApi.getQuotesBatched(codes);

    expect(items).toHaveLength(codes.length);
    expect(items.find((item) => item.stockCode === 'C0')?.quote).toBeNull();
    expect(items.at(-1)?.quote?.currentPrice).toBe(9);
  });
});
