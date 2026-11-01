import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { stockQuoteKey } from '../../../hooks/useStockQuotes';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { HomeStockWorkspace } from '../HomeStockWorkspace';
import type { HomeWatchlistRow, HomeWorkspaceTab } from '../HomeStockWorkspace';

function renderWorkspace({
  watchlistRows,
  selectedRecordId,
  selectedStockCode,
  selectedAssetType,
  activeTab = 'watchlist',
  language = 'zh',
}: {
  watchlistRows: HomeWatchlistRow[];
  selectedRecordId?: number;
  selectedStockCode?: string;
  selectedAssetType?: 'stock' | 'index' | null;
  activeTab?: HomeWorkspaceTab;
  language?: 'zh' | 'en';
}) {
  const onHistoryItemClick = vi.fn();
  const onRemoveFromWatchlist = vi.fn().mockResolvedValue(undefined);
  window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, language);

  const renderView = (rows: HomeWatchlistRow[]) => (
    <UiLanguageProvider>
      <HomeStockWorkspace
        activeTab={activeTab}
        onTabChange={vi.fn()}
        watchlistRows={rows}
        watchlistLoading={false}
        watchlistActioning={false}
        watchlistMessage={null}
        onAddToWatchlist={vi.fn().mockResolvedValue(undefined)}
        onRemoveFromWatchlist={onRemoveFromWatchlist}
        onRefreshWatchlist={vi.fn().mockResolvedValue(undefined)}
        onAnalyzeWatchlist={vi.fn().mockResolvedValue(undefined)}
        isBatchAnalyzing={false}
        batchStatus={null}
        todayItems={[]}
        isLoadingTodayItems={false}
        todayLoadError={false}
        watchlistAnalyzedTodayCount={rows.filter((row) => row.analyzedToday).length}
        historyItems={[]}
        isLoadingHistory={false}
        selectedStockCode={selectedStockCode}
        selectedAssetType={selectedAssetType ?? null}
        selectedRecordId={selectedRecordId}
        onHistoryItemClick={onHistoryItemClick}
      />
    </UiLanguageProvider>
  );
  const view = render(renderView(watchlistRows));

  return {
    onHistoryItemClick,
    onRemoveFromWatchlist,
    rerenderWatchlistRows: (rows: HomeWatchlistRow[]) => view.rerender(renderView(rows)),
  };
}

