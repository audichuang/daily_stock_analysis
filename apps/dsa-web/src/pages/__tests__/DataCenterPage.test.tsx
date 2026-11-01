import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider, useUiLanguage } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import DataCenterPage from '../DataCenterPage';

const { getOverview } = vi.hoisted(() => ({ getOverview: vi.fn() }));

vi.mock('../../api/dataCapability', () => ({
  dataCapabilityApi: { getOverview: () => getOverview() },
}));

// 日期是遠離真實資料的固定值：頁面只比對 API 給的欄位，不看掛鐘。
const market = (status: string, source: string | null, fallback: string[] = []) => ({ status, source, fallback_from: fallback, warnings: [] });

const baseDataset = {
  stale: null,
  lastSuccess: null,
  lastError: null,
  fallbackFrom: [],
  coverage: null,
  warnings: [],
  source: null,
  dataDate: null,
  dataMarket: null,
  expectedDate: null,
  isCurrent: null,
  reason: null,
  fallbackActive: false,
};

const healthyKline = {
  ...baseDataset,
  dataset: 'kline.daily',
  status: 'ok',
  dataDate: '2099-03-02',
  dataMarket: 'tw',
  expectedDate: '2099-03-02',
  isCurrent: true,
  coverage: { markets: { hk: market('ok', 'yfinance'), tw: market('ok', 'marketdb'), us: market('ok', 'yfinance') } },
};

const overview = {
  asOf: '2099-03-02T09:30:00+08:00',
  providers: [
    {
      name: 'marketdb', label: 'MarketDB', enabled: true, configured: true, status: 'ok', priority: 0,
      markets: ['tw'], datasets: ['kline.daily'], datasetMarkets: { 'kline.daily': ['tw'] }, warnings: [], lastError: null, cooldown: false,
    },
    {
      name: 'tushare', label: 'Tushare', enabled: false, configured: false, status: 'unconfigured', priority: null,
      markets: ['cn'], datasets: ['kline.daily'], datasetMarkets: { 'kline.daily': ['cn'] }, warnings: [], lastError: null, cooldown: null,
    },
  ],
  datasets: [
    healthyKline,
    { ...baseDataset, dataset: 'news.events', status: 'unknown', warnings: ['runtime_probe_not_performed'] },
    { ...baseDataset, dataset: 'strategy.screening', status: 'unconfigured', warnings: ['screening_disabled'], reason: 'screening_disabled' },
    { ...baseDataset, dataset: 'portfolio.account', status: 'ok', source: 'portfolio' },
  ],
  priorities: [
    { scenario: 'tw.realtime', providers: ['shioaji', 'yfinance'], source: 'DataFetcherManager TW realtime route', warnings: [] },
    { scenario: 'daily.generic', providers: ['a'.repeat(120)], source: 'runtime', warnings: [] },
  ],
  warnings: ['cn.realtime:unknown_source:foo', 'hk.realtime:unknown_source:foo', 'mystery_code'],
};

function LanguageSwitch() {
  const { language, setLanguage } = useUiLanguage();
  return <button onClick={() => setLanguage(language === 'zh-TW' ? 'en' : 'zh-TW')}>switch language</button>;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const renderPage = () => render(<UiLanguageProvider><MemoryRouter><DataCenterPage /></MemoryRouter></UiLanguageProvider>);

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh-TW');
  getOverview.mockResolvedValue(overview);
});

