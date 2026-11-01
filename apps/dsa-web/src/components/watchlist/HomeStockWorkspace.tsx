import type React from 'react';
import { useCallback, useId, useMemo, useState } from 'react';
import {
  ArrowDown,
  ArrowUp,
  CalendarDays,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Star,
  Trash2,
} from 'lucide-react';
import { Badge, Button, ConfirmDialog, InlineAlert, Input, ScrollArea, Segmented, StatusDot } from '../common';
import { DashboardPanelHeader, DashboardStateBlock } from '../dashboard';
import { StockBar } from '../history';
import { StockBarItemComponent, StockRowLines } from '../history/StockBarItem';
import type { StockQuote } from '../../api/stocks';
import type { WatchlistGroup } from '../../api/systemConfig';
import { stockQuoteKey } from '../../hooks/useStockQuotes';
import type { StockBarItem, TaskInfo } from '../../types/analysis';
import { areAssetAwareCodesEquivalent, toAssetAwareCodeKey, type AssetAwareAssetType } from '../../utils/stockCode';
import { getStockMarketBucket } from '../../utils/stockName';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey, UiTextParams } from '../../i18n/uiText';
import { isWatchlistRowPendingAnalysis } from './watchlistRowState';
import {
  assignCodeToGroup,
  filterRowsByGroup,
  groupFilterValue,
  moveCodeWithinGroup,
  normalizeNewGroupName,
  resolveGroupFilter,
  type WatchlistGroupFilter,
} from './watchlistGroups';

export type HomeWorkspaceTab = 'watchlist' | 'today' | 'history';
export type WatchlistAnalyzeMode = 'all' | 'pending';
type MarketFilter = 'all' | 'tw' | 'us';
type ListSort = 'default' | 'change' | 'score' | 'time';

export interface HomeWatchlistRow {
  code: string;
  assetType?: AssetAwareAssetType;
  /**
   * Asset-aware identity key already resolved by HomePage from the stock index
   * registry (canonical for registered indices, e.g. `sh000016` for a raw
   * watchlist string `000016.SH`). Row-selection compares against this key
   * FIRST instead of re-parsing the raw alias, so a canonical selected report
   * always selects its own alias-form row and never a same-code stock row.
   */
  identityKey?: string;
  latestItem?: StockBarItem;
  analyzedToday: boolean;
  isTodayStatusLoading?: boolean;
  isTodayStatusUnknown?: boolean;
  activeTask?: TaskInfo;
}

interface BatchStatus {
  variant: 'success' | 'warning' | 'danger';
  message: string;
}

type WatchlistSignalTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

interface WatchlistSignal {
  label: string;
  value: string;
  tone: WatchlistSignalTone;
  pulse?: boolean;
}

interface WatchlistRowSignals {
  change: WatchlistSignal;
  state: WatchlistSignal;
  nextAction: WatchlistSignal;
}

function buildSignalDescription(
  signals: WatchlistSignal[],
  t: (key: UiTextKey, params?: UiTextParams) => string,
) {
  return signals
    .map((signal) => t('watchlist.signalSummaryItem', { label: signal.label, value: signal.value }))
    .join(t('watchlist.signalSummarySeparator'));
}

interface HomeStockWorkspaceProps {
  activeTab: HomeWorkspaceTab;
  onTabChange: (tab: HomeWorkspaceTab) => void;
  watchlistRows: HomeWatchlistRow[];
  watchlistLoading: boolean;
  watchlistActioning: boolean;
  watchlistMessage: string | null;
  onAddToWatchlist: (code: string) => Promise<void>;
  onRemoveFromWatchlist: (code: string) => Promise<void>;
  onRefreshWatchlist: () => Promise<void>;
  onAnalyzeWatchlist: (mode: WatchlistAnalyzeMode) => Promise<void>;
  isBatchAnalyzing: boolean;
  batchStatus: BatchStatus | null;
  todayItems: StockBarItem[];
  isLoadingTodayItems: boolean;
  todayLoadError: boolean;
  watchlistAnalyzedTodayCount: number;
  historyItems: StockBarItem[];
  isLoadingHistory: boolean;
  selectedStockCode?: string;
  selectedAssetType?: AssetAwareAssetType | null;
  selectedRecordId?: number;
  onHistoryItemClick: (recordId: number) => void;
  onDeleteStock?: (stockCode: string) => Promise<void> | void;
  isDeleting?: boolean;
  className?: string;
  /** 批次行情，鍵為 stockQuoteKey(code)。 */
  quotes?: Map<string, StockQuote>;
  /** 大盤複盤列：釘在自選、今日兩個頁籤最上面（全部頁籤由 StockBar 釘頂）。 */
  marketReviewItem?: StockBarItem;
  marketLightLabel?: string;
  /** 自選分組；空陣列時畫面與未分組前相同（編輯模式才看得到新增分組）。 */
  watchlistGroups?: WatchlistGroup[];
  onSaveWatchlistGroups?: (groups: WatchlistGroup[]) => Promise<void>;
}

