import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AlertsPage from '../AlertsPage';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';

const api = vi.hoisted(() => ({
  listRules: vi.fn(),
  createRule: vi.fn(),
  updateRule: vi.fn(),
  deleteRule: vi.fn(),
  enableRule: vi.fn(),
  disableRule: vi.fn(),
  testRule: vi.fn(),
  listTriggers: vi.fn(),
  listNotifications: vi.fn(),
  getMonitorStatus: vi.fn(),
  getQuotes: vi.fn(),
}));

vi.mock('../../api/alerts', () => ({ alertsApi: api }));
vi.mock('../../api/stocks', () => ({ stocksApi: { getQuotes: api.getQuotes } }));
vi.mock('../../api/portfolio', () => ({
  portfolioApi: { getAccounts: vi.fn().mockResolvedValue({ accounts: [] }) },
}));

const parsedError = {
  title: '載入失敗',
  message: '警報 API 不可用',
  rawMessage: '警報 API 不可用',
  category: 'http_error' as const,
  status: 500,
};

const rule = {
  id: 1,
  name: 'rule-one',
  targetScope: 'single_symbol' as const,
  target: '2330.TW',
  alertType: 'price_cross' as const,
  parameters: { direction: 'above' as const, price: 1100 },
  severity: 'warning' as const,
  enabled: true,
  source: 'api',
};

const runningMonitor = {
  enabled: true,
  withoutSchedule: true,
  running: true,
  mode: 'monitor_only',
  reason: null,
  intervalSeconds: 300,
  lastRunAt: new Date().toISOString(),
  channels: ['telegram'],
  enabledRules: 3,
};