describe('DataCenterPage', () => {
  it('leads with the Taiwan and US conclusion and real data date', async () => {
    renderPage();
    const banner = await screen.findByTestId('data-center-conclusion');
    expect(banner).toHaveTextContent('台股、美股資料正常');
    expect(banner).toHaveTextContent('台股 日 K 資料到 2099-03-02');
    expect(screen.getByRole('heading', { name: '資料中心' })).toBeInTheDocument();
  });

  it('turns the banner to stale when the stored date is behind even if the source is ok', async () => {
    getOverview.mockResolvedValue({
      ...overview,
      datasets: [{ ...healthyKline, dataDate: '2099-02-20', isCurrent: false }],
    });
    renderPage();
    const banner = await screen.findByTestId('data-center-conclusion');
    expect(banner).toHaveTextContent('台股或美股資料沒有更新');
    expect(banner).toHaveTextContent('台股 日 K 停在 2099-02-20，最新應為 2099-03-02');
    expect(banner).not.toHaveTextContent('資料正常');
  });

  it('does not let other markets turn the conclusion red', async () => {
    getOverview.mockResolvedValue({
      ...overview,
      datasets: [{
        ...healthyKline,
        status: 'partial',
        coverage: { markets: { hk: market('unavailable', null), tw: market('ok', 'marketdb'), us: market('ok', 'yfinance') } },
      }],
    });
    renderPage();
    expect(await screen.findByTestId('data-center-conclusion')).toHaveTextContent('台股、美股資料正常');
  });

  it('reports a Taiwan source that is down', async () => {
    getOverview.mockResolvedValue({
      ...overview,
      datasets: [{
        ...baseDataset,
        dataset: 'quote.realtime',
        status: 'partial',
        coverage: { markets: { tw: market('unavailable', null, ['shioaji', 'yfinance']), us: market('ok', 'yfinance') } },
      }],
    });
    renderPage();
    const banner = await screen.findByTestId('data-center-conclusion');
    expect(banner).toHaveTextContent('台股或美股有資料無法使用');
    expect(banner).toHaveTextContent('台股 即時報價 無法使用');
  });

  it('shows a disabled realtime dataset instead of hiding it from the conclusion', async () => {
    getOverview.mockResolvedValue({
      ...overview,
      datasets: [{ ...baseDataset, dataset: 'quote.realtime', status: 'unavailable', warnings: ['realtime_quote_disabled'], reason: 'realtime_quote_disabled' }],
    });
    renderPage();
    const banner = await screen.findByTestId('data-center-conclusion');
    expect(banner).toHaveTextContent('台股或美股需要留意');
    expect(banner).toHaveTextContent('台股 即時報價 未啟用');
  });

  it('adds a row for a dated market the source routing does not list', async () => {
    getOverview.mockResolvedValue({
      ...overview,
      datasets: [{
        ...baseDataset,
        dataset: 'index.daily',
        status: 'ok',
        dataDate: '2099-02-20',
        dataMarket: 'tw',
        expectedDate: '2099-03-02',
        isCurrent: false,
        coverage: { markets: { us: market('ok', 'yfinance') } },
      }],
    });
    renderPage();
    expect(await screen.findByTestId('data-center-conclusion')).toHaveTextContent('台股 指數日線 停在 2099-02-20');
  });

  it('counts the same rows the tables list, so the cards add up to the row count', async () => {
    renderPage();
    await screen.findByTestId('data-center-conclusion');
    const group = within(screen.getByTestId('metric-group'));
    const value = (label: string) => Number(group.getByText(label).parentElement?.querySelector('[data-metric-value]')?.textContent);
    // 台股、美股日 K 與持股帳本正常；news 未檢查；screening 未啟用（港股收在其他市場，不計）。
    expect(value('正常')).toBe(3);
    expect(value('尚未檢查')).toBe(1);
    expect(value('未設定／未開啟')).toBe(1);
    expect(value('異常')).toBe(0);
    const tableRows = within(screen.getByRole('table', { name: '市場資料狀態' })).getAllByRole('row').length - 1
      + within(screen.getByRole('table', { name: '其他資料' })).getAllByRole('row').length - 1;
    expect(value('正常') + value('尚未檢查') + value('未設定／未開啟') + value('異常')).toBe(tableRows);
    expect(group.getByText('共 5 項（台股、美股與系統）')).toBeInTheDocument();
  });

  it('shows a muted line instead of a banner when the only gap is unchecked data', async () => {
    getOverview.mockResolvedValue({
      ...overview,
      datasets: [{
        ...healthyKline,
        coverage: { markets: { tw: market('ok', 'marketdb'), us: market('unknown', null) } },
      }],
    });
    renderPage();
    const conclusion = await screen.findByTestId('data-center-conclusion');
    expect(conclusion).toHaveTextContent('1 項尚未被呼叫過，休市或首次啟動時屬正常');
    expect(within(conclusion).queryByRole('alert')).not.toBeInTheDocument();
  });

  it('puts Taiwan and US first and folds other markets away', async () => {
    renderPage();
    const table = await screen.findByRole('table', { name: '市場資料狀態' });
    const rows = within(table).getAllByRole('row').slice(1).map((row) => row.textContent);
    expect(rows[0]).toContain('台股 日 K');
    expect(rows[0]).toContain('marketdb');
    expect(rows[0]).toContain('2099-03-02');
    expect(rows[1]).toContain('美股 日 K');
    expect(within(table).queryByText('港股 日 K')).not.toBeInTheDocument();
    expect(within(screen.getByTestId('data-center-other')).getAllByText('港股 日 K').length).toBeGreaterThan(0);
  });

  it('explains which sources were skipped on a fallback row', async () => {
    getOverview.mockResolvedValue({
      ...overview,
      datasets: [{
        ...baseDataset,
        dataset: 'quote.realtime',
        status: 'degraded',
        coverage: { markets: { tw: market('degraded', 'yfinance', ['shioaji']), us: market('ok', 'yfinance') } },
      }],
    });
    renderPage();
    expect((await screen.findAllByText('已跳過 shioaji，目前走 yfinance')).length).toBeGreaterThan(0);
  });

  it('renders a mobile card for each row so phones do not need horizontal scroll', async () => {
    renderPage();
    expect(await screen.findByTestId('data-row-mobile-kline.daily:tw')).toHaveTextContent('台股 日 K');
  });

  it('translates and merges warnings, keeping raw codes only in technical details', async () => {
    renderPage();
    await screen.findByTestId('data-center-conclusion');
    const hints = screen.getByTestId('data-center-hints');
    expect(hints).toHaveTextContent('A 股即時報價、港股即時報價：順序內有不認得的來源 foo');
    expect(hints).toHaveTextContent('另有 1 則未分類提示，見技術細節');
    expect(hints).not.toHaveTextContent('mystery_code');
    const technical = screen.getByTestId('data-center-technical');
    expect(technical).not.toHaveAttribute('open');
    expect(technical).toHaveTextContent('mystery_code');
  });

  it('never shows raw status or dataset codes as labels', async () => {
    renderPage();
    await screen.findByTestId('data-center-conclusion');
    expect(screen.queryByText('unconfigured')).not.toBeInTheDocument();
    expect(screen.queryByText('unknown')).not.toBeInTheDocument();
    expect(screen.queryByText('kline.daily')).not.toBeInTheDocument();
    expect(screen.queryByText(/API[_ ]?KEY/i)).not.toBeInTheDocument();
  });

  it('keeps sources and fallback order folded and grouped', async () => {
    renderPage();
    await screen.findByTestId('data-center-conclusion');
    const providers = screen.getByTestId('data-center-providers');
    expect(providers).not.toHaveAttribute('open');
    expect(within(providers).getByText('可用（1）')).toBeInTheDocument();
    expect(within(providers).getByText('未設定（1）')).toBeInTheDocument();
    const priorities = screen.getByTestId('data-center-priorities');
    expect(priorities).not.toHaveAttribute('open');
    expect(within(priorities).getByText('台股即時報價')).toBeInTheDocument();
    // 長來源名稱要能斷行，路由卡才不會破版。
    expect(within(priorities).getByText('a'.repeat(120))).toHaveClass('break-all');
  });

  it('shows empty and error states and can retry the endpoint', async () => {
    getOverview.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({
      asOf: '2099-03-02T09:30:00+08:00', providers: [], datasets: [], priorities: [], warnings: [],
    });
    renderPage();
    expect(await screen.findByText('資料概覽載入失敗')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重試' }));
    await waitFor(() => expect(getOverview).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText('資料概覽載入失敗')).not.toBeInTheDocument());
    expect(screen.queryByTestId('data-center-conclusion')).not.toBeInTheDocument();
  });

  it('ignores an older request that finishes after a language-triggered reload', async () => {
    const first = deferred<typeof overview>();
    const second = deferred<typeof overview>();
    getOverview.mockReset().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    render(
      <UiLanguageProvider>
        <LanguageSwitch />
        <MemoryRouter><DataCenterPage /></MemoryRouter>
      </UiLanguageProvider>,
    );

    await waitFor(() => expect(getOverview).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'switch language' }));
    await waitFor(() => expect(getOverview).toHaveBeenCalledTimes(2));

    second.resolve(overview);
    expect(await screen.findByTestId('data-center-conclusion')).toBeInTheDocument();
    first.reject(new Error('stale failure'));

    await waitFor(() => expect(screen.queryByText('Failed to load data overview')).not.toBeInTheDocument());
    expect(screen.getByTestId('data-center-conclusion')).toBeInTheDocument();
  });
});