const NO_WATCHLIST_GROUPS: WatchlistGroup[] = [];

function getTaskStatusLabel(task: TaskInfo | undefined, t: (key: UiTextKey, params?: UiTextParams) => string) {
  if (!task) return '';
  if (task.status === 'processing') return t('taskPanel.processing');
  if (task.status === 'pending') return t('taskPanel.pending');
  if (task.status === 'cancel_requested') return t('taskPanel.cancelRequested');
  return task.status;
}

function buildWatchlistRowSignals({
  row,
  canOpenDetail,
  isLatestDetailLoading,
  isLatestDetailUnavailable,
  taskLabel,
  t,
}: {
  row: HomeWatchlistRow;
  canOpenDetail: boolean;
  isLatestDetailLoading: boolean;
  isLatestDetailUnavailable: boolean;
  taskLabel: string;
  t: (key: UiTextKey, params?: UiTextParams) => string;
}): WatchlistRowSignals {
  let change: Omit<WatchlistSignal, 'label'>;
  let state: Omit<WatchlistSignal, 'label'>;
  let nextAction: Omit<WatchlistSignal, 'label'>;

  if (isLatestDetailLoading) {
    change = { value: t('watchlist.changeLoading'), tone: 'info', pulse: true };
    state = { value: t('watchlist.stateLoading'), tone: 'info', pulse: true };
    nextAction = { value: t('watchlist.nextWaitStatus'), tone: 'info', pulse: true };
  } else if (isLatestDetailUnavailable) {
    change = { value: t('watchlist.changeUnknown'), tone: 'warning' };
    state = { value: t('watchlist.stateUnknown'), tone: 'warning' };
    nextAction = { value: t('watchlist.nextRefresh'), tone: 'warning' };
  } else {
    if (row.analyzedToday) {
      change = { value: t('watchlist.changeAnalyzedToday'), tone: 'success' };
      state = { value: t('watchlist.stateAnalyzed'), tone: 'success' };
      nextAction = {
        value: canOpenDetail ? t('watchlist.nextOpenLatest') : t('watchlist.nextRefresh'),
        tone: canOpenDetail ? 'success' : 'warning',
      };
    } else if (row.latestItem) {
      change = { value: t('watchlist.changeHasLatest'), tone: 'info' };
      state = { value: t('watchlist.statePending'), tone: 'warning' };
      nextAction = { value: t('watchlist.nextAnalyze'), tone: 'warning' };
    } else {
      change = { value: t('watchlist.changeNoReport'), tone: 'neutral' };
      state = { value: t('watchlist.statePending'), tone: 'warning' };
      nextAction = { value: t('watchlist.nextAnalyze'), tone: 'warning' };
    }
  }

  if (row.activeTask) {
    state = {
      value: t('watchlist.stateTask', { status: taskLabel }),
      tone: row.activeTask.status === 'processing' ? 'info' : 'neutral',
      pulse: row.activeTask.status === 'processing',
    };
    nextAction = {
      value: t('watchlist.nextWaitTask'),
      tone: row.activeTask.status === 'processing' ? 'info' : 'neutral',
      pulse: row.activeTask.status === 'processing',
    };
  }

  return {
    change: { label: t('watchlist.change'), ...change },
    state: { label: t('watchlist.state'), ...state },
    nextAction: { label: t('watchlist.nextAction'), ...nextAction },
  };
}

function rowHasSelectedIdentity(
  row: HomeWatchlistRow,
  selectedStockCode: string | null | undefined,
  selectedAssetType: AssetAwareAssetType | null | undefined,
): boolean {
  // The registry-derived canonical identity (HomePage) wins: an alias-form raw
  // watchlist code (e.g. `000016.SH`) whose identityKey is `sh000016` must
  // match the canonical selected report without re-parsing the raw alias, and
  // must never fold with the bare `000016` stock row.
  if (row.identityKey) {
    return toAssetAwareCodeKey(selectedStockCode, selectedAssetType) === row.identityKey;
  }
  return areAssetAwareCodesEquivalent(selectedStockCode, selectedAssetType, row.code, row.assetType);
}

