import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import { groupRecords, mergeModels, sharePercents } from '../../utils/usageSummary';
import TokenUsagePage from '../TokenUsagePage';

const { get } = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock('../../api/index', () => ({
  default: { get },
}));

const record = (id: number, calledAt: string, overrides: Record<string, unknown> = {}) => ({
  id,
  called_at: calledAt,
  call_type: 'analysis',
  model: 'openai/gpt-test',
  stock_code: '2330.TW',
  prompt_tokens: 40,
  completion_tokens: 200,
  total_tokens: 240,
  channel: 'litellm',
  billing: 'metered',
  cache_read_tokens: null,
  ...overrides,
});

const dashboardResponse = {
  period: 'month',
  from_date: '2099-06-01',
  to_date: '2099-06-11',
  total_calls: 3,
  total_prompt_tokens: 120,
  total_completion_tokens: 280,
  total_tokens: 400,
  by_call_type: [
    { call_type: 'analysis', calls: 2, prompt_tokens: 100, completion_tokens: 200, total_tokens: 300 },
    { call_type: 'agent', calls: 1, prompt_tokens: 20, completion_tokens: 80, total_tokens: 100 },
  ],
  by_model: [
    { model: 'openai/gpt-test', calls: 2, prompt_tokens: 100, completion_tokens: 200, total_tokens: 300, max_total_tokens: 240 },
    { model: 'gpt-test', calls: 1, prompt_tokens: 20, completion_tokens: 80, total_tokens: 100, max_total_tokens: 100 },
  ],
  by_day: [
    { date: '2099-06-10', calls: 1, prompt_tokens: 20, completion_tokens: 80, total_tokens: 100 },
    { date: '2099-06-11', calls: 2, prompt_tokens: 100, completion_tokens: 200, total_tokens: 300 },
  ],
  by_channel: [{ channel: 'litellm', billing: 'metered', calls: 3, total_tokens: 400 }],
  cache: { read_tokens: 30, known_prompt_tokens: 120, hit_ratio: 0.25 },
  cost: {
    currency: 'USD',
    estimated_total: 1.5,
    complete: true,
    unpriced_models: [],
    subscription_tokens: 0,
    by_model: [
      { model: 'openai/gpt-test', channel: 'litellm', billing: 'metered', total_tokens: 300, estimated_cost: 1 },
      { model: 'gpt-test', channel: 'litellm', billing: 'metered', total_tokens: 100, estimated_cost: 0.5 },
    ],
  },
  previous: {
    from_date: '2099-05-01', to_date: '2099-05-11', total_calls: 2, total_tokens: 320, estimated_cost: 1,
    calls_change_pct: 50, tokens_change_pct: 25, cost_change_pct: 50,
  },
  recent_calls: [record(1, '2099-06-11T09:30:00')],
  recent_total: 1,
};

function makeDashboardResponse(overrides: Record<string, unknown> = {}) {
  return { ...dashboardResponse, ...overrides };
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <UiLanguageProvider>
        <TokenUsagePage />
      </UiLanguageProvider>
    </MemoryRouter>,
  );
}

const defaultParams = { params: { period: 'month', limit: 50 } };

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh-TW');
  vi.clearAllMocks();
  get.mockResolvedValue({ data: dashboardResponse });
});

