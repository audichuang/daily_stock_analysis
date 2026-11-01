import type React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import BacktestPage from '../BacktestPage';

const {
  mockGetResults,
  mockGetOverallPerformance,
  mockGetStockPerformance,
  mockGetSeries,
  mockRun,
} = vi.hoisted(() => ({
  mockGetResults: vi.fn(),
  mockGetOverallPerformance: vi.fn(),
  mockGetStockPerformance: vi.fn(),
  mockGetSeries: vi.fn(),
  mockRun: vi.fn(),
}));

vi.mock('../../api/backtest', () => ({
  backtestApi: {
    getResults: mockGetResults,
    getOverallPerformance: mockGetOverallPerformance,
    getStockPerformance: mockGetStockPerformance,
    getSeries: mockGetSeries,
    run: mockRun,
  },
}));

vi.mock('recharts', () => {
  const passthrough = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    ResponsiveContainer: passthrough,
    LineChart: passthrough,
    BarChart: passthrough,
    CartesianGrid: () => null,
    XAxis: () => null,
    YAxis: () => null,
    ReferenceLine: () => null,
    Tooltip: () => null,
    Line: ({ dataKey }: { dataKey: string }) => <span data-testid={`line-${dataKey}`} />,
    Bar: ({ dataKey }: { dataKey: string }) => <span data-testid={`bar-${dataKey}`} />,
  };
});

// 桌機與手機兩種版面都在 DOM；這裡只留桌機，手機列在專門的測試用 realMobile 驗。
const dataTableMode = vi.hoisted(() => ({ keepMobile: false }));
vi.mock('../../components/common/DataTable', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../components/common/DataTable')>();
  return {
    ...actual,
    DataTable: (props: Parameters<typeof actual.DataTable>[0]) => (
      dataTableMode.keepMobile
        ? <actual.DataTable {...props} />
        : <actual.DataTable {...props} renderMobileCard={() => null} />
    ),
  };
});

const basePerformance = {
  scope: 'overall',
  evalWindowDays: 10,
  engineVersion: 'test-engine',
  totalEvaluations: 60,
  completedCount: 50,
  insufficientCount: 10,
  longCount: 40,
  cashCount: 10,
  winCount: 30,
  lossCount: 15,
  neutralCount: 5,
  directionAccuracyPct: 66.7,
  winRatePct: 66.7,
  neutralRatePct: 10,
  avgStockReturnPct: 2.4,
  avgSimulatedReturnPct: -1.2,
  stopLossTriggerRate: 10,
  takeProfitTriggerRate: 20,
  ambiguousRate: 0,
  avgDaysToFirstHit: 3.5,
  computedAt: '2026-03-30T08:00:00',
  adviceBreakdown: {
    '继续持有': { total: 3, win: 2, loss: 1, neutral: 0, win_rate_pct: 66.67 },
    '逢低买入': { total: 9, win: 6, loss: 3, neutral: 0, win_rate_pct: 66.67 },
  },
  diagnostics: {},
};

const baseResultItem = {
  analysisHistoryId: 101,
  code: '600519',
  stockName: '贵州茅台',
  analysisDate: '2026-03-20',
  evalWindowDays: 10,
  engineVersion: 'test-engine',
  evalStatus: 'completed',
  maturityStatus: 'completed',
  operationAdvice: '继续持有',
  action: 'watch',
  actionLabel: '观望',
  trendPrediction: '震荡偏多',
  actualMovement: 'up',
  actualReturnPct: 3.8,
  directionExpected: 'long',
  directionCorrect: true,
  outcome: 'win',
  simulatedReturnPct: 3.8,
  simulatedEntryPrice: 100,
  simulatedExitPrice: 103.8,
  simulatedExitReason: 'take_profit',
  entryDate: '2026-03-21',
};

