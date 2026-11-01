import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { decisionSignalsApi } from '../../api/decisionSignals';
import { createApiError, createParsedApiError } from '../../api/error';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import type { DecisionSignalItem } from '../../types/decisionSignals';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import { toDateInputValue } from '../../utils/format';
import PortfolioPage from '../PortfolioPage';

const {
  getAccounts,
  getSnapshot,
  getRisk,
  refreshFx,
  listImportBrokers,
  listTrades,
  listCashLedger,
  listCorporateActions,
  createTrade,
  deleteTrade,
  createCashLedger,
  deleteCashLedger,
  createCorporateAction,
  deleteCorporateAction,
  parseCsvImport,
  commitCsvImport,
  parseTextImport,
  commitTextImport,
  createAccount,
  deleteAccount,
  analyzePosition,
  listDecisionSignals,
  getLatestDecisionSignals,
} = vi.hoisted(() => ({
  getAccounts: vi.fn(),
  getSnapshot: vi.fn(),
  getRisk: vi.fn(),
  refreshFx: vi.fn(),
  listImportBrokers: vi.fn(),
  listTrades: vi.fn(),
  listCashLedger: vi.fn(),
  listCorporateActions: vi.fn(),
  createTrade: vi.fn(),
  deleteTrade: vi.fn(),
  createCashLedger: vi.fn(),
  deleteCashLedger: vi.fn(),
  createCorporateAction: vi.fn(),
  deleteCorporateAction: vi.fn(),
  parseCsvImport: vi.fn(),
  commitCsvImport: vi.fn(),
  parseTextImport: vi.fn(),
  commitTextImport: vi.fn(),
  createAccount: vi.fn(),
  deleteAccount: vi.fn(),
  analyzePosition: vi.fn(),
  listDecisionSignals: vi.fn(),
  getLatestDecisionSignals: vi.fn(),
}));

vi.mock('../../api/decisionSignals', () => ({
  decisionSignalsApi: {
    list: listDecisionSignals,
    getLatest: getLatestDecisionSignals,
  },
}));

vi.mock('../../api/portfolio', () => ({
  portfolioApi: {
    getAccounts,
    getSnapshot,
    getRisk,
    refreshFx,
    listImportBrokers,
    listTrades,
    listCashLedger,
    listCorporateActions,
    createTrade,
    deleteTrade,
    createCashLedger,
    deleteCashLedger,
    createCorporateAction,
    deleteCorporateAction,
    parseCsvImport,
    commitCsvImport,
    parseTextImport,
    commitTextImport,
    createAccount,
    deleteAccount,
    analyzePosition,
  },
}));

type AccountItem = {
  id: number;
  name: string;
  market?: 'cn' | 'hk' | 'us' | 'jp' | 'kr' | 'tw';
  baseCurrency?: string;
};

function makeAccounts(items: AccountItem[] = [{ id: 1, name: 'Main' }]) {
  return {
    accounts: items.map((item) => ({
      id: item.id,
      name: item.name,
      broker: 'Demo',
      market: item.market ?? 'us',
      baseCurrency: item.baseCurrency ?? 'CNY',
      isActive: true,
      ownerId: null,
      createdAt: '2026-03-19T00:00:00Z',
      updatedAt: '2026-03-19T00:00:00Z',
    })),
  };
}

function makeSnapshot(options: {
  accountId?: number;
  fxStale?: boolean;
  accountCount?: number;
  dataQuality?: string;
  limitations?: string[];
  positions?: Array<Record<string, unknown>>;
} = {}) {
  const accountId = options.accountId ?? 1;
  return {
    asOf: '2026-03-19',
    costMethod: 'fifo' as const,
    currency: 'CNY',
    accountCount: options.accountCount ?? 1,
    totalCash: 1000,
    totalMarketValue: 2000,
    totalEquity: 3000,
    realizedPnl: 0,
    unrealizedPnl: 0,
    feeTotal: 0,
    taxTotal: 0,
    fxStale: options.fxStale ?? true,
    dataQuality: options.dataQuality ?? 'ok',
    limitations: options.limitations ?? [],
    accounts: [
      {
        accountId,
        accountName: `Account ${accountId}`,
        ownerId: null,
        broker: 'Demo',
        market: 'us',
        baseCurrency: 'CNY',
        asOf: '2026-03-19',
        costMethod: 'fifo' as const,
        totalCash: 1000,
        totalMarketValue: 2000,
        totalEquity: 3000,
        realizedPnl: 0,
        unrealizedPnl: 0,
        feeTotal: 0,
        taxTotal: 0,
        fxStale: options.fxStale ?? true,
        positions: options.positions ?? [],
      },
    ],
  };
}

function makePosition(overrides: Record<string, unknown> = {}) {
  return {
    symbol: '600519',
    market: 'cn',
    currency: 'CNY',
    quantity: 1,
    avgCost: 1500,
    totalCost: 1500,
    lastPrice: 1600,
    marketValueBase: 1600,
    unrealizedPnlBase: 100,
    unrealizedPnlPct: 6.67,
    valuationCurrency: 'CNY',
    priceSource: 'history_close',
    priceDate: '2026-06-17',
    priceStale: false,
    priceAvailable: true,
    ...overrides,
  };
}

function makeRisk(overrides: Record<string, unknown> = {}) {
  return {
    asOf: '2026-03-19',
    accountId: null,
    costMethod: 'fifo' as const,
    currency: 'CNY',
    thresholds: {},
    concentration: {
      totalMarketValue: 0,
      topWeightPct: 0,
      alert: false,
      topPositions: [],
    },
    sectorConcentration: {
      totalMarketValue: 0,
      topWeightPct: 0,
      alert: false,
      topSectors: [],
      coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
      errors: [],
    },
    drawdown: {
      seriesPoints: 0,
      maxDrawdownPct: 0,
      currentDrawdownPct: 0,
      alert: false,
      fxStale: false,
    },
    stopLoss: {
      nearAlert: false,
      triggeredCount: 0,
      nearCount: 0,
      items: [],
    },
    decisionSignalRisk: {
      available: true,
      total: 0,
      actions: { sell: 0, reduce: 0, alert: 0 },
      items: [],
    },
    ...overrides,
  };
}

function makeDecisionSignal(overrides: Partial<DecisionSignalItem> = {}): DecisionSignalItem {
  return {
    id: 100,
    stockCode: '600519',
    stockName: '贵州茅台',
    market: 'cn',
    sourceType: 'analysis',
    sourceReportId: 1,
    traceId: null,
    marketPhase: 'intraday',
    triggerSource: 'portfolio',
    action: 'hold',
    actionLabel: null,
    confidence: 0.7,
    score: 80,
    horizon: '3d',
    entryLow: null,
    entryHigh: null,
    stopLoss: null,
    targetPrice: null,
    invalidation: null,
    watchConditions: '观察量能',
    reason: '趋势延续',
    riskSummary: '短线回撤风险',
    catalystSummary: null,
    evidence: undefined,
    dataQualitySummary: undefined,
    planQuality: 'partial',
    status: 'active',
    expiresAt: null,
    createdAt: '2026-06-17T08:00:00',
    updatedAt: '2026-06-17T08:00:00',
    metadata: undefined,
    ...overrides,
  };
}

function deferredPromise<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function waitForInitialLoad() {
  await waitFor(() => expect(getAccounts).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(getSnapshot).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(getRisk).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(listTrades).toHaveBeenCalledTimes(1));
}

const snapshotQuery = (accountId?: number, costMethod: 'fifo' | 'avg' = 'fifo') => ({
  accountId,
  costMethod,
  includeRealtime: false,
  displayCurrency: 'TWD',
  includeFunds: accountId === undefined,
});
const riskQuery = (accountId?: number, costMethod: 'fifo' | 'avg' = 'fifo') => ({
  accountId,
  costMethod,
  includeRealtime: false,
  displayCurrency: 'TWD',
});

// DataTable 桌機與手機版都在 DOM 裡，文字斷言限定桌機版才不會撞名。
async function desktopHoldings() {
  const holdings = await screen.findByTestId('portfolio-holdings');
  return within(within(holdings).getByTestId('data-table-desktop'));
}

// Same local-date formatting the page uses for "today" (getTodayIso).
const getTodayIsoFor = (date: Date) => toDateInputValue(date);

const selectAccount = (name: string) => fireEvent.click(screen.getByRole('radio', { name }));
const openPageMenu = () => fireEvent.click(screen.getByRole('button', { name: '更多操作' }));