describe('TokenUsagePage', () => {
  it('shows the summary band with cost, comparison, conclusion and small metrics', async () => {
    renderPage();
    const summary = await screen.findByTestId('usage-summary');
    expect(within(summary).getByTestId('usage-total')).toHaveTextContent('400');
    expect(within(summary).getByTestId('usage-cost')).toHaveTextContent('USD 1.50');
    expect(within(summary).getByTestId('usage-change')).toHaveTextContent('較上月同期 +25.0%');
    expect(summary).toHaveTextContent('本月共 3 次呼叫，最多用在個股分析（75.0%）');
    expect(summary).toHaveTextContent('25.0%');
    expect(get).toHaveBeenCalledWith('/api/v1/usage/dashboard', defaultParams);
  });

  it('says subscription is not billed and does not show a zero cost', async () => {
    get.mockResolvedValue({
      data: makeDashboardResponse({
        cost: { currency: 'USD', estimated_total: null, complete: true, unpriced_models: [], subscription_tokens: 400, by_model: [] },
      }),
    });
    renderPage();
    expect(await screen.findByTestId('usage-cost')).toHaveTextContent('走訂閱，不計費');
  });

  it('marks a partial cost and shows no-reading for the cache when no call reported it', async () => {
    get.mockResolvedValue({
      data: makeDashboardResponse({
        cache: { read_tokens: 0, known_prompt_tokens: 0, hit_ratio: null },
        cost: { currency: 'USD', estimated_total: 0.5, complete: false, unpriced_models: ['x'], subscription_tokens: 0, by_model: [] },
      }),
    });
    renderPage();
    expect(await screen.findByTestId('usage-cost')).toHaveTextContent('部分模型未定價');
    expect(screen.getByText('快取命中').parentElement).toHaveTextContent('—');
  });

  it('renames prompt and completion and shows no English tokens labels', async () => {
    renderPage();
    await screen.findByTestId('usage-summary');
    expect(screen.queryByText('Prompt')).not.toBeInTheDocument();
    expect(screen.queryByText('Completion')).not.toBeInTheDocument();
    expect(within(screen.getByRole('table', { name: '呼叫明細' })).getByText('輸入')).toBeInTheDocument();
  });

  it('filters records by clicking a daily bar and clears on a second click, keeping period totals', async () => {
    renderPage();
    const bar = await screen.findByRole('button', { name: /^2099-06-10 合計/ });
    fireEvent.click(bar);
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/v1/usage/dashboard', {
      params: { period: 'month', limit: 50, day: '2099-06-10' },
    }));
    expect(await screen.findByText('只看 2099-06-10')).toBeInTheDocument();
    expect(screen.getByTestId('usage-total')).toHaveTextContent('400');

    fireEvent.click(screen.getByRole('button', { name: /^2099-06-10 合計/ }));
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/v1/usage/dashboard', defaultParams));
  });

  it('shows real call type shares that add up to 100', async () => {
    renderPage();
    expect(await screen.findByTestId('usage-share-analysis')).toHaveTextContent('75.0%');
    expect(screen.getByTestId('usage-share-agent')).toHaveTextContent('25.0%');
  });

  it('merges model names that differ only by a routing prefix', async () => {
    renderPage();
    const table = await screen.findByRole('table', { name: '模型' });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent('gpt-test');
    expect(rows[0]).toHaveTextContent('400');
    expect(rows[0]).toHaveTextContent('USD 1.50');
  });

  it('groups records by day, folds multi-round calls and links the stock', async () => {
    get.mockResolvedValue({
      data: makeDashboardResponse({
        recent_calls: [
          record(3, '2099-06-11T09:32:00'),
          record(2, '2099-06-11T09:30:00'),
          record(1, '2099-06-10T09:30:00', { stock_code: null, call_type: 'agent' }),
        ],
        recent_total: 3,
      }),
    });
    renderPage();
    const table = await screen.findByRole('table', { name: '呼叫明細' });
    expect(within(table).getByText('2099-06-11')).toBeInTheDocument();
    expect(within(table).getByText('2099-06-10')).toBeInTheDocument();
    expect(within(table).getByRole('link', { name: '2330.TW' })).toHaveAttribute('href', '/?stock=2330.TW');
    expect(within(table).queryByTestId('usage-record-3')).not.toBeInTheDocument();
    expect(within(table).getByText('480')).toBeInTheDocument();

    fireEvent.click(within(table).getByRole('button', { name: '展開 2 輪' }));
    expect(within(table).getByTestId('usage-record-3')).toBeInTheDocument();
    expect(within(table).getByTestId('usage-record-2')).toBeInTheDocument();
  });

  it('always shows the total on the first mobile line', async () => {
    renderPage();
    const mobile = await screen.findByTestId('usage-records-mobile');
    expect(within(mobile).getByTestId('usage-mobile-total-1')).toHaveTextContent('240');
    expect(within(mobile).getByTestId('usage-mobile-total-1').parentElement).toHaveTextContent('2330.TW');
  });

  it('sends type and sort filters to the API and flattens the list for sort by tokens', async () => {
    renderPage();
    await screen.findByTestId('usage-summary');
    fireEvent.change(screen.getByLabelText('用途'), { target: { value: 'agent' } });
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/v1/usage/dashboard', {
      params: { period: 'month', limit: 50, call_type: 'agent' },
    }));
    fireEvent.change(screen.getByLabelText('排序'), { target: { value: 'tokens' } });
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/v1/usage/dashboard', {
      params: { period: 'month', limit: 50, call_type: 'agent', sort: 'tokens' },
    }));
  });

  it('appends on load more with the offset of the rows already shown and retries after failure', async () => {
    get.mockResolvedValueOnce({ data: makeDashboardResponse({ recent_total: 2 }) });
    renderPage();
    const more = await screen.findByRole('button', { name: '載入更多' });

    get.mockRejectedValueOnce(new Error('offline'));
    fireEvent.click(more);
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/v1/usage/dashboard', {
      params: { period: 'month', limit: 50, offset: 1 },
    }));
    // 失敗不清掉已載入的列，也不跳頁。
    expect(await screen.findByTestId('usage-record-1')).toBeInTheDocument();

    get.mockResolvedValueOnce({ data: makeDashboardResponse({ recent_calls: [record(9, '2099-06-01T09:30:00')], recent_total: 2 }) });
    fireEvent.click(screen.getByRole('button', { name: '載入更多' }));
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/v1/usage/dashboard', {
      params: { period: 'month', limit: 50, offset: 1 },
    }));
    expect(await screen.findByTestId('usage-record-9')).toBeInTheDocument();
    expect(screen.getByTestId('usage-record-1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '載入更多' })).not.toBeInTheDocument();
  });

  it('shows the empty state when the period has no calls', async () => {
    get.mockResolvedValue({ data: makeDashboardResponse({ total_calls: 0, total_tokens: 0, by_day: [], by_call_type: [], by_model: [], recent_calls: [], recent_total: 0 }) });
    renderPage();
    expect(await screen.findByText('暫無 Token 用量記錄')).toBeInTheDocument();
    expect(screen.queryByTestId('usage-summary')).not.toBeInTheDocument();
  });

  it('shows a retryable error when the first request fails', async () => {
    get.mockRejectedValueOnce(new Error('offline'));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '重試' }));
    expect(await screen.findByTestId('usage-summary')).toBeInTheDocument();
  });

  it('renders English copy when the UI language is English', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    renderPage();
    expect(await screen.findByRole('heading', { name: 'AI usage' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Today' })).toBeInTheDocument();
    expect(await screen.findByTestId('usage-summary')).toHaveTextContent('mostly Stock analysis');
  });

  it('keeps the newest period data when dashboard requests resolve out of order', async () => {
    const monthRequest = createDeferred<{ data: unknown }>();
    const todayRequest = createDeferred<{ data: unknown }>();
    const todayResponse = makeDashboardResponse({ period: 'today', total_calls: 9, total_tokens: 900 });

    get.mockImplementation((_url, config) => {
      const period = config?.params?.period;
      if (period === 'month') return monthRequest.promise;
      if (period === 'today') return todayRequest.promise;
      return Promise.resolve({ data: dashboardResponse });
    });

    renderPage();
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/v1/usage/dashboard', defaultParams));

    fireEvent.click(screen.getByRole('radio', { name: '今日' }));
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/v1/usage/dashboard', {
      params: { period: 'today', limit: 50 },
    }));

    await act(async () => {
      todayRequest.resolve({ data: todayResponse });
    });
    expect(await screen.findByTestId('usage-total')).toHaveTextContent('900');

    await act(async () => {
      monthRequest.resolve({ data: dashboardResponse });
    });
    expect(screen.getByTestId('usage-total')).toHaveTextContent('900');
  });

  it('labels financial_commentary in English and never shows the raw call type', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    get.mockResolvedValue({
      data: makeDashboardResponse({
        by_call_type: [
          { call_type: 'financial_commentary', calls: 1, prompt_tokens: 20, completion_tokens: 80, total_tokens: 100 },
        ],
        recent_calls: [record(1, '2099-06-11T09:30:00', { call_type: 'financial_commentary' })],
      }),
    });
    renderPage();
    const share = await screen.findByTestId('usage-share-financial_commentary');
    expect(within(share).getByText('Financial commentary')).toBeInTheDocument();
    expect(screen.queryByText('financial_commentary')).not.toBeInTheDocument();
  });

  it('shows an unknown call type as other with the raw type in brackets', async () => {
    get.mockResolvedValue({
      data: makeDashboardResponse({
        by_call_type: [{ call_type: 'mystery_job', calls: 1, prompt_tokens: 20, completion_tokens: 80, total_tokens: 100 }],
      }),
    });
    renderPage();
    expect(await screen.findByTestId('usage-share-mystery_job')).toHaveTextContent('其他（mystery_job）');
  });

  it('shows claude models under one readable name and keeps the raw id as the title', async () => {
    get.mockResolvedValue({
      data: makeDashboardResponse({ recent_calls: [record(1, '2099-06-11T09:30:00', { model: 'claude_code_cli' })] }),
    });
    renderPage();
    const table = await screen.findByRole('table', { name: '呼叫明細' });
    const cell = within(table).getByText('Claude Sonnet 5.5');
    expect(cell).toHaveAttribute('title', 'claude_code_cli');
    expect(within(table).queryByText('claude_code_cli')).not.toBeInTheDocument();
  });

  it('renders a one-line text summary instead of bars when there is only one day', async () => {
    get.mockResolvedValue({
      data: makeDashboardResponse({
        by_day: [{ date: '2099-11-01', calls: 3, prompt_tokens: 953_412, completion_tokens: 251_300, total_tokens: 1_204_712 }],
      }),
    });
    renderPage();
    expect(await screen.findByTestId('usage-daily-summary')).toHaveTextContent('11/01：輸入 953K／輸出 251K');
    expect(screen.queryByTestId('usage-daily-bars')).not.toBeInTheDocument();
  });

  it('fills every day of the period with bars and labels the first and last date', async () => {
    get.mockResolvedValue({
      data: makeDashboardResponse({
        by_day: [
          { date: '2099-06-02', calls: 1, prompt_tokens: 20, completion_tokens: 80, total_tokens: 100 },
          { date: '2099-06-05', calls: 1, prompt_tokens: 20, completion_tokens: 80, total_tokens: 100 },
          { date: '2099-06-11', calls: 2, prompt_tokens: 100, completion_tokens: 200, total_tokens: 300 },
        ],
      }),
    });
    renderPage();
    const bars = await screen.findByTestId('usage-daily-bars');
    // 2099-06-01..2099-06-11 is 11 calendar days; only 3 have data and are clickable.
    expect(bars.children).toHaveLength(11);
    expect(within(bars).getAllByRole('button')).toHaveLength(3);
    expect(bars.nextElementSibling).toHaveTextContent('06/01');
    expect(bars.nextElementSibling).toHaveTextContent('06/11');
    expect(screen.queryByTestId('usage-daily-summary')).not.toBeInTheDocument();
  });

  it('hides the cost without any unit price and the comparison without a previous reading', async () => {
    get.mockResolvedValue({
      data: makeDashboardResponse({
        cost: { currency: 'USD', estimated_total: null, complete: false, unpriced_models: ['gpt-test'], subscription_tokens: 0, by_model: [
          { model: 'openai/gpt-test', channel: 'litellm', billing: 'metered', total_tokens: 300, estimated_cost: null },
        ] },
        previous: { ...dashboardResponse.previous, tokens_change_pct: null },
      }),
    });
    renderPage();
    await screen.findByTestId('usage-summary');
    expect(screen.queryByTestId('usage-cost')).not.toBeInTheDocument();
    expect(screen.queryByTestId('usage-change')).not.toBeInTheDocument();
    expect(screen.queryByText('未設定單價')).not.toBeInTheDocument();
    expect(within(screen.getByRole('table', { name: '模型' })).queryByText('估算費用')).not.toBeInTheDocument();
  });

  it('shows a labelled spinner while the first request is loading', async () => {
    get.mockReturnValue(new Promise(() => undefined));
    renderPage();
    expect(await screen.findByText('載入用量中…')).toBeInTheDocument();
  });

  it('clears the day and type filters when the period changes', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /^2099-06-10 合計/ }));
    await screen.findByText('只看 2099-06-10');
    fireEvent.click(screen.getByRole('radio', { name: '今日' }));
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/v1/usage/dashboard', {
      params: { period: 'today', limit: 50 },
    }));
  });
});

