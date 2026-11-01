import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { stocksApi } from '../../../api/stocks';
import { StockPriceChart } from '../StockPriceChart';

vi.mock('../../../api/stocks', () => ({
  stocksApi: {
    getDailyHistory: vi.fn(),
  },
}));

const bar = { date: '2026-10-30', open: 100, high: 110, low: 95, close: 105, volume: 1000 };

describe('StockPriceChart', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('collapses entirely with no bars and no numbers', async () => {
    vi.mocked(stocksApi.getDailyHistory).mockResolvedValue([]);

    const { container } = render(<StockPriceChart stockCode="2330.TW" />);

    await waitFor(() => expect(stocksApi.getDailyHistory).toHaveBeenCalledWith('2330.TW'));
    expect(container).toBeEmptyDOMElement();
  });

  it('collapses when the history request fails', async () => {
    vi.mocked(stocksApi.getDailyHistory).mockRejectedValue(new Error('boom'));

    const { container } = render(<StockPriceChart stockCode="2330.TW" />);

    await waitFor(() => expect(stocksApi.getDailyHistory).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('offers the three ranges when bars exist', async () => {
    vi.mocked(stocksApi.getDailyHistory).mockResolvedValue([bar]);

    render(<StockPriceChart stockCode="2330.TW" language="zh-TW" />);

    expect(await screen.findByRole('radio', { name: '1月' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: '3月' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: '1年' })).toBeInTheDocument();
  });

  it('reads key numbers from the snapshot and keeps a zero reading', async () => {
    vi.mocked(stocksApi.getDailyHistory).mockResolvedValue([]);

    render(
      <StockPriceChart
        stockCode="2330.TW"
        language="zh-TW"
        contextSnapshot={{
          enhancedContext: {
            today: { open: 100, volume: 2000 },
            realtime: { volumeRatio: 1.25, peRatio: null },
            fundamentalContext: { institution: { status: 'ok', data: { foreignNet: 0, trustNet: -500 } } },
          },
        }}
      />,
    );

    const numbers = await screen.findByTestId('stock-key-numbers');
    expect(numbers).toHaveTextContent('量比1.25');
    expect(numbers).toHaveTextContent('外資0');
    expect(numbers).toHaveTextContent('投信−500');
    // 沒有讀數的格子不顯示，不補 0。
    expect(numbers).not.toHaveTextContent('本益比');
    expect(numbers).not.toHaveTextContent('最高');
  });

  it('ignores institution data whose block is not ok', async () => {
    vi.mocked(stocksApi.getDailyHistory).mockResolvedValue([bar]);

    render(
      <StockPriceChart
        stockCode="AAPL"
        language="zh-TW"
        contextSnapshot={{
          enhancedContext: {
            today: { open: 100 },
            fundamentalContext: { institution: { status: 'not_supported', data: { foreignNet: 5 } } },
          },
        }}
      />,
    );

    const numbers = await screen.findByTestId('stock-key-numbers');
    expect(numbers).not.toHaveTextContent('外資');
  });
});