const baseSeries = {
  chartTitle: '逐筆累計（非資金曲線）',
  truncated: false,
  updatedAt: '2026-03-30T08:00:00',
  points: [
    { date: '2026-03-20', analysisHistoryId: 101, code: '600519', returnPct: 3.8, cumulativeReturnPct: 3.8, stockReturnPct: 2, cumulativeStockReturnPct: 2 },
  ],
  monthly: [{ month: '2026-03', completed: 1, win: 1, loss: 0, neutral: 0, winRatePct: 100 }],
};

const resultsResponse = (items: unknown[] = [baseResultItem], statusCounts: Record<string, number> = { completed: 1, pending: 2 }) => ({
  total: items.length,
  page: 1,
  limit: 20,
  items,
  statusCounts,
});

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  dataTableMode.keepMobile = false;
  mockGetOverallPerformance.mockResolvedValue(basePerformance);
  mockGetStockPerformance.mockResolvedValue(null);
  mockGetSeries.mockResolvedValue(baseSeries);
  mockGetResults.mockResolvedValue(resultsResponse());
  mockRun.mockResolvedValue({
    processed: 1,
    saved: 1,
    completed: 1,
    insufficient: 0,
    errors: 0,
  });
});

function renderEnglishPage() {
  window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
  render(
    <UiLanguageProvider>
      <BacktestPage />
    </UiLanguageProvider>,
  );
}

async function openRunDialog() {
  fireEvent.click(await screen.findByRole('button', { name: '重新计算' }));
  return within(await screen.findByRole('dialog'));
}

