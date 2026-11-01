import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MarketIndexRegionState } from '../../../stores/marketIndexStore';
import { TodayOverview } from '../TodayOverview';

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  getSnapshot: vi.fn(),
  getSummary: vi.fn(),
  listSignals: vi.fn(),
  getList: vi.fn(),
  getDetail: vi.fn(),
  indexState: {
    regions: {} as Partial<Record<'tw' | 'us', MarketIndexRegionState>>,
    load: vi.fn(),
  },
}));

vi.mock('react-router-dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router-dom')>()),
  useNavigate: () => mocks.navigate,
}));
vi.mock('../../../api/portfolio', () => ({ portfolioApi: { getSnapshot: mocks.getSnapshot } }));
vi.mock('../../../api/decisionSignals', () => ({
  decisionSignalsApi: { getSummary: mocks.getSummary, list: mocks.listSignals },
}));
vi.mock('../../../api/history', () => ({ historyApi: { getList: mocks.getList, getDetail: mocks.getDetail } }));
vi.mock('../../../stores/marketIndexStore', () => ({
  useMarketIndexStore: (selector: (state: typeof mocks.indexState) => unknown) => selector(mocks.indexState),
}));

const never = () => new Promise<never>(() => undefined);

const loadedUsIndices: MarketIndexRegionState = {
  items: [
    { code: 'SPX', name: 'S&P 500', current: 5800, change: 10, changePct: 0.2, source: null, asOf: null },
    { code: 'DJI', name: '道琼斯工业指数', current: 44800, change: 100, changePct: 0.5, source: null, asOf: null },
    { code: 'VIX', name: 'VIX', current: 15.2, change: -0.5, changePct: -3, source: null, asOf: null },
  ],
  marketPhase: null,
  marketOpen: null,
  fetchedAt: 1,
  isLoading: false,
  failed: false,
};

const renderOverview = () => {
  const onOpenReport = vi.fn();
  render(<TodayOverview watchlistRows={[]} quotes={new Map()} onOpenReport={onOpenReport} />);
  return { onOpenReport };
};

beforeEach(() => {
  mocks.navigate.mockReset();
  mocks.getSnapshot.mockReset().mockResolvedValue({ consolidatedDayPnlBase: 1200, consolidatedMarketValueBase: 500000 });
  mocks.getSummary.mockReset().mockResolvedValue({ actions: { reduce: 2 }, stopTriggeredCount: 1, stopPriceUnavailableCount: 0 });
  mocks.listSignals.mockReset().mockResolvedValue({ items: [], total: 2, page: 1, pageSize: 1 });
  mocks.getList.mockReset().mockResolvedValue({ total: 0, page: 1, limit: 1, items: [] });
  mocks.getDetail.mockReset();
  mocks.indexState.regions = { us: loadedUsIndices };
  mocks.indexState.load = vi.fn();
});