function renderPage(path = '/alerts') {
  return render(
    <UiLanguageProvider>
      <MemoryRouter initialEntries={[path]}>
        <AlertsPage />
      </MemoryRouter>
    </UiLanguageProvider>,
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh-TW');
  api.getMonitorStatus.mockResolvedValue(runningMonitor);
  api.getQuotes.mockResolvedValue([{ stockCode: '2330.TW', quote: { currentPrice: 1000, stockName: '台積電' } }]);
  api.listRules.mockResolvedValue({ items: [rule], total: 1, page: 1, pageSize: 20 });
  api.listTriggers.mockResolvedValue({
    items: [{
      id: 10, ruleId: 1, target: '2330.TW', observedValue: 1101, threshold: 1100, status: 'triggered',
      triggeredAt: new Date().toISOString(), ruleName: 'rule-one', stockName: '台積電', severity: 'critical', quoteSource: 'yfinance',
    }],
    total: 1, page: 1, pageSize: 20,
    summary: { triggered: 1, skipped: 2, degraded: 3, failed: 4 },
  });
  api.listNotifications.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 });
  api.testRule.mockResolvedValue({ ruleId: 1, status: 'not_triggered', triggered: false, observedValue: 1000, message: 'raw' });
  api.createRule.mockResolvedValue(rule);
  api.updateRule.mockResolvedValue(rule);
  api.disableRule.mockResolvedValue({ ...rule, enabled: false });
  api.deleteRule.mockResolvedValue({ deleted: 1 });
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe('AlertsPage', () => {
  it('shows a red banner when the monitor is not running', async () => {
    api.getMonitorStatus.mockResolvedValue({ ...runningMonitor, running: false, mode: 'off', reason: 'schedule_not_running' });
    renderPage();
    expect(await screen.findByText('監控未啟動，規則不會被檢查')).toBeInTheDocument();
    expect(screen.queryByTestId('alert-monitor-bar')).not.toBeInTheDocument();
  });

  it('shows last run and channels while running, and warns about missing channels', async () => {
    renderPage();
    expect(await screen.findByTestId('alert-monitor-bar')).toHaveTextContent('每 5 分鐘檢查');
    expect(screen.getByTestId('alert-monitor-bar')).toHaveTextContent('上次執行');
    expect(screen.getByTestId('alert-monitor-bar')).toHaveTextContent('通知：telegram');
    expect(screen.queryByText('監控未啟動，規則不會被檢查')).not.toBeInTheDocument();
    cleanup();
    api.getMonitorStatus.mockResolvedValue({ ...runningMonitor, channels: [] });
    renderPage();
    expect(await screen.findByText(/尚未設定通知管道/)).toBeInTheDocument();
  });

  it('does not claim the monitor is down when the status request fails', async () => {
    api.getMonitorStatus.mockRejectedValue(new Error('offline'));
    renderPage();
    expect(await screen.findByText('無法取得監控狀態')).toBeInTheDocument();
    expect(screen.queryByText('監控未啟動，規則不會被檢查')).not.toBeInTheDocument();
  });

  it('renders counts, sentence cards and the activity stream', async () => {
    renderPage();
    expect(await screen.findByText('當 台積電 2330.TW 站上 1,100 時提醒')).toBeInTheDocument();
    expect(await screen.findByTestId('alert-trigger-10')).toHaveTextContent('台積電');
    expect(screen.getByTestId('alert-trigger-10')).toHaveTextContent('來源 yfinance（可能延遲）');
    expect(screen.getByTestId('alert-trigger-10').querySelector('.bg-danger')).not.toBeNull();
    expect(screen.getByText('啟用規則').previousSibling).toHaveTextContent('3');
    expect(screen.getByText('異常').previousSibling).toHaveTextContent('7');
    expect(api.listTriggers).toHaveBeenCalledWith({ status: 'triggered', page: 1, pageSize: 20 });
  });

  it('switches activity to issues using the combined status filter', async () => {
    renderPage();
    await screen.findByTestId('alert-trigger-10');
    fireEvent.click(screen.getByRole('tab', { name: /^異常/ }));
    await waitFor(() => expect(api.listTriggers).toHaveBeenLastCalledWith({
      status: 'degraded,failed,skipped', page: 1, pageSize: 20,
    }));
  });

  it('guides an empty account through templates into the shared drawer', async () => {
    api.listRules.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '台股大盤轉紅燈' }));
    expect(await screen.findByLabelText('市場區域')).toHaveValue('tw');
    expect(screen.getByText('1. 監控誰')).toBeInTheDocument();
    expect(screen.getByText('2. 何時提醒')).toBeInTheDocument();
    expect(screen.getByText('3. 怎麼提醒')).toBeInTheDocument();
  });

  it('opens the create drawer from ?new=1&target= and creates the rule', async () => {
    renderPage('/alerts?new=1&target=2330.TW');
    expect(await screen.findByLabelText('標的代號')).toHaveValue('2330.TW');
    fireEvent.change(screen.getByLabelText('價格閾值'), { target: { value: '1100' } });
    fireEvent.click(screen.getByRole('button', { name: '建立規則' }));
    await waitFor(() => expect(api.createRule).toHaveBeenCalledWith(expect.objectContaining({
      target: '2330.TW',
      alertType: 'price_cross',
      parameters: { direction: 'above', price: 1100 },
      name: '2330.TW 站上 1,100',
    })));
    expect(await screen.findByText(/已建立規則/)).toBeInTheDocument();
    expect(screen.queryByLabelText('標的代號')).not.toBeInTheDocument();
  });

  it('applies ?target= as a filter when not creating', async () => {
    renderPage('/alerts?target=2330.TW');
    await waitFor(() => expect(api.listRules).toHaveBeenCalledWith(expect.objectContaining({ target: '2330.TW' })));
    expect(screen.queryByText('1. 監控誰')).not.toBeInTheDocument();
  });

  it('edits through the same drawer with PATCH', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'rule-one 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '編輯' }));
    expect(await screen.findByLabelText('價格閾值')).toHaveValue(1100);
    fireEvent.change(screen.getByLabelText('價格閾值'), { target: { value: '1200' } });
    fireEvent.click(screen.getByRole('button', { name: '儲存' }));
    await waitFor(() => expect(api.updateRule).toHaveBeenCalledWith(1, expect.objectContaining({
      parameters: { direction: 'above', price: 1200 },
      cooldownSeconds: 86400,
    })));
    expect(api.createRule).not.toHaveBeenCalled();
  });

  it('never sends target or price when editing a board level rule', async () => {
    api.listRules.mockResolvedValue({ items: [{ ...rule, source: 'tw_levels' }], total: 1, page: 1, pageSize: 20 });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'rule-one 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '編輯' }));
    expect(await screen.findByLabelText('價格閾值')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '儲存' }));
    await waitFor(() => expect(api.updateRule).toHaveBeenCalled());
    const payload = api.updateRule.mock.calls[0][1];
    expect(payload).not.toHaveProperty('parameters');
    expect(payload).not.toHaveProperty('target');
    expect(payload.cooldownSeconds).toBe(86400);
  });

  it('keeps form values and shows the error when saving fails', async () => {
    api.createRule.mockRejectedValueOnce({ parsedError });
    renderPage('/alerts?new=1&target=2330.TW');
    fireEvent.change(await screen.findByLabelText('價格閾值'), { target: { value: '1100' } });
    fireEvent.click(screen.getByRole('button', { name: '建立規則' }));
    expect(await screen.findByText('載入失敗')).toBeInTheDocument();
    expect(screen.getByLabelText('價格閾值')).toHaveValue(1100);
  });

  it('runs a dry run in place', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'rule-one 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '試算目前條件' }));
    await waitFor(() => expect(api.testRule).toHaveBeenCalledWith(1));
    expect(await screen.findByText('目前條件未達成')).toBeInTheDocument();
    expect(screen.getByText(/只試算，不會送出通知/)).toBeInTheDocument();
  });

  async function dryRun() {
    fireEvent.click(await screen.findByRole('button', { name: 'rule-one 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '試算目前條件' }));
  }

  async function saveEdit() {
    fireEvent.click(screen.getByRole('button', { name: 'rule-one 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '編輯' }));
    fireEvent.change(await screen.findByLabelText('價格閾值'), { target: { value: '2000' } });
    fireEvent.click(screen.getByRole('button', { name: '儲存' }));
  }

  it('clears the dry run of an edited rule after saving', async () => {
    api.testRule.mockResolvedValue({ ruleId: 1, status: 'triggered', triggered: true, observedValue: 1200, message: 'm' });
    renderPage();
    await dryRun();
    expect(await screen.findByText('目前條件已達成')).toBeInTheDocument();
    await saveEdit();
    await waitFor(() => expect(api.updateRule).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText('目前條件已達成')).not.toBeInTheDocument());
  });

  it('keeps the dry run when saving fails, and of other rules when saving succeeds', async () => {
    const other = { ...rule, id: 2, name: 'rule-two', target: 'AAPL' };
    api.listRules.mockResolvedValue({ items: [rule, other], total: 2, page: 1, pageSize: 20 });
    api.testRule.mockResolvedValue({ ruleId: 2, status: 'triggered', triggered: true, observedValue: 1200, message: 'm' });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'rule-two 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '試算目前條件' }));
    expect(await screen.findByText('目前條件已達成')).toBeInTheDocument();
    await saveEdit();
    await waitFor(() => expect(api.updateRule).toHaveBeenCalledWith(1, expect.anything()));
    await waitFor(() => expect(screen.queryByLabelText('價格閾值')).not.toBeInTheDocument());
    expect(screen.getByText('目前條件已達成')).toBeInTheDocument();

    api.updateRule.mockRejectedValueOnce({ parsedError });
    fireEvent.click(screen.getByRole('button', { name: 'rule-two 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '編輯' }));
    fireEvent.click(await screen.findByRole('button', { name: '儲存' }));
    expect(await screen.findByText('載入失敗')).toBeInTheDocument();
    expect(screen.getByText('目前條件已達成')).toBeInTheDocument();
  });

  it('rejects a dry run sent before an edit that returns after it', async () => {
    const pending = deferred<unknown>();
    api.testRule.mockReturnValueOnce(pending.promise);
    renderPage();
    // 卡片的選單在試算進行中會停用，所以先開抽屜，再讓試算在儲存前發出
    fireEvent.click(await screen.findByRole('button', { name: 'rule-one 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '編輯' }));
    fireEvent.change(await screen.findByLabelText('價格閾值'), { target: { value: '2000' } });
    await dryRun();
    fireEvent.click(screen.getByRole('button', { name: '儲存' }));
    await waitFor(() => expect(api.updateRule).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByLabelText('價格閾值')).not.toBeInTheDocument());
    await act(async () => {
      pending.resolve({ ruleId: 1, status: 'triggered', triggered: true, observedValue: 1200, message: 'm' });
    });
    expect(screen.queryByText('目前條件已達成')).not.toBeInTheDocument();

    api.testRule.mockResolvedValueOnce({ ruleId: 1, status: 'triggered', triggered: true, observedValue: 1200, message: 'm' });
    await dryRun();
    expect(await screen.findByText('目前條件已達成')).toBeInTheDocument();
  });

  it('appends on load more and resets to page one after a mutation', async () => {
    const second = { ...rule, id: 2, name: 'rule-two', target: 'AAPL' };
    api.listRules.mockImplementation(async (query: { page: number }) => (
      query.page === 2
        ? { items: [second], total: 2, page: 2, pageSize: 20 }
        : { items: [rule], total: 2, page: 1, pageSize: 20 }
    ));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '載入更多' }));
    expect(await screen.findByTestId('alert-rule-2')).toBeInTheDocument();
    expect(screen.getByTestId('alert-rule-1')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'rule-two 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '刪除' }));
    fireEvent.click(await screen.findByRole('button', { name: '刪除' }));
    await waitFor(() => expect(api.deleteRule).toHaveBeenCalledWith(2));
    await waitFor(() => expect(screen.queryByTestId('alert-rule-2')).not.toBeInTheDocument());
    expect(api.listRules).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1 }));
  });

  it('retries the same rules page after load more fails and never skips it', async () => {
    const row = (id: number) => ({ ...rule, id, name: `rule-${id}`, target: `T${id}` });
    let failSecond = true;
    api.listRules.mockImplementation(async (query: { page: number }) => {
      if (query.page === 2 && failSecond) {
        failSecond = false;
        throw { parsedError };
      }
      return { items: [row(query.page)], total: 3, page: query.page, pageSize: 20 };
    });
    renderPage();
    await screen.findByTestId('alert-rule-1');
    fireEvent.click(screen.getByRole('button', { name: '載入更多' }));
    expect(await screen.findByText('警報 API 不可用')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '載入更多' }));
    expect(await screen.findByTestId('alert-rule-2')).toBeInTheDocument();
    expect(api.listRules.mock.calls.map(([query]) => query.page)).toEqual([1, 2, 2]);

    fireEvent.click(screen.getByRole('button', { name: '載入更多' }));
    expect(await screen.findByTestId('alert-rule-3')).toBeInTheDocument();
    expect(screen.getByTestId('alert-rule-1')).toBeInTheDocument();
    expect(screen.queryByText('警報 API 不可用')).not.toBeInTheDocument();
    expect(api.listRules.mock.calls.map(([query]) => query.page)).toEqual([1, 2, 2, 3]);
  });

  it('retries the same activity page after load more fails and never skips it', async () => {
    const row = (id: number) => ({ id, target: `T${id}`, status: 'triggered', triggeredAt: new Date().toISOString() });
    let failSecond = true;
    api.listTriggers.mockImplementation(async (query: { page: number }) => {
      if (query.page === 2 && failSecond) {
        failSecond = false;
        throw { parsedError };
      }
      return { items: [row(query.page)], total: 3, page: query.page, pageSize: 20 };
    });
    renderPage();
    await screen.findByTestId('alert-trigger-1');
    fireEvent.click(screen.getByRole('button', { name: '載入更多' }));
    expect(await screen.findByText('警報 API 不可用')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '載入更多' }));
    expect(await screen.findByTestId('alert-trigger-2')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '載入更多' }));
    expect(await screen.findByTestId('alert-trigger-3')).toBeInTheDocument();
    expect(api.listTriggers.mock.calls.map(([query]) => query.page)).toEqual([1, 2, 2, 3]);
  });

  it('keeps activity rows when the current tab is clicked again, and clears them only on a real switch', async () => {
    const issues = deferred<unknown>();
    renderPage();
    await screen.findByTestId('alert-trigger-10');
    const calls = api.listTriggers.mock.calls.length;
    fireEvent.click(screen.getByRole('tab', { name: /^已觸發/ }));
    expect(screen.getByTestId('alert-trigger-10')).toBeInTheDocument();
    expect(api.listTriggers).toHaveBeenCalledTimes(calls);

    api.listTriggers.mockReturnValueOnce(issues.promise);
    fireEvent.click(screen.getByRole('tab', { name: /^異常/ }));
    expect(screen.queryByTestId('alert-trigger-10')).not.toBeInTheDocument();
    await act(async () => {
      issues.resolve({ items: [], total: 0, page: 1, pageSize: 20 });
    });
  });

  it('starts from page one again after a filter change even if more pages were loaded', async () => {
    const second = { ...rule, id: 2, name: 'rule-two', target: 'AAPL' };
    api.listRules.mockImplementation(async (query: { page: number }) => (
      query.page === 2
        ? { items: [second], total: 2, page: 2, pageSize: 20 }
        : { items: [rule], total: 2, page: 1, pageSize: 20 }
    ));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '載入更多' }));
    await screen.findByTestId('alert-rule-2');
    fireEvent.change(screen.getByLabelText('狀態'), { target: { value: 'disabled' } });
    await waitFor(() => expect(api.listRules).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, enabled: false })));
    await waitFor(() => expect(screen.queryByTestId('alert-rule-2')).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '載入更多' }));
    await waitFor(() => expect(api.listRules).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, enabled: false })));
  });

  it('asks for page one again when a filter change failed after more pages were loaded', async () => {
    const second = { ...rule, id: 2, name: 'rule-two', target: 'AAPL' };
    api.listRules.mockImplementation(async (query: { page: number }) => (
      query.page === 2
        ? { items: [second], total: 3, page: 2, pageSize: 20 }
        : { items: [rule], total: 3, page: 1, pageSize: 20 }
    ));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '載入更多' }));
    await screen.findByTestId('alert-rule-2');

    api.listRules.mockRejectedValueOnce({ parsedError });
    fireEvent.change(screen.getByLabelText('狀態'), { target: { value: 'disabled' } });
    expect(await screen.findByText('警報 API 不可用')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '載入更多' }));
    await waitFor(() => expect(api.listRules).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, enabled: false })));
  });

  it('keeps the latest rules response when filter requests resolve out of order', async () => {
    const first = deferred<unknown>();
    const second = deferred<unknown>();
    api.listRules.mockReset().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    renderPage();
    fireEvent.change(screen.getByLabelText('狀態'), { target: { value: 'disabled' } });
    await waitFor(() => expect(api.listRules).toHaveBeenCalledTimes(2));
    await act(async () => {
      second.resolve({ items: [{ ...rule, id: 4, name: 'filtered' }], total: 1, page: 1, pageSize: 20 });
    });
    expect(await screen.findByTestId('alert-rule-4')).toBeInTheDocument();
    await act(async () => {
      first.resolve({ items: [{ ...rule, id: 3, name: 'stale' }], total: 1, page: 1, pageSize: 20 });
    });
    expect(screen.queryByTestId('alert-rule-3')).not.toBeInTheDocument();
    expect(screen.getByTestId('alert-rule-4')).toBeInTheDocument();
  });

  it('renders API errors and legacy rule disclosure without simplified text', async () => {
    api.listRules.mockResolvedValueOnce({
      items: [], total: 0, page: 1, pageSize: 20, ruleSources: { legacyConfigured: 2, legacyEffective: 1 },
    });
    const { container } = renderPage();
    expect(await screen.findByText('另有環境變數規則')).toBeInTheDocument();
    expect(screen.getByText(/環境變數設定了 2 條規則，其中 1 條/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/告警|规则|触发|监控|环境变量/);
    cleanup();
    api.listRules.mockRejectedValueOnce({ parsedError });
    renderPage();
    expect(await screen.findByText('警報 API 不可用')).toBeInTheDocument();
  });

  it('provides the three mobile tabs', async () => {
    renderPage();
    await screen.findByTestId('alert-rule-1');
    expect(screen.getByRole('tab', { name: '規則' })).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(screen.getByRole('tab', { name: '通知診斷' }));
    expect(screen.getByRole('tab', { name: '通知診斷' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('alert-rule-1').closest('.hidden')).not.toBeNull();
  });
});