describe('BacktestPage layout', () => {
  it('shows the conclusion, four metrics and results without a side column', async () => {
    render(<BacktestPage />);

    expect(await screen.findByRole('heading', { name: '回测' })).toBeInTheDocument();
    expect(await screen.findByTestId('backtest-conclusion')).toHaveTextContent('已完成 50 笔');
    expect(screen.getByTestId('metric-group').children).toHaveLength(4);
    expect(screen.getByText('方向准确率')).toBeInTheDocument();
    expect(screen.getByText('平均模拟收益')).toBeInTheDocument();
    expect(screen.queryByText('整体表现')).not.toBeInTheDocument();

    const resultRow = (await screen.findByText('600519')).closest('tr') as HTMLElement;
    const row = within(resultRow);
    expect(row.getByText('观望')).toBeInTheDocument();
    expect(row.getByText('震荡偏多')).toBeInTheDocument();
    expect(row.getByText('继续持有')).toBeInTheDocument();
    expect(row.getByText('盈利')).toBeInTheDocument();
    expect(row.getByText('做多')).toBeInTheDocument();
  });

  it('says the sample is insufficient instead of drawing a conclusion', async () => {
    mockGetOverallPerformance.mockResolvedValue({ ...basePerformance, completedCount: 29 });

    render(<BacktestPage />);

    const conclusion = await screen.findByTestId('backtest-conclusion');
    expect(conclusion).toHaveTextContent('样本不足');
    expect(conclusion).not.toHaveTextContent('胜率');
  });

  it('draws a conclusion from the threshold sample size', async () => {
    mockGetOverallPerformance.mockResolvedValue({ ...basePerformance, completedCount: 30 });

    render(<BacktestPage />);

    const conclusion = await screen.findByTestId('backtest-conclusion');
    expect(conclusion).toHaveTextContent('胜率');
    expect(conclusion).not.toHaveTextContent('样本不足');
  });

  it('colors returns as profit or loss with a sign, and marks direction neutrally', async () => {
    render(<BacktestPage />);

    const metricValue = await screen.findByText('−1.20%');
    expect(metricValue).toHaveClass('text-market-down');
    expect(screen.getByText('+2.40%')).toHaveClass('text-market-up');

    const row = within((await screen.findByText('600519')).closest('tr') as HTMLElement);
    expect(row.getByText('+3.80%')).toHaveClass('text-market-up');
    const mark = row.getByLabelText('是');
    expect(mark).toHaveTextContent('✓');
    expect(mark).not.toHaveClass('text-success');
    expect(row.getByText('盈利')).not.toHaveClass('text-success');
  });

  it.each([
    ['up', 3.8, '上涨', 'text-market-up'],
    ['down', -3.8, '下跌', 'text-market-down'],
  ])('colors the %s movement badge the same way as its return', async (actualMovement, actualReturnPct, label, tone) => {
    mockGetResults.mockResolvedValue(resultsResponse([{ ...baseResultItem, actualMovement, actualReturnPct }]));

    render(<BacktestPage />);

    const badge = await screen.findByText(label);
    expect(badge).toHaveClass(tone);
    expect(badge).not.toHaveClass('text-success');
    expect(badge).not.toHaveClass('text-danger');
    expect(within(badge.parentElement as HTMLElement).getByText(/3\.80?%/)).toHaveClass(tone);
  });

  it('breaks results down by advice, largest group first', async () => {
    render(<BacktestPage />);

    const table = await screen.findByRole('table', { name: '依建议拆解' });
    const rows = within(table).getAllByRole('row');
    expect(rows[1]).toHaveTextContent('逢低买入');
    expect(rows[2]).toHaveTextContent('继续持有');
    expect(rows[1]).toHaveTextContent('6／3／0');
  });

  it('expands a row to show entry and exit, and collapses it again', async () => {
    render(<BacktestPage />);

    const row = (await screen.findByText('600519')).closest('tr') as HTMLElement;
    expect(screen.queryByTestId('backtest-row-detail-101')).not.toBeInTheDocument();

    fireEvent.click(row);
    const detail = await screen.findByTestId('backtest-row-detail-101');
    expect(detail).toHaveTextContent('2026-03-21');
    expect(detail).toHaveTextContent('触及停利');

    fireEvent.click(row);
    await waitFor(() => expect(screen.queryByTestId('backtest-row-detail-101')).not.toBeInTheDocument());
  });

  it('renders the phone card as two lines with the same return tone', async () => {
    dataTableMode.keepMobile = true;
    render(<BacktestPage />);

    const card = await screen.findByTestId('backtest-mobile-row-101');
    expect(within(card).getByText('+3.80%')).toHaveClass('text-market-up');
    expect(card.children).toHaveLength(2);
    fireEvent.click(card);
    expect(await screen.findAllByTestId('backtest-row-detail-101')).not.toHaveLength(0);
  });
});