describe('TodayOverview', () => {
  it('opens AI signals pre-filtered to held reduce actions and triggered stops', async () => {
    renderOverview();
    await waitFor(() => expect(screen.getByTestId('overview-tile-reduce')).toHaveTextContent('2'));

    fireEvent.click(screen.getByTestId('overview-tile-reduce'));
    expect(mocks.navigate).toHaveBeenLastCalledWith(expect.stringContaining('holding=1&action=reduce'));
    expect(mocks.navigate).toHaveBeenLastCalledWith('/decision-signals?holding=1&action=reduce');

    fireEvent.click(screen.getByTestId('overview-tile-stop'));
    expect(mocks.navigate).toHaveBeenLastCalledWith('/decision-signals?holding=1&stop=triggered');
  });

  it('labels day P&L as the TW + US stock total and keeps only DJI and VIX in the index line', async () => {
    renderOverview();
    const dayPnlTile = screen.getByTestId('overview-tile-day-pnl');
    expect(dayPnlTile).toHaveTextContent('股票今日损益');
    expect(dayPnlTile).not.toHaveTextContent('股票今日损益（');
    // The "TW + US, in TWD" note lives in the hint so the label stays one short line.
    expect(dayPnlTile).toHaveTextContent('台＋美，折台币');
    expect(screen.getByTestId('overview-index-DJI')).toHaveTextContent('道琼');
    expect(screen.getByTestId('overview-index-VIX')).toBeInTheDocument();
    expect(screen.queryByTestId('overview-index-SPX')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('overview-tile-stop')).toHaveTextContent('1'));
  });

  it('shows skeletons instead of an em dash while KPIs and indices are loading', () => {
    mocks.getSnapshot.mockImplementation(never);
    mocks.getSummary.mockImplementation(never);
    mocks.listSignals.mockImplementation(never);
    mocks.getList.mockImplementation(never);
    mocks.indexState.regions = {};

    renderOverview();

    expect(screen.getAllByTestId('skeleton').length).toBeGreaterThanOrEqual(6);
    expect(screen.queryByText('—')).not.toBeInTheDocument();
  });

  it('shows an em dash only after loading settles without a value', async () => {
    mocks.getSnapshot.mockRejectedValue(new Error('down'));
    mocks.getSummary.mockRejectedValue(new Error('down'));
    mocks.listSignals.mockRejectedValue(new Error('down'));
    mocks.indexState.regions = { us: { ...loadedUsIndices, items: [] } };

    renderOverview();

    await waitFor(() => expect(screen.queryAllByTestId('skeleton')).toHaveLength(0));
    expect(screen.getByTestId('overview-tile-reduce')).toHaveTextContent('—');
    expect(screen.getByTestId('overview-indices')).toHaveTextContent('—');
  });

  it('counts pending reduce from the same list query as the AI signals page, not the summary', async () => {
    mocks.getSummary.mockResolvedValue({ actions: { reduce: 12 }, stopTriggeredCount: 1, stopPriceUnavailableCount: 0 });
    mocks.listSignals.mockResolvedValue({ items: [], total: 13, page: 1, pageSize: 1 });

    renderOverview();

    await waitFor(() => expect(screen.getByTestId('overview-tile-reduce')).toHaveTextContent('13'));
    expect(screen.getByTestId('overview-tile-reduce')).not.toHaveTextContent('12');
    expect(mocks.listSignals).toHaveBeenCalledWith(expect.objectContaining({
      holdingOnly: true,
      action: 'reduce',
      status: 'active',
      groupLatest: true,
      sort: 'priority',
    }));
    // Stop-triggered still reads the summary.
    await waitFor(() => expect(screen.getByTestId('overview-tile-stop')).toHaveTextContent('1'));
  });

  it('shows an em dash for pending reduce when the list query fails instead of falling back to the summary', async () => {
    mocks.getSummary.mockResolvedValue({ actions: { reduce: 12 }, stopTriggeredCount: 1, stopPriceUnavailableCount: 0 });
    mocks.listSignals.mockRejectedValue(new Error('down'));

    renderOverview();

    await waitFor(() => expect(screen.getByTestId('overview-tile-reduce')).toHaveTextContent('—'));
    expect(screen.getByTestId('overview-tile-reduce')).not.toHaveTextContent('12');
    await waitFor(() => expect(screen.getByTestId('overview-tile-stop')).toHaveTextContent('1'));
  });

  it('prefixes day P&L and market value with NT$ like the portfolio page', async () => {
    mocks.getSnapshot.mockResolvedValue({ consolidatedDayPnlBase: -137163, consolidatedMarketValueBase: 500000 });

    renderOverview();

    const value = await waitFor(() => {
      const node = screen.getByTestId('overview-tile-day-pnl').querySelector('.tabular-nums');
      expect(node?.textContent?.trim()).toMatch(/^NT\$ /);
      return node;
    });
    expect(value?.textContent).toContain('137,163');
    expect(screen.getByTestId('overview-tile-day-pnl')).not.toHaveTextContent('TWD');
    expect(screen.getByTestId('overview-tile-market-value')).toHaveTextContent('NT$ 500,000');
    expect(screen.getByTestId('overview-tile-market-value')).not.toHaveTextContent('TWD');
  });

  it('renders the verdict card from the latest market review payload and opens that report', async () => {
    mocks.getList.mockResolvedValue({ total: 1, page: 1, limit: 1, items: [{ id: 5, stockCode: 'MARKET', createdAt: '2026-10-30T15:00:00' }] });
    mocks.getDetail.mockResolvedValue({
      details: {
        contextSnapshot: {
          marketReviewPayload: {
            markets: {
              us: { marketLight: { status: 'red', label: '偏空' } },
              tw: {
                date: '2026-10-30',
                marketLight: { status: 'green', label: '偏多', guidance: '量價齐扬，可分批加码。' },
                nextDayPlan: {
                  stance: 'offensive',
                  summary: '明日偏多操作',
                  keyLevels: [
                    { label: '支撑', price: 44800 },
                    { label: '压力', price: 46200 },
                    { label: '远压', price: 47000 },
                  ],
                },
              },
            },
          },
        },
      },
    });

    const { onOpenReport } = renderOverview();
    const card = await screen.findByTestId('today-verdict-card');

    expect(mocks.getList).toHaveBeenCalledWith(expect.objectContaining({ reportType: 'market_review', limit: 1 }));
    expect(card).toHaveTextContent('偏多 · 进攻');
    expect(card).toHaveTextContent('台股 10/30 收盘');
    expect(card).toHaveTextContent('量價齐扬，可分批加码。');
    expect(card).toHaveTextContent('关键价 44,800 / 46,200');
    expect(card).not.toHaveTextContent('47,000');

    fireEvent.click(card);
    expect(onOpenReport).toHaveBeenCalledWith(5);
  });

  it('does not render the verdict card without a market review payload', async () => {
    mocks.getList.mockResolvedValue({ total: 1, page: 1, limit: 1, items: [{ id: 6, stockCode: 'MARKET', createdAt: '2026-10-30T15:00:00' }] });
    mocks.getDetail.mockResolvedValue({ details: { contextSnapshot: {} } });

    renderOverview();

    await waitFor(() => expect(mocks.getDetail).toHaveBeenCalledWith(6));
    await waitFor(() => expect(screen.getByTestId('overview-tile-reduce')).toHaveTextContent('2'));
    expect(screen.queryByTestId('today-verdict-card')).not.toBeInTheDocument();
  });
});