const WatchlistRowItem: React.FC<{
  row: HomeWatchlistRow;
  onRequestRemove: (code: string) => void;
  onOpenDetail: (row: HomeWatchlistRow) => void;
  disabled: boolean;
  selected: boolean;
  editMode: boolean;
  quote?: StockQuote;
  groupControls?: React.ReactNode;
}> = ({ row, onRequestRemove, onOpenDetail, disabled, selected, editMode, quote, groupControls }) => {
  const { t } = useUiLanguage();
  const signalDescriptionId = useId();
  const taskLabel = getTaskStatusLabel(row.activeTask, t);
  const isLatestDetailLoading = Boolean(row.isTodayStatusLoading);
  const isLatestDetailUnavailable = !isLatestDetailLoading && Boolean(row.isTodayStatusUnknown);
  const item = isLatestDetailLoading || isLatestDetailUnavailable ? undefined : row.latestItem;
  const canOpenDetail = typeof item?.id === 'number';
  const signals = buildWatchlistRowSignals({
    row,
    canOpenDetail,
    isLatestDetailLoading,
    isLatestDetailUnavailable,
    taskLabel,
    t,
  });
  const signalDescription = buildSignalDescription([signals.change, signals.state, signals.nextAction], t);

  return (
    <div
      className={`home-subpanel group flex min-h-[52px] min-w-0 items-center gap-2 px-2.5 py-1.5 text-left transition-colors ${
        selected
          ? 'border-primary/35 bg-primary/10'
          : 'hover:border-subtle-hover hover:bg-base/65'
      }`}
      data-testid={`watchlist-row-${row.code}`}
    >
      <button
        type="button"
        aria-pressed={selected}
        aria-label={canOpenDetail
          ? t('watchlist.openLatestDetailAria', { code: row.code })
          : isLatestDetailLoading
            ? t('watchlist.latestDetailLoadingAria', { code: row.code })
            : isLatestDetailUnavailable
              ? t('watchlist.latestDetailUnavailableAria', { code: row.code })
            : t('watchlist.noLatestDetailAria', { code: row.code })}
        aria-describedby={signalDescriptionId}
        className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan/30"
        onClick={() => onOpenDetail(row)}
      >
        {/* 兩行列放不下三格狀態，文字留給輔助科技，視覺上由左側圖示與任務點表示。 */}
        <span id={signalDescriptionId} className="sr-only">
          {signalDescription}
        </span>
        {row.isTodayStatusLoading ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-text" aria-label={t('watchlist.todayStatusLoading')} />
        ) : row.isTodayStatusUnknown ? (
          <CircleAlert className="h-3.5 w-3.5 shrink-0 text-warning" aria-label={t('watchlist.todayStatusUnavailable')} />
        ) : row.analyzedToday ? (
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" aria-label={t('watchlist.analyzedToday')} />
        ) : (
          <Clock3 className="h-3.5 w-3.5 shrink-0 text-muted-text" aria-label={t('watchlist.notAnalyzedToday')} />
        )}
        {row.activeTask ? (
          <StatusDot
            tone={row.activeTask.status === 'processing' ? 'info' : 'neutral'}
            pulse={row.activeTask.status === 'processing'}
            className="h-1.5 w-1.5 shrink-0"
          />
        ) : null}
        <StockRowLines
          code={row.code}
          name={row.latestItem?.stockName}
          quote={quote}
          analysisPrice={item?.analysisPrice}
          item={item}
        />
      </button>
      {editMode ? groupControls : null}
      {editMode ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 w-7 shrink-0 px-0"
          disabled={disabled}
          aria-label={t('watchlist.removeAria', { code: row.code })}
          onClick={() => onRequestRemove(row.code)}
        >
          <Trash2 className="h-3.5 w-3.5 text-danger" aria-hidden="true" />
        </Button>
      ) : null}
    </div>
  );
};