describe('usageSummary', () => {
  it('sharePercents adds up to exactly 100 even with thirds', () => {
    const shares = sharePercents([1, 1, 1]);
    expect(shares.reduce((total, value) => total + value, 0)).toBeCloseTo(100, 6);
    expect(sharePercents([0, 0])).toEqual([0, 0]);
    expect(sharePercents([3, 1])).toEqual([75, 25]);
  });

  it('mergeModels separates subscription, unpriced and partial costs', () => {
    const base = { calls: 1, promptTokens: 1, completionTokens: 1, totalTokens: 2, maxTotalTokens: 2 };
    const cost = {
      currency: 'USD',
      estimatedTotal: 1,
      complete: false,
      unpricedModels: [],
      subscriptionTokens: 0,
      byModel: [
        { model: 'sub', channel: 'cli', billing: 'subscription', totalTokens: 2, estimatedCost: null },
        { model: 'none', channel: 'litellm', billing: 'metered', totalTokens: 2, estimatedCost: null },
        { model: 'a/mix', channel: 'litellm', billing: 'metered', totalTokens: 2, estimatedCost: 1 },
        { model: 'b/mix', channel: 'litellm', billing: 'metered', totalTokens: 2, estimatedCost: null },
      ],
    };
    const rows = mergeModels(
      [{ ...base, model: 'sub' }, { ...base, model: 'none' }, { ...base, model: 'a/mix' }, { ...base, model: 'b/mix' }],
      cost,
    );
    const state = (name: string) => rows.find((row) => row.name === name)?.costState;
    expect(state('sub')).toBe('subscription');
    expect(state('none')).toBe('unpriced');
    expect(state('mix')).toBe('partial');
    expect(rows.find((row) => row.name === 'mix')?.cost).toBe(1);
  });

  it('groupRecords does not fold calls that are far apart or for another stock', () => {
    const make = (id: number, calledAt: string, stockCode: string) => ({
      id, calledAt, stockCode, callType: 'agent', model: 'm', promptTokens: 1, completionTokens: 1, totalTokens: 2,
    });
    const groups = groupRecords([
      make(4, '2099-06-11T10:00:00', 'A'),
      make(3, '2099-06-11T09:00:00', 'A'),
      make(2, '2099-06-11T08:59:00', 'B'),
    ], 'newest');
    expect(groups).toHaveLength(1);
    expect(groups[0].entries.map((entry) => entry.kind)).toEqual(['single', 'single', 'single']);
    expect(groupRecords([make(1, '2099-06-11T10:00:00', 'A')], 'tokens')[0].day).toBeNull();
  });
});
