import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import RealtimeBoardPage from '../RealtimeBoardPage';

const { getWatchlist, getSnapshot, listHoldings, getQuotes, getIndices, getDossierSummaries } = vi.hoisted(() => ({
  getDossierSummaries: vi.fn(),
  getWatchlist: vi.fn(),
  getSnapshot: vi.fn(),
  listHoldings: vi.fn(),
  getQuotes: vi.fn(),
  getIndices: vi.fn(),
}));

vi.mock('../../api/systemConfig', () => ({ systemConfigApi: { getWatchlist } }));
vi.mock('../../api/portfolio', () => ({ portfolioApi: { getSnapshot } }));
vi.mock('../../api/funds', () => ({ fundsApi: { listHoldings } }));
vi.mock('../../api/stocks', () => ({
  stocksApi: { getQuotes, getIndices, getDossierSummaries, getTrend: vi.fn().mockResolvedValue([]) },
}));
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
    vi.clearAllMocks();
    window.localStorage.clear();
    getWatchlist.mockResolvedValue(['2330.TW', '2454.TW']);
    getSnapshot.mockResolvedValue(snapshot);
    listHoldings.mockResolvedValue({
      items: [{ id: 1, fundId: '18480065', fundName: '安聯台灣科技基金', nav: 783.21, navDate: '2026-10-21', isStale: false, pnlPct: 98.57 }],
      totals: [], navError: null,
    });
    getIndices.mockResolvedValue([]);
    getDossierSummaries.mockResolvedValue({ items: [], levelAlertsEnabled: false });
    getQuotes.mockImplementation((codes: string[]) =>
      Promise.resolve(codes.map((c) => quote(c, c === '2330.TW' ? 1000 : c === '2887.TW' ? 40 : 200))),
    );
  });

  it('shows watchlist plus every account holding by default, without duplicates', async () => {
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['2330.TW', '2454.TW', '2887.TW', 'NVDA']));
    expect(getSnapshot).toHaveBeenCalledWith({ includeRealtime: false });
  });

  it('treats a lowercase watchlist code and the ledger symbol as one row', async () => {
    // STOCK_LIST 是原樣字串（可能小寫），帳本是大寫：同一檔只能一列，且要帶持股標籤與股數
    getWatchlist.mockResolvedValue(['2330.tw']);
    getSnapshot.mockResolvedValue({ accounts: [{ accountName: '國泰台股', positions: [position('2330.TW', 10, 900)] }] });
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['2330.tw']));
    const row = screen.getAllByRole('row')[1];
    expect(within(row).getByText('Held')).toBeInTheDocument();
    expect(within(row).getByText('10')).toBeInTheDocument();
  });

  it('treats a US ticker in another case as the same holding', async () => {
    // normalizeStockCode 對美股原樣回傳不轉大寫：`nvda` 與帳本的 `NVDA` 仍要合成一列
    getWatchlist.mockResolvedValue(['nvda']);
    getSnapshot.mockResolvedValue({ accounts: [{ accountName: '永豐複委託', positions: [position('NVDA', 2, 100, 'USD')] }] });
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['nvda']));
    const row = screen.getAllByRole('row')[1];
    expect(within(row).getByText('Held')).toBeInTheDocument();
    expect(within(row).getByText('2')).toBeInTheDocument();
  });

  it('normalizes non-canonical ledger symbols before merging and matching', async () => {
    // 帳本代碼不一定是正規形式：`2330.tw` 與 `2330.TW` 跨帳戶要合併，且對上自選的 `2330.TW`
    getWatchlist.mockResolvedValue(['2330.TW']);
    getSnapshot.mockResolvedValue({
      accounts: [
        { accountName: '國泰台股', positions: [position('2330.tw', 10, 900)] },
        { accountName: '美好台股', positions: [position('2330.TW', 30, 1100)] },
      ],
    });
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['2330.TW']));
    const row = screen.getAllByRole('row')[1];
    expect(within(row).getByText('Held')).toBeInTheDocument();
    expect(within(row).getByText('40')).toBeInTheDocument();
  });

  it('keeps distinct US tickers apart after case folding', async () => {
    // 反向：轉大寫不能把不同代碼摺成一檔
    getWatchlist.mockResolvedValue(['nvda', 'amd']);
    getSnapshot.mockResolvedValue({ accounts: [{ accountName: '永豐複委託', positions: [position('NVDA', 2, 100, 'USD')] }] });
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['nvda', 'amd']));
    const rows = screen.getAllByRole('row');
    expect(within(rows[1]).getByText('Held')).toBeInTheDocument();
    expect(within(rows[2]).queryByText('Held')).not.toBeInTheDocument();
  });

  it('does not fold a bare code or a different board into the ledger symbol', async () => {
    // 裸代碼不是台股語意、.TWO 是另一個市場：都不能被當成 2330.TW 的同一檔
    getWatchlist.mockResolvedValue(['2330', '2330.TWO']);
    getSnapshot.mockResolvedValue({ accounts: [{ accountName: '國泰台股', positions: [position('2330.TW', 10, 900)] }] });
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['2330', '2330.TWO', '2330.TW']));
    const rows = screen.getAllByRole('row');
    expect(within(rows[1]).queryByText('Held')).not.toBeInTheDocument();
    expect(within(rows[2]).queryByText('Held')).not.toBeInTheDocument();
    expect(within(rows[3]).getByText('Held')).toBeInTheDocument();
  });

  it('labels the index bar by the source the backend used', async () => {
    const idx = (source: string | null, asOf: string | null) => [
      { code: 'TWII', name: 'TAIEX', current: 46887.77, change: 594.84, changePct: 1.28, source, asOf },
    ];
    getIndices.mockResolvedValue(idx('shioaji', null));
    const { unmount } = renderPage();
    expect(await screen.findByLabelText(/Shioaji snapshot: realtime/)).toHaveTextContent(/^Live$/);
    expect(screen.queryByLabelText(/via yfinance/)).not.toBeInTheDocument();
    unmount();

    getIndices.mockResolvedValue(idx('official_close', '2026-10-22'));
    const second = renderPage();
    expect(await screen.findByLabelText(/local official close/)).toHaveTextContent('Official close 2026-10-22');
    second.unmount();

    getIndices.mockResolvedValue(idx(null, null));
    renderPage();
    expect(await screen.findByLabelText(/via yfinance/)).toHaveTextContent('Delayed');
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

  it('asks the dossier summary only for TW codes and shows the structure column', async () => {
    getDossierSummaries.mockImplementation((codes: string[]) =>
      Promise.resolve({ levelAlertsEnabled: false, items: codes.map((c) => ({
        stockCode: c,
        summary: c === '2330.TW'
          ? { asOf: '2026-10-21', close: 990, structure: { kind: 'BOS', bias: 'bull', date: '2026-10-05', level: 950 },
              levels: [{ label: 'OB', low: 940, high: 960, kind: 'ob', bias: 'bull' }], changes: [], verdicts: null }
          : null,
      })) }),
    );
    renderPage();
    await waitFor(() => expect(getDossierSummaries).toHaveBeenCalled());
    expect(getDossierSummaries.mock.calls.flat(2)).not.toContain('NVDA');
    const row = (await screen.findAllByRole('row')).find((r) => r.textContent?.startsWith('2330.TW'))!;
    await waitFor(() => expect(row.textContent).toContain('▲ BOS'));
    // 距離用即時價 1000 算：960 / 1000 − 1
    expect(row.textContent).toContain('-4.0%');
  });

  const summaryFor = (code: string) => ({
    stockCode: code,
    summary: { asOf: '2026-10-21', close: 990, structure: { kind: 'CHoCH', bias: 'bear', date: '2026-10-05', level: 950 },
      levels: [], changes: [], verdicts: null },
  });

  it('matches summaries to lowercase watchlist codes (backend answers uppercase)', async () => {
    getWatchlist.mockResolvedValue(['00631l.tw', '2454.TW']);
    getSnapshot.mockResolvedValue({ accounts: [] });
    // 兩邊都正規化：回應代碼大小寫與清單不同也對得上
    getDossierSummaries.mockResolvedValue({ levelAlertsEnabled: false, items: [summaryFor('00631L.TW'), summaryFor('2454.tw')] });
    renderPage();
    const rows = await screen.findAllByRole('row');
    for (const code of ['00631l.tw', '2454.TW']) {
      const row = rows.find((r) => r.textContent?.startsWith(code))!;
      await waitFor(() => expect(row.textContent).toContain('▼ CHoCH'));
    }
  });

  it('refetches summaries on manual refresh and every 15 minutes while visible', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderPage();
      await waitFor(() => expect(getDossierSummaries).toHaveBeenCalledTimes(1));
      fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
      await waitFor(() => expect(getDossierSummaries).toHaveBeenCalledTimes(2));
      await vi.advanceTimersByTimeAsync(15 * 60_000);
      await waitFor(() => expect(getDossierSummaries).toHaveBeenCalledTimes(3));
      // 分頁在背景時不抓
      Object.defineProperty(document, 'hidden', { configurable: true, value: true });
      await act(() => vi.advanceTimersByTimeAsync(15 * 60_000));
      expect(getDossierSummaries).toHaveBeenCalledTimes(3);
    } finally {
      Object.defineProperty(document, 'hidden', { configurable: true, value: false });
      vi.useRealTimers();
    }
  });
});
