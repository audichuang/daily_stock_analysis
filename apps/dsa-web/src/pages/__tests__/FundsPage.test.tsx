import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
  return { LineChart: Stub, Line: Stub, ResponsiveContainer: Stub, Tooltip: Stub, XAxis: Stub, YAxis: Stub };
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

function renderPage(path = '/funds') {
  return render(
    <UiLanguageProvider>
      <MemoryRouter initialEntries={[path]}>
        <FundsPage />
      </MemoryRouter>
    </UiLanguageProvider>,
  );
}

describe('FundsPage', () => {
  beforeEach(() => {
    get.mockReset();
    get.mockImplementation(route);
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
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/v1/funds/18480065/nav', { params: { days: 366 } }));
  });

  it('searches funds by keyword', async () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText('Fund or company'), { target: { value: '奔腾' } });
    fireEvent.click(screen.getByRole('button', { name: /Search/ }));
    expect(await screen.findByText('统一奔腾基金')).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith('/api/v1/funds/search', { params: { q: '奔腾', limit: 20 } });
  });

  describe('holding form picks up the selected fund', () => {
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

    const pickSearchResult = async () => {
      fireEvent.change(screen.getByPlaceholderText('Fund or company'), { target: { value: '奔腾' } });
      fireEvent.click(screen.getByRole('button', { name: /Search/ }));
      fireEvent.click(await screen.findByRole('button', { name: /统一奔腾基金/ }));
      await screen.findByRole('heading', { name: '统一奔腾基金' });
    };

    beforeEach(() => {
      get.mockImplementation(routeWithSecondFund);
    });

    it('fills an empty add form once a fund is searched and selected', async () => {
      renderPage();
      await screen.findAllByText('安联台湾科技基金');
      fireEvent.click(screen.getByRole('button', { name: 'Add holding' }));
      expect(screen.getByText('Search and select a fund below first')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();

      await pickSearchResult();

      await waitFor(() => expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled());
      expect(screen.queryByText('Search and select a fund below first')).not.toBeInTheDocument();
      expect(screen.getByText('Add holding：统一奔腾基金')).toBeInTheDocument();
    });

    it('keeps the fund of an add form that already has one', async () => {
      renderPage('/funds?fund=18480065');
      await screen.findByText('+157.99%');
      fireEvent.click(screen.getByRole('button', { name: 'Add holding' }));
      expect(screen.getByText('Add holding：安联台湾科技基金')).toBeInTheDocument();

      await pickSearchResult();

      expect(screen.getByText('Add holding：安联台湾科技基金')).toBeInTheDocument();
      expect(screen.queryByText('Add holding：统一奔腾基金')).not.toBeInTheDocument();
    });

    it('does not retarget an edit form when another fund is selected', async () => {
      renderPage();
      await screen.findAllByText('安联台湾科技基金');
      fireEvent.click(screen.getAllByRole('button', { name: 'Edit holding' })[0]);
      expect(screen.getByText('Edit holding：安联台湾科技基金')).toBeInTheDocument();

      await pickSearchResult();

      expect(screen.getByText('Edit holding：安联台湾科技基金')).toBeInTheDocument();
      expect(screen.queryByText('Edit holding：统一奔腾基金')).not.toBeInTheDocument();
    });
  });
});
