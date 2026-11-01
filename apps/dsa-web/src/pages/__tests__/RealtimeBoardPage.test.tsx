import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import RealtimeBoardPage, { trendAxisBounds, trendPriceDigits } from '../RealtimeBoardPage';
import { useMarketIndexStore } from '../../stores/marketIndexStore';

const { getWatchlist, getSnapshot, listHoldings, getQuotes, getIndices, getDossierSummaries, getMarketStatus, getIntradayTrends, getHistoryList, getFinancials } = vi.hoisted(() => ({
  getFinancials: vi.fn(),
  getIntradayTrends: vi.fn(),
  getHistoryList: vi.fn(),
  getDossierSummaries: vi.fn(),
  getWatchlist: vi.fn(),
  getSnapshot: vi.fn(),
  listHoldings: vi.fn(),
  getQuotes: vi.fn(),
  getIndices: vi.fn(),
  getMarketStatus: vi.fn(),
}));

vi.mock('../../api/systemConfig', () => ({ systemConfigApi: { getWatchlist } }));
vi.mock('../../api/portfolio', () => ({ portfolioApi: { getSnapshot } }));
vi.mock('../../api/funds', () => ({ fundsApi: { listHoldings } }));
vi.mock('../../api/stocks', () => ({
  stocksApi: { getQuotes, getIndices, getIndicesSnapshot: (region: string) => Promise.resolve(getIndices(region)).then((items: unknown) => ({ items, marketPhase: null, marketOpen: null })), getFinancials, ensureFinancialCommentary: vi.fn(), getMarketStatus, getDossierSummaries, getIntradayTrends, getTrend: vi.fn().mockResolvedValue([]) },
}));
vi.mock('../../api/history', () => ({ historyApi: { getList: getHistoryList } }));
vi.mock('../../hooks/useStockIndex', () => ({ useStockIndex: () => ({ index: [] }) }));
vi.mock('recharts', () => {
  const Stub = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return { LineChart: Stub, Line: Stub, ReferenceLine: Stub, ResponsiveContainer: Stub, Tooltip: Stub, XAxis: Stub, YAxis: Stub };
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

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location" data-state={JSON.stringify(location.state)}>{`${location.pathname}${location.search}`}</div>;
}

function renderPage() {
  return render(
    <UiLanguageProvider>
      <MemoryRouter>
        <RealtimeBoardPage />
        <LocationProbe />
      </MemoryRouter>
    </UiLanguageProvider>,
  );
}

// DataTable 桌機與手機版面都掛載；board-code 只在桌機列上，順序即畫面由上到下
const rowCodes = () => screen.queryAllByTestId('board-code').map((el) => el.textContent);
const rowFor = (code: string) => screen.getAllByTestId('board-code').find((el) => el.textContent === code)!.closest('tr')!;
const resetIndexStore = () => useMarketIndexStore.getState().reset();

describe('RealtimeBoardPage scope', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    resetIndexStore();
    getIntradayTrends.mockResolvedValue([]);
    getFinancials.mockRejectedValue(new Error('no financials in this test'));
    getHistoryList.mockResolvedValue({ items: [] });
    getWatchlist.mockResolvedValue(['2330.TW', '2454.TW']);
    getSnapshot.mockResolvedValue(snapshot);
    listHoldings.mockResolvedValue({
      items: [{ id: 1, fundId: '18480065', fundName: '安聯台灣科技基金', nav: 783.21, navDate: '2026-10-21', isStale: false, pnlPct: 98.57 }],
      totals: [], navError: null,
    });
    getIndices.mockResolvedValue([]);
    getMarketStatus.mockResolvedValue({ tw: true, us: true });
    getDossierSummaries.mockResolvedValue({ items: [], levelAlertsEnabled: false });
    getQuotes.mockImplementation((codes: string[]) =>
      Promise.resolve(codes.map((c) => quote(c, c === '2330.TW' ? 1000 : c === '2887.TW' ? 40 : 200))),
    );
  });

  it('shows watchlist plus every account holding by default, without duplicates', async () => {
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['2330.TW', '2887.TW', 'NVDA', '2454.TW']));
    // 只打一支帶即時價的帳本快照，同時給持股清單與總覽，不再先打一支 include_realtime=false
    expect(getSnapshot).toHaveBeenCalledWith({ includeRealtime: true });
    expect(getSnapshot).not.toHaveBeenCalledWith({ includeRealtime: false });
  });

  it('asks quotes for the watchlist before the ledger snapshot comes back', async () => {
    let releaseSnapshot: (value: unknown) => void = () => {};
    getSnapshot.mockImplementation(() => new Promise((resolve) => {
      releaseSnapshot = resolve;
    }));
    renderPage();
    await waitFor(() => expect(getQuotes).toHaveBeenCalled());
    const firstBatch = getQuotes.mock.calls.flatMap((c) => c[0] as string[]);
    expect(new Set(firstBatch)).toEqual(new Set(['2330.TW', '2454.TW']));
    getQuotes.mockClear();
    await act(async () => releaseSnapshot(snapshot));
    // 帳本回來只補抓新出現的持股代碼，已抓過的自選不重打
    await waitFor(() => expect(getQuotes).toHaveBeenCalled());
    expect(new Set(getQuotes.mock.calls.flatMap((c) => c[0] as string[]))).toEqual(new Set(['2887.TW', 'NVDA']));
    await waitFor(() => expect(rowCodes()).toEqual(['2330.TW', '2887.TW', 'NVDA', '2454.TW']));
  });

  it('treats a lowercase watchlist code and the ledger symbol as one row', async () => {
    // STOCK_LIST 是原樣字串（可能小寫），帳本是大寫：同一檔只能一列，且要帶持股標籤與股數
    getWatchlist.mockResolvedValue(['2330.tw']);
    getSnapshot.mockResolvedValue({ accounts: [{ accountName: '國泰台股', positions: [position('2330.TW', 10, 900)] }] });
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['2330.tw']));
    const row = screen.getAllByTestId('board-code')[0].closest('tr')!;
    expect(within(row).getByText('Held')).toBeInTheDocument();
    expect(within(row).getByText('10')).toBeInTheDocument();
  });

  it('treats a US ticker in another case as the same holding', async () => {
    // normalizeStockCode 對美股原樣回傳不轉大寫：`nvda` 與帳本的 `NVDA` 仍要合成一列
    getWatchlist.mockResolvedValue(['nvda']);
    getSnapshot.mockResolvedValue({ accounts: [{ accountName: '永豐複委託', positions: [position('NVDA', 2, 100, 'USD')] }] });
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['nvda']));
    const row = screen.getAllByTestId('board-code')[0].closest('tr')!;
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
    const row = screen.getAllByTestId('board-code')[0].closest('tr')!;
    expect(within(row).getByText('Held')).toBeInTheDocument();
    expect(within(row).getByText('40')).toBeInTheDocument();
  });

  it('keeps distinct US tickers apart after case folding', async () => {
    // 反向：轉大寫不能把不同代碼摺成一檔
    getWatchlist.mockResolvedValue(['nvda', 'amd']);
    getSnapshot.mockResolvedValue({ accounts: [{ accountName: '永豐複委託', positions: [position('NVDA', 2, 100, 'USD')] }] });
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['nvda', 'amd']));
    expect(within(rowFor('nvda')).getByText('Held')).toBeInTheDocument();
    expect(within(rowFor('amd')).queryByText('Held')).not.toBeInTheDocument();
  });

  it('does not fold a bare code or a different board into the ledger symbol', async () => {
    // 裸代碼不是台股語意、.TWO 是另一個市場：都不能被當成 2330.TW 的同一檔
    getWatchlist.mockResolvedValue(['2330', '2330.TWO']);
    getSnapshot.mockResolvedValue({ accounts: [{ accountName: '國泰台股', positions: [position('2330.TW', 10, 900)] }] });
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['2330.TW', '2330', '2330.TWO']));
    expect(within(rowFor('2330')).queryByText('Held')).not.toBeInTheDocument();
    expect(within(rowFor('2330.TWO')).queryByText('Held')).not.toBeInTheDocument();
    expect(within(rowFor('2330.TW')).getByText('Held')).toBeInTheDocument();
  });

  it('labels the index bar by the source the backend used', async () => {
    const idx = (source: string | null, asOf: string | null) => [
      { code: 'TWII', name: 'TAIEX', current: 46887.77, change: 594.84, changePct: 1.28, source, asOf },
    ];
    const twOnly = (rows: unknown[]) => (region: string) => Promise.resolve(region === 'tw' ? rows : []);
    getIndices.mockImplementation(twOnly(idx('shioaji', null)));
    const { unmount } = renderPage();
    expect(await screen.findByLabelText(/Shioaji snapshot: realtime/)).toHaveTextContent(/^Live$/);
    expect(screen.queryByLabelText(/via yfinance/)).not.toBeInTheDocument();
    unmount();

    resetIndexStore();
    getIndices.mockImplementation(twOnly(idx('official_close', '2026-10-22')));
    const second = renderPage();
    expect(await screen.findByLabelText(/local official close/)).toHaveTextContent('Official close 2026-10-22');
    second.unmount();

    resetIndexStore();
    getIndices.mockImplementation(twOnly(idx(null, null)));
    renderPage();
    expect(await screen.findByLabelText(/via yfinance/)).toHaveTextContent('Delayed');
  });

  it('merges the same symbol across accounts with a share-weighted cost', async () => {
    renderPage();
    await waitFor(() => expect(rowCodes()).toContain('2330.TW'));
    const row = rowFor('2330.TW');
    // 10 股 @900 + 30 股 @1100 → 40 股、均價 1050；現價 1000 → −2,000
    expect(within(row).getByText('40')).toBeInTheDocument();
    await waitFor(() => expect(row.textContent).toContain('\u22122,000 TWD'));
  });

  it('holdings scope hides watch-only codes and is remembered', async () => {
    renderPage();
    await waitFor(() => expect(rowCodes()).toContain('2454.TW'));
    fireEvent.click(screen.getByRole('radio', { name: 'Holdings' }));
    await waitFor(() => expect(rowCodes()).toEqual(['2330.TW', '2887.TW', 'NVDA']));
    expect(window.localStorage.getItem('dsa.board.scope')).toBe('holdings');
  });

  it('keeps the watchlist when the ledger fails, and says so', async () => {
    getSnapshot.mockRejectedValue(new Error('boom'));
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['2330.TW', '2454.TW']));
    expect(screen.getByText('Holdings unavailable; showing watchlist only')).toBeInTheDocument();
  });

  it('labels the fund return as a holding return with the NAV date, without up/down colour', async () => {
    renderPage();
    const held = await screen.findByText('Held +98.57%');
    expect(held).toHaveClass('text-xs');
    expect(held.className).not.toMatch(/market-up|market-down|text-red|text-emerald/);
    expect(screen.getByText('NAV 10/21')).toBeInTheDocument();
  });

  it('shows fund holdings outside the watchlist scope only', async () => {
    renderPage();
    expect(await screen.findByText('安聯台灣科技基金')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: 'Watchlist' }));
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
    await waitFor(() => expect(rowCodes()).toContain('2330.TW'));
    const row = rowFor('2330.TW');
    await waitFor(() => expect(row.textContent).toContain('▲BOS'));
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
    await waitFor(() => expect(rowCodes()).toEqual(['00631l.tw', '2454.TW']));
    for (const code of ['00631l.tw', '2454.TW']) {
      await waitFor(() => expect(rowFor(code).textContent).toContain('▼CHoCH'));
    }
  });

  it('refetches summaries on manual refresh and every 15 minutes while visible', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderPage();
      // 自選與持股可能分兩批到，初次載入可能是一到兩支；之後的次數以它為基準
      await waitFor(() => expect(rowCodes()).toHaveLength(4));
      const asked = () => getDossierSummaries.mock.calls.flatMap((c) => c[0] as string[]);
      await waitFor(() => expect(new Set(asked())).toEqual(new Set(['2330.TW', '2887.TW', '2454.TW'])));
      expect(asked()).toHaveLength(3); // 分批也不重複問同一檔
      const base = getDossierSummaries.mock.calls.length;
      fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
      await waitFor(() => expect(getDossierSummaries).toHaveBeenCalledTimes(base + 1));
      await vi.advanceTimersByTimeAsync(15 * 60_000);
      await waitFor(() => expect(getDossierSummaries).toHaveBeenCalledTimes(base + 2));
      // 分頁在背景時不抓
      Object.defineProperty(document, 'hidden', { configurable: true, value: true });
      await act(() => vi.advanceTimersByTimeAsync(15 * 60_000));
      expect(getDossierSummaries).toHaveBeenCalledTimes(base + 2);
    } finally {
      Object.defineProperty(document, 'hidden', { configurable: true, value: false });
      vi.useRealTimers();
    }
  });

  it('stops polling quotes while the market is closed and resumes when it reopens', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderPage();
      await waitFor(() => expect(getQuotes).toHaveBeenCalled());
      getMarketStatus.mockResolvedValue({ tw: false, us: false });
      await act(() => vi.advanceTimersByTimeAsync(5 * 60_000 + 30_000)); // status check turns closed
      const calls = getQuotes.mock.calls.length;
      await act(() => vi.advanceTimersByTimeAsync(4 * 60_000)); // closed: no quote requests, no status request
      expect(getQuotes.mock.calls.length).toBe(calls);
      getMarketStatus.mockResolvedValue({ tw: true, us: true });
      await act(() => vi.advanceTimersByTimeAsync(2 * 60_000)); // next status check reopens
      expect(getQuotes.mock.calls.length).toBeGreaterThan(calls);
    } finally {
      vi.useRealTimers();
    }
  });

  const pollAfterStatusCheck = async (status: Record<string, boolean>) => {
    await waitFor(() => expect(getQuotes).toHaveBeenCalled());
    getMarketStatus.mockResolvedValue(status);
    getQuotes.mockClear();
    getIndices.mockClear();
    await act(() => vi.advanceTimersByTimeAsync(5 * 60_000 + 30_000));
    getQuotes.mockClear();
    getIndices.mockClear();
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    return getQuotes.mock.calls.flatMap((c) => c[0] as string[]);
  };

  it('polls only open markets: tw closed and us open skips tw quotes and the tw index', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderPage();
      const polled = await pollAfterStatusCheck({ tw: false, us: true });
      expect(new Set(polled)).toEqual(new Set(['NVDA']));
      expect(getIndices).not.toHaveBeenCalledWith('tw');
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps refreshing the tw index when a us-only board sees tw open', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      getWatchlist.mockResolvedValue(['NVDA']);
      getSnapshot.mockResolvedValue({ accounts: [] });
      renderPage();
      const polled = await pollAfterStatusCheck({ tw: true, us: false });
      expect(polled).toEqual([]);
      expect(getIndices).toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('never gates non-tw non-us codes (7203.T) on the us market', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      getWatchlist.mockResolvedValue(['7203.T', 'NVDA']);
      getSnapshot.mockResolvedValue({ accounts: [] });
      renderPage();
      const polled = await pollAfterStatusCheck({ tw: false, us: false });
      expect(new Set(polled)).toEqual(new Set(['7203.T']));
    } finally {
      vi.useRealTimers();
    }
  });
  it('polls AAPL.US and BRK-B as us codes: zero quote requests when both markets are closed', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      getWatchlist.mockResolvedValue(['AAPL.US', 'BRK-B']);
      getSnapshot.mockResolvedValue({ accounts: [] });
      renderPage();
      const polled = await pollAfterStatusCheck({ tw: false, us: false });
      expect(polled).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps a pending manual full refresh alive when a subset poll tick fires first', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderPage();
      await waitFor(() => expect(getQuotes).toHaveBeenCalled());
      getMarketStatus.mockResolvedValue({ tw: false, us: true });
      await act(() => vi.advanceTimersByTimeAsync(5 * 60_000 + 30_000)); // status turns tw closed
      const pending: Array<() => void> = [];
      getQuotes.mockImplementation(
        (codes: string[]) =>
          new Promise((resolve) => {
            pending.push(() => resolve(codes.map((c) => quote(c, c === '2330.TW' ? 1234 : 200))));
          }),
      );
      fireEvent.click(screen.getByRole('button', { name: /刷新|重新整理|refresh/i }));
      const manual = pending.splice(0); // full refresh, still in flight
      await act(() => vi.advanceTimersByTimeAsync(30_000)); // us-only tick fires before tw chunks return
      await act(async () => {
        manual.forEach((f) => f());
        pending.splice(0).forEach((f) => f());
      });
      expect((await screen.findAllByText(/1,?234/)).length).toBeGreaterThan(0);
    } finally {
      vi.useRealTimers();
    }
  });
  it('still drops a late response for codes that a newer refresh already covered', async () => {
    renderPage();
    await waitFor(() => expect(getQuotes).toHaveBeenCalled());
    const pending: Array<(price: number) => void> = [];
    getQuotes.mockImplementation(
      (codes: string[]) =>
        new Promise((resolve) => {
          pending.push((price) => resolve(codes.map((c) => quote(c, c === '2330.TW' ? price : 200))));
        }),
    );
    const btn = screen.getByRole('button', { name: /刷新|重新整理|refresh/i });
    fireEvent.click(btn);
    const older = pending.splice(0);
    fireEvent.click(btn);
    const newer = pending.splice(0);
    await act(async () => newer.forEach((f) => f(2222)));
    await act(async () => older.forEach((f) => f(1111)));
    expect((await screen.findAllByText(/2,?222/)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/1,?111/)).toBeNull();
  });

  it('groups rows into TW holdings, US holdings and watchlist sections', async () => {
    renderPage();
    const tw = await screen.findByRole('table', { name: 'Holdings (TW)' });
    expect(within(tw).getAllByText('2887.TW').length).toBeGreaterThan(0);
    expect(within(screen.getByRole('table', { name: 'Holdings (US)' })).getAllByText('NVDA').length).toBeGreaterThan(0);
    expect(within(screen.getByRole('table', { name: 'Watchlist' })).getAllByText('2454.TW').length).toBeGreaterThan(0);
  });

  it('has no status or time column', async () => {
    renderPage();
    await screen.findByRole('table', { name: 'Holdings (TW)' });
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent);
    expect(headers).not.toContain('Status');
    expect(headers).toContain('Name / Code');
  });

  it('keeps the name when there is no quote, and says there is no quote', async () => {
    getWatchlist.mockResolvedValue([]);
    getSnapshot.mockResolvedValue({ accounts: [{ accountName: '國泰台股', positions: [{ ...position('2330.TW', 10, 900), name: '台積電' }] }] });
    getQuotes.mockResolvedValue([{ stockCode: '2330.TW', quote: null, error: 'no_data' }]);
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['2330.TW']));
    const row = rowFor('2330.TW');
    expect(within(row).getByText('台積電')).toBeInTheDocument();
    await waitFor(() => expect(within(row).getByText('No quote')).toBeInTheDocument());
  });

  it('flags stale quotes only while the market is open', async () => {
    const stale = (codes: string[]) =>
      Promise.resolve(codes.map((c) => ({ stockCode: c, quote: { ...quote(c, 100).quote, isStale: true } })));
    getWatchlist.mockResolvedValue(['2454.TW']);
    getSnapshot.mockResolvedValue({ accounts: [] });
    getQuotes.mockImplementation(stale);
    const open = renderPage();
    await waitFor(() => expect(within(rowFor('2454.TW')).getByText('Stale data')).toBeInTheDocument());
    open.unmount();

    getMarketStatus.mockResolvedValue({ tw: false, us: false });
    renderPage();
    await waitFor(() => expect(screen.getByTestId('board-market-status').textContent).toContain('TW Closed'));
    await waitFor(() => expect(rowFor('2454.TW').textContent).toContain('100'));
    expect(within(rowFor('2454.TW')).queryByText('Stale data')).not.toBeInTheDocument();
  });

  it('restores the saved sort and keeps missing readings last in both directions', async () => {
    getWatchlist.mockResolvedValue(['A', 'B', 'C']);
    getSnapshot.mockResolvedValue({ accounts: [] });
    getQuotes.mockImplementation((codes: string[]) =>
      Promise.resolve(codes.map((c) => (c === 'B' ? { stockCode: c, quote: null } : quote(c, c === 'A' ? 10 : 20)))),
    );
    window.localStorage.setItem('dsa.board.sort', JSON.stringify({ key: 'price', direction: 'desc' }));
    renderPage();
    await waitFor(() => expect(rowCodes()).toEqual(['C', 'A', 'B']));
    fireEvent.click(screen.getByRole('button', { name: /Price|现价|現價/ }));
    // 已是降冪，再點變升冪：缺值仍在最後
    await waitFor(() => expect(rowCodes()).toEqual(['A', 'C', 'B']));
    expect(JSON.parse(window.localStorage.getItem('dsa.board.sort')!)).toEqual({ key: 'price', direction: 'asc' });
  });

  it('filters rows by code', async () => {
    renderPage();
    await waitFor(() => expect(rowCodes()).toContain('2454.TW'));
    fireEvent.change(screen.getByRole('textbox', { name: 'Filter by name or code' }), { target: { value: 'nvd' } });
    await waitFor(() => expect(rowCodes()).toEqual(['NVDA']));
    fireEvent.change(screen.getByRole('textbox', { name: 'Filter by name or code' }), { target: { value: 'zzz' } });
    expect(await screen.findByText('No stocks match the filter')).toBeInTheDocument();
  });

  it('takes the day P/L from day_pnl by currency, never from quotes', async () => {
    getSnapshot.mockImplementation(({ includeRealtime }: { includeRealtime: boolean }) =>
      Promise.resolve(includeRealtime
        ? { accounts: [
            { accountName: 'a', baseCurrency: 'TWD', dayPnl: 1200, unrealizedPnl: 5000, positions: [] },
            { accountName: 'b', baseCurrency: 'TWD', dayPnl: 300, unrealizedPnl: 1000, positions: [] },
            { accountName: 'c', baseCurrency: 'USD', dayPnl: null, unrealizedPnl: -5, positions: [] },
          ] }
        : snapshot),
    );
    renderPage();
    const twd = (await screen.findByText('Day P/L (TW)')).closest('[data-metric-state]')!;
    expect(twd.textContent).toContain('+1,500');
    expect(twd.textContent).toContain('+6,000');
    // 有一個帳戶算不出就是沒有讀數，不是 0
    const usd = screen.getByText('Day P/L (US)').closest('[data-metric-state]')!;
    expect(usd).toHaveAttribute('data-metric-state', 'unavailable');
  });

  it('asks for market status on first load and does not say Live after the close', async () => {
    getMarketStatus.mockResolvedValue({ tw: false, us: true });
    getIndices.mockImplementation((region: string) =>
      Promise.resolve(region === 'tw'
        ? [{ code: 'TWII', name: 'TAIEX', current: 100, change: 1, changePct: 1, source: 'shioaji', asOf: null }]
        : [{ code: 'SPX', name: 'S&P 500', current: 200, change: 1, changePct: 1, source: null, asOf: null }]),
    );
    renderPage();
    await waitFor(() => expect(screen.getByTestId('board-market-status').textContent).toContain('TW Closed'));
    expect(screen.getByTestId('board-market-status').textContent).toContain('US Open');
    expect(getMarketStatus).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('S&P 500')).toBeInTheDocument();
    const live = await screen.findByLabelText(/Shioaji snapshot: realtime/);
    expect(live).toHaveTextContent('Closed');
    expect(live).not.toHaveTextContent('Live');
  });

  it('still says Live for a live index while the market is open', async () => {
    // 反向：不能把「即時」一律拿掉
    getIndices.mockImplementation((region: string) =>
      Promise.resolve(region === 'tw'
        ? [{ code: 'TWII', name: 'TAIEX', current: 100, change: 1, changePct: 1, source: 'shioaji', asOf: null }]
        : []),
    );
    renderPage();
    await waitFor(() => expect(screen.getByTestId('board-market-status').textContent).toContain('TW Open'));
    expect(await screen.findByLabelText(/Shioaji snapshot: realtime/)).toHaveTextContent(/^Live$/);
  });

  const clickAnalyze = async (code: string) => {
    await waitFor(() => expect(rowCodes()).toContain(code));
    fireEvent.click(within(rowFor(code)).getByRole('button', { name: 'Analyze' }));
  };

  it('Analyze opens the latest report without triggering an analysis', async () => {
    getHistoryList.mockResolvedValue({ items: [{ id: 42 }] });
    renderPage();
    await clickAnalyze('2454.TW');
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/?report=42'));
    expect(getHistoryList).toHaveBeenCalledWith({ stockCode: '2454.TW', limit: 1 });
    // 不帶 location.state：autoAnalyze 走的是那條路
    expect(screen.getByTestId('location').dataset.state).toBe('null');
  });

  it('Analyze falls back to the stock link when there is no report or the lookup fails', async () => {
    const first = renderPage();
    await clickAnalyze('2454.TW');
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/?stock=2454.TW'));
    first.unmount();

    getHistoryList.mockRejectedValue(new Error('boom'));
    renderPage();
    await clickAnalyze('2454.TW');
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/?stock=2454.TW'));
  });

  it('expanding a row shows the value grid, one set of bid/ask tones, and the actions', async () => {
    getWatchlist.mockResolvedValue(['2454.TW']);
    getSnapshot.mockResolvedValue({ accounts: [] });
    getQuotes.mockResolvedValue([{
      stockCode: '2454.TW',
      quote: { ...quote('2454.TW', 100).quote, prevClose: 100, bestBid: 99, bestBidVolume: 5, bestAsk: 101, bestAskVolume: 7 },
    }]);
    renderPage();
    await waitFor(() => expect(rowFor('2454.TW').textContent).toContain('100'));
    fireEvent.click(rowFor('2454.TW'));
    const panel = await screen.findByTestId('board-expanded');
    const grid = within(panel).getByTestId('board-detail-grid');
    // 委買低於昨收是跌色、委賣高於昨收是漲色；同一價位規則，不是固定一紅一綠
    expect(within(grid).getByText('Bid').parentElement?.querySelector('.text-market-down')).toBeTruthy();
    expect(within(grid).getByText('Ask').parentElement?.querySelector('.text-market-up')).toBeTruthy();
    fireEvent.click(within(panel).getByRole('button', { name: 'Create alert' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/alerts?new=1&target=2454.TW'));
  });

  it('colors a bid above the previous close as up', async () => {
    // 反向：委買不能寫死跌色
    getWatchlist.mockResolvedValue(['2454.TW']);
    getSnapshot.mockResolvedValue({ accounts: [] });
    getQuotes.mockResolvedValue([{
      stockCode: '2454.TW',
      quote: { ...quote('2454.TW', 100).quote, prevClose: 90, bestBid: 99, bestBidVolume: 5 },
    }]);
    renderPage();
    await waitFor(() => expect(rowFor('2454.TW').textContent).toContain('100'));
    fireEvent.click(rowFor('2454.TW'));
    const grid = within(await screen.findByTestId('board-expanded')).getByTestId('board-detail-grid');
    expect(within(grid).getByText('Bid').parentElement?.querySelector('.text-market-up')).toBeTruthy();
  });

  it('asks sparklines for holdings only and draws them in the holdings sections', async () => {
    getIntradayTrends.mockImplementation((codes: string[]) =>
      Promise.resolve(codes.map((c) => ({ stockCode: c, points: [{ t: 'a', price: 1 }, { t: 'b', price: 2 }] }))),
    );
    renderPage();
    await waitFor(() => expect(getIntradayTrends).toHaveBeenCalled());
    const asked = getIntradayTrends.mock.calls.flatMap((c) => c[0] as string[]);
    expect(asked).toContain('2330.TW');
    expect(asked).not.toContain('2454.TW');
    await waitFor(() => expect(within(rowFor('2330.TW')).getByTestId('board-spark')).toBeInTheDocument());
    expect(within(rowFor('2454.TW')).queryByTestId('board-spark')).not.toBeInTheDocument();
  });

  it('can turn sparklines off, stops asking, and remembers it', async () => {
    renderPage();
    await waitFor(() => expect(getIntradayTrends).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: 'Holdings sparkline' }));
    expect(window.localStorage.getItem('dsa.board.spark')).toBe('off');
    expect(screen.queryAllByRole('columnheader').map((h) => h.textContent)).not.toContain('Today');
    getIntradayTrends.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(getQuotes).toHaveBeenCalled());
    expect(getIntradayTrends).not.toHaveBeenCalled();
  });

  it('does not spend sparkline requests on a phone-sized viewport', async () => {
    const original = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({ matches: false }) as unknown as typeof window.matchMedia;
    try {
      renderPage();
      await waitFor(() => expect(rowCodes()).toContain('2454.TW'));
      expect(getIntradayTrends).not.toHaveBeenCalled();
    } finally {
      window.matchMedia = original;
    }
  });

  const bigMoveQuotes = (codes: string[]) =>
    Promise.resolve(codes.map((c) => (c === '2454.TW'
      ? { stockCode: c, quote: { ...quote(c, 200).quote, changePercent: 7 } }
      : quote(c, c === '2330.TW' ? 1000 : c === '2887.TW' ? 40 : 200))));

  it('builds the attention chips from the filtered rows only', async () => {
    getQuotes.mockImplementation(bigMoveQuotes);
    renderPage();
    const chips = await screen.findByTestId('board-attention');
    expect(within(chips).getByRole('button', { name: /2454\.TW/ })).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'Filter by name or code' }), { target: { value: 'zzzz' } });
    await screen.findByText('No stocks match the filter');
    expect(screen.queryByTestId('board-attention')).not.toBeInTheDocument();
  });

  it('jumps to the attention row: clears the filter, expands, scrolls it to the centre and highlights it', async () => {
    const scrollIntoView = vi.fn();
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scrollIntoView;
    try {
      getQuotes.mockImplementation(bigMoveQuotes);
      renderPage();
      fireEvent.change(await screen.findByRole('textbox', { name: 'Filter by name or code' }), { target: { value: '2454' } });
      const chip = within(await screen.findByTestId('board-attention')).getByRole('button', { name: /2454\.TW/ });
      fireEvent.click(chip);
      expect(screen.getByRole('textbox', { name: 'Filter by name or code' })).toHaveValue('');
      await waitFor(() => expect(rowCodes()).toContain('2330.TW'));
      expect(rowFor('2454.TW')).toHaveAttribute('data-row-highlighted', 'true');
      expect(await screen.findByTestId('board-expanded')).toBeInTheDocument();
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: 'center', behavior: 'smooth' }));
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  it('caps the attention chips at five and folds the rest', async () => {
    const codes = ['A', 'B', 'C', 'D', 'E', 'F', 'G'];
    getWatchlist.mockResolvedValue(codes);
    getSnapshot.mockResolvedValue({ accounts: [] });
    getQuotes.mockImplementation((cs: string[]) =>
      Promise.resolve(cs.map((c) => ({ stockCode: c, quote: { ...quote(c, 10).quote, changePercent: 5 + codes.indexOf(c) } }))),
    );
    renderPage();
    const chips = await screen.findByTestId('board-attention');
    await waitFor(() => expect(within(chips).getAllByRole('button')).toHaveLength(5));
    // 依 |漲跌幅| 由大到小：G 最大排第一，A、B 被收起來
    expect(within(chips).getAllByRole('button')[0]).toHaveTextContent('G');
    expect(within(chips).getByText('+2 more')).toBeInTheDocument();
  });

  it('renders a single watchlist section in the watchlist scope, with held rows tagged', async () => {
    renderPage();
    await screen.findByRole('table', { name: 'Holdings (TW)' });
    fireEvent.click(screen.getByRole('radio', { name: 'Watchlist' }));
    const watch = await screen.findByRole('table', { name: 'Watchlist' });
    await waitFor(() => expect(screen.getAllByRole('table')).toHaveLength(1));
    expect(screen.queryByRole('table', { name: 'Holdings (TW)' })).not.toBeInTheDocument();
    const held = within(watch).getAllByTestId('board-code').find((el) => el.textContent === '2330.TW')!.closest('tr')!;
    expect(within(held).getByText('Held')).toBeInTheDocument();
  });

  it('keeps TW and US holdings apart in the holdings scope', async () => {
    window.localStorage.setItem('dsa.board.scope', 'holdings');
    renderPage();
    expect(await screen.findByRole('table', { name: 'Holdings (TW)' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Holdings (US)' })).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Watchlist' })).not.toBeInTheDocument();
  });

  it('labels the day P/L as the previous session when both markets are closed', async () => {
    getMarketStatus.mockResolvedValue({ tw: false, us: false });
    getSnapshot.mockResolvedValue({ accounts: [
      { accountName: 'a', baseCurrency: 'TWD', dayPnl: 1200, unrealizedPnl: 5000, positions: [] },
    ] });
    renderPage();
    expect(await screen.findByText('Previous session P&L (TW)')).toBeInTheDocument();
    expect(screen.queryByText('Day P/L (TW)')).not.toBeInTheDocument();
  });

  it('keeps the day P/L label while one market is still open', async () => {
    // 反向：只有一邊休市不能改叫上一交易日
    getMarketStatus.mockResolvedValue({ tw: false, us: true });
    getSnapshot.mockResolvedValue({ accounts: [
      { accountName: 'a', baseCurrency: 'TWD', dayPnl: 1200, unrealizedPnl: 5000, positions: [] },
    ] });
    renderPage();
    await waitFor(() => expect(screen.getByTestId('board-market-status').textContent).toContain('TW Closed'));
    expect(await screen.findByText('Day P/L (TW)')).toBeInTheDocument();
    expect(screen.queryByText('Previous session P&L (TW)')).not.toBeInTheDocument();
  });

  it('shows shares and unrealized P/L on the phone card of a holding', async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId('board-mobile-holding').length).toBe(3));
    // 40 股 @1050，現價 1000 → −2,000（−4.8%）
    await waitFor(() =>
      expect(screen.getAllByTestId('board-mobile-holding').map((el) => el.textContent)).toContainEqual(
        expect.stringMatching(/^40 sh · [−-]2,000 \([−-]4\.8%\)$/),
      ),
    );
  });

  it('says how many quotes are back while the breadth is still loading', async () => {
    const pending: Array<() => void> = [];
    getQuotes.mockImplementation((codes: string[]) => new Promise((resolve) => {
      pending.push(() => resolve(codes.map((c) => quote(c, 100))));
    }));
    renderPage();
    await waitFor(() => expect(rowCodes()).toHaveLength(4));
    expect(await screen.findByText('Loading 0/4')).toBeInTheDocument();
    await act(async () => pending.splice(0).forEach((f) => f()));
    await waitFor(() => expect(screen.getByText('Up 4 / Down 0 / Flat 0')).toBeInTheDocument());
  });

  const expandOnly2454 = async (quoteOver: Record<string, unknown> = {}) => {
    getWatchlist.mockResolvedValue(['2454.TW', '2330.TW']);
    getSnapshot.mockResolvedValue({ accounts: [] });
    getQuotes.mockImplementation((codes: string[]) =>
      Promise.resolve(codes.map((c) => ({ stockCode: c, quote: { ...quote(c, 100).quote, prevClose: 100, ...quoteOver } }))),
    );
    renderPage();
    await waitFor(() => expect(rowFor('2454.TW').textContent).toContain('100'));
    fireEvent.click(rowFor('2454.TW'));
    return screen.findByTestId('board-expanded');
  };

  it('keeps the financials collapsed in the expanded row, showing only the title', async () => {
    getFinancials.mockResolvedValue({
      stockCode: '2454.TW', status: 'ok', template: 'general', currency: 'TWD', tradingCurrency: 'TWD', source: null,
      periods: [{ key: '2026Q2', label: '2026 Q2', periodEnd: '2026-06-30', announceDate: null, announceDateKind: 'filed' }],
      metrics: [{ key: 'revenue', label: '營收', kind: 'amount', unit: 'TWD', definition: '教學', points: [
        { period: '2026Q2', value: 1.27e12, yoyPct: 1, qoqPct: 1, yoyPp: null, qoqPp: null, derived: false }] }],
      notApplicable: [], monthlyRevenue: [], limitations: [], isStale: false,
      commentary: { status: 'disabled', highlights: [], headline: null },
    });
    const panel = await expandOnly2454();
    const toggle = await within(panel).findByRole('button', { name: 'Financials & monthly revenue (2026 Q2)' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(within(panel).queryByText('營收')).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(within(panel).getByText('營收')).toBeInTheDocument();
  });

  it('hides the row-tail Analyze only on the expanded row and offers View report in the expanded actions', async () => {
    getHistoryList.mockResolvedValue({ items: [{ id: 7 }] });
    const panel = await expandOnly2454();
    expect(within(rowFor('2454.TW')).queryByRole('button', { name: 'Analyze' })).not.toBeInTheDocument();
    // reverse: other rows keep it
    expect(within(rowFor('2330.TW')).getByRole('button', { name: 'Analyze' })).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Full analysis' })).not.toBeInTheDocument();
    fireEvent.click(within(panel).getByRole('button', { name: 'View report' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/?report=7'));
  });

  it('collapses the expanded row from the sticky button at its bottom', async () => {
    const panel = await expandOnly2454();
    const collapse = within(panel).getByTestId('board-expanded-collapse');
    expect(collapse).toHaveClass('sticky', 'bottom-0', 'h-10', 'w-full', 'border-t');
    fireEvent.click(collapse);
    await waitFor(() => expect(screen.queryByTestId('board-expanded')).not.toBeInTheDocument());
    expect(within(rowFor('2454.TW')).getByRole('button', { name: 'Analyze' })).toBeInTheDocument();
  });

  it('shows the limit distance as a small pill instead of 10px text', async () => {
    getWatchlist.mockResolvedValue(['2454.TW']);
    getSnapshot.mockResolvedValue({ accounts: [] });
    getQuotes.mockResolvedValue([{ stockCode: '2454.TW', quote: { ...quote('2454.TW', 108).quote, limitUp: 110, limitDown: 90 } }]);
    renderPage();
    const pill = await within(await waitFor(() => rowFor('2454.TW'))).findByText(/1\.9%/);
    expect(pill).toHaveClass('text-[11px]', 'font-medium', 'rounded-full');
    expect(pill).not.toHaveClass('text-[10px]');
  });
});

describe('trend chart axis', () => {
  it('pulls the prev-close baseline inside the axis when prices sit entirely above it', () => {
    const baseline = 100;
    const [lo, hi] = trendAxisBounds(104, 110, baseline);
    expect(lo).toBeLessThanOrEqual(baseline);
    expect(hi).toBeGreaterThanOrEqual(baseline);
    expect(hi).toBeGreaterThanOrEqual(110);
  });

  it('pulls the baseline inside when prices sit entirely below it', () => {
    const baseline = 100;
    const [lo, hi] = trendAxisBounds(90, 96, baseline);
    expect(lo).toBeLessThanOrEqual(90);
    expect(hi).toBeGreaterThanOrEqual(baseline);
  });

  it('fits the prices only when there is no baseline (month / year ranges)', () => {
    const [lo, hi] = trendAxisBounds(90, 96, null);
    expect(lo).toBeLessThanOrEqual(90);
    expect(hi).toBeGreaterThanOrEqual(96);
    expect(hi).toBeLessThan(100); // reverse: no phantom baseline stretching the axis
  });

  it('gives a flat series a non-zero band', () => {
    const [lo, hi] = trendAxisBounds(50, 50, 50);
    expect(hi).toBeGreaterThan(lo);
  });

  it('picks tick decimals from the TW tick-size band', () => {
    expect(trendPriceDigits(1000)).toBe(0);
    expect(trendPriceDigits(120)).toBe(1);
    expect(trendPriceDigits(18.35)).toBe(2);
  });
});