const TodayItem: React.FC<{
  item: StockBarItem;
  onClick: (recordId: number) => void;
  quote?: StockQuote;
}> = ({ item, onClick, quote }) => (
  <button
    type="button"
    className="home-subpanel flex min-h-[52px] w-full min-w-0 items-center gap-2 px-2.5 py-1.5 text-left"
    onClick={() => onClick(item.id)}
  >
    <StockRowLines
      code={item.stockCode}
      name={item.stockName}
      quote={quote}
      analysisPrice={item.analysisPrice}
      item={item}
    />
  </button>
);

const analysisTime = (item?: StockBarItem): number => {
  const parsed = item?.lastAnalysisTime ? Date.parse(item.lastAnalysisTime) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
};

/** 缺讀數的一律排最後，不當成 0。default 維持呼叫端給的順序。 */
function sortRows<T>(
  rows: T[],
  sort: ListSort,
  getCode: (row: T) => string,
  getItem: (row: T) => StockBarItem | undefined,
  quotes?: Map<string, StockQuote>,
): T[] {
  if (sort === 'default') return rows;
  const readValue = (row: T): number | null => {
    if (sort === 'change') {
      const change = quotes?.get(stockQuoteKey(getCode(row)))?.changePercent;
      return typeof change === 'number' ? change : null;
    }
    const item = getItem(row);
    if (sort === 'score') return typeof item?.sentimentScore === 'number' ? item.sentimentScore : null;
    return analysisTime(item) || null;
  };
  return [...rows].sort((left, right) => {
    const leftValue = readValue(left);
    const rightValue = readValue(right);
    if (leftValue === null) return rightValue === null ? 0 : 1;
    if (rightValue === null) return -1;
    return rightValue - leftValue;
  });
}