describe('BacktestPage filters', () => {
  it('queries as soon as a filter changes, without a filter button', async () => {
    render(<BacktestPage />);

    const filterInput = await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）');
    expect(screen.queryByRole('button', { name: '筛选' })).not.toBeInTheDocument();

    fireEvent.change(filterInput, { target: { value: 'aapl' } });
    fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '20' } });
    fireEvent.change(screen.getByDisplayValue('全部阶段'), { target: { value: 'intraday' } });
    fireEvent.change(screen.getByLabelText('分析开始日期'), { target: { value: '2026-03-01' } });
    fireEvent.change(screen.getByLabelText('分析结束日期'), { target: { value: '2026-03-31' } });

    await waitFor(() => {
      expect(mockGetResults).toHaveBeenLastCalledWith({
        code: 'AAPL',
        evalWindowDays: 20,
        analysisDateFrom: '2026-03-01',
        analysisDateTo: '2026-03-31',
        analysisPhase: 'intraday',
        status: 'completed',
        page: 1,
        limit: 20,
      });
      expect(mockGetStockPerformance).toHaveBeenLastCalledWith('AAPL', {
        evalWindowDays: 20,
        analysisDateFrom: '2026-03-01',
        analysisDateTo: '2026-03-31',
        analysisPhase: 'intraday',
      });
      expect(mockGetSeries).toHaveBeenLastCalledWith({
        code: 'AAPL',
        evalWindowDays: 20,
        analysisDateFrom: '2026-03-01',
        analysisDateTo: '2026-03-31',
      });
    });
  });

  it('shows applied conditions separately from what is still being typed', async () => {
    render(<BacktestPage />);

    const applied = await screen.findByTestId('backtest-applied');
    expect(applied).toHaveTextContent('全部股票');

    fireEvent.change(await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）'), { target: { value: 'AAPL' } });
    // 防抖期間：輸入框已變，已套用條件還沒變
    expect(applied).toHaveTextContent('全部股票');

    await waitFor(() => expect(screen.getByTestId('backtest-applied')).toHaveTextContent('筛选 AAPL'));
  });

  it('applies immediately on Enter', async () => {
    render(<BacktestPage />);

    const filterInput = await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）');
    await waitFor(() => expect(mockGetResults).toHaveBeenCalled());
    fireEvent.change(filterInput, { target: { value: 'AAPL' } });
    fireEvent.keyDown(filterInput, { key: 'Enter' });

    await waitFor(() => expect(screen.getByTestId('backtest-applied')).toHaveTextContent('筛选 AAPL'));
  });

  it('separates completed, not matured and all results', async () => {
    mockGetResults.mockResolvedValue(resultsResponse([{
      ...baseResultItem,
      evalStatus: 'insufficient_data',
      maturityStatus: 'pending',
      maturesBy: '2026-04-10',
      outcome: null,
      actualReturnPct: null,
      actualMovement: null,
    }]));
    render(<BacktestPage />);

    const tabs = await screen.findByRole('radiogroup', { name: '状态' });
    await waitFor(() => expect(mockGetResults).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'completed' })));

    fireEvent.click(within(tabs).getByRole('radio', { name: /未到期/ }));
    await waitFor(() => expect(mockGetResults).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'pending', page: 1 })));
    expect(await screen.findByText('2026-04-10 前到期')).toBeInTheDocument();
    expect(screen.queryByText('数据不足')).not.toBeInTheDocument();

    fireEvent.click(within(tabs).getByRole('radio', { name: '全部' }));
    await waitFor(() => expect(mockGetResults).toHaveBeenLastCalledWith(expect.objectContaining({ status: undefined })));
  });

  it('switches to next-day validation with the 1D shortcut', async () => {
    render(<BacktestPage />);

    await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）');
    fireEvent.click(screen.getByRole('button', { name: '1 日验证' }));

    await waitFor(() => {
      expect(mockGetResults).toHaveBeenLastCalledWith(expect.objectContaining({ evalWindowDays: 1, page: 1 }));
      expect(mockGetOverallPerformance).toHaveBeenLastCalledWith(expect.objectContaining({ evalWindowDays: 1 }));
    });
    expect(await screen.findByText('实际表现')).toBeInTheDocument();
    expect(screen.getByText('准确性')).toBeInTheDocument();
    expect(screen.getByText('1 日验证模式会用下一个可进场交易日的开盘至收盘收益校验 AI 预测，不含隔夜跳空。')).toBeInTheDocument();
  });

  it('renders the action in English from the taxonomy before the server label', async () => {
    mockGetResults.mockResolvedValue(resultsResponse([{
      ...baseResultItem,
      operationAdvice: 'continue holding',
      trendPrediction: 'range-bound',
    }]));

    renderEnglishPage();

    const row = within((await screen.findByText('600519')).closest('tr') as HTMLElement);
    expect(row.getByText('Watch')).toBeInTheDocument();
    expect(row.getByText('continue holding')).toBeInTheDocument();
    expect(row.queryByText('观望')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Recalculate' })).toBeInTheDocument();
    expect(screen.queryByText('运行回测')).not.toBeInTheDocument();
  });

  it('keeps operation advice visible when the action fields are absent', async () => {
    mockGetResults.mockResolvedValue(resultsResponse([{
      ...baseResultItem,
      operationAdvice: 'risk alert, avoid buying',
      action: null,
      actionLabel: null,
    }]));

    render(<BacktestPage />);

    const row = within((await screen.findByText('600519')).closest('tr') as HTMLElement);
    expect(row.getByText('震荡偏多')).toBeInTheDocument();
    expect(row.getByText('risk alert, avoid buying')).toBeInTheDocument();
    expect(row.queryByText('回避')).not.toBeInTheDocument();
  });
});