describe('HomeStockWorkspace', () => {
  it('uses the mobile scroll-shell contract for watchlist and today content', () => {
    renderWorkspace({ watchlistRows: [] });

    const workspace = screen.getByTestId('home-stock-workspace');
    expect(workspace).toHaveClass('glass-card', 'home-stock-scroll-shell');
    expect(workspace).not.toHaveClass('overflow-hidden');
    expect(screen.getByTestId('home-stock-workspace-scroll')).toHaveClass('overscroll-y-contain', 'touch-pan-y');
  });

  it('keeps all three tabs in one shared glass-card shell with a frameless StockBar list', () => {
    renderWorkspace({ watchlistRows: [], activeTab: 'history' });

    const workspace = screen.getByTestId('home-stock-workspace');
    const stockBar = screen.getByTestId('home-stock-bar');
    expect(workspace).toHaveClass('glass-card', 'home-stock-scroll-shell');
    expect(workspace).not.toHaveClass('overflow-hidden');
    expect(stockBar).toHaveClass('min-h-0');
    expect(stockBar).not.toHaveClass('glass-card');
    expect(stockBar).not.toHaveClass('overflow-hidden');
    expect(screen.getByTestId('home-stock-bar-scroll')).toHaveClass('touch-pan-y');
  });

  it('opens the latest watchlist detail from a native button and keeps the row selected', () => {
    const { onHistoryItemClick } = renderWorkspace({
      watchlistRows: [{
        code: '600519',
        analyzedToday: true,
        latestItem: {
          id: 21,
          stockCode: '600519',
          stockName: '贵州茅台',
          sentimentScore: 88,
          operationAdvice: '买入',
          analysisCount: 1,
          lastAnalysisTime: '2026-03-19T09:00:00+08:00',
        },
      }],
      selectedRecordId: 21,
    });

    const row = screen.getByRole('button', { name: '打开 600519 最新分析详情' });
    fireEvent.click(row);

    expect(onHistoryItemClick).toHaveBeenCalledWith(21);
    expect(row.tagName).toBe('BUTTON');
    expect(row).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows change state and next-action signals for watchlist rows', () => {
    renderWorkspace({
      watchlistRows: [
        {
          code: '600519',
          analyzedToday: true,
          latestItem: {
            id: 21,
            stockCode: '600519',
            stockName: '贵州茅台',
            sentimentScore: 88,
            operationAdvice: '买入',
            analysisCount: 1,
            lastAnalysisTime: '2026-03-19T09:00:00+08:00',
          },
        },
        {
          code: '00700',
          analyzedToday: false,
          latestItem: {
            id: 22,
            stockCode: '00700',
            stockName: '腾讯控股',
            sentimentScore: 68,
            operationAdvice: 'neutral',
            analysisCount: 1,
            lastAnalysisTime: '2026-03-18T09:00:00+08:00',
          },
        },
        {
          code: 'AAPL',
          analyzedToday: false,
          activeTask: {
            taskId: 'task-aapl',
            stockCode: 'AAPL',
            status: 'processing',
            progress: 25,
            reportType: 'simple',
            createdAt: '2026-03-19T09:20:00+08:00',
          },
        },
      ],
    });

    const analyzedRow = within(screen.getByTestId('watchlist-row-600519'));
    const analyzedButton = analyzedRow.getByRole('button', { name: '打开 600519 最新分析详情' });
    expect(analyzedButton).toHaveAccessibleDescription('变化：今日已更新；状态：已完成；下一步：打开最新报告');

    const staleRow = within(screen.getByTestId('watchlist-row-00700'));
    expect(staleRow.getByRole('button', { name: '打开 00700 最新分析详情' })).toHaveAccessibleDescription(
      '变化：有历史报告；状态：待更新；下一步：运行今日分析',
    );

    const taskRow = within(screen.getByTestId('watchlist-row-AAPL'));
    expect(taskRow.getByRole('button', { name: '暂无 AAPL 的分析详情，可先分析' })).toHaveAccessibleDescription(
      '变化：等待首次分析；状态：任务分析中；下一步：等待任务完成',
    );
  });

  it('keeps asset-aware selection while excluding a running index from the pending count', () => {
    renderWorkspace({
      selectedStockCode: '000016',
      selectedAssetType: 'stock',
      watchlistRows: [
        { code: '000016', assetType: 'stock', analyzedToday: false },
        { code: '000016.SH', assetType: 'index', identityKey: 'sh000016', analyzedToday: false,
          activeTask: { taskId: 'index-task', stockCode: 'sh000016', status: 'processing', progress: 25,
            reportType: 'simple', createdAt: '2026-10-01T09:20:00+08:00' } },
      ],
    });
    expect(screen.getByTestId('watchlist-analyze-split')).toHaveTextContent('分析未完成 1');
    expect(screen.getByRole('button', { name: '暂无 000016 的分析详情，可先分析' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '暂无 000016.SH 的分析详情，可先分析' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: '暂无 000016.SH 的分析详情，可先分析' })).toHaveAccessibleDescription(
      '变化：等待首次分析；状态：任务分析中；下一步：等待任务完成',
    );
  });

  it('localizes watchlist signal descriptions for assistive technology', () => {
    renderWorkspace({
      language: 'en',
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
        latestItem: {
          id: 22,
          stockCode: 'AAPL',
          stockName: 'Apple',
          sentimentScore: 68,
          operationAdvice: 'neutral',
          analysisCount: 1,
          lastAnalysisTime: '2026-03-18T09:00:00+08:00',
        },
      }],
    });

    expect(screen.getByRole('button', { name: 'Open the latest analysis details for AAPL' })).toHaveAccessibleDescription(
      'Change: Has prior report; State: Pending update; Next action: Run today analysis',
    );
  });

  it('shows an explicit notice when a watchlist row has no detail yet', async () => {
    const { onHistoryItemClick } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
      }],
    });

    const row = screen.getByRole('button', { name: '暂无 AAPL 的分析详情，可先分析' });
    fireEvent.click(row);

    expect(await screen.findByRole('alert')).toHaveTextContent('暂无分析详情，可先分析。');
    expect(onHistoryItemClick).not.toHaveBeenCalled();
  });

  it('shows loading feedback instead of no-detail copy while latest detail lookup is still pending', async () => {
    const { onHistoryItemClick } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
        isTodayStatusLoading: true,
      }],
    });

    const row = screen.getByRole('button', { name: '正在查找 AAPL 的最新分析详情' });
    fireEvent.click(row);

    expect(await screen.findByRole('alert')).toHaveTextContent('正在查找最新分析详情，请稍候。');
    expect(onHistoryItemClick).not.toHaveBeenCalled();
  });

  it('shows retry feedback instead of no-detail copy when the latest detail lookup failed', async () => {
    const { onHistoryItemClick } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
        isTodayStatusUnknown: true,
      }],
    });

    const row = screen.getByRole('button', { name: 'AAPL 的最新分析详情暂时无法确认，请稍后重试' });
    fireEvent.click(row);

    expect(await screen.findByRole('alert')).toHaveTextContent('最新分析详情暂时无法确认，请稍后重试。');
    expect(screen.queryByText('暂无分析详情，可先分析。')).not.toBeInTheDocument();
    expect(onHistoryItemClick).not.toHaveBeenCalled();
  });

  it('does not expose a cached detail while the current row status is unsettled', async () => {
    const cachedItem = {
      id: 24,
      stockCode: 'AAPL',
      stockName: 'Apple',
      sentimentScore: 68,
      operationAdvice: 'neutral',
      analysisCount: 1,
      lastAnalysisTime: '2026-03-18T09:20:00+08:00',
    };
    const { onHistoryItemClick, rerenderWatchlistRows } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
        latestItem: cachedItem,
        isTodayStatusLoading: true,
      }],
    });

    fireEvent.click(screen.getByRole('button', { name: '\u6b63\u5728\u67e5\u627e AAPL \u7684\u6700\u65b0\u5206\u6790\u8be6\u60c5' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('\u6b63\u5728\u67e5\u627e\u6700\u65b0\u5206\u6790\u8be6\u60c5\uff0c\u8bf7\u7a0d\u5019\u3002');
    expect(onHistoryItemClick).not.toHaveBeenCalled();

    rerenderWatchlistRows([{
      code: 'AAPL',
      analyzedToday: false,
      latestItem: cachedItem,
      isTodayStatusUnknown: true,
    }]);
    fireEvent.click(screen.getByRole('button', { name: 'AAPL \u7684\u6700\u65b0\u5206\u6790\u8be6\u60c5\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5' }));
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('\u6700\u65b0\u5206\u6790\u8be6\u60c5\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002');
    });
    expect(onHistoryItemClick).not.toHaveBeenCalled();
  });

  it('clears a loading notice when the same row detail lookup settles', async () => {
    const { rerenderWatchlistRows } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
        isTodayStatusLoading: true,
      }],
    });

    const row = screen.getByTestId('watchlist-row-AAPL');
    fireEvent.click(row.querySelector('button[aria-pressed]') as HTMLButtonElement);
    expect(await screen.findByRole('alert')).toBeInTheDocument();

    rerenderWatchlistRows([{
      code: 'AAPL',
      analyzedToday: false,
      latestItem: {
        id: 22,
        stockCode: 'AAPL',
        stockName: 'Apple',
        sentimentScore: 72,
        operationAdvice: 'neutral',
        analysisCount: 1,
        lastAnalysisTime: '2026-03-19T09:00:00+08:00',
      },
    }]);

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(row.querySelector('button[aria-pressed]')).toBeInTheDocument();
  });

  it('clears a no-detail notice when the matching row receives a detail', async () => {
    const { rerenderWatchlistRows } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
      }],
    });

    fireEvent.click(screen.getByRole('button', { name: '暂无 AAPL 的分析详情，可先分析' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('暂无分析详情，可先分析。');

    rerenderWatchlistRows([{
      code: 'AAPL',
      analyzedToday: true,
      latestItem: {
        id: 23,
        stockCode: 'AAPL',
        stockName: 'Apple',
        sentimentScore: 80,
        operationAdvice: 'buy',
        analysisCount: 1,
        lastAnalysisTime: '2026-03-19T10:00:00+08:00',
      },
    }]);

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: '打开 AAPL 最新分析详情' })).toBeInTheDocument();
  });

  it('derives an opened notice from the latest row state instead of retaining stale copy', async () => {
    const { rerenderWatchlistRows } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
      }],
    });

    const row = screen.getByTestId('watchlist-row-AAPL');
    fireEvent.click(row.querySelector('button[aria-pressed]') as HTMLButtonElement);
    expect(await screen.findByRole('alert')).toHaveTextContent('\u6682\u65e0\u5206\u6790\u8be6\u60c5\uff0c\u53ef\u5148\u5206\u6790\u3002');

    rerenderWatchlistRows([{
      code: 'AAPL',
      analyzedToday: false,
      isTodayStatusLoading: true,
    }]);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('\u6b63\u5728\u67e5\u627e\u6700\u65b0\u5206\u6790\u8be6\u60c5\uff0c\u8bf7\u7a0d\u5019\u3002');
    });

    rerenderWatchlistRows([{
      code: 'AAPL',
      analyzedToday: false,
      isTodayStatusUnknown: true,
    }]);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('\u6700\u65b0\u5206\u6790\u8be6\u60c5\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002');
    });
  });

  it('does not bubble delete clicks into detail opening', async () => {
    const { onHistoryItemClick, onRemoveFromWatchlist } = renderWorkspace({
      watchlistRows: [{
        code: '600519',
        analyzedToday: true,
        latestItem: {
          id: 21,
          stockCode: '600519',
          stockName: '贵州茅台',
          sentimentScore: 88,
          operationAdvice: '买入',
          analysisCount: 1,
          lastAnalysisTime: '2026-03-19T09:00:00+08:00',
        },
      }],
    });

    expect(screen.queryByRole('button', { name: '从自选股移除 600519' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));
    fireEvent.click(screen.getByRole('button', { name: '从自选股移除 600519' }));
    // 確認前不能真的移除
    expect(onRemoveFromWatchlist).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '删除' }));

    expect(onRemoveFromWatchlist).toHaveBeenCalledWith('600519');
    expect(onHistoryItemClick).not.toHaveBeenCalled();
  });

  it('shows the batch quote as the current price, never the analysis price', () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    const row = {
      code: '2330.TW',
      analyzedToday: true,
      latestItem: {
        id: 1,
        stockCode: '2330.TW',
        stockName: '台積電',
        sentimentScore: 70,
        action: 'hold' as const,
        analysisCount: 1,
        analysisPrice: 900,
      },
    };
    const quotes = new Map([[stockQuoteKey('2330.TW'), { stockCode: '2330.TW', currentPrice: 1234, changePercent: 1.5 }]]);
    const baseProps = {
      activeTab: 'watchlist' as const,
      onTabChange: vi.fn(),
      watchlistRows: [row],
      watchlistLoading: false,
      watchlistActioning: false,
      watchlistMessage: null,
      onAddToWatchlist: vi.fn().mockResolvedValue(undefined),
      onRemoveFromWatchlist: vi.fn().mockResolvedValue(undefined),
      onRefreshWatchlist: vi.fn().mockResolvedValue(undefined),
      onAnalyzeWatchlist: vi.fn().mockResolvedValue(undefined),
      isBatchAnalyzing: false,
      batchStatus: null,
      todayItems: [],
      isLoadingTodayItems: false,
      todayLoadError: false,
      watchlistAnalyzedTodayCount: 1,
      historyItems: [],
      isLoadingHistory: false,
      onHistoryItemClick: vi.fn(),
    };

    const view = render(
      <UiLanguageProvider>
        <HomeStockWorkspace {...baseProps} quotes={quotes} />
      </UiLanguageProvider>,
    );
    const priced = within(screen.getByTestId('watchlist-row-2330.TW'));
    expect(priced.getByTestId('stock-row-price')).toHaveTextContent('1,234');
    expect(priced.queryByText(/分析时/)).not.toBeInTheDocument();

    // 沒有報價：現價是 —，分析時價要明確標示
    view.rerender(
      <UiLanguageProvider>
        <HomeStockWorkspace {...baseProps} quotes={new Map()} />
      </UiLanguageProvider>,
    );
    const unpriced = within(screen.getByTestId('watchlist-row-2330.TW'));
    expect(unpriced.getByTestId('stock-row-price')).toHaveTextContent(/^900.* · 分析时$/);
    expect(unpriced.getByTestId('stock-row-price')).toHaveClass('text-muted-text');
  });

  it('filters rows by market and sorts missing readings last', () => {
    const makeRow = (code: string, score?: number) => ({
      code,
      analyzedToday: false,
      latestItem: { id: code.length, stockCode: code, stockName: code, sentimentScore: score, analysisCount: 1 },
    });
    renderWorkspace({ watchlistRows: [makeRow('2330.TW', 40), makeRow('AAPL'), makeRow('NVDA', 90)] });

    fireEvent.change(screen.getByRole('combobox', { name: '排序' }), { target: { value: 'score' } });
    const order = screen.getAllByTestId(/^watchlist-row-/).map((node) => node.getAttribute('data-testid'));
    expect(order).toEqual(['watchlist-row-NVDA', 'watchlist-row-2330.TW', 'watchlist-row-AAPL']);

    fireEvent.click(screen.getByRole('button', { name: '台股' }));
    expect(screen.getAllByTestId(/^watchlist-row-/)).toHaveLength(1);
    expect(screen.getByTestId('watchlist-row-2330.TW')).toBeInTheDocument();
  });

  it('renders the market filter as small chips, not a Segmented radiogroup', () => {
    renderWorkspace({ watchlistRows: [] });

    const controls = screen.getByTestId('home-list-controls');
    expect(within(controls).queryByRole('radiogroup')).not.toBeInTheDocument();
    expect(within(controls).queryAllByRole('radio')).toHaveLength(0);
    const twChip = within(controls).getByRole('button', { name: '台股' });
    expect(twChip).toHaveClass('h-6', 'text-[11px]', 'rounded-full');
    expect(twChip).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(twChip);
    expect(twChip).toHaveAttribute('aria-pressed', 'true');
    // Sort shares the same row as the chips.
    expect(within(controls).getByRole('combobox', { name: '排序' })).toHaveClass('h-8');
  });

  it('orders the tabs watchlist, today, history', () => {
    renderWorkspace({ watchlistRows: [] });
    const labels = within(screen.getByTestId('home-stock-workspace')).getAllByRole('button')
      .map((button) => button.textContent)
      .filter((label) => ['自选', '今日', '记录'].includes(label ?? ''));
    expect(labels).toEqual(['自选', '今日', '记录']);
  });

  it('folds analyze-all and analyze-pending into one split button and keeps the add form in edit mode', () => {
    const onAnalyzeWatchlist = vi.fn().mockResolvedValue(undefined);
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    render(
      <UiLanguageProvider>
        <HomeStockWorkspace
          activeTab="watchlist"
          onTabChange={vi.fn()}
          watchlistRows={[
            { code: 'AAPL', analyzedToday: false },
            { code: 'NVDA', analyzedToday: true },
          ]}
          watchlistLoading={false}
          watchlistActioning={false}
          watchlistMessage={null}
          onAddToWatchlist={vi.fn().mockResolvedValue(undefined)}
          onRemoveFromWatchlist={vi.fn().mockResolvedValue(undefined)}
          onRefreshWatchlist={vi.fn().mockResolvedValue(undefined)}
          onAnalyzeWatchlist={onAnalyzeWatchlist}
          isBatchAnalyzing={false}
          batchStatus={null}
          todayItems={[]}
          isLoadingTodayItems={false}
          todayLoadError={false}
          watchlistAnalyzedTodayCount={1}
          historyItems={[]}
          isLoadingHistory={false}
          onHistoryItemClick={vi.fn()}
        />
      </UiLanguageProvider>,
    );

    expect(screen.queryByText('自选股')).not.toBeInTheDocument();
    expect(screen.getByTestId('watchlist-subline')).toHaveTextContent('2 只 · 今日 1/2 已分析');
    expect(screen.queryByRole('button', { name: '分析全部' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /分析未完成 1/ }));
    expect(onAnalyzeWatchlist).toHaveBeenLastCalledWith('pending');

    fireEvent.click(screen.getByRole('button', { name: '更多分析选项' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '分析全部' }));
    expect(onAnalyzeWatchlist).toHaveBeenLastCalledWith('all');

    expect(screen.queryByLabelText('添加代码，如 600519')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));
    expect(screen.getByLabelText('添加代码，如 600519')).toBeInTheDocument();
  });

  it('keeps the watchlist row selected for equivalent stock-code formats', () => {
    renderWorkspace({
      watchlistRows: [{
        code: 'HK700',
        analyzedToday: true,
        latestItem: {
          id: 88,
          stockCode: '00700',
          stockName: '腾讯控股',
          sentimentScore: 91,
          operationAdvice: '买入',
          analysisCount: 1,
          lastAnalysisTime: '2026-03-19T09:00:00+08:00',
        },
      }],
      selectedStockCode: '00700.HK',
    });

    expect(screen.getByRole('button', { name: '打开 HK700 最新分析详情' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('keeps a same-code stock row selected without selecting the index row', () => {
    renderWorkspace({
      watchlistRows: [
        {
          code: 'sh000016',
          assetType: 'index',
          analyzedToday: true,
          latestItem: {
            id: 31,
            stockCode: 'sh000016',
            stockName: '上证50',
            sentimentScore: 66,
            operationAdvice: '观望',
            analysisCount: 1,
            lastAnalysisTime: '2026-03-19T09:00:00+08:00',
            assetType: 'index',
          },
        },
        {
          code: '000016',
          assetType: 'stock',
          analyzedToday: true,
          latestItem: {
            id: 32,
            stockCode: '000016',
            stockName: '深康佳A',
            sentimentScore: 71,
            operationAdvice: '买入',
            analysisCount: 1,
            lastAnalysisTime: '2026-03-19T09:00:00+08:00',
            assetType: 'stock',
          },
        },
      ],
      selectedStockCode: '000016',
      selectedAssetType: 'stock',
      selectedRecordId: 32,
    });

    const stockRowButton = screen.getByTestId('watchlist-row-000016').querySelector('button[aria-pressed]');
    const indexRowButton = screen.getByTestId('watchlist-row-sh000016').querySelector('button[aria-pressed]');
    expect(stockRowButton).toHaveAttribute('aria-pressed', 'true');
    expect(indexRowButton).toHaveAttribute('aria-pressed', 'false');
  });

  it('selects the index row when the index report is active', () => {
    renderWorkspace({
      watchlistRows: [
        {
          code: 'sh000016',
          assetType: 'index',
          analyzedToday: true,
          latestItem: {
            id: 41,
            stockCode: 'SH000016',
            stockName: '上证50',
            sentimentScore: 66,
            operationAdvice: '观望',
            analysisCount: 2,
            lastAnalysisTime: '2026-03-19T09:00:00+08:00',
            assetType: 'index',
          },
        },
        {
          code: '000016',
          assetType: 'stock',
          analyzedToday: true,
          latestItem: {
            id: 42,
            stockCode: '000016',
            stockName: '深康佳A',
            sentimentScore: 71,
            operationAdvice: '买入',
            analysisCount: 1,
            lastAnalysisTime: '2026-03-19T09:00:00+08:00',
            assetType: 'stock',
          },
        },
      ],
      selectedStockCode: 'sh000016',
      selectedAssetType: 'index',
      selectedRecordId: 41,
    });

    const indexRowButton = screen.getByTestId('watchlist-row-sh000016').querySelector('button[aria-pressed]');
    const stockRowButton = screen.getByTestId('watchlist-row-000016').querySelector('button[aria-pressed]');
    expect(indexRowButton).toHaveAttribute('aria-pressed', 'true');
    expect(stockRowButton).toHaveAttribute('aria-pressed', 'false');
  });

  it('selects an alias-form index row via its registry identity even without a latest detail (PR #2312)', () => {
    renderWorkspace({
      watchlistRows: [
        {
          code: '000016.SH',
          assetType: 'index',
          identityKey: 'sh000016',
          analyzedToday: true,
        },
        {
          code: '000016',
          assetType: 'stock',
          analyzedToday: true,
        },
      ],
      selectedStockCode: 'sh000016',
      selectedAssetType: 'index',
    });

    // No `selectedRecordId` and no latest detail on either row, so selection
    // must come from the identity comparison: the canonical report pairs with
    // the alias row through `identityKey` (HomePage's registry resolution) and
    // never with the bare `000016` stock row.
    const aliasRowButton = screen.getByTestId('watchlist-row-000016.SH').querySelector('button[aria-pressed]');
    const stockRowButton = screen.getByTestId('watchlist-row-000016').querySelector('button[aria-pressed]');
    expect(aliasRowButton).toHaveAttribute('aria-pressed', 'true');
    expect(stockRowButton).toHaveAttribute('aria-pressed', 'false');
  });

  it('keeps the no-detail notice on the triggering index row instead of reusing the same-code stock row detail (PR #2312)', async () => {
    const { onHistoryItemClick } = renderWorkspace({
      watchlistRows: [
        {
          code: '000016',
          assetType: 'stock',
          analyzedToday: true,
          latestItem: {
            id: 99,
            stockCode: '000016',
            stockName: '深康佳A',
            sentimentScore: 70,
            operationAdvice: '买入',
            analysisCount: 1,
            lastAnalysisTime: '2026-03-19T09:00:00+08:00',
            assetType: 'stock',
          },
        },
        {
          code: '000016.SH',
          assetType: 'index',
          analyzedToday: false,
        },
      ],
    });

    fireEvent.click(screen.getByTestId('watchlist-row-000016.SH').querySelector('button[aria-pressed]') as HTMLButtonElement);

    // The index row has no detail yet. The notice carries the triggering row's
    // own code+assetType (000016.SH / index); without that, the shared stock
    // normalization would fold 000016.SH to 000016 and the notice would be
    // swallowed by the stock row (which HAS a detail).
    expect(await screen.findByRole('alert')).toHaveTextContent('暂无分析详情，可先分析。');
    expect(onHistoryItemClick).not.toHaveBeenCalled();
  });
});

describe('HomeStockWorkspace watchlist groups', () => {
  const rows: HomeWatchlistRow[] = ['2330.TW', '2317.TW', 'AAPL'].map((code) => ({ code, analyzedToday: false }));

  function renderGroups(watchlistGroups: Array<{ name: string; codes: string[] }>) {
    const onSaveWatchlistGroups = vi.fn().mockResolvedValue(undefined);
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    render(
      <UiLanguageProvider>
        <HomeStockWorkspace
          activeTab="watchlist"
          onTabChange={vi.fn()}
          watchlistRows={rows}
          watchlistLoading={false}
          watchlistActioning={false}
          watchlistMessage={null}
          onAddToWatchlist={vi.fn().mockResolvedValue(undefined)}
          onRemoveFromWatchlist={vi.fn().mockResolvedValue(undefined)}
          onRefreshWatchlist={vi.fn().mockResolvedValue(undefined)}
          onAnalyzeWatchlist={vi.fn().mockResolvedValue(undefined)}
          isBatchAnalyzing={false}
          batchStatus={null}
          todayItems={[]}
          isLoadingTodayItems={false}
          todayLoadError={false}
          watchlistAnalyzedTodayCount={0}
          historyItems={[]}
          isLoadingHistory={false}
          onHistoryItemClick={vi.fn()}
          watchlistGroups={watchlistGroups}
          onSaveWatchlistGroups={onSaveWatchlistGroups}
        />
      </UiLanguageProvider>,
    );
    return { onSaveWatchlistGroups };
  }

  it('shows no group filter when there are no groups', () => {
    renderGroups([]);
    expect(screen.queryByTestId('watchlist-group-filter')).not.toBeInTheDocument();
    expect(screen.getByTestId('watchlist-row-AAPL')).toBeInTheDocument();
  });

  it('filters rows by the selected group and by ungrouped', () => {
    renderGroups([{ name: 'Tech', codes: ['2330.TW'] }]);

    fireEvent.change(screen.getByTestId('watchlist-group-filter'), { target: { value: 'group:Tech' } });
    expect(screen.getByTestId('watchlist-row-2330.TW')).toBeInTheDocument();
    expect(screen.queryByTestId('watchlist-row-AAPL')).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId('watchlist-group-filter'), { target: { value: 'ungrouped' } });
    expect(screen.queryByTestId('watchlist-row-2330.TW')).not.toBeInTheDocument();
    expect(screen.getByTestId('watchlist-row-AAPL')).toBeInTheDocument();
  });

  it('creates a group from edit mode and moves a code into it', () => {
    const { onSaveWatchlistGroups } = renderGroups([{ name: 'Tech', codes: [] }]);

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('New group name'), { target: { value: ' Cash ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add group' }));
    expect(onSaveWatchlistGroups).toHaveBeenLastCalledWith([
      { name: 'Tech', codes: [] },
      { name: 'Cash', codes: [] },
    ]);

    fireEvent.change(screen.getByLabelText('Move AAPL to a group'), { target: { value: 'Tech' } });
    expect(onSaveWatchlistGroups).toHaveBeenLastCalledWith([{ name: 'Tech', codes: ['AAPL'] }]);
  });
});
