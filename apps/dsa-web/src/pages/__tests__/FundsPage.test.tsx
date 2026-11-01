import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { createApiError, createParsedApiError } from '../../api/error';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import FundsPage from '../FundsPage';

const { get, post, put, del } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
}));

vi.mock('../../api/index', () => ({
  default: { get, post, put, delete: del },
}));

vi.mock('recharts', () => {
  const Stub = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    LineChart: Stub,
    Line: Stub,
    ResponsiveContainer: Stub,
    Tooltip: Stub,
    XAxis: Stub,
    YAxis: ({ tickFormatter }: { tickFormatter?: (value: number) => string }) => (
      <div data-testid="y-axis">{tickFormatter?.(766.5)}</div>
    ),
    ReferenceLine: ({ y }: { y: number }) => <div data-testid="cost-line">{y}</div>,
  };
});

const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * 86_400_000).toISOString().slice(0, 10);

const holdingsResponse = (marketValue: number | null) => ({
  items: [
    {
      id: 1, platform: '国泰世华', fund_id: '18480065', fund_name: '安联台湾科技基金', units: 588.2,
      cost_total: 232000, currency: 'TWD', as_of: iso(1), note: null, nav: marketValue == null ? null : 766.59,
      nav_date: marketValue == null ? null : iso(1), is_stale: marketValue == null, market_value: marketValue,
      pnl: marketValue == null ? null : marketValue - 232000, pnl_pct: marketValue == null ? null : 94.36,
    },
  ],
  totals: [{ currency: 'TWD', cost_total: 232000, market_value: marketValue, pnl: null, pnl_pct: null }],
  nav_error: null,
});

const detailResponse = {
  fund_id: '18480065', name: '安联台湾科技基金', company: '安联投信', isin: 'TW000T3604Y3', type_name: '国内投资股票型',
  currency: 'TWD', nav: 783.21, nav_date: iso(0), nav_change: 16.62, nav_change_pct: 2.17, nav_source: 'sitca',
  is_stale: false, history_start: '2011-11-01', history_points: 3663, history_error: null,
  returns: { w1: -6.46, m1: -0.42, m3: 5.82, m6: 17.38, ytd: 102.1, y1: 157.99, y3: null, y5: null },
  risk: { max_drawdown: -32.1, volatility: 43.6 },
};

function route(url: string) {
  if (url === '/api/v1/funds/holdings') return Promise.resolve({ data: holdingsResponse(450906) });
  if (url === '/api/v1/funds/search') {
    return Promise.resolve({ data: { items: [{ fund_id: '73990253', name: '统一奔腾基金', company: '统一投信', nav: 754.52, nav_date: iso(0) }] } });
  }
  if (url === '/api/v1/funds/18480065') return Promise.resolve({ data: detailResponse });
  if (url === '/api/v1/funds/18480065/nav') return Promise.resolve({ data: { fund_id: '18480065', points: [{ date: iso(1), nav: 766.59 }, { date: iso(0), nav: 783.21 }] } });
  if (url === '/api/v1/funds/18480065/holdings') {
    return Promise.resolve({ data: { fund_id: '18480065', items: [{ name: '创意', sector: '科技', weight: 7.65, country: '台湾' }], error: null } });
  }
  return Promise.reject(new Error(`unexpected ${url}`));
}

// Exposes the router's current query string so tests can assert what was (not) written to the URL.
const LocationProbe = () => <div data-testid="location-search">{useLocation().search}</div>;

function renderPage(path = '/funds') {
  return render(
    <UiLanguageProvider>
      <MemoryRouter initialEntries={[path]}>
        <FundsPage />
        <LocationProbe />
      </MemoryRouter>
    </UiLanguageProvider>,
  );
}

// Only the "below md" query is width-dependent; set viewport.narrow before render.
const viewport = { narrow: false };
const originalMatchMedia = window.matchMedia;