describe('BacktestPage recalculate dialog', () => {
  it('keeps force rerun inside the dialog and runs with the current conditions', async () => {
    render(<BacktestPage />);

    fireEvent.change(await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）'), { target: { value: '600519.SH' } });
    fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '15' } });
    expect(screen.queryByRole('checkbox', { name: '强制重跑' })).not.toBeInTheDocument();

    const dialog = await openRunDialog();
    fireEvent.click(dialog.getByRole('checkbox', { name: '强制重跑' }));
    fireEvent.click(dialog.getByRole('button', { name: '运行回测' }));

    await waitFor(() => {
      expect(mockRun).toHaveBeenCalledWith({
        code: '600519.SH',
        force: true,
        minAgeDays: 0,
        evalWindowDays: 15,
        analysisDateFrom: undefined,
        analysisDateTo: undefined,
      });
    });
    expect(await screen.findByTestId('backtest-run-summary')).toBeInTheDocument();
  });

  it('uses the backend-applied window after a run with an empty window, and reloads the data', async () => {
    mockRun.mockResolvedValueOnce({
      processed: 0,
      saved: 0,
      completed: 0,
      insufficient: 0,
      errors: 0,
      appliedEvalWindowDays: 7,
      message: '未找到符合条件的历史分析记录',
    });
    render(<BacktestPage />);

    const windowInput = await screen.findByPlaceholderText('10');
    fireEvent.change(windowInput, { target: { value: '' } });

    const dialog = await openRunDialog();
    fireEvent.click(dialog.getByRole('button', { name: '运行回测' }));

    await waitFor(() => {
      expect(mockRun).toHaveBeenCalledWith(expect.objectContaining({ evalWindowDays: undefined, force: undefined, minAgeDays: undefined }));
    });
    await waitFor(() => {
      expect(windowInput).toHaveValue(7);
      expect(mockGetResults).toHaveBeenLastCalledWith(expect.objectContaining({ evalWindowDays: 7 }));
      expect(mockGetOverallPerformance).toHaveBeenLastCalledWith(expect.objectContaining({ evalWindowDays: 7 }));
    });
    expect(await screen.findByText('未找到符合条件的历史分析记录')).toBeInTheDocument();
  });

  it('reloads even when the run does not change any condition', async () => {
    render(<BacktestPage />);
    await screen.findByText('600519');
    await waitFor(() => expect(mockGetResults).toHaveBeenCalled());
    const before = mockGetResults.mock.calls.length;

    const dialog = await openRunDialog();
    fireEvent.click(dialog.getByRole('button', { name: '运行回测' }));

    await waitFor(() => expect(mockGetResults.mock.calls.length).toBeGreaterThan(before));
  });
});

