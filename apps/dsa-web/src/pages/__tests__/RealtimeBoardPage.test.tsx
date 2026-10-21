import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import RealtimeBoardPage from '../RealtimeBoardPage';

const { getWatchlist, getSnapshot, listHoldings, getQuotes, getIndices } = vi.hoisted(() => ({
  getWatchlist: vi.fn(),
  getSnapshot: vi.fn(),
  listHoldings: vi.fn(),
  getQuotes: vi.fn(),
  getIndices: vi.fn(),
}));

vi.mock('../../api/systemConfig', () => ({ systemConfigApi: { getWatchlist } }));
vi.mock('../../api/portfolio', () => ({ portfolioApi: { getSnapshot } }));
vi.mock('../../api/funds', () => ({ fundsApi: { listHoldings } }));
vi.mock('../../api/stocks', () => ({ stocksApi: { getQuotes, getIndices, getTrend: vi.fn().mockResolvedValue([]) } }));
vi.mock('recharts', () => {
  const Stub = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return { LineChart: Stub, Line: Stub, ResponsiveContainer: Stub, Tooltip: Stub, XAxis: Stub, YAxis: Stub };
});

const position = (symbol: string, quantity: number, avgCost: number, currency = 'TWD') => ({
  symbol, quantity, avgCost, currency, market: 'tw', totalCost: 0, lastPrice: 0, marketValueBase: 0,
  unrealizedPnlBase: 0, valuationCurrency: currency,
});

const snapshot = {
  accounts: [
    // 3481 已出清（股數 0），不該出現在持股
    { accountName: '國泰台股', positions: [position('2887.TW', 1000, 10), position('2330.TW', 10, 900), position('3481.TW', 0, 50)] },
    { accountName: '美好台股', positions: [position('2330.TW', 30, 1100)] },
    { accountName: '永豐複委託', positions: [position('NVDA', 2, 100, 'USD')] },
  ],
};

const quote = (code: string, price: number) => ({
  stockCode: code,
  quote: { stockCode: code, stockName: code, currentPrice: price, changePercent: 1, source: 'shioaji', isStale: false },
});

function renderPage() {
  return render(
    <UiLanguageProvider>
      <MemoryRouter>
        <RealtimeBoardPage />
      </MemoryRouter>
    </UiLanguageProvider>,
  );
}

const rowCodes = () => screen.getAllByRole('row').slice(1).map((r) => r.querySelector('td.font-mono')?.firstChild?.textContent);

describe('RealtimeBoardPage scope', () => {
  beforeEach(() => {
    window.localStorage.clear();
    getWatchlist.mockResolvedValue(['2330.TW', '2454.TW']);
    getSnapshot.mockResolvedValue(snapshot);
    listHoldings.mockResolvedValue({
      items: [{ id: 1, fundId: '18480065', fundName: '安聯台灣科技基金', nav: 783.21, navDate: '2026-10-21', isStale: false, pnlPct: 98.57 }],
      totals: [], navError: null,
    });
    getIndices.mockResolvedValue([]);
    getQuotes.mockImplementation((codes: string[]) =>
      Promise.resolve(codes.map((c) => quote(c, c === '2330.TW' ? 1000 : c === '2887.TW' ? 40 : 200))),
    );
  });

  it('shows watchlist plus every account holding by default, without duplicates', async () => {
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['2330.TW', '2454.TW', '2887.TW', 'NVDA']));
    expect(getSnapshot).toHaveBeenCalledWith({ includeRealtime: false });
  });

  it('merges the same symbol across accounts with a share-weighted cost', async () => {
    renderPage();
    const row = (await screen.findAllByRole('row')).find((r) => r.textContent?.startsWith('2330.TW'))!;
    // 10 股 @900 + 30 股 @1100 → 40 股、均價 1050；現價 1000 → −2,000
    expect(within(row).getByText('40')).toBeInTheDocument();
    await waitFor(() => expect(row.textContent).toContain('-2,000 TWD'));
  });

  it('holdings scope hides watch-only codes and is remembered', async () => {
    renderPage();
    await screen.findByText('2454.TW');
    fireEvent.click(screen.getByRole('button', { name: 'Holdings' }));
    await waitFor(() => expect(rowCodes()).toEqual(['2330.TW', '2887.TW', 'NVDA']));
    expect(window.localStorage.getItem('dsa.board.scope')).toBe('holdings');
  });

  it('keeps the watchlist when the ledger fails, and says so', async () => {
    getSnapshot.mockRejectedValue(new Error('boom'));
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['2330.TW', '2454.TW']));
    expect(screen.getByText('Holdings unavailable; showing watchlist only')).toBeInTheDocument();
  });

  it('shows fund holdings outside the watchlist scope only', async () => {
    renderPage();
    expect(await screen.findByText('安聯台灣科技基金')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Watchlist' }));
    await waitFor(() => expect(screen.queryByText('安聯台灣科技基金')).not.toBeInTheDocument());
  });
});