describe('PortfolioPage FX refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();

    getAccounts.mockResolvedValue(makeAccounts());
    getSnapshot.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => makeSnapshot({ accountId, fxStale: true }));
    getRisk.mockResolvedValue(makeRisk());
    refreshFx.mockResolvedValue({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: true,
      disabledReason: null,
      pairCount: 1,
      updatedCount: 1,
      staleCount: 0,
      errorCount: 0,
    });
    listImportBrokers.mockResolvedValue({
      brokers: [{ broker: 'huatai', aliases: [], displayName: '华泰' }],
    });
    listTrades.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 });
    listCashLedger.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 });
    listCorporateActions.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 });
    createTrade.mockResolvedValue({ id: 1 });
    deleteTrade.mockResolvedValue({ deleted: 1 });
    createCashLedger.mockResolvedValue({ id: 1 });
    deleteCashLedger.mockResolvedValue({ deleted: 1 });
    createCorporateAction.mockResolvedValue({ id: 1 });
    deleteCorporateAction.mockResolvedValue({ deleted: 1 });
    parseCsvImport.mockResolvedValue({ broker: 'huatai', recordCount: 0, skippedCount: 0, errorCount: 0, records: [], errors: [] });
    commitCsvImport.mockResolvedValue({
      accountId: 1,
      recordCount: 0,
      insertedCount: 0,
      duplicateCount: 0,
      failedCount: 0,
      dryRun: true,
      errors: [],
    });
    createAccount.mockResolvedValue({ id: 1 });
    deleteAccount.mockResolvedValue({ deleted: 1 });
    analyzePosition.mockResolvedValue({
      taskId: 'task-portfolio-1',
      traceId: 'task-portfolio-1',
      status: 'pending',
      message: '分析任务已加入队列: HK00700',
      analysisPhase: 'auto',
    });
    getLatestDecisionSignals.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 1 });
    // Default: the grouped list hits nothing, so lookups fall back to the per-stock endpoint.
    listDecisionSignals.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 100 });
  });

  function renderEnglishPage() {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    render(
      <UiLanguageProvider>
        <PortfolioPage />
      </UiLanguageProvider>,
    );
  }

  it('uses fast portfolio valuation for page snapshot and risk loads', async () => {
    render(<PortfolioPage />);

    await waitForInitialLoad();

    expect(getSnapshot).toHaveBeenCalledWith(snapshotQuery());
    expect(getRisk).toHaveBeenCalledWith(riskQuery());
  });

  it('shows the stock name under the code and falls back to the bare code when unknown', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: false,
      positions: [
        makePosition({ symbol: '5469.TW', market: 'tw', name: '瀚宇博' }),
        makePosition({ symbol: '9999.TW', market: 'tw', name: null }),
      ],
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const table = await desktopHoldings();
    const namedCell = table.getByText('5469.TW').closest('td') as HTMLElement;
    expect(within(namedCell).getByText('瀚宇博')).toBeInTheDocument();
    const unnamedCell = table.getByText('9999.TW').closest('td') as HTMLElement;
    expect(unnamedCell.textContent).toBe('9999.TW');
  });

  it('renders stale FX status with a manual refresh button', async () => {
    render(<PortfolioPage />);

    await waitForInitialLoad();

    expect(await screen.findByText('过期')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新汇率' })).toBeInTheDocument();
  });

  it('hides converted totals when an FX pair is missing instead of showing 1:1 sums', async () => {
    getSnapshot.mockResolvedValueOnce({
      ...makeSnapshot({ fxStale: true }),
      fxMissing: true,
      fxMissingPairs: ['USD/CNY'],
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    expect(await screen.findByText('缺汇率')).toBeInTheDocument();
    expect(screen.getByText(/缺少 USD\/CNY 汇率/)).toBeInTheDocument();
    expect(screen.queryByText(/3,000/)).not.toBeInTheDocument();
  });

  it('keeps showing converted totals when no FX pair is missing', async () => {
    getSnapshot.mockResolvedValueOnce({ ...makeSnapshot({ fxStale: true }), fxMissing: false, fxMissingPairs: [] });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    expect(await screen.findByText(/3,000/)).toBeInTheDocument();
    expect(screen.getByText('过期')).toBeInTheDocument();
    expect(screen.queryByText('缺汇率')).not.toBeInTheDocument();
  });

  it('renders portfolio risk flags and exposure dashboard from snapshot and risk data', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: false,
      positions: [
        makePosition({
          symbol: '600519',
          market: 'cn',
          currency: 'CNY',
          valuationCurrency: 'CNY',
          marketValueBase: 6000,
        }),
        makePosition({
          symbol: 'HK00700',
          market: 'hk',
          currency: 'HKD',
          valuationCurrency: 'CNY',
          marketValueBase: 4000,
          priceStale: true,
        }),
      ],
    }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        alert: true,
        topPositions: [{ symbol: '600519', marketValueBase: 6000, weightPct: 60, isAlert: true }],
      },
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: true,
        topSectors: [{ sector: '白酒', marketValueBase: 7000, weightPct: 70, symbolCount: 2, isAlert: true }],
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
      drawdown: {
        seriesPoints: 10,
        maxDrawdownPct: 18.5,
        currentDrawdownPct: 12.5,
        alert: true,
        fxStale: false,
      },
      stopLoss: {
        nearAlert: true,
        triggeredCount: 1,
        nearCount: 2,
        items: [],
      },
      decisionSignalRisk: {
        available: true,
        total: 1,
        actions: { sell: 0, reduce: 1, alert: 0 },
        items: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(dashboard).not.toBeNull();
    const dashboardScope = within(dashboard as HTMLElement);

    expect(dashboardScope.getByText('风险旗标')).toBeInTheDocument();
    expect(dashboardScope.getAllByText('需处理').length).toBeGreaterThanOrEqual(5);
    expect(dashboardScope.getByText('个股集中')).toBeInTheDocument();
    expect(dashboardScope.getByText('Top1: 600519')).toBeInTheDocument();
    expect(dashboardScope.getByText('行业集中')).toBeInTheDocument();
    expect(dashboardScope.getByText('Top1: 白酒')).toBeInTheDocument();
    expect(dashboardScope.getByText('最大回撤: 18.50%')).toBeInTheDocument();
    // The backend's nearCount (2) includes the triggered holding, so only one is merely near.
    expect(dashboardScope.getByText('已触发 1 · 接近 1')).toBeInTheDocument();
    expect(dashboardScope.getByText('缺价: 0 · 过期价: 1')).toBeInTheDocument();
    expect(dashboardScope.getAllByText('市场暴露').length).toBeGreaterThan(0);
    expect(dashboardScope.getAllByText('币种暴露').length).toBeGreaterThan(0);
    expect(dashboardScope.getByText('A 股')).toBeInTheDocument();
    expect(dashboardScope.getByText('港股')).toBeInTheDocument();
    expect(dashboardScope.getByText('CNY')).toBeInTheDocument();
    expect(dashboardScope.getByText('HKD')).toBeInTheDocument();
  });

  it('converts single-account foreign-currency exposure values into the snapshot currency', async () => {
    getSnapshot.mockResolvedValueOnce({
      asOf: '2026-03-19',
      costMethod: 'fifo' as const,
      currency: 'CNY',
      accountCount: 1,
      totalCash: 0,
      totalMarketValue: 700,
      totalEquity: 700,
      realizedPnl: 0,
      unrealizedPnl: 0,
      feeTotal: 0,
      taxTotal: 0,
      fxStale: false,
      dataQuality: 'ok',
      limitations: [],
      accounts: [
        {
          accountId: 1,
          accountName: 'USD Account',
          ownerId: null,
          broker: 'Demo',
          market: 'us',
          baseCurrency: 'USD',
          asOf: '2026-03-19',
          costMethod: 'fifo' as const,
          totalCash: 0,
          totalMarketValue: 100,
          totalEquity: 100,
          realizedPnl: 0,
          unrealizedPnl: 0,
          feeTotal: 0,
          taxTotal: 0,
          fxStale: false,
          dataQuality: 'ok',
          limitations: [],
          positions: [
            makePosition({
              symbol: 'AAPL',
              market: 'us',
              currency: 'USD',
              valuationCurrency: 'USD',
              marketValueBase: 100,
            }),
          ],
        },
      ],
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(dashboard).not.toBeNull();
    const dashboardScope = within(dashboard as HTMLElement);
    expect(dashboardScope.getByText('美股')).toBeInTheDocument();
    expect(dashboardScope.getAllByText('CNY 700.00').length).toBeGreaterThan(0);
    expect(dashboardScope.queryByText('CNY 100.00')).not.toBeInTheDocument();
    expect(dashboardScope.getAllByText('100.00%').length).toBeGreaterThan(0);
  });

  it('converts mixed CNY and USD accounts using per-account aggregate market values', async () => {
    getSnapshot.mockResolvedValueOnce({
      asOf: '2026-03-19',
      costMethod: 'fifo' as const,
      currency: 'CNY',
      accountCount: 2,
      totalCash: 0,
      totalMarketValue: 770,
      totalEquity: 770,
      realizedPnl: 0,
      unrealizedPnl: 0,
      feeTotal: 0,
      taxTotal: 0,
      fxStale: false,
      dataQuality: 'ok',
      limitations: [],
      accounts: [
        {
          accountId: 1,
          accountName: 'CNY Account',
          ownerId: null,
          broker: 'Demo',
          market: 'cn',
          baseCurrency: 'CNY',
          asOf: '2026-03-19',
          costMethod: 'fifo' as const,
          totalCash: 0,
          totalMarketValue: 70,
          totalEquity: 70,
          realizedPnl: 0,
          unrealizedPnl: 0,
          feeTotal: 0,
          taxTotal: 0,
          fxStale: false,
          dataQuality: 'ok',
          limitations: [],
          positions: [
            makePosition({
              symbol: '600519',
              market: 'cn',
              currency: 'CNY',
              valuationCurrency: 'CNY',
              marketValueBase: 70,
            }),
          ],
        },
        {
          accountId: 2,
          accountName: 'USD Account',
          ownerId: null,
          broker: 'Demo',
          market: 'us',
          baseCurrency: 'USD',
          asOf: '2026-03-19',
          costMethod: 'fifo' as const,
          totalCash: 0,
          totalMarketValue: 100,
          totalMarketValueAggregate: 700,
          totalEquity: 100,
          realizedPnl: 0,
          unrealizedPnl: 0,
          feeTotal: 0,
          taxTotal: 0,
          fxStale: false,
          dataQuality: 'ok',
          limitations: [],
          positions: [
            makePosition({
              symbol: 'AAPL',
              market: 'us',
              currency: 'USD',
              valuationCurrency: 'USD',
              marketValueBase: 100,
            }),
          ],
        },
      ],
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(dashboard).not.toBeNull();
    const dashboardScope = within(dashboard as HTMLElement);
    for (const label of ['市场暴露', '币种暴露']) {
      const exposure = dashboardScope.getByText(label).closest('div.rounded-xl');
      const scope = within(exposure as HTMLElement);
      expect(scope.getByText('CNY 70.00')).toBeInTheDocument();
      expect(scope.getByText('CNY 700.00')).toBeInTheDocument();
      expect(scope.getByText('9.09%')).toBeInTheDocument();
      expect(scope.getByText('90.91%')).toBeInTheDocument();
      expect(scope.queryByText('CNY 100.00')).not.toBeInTheDocument();
    }
    expect(dashboardScope.queryByText('暴露不可用')).not.toBeInTheDocument();
  });

  it.each(['fresh', 'stale', 'missing', 'zero-value-account'] as const)('handles three account valuation currencies with %s conversion evidence', async (evidence) => {
    const snapshot = makeSnapshot({ fxStale: false });
    const specs = [
      { currency: 'CNY', market: 'cn', symbol: '600519', raw: 70, converted: 70 },
      { currency: 'USD', market: 'us', symbol: 'AAPL', raw: 100, converted: 700 },
      { currency: 'HKD', market: 'hk', symbol: 'HK00700', raw: 200, converted: 180 },
    ];
    const accounts = specs.map((item, index) => ({
      ...snapshot.accounts[0],
      accountId: index + 1,
      baseCurrency: item.currency,
      totalMarketValue: item.raw,
      totalMarketValueAggregate: evidence === 'missing' && index === 1 ? undefined : item.converted,
      fxStale: evidence === 'stale' && index === 1,
      positions: [makePosition({
        symbol: item.symbol, market: item.market, currency: item.currency,
        valuationCurrency: item.currency, marketValueBase: item.raw,
      })],
    }));
    if (evidence === 'zero-value-account') {
      accounts.push({
        ...accounts[2], accountId: 4, totalMarketValue: 0, totalMarketValueAggregate: 0,
        positions: [makePosition({
          symbol: 'HK09988', market: 'hk', currency: 'HKD', valuationCurrency: 'HKD', marketValueBase: 0,
        })],
      });
    }
    getSnapshot.mockResolvedValueOnce({ ...snapshot, accounts, accountCount: accounts.length, totalMarketValue: 950 });

    render(<PortfolioPage />);
    await waitForInitialLoad();
    const dashboard = within(screen.getByText('风险与暴露看板').closest('section') as HTMLElement);
    if (evidence === 'stale' || evidence === 'missing') {
      expect(dashboard.getAllByText('暴露不可用')).toHaveLength(2);
      expect(dashboard.queryByText('73.68%')).not.toBeInTheDocument();
      return;
    }
    for (const label of ['市场暴露', '币种暴露']) {
      const exposure = within(dashboard.getByText(label).closest('div.rounded-xl') as HTMLElement);
      for (const value of ['CNY 700.00', 'CNY 180.00', 'CNY 70.00', '73.68%', '18.95%', '7.37%']) {
        expect(exposure.getByText(value)).toBeInTheDocument();
      }
      if (evidence === 'zero-value-account') {
        expect(exposure.getByText('持仓 2')).toBeInTheDocument();
      }
    }
  });

  it.each([NaN, Infinity, -1, undefined])('does not hide invalid position valuation %s in otherwise complete exposure', async (marketValueBase) => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: false,
      positions: [makePosition(), makePosition({ symbol: 'AAPL', market: 'us', marketValueBase })],
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();
    const dashboard = within(screen.getByText('风险与暴露看板').closest('section') as HTMLElement);
    expect(dashboard.getAllByText('暴露不可用')).toHaveLength(2);
  });

  it('distinguishes an empty portfolio from unavailable exposure', async () => {
    const snapshot = makeSnapshot({ fxStale: false });
    getSnapshot.mockResolvedValueOnce({
      ...snapshot, totalMarketValue: 0, totalEquity: 1000,
      accounts: [{ ...snapshot.accounts[0], totalMarketValue: 0, totalEquity: 1000 }],
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();
    const dashboard = within(screen.getByText('风险与暴露看板').closest('section') as HTMLElement);
    expect(dashboard.getAllByText('暂无暴露数据')).toHaveLength(2);
    expect(dashboard.getByText('总市值: CNY 0.00')).toBeInTheDocument();
    expect(dashboard.getByText('持仓: 0')).toBeInTheDocument();
    expect(screen.getByText('共 0 项')).toBeInTheDocument();
    expect(screen.getByText('当前无持仓数据')).toBeInTheDocument();
    expect(screen.getByText('最新')).toBeInTheDocument();
    expect(dashboard.queryByText('暴露不可用')).not.toBeInTheDocument();
  });

  it('labels unavailable exposure in English when FX evidence is stale', async () => {
    renderEnglishPage();
    await waitForInitialLoad();
    const dashboard = within(screen.getByText('Risk and exposure dashboard').closest('section') as HTMLElement);
    expect(dashboard.getAllByText('Exposure unavailable')).toHaveLength(2);
    expect(dashboard.queryByText('No exposure data')).not.toBeInTheDocument();
  });

  it('hides exposure breakdowns when positions mix valuation currencies under one aggregate snapshot', async () => {
    getSnapshot.mockResolvedValueOnce({
      asOf: '2026-03-19',
      costMethod: 'fifo' as const,
      currency: 'CNY',
      accountCount: 1,
      totalCash: 0,
      totalMarketValue: 1040,
      totalEquity: 1040,
      realizedPnl: 0,
      unrealizedPnl: 0,
      feeTotal: 0,
      taxTotal: 0,
      fxStale: false,
      dataQuality: 'ok',
      limitations: [],
      accounts: [
        {
          accountId: 1,
          accountName: 'Mixed FX Account',
          ownerId: null,
          broker: 'Demo',
          market: 'us',
          baseCurrency: 'USD',
          asOf: '2026-03-19',
          costMethod: 'fifo' as const,
          totalCash: 0,
          totalMarketValue: 300,
          totalEquity: 300,
          realizedPnl: 0,
          unrealizedPnl: 0,
          feeTotal: 0,
          taxTotal: 0,
          fxStale: false,
          dataQuality: 'ok',
          limitations: [],
          positions: [
            makePosition({
              symbol: 'AAPL',
              market: 'us',
              currency: 'USD',
              valuationCurrency: 'USD',
              marketValueBase: 100,
            }),
            makePosition({
              symbol: 'HK00700',
              market: 'hk',
              currency: 'HKD',
              valuationCurrency: 'HKD',
              marketValueBase: 200,
            }),
          ],
        },
      ],
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(dashboard).not.toBeNull();
    const dashboardScope = within(dashboard as HTMLElement);
    expect(dashboardScope.getAllByText('暴露不可用')).toHaveLength(2);
  });

  it('renders every market exposure group instead of silently dropping the remainder', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: false,
      positions: [
        makePosition({ symbol: '600519', market: 'cn', marketValueBase: 100 }),
        makePosition({ symbol: 'HK00700', market: 'hk', marketValueBase: 100 }),
        makePosition({ symbol: 'AAPL', market: 'us', marketValueBase: 100 }),
        makePosition({ symbol: '7203.T', market: 'jp', marketValueBase: 100 }),
        makePosition({ symbol: '005930.KS', market: 'kr', marketValueBase: 100 }),
        makePosition({ symbol: '2330.TW', market: 'tw', marketValueBase: 100 }),
      ],
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const marketExposure = screen.getByText('市场暴露').closest('div.rounded-xl');
    expect(marketExposure).not.toBeNull();
    const exposureScope = within(marketExposure as HTMLElement);
    for (const market of ['A 股', '港股', '美股', '日股', '韩股', '台股']) {
      expect(exposureScope.getByText(market)).toBeInTheDocument();
    }
  });

  it('hides exposure amounts and weights when aggregate FX uses stale fallback values', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: true,
      positions: [
        makePosition({
          symbol: 'AAPL',
          market: 'us',
          currency: 'USD',
          valuationCurrency: 'USD',
          marketValueBase: 100,
        }),
      ],
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(dashboard).not.toBeNull();
    const dashboardScope = within(dashboard as HTMLElement);
    expect(dashboardScope.getAllByText('暴露不可用')).toHaveLength(2);
    expect(dashboardScope.queryByText('CNY 100.00')).not.toBeInTheDocument();
    expect(dashboardScope.queryByText('100.00%')).not.toBeInTheDocument();
  });

  it('collapses a failed risk load into one failure row with a retry', async () => {
    getRisk.mockRejectedValueOnce(
      createApiError(
        createParsedApiError({
          title: '风险失败',
          message: '风险接口暂不可用',
        }),
      ),
    );

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const dashboard = within(await screen.findByTestId('portfolio-risk'));
    expect(await dashboard.findByText('风险模块降级')).toBeInTheDocument();
    expect(dashboard.getByText('风险接口暂不可用')).toBeInTheDocument();
    // 不再一格一格顯示不可用，也不再常駐琥珀框。
    expect(dashboard.queryByText('个股集中')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText('行业数据暂不可用，当前展示个股集中度')).not.toBeInTheDocument();

    const callsBeforeRetry = getRisk.mock.calls.length;
    fireEvent.click(dashboard.getByRole('button', { name: '重试' }));
    await waitFor(() => expect(getRisk).toHaveBeenCalledTimes(callsBeforeRetry + 1));
    expect(await dashboard.findByText('个股集中')).toBeInTheDocument();
    expect(dashboard.queryByText('风险模块降级')).not.toBeInTheDocument();
  });

  it('shows the risk skeleton while the first load is in flight', async () => {
    const pendingSnapshot = deferredPromise<ReturnType<typeof makeSnapshot>>();
    getSnapshot.mockReturnValueOnce(pendingSnapshot.promise);

    render(<PortfolioPage />);

    expect(await screen.findByTestId('portfolio-risk-skeleton')).toBeInTheDocument();
    await act(async () => {
      pendingSnapshot.resolve(makeSnapshot({ fxStale: false }));
      await pendingSnapshot.promise;
    });
    await waitFor(() => expect(screen.queryByTestId('portfolio-risk-skeleton')).not.toBeInTheDocument());
  });

  it('treats empty server risk blocks as unavailable instead of normal', async () => {
    getRisk.mockResolvedValueOnce({
      ...makeRisk(),
      concentration: {},
      sectorConcentration: {},
      drawdown: {},
      stopLoss: {},
      decisionSignalRisk: {} as never,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(dashboard).not.toBeNull();
    const dashboardScope = within(dashboard as HTMLElement);
    expect(dashboardScope.getAllByText('不可用').length).toBeGreaterThanOrEqual(5);
    expect(dashboardScope.getAllByText('—').length).toBeGreaterThanOrEqual(5);
  });

  it('treats zero-point drawdown as unavailable even when numeric fields are zero', async () => {
    getRisk.mockResolvedValueOnce(makeRisk({
      drawdown: {
        seriesPoints: 0,
        maxDrawdownPct: 0,
        currentDrawdownPct: 0,
        alert: false,
        fxStale: false,
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const drawdownFlag = screen.getByText('回撤').closest('div.rounded-xl');
    expect(drawdownFlag).not.toBeNull();
    expect(within(drawdownFlag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(within(drawdownFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
  });

  it('treats one-point drawdown as unavailable because no decline can be measured', async () => {
    getRisk.mockResolvedValueOnce(makeRisk({
      drawdown: {
        seriesPoints: 1,
        maxDrawdownPct: 0,
        currentDrawdownPct: 0,
        alert: false,
        fxStale: false,
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const drawdownFlag = screen.getByText('回撤').closest('div.rounded-xl');
    expect(drawdownFlag).not.toBeNull();
    expect(within(drawdownFlag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(within(drawdownFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
  });

  it('treats stale-FX drawdown as unavailable instead of normal', async () => {
    getRisk.mockResolvedValueOnce(makeRisk({
      drawdown: {
        seriesPoints: 10,
        maxDrawdownPct: 0,
        currentDrawdownPct: 0,
        alert: false,
        fxStale: true,
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const drawdownFlag = screen.getByText('回撤').closest('div.rounded-xl');
    expect(drawdownFlag).not.toBeNull();
    expect(within(drawdownFlag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(within(drawdownFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
  });

  it('treats stale-FX concentration summaries as unavailable instead of authoritative', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: true }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        alert: true,
        topPositions: [{ symbol: '600519', marketValueBase: 6000, weightPct: 60, isAlert: true }],
      },
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: true,
        topSectors: [{ sector: '白酒', marketValueBase: 7000, weightPct: 70, symbolCount: 2, isAlert: true }],
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    for (const label of ['个股集中', '行业集中']) {
      const flag = screen.getByText(label).closest('div.rounded-xl');
      expect(flag).not.toBeNull();
      expect(within(flag as HTMLElement).getByText('—')).toBeInTheDocument();
      expect(within(flag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    }
    expect(screen.queryByText('Top1: 白酒')).not.toBeInTheDocument();
    expect(screen.queryByText('60.00%')).not.toBeInTheDocument();
  });

  it.each<{
    priceAvailable?: boolean;
    priceSource: string;
    lastPrice: number;
    separateAccount?: boolean;
  }>([
    { priceAvailable: false, priceSource: 'missing', lastPrice: 0 },
    { priceAvailable: undefined, priceSource: 'missing', lastPrice: 0 },
    { priceAvailable: undefined, priceSource: 'history_close', lastPrice: 1600 },
    { priceAvailable: false, priceSource: 'history_close', lastPrice: 1600 },
    { priceAvailable: true, priceSource: 'missing', lastPrice: 1600 },
    { priceAvailable: true, priceSource: 'history_close', lastPrice: 0 },
    { priceAvailable: true, priceSource: 'history_close', lastPrice: -1 },
    { priceAvailable: true, priceSource: 'history_close', lastPrice: NaN },
    { priceAvailable: true, priceSource: 'history_close', lastPrice: Infinity },
    { priceAvailable: false, priceSource: 'missing', lastPrice: 0, separateAccount: true },
  ])('hides concentration and exposure conclusions for an unusable quote: %j', async ({ separateAccount = false, ...quote }) => {
    const snapshot = makeSnapshot({
      fxStale: false,
      positions: [
        makePosition({
          symbol: '600519',
          market: 'cn',
          currency: 'CNY',
          valuationCurrency: 'CNY',
          marketValueBase: 6000,
          priceAvailable: true,
        }),
        makePosition({
          symbol: 'AAPL',
          market: 'us',
          currency: 'USD',
          valuationCurrency: 'CNY',
          marketValueBase: 0,
          priceDate: null,
          priceStale: true,
          ...quote,
        }),
      ],
    });
    snapshot.totalMarketValue = 6000;
    snapshot.accounts[0].totalMarketValue = 6000;
    if (separateAccount) {
      const unpricedPosition = snapshot.accounts[0].positions.pop()!;
      snapshot.accounts.push({
        ...snapshot.accounts[0],
        accountId: 2,
        accountName: 'Account 2',
        totalMarketValue: 0,
        positions: [unpricedPosition],
      });
      snapshot.accountCount = 2;
    }
    getSnapshot.mockResolvedValueOnce(snapshot);
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 6000,
        topWeightPct: 100,
        alert: true,
        topPositions: [{ symbol: '600519', marketValueBase: 6000, weightPct: 100, isAlert: true }],
      },
      sectorConcentration: {
        totalMarketValue: 6000,
        topWeightPct: 100,
        alert: true,
        topSectors: [{ sector: '白酒', marketValueBase: 6000, weightPct: 100, symbolCount: 1, isAlert: true }],
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
      stopLoss: {
        nearAlert: true,
        triggeredCount: 1,
        nearCount: 1,
        items: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    for (const label of ['个股集中', '行业集中']) {
      const flag = screen.getByText(label).closest('div.rounded-xl');
      expect(flag).not.toBeNull();
      expect(within(flag as HTMLElement).getByText('—')).toBeInTheDocument();
      expect(within(flag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    }
    expect(screen.getAllByText('暴露不可用')).toHaveLength(2);
    expect(screen.queryByText('美股')).not.toBeInTheDocument();
    expect(screen.queryByText('100.00%')).not.toBeInTheDocument();
    const concentrationCard = screen.getByText('行业数据暂不可用，当前展示个股集中度').closest('[data-card-level]');
    expect(concentrationCard).not.toBeNull();
    const concentrationScope = within(concentrationCard as HTMLElement);
    expect(concentrationScope.getByText('暂无集中度数据')).toBeInTheDocument();
    expect(concentrationScope.getByText('板块集中度告警: 不可用')).toBeInTheDocument();
    expect(concentrationScope.getByText('Top1 权重: —')).toBeInTheDocument();
    const priceFlag = screen.getByText('价格质量').closest('div.rounded-xl');
    expect(priceFlag).not.toBeNull();
    expect(within(priceFlag as HTMLElement).getByText('缺价: 1 · 过期价: 0')).toBeInTheDocument();
    expect(within(priceFlag as HTMLElement).getByText('需处理')).toBeInTheDocument();
    const stopLossFlag = screen.getByText('止损', { exact: true }).closest('div.rounded-xl');
    expect(stopLossFlag).not.toBeNull();
    expect(within(stopLossFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
  });

  it.each([false, true])('keeps genuine 100%% concentration available with a usable quote (stale: %s)', async (priceStale) => {
    const snapshot = makeSnapshot({
      fxStale: false,
      positions: [makePosition({ priceStale })],
    });
    snapshot.totalMarketValue = 1600;
    snapshot.accounts[0].totalMarketValue = 1600;
    getSnapshot.mockResolvedValueOnce(snapshot);
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 1600,
        topWeightPct: 100,
        alert: true,
        topPositions: [{ symbol: '600519', marketValueBase: 1600, weightPct: 100, isAlert: true }],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const flag = screen.getByText('个股集中').closest('div.rounded-xl');
    expect(flag).not.toBeNull();
    const flagScope = within(flag as HTMLElement);
    expect(flagScope.getByText('100.00%')).toBeInTheDocument();
    expect(flagScope.getByText('Top1: 600519')).toBeInTheDocument();
    expect(flagScope.getByText('需处理')).toBeInTheDocument();
    expect(screen.getByText('Top1 权重: 100.00%')).toBeInTheDocument();
    expect(screen.queryByText('暂无集中度数据')).not.toBeInTheDocument();
  });

  it('uses nested account FX quality when the aggregate flag is incorrectly fresh', async () => {
    const snapshot = makeSnapshot({
      fxStale: false,
      positions: [makePosition({ marketValueBase: 6000 })],
    });
    snapshot.accounts[0].fxStale = true;
    getSnapshot.mockResolvedValueOnce(snapshot);
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 6000,
        topWeightPct: 100,
        alert: true,
        topPositions: [{ symbol: '600519', marketValueBase: 6000, weightPct: 100, isAlert: true }],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const concentrationFlag = screen.getByText('个股集中').closest('div.rounded-xl');
    expect(concentrationFlag).not.toBeNull();
    expect(within(concentrationFlag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(within(concentrationFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    expect(screen.getAllByText('暴露不可用')).toHaveLength(2);
  });

  it('collapses the risk area into one failure row when the portfolio snapshot fails', async () => {
    getSnapshot.mockRejectedValueOnce(new Error('snapshot unavailable'));

    render(<PortfolioPage />);

    await screen.findByText('snapshot unavailable');
    const dashboard = within(await screen.findByTestId('portfolio-risk'));
    expect(dashboard.queryByText('价格质量')).not.toBeInTheDocument();
    expect(dashboard.getByText('总市值: —')).toBeInTheDocument();
    expect(dashboard.queryByText(/总市值: CNY 0/)).not.toBeInTheDocument();
    expect(dashboard.getByText('持仓: —')).toBeInTheDocument();
    expect(screen.getByText('共 — 项')).toBeInTheDocument();
    expect(screen.getAllByText('持仓快照不可用').length).toBeGreaterThan(0);
    expect(screen.queryByText('当前无持仓数据')).not.toBeInTheDocument();
    expect(screen.queryByText('最新')).not.toBeInTheDocument();
  });

  it('treats partial server risk blocks as unavailable instead of normal', async () => {
    getRisk.mockResolvedValueOnce({
      ...makeRisk(),
      concentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        topPositions: [{ symbol: '600519', marketValueBase: 6000, weightPct: 60, isAlert: true }],
      } as never,
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        topSectors: [{ sector: '白酒', marketValueBase: 7000, weightPct: 70, symbolCount: 2, isAlert: true }],
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      } as never,
      drawdown: {
        seriesPoints: 10,
        maxDrawdownPct: 18.5,
        currentDrawdownPct: 12.5,
        fxStale: false,
      } as never,
      stopLoss: {
        triggeredCount: 1,
        nearCount: 2,
        items: [],
      } as never,
      decisionSignalRisk: {
        total: 1,
        actions: { sell: 0, reduce: 1, alert: 0 },
        items: [],
      } as never,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    for (const label of ['个股集中', '行业集中', '回撤', '止损', 'AI 信号']) {
      const card = screen.getByText(label).closest('div.rounded-xl');
      expect(card).not.toBeNull();
      const cardScope = within(card as HTMLElement);
      expect(cardScope.getAllByText('不可用').length).toBeGreaterThanOrEqual(1);
      expect(cardScope.getByText('—')).toBeInTheDocument();
    }

    const concentrationCard = screen.getByText('行业数据暂不可用，当前展示个股集中度').closest('[data-card-level]');
    expect(concentrationCard).not.toBeNull();
    const concentrationScope = within(concentrationCard as HTMLElement);
    expect(concentrationScope.getByText('板块集中度告警: 不可用')).toBeInTheDocument();
    expect(concentrationScope.getByText('Top1 权重: —')).toBeInTheDocument();
    expect(concentrationScope.queryByText('600519')).not.toBeInTheDocument();

  });

  it('treats an all-UNCLASSIFIED sector result as unavailable and falls back to positions', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        alert: true,
        topPositions: [{ symbol: 'AAPL', marketValueBase: 6000, weightPct: 60, isAlert: true }],
      },
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 100,
        alert: true,
        topSectors: [{
          sector: 'UNCLASSIFIED',
          marketValueBase: 10000,
          weightPct: 100,
          symbolCount: 2,
          isAlert: true,
        }],
        coverage: { classifiedCount: 0, unclassifiedCount: 2, failedCount: 0 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    expect(within(sectorFlag as HTMLElement).getByText('—')).toBeInTheDocument();

    const concentrationCard = screen.getByText('行业数据暂不可用，当前展示个股集中度').closest('[data-card-level]');
    expect(concentrationCard).not.toBeNull();
    const concentrationScope = within(concentrationCard as HTMLElement);
    expect(concentrationScope.getByText('板块集中度告警: 不可用')).toBeInTheDocument();
    expect(concentrationScope.getByText('Top1 权重: 60.00%')).toBeInTheDocument();
    expect(screen.queryByText('UNCLASSIFIED')).not.toBeInTheDocument();
  });

  it('treats partially covered sector risk as unavailable instead of presenting a subset as complete', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        alert: true,
        topSectors: [
          {
            sector: 'UNCLASSIFIED',
            marketValueBase: 6000,
            weightPct: 60,
            symbolCount: 2,
            isAlert: true,
          },
          {
            sector: 'Technology',
            marketValueBase: 4000,
            weightPct: 40,
            symbolCount: 1,
            isAlert: false,
          },
        ],
        coverage: { classifiedCount: 1, unclassifiedCount: 2, failedCount: 0 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    expect(screen.queryByText('Top1: Technology')).not.toBeInTheDocument();
    expect(screen.queryByText('40.00%')).not.toBeInTheDocument();
    const concentrationCard = screen.getByText('行业数据暂不可用，当前展示个股集中度').closest('[data-card-level]');
    expect(concentrationCard).not.toBeNull();
    const concentrationScope = within(concentrationCard as HTMLElement);
    expect(concentrationScope.getByText('板块集中度告警: 不可用')).toBeInTheDocument();
    expect(concentrationScope.getByText('Top1 权重: —')).toBeInTheDocument();
    expect(screen.queryByText('UNCLASSIFIED')).not.toBeInTheDocument();
  });

  it.each([
    { classifiedCount: 0, unclassifiedCount: 0, failedCount: 0, errors: [] },
    { classifiedCount: undefined, unclassifiedCount: 0, failedCount: 0, errors: [] },
    { classifiedCount: 1, unclassifiedCount: 1, failedCount: 0, errors: [] },
    { classifiedCount: 1, unclassifiedCount: 0, failedCount: 1, errors: [] },
    { classifiedCount: 1, unclassifiedCount: 0, failedCount: 0, errors: ['classification failed'] },
  ])('marks sector risk unavailable for incomplete classification evidence: %j', async ({ errors, ...coverage }) => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 100,
        alert: true,
        topSectors: [{ sector: 'Technology', marketValueBase: 10000, weightPct: 100, symbolCount: 1, isAlert: true }],
        coverage,
        errors,
      },
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();
    const flag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(within(flag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(within(flag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    expect(screen.getByText('板块集中度告警: 不可用')).toBeInTheDocument();
    expect(screen.queryByText('Top1: Technology')).not.toBeInTheDocument();
  });

  it('requires explicit sector coverage counters before declaring sector risk available', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: false,
        topSectors: [{ sector: '白酒', marketValueBase: 7000, weightPct: 70, symbolCount: 2, isAlert: false }],
        coverage: {},
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(within(sectorFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    expect(screen.queryByText('Top1: 白酒')).not.toBeInTheDocument();
  });

  it('requires an explicit sector error array before declaring sector risk available', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: false,
        topSectors: [{ sector: '白酒', marketValueBase: 7000, weightPct: 70, symbolCount: 2, isAlert: false }],
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
      } as never,
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(screen.queryByText('Top1: 白酒')).not.toBeInTheDocument();
  });

  it('rejects numeric-string sector weights without crashing the page', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: false,
        topSectors: [{
          sector: '白酒',
          marketValueBase: 7000,
          weightPct: '70',
          symbolCount: 2,
          isAlert: false,
        } as never],
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(screen.getByText('行业数据暂不可用，当前展示个股集中度')).toBeInTheDocument();
  });

  it('treats malformed sector rows as unavailable instead of crashing the page', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: true,
        topSectors: [{
          sector: null,
          marketValueBase: 7000,
          weightPct: 70,
          symbolCount: 2,
          isAlert: true,
        } as never],
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(screen.getByText('行业数据暂不可用，当前展示个股集中度')).toBeInTheDocument();
  });

  it('treats a malformed sector row collection as unavailable', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: true,
        topSectors: { sector: 'Technology', weightPct: 70 } as never,
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(screen.getByText('行业数据暂不可用，当前展示个股集中度')).toBeInTheDocument();
  });

  it('requires a valid top-position row before showing concentration status', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        alert: true,
        topPositions: { symbol: '600519', weightPct: 60 } as never,
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const concentrationFlag = screen.getByText('个股集中').closest('div.rounded-xl');
    expect(concentrationFlag).not.toBeNull();
    expect(within(concentrationFlag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(within(concentrationFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
  });

  it.each([
    [{ symbol: '', weightPct: 60 }, { symbol: 'AAPL', weightPct: 40 }],
    [{ symbol: '600519', weightPct: 40 }, { symbol: 'AAPL', weightPct: 60 }],
    [{ symbol: '600519', weightPct: 60 }, { symbol: '', weightPct: 40 }],
    [{ symbol: '600519', weightPct: '60' }],
    [{ symbol: '600519', weightPct: 60 }, { symbol: 'AAPL', weightPct: 70 }],
  ])('rejects inconsistent concentration rows instead of relabeling Top1: %j', async (...topPositions) => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        alert: true,
        topPositions: topPositions as never,
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const concentrationFlag = screen.getByText('个股集中').closest('div.rounded-xl');
    expect(within(concentrationFlag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(within(concentrationFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    expect(screen.queryByText('Top1: AAPL')).not.toBeInTheDocument();
    expect(screen.getByText('暂无集中度数据')).toBeInTheDocument();
  });

  it.each([
    { summary: 80, weights: [20, 80] },
    { summary: 80, weights: [70, 30] },
    { summary: 70, weights: [70, 80] },
    { summary: 120, weights: [120] },
  ])('rejects inconsistent sector Top1 evidence: %j', async ({ summary, weights }) => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 10000, topWeightPct: 60, alert: true,
        topPositions: [{ symbol: '600519', marketValueBase: 6000, weightPct: 60, isAlert: true }],
      },
      sectorConcentration: {
        totalMarketValue: 10000, topWeightPct: summary, alert: true,
        topSectors: weights.map((weightPct, index) => ({
          sector: index === 0 ? '白酒' : '科技', marketValueBase: weightPct * 100,
          weightPct, symbolCount: 1, isAlert: true,
        })),
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 }, errors: [],
      },
    }));
    render(<PortfolioPage />);
    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(within(sectorFlag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(within(sectorFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    expect(screen.queryByText('Top1: 白酒')).not.toBeInTheDocument();
    expect(screen.getByText('行业数据暂不可用，当前展示个股集中度')).toBeInTheDocument();
    expect(screen.getByText('Top1: 600519')).toBeInTheDocument();
  });

  it.each(['position', 'sector'])('keeps valid %s concentration with rounded-zero tail weights', async (kind) => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false, positions: [
      makePosition({ symbol: '600519', marketValueBase: 10000000 }),
      makePosition({ symbol: '000001', lastPrice: 1, marketValueBase: 1 }),
    ] }));
    const topPositions = [
      { symbol: '600519', marketValueBase: 10000000, weightPct: 100, isAlert: true },
      { symbol: '000001', marketValueBase: 1, weightPct: 0, isAlert: false },
    ];
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: { totalMarketValue: 10000001, topWeightPct: 100, alert: true, topPositions },
      ...(kind === 'sector' ? { sectorConcentration: {
        totalMarketValue: 10000001, topWeightPct: 100, alert: true,
        topSectors: topPositions.map((row, index) => ({ ...row, sector: index ? '银行' : '白酒', symbolCount: 1 })),
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 }, errors: [],
      } } : {}),
    }));
    render(<PortfolioPage />);
    await waitForInitialLoad();
    const flag = screen.getByText(kind === 'sector' ? '行业集中' : '个股集中').closest('div.rounded-xl');
    expect(within(flag as HTMLElement).getByText('100.00%')).toBeInTheDocument();
    expect(within(flag as HTMLElement).getByText('需处理')).toBeInTheDocument();
    expect(within(flag as HTMLElement).getByText(kind === 'sector' ? 'Top1: 白酒' : 'Top1: 600519')).toBeInTheDocument();
    expect(screen.queryByText('暂无集中度数据')).not.toBeInTheDocument();
    expect(screen.getByText(kind === 'sector' ? '行业集中度分布' : '行业数据暂不可用，当前展示个股集中度')).toBeInTheDocument();
  });

  it('marks stop-loss risk unavailable when any holding lacks a usable quote', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: false,
      positions: [makePosition({
        lastPrice: 0,
        priceAvailable: false,
        priceStale: true,
      })],
    }));
    getRisk.mockResolvedValueOnce(makeRisk({
      stopLoss: {
        nearAlert: true,
        triggeredCount: 1,
        nearCount: 0,
        items: [{ symbol: '600519' }],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const stopLossFlag = screen.getByText('止损').closest('div.rounded-xl');
    expect(stopLossFlag).not.toBeNull();
    expect(within(stopLossFlag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(within(stopLossFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
  });

  it('uses the validated sector block alert when a top row disagrees', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: true,
        topSectors: [{ sector: '白酒', marketValueBase: 7000, weightPct: 70, symbolCount: 2, isAlert: false }],
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getByText('需处理')).toBeInTheDocument();
    expect(within(sectorFlag as HTMLElement).getByText('70.00%')).toBeInTheDocument();
    expect(screen.getByText('板块集中度告警: 是')).toBeInTheDocument();
  });

  it('counts missing and stale price-quality positions without double counting missing quotes', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      positions: [
        makePosition({
          symbol: 'HK00700',
          market: 'hk',
          currency: 'HKD',
          valuationCurrency: 'CNY',
          marketValueBase: 4200,
          priceStale: true,
          priceAvailable: true,
        }),
        makePosition({
          symbol: 'AAPL',
          market: 'us',
          currency: 'USD',
          valuationCurrency: 'CNY',
          marketValueBase: 0,
          lastPrice: 0,
          priceSource: 'missing',
          priceDate: null,
          priceStale: true,
          priceAvailable: false,
        }),
      ],
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const card = screen.getByText('价格质量').closest('div.rounded-xl');
    expect(card).not.toBeNull();
    const cardScope = within(card as HTMLElement);
    expect(cardScope.getByText('2')).toBeInTheDocument();
    expect(cardScope.getByText('缺价: 1 · 过期价: 1')).toBeInTheDocument();
  });

  it('counts a missing quote once when it is also marked stale', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      positions: [
        makePosition({
          symbol: 'AAPL',
          market: 'us',
          currency: 'USD',
          valuationCurrency: 'USD',
          marketValueBase: 0,
          lastPrice: 0,
          priceSource: 'missing',
          priceDate: null,
          priceStale: true,
          priceAvailable: false,
        }),
      ],
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const card = screen.getByText('价格质量').closest('div.rounded-xl');
    expect(card).not.toBeNull();
    const cardScope = within(card as HTMLElement);
    expect(cardScope.getByText('1')).toBeInTheDocument();
    expect(cardScope.getByText('缺价: 1 · 过期价: 0')).toBeInTheDocument();
  });

  it('shows aggregate partial valuation limitations near summary totals', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      dataQuality: 'partial',
      limitations: ['realtime_quote_best_effort', 'fx_and_cost_basis_partial'],
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    expect(await screen.findByText('组合估值限制')).toBeInTheDocument();
    expect(screen.getByText(/实时行情为尽力获取/)).toBeInTheDocument();
    expect(screen.getByText(/汇率与成本基础为部分口径/)).toBeInTheDocument();
  });

  it('renders portfolio risk drawdown labels in English UI mode', async () => {
    renderEnglishPage();

    await waitForInitialLoad();

    expect(await screen.findByText('Assets')).toBeInTheDocument();
    const dashboard = within(screen.getByTestId('portfolio-risk'));
    expect(dashboard.getByText('Drawdown')).toBeInTheDocument();
    expect(dashboard.getByText('Stop loss')).toBeInTheDocument();
    expect(dashboard.getByText('AI signals')).toBeInTheDocument();
    expect(screen.queryByText('回撤')).not.toBeInTheDocument();
  });

  it('renders portfolio decision signal risk summary', async () => {
    getRisk.mockResolvedValueOnce(makeRisk({
      decisionSignalRisk: {
        available: true,
        total: 2,
        actions: { sell: 1, reduce: 0, alert: 1 },
        items: [
          {
            accountId: 1,
            symbol: '600519',
            market: 'cn',
            signal: makeDecisionSignal({ id: 201, action: 'sell', actionLabel: null }),
          },
          {
            accountId: 1,
            symbol: '300750',
            market: 'cn',
            signal: makeDecisionSignal({ id: 202, stockCode: '300750', action: 'alert', actionLabel: null }),
          },
        ],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const pending = within(screen.getByTestId('portfolio-pending'));
    expect(pending.getByText('600519 · 卖出')).toBeInTheDocument();
    expect(pending.getByText('300750 · 预警')).toBeInTheDocument();
    expect(screen.queryByText('600519 · sell')).not.toBeInTheDocument();
    expect(screen.queryByText('300750 · alert')).not.toBeInTheDocument();
  });

  it('uses the current UI language for portfolio decision signal risk action labels', async () => {
    getRisk.mockResolvedValueOnce(makeRisk({
      decisionSignalRisk: {
        available: true,
        total: 1,
        actions: { sell: 1, reduce: 0, alert: 0 },
        items: [
          {
            accountId: 1,
            symbol: '600519',
            market: 'cn',
            signal: makeDecisionSignal({ id: 203, action: 'sell', actionLabel: '卖出' }),
          },
        ],
      },
    }));

    renderEnglishPage();

    await waitForInitialLoad();

    expect(screen.getByText('600519 · Sell')).toBeInTheDocument();
    expect(screen.queryByText('600519 · 卖出')).not.toBeInTheDocument();
    expect(screen.queryByText('600519 · sell')).not.toBeInTheDocument();
  });

  it('renders portfolio decision signal risk fail-open state', async () => {
    getRisk.mockResolvedValueOnce(makeRisk({
      decisionSignalRisk: {
        available: false,
        total: 0,
        actions: { sell: 0, reduce: 0, alert: 0 },
        items: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const flag = screen.getByText('AI 信号').closest('div.rounded-xl');
    expect(within(flag as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(screen.queryByTestId('portfolio-pending')).not.toBeInTheDocument();
  });

  it('refreshes FX for a single selected account and only reloads snapshot/risk', async () => {
    getSnapshot
      .mockResolvedValueOnce(makeSnapshot({ fxStale: true }))
      .mockResolvedValueOnce(makeSnapshot({ accountId: 1, fxStale: true }))
      .mockResolvedValueOnce(makeSnapshot({ accountId: 1, fxStale: false }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    selectAccount('Main');

    await waitFor(() => {
      expect(getSnapshot).toHaveBeenLastCalledWith(snapshotQuery(1));
    });

    const snapshotCallsBeforeRefresh = getSnapshot.mock.calls.length;
    const riskCallsBeforeRefresh = getRisk.mock.calls.length;
    const tradeCallsBeforeRefresh = listTrades.mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    await waitFor(() => expect(refreshFx).toHaveBeenCalledWith({ accountId: 1 }));
    expect(await screen.findByText('汇率已刷新，共更新 1 对。')).toBeInTheDocument();
    await waitFor(() => expect(getSnapshot).toHaveBeenCalledTimes(snapshotCallsBeforeRefresh + 1));
    await waitFor(() => expect(getRisk).toHaveBeenCalledTimes(riskCallsBeforeRefresh + 1));
    expect(listTrades).toHaveBeenCalledTimes(tradeCallsBeforeRefresh);
    expect(listCashLedger).not.toHaveBeenCalled();
    expect(listCorporateActions).not.toHaveBeenCalled();
    expect(screen.getByText('最新')).toBeInTheDocument();
  });

  it('refreshes FX for the full portfolio without sending accountId and shows neutral feedback when no pair exists', async () => {
    refreshFx.mockResolvedValueOnce({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: true,
      disabledReason: null,
      pairCount: 0,
      updatedCount: 0,
      staleCount: 0,
      errorCount: 0,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    await waitFor(() => expect(refreshFx).toHaveBeenCalledWith({ accountId: undefined }));
    expect(await screen.findByText('当前范围无可刷新的汇率对。')).toBeInTheDocument();
  });

  it('shows disabled feedback when FX online refresh is disabled even without a disabled reason', async () => {
    refreshFx.mockResolvedValueOnce({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: false,
      pairCount: 1,
      updatedCount: 0,
      staleCount: 0,
      errorCount: 0,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    expect(await screen.findByText('汇率在线刷新已被禁用。')).toBeInTheDocument();
  });

  it('renders backend-provided position valuation fields and stale missing-price hint', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: true, positions: [
      { symbol: 'HK00700', market: 'hk', currency: 'HKD', quantity: 10, avgCost: 400, totalCost: 4000, lastPrice: 420, marketValueBase: 4200, unrealizedPnlBase: 200, unrealizedPnlPct: 5, valuationCurrency: 'HKD', priceSource: 'history_close', priceDate: '2026-03-18', priceStale: true, priceAvailable: true },
      { symbol: 'AAPL', market: 'us', currency: 'USD', quantity: 5, avgCost: 100, totalCost: 500, lastPrice: 0, marketValueBase: 0, unrealizedPnlBase: 0, unrealizedPnlPct: null, valuationCurrency: 'USD', priceSource: 'missing', priceDate: null, priceStale: true, priceAvailable: false },
    ] }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const table = await desktopHoldings();
    expect(table.getByText('HK00700')).toBeInTheDocument();
    expect(table.getByText('420.00')).toBeInTheDocument();
    // The HKD group subtotal row now repeats value and P&L (W09), so scope to the holding row.
    const hkHoldingRow = within(table.getByText('HK00700').closest('tr') as HTMLTableRowElement);
    expect(hkHoldingRow.getByText('HKD 4,200.00')).toBeInTheDocument();
    expect(hkHoldingRow.getByText('+5.00%')).toBeInTheDocument();
    expect(table.getByText('收盘价 · 2026-03-18')).toBeInTheDocument();
    expect(table.getByText('缺价')).toBeInTheDocument();
    expect(table.getAllByText('—').length).toBeGreaterThanOrEqual(2);

    const hkRow = table.getByText('HK00700').closest('tr');
    const aaplRow = table.getByText('AAPL').closest('tr');
    expect(hkRow).not.toBeNull();
    expect(aaplRow).not.toBeNull();

    expect(within(hkRow as HTMLTableRowElement).getByTestId('holding-pnl')).toHaveClass('text-market-up');
    expect(within(aaplRow as HTMLTableRowElement).getByTestId('holding-pnl')).toHaveClass('text-secondary');
  });

  it('loads latest active signals for holdings without scanning paginated signal lists', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ positions: [
      { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
    ] }));
    const latestSignal = makeDecisionSignal({
      id: 101,
      stockCode: '600519',
      riskSummary: '分页后的风险摘要',
      watchConditions: '分页后的观察条件',
    });
    getLatestDecisionSignals.mockResolvedValueOnce({ items: [latestSignal], total: 1, page: 1, pageSize: 1 });

    render(<PortfolioPage />);

    expect((await desktopHoldings()).getByText('600519')).toBeInTheDocument();
    expect(await screen.findByLabelText('分页后的风险摘要')).toBeInTheDocument();
    expect(decisionSignalsApi.getLatest).toHaveBeenCalledWith('600519', {
      market: 'cn',
      limit: 1,
    });
    // The grouped list missed this holding, so it fell back to the per-stock endpoint.
    expect(decisionSignalsApi.list).toHaveBeenCalledTimes(1);
  });

  it('refreshes holding signals when manually refreshing unchanged portfolio data', async () => {
    const position = { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true };
    getSnapshot.mockResolvedValue(makeSnapshot({ positions: [position] }));
    getLatestDecisionSignals
      .mockResolvedValueOnce({
        items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '旧 AI 风险' })],
        total: 1,
        page: 1,
        pageSize: 1,
      })
      .mockResolvedValueOnce({
        items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '新 AI 风险' })],
        total: 1,
        page: 1,
        pageSize: 1,
      });

    render(<PortfolioPage />);

    expect(await screen.findByLabelText('旧 AI 风险')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新数据' }));

    expect(await screen.findByLabelText('新 AI 风险')).toBeInTheDocument();
    await waitFor(() => expect(getLatestDecisionSignals).toHaveBeenCalledTimes(2));
    expect(screen.queryByLabelText('旧 AI 风险')).not.toBeInTheDocument();
  });

  it('waits for the selected-account snapshot before loading account-scoped holding signals', async () => {
    getAccounts.mockResolvedValueOnce(makeAccounts([
      { id: 1, name: 'Main' },
      { id: 2, name: 'Alt' },
    ]));
    const accountTwoSnapshot = deferredPromise<ReturnType<typeof makeSnapshot>>();
    getSnapshot
      .mockResolvedValueOnce(makeSnapshot({
        accountCount: 2,
        positions: [
          { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
        ],
      }))
      .mockReturnValueOnce(accountTwoSnapshot.promise);
    getLatestDecisionSignals.mockResolvedValue({
      items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '账号信号' })],
      total: 1,
      page: 1,
      pageSize: 1,
    });

    render(<PortfolioPage />);

    expect(await screen.findByLabelText('账号信号')).toBeInTheDocument();
    const signalCallsBeforeSwitch = getLatestDecisionSignals.mock.calls.length;

    selectAccount('Alt');

    await waitFor(() => {
      expect(getSnapshot).toHaveBeenLastCalledWith(snapshotQuery(2));
    });
    expect(screen.queryByLabelText('账号信号')).not.toBeInTheDocument();
    expect(getLatestDecisionSignals).toHaveBeenCalledTimes(signalCallsBeforeSwitch);

    await act(async () => {
      accountTwoSnapshot.resolve(makeSnapshot({
        accountId: 2,
        positions: [
          { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
        ],
      }));
      await accountTwoSnapshot.promise;
    });

    await waitFor(() => {
      expect(getLatestDecisionSignals).toHaveBeenLastCalledWith('600519', {
        market: 'cn',
        limit: 1,
      });
    });
  });

  it('drops late holding-signal responses after switching account scope', async () => {
    getAccounts.mockResolvedValueOnce(makeAccounts([
      { id: 1, name: 'Main' },
      { id: 2, name: 'Alt' },
    ]));
    getSnapshot
      .mockResolvedValueOnce(makeSnapshot({
        accountCount: 2,
        positions: [
          { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
        ],
      }))
      .mockResolvedValueOnce(makeSnapshot({
        accountId: 2,
        positions: [
          { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
        ],
      }));
    const oldSignals = deferredPromise<{
      items: DecisionSignalItem[];
      total: number;
      page: number;
      pageSize: number;
    }>();
    getLatestDecisionSignals
      .mockReturnValueOnce(oldSignals.promise)
      .mockResolvedValueOnce({
        items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '新账号信号' })],
        total: 1,
        page: 1,
        pageSize: 1,
      });

    render(<PortfolioPage />);

    await desktopHoldings();

    selectAccount('Alt');

    expect(await screen.findByLabelText('新账号信号')).toBeInTheDocument();

    await act(async () => {
      oldSignals.resolve({
        items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '旧账号晚返回信号' })],
        total: 1,
        page: 1,
        pageSize: 1,
      });
      await oldSignals.promise;
    });

    expect(screen.getByLabelText('新账号信号')).toBeInTheDocument();
    expect(screen.queryByLabelText('旧账号晚返回信号')).not.toBeInTheDocument();
  });

  it('matches holding signals by stock-code equivalence and leaves unmatched rows empty', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ positions: [
      { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
      { symbol: 'SH600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
      { symbol: '00700.HK', market: 'hk', currency: 'HKD', quantity: 10, avgCost: 400, totalCost: 4000, lastPrice: 420, marketValueBase: 4200, unrealizedPnlBase: 200, unrealizedPnlPct: 5, valuationCurrency: 'HKD', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
      { symbol: 'AAPL', market: 'us', currency: 'USD', quantity: 2, avgCost: 180, totalCost: 360, lastPrice: 190, marketValueBase: 380, unrealizedPnlBase: 20, unrealizedPnlPct: 5.56, valuationCurrency: 'USD', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
    ] }));
    getLatestDecisionSignals.mockImplementation(async (stockCode: string) => {
      if (stockCode.includes('600519')) {
        return {
          items: [makeDecisionSignal({ id: 1, stockCode: '600519', market: 'cn', riskSummary: 'A 股风险' })],
          total: 1,
          page: 1,
          pageSize: 1,
        };
      }
      if (stockCode.includes('00700')) {
        return {
          items: [makeDecisionSignal({ id: 2, stockCode: 'HK00700', market: 'hk', riskSummary: '港股风险', watchConditions: '观察回购' })],
          total: 1,
          page: 1,
          pageSize: 1,
        };
      }
      return { items: [], total: 0, page: 1, pageSize: 1 };
    });

    render(<PortfolioPage />);

    expect(await screen.findAllByLabelText('A 股风险')).toHaveLength(2);
    expect(screen.getByLabelText('港股风险')).toBeInTheDocument();
    const latestLookupSymbols = getLatestDecisionSignals.mock.calls.map(([stockCode]) => String(stockCode));
    expect(latestLookupSymbols.filter((stockCode) => stockCode.includes('600519'))).toEqual(['600519']);
    expect(getLatestDecisionSignals).toHaveBeenCalledTimes(3);
    expect(getLatestDecisionSignals).toHaveBeenCalledWith('00700.HK', {
      market: 'hk',
      limit: 1,
    });
    const aaplRow = (await desktopHoldings()).getByText('AAPL').closest('tr');
    expect(aaplRow).not.toBeNull();
    expect(within(aaplRow as HTMLTableRowElement).queryByLabelText(/风险/)).not.toBeInTheDocument();
  });

  it('shows a visible partial warning when one latest holding signal lookup fails', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ positions: [
      { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
      { symbol: 'AAPL', market: 'us', currency: 'USD', quantity: 2, avgCost: 180, totalCost: 360, lastPrice: 190, marketValueBase: 380, unrealizedPnlBase: 20, unrealizedPnlPct: 5.56, valuationCurrency: 'USD', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
    ] }));
    getLatestDecisionSignals
      .mockResolvedValueOnce({
        items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '已加载风险' })],
        total: 1,
        page: 1,
        pageSize: 1,
      })
      .mockRejectedValueOnce(new Error('latest AAPL failed'));

    render(<PortfolioPage />);

    expect(await screen.findByLabelText('已加载风险')).toBeInTheDocument();
    expect(await screen.findByText('AI 建议降级')).toBeInTheDocument();
    expect(screen.getByText(/latest AAPL failed/)).toBeInTheDocument();
  });

  it('loads each unique holding through the latest endpoint once', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ positions: [
      { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
      { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 2, avgCost: 1500, totalCost: 3000, lastPrice: 1600, marketValueBase: 3200, unrealizedPnlBase: 200, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
    ] }));
    getLatestDecisionSignals.mockResolvedValueOnce({
      items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '唯一 latest 风险' })],
      total: 1,
      page: 1,
      pageSize: 1,
    });

    render(<PortfolioPage />);

    // 同一檔已合併成一列。
    expect(await screen.findAllByLabelText('唯一 latest 风险')).toHaveLength(1);
    expect(getLatestDecisionSignals).toHaveBeenCalledTimes(1);
    expect(decisionSignalsApi.list).toHaveBeenCalledTimes(1);
  });

  it('limits concurrent latest lookups for large portfolios', async () => {
    const positions = Array.from({ length: 10 }, (_, index) => makePosition({
      symbol: `AAPL${index}`,
      market: 'us',
      currency: 'USD',
      totalCost: 100 + index,
      marketValueBase: 120 + index,
    }));
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ positions }));
    let inFlight = 0;
    let maxInFlight = 0;
    getLatestDecisionSignals.mockImplementation(async () => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 5));
      inFlight -= 1;
      return { items: [], total: 0, page: 1, pageSize: 1 };
    });

    render(<PortfolioPage />);

    expect((await desktopHoldings()).getByText('AAPL0')).toBeInTheDocument();
    await waitFor(() => expect(getLatestDecisionSignals).toHaveBeenCalledTimes(10));
    await waitFor(() => expect(inFlight).toBe(0));
    expect(maxInFlight).toBeLessThanOrEqual(6);
  });

  it('submits manual analysis for a held position without exposing portfolio details in the UI call', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: true, positions: [
      { symbol: 'HK00700', market: 'hk', currency: 'HKD', quantity: 10, avgCost: 400, totalCost: 4000, lastPrice: 420, marketValueBase: 4200, unrealizedPnlBase: 200, unrealizedPnlPct: 5, valuationCurrency: 'HKD', priceSource: 'history_close', priceDate: '2026-03-18', priceStale: true, priceAvailable: true },
    ] }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const row = (await desktopHoldings()).getByText('HK00700').closest('tr');
    expect(row).not.toBeNull();
    fireEvent.click(within(row as HTMLTableRowElement).getByRole('button', { name: 'HK00700 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '分析' }));

    await waitFor(() => {
      expect(analyzePosition).toHaveBeenCalledWith('HK00700', {
        accountId: 1,
        analysisPhase: 'auto',
        force: false,
      });
    });
    expect(await screen.findByText('已提交 HK00700 分析任务：task-portfolio-1')).toBeInTheDocument();
  });

  it('prefers disabled feedback over empty-pair feedback when refresh is disabled', async () => {
    refreshFx.mockResolvedValueOnce({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: false,
      disabledReason: 'portfolio_fx_update_disabled',
      pairCount: 0,
      updatedCount: 0,
      staleCount: 0,
      errorCount: 0,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    expect(await screen.findByText('汇率在线刷新已被禁用。')).toBeInTheDocument();
    expect(screen.queryByText('当前范围无可刷新的汇率对。')).not.toBeInTheDocument();
  });

  it('shows warning feedback when FX refresh still falls back to stale rates', async () => {
    refreshFx.mockResolvedValueOnce({
      asOf: '2026-03-19',
      accountCount: 1,
      pairCount: 2,
      updatedCount: 1,
      staleCount: 1,
      errorCount: 0,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    expect(await screen.findByText(/stale\/fallback 汇率/)).toBeInTheDocument();
  });

  it('shows warning feedback when FX refresh returns online errors without stale pairs', async () => {
    refreshFx.mockResolvedValueOnce({
      asOf: '2026-03-19',
      accountCount: 1,
      pairCount: 1,
      updatedCount: 0,
      staleCount: 0,
      errorCount: 1,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const snapshotCallsBeforeRefresh = getSnapshot.mock.calls.length;
    const riskCallsBeforeRefresh = getRisk.mock.calls.length;
    const tradeCallsBeforeRefresh = listTrades.mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    expect(await screen.findByText(/在线刷新未完全成功/)).toBeInTheDocument();
    await waitFor(() => expect(getSnapshot).toHaveBeenCalledTimes(snapshotCallsBeforeRefresh + 1));
    await waitFor(() => expect(getRisk).toHaveBeenCalledTimes(riskCallsBeforeRefresh + 1));
    expect(listTrades).toHaveBeenCalledTimes(tradeCallsBeforeRefresh);
    expect(listCashLedger).not.toHaveBeenCalled();
    expect(listCorporateActions).not.toHaveBeenCalled();
  });

  it('restores the button state and shows the existing error alert when FX refresh fails', async () => {
    refreshFx.mockRejectedValueOnce(
      createApiError(
        createParsedApiError({
          title: '刷新失败',
          message: '汇率服务暂时不可用',
        }),
      ),
    );

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const refreshButton = screen.getByRole('button', { name: '刷新汇率' });
    fireEvent.click(refreshButton);

    const fxAlertTitle = await screen.findByText('刷新失败');
    expect(fxAlertTitle.closest('[role="alert"]')).toHaveTextContent('汇率服务暂时不可用');
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新汇率' })).not.toBeDisabled());
  });

  it('does not keep success feedback when snapshot reload fails after FX refresh succeeds', async () => {
    getSnapshot
      .mockResolvedValueOnce(makeSnapshot({ fxStale: true }))
      .mockRejectedValueOnce(
        createApiError(
          createParsedApiError({
            title: '快照刷新失败',
            message: '无法加载最新持仓快照',
          }),
        ),
      );

    render(<PortfolioPage />);

    await waitForInitialLoad();

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    const fxAlertTitle = await screen.findByText('快照刷新失败');
    expect(fxAlertTitle.closest('[role="alert"]')).toHaveTextContent('无法加载最新持仓快照');
    await waitFor(() => expect(screen.queryByText('汇率已刷新，共更新 1 对。')).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新汇率' })).not.toBeDisabled());
  });

  it('drops late FX refresh results after switching to another account scope', async () => {
    getAccounts.mockResolvedValueOnce(makeAccounts([{ id: 1, name: 'Main' }, { id: 2, name: 'Alt' }]));
    getSnapshot.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 2) {
        return makeSnapshot({ accountId: 2, fxStale: false });
      }
      return makeSnapshot({ accountId: accountId ?? 1, fxStale: true, accountCount: accountId ? 1 : 2 });
    });

    const pendingRefresh = deferredPromise<{
      asOf: string;
      accountCount: number;
      pairCount: number;
      updatedCount: number;
      staleCount: number;
      errorCount: number;
    }>();
    refreshFx.mockImplementationOnce(() => pendingRefresh.promise);

    render(<PortfolioPage />);

    await waitForInitialLoad();

    selectAccount('Main');
    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith(snapshotQuery(1)));

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));
    expect(await screen.findByRole('button', { name: '刷新中...' })).toBeDisabled();

    selectAccount('Alt');
    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith(snapshotQuery(2)));
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新汇率' })).not.toBeDisabled());

    const snapshotCallsAfterSwitch = getSnapshot.mock.calls.length;
    const riskCallsAfterSwitch = getRisk.mock.calls.length;

    await act(async () => {
      pendingRefresh.resolve({
        asOf: '2026-03-19',
        accountCount: 1,
        pairCount: 1,
        updatedCount: 1,
        staleCount: 0,
        errorCount: 0,
      });
      await pendingRefresh.promise;
    });

    expect(getSnapshot).toHaveBeenCalledTimes(snapshotCallsAfterSwitch);
    expect(getRisk).toHaveBeenCalledTimes(riskCallsAfterSwitch);
    expect(screen.queryByText('汇率已刷新，共更新 1 对。')).not.toBeInTheDocument();
  });

  it('drops late FX refresh results after switching cost method', async () => {
    const pendingRefresh = deferredPromise<{
      asOf: string;
      accountCount: number;
      pairCount: number;
      updatedCount: number;
      staleCount: number;
      errorCount: number;
    }>();
    refreshFx.mockImplementationOnce(() => pendingRefresh.promise);

    render(<PortfolioPage />);

    await waitForInitialLoad();

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));
    expect(await screen.findByRole('button', { name: '刷新中...' })).toBeDisabled();

    openPageMenu();
    fireEvent.click(screen.getByRole('radio', { name: '均价成本（AVG）' }));
    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith(snapshotQuery(undefined, 'avg')));
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新汇率' })).not.toBeDisabled());

    const snapshotCallsAfterSwitch = getSnapshot.mock.calls.length;
    const riskCallsAfterSwitch = getRisk.mock.calls.length;

    await act(async () => {
      pendingRefresh.resolve({
        asOf: '2026-03-19',
        accountCount: 1,
        pairCount: 1,
        updatedCount: 1,
        staleCount: 0,
        errorCount: 0,
      });
      await pendingRefresh.promise;
    });

    expect(getSnapshot).toHaveBeenCalledTimes(snapshotCallsAfterSwitch);
    expect(getRisk).toHaveBeenCalledTimes(riskCallsAfterSwitch);
    expect(screen.queryByText('汇率已刷新，共更新 1 对。')).not.toBeInTheDocument();
  });

  it('turns pasted broker inventory rows without cost into a fill-in template instead of committing them', async () => {
    parseTextImport.mockResolvedValueOnce({
      broker: 'text',
      recordCount: 1,
      skippedCount: 1,
      errorCount: 0,
      records: [{ tradeDate: '2026-10-15', symbol: '2303.TW', side: 'buy', quantity: 450, price: 142.5, fee: 0, tax: 0, dedupHash: 'h' }],
      errors: [],
      missingCost: [{ line: 2, symbol: '00631L.TW', name: '元大台灣50正2', quantity: 2000 }],
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();
    fireEvent.click(screen.getByRole('button', { name: '导入' }));

    const textarea = screen.getByLabelText('粘贴持仓');
    fireEvent.change(textarea, { target: { value: '元大台灣50正2\t2,000\t2,000\t\t79,560\n聯電 450 142.5' } });
    fireEvent.click(screen.getByRole('button', { name: '解析内容' }));

    await waitFor(() => expect(parseTextImport).toHaveBeenCalledWith(1, expect.stringContaining('聯電'), expect.any(String)));
    expect(await screen.findByText(/缺成本：元大台灣50正2 00631L.TW × 2000/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '转成待填范本' }));
    expect((textarea as HTMLTextAreaElement).value).toBe('2303.TW 450 142.5 2026-10-15\n00631L.TW 2000 ');
    expect(commitTextImport).not.toHaveBeenCalled();
  });

  it('deactivates the selected account from the account toolbar and reloads accounts', async () => {
    getAccounts
      .mockResolvedValueOnce(makeAccounts([{ id: 1, name: 'Main' }, { id: 2, name: 'Alt' }]))
      .mockResolvedValueOnce(makeAccounts([{ id: 2, name: 'Alt' }]));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    selectAccount('Main');

    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith(snapshotQuery(1)));
    openPageMenu();
    fireEvent.click(screen.getByRole('menuitem', { name: '删除账户' }));

    const dialog = await screen.findByText('删除持仓账户');
    expect(dialog.closest('[role="dialog"]') ?? document.body).toHaveTextContent(
      '删除后该账户会从默认列表、快照、风险和录入入口隐藏',
    );
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }));

    await waitFor(() => expect(deleteAccount).toHaveBeenCalledWith(1));
    await waitFor(() => expect(getAccounts).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('radio', { name: 'Main' })).not.toBeInTheDocument());
    expect(screen.getByRole('radio', { name: 'Alt' })).toBeInTheDocument();
  });

  function makeConsolidatedSnapshot(overrides: Record<string, unknown> = {}) {
    return {
      ...makeSnapshot({ fxStale: false }),
      displayCurrency: 'TWD',
      consolidatedEquityBase: 500000,
      consolidatedMarketValueBase: 400000,
      consolidatedCashBase: 100000,
      consolidatedUnrealizedPnlBase: 20000,
      consolidatedRealizedPnlBase: -3000,
      consolidatedDayPnlBase: 1500,
      consolidatedFundValueBase: 200000,
      consolidatedFundDayPnlBase: 500,
      consolidatedFxStale: false,
      consolidatedFxMissing: false,
      consolidatedFxMissingPairs: [],
      ...overrides,
    };
  }

  it('shows total assets in TWD from consolidated fields, adding funds, and never the CNY totals', async () => {
    getSnapshot.mockResolvedValueOnce(makeConsolidatedSnapshot());

    render(<PortfolioPage />);
    await waitForInitialLoad();

    // Summary amounts: NT$ unit prefix rendered separately, TWD without decimals.
    expect(await screen.findByText('700,000')).toBeInTheDocument();
    expect(screen.getByText('含基金 NT$ 200,000')).toBeInTheDocument();
    expect(screen.getByText('+2,000')).toBeInTheDocument();
    expect(screen.getAllByText('NT$').length).toBeGreaterThan(0);
    expect(screen.queryByText('CNY 3,000.00')).not.toBeInTheDocument();
    expect(screen.queryByText(/^3,000$/)).not.toBeInTheDocument();
  });

  it('keeps today P&L unknown when funds have value but no day P&L', async () => {
    getSnapshot.mockResolvedValueOnce(makeConsolidatedSnapshot({
      consolidatedDayPnlBase: 777,
      consolidatedFundValueBase: 20000,
      consolidatedFundDayPnlBase: null,
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();

    await screen.findByText('520,000');
    expect(screen.queryByText('+777')).not.toBeInTheDocument();
  });

  it('does not count missing fund value as zero and says the total excludes funds', async () => {
    getSnapshot.mockResolvedValueOnce(makeConsolidatedSnapshot({
      consolidatedFundValueBase: null,
      consolidatedFundDayPnlBase: null,
      fundsError: 'fund_data_unavailable',
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();

    expect(await screen.findByText('500,000')).toBeInTheDocument();
    expect(screen.getByText('不含基金（基金资料暂时无法取得）')).toBeInTheDocument();
  });

  it('hides consolidated totals when a display FX pair is missing instead of falling back to CNY', async () => {
    getSnapshot.mockResolvedValueOnce(makeConsolidatedSnapshot({
      consolidatedEquityBase: null,
      consolidatedMarketValueBase: null,
      consolidatedCashBase: null,
      consolidatedUnrealizedPnlBase: null,
      consolidatedRealizedPnlBase: null,
      consolidatedDayPnlBase: null,
      consolidatedFxMissing: true,
      consolidatedFxMissingPairs: ['USD/TWD'],
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();

    expect(await screen.findByText('缺汇率')).toBeInTheDocument();
    expect(screen.getByText(/缺少 USD\/TWD 汇率/)).toBeInTheDocument();
    expect(screen.queryByText(/3,000/)).not.toBeInTheDocument();
  });

  it('converts exposure amounts into the display currency without changing weights', async () => {
    getSnapshot.mockResolvedValueOnce(makeConsolidatedSnapshot({
      totalMarketValue: 2000,
      consolidatedMarketValueBase: 9000,
      accounts: [{
        ...makeSnapshot({ fxStale: false }).accounts[0],
        positions: [makePosition({ marketValueBase: 2000 })],
      }],
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const dashboard = within(await screen.findByTestId('portfolio-risk'));
    expect(dashboard.getByText('总市值: TWD 9,000.00')).toBeInTheDocument();
    expect(dashboard.getAllByText('TWD 9,000.00').length).toBeGreaterThan(0);
    expect(dashboard.queryByText('CNY 2,000.00')).not.toBeInTheDocument();
    expect(dashboard.getAllByText('100.00%').length).toBeGreaterThan(0);
  });

  it('lists only anomalies in the pending section and jumps to the row', async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: false,
      positions: [makePosition({ symbol: '2330.TW', market: 'tw' }), makePosition({ symbol: '2303.TW', market: 'tw' })],
    }));
    getRisk.mockResolvedValueOnce(makeRisk({
      stopLoss: {
        nearAlert: true,
        triggeredCount: 1,
        nearCount: 0,
        items: [{ accountId: 1, symbol: '2330.TW', avgCost: 100, lastPrice: 80, lossPct: 20, nearThresholdPct: 12, isTriggered: true }],
      },
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const pending = within(await screen.findByTestId('portfolio-pending'));
    expect(pending.getAllByRole('listitem')).toHaveLength(1);
    fireEvent.click(pending.getByRole('button', { name: /2330\.TW/ }));
    const row = (await desktopHoldings()).getByText('2330.TW').closest('tr') as HTMLElement;
    await waitFor(() => expect(row).toHaveAttribute('data-row-highlighted', 'true'));
    expect(scrollIntoView).toHaveBeenCalled();
  });

  it('hides the pending section when nothing is abnormal', async () => {
    render(<PortfolioPage />);
    await waitForInitialLoad();
    await screen.findByText('风险旗标');
    expect(screen.queryByTestId('portfolio-pending')).not.toBeInTheDocument();
  });

  it('prompts to backfill negative cash and opens the cash form on that account', async () => {
    getAccounts.mockResolvedValueOnce(makeAccounts([{ id: 1, name: 'Main' }, { id: 2, name: 'Alt' }]));
    const snapshot = makeSnapshot({ accountId: 2, fxStale: false });
    snapshot.accounts[0].totalCash = -500;
    getSnapshot.mockResolvedValueOnce(snapshot);

    render(<PortfolioPage />);
    await waitForInitialLoad();

    fireEvent.click(await screen.findByRole('button', { name: '补记' }));
    expect(screen.getByRole('button', { name: '提交资金流水' })).toBeInTheDocument();
    const accountSelect = screen.getByRole('combobox', { name: /帐户/ }) as HTMLSelectElement;
    expect(accountSelect.value).toBe('2');
  });

  it('merges one symbol across accounts and offers analysis per account', async () => {
    getAccounts.mockResolvedValueOnce(makeAccounts([{ id: 1, name: 'Main' }, { id: 2, name: 'Alt' }]));
    const base = makeSnapshot({ fxStale: false, accountCount: 2 });
    const account = base.accounts[0];
    getSnapshot.mockResolvedValueOnce({
      ...base,
      accounts: [
        { ...account, accountId: 1, accountName: 'Main', positions: [makePosition({ symbol: '2330.TW', market: 'tw', quantity: 1, avgCost: 100, marketValueBase: 300, unrealizedPnlBase: 100 })] },
        { ...account, accountId: 2, accountName: 'Alt', positions: [makePosition({ symbol: '2330.TW', market: 'tw', quantity: 3, avgCost: 200, marketValueBase: 900, unrealizedPnlBase: 100 })] },
      ],
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const table = await desktopHoldings();
    expect(table.getAllByText('2330.TW')).toHaveLength(1);
    expect(table.getByText('Main、Alt')).toBeInTheDocument();
    // 成本均價（100×1＋200×3）÷4＝175；報酬 200÷(1200−200)＝20%。
    expect(table.getByText('成本 175')).toBeInTheDocument();
    expect(table.getAllByText('+20.00%').length).toBeGreaterThan(0);

    fireEvent.click(table.getByRole('button', { name: '2330.TW 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '分析（Alt）' }));
    await waitFor(() => expect(analyzePosition).toHaveBeenCalledWith('2330.TW', {
      accountId: 2,
      analysisPhase: 'auto',
      force: false,
    }));
  });

  it('groups holdings by market with Taiwan first and subtotals in one currency', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: false,
      positions: [
        makePosition({ symbol: 'AAPL', market: 'us', marketValueBase: 900, unrealizedPnlBase: 90 }),
        makePosition({ symbol: '2330.TW', market: 'tw', marketValueBase: 300, unrealizedPnlBase: 30 }),
        makePosition({ symbol: '2303.TW', market: 'tw', marketValueBase: 100, unrealizedPnlBase: 10 }),
      ],
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const table = await desktopHoldings();
    const groups = document.querySelectorAll('[data-testid="data-table-desktop"] tr[data-row-group]');
    expect(Array.from(groups).map((row) => row.getAttribute('data-row-group'))).toEqual(['tw', 'us']);
    const taiwan = table.getByText('台股（2 档）').closest('tr') as HTMLElement;
    expect(within(taiwan).getByText('CNY 400.00')).toBeInTheDocument();
    expect(within(taiwan).getByText('30.77%')).toBeInTheDocument();
  });

  it('sorts holdings by value and flips on a second click', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: false,
      positions: [
        makePosition({ symbol: '2303.TW', market: 'tw', marketValueBase: 100 }),
        makePosition({ symbol: '2330.TW', market: 'tw', marketValueBase: 300 }),
      ],
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const table = await desktopHoldings();
    const order = () => Array.from(document.querySelectorAll('[data-testid="data-table-desktop"] tr[data-row-key]'))
      .map((row) => row.getAttribute('data-row-key'));
    expect(order()[0]).toContain('2330.TW');
    fireEvent.click(table.getByRole('button', { name: /^市值/ }));
    expect(order()[0]).toContain('2303.TW');
  });

  it('keeps weights for a single currency even when aggregate FX is stale', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: true,
      positions: [
        makePosition({ symbol: '2330.TW', market: 'tw', valuationCurrency: 'TWD', marketValueBase: 300 }),
        makePosition({ symbol: '2303.TW', market: 'tw', valuationCurrency: 'TWD', marketValueBase: 100 }),
      ],
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();
    expect((await desktopHoldings()).getByText('75.00%')).toBeInTheDocument();
  });

  it('blanks weights when positions span currencies and FX is stale', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: true,
      positions: [
        makePosition({ symbol: '2330.TW', market: 'tw', valuationCurrency: 'TWD', marketValueBase: 300 }),
        makePosition({ symbol: 'AAPL', market: 'us', valuationCurrency: 'USD', marketValueBase: 100 }),
      ],
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();
    expect((await desktopHoldings()).queryByText('75.00%')).not.toBeInTheDocument();
  });

  it('ranks every holding as bars instead of the Top 6 pie', async () => {
    const topPositions = Array.from({ length: 8 }, (_, index) => ({
      symbol: `S${index}`, marketValueBase: 100 - index, weightPct: 20 - index, isAlert: false,
    }));
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: { totalMarketValue: 100, topWeightPct: 20, alert: false, topPositions },
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const card = (await screen.findByText('行业数据暂不可用，当前展示个股集中度')).closest('[data-card-level]') as HTMLElement;
    expect(within(card).getByText('S7')).toBeInTheDocument();
    expect(within(card).getAllByRole('listitem')).toHaveLength(8);
  });

  it('opens the entry drawer with Taiwan example and no simplified Chinese in zh-TW', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh-TW');
    render(
      <UiLanguageProvider>
        <PortfolioPage />
      </UiLanguageProvider>,
    );
    await waitForInitialLoad();

    fireEvent.click(await screen.findByRole('button', { name: '記一筆' }));
    expect(screen.getByPlaceholderText('股票代號（例如 2330.TW）')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/[账户录仓导资币种税]/);
  });

  it('defaults a new account to Taiwan and TWD from the menu', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh-TW');
    render(
      <UiLanguageProvider>
        <PortfolioPage />
      </UiLanguageProvider>,
    );
    await waitForInitialLoad();

    fireEvent.click(await screen.findByRole('button', { name: '更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '新建帳戶' }));
    expect((screen.getByPlaceholderText('基準幣（例如 TWD/USD）') as HTMLInputElement).value).toBe('TWD');
    expect((within(screen.getByRole('dialog')).getByRole('combobox') as HTMLSelectElement).value).toBe('tw');
  });

  it('renders records as a table and keeps delete to a single account view', async () => {
    listTrades.mockResolvedValue({
      items: [{ id: 7, accountId: 1, symbol: '2330.TW', market: 'tw', currency: 'TWD', tradeDate: '2026-10-01', side: 'buy', quantity: 10, price: 1000, fee: 1, tax: 2 }],
      total: 1, page: 1, pageSize: 20,
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const records = within(await screen.findByTestId('portfolio-records'));
    const desktop = within(await records.findByTestId('data-table-desktop'));
    expect(await desktop.findByText('2330.TW')).toBeInTheDocument();
    expect(desktop.getByText('TWD 1,000.00')).toBeInTheDocument();
    expect(desktop.queryByRole('button', { name: '删除这笔' })).not.toBeInTheDocument();

    selectAccount('Main');
    fireEvent.click(await desktop.findByRole('button', { name: '删除这笔' }));
    expect(await screen.findByText('删除错误流水')).toBeInTheDocument();
  });

  it('loads signals for 22 holdings with one grouped list request and no per-stock lookups', async () => {
    const positions = Array.from({ length: 22 }, (_, index) => makePosition({
      symbol: `${2300 + index}.TW`,
      market: 'tw',
      currency: 'TWD',
      valuationCurrency: 'TWD',
      marketValueBase: 1000 + index,
    }));
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false, positions }));
    listDecisionSignals.mockResolvedValue({
      items: positions.map((position, index) => makeDecisionSignal({
        id: 500 + index,
        stockCode: String(position.symbol),
        market: 'tw',
        riskSummary: `訊號 ${index}`,
      })),
      total: 22,
      page: 1,
      pageSize: 100,
    });

    render(<PortfolioPage />);

    expect((await screen.findAllByLabelText('訊號 0')).length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText('訊號 21').length).toBeGreaterThan(0);
    expect(listDecisionSignals).toHaveBeenCalledTimes(1);
    expect(listDecisionSignals).toHaveBeenCalledWith(expect.objectContaining({
      holdingOnly: true,
      groupLatest: true,
      status: 'active',
    }));
    expect(getLatestDecisionSignals).not.toHaveBeenCalled();
  });

  it('falls back to the per-stock endpoint only for the holding the grouped list missed', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false, positions: [
      makePosition({ symbol: '2330.TW', market: 'tw', valuationCurrency: 'TWD', marketValueBase: 300 }),
      makePosition({ symbol: '2303.TW', market: 'tw', valuationCurrency: 'TWD', marketValueBase: 200 }),
      makePosition({ symbol: '2454.TW', market: 'tw', valuationCurrency: 'TWD', marketValueBase: 100 }),
    ] }));
    listDecisionSignals.mockResolvedValue({
      items: [
        makeDecisionSignal({ id: 1, stockCode: '2330.TW', market: 'tw', riskSummary: '台積電風險' }),
        makeDecisionSignal({ id: 2, stockCode: '2303.TW', market: 'tw', riskSummary: '聯電風險' }),
      ],
      total: 2,
      page: 1,
      pageSize: 100,
    });
    getLatestDecisionSignals.mockResolvedValue({
      items: [makeDecisionSignal({ id: 3, stockCode: '2454.TW', market: 'tw', riskSummary: '聯發科風險' })],
      total: 1,
      page: 1,
      pageSize: 1,
    });

    render(<PortfolioPage />);

    expect((await screen.findAllByLabelText('聯發科風險')).length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText('台積電風險').length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText('聯電風險').length).toBeGreaterThan(0);
    expect(getLatestDecisionSignals).toHaveBeenCalledTimes(1);
    expect(getLatestDecisionSignals).toHaveBeenCalledWith('2454.TW', { market: 'tw', limit: 1 });
  });

  it('scopes the grouped signal request to the selected account', async () => {
    getSnapshot.mockResolvedValue(makeSnapshot({ fxStale: false, positions: [makePosition()] }));

    render(<PortfolioPage />);
    await waitForInitialLoad();
    await waitFor(() => expect(listDecisionSignals).toHaveBeenCalled());

    selectAccount('Main');

    await waitFor(() => expect(listDecisionSignals).toHaveBeenLastCalledWith(expect.objectContaining({
      holdingOnly: true,
      groupLatest: true,
      accountId: 1,
    })));
  });

  it('keeps cross-currency weights and the Taiwan subtotal when FX is stale, flagging the weight header', async () => {
    getAccounts.mockResolvedValueOnce(makeAccounts([{ id: 1, name: 'Main' }, { id: 8, name: 'US' }]));
    const base = makeSnapshot({ fxStale: true, accountCount: 2 });
    const account = base.accounts[0];
    getSnapshot.mockResolvedValueOnce({
      ...base,
      totalMarketValue: 297_000,
      fxMissing: false,
      displayCurrency: 'TWD',
      consolidatedMarketValueBase: 1_320_000,
      consolidatedFxStale: true,
      consolidatedFxMissing: false,
      accounts: [
        {
          ...account,
          accountId: 1,
          accountName: 'Main',
          baseCurrency: 'TWD',
          totalMarketValue: 1_000_000,
          totalMarketValueAggregate: 225_000,
          positions: [
            makePosition({ symbol: '2330.TW', market: 'tw', currency: 'TWD', valuationCurrency: 'TWD', marketValueBase: 600_000, unrealizedPnlBase: 100_000 }),
            makePosition({ symbol: '2303.TW', market: 'tw', currency: 'TWD', valuationCurrency: 'TWD', marketValueBase: 400_000, unrealizedPnlBase: -50_000 }),
          ],
        },
        {
          ...account,
          accountId: 8,
          accountName: 'US',
          baseCurrency: 'USD',
          totalMarketValue: 10_000,
          totalMarketValueAggregate: 72_000,
          positions: [
            makePosition({ symbol: 'AAPL', market: 'us', currency: 'USD', valuationCurrency: 'USD', marketValueBase: 10_000, unrealizedPnlBase: 1_000 }),
          ],
        },
      ],
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const table = await desktopHoldings();
    expect(table.getByText('汇率过期')).toBeInTheDocument();
    // 600,000 / 1,320,000 (TWD-equivalent total, same source as the summary cards).
    expect(table.getByText('45.45%')).toBeInTheDocument();
    const taiwan = table.getByText('台股（2 档）').closest('tr') as HTMLElement;
    expect(within(taiwan).getByText('TWD 1,000,000.00')).toBeInTheDocument();
    expect(within(taiwan).getByText('75.76%')).toBeInTheDocument();
  });

  it('labels the day P&L with the quote date when quotes are not from today', async () => {
    const past = new Date();
    past.setDate(past.getDate() - 3);
    const pastIso = getTodayIsoFor(past);
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false, positions: [makePosition({ priceDate: pastIso })] }));

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const label = `${pastIso.slice(5, 7)}/${pastIso.slice(8, 10)} 损益`;
    expect(await screen.findByText(label)).toBeInTheDocument();
    expect(screen.getByText('台美股休市')).toBeInTheDocument();
    expect(screen.queryByText('今日')).not.toBeInTheDocument();
  });

  it('keeps the plain today label when quotes are from today', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false, positions: [makePosition({ priceDate: getTodayIsoFor(new Date()) })] }));

    render(<PortfolioPage />);
    await waitForInitialLoad();

    expect(await screen.findByText('今日')).toBeInTheDocument();
    expect(screen.queryByText('台美股休市')).not.toBeInTheDocument();
  });

  it('shows side, price and quantity on the mobile trade card', async () => {
    listTrades.mockResolvedValue({
      items: [
        { id: 7, accountId: 1, symbol: '2330.TW', market: 'tw', currency: 'TWD', tradeDate: '2026-10-01', side: 'buy', quantity: 10, price: 1000, fee: 1, tax: 2 },
        { id: 8, accountId: 1, symbol: '2303.TW', market: 'tw', currency: 'TWD', tradeDate: '2026-10-02', side: 'sell', quantity: 5, price: 50, fee: 1, tax: 2 },
      ],
      total: 2, page: 1, pageSize: 20,
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const records = within(await screen.findByTestId('portfolio-records'));
    const mobile = within(await records.findByTestId('data-table-mobile'));
    expect(await mobile.findByText('买入')).toBeInTheDocument();
    expect(mobile.getByText('卖出')).toBeInTheDocument();
    expect(mobile.getByText('TWD 1,000.00')).toBeInTheDocument();
    expect(mobile.getByText('10 股')).toBeInTheDocument();
    expect(mobile.getByText('2026-10-02')).toBeInTheDocument();
  });
});
