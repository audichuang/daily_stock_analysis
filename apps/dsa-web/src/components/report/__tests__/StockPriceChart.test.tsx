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
            fundamentalContext: { institution: { status: 'ok', data: { foreignNet: 0, trustNet: -500000 } } },
          },
        }}
      />,
    );

    const numbers = await screen.findByTestId('stock-key-numbers');
    expect(screen.getByTestId('key-number-volumeRatio')).toHaveTextContent('1.25');
    expect(screen.getByTestId('key-number-foreign')).toHaveTextContent('0 張');
    expect(screen.getByTestId('key-number-trust')).toHaveTextContent('−500 張');
    // 沒有讀數的格子不顯示，不補 0。
    expect(numbers).not.toHaveTextContent('本益比');
    expect(numbers).not.toHaveTextContent('最高');
  });

  it('converts shares to Taiwan lots and compacts large numbers so cells stay on one line', async () => {
    vi.mocked(stocksApi.getDailyHistory).mockResolvedValue([]);

    render(
      <StockPriceChart
        stockCode="1257.TW"
        language="zh-TW"
        currency="TWD"
        contextSnapshot={{
          enhancedContext: {
            // Snapshot units are shares and currency: 36,600 lots, 868.3 億, −8,633 lots.
            today: { volume: 36_600_000, amount: 86_833_096_690 },
            fundamentalContext: { institution: { status: 'ok', data: { foreignNet: -8_632_834, trustNet: 1_854_677 } } },
          },
        }}
      />,
    );

    await screen.findByTestId('stock-key-numbers');
    expect(screen.getByTestId('key-number-volume')).toHaveTextContent(/^3\.66 萬張$/);
    expect(screen.getByTestId('key-number-amount')).toHaveTextContent(/^868\.3 億$/);
    expect(screen.getByTestId('key-number-foreign')).toHaveTextContent(/^−8,633 張$/);
    expect(screen.getByTestId('key-number-trust')).toHaveTextContent(/^1,855 張$/);
    expect(screen.getByTestId('key-number-volume').className).toContain('whitespace-nowrap');
    expect(screen.getByTestId('stock-key-numbers').className).toContain('xl:grid-cols-5');
  });

  it('keeps shares for non-Taiwan codes', async () => {
    vi.mocked(stocksApi.getDailyHistory).mockResolvedValue([]);

    render(
      <StockPriceChart stockCode="GOOG" language="zh-TW" contextSnapshot={{ enhancedContext: { today: { volume: 36_600_000 } } }} />,
    );

    await screen.findByTestId('stock-key-numbers');
    expect(screen.getByTestId('key-number-volume')).toHaveTextContent(/^3,660 萬股$/);
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