describe('BacktestPage init and empty states', () => {
  it('shows the error and still loads results when the initial performance call fails', async () => {
    mockGetOverallPerformance.mockRejectedValue(new Error('perf down'));

    render(<BacktestPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('perf down');
    expect(await screen.findByText('600519')).toBeInTheDocument();
    expect(mockGetResults).toHaveBeenCalledWith(expect.objectContaining({ evalWindowDays: undefined }));
  });

  it('offers a recalculation when nothing has ever been run', async () => {
    mockGetOverallPerformance.mockResolvedValue(null);
    mockGetResults.mockResolvedValue(resultsResponse([], {}));

    render(<BacktestPage />);

    expect(await screen.findByText('暂无结果')).toBeInTheDocument();
    expect(screen.queryByTestId('backtest-conclusion')).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '重新计算' })).toHaveLength(2);
  });

  it('offers to clear conditions when filters match nothing', async () => {
    mockGetResults.mockResolvedValue(resultsResponse([], {}));
    render(<BacktestPage />);

    fireEvent.change(await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）'), { target: { value: 'ZZZZ' } });

    fireEvent.click(await screen.findByRole('button', { name: '清除条件' }));
    expect(await screen.findByText('暂无结果')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('按股票代码筛选（留空表示全部）')).toHaveValue('');
  });

  it('has its own empty state for the not matured tab', async () => {
    mockGetResults.mockResolvedValue(resultsResponse([], {}));
    render(<BacktestPage />);

    fireEvent.click(within(await screen.findByRole('radiogroup', { name: '状态' })).getByRole('radio', { name: /未到期/ }));

    expect(await screen.findByText('没有未到期的回测')).toBeInTheDocument();
  });
});

describe('BacktestPage trend charts', () => {
  it('names the chart as not an equity curve and shows when the data was updated', async () => {
    render(<BacktestPage />);

    expect(await screen.findByText('逐笔累计（非资金曲线）')).toBeInTheDocument();
    expect(await screen.findByTestId('backtest-trend-updated')).toHaveTextContent('资料更新');
    expect(screen.getByTestId('line-cumulativeReturnPct')).toBeInTheDocument();
    expect(screen.getByTestId('line-cumulativeStockReturnPct')).toBeInTheDocument();
    expect(screen.getByTestId('bar-winRatePct')).toBeInTheDocument();
  });

  it('hides the charts without data', async () => {
    mockGetSeries.mockResolvedValue({ ...baseSeries, points: [], monthly: [] });

    render(<BacktestPage />);

    await screen.findByText('600519');
    await waitFor(() => expect(mockGetSeries).toHaveBeenCalled());
    expect(screen.queryByTestId('backtest-trend')).not.toBeInTheDocument();
  });

  it('hides the charts when the series request fails, keeping the rest of the page', async () => {
    mockGetSeries.mockRejectedValue(new Error('series down'));

    render(<BacktestPage />);

    expect(await screen.findByText('600519')).toBeInTheDocument();
    await waitFor(() => expect(mockGetSeries).toHaveBeenCalled());
    expect(screen.queryByTestId('backtest-trend')).not.toBeInTheDocument();
    expect(screen.queryByText('series down')).not.toBeInTheDocument();
  });

  it('skips the stock line when no row has a stock return', async () => {
    mockGetSeries.mockResolvedValue({
      ...baseSeries,
      points: [{ date: '2026-03-20', analysisHistoryId: 101, code: '600519', returnPct: 3.8, cumulativeReturnPct: 3.8 }],
    });

    render(<BacktestPage />);

    expect(await screen.findByTestId('line-cumulativeReturnPct')).toBeInTheDocument();
    expect(screen.queryByTestId('line-cumulativeStockReturnPct')).not.toBeInTheDocument();
  });

  it('does not plot months without a win or loss as 0%', async () => {
    mockGetSeries.mockResolvedValue({
      ...baseSeries,
      monthly: [{ month: '2026-03', completed: 2, win: 0, loss: 0, neutral: 2, winRatePct: null }],
    });

    render(<BacktestPage />);

    expect(await screen.findByTestId('backtest-trend')).toBeInTheDocument();
    expect(screen.queryByTestId('backtest-monthly')).not.toBeInTheDocument();
  });

  it('says the charts ignore the phase condition when one is applied', async () => {
    render(<BacktestPage />);

    fireEvent.change(await screen.findByDisplayValue('全部阶段'), { target: { value: 'intraday' } });

    expect(await screen.findByText('趋势图不受阶段条件影响。')).toBeInTheDocument();
  });
});