describe('FundsPage', () => {
  beforeAll(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: viewport.narrow && query.includes('max-width: 767'),
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  afterAll(() => {
    Object.defineProperty(window, 'matchMedia', { writable: true, value: originalMatchMedia });
  });

  beforeEach(() => {
    viewport.narrow = false;
    document.body.classList.remove('overflow-hidden');
    get.mockReset();
    get.mockImplementation(route);
  });

  it('opens the mobile detail layer for an explicit ?fund= deep link', async () => {
    viewport.narrow = true;
    renderPage('/funds?fund=18480065');
    expect((await screen.findByTestId('funds-detail')).parentElement).toBe(document.body);
  });

  it('auto-selects the first holding without writing ?fund= to the URL', async () => {
    renderPage();
    // The detail request proves the auto-selection happened before checking the URL.
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/v1/funds/18480065'));
    expect(await screen.findByRole('heading', { name: '安联台湾科技基金' })).toBeInTheDocument();
    expect(screen.getByTestId('location-search').textContent).not.toContain('fund=');
    // A deliberate pick still writes the URL.
    const desktop = within(screen.getByTestId('data-table-desktop'));
    fireEvent.click(desktop.getByRole('button', { name: '安联台湾科技基金' }));
    expect(screen.getByTestId('location-search')).toHaveTextContent('fund=18480065');
  });

  it('renders the tapped mobile detail layer into document.body and closes it on Back', async () => {
    viewport.narrow = true;
    const { container } = renderPage();
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/v1/funds/18480065'));
    // Auto-selection keeps the phone on the list.
    expect(screen.queryByTestId('funds-detail')).not.toBeInTheDocument();
    expect(screen.getByTestId('funds-mobile-row').closest('li')).not.toHaveAttribute('data-row-highlighted');

    fireEvent.click(within(screen.getByTestId('data-table-mobile')).getByText('安联台湾科技基金'));
    const detail = await screen.findByTestId('funds-detail');
    expect(detail.parentElement).toBe(document.body);
    expect(container.contains(detail)).toBe(false);
    expect(detail.className).toContain('fixed inset-0 z-[45]');
    expect(document.body).toHaveClass('overflow-hidden');
    expect(screen.getByTestId('funds-mobile-row').closest('li')).toHaveAttribute('data-row-highlighted', 'true');
    expect(screen.getByTestId('location-search')).toHaveTextContent('fund=18480065');

    const detailCalls = () => get.mock.calls.filter(([url]) => url === '/api/v1/funds/18480065').length;
    const callsBeforeBack = detailCalls();
    fireEvent.click(screen.getByRole('button', { name: 'Back to list' }));
    expect(screen.queryByTestId('funds-detail')).not.toBeInTheDocument();
    expect(document.body).not.toHaveClass('overflow-hidden');
    // Back drops ?fund= so a refresh or shared link does not reopen the layer.
    expect(screen.getByTestId('location-search').textContent).not.toContain('fund=');
    // The selection survives in state: the same fund stays selected, so its detail is not refetched.
    await waitFor(() => expect(screen.getByTestId('funds-mobile-row')).toBeInTheDocument());
    expect(detailCalls()).toBe(callsBeforeBack);
  });

  it('clears ?fund= on Back after a deep link, while the deep link itself still opens the layer', async () => {
    viewport.narrow = true;
    renderPage('/funds?fund=18480065');
    const detail = await screen.findByTestId('funds-detail');
    expect(screen.getByTestId('location-search')).toHaveTextContent('fund=18480065');
    // The sticky header carries the safe-area padding; the scroll container no longer leaves a top gap.
    expect(detail.className).toContain('pt-0');
    expect(detail.className).not.toContain('safe-area-inset-top');
    expect(screen.getByTestId('funds-detail-header').className).toContain('pt-[env(safe-area-inset-top)]');

    await screen.findByText('+157.99%');
    const detailCalls = () => get.mock.calls.filter(([url]) => url === '/api/v1/funds/18480065').length;
    const callsBeforeBack = detailCalls();
    fireEvent.click(screen.getByRole('button', { name: 'Back to list' }));
    expect(screen.queryByTestId('funds-detail')).not.toBeInTheDocument();
    expect(screen.getByTestId('location-search').textContent).not.toContain('fund=');
    // The deep-linked fund stays selected in state after ?fund= is dropped, so nothing is refetched.
    await waitFor(() => expect(screen.getByTestId('funds-mobile-row')).toBeInTheDocument());
    expect(detailCalls()).toBe(callsBeforeBack);
  });

  it('shows day P/L and total return on mobile rows and keeps edit/delete in the row menu', async () => {
    get.mockImplementation((url: string) => {
      if (url === '/api/v1/funds/holdings') {
        const data = holdingsResponse(450906);
        return Promise.resolve({ data: { ...data, items: [{ ...data.items[0], day_pnl: -18928, nav_change_pct: -4.28 }] } });
      }
      return route(url);
    });
    viewport.narrow = true;
    renderPage();
    const row = await screen.findByTestId('funds-mobile-row');
    expect(row).toHaveTextContent('Day P/L \u221218,928（\u22124.28%）');
    // Only the label may be cut off; the value and % never sit inside a truncating node.
    const dayValue = within(row).getByText('\u221218,928（\u22124.28%）');
    expect(dayValue).toHaveClass('shrink-0', 'whitespace-nowrap');
    expect(dayValue.closest('.truncate')).toBeNull();
    expect(row).toHaveTextContent('Total +94.36%');
    expect(within(row).queryByRole('button', { name: 'Edit holding' })).not.toBeInTheDocument();
    fireEvent.click(within(row).getByRole('button', { name: 'More actions' }));
    const remove = await screen.findByRole('menuitem', { name: 'Delete holding' });
    expect(remove).toHaveClass('text-danger');
    fireEvent.click(remove);
    expect(screen.getByText('Delete the holding of "安联台湾科技基金"?')).toBeInTheDocument();
    expect(screen.queryByTestId('funds-detail')).not.toBeInTheDocument();
  });

  it('shows my aggregated holding in the detail', async () => {
    renderPage('/funds?fund=18480065');
    const mine = await screen.findByTestId('funds-my-holding');
    expect(mine).toHaveTextContent('My holding：588.2 units · Cost 232,000 · P/L +218,906（+94.36%）');
  });

  it('lists fund holdings with market value from the latest NAV', async () => {
    renderPage();
    expect((await screen.findAllByText('安联台湾科技基金')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('450,906').length).toBeGreaterThan(0);
  });

  it('shows a dash instead of zero when a holding has no NAV', async () => {
    get.mockImplementation((url: string) =>
      url === '/api/v1/funds/holdings' ? Promise.resolve({ data: holdingsResponse(null) }) : route(url),
    );
    renderPage();
    await screen.findAllByText('安联台湾科技基金');
    expect(screen.queryByText('0')).not.toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('loads detail, returns and top holdings for the fund in the URL', async () => {
    renderPage('/funds?fund=18480065');
    expect(await screen.findByText('+157.99%')).toBeInTheDocument();
    expect(screen.getByText('TW000T3604Y3')).toBeInTheDocument();
    expect(await screen.findByText('创意')).toBeInTheDocument();
    // 走勢區間用與報酬卡同一個基準點（period），不再以今天回推天數
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/v1/funds/18480065/nav', { params: { period: 'y1' } }));
  });

  it('asks the chart for the same period basis as the return cards, and the full history for All', async () => {
    renderPage('/funds?fund=18480065');
    await screen.findByText('+157.99%');
    fireEvent.click(screen.getByRole('radio', { name: '5Y' }));
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/v1/funds/18480065/nav', { params: { period: 'y5' } }));
    fireEvent.click(screen.getByRole('radio', { name: 'All' }));
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/v1/funds/18480065/nav', { params: {} }));
    expect(get.mock.calls.some(([, cfg]) => cfg?.params?.days !== undefined)).toBe(false);
  });

  it('searches funds from the header dropdown and marks held funds without truncating names', async () => {
    renderPage();
    const header = within(screen.getByTestId('funds-header-search'));
    fireEvent.change(header.getByPlaceholderText('Fund or company'), { target: { value: '奔腾' } });
    fireEvent.click(header.getByRole('button', { name: /Search/ }));
    expect(await screen.findByText('统一奔腾基金')).not.toHaveClass('truncate');
    expect(get).toHaveBeenCalledWith('/api/v1/funds/search', { params: { q: '奔腾', limit: 20 } });
  });

  it('marks a search result that is already held', async () => {
    get.mockImplementation((url: string) => (
      url === '/api/v1/funds/search'
        ? Promise.resolve({ data: { items: [{ fund_id: '18480065', name: '安联台湾科技基金', nav: 783.21, nav_date: iso(0) }] } })
        : route(url)
    ));
    renderPage();
    await screen.findAllByText('安联台湾科技基金');
    const header = within(screen.getByTestId('funds-header-search'));
    fireEvent.change(header.getByPlaceholderText('Fund or company'), { target: { value: '安联' } });
    fireEvent.click(header.getByRole('button', { name: /Search/ }));
    expect(await header.findByText('Held')).toBeInTheDocument();
  });

  it('selects the first holding by default and highlights its row', async () => {
    renderPage();
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/v1/funds/18480065'));
    expect(await screen.findByRole('heading', { name: '安联台湾科技基金' })).toBeInTheDocument();
    const desktop = within(screen.getByTestId('data-table-desktop'));
    expect(desktop.getByText('安联台湾科技基金').closest('tr')).toHaveAttribute('data-row-highlighted', 'true');
  });

  it('shows the overview totals with signed P/L and an uncoloured market value', async () => {
    get.mockImplementation((url: string) => {
      if (url === '/api/v1/funds/holdings') {
        return Promise.resolve({
          data: {
            ...holdingsResponse(450906),
            totals: [{ currency: 'TWD', cost_total: 232000, market_value: 450906, pnl: 218906, pnl_pct: 94.36, day_pnl: -1200 }],
          },
        });
      }
      return route(url);
    });
    renderPage();
    const overview = (await screen.findByText('Total P/L')).closest('[data-testid="metric-group"]') as HTMLElement;
    const scope = within(overview);
    expect(scope.getByText('+218,906')).toHaveClass('text-market-up');
    expect(scope.getByText('\u22121,200')).toHaveClass('text-market-down');
    const marketValue = scope.getByText('450,906');
    expect(marketValue.className).not.toContain('text-market');
    expect(marketValue.closest('span')).toBeNull();
    expect(scope.getByText('232,000')).toBeInTheDocument();
  });

  it('draws the cost line at the unit cost and uses decimals that keep axis ticks distinct', async () => {
    renderPage('/funds?fund=18480065');
    const line = await screen.findByTestId('cost-line');
    expect(Number(line.textContent)).toBeCloseTo(232000 / 588.2, 4);
    // 走勢振幅 16.62 → 一位小數，不再全取整。
    expect(screen.getByTestId('y-axis')).toHaveTextContent('766.5');
    expect(screen.getByTestId('funds-range-row')).toHaveTextContent('+2.17%');
  });

  it('marks top holdings that overlap the ledger and shows the data month', async () => {
    get.mockImplementation((url: string) => (
      url === '/api/v1/funds/18480065/holdings'
        ? Promise.resolve({
            data: {
              fund_id: '18480065',
              items: [
                { name: '台积电', sector: '半导体', weight: 9.1, country: '台湾', ledger_symbol: '2330.TW' },
                { name: '创意', sector: '科技', weight: 7.65, country: '台湾' },
              ],
              error: null,
              as_of_month: '2026-09',
              overlap: [{ symbol: '2330.TW', name: '台积电', weight: 9.1 }],
            },
          })
        : route(url)
    ));
    renderPage('/funds?fund=18480065');
    const held = await screen.findByText('Also in ledger');
    expect(held.closest('tr')).toHaveTextContent('台积电');
    expect(screen.getAllByText('Also in ledger')).toHaveLength(1);
    expect(screen.getByText(/Holdings as of 2026-09/)).toBeInTheDocument();
  });

  it('keeps errors local: a failed chart does not hide detail or holdings', async () => {
    get.mockImplementation((url: string) => (
      url === '/api/v1/funds/18480065/nav' ? Promise.reject(new Error('nav down')) : route(url)
    ));
    renderPage('/funds?fund=18480065');
    expect(await screen.findByText('NAV chart is unavailable right now')).toBeInTheDocument();
    expect(screen.getByText('+157.99%')).toBeInTheDocument();
    expect(screen.getAllByText('安联台湾科技基金').length).toBeGreaterThan(0);
  });

  it('keeps holdings visible when the detail fails and retries only the detail', async () => {
    let fail = true;
    get.mockImplementation((url: string) => {
      if (url === '/api/v1/funds/18480065' && fail) return Promise.reject(new Error('detail down'));
      return route(url);
    });
    renderPage('/funds?fund=18480065');
    expect(await screen.findByText('detail down')).toBeInTheDocument();
    expect(screen.getAllByText('安联台湾科技基金').length).toBeGreaterThan(0);
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('+157.99%')).toBeInTheDocument();
  });

  it('shows a skeleton instead of the previous fund while switching', async () => {
    let resolveDetail: (value: unknown) => void = () => undefined;
    get.mockImplementation((url: string) => {
      if (url === '/api/v1/funds/73990253') return new Promise((resolve) => { resolveDetail = resolve; });
      if (url === '/api/v1/funds/73990253/holdings') return Promise.resolve({ data: { fund_id: '73990253', items: [], error: 'not_mapped' } });
      return route(url);
    });
    renderPage('/funds?fund=18480065');
    await screen.findByText('+157.99%');
    const header = within(screen.getByTestId('funds-header-search'));
    fireEvent.change(header.getByPlaceholderText('Fund or company'), { target: { value: '奔腾' } });
    fireEvent.click(header.getByRole('button', { name: /Search/ }));
    fireEvent.click(await screen.findByRole('button', { name: /统一奔腾基金/ }));
    expect(await screen.findByTestId('funds-detail-skeleton')).toBeInTheDocument();
    expect(screen.queryByText('+157.99%')).not.toBeInTheDocument();
    resolveDetail({ data: { ...detailResponse, fund_id: '73990253', name: '统一奔腾基金' } });
    await screen.findByRole('heading', { name: '统一奔腾基金' });
  });

  describe('holding form', () => {
    // 搜尋結果 73990253 的詳情／走勢／持股，沿用 18480065 的形狀換掉代號與名稱
    const routeWithSecondFund = (url: string) => {
      if (url === '/api/v1/funds/73990253') {
        return Promise.resolve({ data: { ...detailResponse, fund_id: '73990253', name: '统一奔腾基金' } });
      }
      if (url === '/api/v1/funds/73990253/nav') return Promise.resolve({ data: { fund_id: '73990253', points: [] } });
      if (url === '/api/v1/funds/73990253/holdings') {
        return Promise.resolve({ data: { fund_id: '73990253', items: [], error: 'not_mapped' } });
      }
      return route(url);
    };

    const pickFrom = async (scope: ReturnType<typeof within>) => {
      fireEvent.change(scope.getByPlaceholderText('Fund or company'), { target: { value: '奔腾' } });
      fireEvent.click(scope.getByRole('button', { name: /Search/ }));
      fireEvent.click(await scope.findByRole('button', { name: /统一奔腾基金/ }));
    };

    beforeEach(() => {
      get.mockImplementation(routeWithSecondFund);
      post.mockReset();
    });

    it('fills an empty add form once a fund is picked in the dialog', async () => {
      get.mockImplementation((url: string) => (
        url === '/api/v1/funds/holdings'
          ? Promise.resolve({ data: { items: [], totals: [], nav_error: null } })
          : routeWithSecondFund(url)
      ));
      renderPage();
      await screen.findByText('No fund holdings yet');
      fireEvent.click(screen.getByRole('button', { name: 'Add fund' }));
      const dialog = within(await screen.findByRole('dialog'));
      expect(dialog.getByText('Search and select a fund below first')).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled();

      await pickFrom(dialog);

      await waitFor(() => expect(dialog.getByRole('button', { name: 'Save' })).toBeEnabled());
      expect(dialog.queryByText('Search and select a fund below first')).not.toBeInTheDocument();
      expect(dialog.getByText('Add holding：统一奔腾基金')).toBeInTheDocument();
    });

    it('keeps the fund of an add form that already has one when the page selection changes', async () => {
      renderPage('/funds?fund=18480065');
      await screen.findByText('+157.99%');
      fireEvent.click(screen.getByRole('button', { name: 'Add fund' }));
      expect(screen.getByText('Add holding：安联台湾科技基金')).toBeInTheDocument();

      await pickFrom(within(screen.getByTestId('funds-header-search')));
      await screen.findByRole('heading', { name: '统一奔腾基金' });

      expect(screen.getByText('Add holding：安联台湾科技基金')).toBeInTheDocument();
      expect(screen.queryByText('Add holding：统一奔腾基金')).not.toBeInTheDocument();
    });

    it('does not retarget an edit form when another fund is selected', async () => {
      renderPage();
      await screen.findAllByText('安联台湾科技基金');
      fireEvent.click(screen.getAllByRole('button', { name: 'Edit holding' })[0]);
      expect(screen.getByText('Edit holding：安联台湾科技基金')).toBeInTheDocument();

      await pickFrom(within(screen.getByTestId('funds-header-search')));
      await screen.findByRole('heading', { name: '统一奔腾基金' });

      expect(screen.getByText('Edit holding：安联台湾科技基金')).toBeInTheDocument();
      expect(screen.queryByText('Edit holding：统一奔腾基金')).not.toBeInTheDocument();
    });

    it('shows field errors instead of silently refusing to save', async () => {
      renderPage('/funds?fund=18480065');
      await screen.findByText('+157.99%');
      fireEvent.click(screen.getByRole('button', { name: 'Add fund' }));
      const dialog = within(await screen.findByRole('dialog'));
      fireEvent.click(dialog.getByRole('button', { name: 'Save' }));
      expect(await dialog.findByText('Units must be above 0')).toBeInTheDocument();
      expect(dialog.getByText('Enter a total cost of 0 or more')).toBeInTheDocument();
      expect(post).not.toHaveBeenCalled();
    });

    it('puts a duplicate-platform conflict on the platform field and keeps the form open', async () => {
      post.mockRejectedValueOnce(createApiError(createParsedApiError({ title: 'Conflict', message: 'Platform already recorded', status: 409 })));
      renderPage('/funds?fund=18480065');
      await screen.findByText('+157.99%');
      fireEvent.click(screen.getByRole('button', { name: 'Add fund' }));
      const dialog = within(await screen.findByRole('dialog'));
      fireEvent.change(dialog.getByLabelText('Units'), { target: { value: '10' } });
      fireEvent.change(dialog.getByLabelText('Total cost'), { target: { value: '1000' } });
      fireEvent.click(dialog.getByRole('button', { name: 'Save' }));
      expect(await dialog.findByText('Platform already recorded')).toBeInTheDocument();
      expect(dialog.getByLabelText('Platform')).toHaveAttribute('aria-invalid', 'true');
    });
  });
});