export const HomeStockWorkspace: React.FC<HomeStockWorkspaceProps> = ({
  activeTab,
  onTabChange,
  watchlistRows,
  watchlistLoading,
  watchlistActioning,
  watchlistMessage,
  onAddToWatchlist,
  onRemoveFromWatchlist,
  onRefreshWatchlist,
  onAnalyzeWatchlist,
  isBatchAnalyzing,
  batchStatus,
  todayItems,
  isLoadingTodayItems,
  todayLoadError,
  watchlistAnalyzedTodayCount,
  historyItems,
  isLoadingHistory,
  selectedStockCode,
  selectedAssetType,
  selectedRecordId,
  onHistoryItemClick,
  onDeleteStock,
  isDeleting = false,
  className = '',
  quotes,
  marketReviewItem,
  marketLightLabel,
  watchlistGroups = NO_WATCHLIST_GROUPS,
  onSaveWatchlistGroups,
}) => {
  const { t } = useUiLanguage();
  const [draftCode, setDraftCode] = useState('');
  const [groupFilter, setGroupFilter] = useState<WatchlistGroupFilter>('all');
  const [draftGroupName, setDraftGroupName] = useState('');
  const [marketFilter, setMarketFilter] = useState<MarketFilter>('all');
  const [listSort, setListSort] = useState<ListSort>('default');
  const [editMode, setEditMode] = useState(false);
  const [pendingRemoveCode, setPendingRemoveCode] = useState<string | null>(null);
  // PR #2312: the notice carries the *triggering row's own* identity
  // (code + assetType). Reusing the candidate row's assetType for the notice
  // code would let an index row and a same-code stock row cross-match (e.g.
  // notice code ``000016.SH`` classified with the stock row's asset type folds
  // to stock ``000016`` and attaches to the wrong row).
  const [workspaceNotice, setWorkspaceNotice] = useState<{ code: string; assetType: AssetAwareAssetType } | null>(null);
  const pendingWatchlistCount = watchlistRows.filter(isWatchlistRowPendingAnalysis).length;
  const isTodayStatusUnavailable = watchlistRows.some((row) => row.isTodayStatusLoading || row.isTodayStatusUnknown);
  const topTodayItem = todayItems[0];
  const tabs: Array<{ key: HomeWorkspaceTab; label: string }> = [
    { key: 'watchlist', label: t('watchlist.tabWatchlist') },
    { key: 'today', label: t('watchlist.tabToday') },
    { key: 'history', label: t('watchlist.tabHistory') },
  ];

  const matchesMarket = useCallback(
    (code: string) => marketFilter === 'all' || getStockMarketBucket(code) === marketFilter,
    [marketFilter],
  );
  const activeGroupFilter = resolveGroupFilter(groupFilter, watchlistGroups);
  const activeGroupName = activeGroupFilter.startsWith('group:') ? activeGroupFilter.slice('group:'.length) : null;
  const newGroupName = normalizeNewGroupName(draftGroupName, watchlistGroups);
  const visibleWatchlistRows = useMemo(() => sortRows(
    filterRowsByGroup(watchlistRows, (row) => row.code, activeGroupFilter, watchlistGroups)
      .filter((row) => matchesMarket(row.code)),
    listSort,
    (row) => row.code,
    (row) => row.latestItem,
    quotes,
  ), [activeGroupFilter, listSort, matchesMarket, quotes, watchlistGroups, watchlistRows]);
  const visibleTodayItems = useMemo(() => sortRows(
    todayItems.filter((item) => matchesMarket(item.stockCode)),
    listSort,
    (item) => item.stockCode,
    (item) => item,
    quotes,
  ), [listSort, matchesMarket, quotes, todayItems]);
  const visibleHistoryItems = useMemo(() => sortRows(
    historyItems.filter((item) => item.stockCode === 'MARKET' || matchesMarket(item.stockCode)),
    listSort,
    (item) => item.stockCode,
    (item) => item,
    quotes,
  ), [historyItems, listSort, matchesMarket, quotes]);

  const listControls = (
    <div className="flex flex-wrap items-center justify-between gap-1.5" data-testid="home-list-controls">
      <Segmented<MarketFilter>
        size="sm"
        aria-label={t('watchlist.marketFilterAria')}
        value={marketFilter}
        onChange={setMarketFilter}
        options={[
          { value: 'all', label: t('watchlist.filterAll') },
          { value: 'tw', label: t('watchlist.filterTw') },
          { value: 'us', label: t('watchlist.filterUs') },
        ]}
      />
      <select
        aria-label={t('watchlist.sortAria')}
        value={listSort}
        onChange={(event) => setListSort(event.target.value as ListSort)}
        className="h-7 rounded-lg border border-subtle bg-base/40 px-1.5 text-xs text-secondary-text"
      >
        <option value="default">{t('watchlist.sortDefault')}</option>
        <option value="change">{t('watchlist.sortChange')}</option>
        <option value="score">{t('watchlist.sortScore')}</option>
        <option value="time">{t('watchlist.sortTime')}</option>
      </select>
    </div>
  );

  const saveGroups = (next: WatchlistGroup[]) => {
    // 失敗由 useWatchlist 的 actionMessage（操作失敗）顯示在面板上方。
    void onSaveWatchlistGroups?.(next);
  };

  const handleAddGroup = (event: React.FormEvent) => {
    event.preventDefault();
    if (!newGroupName) return;
    saveGroups([...watchlistGroups, { name: newGroupName, codes: [] }]);
    setDraftGroupName('');
  };

  const groupSelect = watchlistGroups.length > 0 ? (
    <select
      aria-label={t('watchlist.groupFilterAria')}
      data-testid="watchlist-group-filter"
      value={activeGroupFilter}
      onChange={(event) => setGroupFilter(event.target.value as WatchlistGroupFilter)}
      className="h-7 max-w-[10rem] rounded-lg border border-subtle bg-base/40 px-1.5 text-xs text-secondary-text"
    >
      <option value="all">{t('watchlist.groupAll')}</option>
      {watchlistGroups.map((group) => (
        <option key={group.name} value={groupFilterValue(group.name)}>{group.name}</option>
      ))}
      <option value="ungrouped">{t('watchlist.groupUngrouped')}</option>
    </select>
  ) : null;

  const groupEditor = editMode && onSaveWatchlistGroups ? (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="watchlist-group-editor">
      <form className="flex min-w-0 flex-1 items-center gap-1.5" onSubmit={handleAddGroup}>
        <Input
          value={draftGroupName}
          onChange={(event) => setDraftGroupName(event.target.value)}
          placeholder={t('watchlist.groupNamePlaceholder')}
          aria-label={t('watchlist.groupNamePlaceholder')}
          className="h-8 rounded-lg px-3 text-xs"
          disabled={watchlistActioning}
        />
        <Button type="submit" size="sm" variant="secondary" disabled={!newGroupName || watchlistActioning}>
          {t('watchlist.groupAdd')}
        </Button>
      </form>
      {activeGroupName ? (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={watchlistActioning}
          onClick={() => saveGroups(watchlistGroups.filter((group) => group.name !== activeGroupName))}
        >
          {t('watchlist.groupDelete', { name: activeGroupName })}
        </Button>
      ) : null}
    </div>
  ) : null;

  const renderGroupControls = (code: string) => {
    if (!onSaveWatchlistGroups || watchlistGroups.length === 0) return null;
    const currentGroup = watchlistGroups.find((group) => group.codes.includes(code))?.name ?? '';
    return (
      <>
        {activeGroupName ? (
          <>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 w-7 shrink-0 px-0"
              disabled={watchlistActioning}
              aria-label={t('watchlist.groupMoveUpAria', { code })}
              onClick={() => saveGroups(moveCodeWithinGroup(watchlistGroups, activeGroupName, code, -1))}
            >
              <ArrowUp className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 w-7 shrink-0 px-0"
              disabled={watchlistActioning}
              aria-label={t('watchlist.groupMoveDownAria', { code })}
              onClick={() => saveGroups(moveCodeWithinGroup(watchlistGroups, activeGroupName, code, 1))}
            >
              <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
          </>
        ) : null}
        <select
          aria-label={t('watchlist.groupMoveAria', { code })}
          value={currentGroup}
          disabled={watchlistActioning}
          onChange={(event) => saveGroups(assignCodeToGroup(watchlistGroups, code, event.target.value || null))}
          className="h-7 max-w-[6rem] shrink-0 rounded-lg border border-subtle bg-base/40 px-1 text-xs text-secondary-text"
        >
          <option value="">{t('watchlist.groupUngrouped')}</option>
          {watchlistGroups.map((group) => (
            <option key={group.name} value={group.name}>{group.name}</option>
          ))}
        </select>
      </>
    );
  };

  const pinnedMarketReview = marketReviewItem ? (
    <StockBarItemComponent
      item={marketReviewItem}
      isViewing={selectedRecordId === marketReviewItem.id}
      onClick={onHistoryItemClick}
      isMarketReview
      marketLightLabel={marketLightLabel}
    />
  ) : null;

  const statusClassName = useMemo(() => {
    if (!batchStatus) return '';
    if (batchStatus.variant === 'danger') return 'border-danger/30 bg-danger/10 text-danger';
    if (batchStatus.variant === 'warning') return 'border-warning/30 bg-warning/10 text-warning';
    return 'border-success/30 bg-success/10 text-success';
  }, [batchStatus]);

  const visibleWorkspaceNotice = useMemo(() => {
    if (!workspaceNotice) return null;
    const row = watchlistRows.find(
      (item) => areAssetAwareCodesEquivalent(item.code, item.assetType, workspaceNotice.code, workspaceNotice.assetType),
    );
    if (!row) return null;
    if (row.isTodayStatusLoading) {
      return { message: t('watchlist.latestDetailLoading') };
    }
    if (row.isTodayStatusUnknown) {
      return { message: t('watchlist.latestDetailUnavailable') };
    }
    if (row.latestItem) return null;
    return { message: t('watchlist.noLatestDetail') };
  }, [t, watchlistRows, workspaceNotice]);

  const handleAddSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const code = draftCode.trim();
    if (!code) return;
    setWorkspaceNotice(null);
    void onAddToWatchlist(code).then(() => setDraftCode(''));
  };

  const handleWatchlistRowOpen = (row: HomeWatchlistRow) => {
    if (row.isTodayStatusLoading || row.isTodayStatusUnknown) {
      setWorkspaceNotice({ code: row.code, assetType: row.assetType ?? 'stock' });
      return;
    }
    const recordId = row.latestItem?.id;
    if (typeof recordId === 'number') {
      setWorkspaceNotice(null);
      onHistoryItemClick(recordId);
      return;
    }
    setWorkspaceNotice({ code: row.code, assetType: row.assetType ?? 'stock' });
  };

  const renderTabs = (
    <div className="grid grid-cols-3 gap-1 rounded-xl border border-subtle bg-base/40 p-1">
      {tabs.map((tab) => {
        const selected = activeTab === tab.key;
        return (
          <button
            key={tab.key}
            type="button"
            aria-pressed={selected}
            className={`h-8 rounded-lg px-2 text-xs font-medium transition-colors ${
              selected ? 'bg-primary/15 text-primary shadow-inner' : 'text-secondary-text hover:bg-hover hover:text-foreground'
            }`}
            onClick={() => {
              setWorkspaceNotice(null);
              onTabChange(tab.key);
            }}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );

  if (activeTab === 'history') {
    return (
      <div
        data-testid="home-stock-workspace"
        className={`home-stock-scroll-shell flex min-h-0 flex-1 flex-col gap-2 ${className}`}
      >
        {renderTabs}
        <StockBar
          items={visibleHistoryItems}
          isLoading={isLoadingHistory}
          selectedStockCode={selectedStockCode}
          selectedRecordId={selectedRecordId}
          onItemClick={onHistoryItemClick}
          onDeleteStock={onDeleteStock}
          isDeleting={isDeleting}
          className="flex-1"
          quotes={quotes}
          marketLightLabel={marketLightLabel}
          controls={listControls}
        />
      </div>
    );
  }

  return (
    <aside
      data-testid="home-stock-workspace"
      className={`glass-card home-stock-scroll-shell flex min-h-0 flex-1 flex-col ${className}`}
    >
      <div className="space-y-2.5 border-b border-subtle px-3 py-3 sm:px-4">
        {renderTabs}

        {activeTab === 'watchlist' ? (
          <>
            <DashboardPanelHeader
              className="mb-0"
              title={t('watchlist.title')}
              titleClassName="text-sm font-medium"
              leading={<Star className="h-4 w-4 text-primary" aria-hidden="true" />}
              actions={(
                <div className="flex items-center gap-1.5">
                  <span className="text-[11px] text-muted-text">{t('common.itemsCount', { count: watchlistRows.length })}</span>
                  {watchlistRows.length > 0 ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-pressed={editMode}
                      onClick={() => setEditMode((current) => !current)}
                    >
                      {editMode ? t('watchlist.editDone') : t('watchlist.edit')}
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 px-0"
                    disabled={watchlistLoading}
                    onClick={() => {
                      setWorkspaceNotice(null);
                      void onRefreshWatchlist();
                    }}
                    aria-label={t('watchlist.refreshAria')}
                  >
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                  </Button>
                </div>
              )}
            />
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="default" className="gap-1 shadow-none text-[11px]">
                {t('watchlist.todayCoverage')} {watchlistAnalyzedTodayCount}/{watchlistRows.length}
              </Badge>
              <Badge variant="default" className="gap-1 shadow-none text-[11px]">
                {t('watchlist.pendingToday')} {pendingWatchlistCount}
              </Badge>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant="primary"
                className="h-8 flex-1 whitespace-nowrap px-2 text-xs sm:flex-none"
                disabled={watchlistLoading || watchlistRows.length === 0 || isBatchAnalyzing}
                isLoading={isBatchAnalyzing}
                loadingText={t('watchlist.submitting')}
                onClick={() => void onAnalyzeWatchlist('all')}
              >
                <Play className="h-4 w-4" aria-hidden="true" />
                {t('watchlist.analyzeAll')}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="h-8 flex-1 whitespace-nowrap px-2 text-xs sm:flex-none"
                disabled={watchlistLoading || pendingWatchlistCount === 0 || isTodayStatusUnavailable || isBatchAnalyzing}
                onClick={() => void onAnalyzeWatchlist('pending')}
              >
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                {t('watchlist.analyzePending')}
              </Button>
            </div>
            <form className="grid grid-cols-[minmax(0,1fr)_auto] gap-2" onSubmit={handleAddSubmit}>
              <Input
                value={draftCode}
                onChange={(event) => setDraftCode(event.target.value)}
                placeholder={t('watchlist.addPlaceholder')}
                className="h-8 rounded-lg px-3 text-xs"
                disabled={watchlistActioning}
                aria-label={t('watchlist.addPlaceholder')}
              />
              <Button
                type="submit"
                size="sm"
                variant="secondary"
                className="h-8 w-8 px-0"
                disabled={!draftCode.trim() || watchlistActioning}
                isLoading={watchlistActioning}
                aria-label={t('watchlist.add')}
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
              </Button>
            </form>
            {batchStatus ? (
              <div className={`rounded-xl border px-3 py-2 text-xs ${statusClassName}`}>
                {batchStatus.message}
              </div>
            ) : null}
            {watchlistMessage ? (
              <div className="rounded-xl border border-subtle bg-base/35 px-3 py-2 text-xs text-secondary-text">
                {watchlistMessage}
              </div>
            ) : null}
            {groupEditor}
            {visibleWorkspaceNotice ? (
              <InlineAlert
                variant="warning"
                message={visibleWorkspaceNotice.message}
                className="rounded-xl px-3 py-2 text-xs shadow-none"
              />
            ) : null}
          </>
        ) : (
          <>
            <DashboardPanelHeader
              className="mb-0"
              title={t('watchlist.todayTitle')}
              titleClassName="text-sm font-medium"
              leading={<CalendarDays className="h-4 w-4 text-cyan" aria-hidden="true" />}
              actions={<span className="text-[11px] text-muted-text">{t('common.itemsCount', { count: todayItems.length })}</span>}
            />
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="default" className="gap-1 shadow-none text-[11px]">
                {t('watchlist.watchlistCoverage')} {watchlistAnalyzedTodayCount}/{watchlistRows.length}
              </Badge>
              <Badge variant="default" className="gap-1 shadow-none text-[11px]">
                {t('watchlist.topScore')} {topTodayItem?.sentimentScore ?? '-'}
              </Badge>
            </div>
          </>
        )}
        {activeTab === 'watchlist' && groupSelect ? (
          <div className="flex items-center gap-1.5">{groupSelect}</div>
        ) : null}
        {listControls}
      </div>

      <ScrollArea
        viewportClassName="px-3 py-3 sm:px-4 overscroll-y-contain touch-pan-y"
        className="min-h-0 flex-1"
        testId="home-stock-workspace-scroll"
      >
        {pinnedMarketReview ? <div className="mb-1.5">{pinnedMarketReview}</div> : null}
        {activeTab === 'watchlist' ? (
          watchlistLoading ? (
            <DashboardStateBlock loading compact title={t('watchlist.loading')} />
          ) : watchlistRows.length === 0 ? (
            <DashboardStateBlock
              compact
              title={t('watchlist.emptyTitle')}
              description={t('watchlist.emptyDescription')}
            />
          ) : (
            <div className="space-y-1.5">
              {visibleWatchlistRows.map((row) => (
                <WatchlistRowItem
                  key={row.code}
                  row={row}
                  onRequestRemove={(code) => {
                    setWorkspaceNotice(null);
                    setPendingRemoveCode(code);
                  }}
                  onOpenDetail={handleWatchlistRowOpen}
                  disabled={watchlistActioning}
                  editMode={editMode}
                  groupControls={renderGroupControls(row.code)}
                  quote={row.assetType === 'index' ? undefined : quotes?.get(stockQuoteKey(row.code))}
                  selected={
                    (typeof selectedRecordId === 'number' && selectedRecordId === row.latestItem?.id)
                    || (
                      Boolean(selectedStockCode)
                      && (
                        rowHasSelectedIdentity(row, selectedStockCode, selectedAssetType)
                        || areAssetAwareCodesEquivalent(selectedStockCode ?? '', selectedAssetType, row.latestItem?.stockCode ?? '', row.latestItem?.assetType)
                      )
                    )
                  }
                />
              ))}
            </div>
          )
        ) : isLoadingTodayItems ? (
          <DashboardStateBlock loading compact title={t('watchlist.loading')} />
        ) : todayLoadError ? (
          <DashboardStateBlock
            compact
            title={t('watchlist.todayLoadErrorTitle')}
            description={t('watchlist.todayLoadErrorDescription')}
          />
        ) : todayItems.length === 0 ? (
          <DashboardStateBlock
            compact
            title={t('watchlist.todayEmptyTitle')}
            description={t('watchlist.todayEmptyDescription')}
          />
        ) : (
          <div className="space-y-1.5">
            {visibleTodayItems.map((item) => (
              <TodayItem
                key={`${item.stockCode}-${item.id}`}
                item={item}
                onClick={onHistoryItemClick}
                quote={quotes?.get(stockQuoteKey(item.stockCode))}
              />
            ))}
          </div>
        )}
      </ScrollArea>
      <ConfirmDialog
        isOpen={pendingRemoveCode !== null}
        title={t('watchlist.removeConfirmTitle')}
        message={t('watchlist.removeConfirmMessage', { code: pendingRemoveCode ?? '' })}
        confirmText={t('common.delete')}
        isDanger
        onConfirm={() => {
          const code = pendingRemoveCode;
          setPendingRemoveCode(null);
          // 失敗由 useWatchlist 的 actionMessage（操作失敗）顯示在面板上方。
          if (code) void onRemoveFromWatchlist(code);
        }}
        onCancel={() => setPendingRemoveCode(null)}
      />
    </aside>
  );
};

export default HomeStockWorkspace;
