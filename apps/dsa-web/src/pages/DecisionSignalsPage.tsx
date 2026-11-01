import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, BarChart3, MoreHorizontal, RefreshCw, Search, ShieldCheck, SlidersHorizontal, X } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import {
  decisionSignalsApi,
  getDecisionSignalReassessBlockedError,
} from '../api/decisionSignals';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import { historyApi } from '../api/history';
import { stocksApi, type StockQuote } from '../api/stocks';
import {
  ApiErrorAlert,
  AppPage,
  Button,
  Card,
  Collapsible,
  ConfirmDialog,
  Drawer,
  EmptyState,
  IconButton,
  InlineAlert,
  PageHeader,
  Pagination,
} from '../components/common';
import {
  DecisionSignalCard,
  DecisionSignalDetails,
} from '../components/decision-signals/DecisionSignalDisplay';
import { DecisionSignalProfileCalibration } from '../components/decision-signals/DecisionSignalProfileCalibration';
import { DecisionSignalTable, DecisionSignalTableSkeleton } from '../components/decision-signals/DecisionSignalTable';
import { DecisionSignalTimeline } from '../components/decision-signals/DecisionSignalTimeline';
import { StockAutocomplete } from '../components/StockAutocomplete';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { useStockIndex } from '../hooks/useStockIndex';
import { formatUiText, type UiTextKey } from '../i18n/uiText';
import { SIGNALS_TEXT } from '../locales/signalsText';
import type { DecisionAction, MarketPhaseValue, StockBarItem } from '../types/analysis';
import type {
  DecisionSignalItem,
  DecisionSignalFeedbackItem,
  DecisionSignalFeedbackValue,
  DecisionSignalListParams,
  DecisionSignalMarket,
  DecisionSignalOutcomeItem,
  DecisionSignalOutcomeStatsResponse,
  DecisionSignalReassessResponse,
  DecisionSignalReassessBlockedError,
  DecisionSignalSourceType,
  DecisionSignalStatus,
  DecisionSignalSummaryResponse,
  DecisionProfile,
  DecisionProfileDisplay,
} from '../types/decisionSignals';
import type { Market, StockIndexItem } from '../types/stockIndex';
import { cn } from '../utils/cn';
import { formatNumber } from '../utils/format';
import { formatSignalText } from '../utils/signalText';
import { buildDecisionActionLabelMap, normalizeDecisionActionAlias } from '../utils/decisionAction';
import {
  getDecisionSignalMarketLabel,
  getDecisionSignalMarketPhaseLabel,
  getDecisionSignalSourceTypeLabel,
} from '../utils/decisionSignalLabels';
import { getDecisionProfile } from '../utils/decisionSignalProfile';
import { parseDecisionSignalDate } from '../utils/decisionSignalTime';
import { areStockCodesEquivalent, stockCodeMatchKey } from '../utils/stockCode';

const PAGE_SIZE = 20;
const TIMELINE_PAGE_SIZE = 100;
const STOCK_CANDIDATE_LIMIT = 8;
const DAY_MS = 86400_000;

type BaseListFilters = {
  market: '' | DecisionSignalMarket;
  marketPhase: '' | MarketPhaseValue;
  sourceType: '' | DecisionSignalSourceType;
  sourceReportId: string;
  status: '' | DecisionSignalStatus;
};

/** Filters that live in the URL (?holding=1&action=reduce&stop=triggered) so other pages can deep-link them. */
type UrlListFilters = {
  action: '' | DecisionAction;
  holdingOnly: boolean;
  stopTriggered: boolean;
};

type ListFilters = BaseListFilters & UrlListFilters;

type TimelineRange = '30d' | '90d' | '180d';
type TimelineStatusFilter = 'all' | 'active';

type TimelineFilters = {
  market: '' | DecisionSignalMarket;
  range: TimelineRange;
  status: TimelineStatusFilter;
  decisionProfile: '' | DecisionProfileDisplay;
};

type TimelineMarketSource = 'context' | 'user' | null;

type TimelineFilterUpdate = {
  filters: TimelineFilters;
  marketSource: TimelineMarketSource;
};

type AppliedTimelineContext = TimelineFilters & {
  stockCode: string;
};

type StockContext = {
  code: string;
  displayCode?: string;
  name?: string;
  market?: DecisionSignalMarket;
};

type StockCandidate = StockContext & {
  source: 'history' | 'popular';
};

type PendingStatusChange = {
  item: DecisionSignalItem;
  status: Extract<DecisionSignalStatus, 'closed' | 'invalidated' | 'archived'>;
  message: string;
};

type SelectedSignal = {
  item: DecisionSignalItem;
  source: 'list' | 'latest' | 'timeline' | 'persisted';
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const MARKET_OPTIONS: DecisionSignalMarket[] = ['cn', 'hk', 'us', 'jp', 'kr', 'tw'];
const ACTION_OPTIONS: DecisionAction[] = ['buy', 'add', 'hold', 'reduce', 'sell', 'watch', 'avoid', 'alert'];
const PHASE_OPTIONS: MarketPhaseValue[] = ['premarket', 'intraday', 'lunch_break', 'closing_auction', 'postmarket', 'non_trading', 'unknown'];
const SOURCE_OPTIONS: DecisionSignalSourceType[] = ['analysis', 'agent', 'alert', 'market_review', 'manual'];
const STATUS_OPTIONS: DecisionSignalStatus[] = ['active', 'expired', 'invalidated', 'closed', 'archived'];

const STATUS_ACTIONS: Array<PendingStatusChange['status']> = ['closed', 'invalidated', 'archived'];
const REASSESS_PROFILES: DecisionProfile[] = ['conservative', 'balanced', 'aggressive'];

const STATUS_LABEL_KEYS: Record<DecisionSignalStatus, UiTextKey> = {
  active: 'decisionSignals.active',
  expired: 'decisionSignals.expired',
  invalidated: 'decisionSignals.invalidated',
  closed: 'decisionSignals.closed',
  archived: 'decisionSignals.archived',
};

const STATUS_ACTION_LABEL_KEYS: Record<PendingStatusChange['status'], UiTextKey> = {
  closed: 'decisionSignals.close',
  invalidated: 'decisionSignals.invalidate',
  archived: 'decisionSignals.archive',
};

const STATUS_ACTION_CONFIRM_KEYS: Record<PendingStatusChange['status'], UiTextKey> = {
  closed: 'decisionSignals.closeConfirm',
  invalidated: 'decisionSignals.invalidateConfirm',
  archived: 'decisionSignals.archiveConfirm',
};

const DEFAULT_LIST_FILTERS: BaseListFilters = {
  market: '',
  marketPhase: '',
  sourceType: '',
  sourceReportId: '',
  status: 'active',
};

const DEFAULT_TIMELINE_FILTERS: TimelineFilters = {
  market: '',
  range: '90d',
  status: 'all',
  decisionProfile: '',
};

const TIMELINE_RANGE_DAYS: Record<TimelineRange, number> = {
  '30d': 30,
  '90d': 90,
  '180d': 180,
};

function parseSourceReportId(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

function parseUrlFilters(search: string): UrlListFilters {
  const params = new URLSearchParams(search);
  return {
    holdingOnly: params.get('holding') === '1',
    // Accepts enum names and stored labels (reduce, 減碼, 减仓); anything else is ignored.
    action: normalizeDecisionActionAlias(params.get('action')) ?? '',
    stopTriggered: params.get('stop') === 'triggered',
  };
}

function getInitialFilters(search = typeof window === 'undefined' ? '' : window.location.search): BaseListFilters {
  const params = new URLSearchParams(search);
  const sourceReportId = parseSourceReportId(params.get('sourceReportId') ?? params.get('source_report_id') ?? '');
  if (sourceReportId === undefined) return DEFAULT_LIST_FILTERS;
  return {
    ...DEFAULT_LIST_FILTERS,
    sourceReportId: String(sourceReportId),
  };
}

function toListParams(
  filters: ListFilters,
  stock: Pick<StockContext, 'code' | 'market'> | null,
  page: number,
): DecisionSignalListParams {
  const sourceReportId = parseSourceReportId(filters.sourceReportId);
  if (sourceReportId !== undefined) {
    return {
      sourceReportId,
      sourceType: 'analysis',
      page,
      pageSize: PAGE_SIZE,
    };
  }

  return {
    market: filters.market || stock?.market || undefined,
    stockCode: stock?.code.trim() || undefined,
    action: filters.action || undefined,
    marketPhase: filters.marketPhase || undefined,
    sourceType: filters.sourceType || undefined,
    status: filters.status || undefined,
    holdingOnly: filters.holdingOnly || undefined,
    // 每檔只留最新一筆，已觸停損與持股排最前；去重在後端做，跨頁才不會重複。
    groupLatest: true,
    sort: 'priority',
    page,
    pageSize: PAGE_SIZE,
  };
}

function refreshLatestSelection(
  current: SelectedSignal | null,
  latestItems: DecisionSignalItem[],
): SelectedSignal | null {
  if (!current || current.source !== 'latest') return current;
  const refreshed = latestItems.find((item) => item.id === current.item.id);
  return refreshed ? { source: 'latest', item: refreshed } : null;
}

function refreshTimelineSelection(
  current: SelectedSignal | null,
  timelineItems: DecisionSignalItem[],
): SelectedSignal | null {
  if (!current || current.source !== 'timeline') return current;
  const refreshed = timelineItems.find((item) => item.id === current.item.id);
  return refreshed ? { source: 'timeline', item: refreshed } : null;
}

function normalizeDecisionSignalMarket(value: unknown): DecisionSignalMarket | undefined {
  const market = String(value ?? '').trim().toUpperCase();
  if (!market || market === 'INDEX' || market === 'ETF' || market === 'UNKNOWN') return undefined;
  if (market === 'CN' || market === 'BSE') return 'cn';
  if (market === 'HK') return 'hk';
  if (market === 'US') return 'us';
  if (market === 'JP') return 'jp';
  if (market === 'KR') return 'kr';
  if (market === 'TW') return 'tw';
  if (MARKET_OPTIONS.includes(market.toLowerCase() as DecisionSignalMarket)) {
    return market.toLowerCase() as DecisionSignalMarket;
  }
  return undefined;
}

function getCandidateKey(candidate: Pick<StockCandidate, 'code' | 'market'>): string {
  const code = candidate.code.trim().toUpperCase();
  return candidate.market ? `${candidate.market}:${code}` : code;
}

function toHistoryCandidate(item: StockBarItem): StockCandidate | null {
  const code = String(item.stockCode || '').trim();
  if (!code || code.toUpperCase() === 'MARKET') return null;
  return {
    code,
    displayCode: code,
    name: item.stockName || undefined,
    market: normalizeDecisionSignalMarket(item.marketPhaseSummary?.market),
    source: 'history',
  };
}

function toPopularCandidates(index: StockIndexItem[], limit = STOCK_CANDIDATE_LIMIT): StockCandidate[] {
  const candidates: StockCandidate[] = [];
  const seen = new Set<string>();
  const sorted = [...index]
    .filter((item) => item.active && item.assetType === 'stock')
    .sort((left, right) => (right.popularity ?? 0) - (left.popularity ?? 0));

  for (const item of sorted) {
    const market = normalizeDecisionSignalMarket(item.market);
    const candidate: StockCandidate = {
      code: item.canonicalCode,
      displayCode: item.displayCode,
      name: item.nameZh,
      market,
      source: 'popular',
    };
    const key = getCandidateKey(candidate);
    if (seen.has(key)) continue;
    seen.add(key);
    candidates.push(candidate);
    if (candidates.length >= limit) break;
  }

  return candidates;
}

function toTimelineParams(filters: TimelineFilters, stockCode: string): DecisionSignalListParams {
  const days = TIMELINE_RANGE_DAYS[filters.range];
  const createdTo = new Date();
  const createdFrom = new Date(createdTo.getTime() - days * DAY_MS);
  return {
    market: filters.market || undefined,
    stockCode,
    createdFrom: createdFrom.toISOString(),
    createdTo: createdTo.toISOString(),
    status: filters.status === 'active' ? 'active' : undefined,
    decisionProfile: filters.decisionProfile || undefined,
    page: 1,
    pageSize: TIMELINE_PAGE_SIZE,
  };
}

function upsertDecisionSignal(
  current: DecisionSignalItem[],
  item: DecisionSignalItem,
  limit?: number,
): DecisionSignalItem[] {
  const next = [item, ...current.filter((candidate) => candidate.id !== item.id)];
  next.sort((left, right) => {
    const leftTime = parseDecisionSignalDate(left.createdAt)?.getTime() ?? Number.NEGATIVE_INFINITY;
    const rightTime = parseDecisionSignalDate(right.createdAt)?.getTime() ?? Number.NEGATIVE_INFINITY;
    return rightTime - leftTime || right.id - left.id;
  });
  return limit ? next.slice(0, limit) : next;
}

function itemMatchesStockContext(item: DecisionSignalItem, context: StockContext): boolean {
  return areStockCodesEquivalent(item.stockCode, context.code)
    && (!context.market || item.market === context.market);
}

function itemMatchesAppliedTimeline(
  item: DecisionSignalItem,
  context: AppliedTimelineContext,
  now = Date.now(),
): boolean {
  if (!areStockCodesEquivalent(item.stockCode, context.stockCode)) return false;
  if (context.market && item.market !== context.market) return false;
  if (context.status === 'active' && item.status !== 'active') return false;
  if (context.decisionProfile && getDecisionProfile(item) !== context.decisionProfile) return false;
  const createdAt = parseDecisionSignalDate(item.createdAt)?.getTime();
  if (createdAt === undefined) return false;
  return createdAt >= now - TIMELINE_RANGE_DAYS[context.range] * DAY_MS && createdAt <= now;
}

function isSameStockContext(
  previousContext: StockContext | null,
  nextContext: StockContext,
): boolean {
  return previousContext?.code.trim().toUpperCase() === nextContext.code.trim().toUpperCase()
    && previousContext?.market === nextContext.market;
}

function buildNextTimelineFilters(
  currentFilters: TimelineFilters,
  previousContext: StockContext | null,
  nextContext: StockContext,
  marketSource: TimelineMarketSource,
): TimelineFilterUpdate {
  if (isSameStockContext(previousContext, nextContext)) {
    return { filters: currentFilters, marketSource };
  }
  if (nextContext.market) {
    return {
      filters: { ...currentFilters, market: nextContext.market },
      marketSource: 'context',
    };
  }
  if (marketSource === 'context') {
    return {
      filters: { ...currentFilters, market: '' },
      marketSource: null,
    };
  }
  return { filters: currentFilters, marketSource };
}

function draftMatchesStockContext(draft: string, context: StockContext | null): context is StockContext {
  if (!context) return false;
  const normalizedDraft = draft.trim().toUpperCase();
  if (!normalizedDraft) return false;
  return normalizedDraft === context.code.trim().toUpperCase()
    || normalizedDraft === String(context.displayCode ?? '').trim().toUpperCase();
}

function formatStatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return Number(value).toFixed(2).replace(/\.?0+$/, '');
}

function formatStatPercent(value: number | null | undefined): string {
  const formatted = formatStatNumber(value);
  return formatted === '-' ? formatted : `${formatted}%`;
}

function mergeSignalPages(current: DecisionSignalItem[], next: DecisionSignalItem[]): DecisionSignalItem[] {
  const seen = new Set(current.map((item) => item.id));
  return [...current, ...next.filter((item) => !seen.has(item.id))];
}

const DecisionSignalsPage: React.FC = () => {
  const { language, t } = useUiLanguage();
  const actionLabels = useMemo(() => buildDecisionActionLabelMap(t), [t]);
  const { index: stockIndex } = useStockIndex();
  const signalsText = SIGNALS_TEXT[language];
  const [searchParams, setSearchParams] = useSearchParams();
  const searchKey = searchParams.toString();
  const urlFilters = useMemo(() => parseUrlFilters(searchKey), [searchKey]);
  const [baseFilters, setBaseFilters] = useState<BaseListFilters>(() => getInitialFilters());
  // Older backends omit stopTriggered; then stop=triggered falls back to held stocks in priority order.
  const [stopFieldMissing, setStopFieldMissing] = useState(false);
  const filters = useMemo<ListFilters>(() => ({
    ...baseFilters,
    ...urlFilters,
    holdingOnly: urlFilters.holdingOnly || (urlFilters.stopTriggered && stopFieldMissing),
  }), [baseFilters, stopFieldMissing, urlFilters]);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [extraItems, setExtraItems] = useState<DecisionSignalItem[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [quotes, setQuotes] = useState<Map<string, StockQuote>>(() => new Map());
  const [summary, setSummary] = useState<DecisionSignalSummaryResponse | null>(null);
  const [moreOpen, setMoreOpen] = useState(false);
  const [items, setItems] = useState<DecisionSignalItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [selected, setSelected] = useState<SelectedSignal | null>(null);
  const [pendingStatus, setPendingStatus] = useState<PendingStatusChange | null>(null);
  const [statusUpdating, setStatusUpdating] = useState(false);
  const [outcomeStats, setOutcomeStats] = useState<DecisionSignalOutcomeStatsResponse | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<ParsedApiError | null>(null);
  const [stockDraft, setStockDraft] = useState('');
  const [activeStockContext, setActiveStockContext] = useState<StockContext | null>(null);
  const [historyCandidates, setHistoryCandidates] = useState<StockCandidate[]>([]);
  const [historyCandidatesLoaded, setHistoryCandidatesLoaded] = useState(false);
  const [latestItems, setLatestItems] = useState<DecisionSignalItem[]>([]);
  const [latestSearched, setLatestSearched] = useState(false);
  const [latestLoading, setLatestLoading] = useState(false);
  const [latestError, setLatestError] = useState<ParsedApiError | null>(null);
  const [timelineFilters, setTimelineFilters] = useState<TimelineFilters>(DEFAULT_TIMELINE_FILTERS);
  const [appliedTimelineContext, setAppliedTimelineContext] = useState<AppliedTimelineContext | null>(null);
  const [timelineItems, setTimelineItems] = useState<DecisionSignalItem[]>([]);
  const [timelineSearched, setTimelineSearched] = useState(false);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineError, setTimelineError] = useState<ParsedApiError | null>(null);
  const [timelineTruncated, setTimelineTruncated] = useState(false);
  const [selectedOutcomes, setSelectedOutcomes] = useState<DecisionSignalOutcomeItem[]>([]);
  const [selectedOutcomesLoading, setSelectedOutcomesLoading] = useState(false);
  const [selectedOutcomesError, setSelectedOutcomesError] = useState<ParsedApiError | null>(null);
  const [selectedFeedback, setSelectedFeedback] = useState<DecisionSignalFeedbackItem | null>(null);
  const [selectedFeedbackLoading, setSelectedFeedbackLoading] = useState(false);
  const [selectedFeedbackError, setSelectedFeedbackError] = useState<ParsedApiError | null>(null);
  const [feedbackSaving, setFeedbackSaving] = useState(false);
  const [reassessProfile, setReassessProfile] = useState<DecisionProfile>('balanced');
  const [reassessResponse, setReassessResponse] = useState<DecisionSignalReassessResponse | null>(null);
  const [reassessLoading, setReassessLoading] = useState(false);
  const [reassessPersisting, setReassessPersisting] = useState(false);
  const [reassessPersistConfirm, setReassessPersistConfirm] = useState(false);
  const [reassessPersistBlocked, setReassessPersistBlocked] = useState<DecisionSignalReassessBlockedError | null>(null);
  const [reassessError, setReassessError] = useState<ParsedApiError | null>(null);
  const requestIdRef = useRef(0);
  const statsRequestIdRef = useRef(0);
  const latestRequestIdRef = useRef(0);
  const timelineRequestIdRef = useRef(0);
  const detailRequestIdRef = useRef(0);
  const reassessRequestIdRef = useRef(0);
  const selectedSignalIdRef = useRef<number | null>(null);
  const statusUpdateInFlightRef = useRef(false);
  const timelineMarketSourceRef = useRef<TimelineMarketSource>(null);
  const quoteRequestIdRef = useRef(0);
  const loadMoreRequestIdRef = useRef(0);
  const listStockCode = activeStockContext?.code ?? null;
  const listStockMarket = activeStockContext?.market;

  const popularCandidates = useMemo(
    () => toPopularCandidates(stockIndex, STOCK_CANDIDATE_LIMIT),
    [stockIndex],
  );
  const stockCandidates = historyCandidates.length > 0 ? historyCandidates : popularCandidates;
  const stockCandidateMode: 'history' | 'popular' | 'empty' = historyCandidates.length > 0
    ? 'history'
    : stockCandidates.length > 0
      ? 'popular'
      : 'empty';

  useEffect(() => {
    document.title = t('decisionSignals.pageTitle');
  }, [t]);

  useEffect(() => {
    let mounted = true;
    void historyApi.getStockBarList({ limit: STOCK_CANDIDATE_LIMIT })
      .then((response) => {
        if (!mounted) return;
        const nextCandidates: StockCandidate[] = [];
        const seen = new Set<string>();
        for (const item of response.items) {
          const candidate = toHistoryCandidate(item);
          if (!candidate) continue;
          const key = getCandidateKey(candidate);
          if (seen.has(key)) continue;
          seen.add(key);
          nextCandidates.push(candidate);
          if (nextCandidates.length >= STOCK_CANDIDATE_LIMIT) break;
        }
        setHistoryCandidates(nextCandidates);
      })
      .catch(() => {
        if (mounted) setHistoryCandidates([]);
      })
      .finally(() => {
        if (mounted) setHistoryCandidatesLoaded(true);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const loadSignalsForPage = useCallback(async (nextPage: number) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLoading(true);
    try {
      const response = await decisionSignalsApi.list(toListParams(
        filters,
        listStockCode ? { code: listStockCode, market: listStockMarket } : null,
        nextPage,
      ));
      if (requestIdRef.current !== requestId) return;
      const lastPage = Math.max(1, Math.ceil(response.total / PAGE_SIZE));
      if (response.total > 0 && nextPage > lastPage) {
        setPage(lastPage);
        return;
      }
      loadMoreRequestIdRef.current += 1;
      setExtraItems([]);
      setLoadingMore(false);
      if (
        filters.stopTriggered
        && response.items.length > 0
        && response.items.every((item) => item.stopTriggered === undefined)
      ) {
        setStopFieldMissing(true);
      }
      setItems(response.items);
      setTotal(response.total);
      setError(null);
      setSelected((current) => {
        if (!current) return current;
        if (current.source !== 'list') return current;
        const refreshed = response.items.find((item) => item.id === current.item.id);
        return refreshed ? { source: 'list', item: refreshed } : null;
      });
    } catch (err) {
      if (requestIdRef.current !== requestId) return;
      setError(getParsedApiError(err));
      loadMoreRequestIdRef.current += 1;
      setExtraItems([]);
      setLoadingMore(false);
      setItems([]);
      setTotal(0);
      setSelected((current) => (current?.source === 'list' ? null : current));
    } finally {
      if (requestIdRef.current === requestId) {
        setLoading(false);
      }
    }
  }, [filters, listStockCode, listStockMarket]);

  const loadSignals = useCallback(async () => {
    await loadSignalsForPage(page);
  }, [loadSignalsForPage, page]);

  const loadOutcomeStats = useCallback(async () => {
    const requestId = statsRequestIdRef.current + 1;
    statsRequestIdRef.current = requestId;
    setStatsLoading(true);
    try {
      const response = await decisionSignalsApi.getOutcomeStats();
      if (statsRequestIdRef.current !== requestId) return;
      setOutcomeStats(response);
      setStatsError(null);
    } catch (err) {
      if (statsRequestIdRef.current !== requestId) return;
      setOutcomeStats(null);
      setStatsError(getParsedApiError(err));
    } finally {
      if (statsRequestIdRef.current === requestId) {
        setStatsLoading(false);
      }
    }
  }, []);

  // 摘要只是輔助資訊，失敗就不顯示，不擋清單。
  const loadSummary = useCallback(async () => {
    try {
      setSummary(await decisionSignalsApi.getSummary());
    } catch {
      setSummary(null);
    }
  }, []);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    void loadSignals();
    return () => {
      requestIdRef.current += 1;
    };
  }, [loadSignals]);

  useEffect(() => {
    void loadOutcomeStats();
    return () => {
      statsRequestIdRef.current += 1;
    };
  }, [loadOutcomeStats]);

  useEffect(() => () => {
    latestRequestIdRef.current += 1;
  }, []);

  useEffect(() => () => {
    timelineRequestIdRef.current += 1;
  }, []);

  useEffect(() => {
    selectedSignalIdRef.current = selected?.item.id ?? null;
    if (!selected) {
      detailRequestIdRef.current += 1;
      setSelectedOutcomes([]);
      setSelectedOutcomesError(null);
      setSelectedFeedback(null);
      setSelectedFeedbackError(null);
      setSelectedOutcomesLoading(false);
      setSelectedFeedbackLoading(false);
      return;
    }

    const requestId = detailRequestIdRef.current + 1;
    detailRequestIdRef.current = requestId;
    setSelectedOutcomesLoading(true);
    setSelectedFeedbackLoading(true);
    setSelectedOutcomesError(null);
    setSelectedFeedbackError(null);

    void decisionSignalsApi.getSignalOutcomes(selected.item.id)
      .then((response) => {
        if (detailRequestIdRef.current !== requestId) return;
        setSelectedOutcomes(response.items);
      })
      .catch((err) => {
        if (detailRequestIdRef.current !== requestId) return;
        setSelectedOutcomes([]);
        setSelectedOutcomesError(getParsedApiError(err));
      })
      .finally(() => {
        if (detailRequestIdRef.current === requestId) {
          setSelectedOutcomesLoading(false);
        }
      });

    void decisionSignalsApi.getFeedback(selected.item.id)
      .then((response) => {
        if (detailRequestIdRef.current !== requestId) return;
        setSelectedFeedback(response);
      })
      .catch((err) => {
        if (detailRequestIdRef.current !== requestId) return;
        setSelectedFeedback(null);
        setSelectedFeedbackError(getParsedApiError(err));
      })
      .finally(() => {
        if (detailRequestIdRef.current === requestId) {
          setSelectedFeedbackLoading(false);
        }
      });
  }, [selected]);

  const loadedItems = useMemo(() => mergeSignalPages(items, extraItems), [items, extraItems]);
  // stop=triggered 在前端過濾已載入的列（後端依優先序把已觸停損排最前）；欄位缺席時改由 holdingOnly 請求代替。
  const clientStopFilter = filters.stopTriggered && !stopFieldMissing;
  const tableItems = useMemo(
    () => (clientStopFilter ? loadedItems.filter((item) => item.stopTriggered === true) : loadedItems),
    [clientStopFilter, loadedItems],
  );
  const selectedStockCode = selected?.item.stockCode;
  // 現價一律來自批次行情（含抽屜裡不在清單上的訊號），訊號當時價只當對照，不拿來算距離。
  const quoteCodesKey = useMemo(() => {
    const codes = new Set(tableItems.map((item) => item.stockCode));
    if (selectedStockCode) codes.add(selectedStockCode);
    return Array.from(codes).sort().join(',');
  }, [tableItems, selectedStockCode]);

  useEffect(() => {
    if (!quoteCodesKey) return undefined;
    const requestId = quoteRequestIdRef.current + 1;
    quoteRequestIdRef.current = requestId;
    void stocksApi.getQuotesBatched(quoteCodesKey.split(','))
      .then((rows) => {
        if (quoteRequestIdRef.current !== requestId) return;
        const next = new Map<string, StockQuote>();
        for (const row of rows) {
          if (row.quote) next.set(stockCodeMatchKey(row.stockCode), row.quote);
        }
        setQuotes(next);
      })
      .catch(() => {
        // 行情拿不到時現價顯示 —，清單照常可用。
        if (quoteRequestIdRef.current === requestId) setQuotes(new Map());
      });
    return () => {
      quoteRequestIdRef.current += 1;
    };
  }, [quoteCodesKey]);

  const quoteFor = useCallback(
    (stockCode: string) => quotes.get(stockCodeMatchKey(stockCode)),
    [quotes],
  );

  useEffect(() => {
    if (!selected) setMoreOpen(false);
  }, [selected]);

  const appliedSourceReportId = parseSourceReportId(filters.sourceReportId);
  const selectedSourceReportId = selected?.item.sourceReportId ?? undefined;
  const reassessSourceReportId = selected ? selectedSourceReportId : appliedSourceReportId;
  const reassessContextKey = [
    reassessSourceReportId ?? '',
    reassessProfile,
  ].join(':');

  useEffect(() => {
    reassessRequestIdRef.current += 1;
    setReassessResponse(null);
    setReassessError(null);
    setReassessLoading(false);
    setReassessPersisting(false);
    setReassessPersistConfirm(false);
    setReassessPersistBlocked(null);
  }, [reassessContextKey]);

  const handleReassess = useCallback(async () => {
    if (!reassessSourceReportId) return;
    const requestId = reassessRequestIdRef.current + 1;
    reassessRequestIdRef.current = requestId;
    setReassessLoading(true);
    setReassessError(null);
    setReassessPersistBlocked(null);
    try {
      const response = await decisionSignalsApi.reassess({
        sourceReportId: reassessSourceReportId,
        decisionProfile: reassessProfile,
        persist: false,
      });
      if (reassessRequestIdRef.current !== requestId) return;
      setReassessResponse(response);
    } catch (err) {
      if (reassessRequestIdRef.current !== requestId) return;
      setReassessResponse(null);
      setReassessError(getParsedApiError(err));
    } finally {
      if (reassessRequestIdRef.current === requestId) {
        setReassessLoading(false);
      }
    }
  }, [reassessProfile, reassessSourceReportId]);

  // 篩選改動即查；動作、持股、停損三項寫回網址（replace，不多一筆歷史）。
  const updateFilters = (patch: Partial<ListFilters>) => {
    const { action, holdingOnly, stopTriggered, ...base } = patch;
    if (Object.keys(base).length > 0) setBaseFilters((current) => ({ ...current, ...base }));
    if (action !== undefined || holdingOnly !== undefined || stopTriggered !== undefined) {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        if (action !== undefined) {
          if (action) next.set('action', action);
          else next.delete('action');
        }
        if (holdingOnly !== undefined) {
          if (holdingOnly) next.set('holding', '1');
          else next.delete('holding');
        }
        if (stopTriggered !== undefined) {
          if (stopTriggered) next.set('stop', 'triggered');
          else next.delete('stop');
        }
        return next;
      }, { replace: true });
    }
    setPage(1);
  };

  const handleLoadMore = async () => {
    const nextPage = page + 1 + Math.ceil(extraItems.length / PAGE_SIZE);
    const requestId = loadMoreRequestIdRef.current + 1;
    loadMoreRequestIdRef.current = requestId;
    setLoadingMore(true);
    try {
      const response = await decisionSignalsApi.list(toListParams(
        filters,
        listStockCode ? { code: listStockCode, market: listStockMarket } : null,
        nextPage,
      ));
      if (loadMoreRequestIdRef.current !== requestId) return;
      setExtraItems((current) => [...current, ...response.items]);
    } catch (err) {
      if (loadMoreRequestIdRef.current === requestId) setError(getParsedApiError(err));
    } finally {
      if (loadMoreRequestIdRef.current === requestId) setLoadingMore(false);
    }
  };

  const resetLatestView = useCallback(() => {
    latestRequestIdRef.current += 1;
    setLatestItems([]);
    setLatestSearched(false);
    setLatestLoading(false);
    setLatestError(null);
    setSelected((current) => (current?.source === 'latest' ? null : current));
  }, []);

  const loadLatestForContext = useCallback(async (context: StockContext) => {
    const stockCode = context.code.trim();
    if (!stockCode) return;
    const requestId = latestRequestIdRef.current + 1;
    latestRequestIdRef.current = requestId;
    setLatestLoading(true);
    setLatestError(null);
    setLatestSearched(true);
    setLatestItems([]);
    setSelected((current) => (current?.source === 'latest' ? null : current));
    try {
      const response = await decisionSignalsApi.getLatest(stockCode, {
        market: context.market,
        limit: 5,
      });
      if (latestRequestIdRef.current !== requestId) return;
      setLatestItems(response.items);
      setSelected((current) => refreshLatestSelection(current, response.items));
    } catch (err) {
      if (latestRequestIdRef.current !== requestId) return;
      setLatestItems([]);
      setSelected((current) => refreshLatestSelection(current, []));
      setLatestError(getParsedApiError(err));
    } finally {
      if (latestRequestIdRef.current === requestId) {
        setLatestLoading(false);
      }
    }
  }, []);

  const resetTimelineView = useCallback(() => {
    timelineRequestIdRef.current += 1;
    setTimelineItems([]);
    setTimelineSearched(false);
    setTimelineLoading(false);
    setTimelineError(null);
    setTimelineTruncated(false);
    setAppliedTimelineContext(null);
    setSelected((current) => (current?.source === 'timeline' ? null : current));
  }, []);

  const loadTimelineForContext = useCallback(async (
    context: StockContext,
    filtersSnapshot: TimelineFilters,
  ) => {
    const stockCode = context.code.trim();
    if (!stockCode) return;
    const requestId = timelineRequestIdRef.current + 1;
    timelineRequestIdRef.current = requestId;
    setTimelineLoading(true);
    setTimelineError(null);
    setTimelineSearched(true);
    setTimelineItems([]);
    setTimelineTruncated(false);
    setAppliedTimelineContext(null);
    setSelected((current) => (current?.source === 'timeline' ? null : current));
    const nextAppliedContext: AppliedTimelineContext = {
      ...filtersSnapshot,
      stockCode,
    };
    try {
      const response = await decisionSignalsApi.list(toTimelineParams(filtersSnapshot, stockCode));
      if (timelineRequestIdRef.current !== requestId) return;
      setAppliedTimelineContext(nextAppliedContext);
      setTimelineItems(response.items);
      setTimelineTruncated(response.total > response.items.length);
      setSelected((current) => refreshTimelineSelection(current, response.items));
    } catch (err) {
      if (timelineRequestIdRef.current !== requestId) return;
      setTimelineItems([]);
      setTimelineTruncated(false);
      setSelected((current) => refreshTimelineSelection(current, []));
      setTimelineError(getParsedApiError(err));
    } finally {
      if (timelineRequestIdRef.current === requestId) {
        setTimelineLoading(false);
      }
    }
  }, []);

  const handlePersistReassess = useCallback(async () => {
    const preview = reassessResponse?.preview;
    const guardrail = preview && isRecord(preview.metadata.guardrail_result)
      ? preview.metadata.guardrail_result
      : null;
    if (!reassessSourceReportId || !preview || guardrail?.passed !== true) return;

    const requestId = reassessRequestIdRef.current + 1;
    reassessRequestIdRef.current = requestId;
    setReassessPersistConfirm(false);
    setReassessPersisting(true);
    setReassessError(null);
    setReassessPersistBlocked(null);
    try {
      const response = await decisionSignalsApi.reassess({
        sourceReportId: reassessSourceReportId,
        decisionProfile: reassessProfile,
        persist: true,
      });
      if (reassessRequestIdRef.current !== requestId) return;
      if (!response.item || !response.persistStatus) {
        throw new Error('DecisionSignal reassess persist response item and persist_status are required');
      }
      const authoritativeItem = response.item;
      const shouldOptimisticallyUpsert = response.persistStatus !== 'existing';
      setReassessResponse(response);
      setSelected((current) => (
        current
          ? { source: 'persisted', item: authoritativeItem }
          : null
      ));
      if (
        shouldOptimisticallyUpsert
        &&
        activeStockContext
        && authoritativeItem.status === 'active'
        && itemMatchesStockContext(authoritativeItem, activeStockContext)
      ) {
        setLatestItems((current) => upsertDecisionSignal(current, authoritativeItem, 5));
        void loadLatestForContext(activeStockContext);
      }
      if (
        shouldOptimisticallyUpsert
        &&
        appliedTimelineContext
        && itemMatchesAppliedTimeline(authoritativeItem, appliedTimelineContext)
      ) {
        setTimelineItems((current) => upsertDecisionSignal(current, authoritativeItem));
        void loadTimelineForContext(
          {
            code: appliedTimelineContext.stockCode,
            market: appliedTimelineContext.market || undefined,
          },
          appliedTimelineContext,
        );
      }
      void loadSignalsForPage(page);
    } catch (err) {
      if (reassessRequestIdRef.current !== requestId) return;
      const blocked = getDecisionSignalReassessBlockedError(err);
      if (blocked) {
        setReassessPersistBlocked(blocked);
        setReassessError(null);
      } else {
        setReassessError(getParsedApiError(err));
      }
    } finally {
      if (reassessRequestIdRef.current === requestId) {
        setReassessPersisting(false);
      }
    }
  }, [
    activeStockContext,
    appliedTimelineContext,
    loadLatestForContext,
    loadSignalsForPage,
    loadTimelineForContext,
    page,
    reassessProfile,
    reassessResponse,
    reassessSourceReportId,
  ]);

  const applyStockContext = useCallback((nextContext: StockContext) => {
    const nextTimeline = buildNextTimelineFilters(
      timelineFilters,
      activeStockContext,
      nextContext,
      timelineMarketSourceRef.current,
    );
    timelineMarketSourceRef.current = nextTimeline.marketSource;
    if (!isSameStockContext(activeStockContext, nextContext)) setPage(1);
    setActiveStockContext(nextContext);
    setStockDraft(nextContext.displayCode ?? nextContext.code);
    setTimelineFilters(nextTimeline.filters);
    void loadLatestForContext(nextContext);
    void loadTimelineForContext(nextContext, nextTimeline.filters);
  }, [activeStockContext, loadLatestForContext, loadTimelineForContext, timelineFilters]);

  const handleStockSubmit = useCallback((
    code: string,
    name?: string,
    _source?: 'manual' | 'autocomplete',
    metadata?: { market?: Market; displayCode?: string },
  ) => {
    const trimmedCode = code.trim();
    if (!trimmedCode) return;
    applyStockContext({
      code: trimmedCode,
      displayCode: metadata?.displayCode,
      name,
      market: normalizeDecisionSignalMarket(metadata?.market),
    });
  }, [applyStockContext]);

  const handleCandidateSelect = useCallback((candidate: StockCandidate) => {
    applyStockContext(candidate);
  }, [applyStockContext]);

  const handleStockFormSubmit = useCallback((code: string) => {
    if (draftMatchesStockContext(code, activeStockContext)) {
      applyStockContext(activeStockContext);
      return;
    }
    handleStockSubmit(code);
  }, [activeStockContext, applyStockContext, handleStockSubmit]);

  const handleClearStockContext = useCallback(() => {
    setStockDraft('');
    setActiveStockContext(null);
    setPage(1);
    timelineMarketSourceRef.current = null;
    setTimelineFilters((current) => ({ ...current, market: '' }));
    resetLatestView();
    resetTimelineView();
  }, [resetLatestView, resetTimelineView]);

  const handleTimelineSearch = useCallback((event: React.FormEvent) => {
    event.preventDefault();
    if (!activeStockContext) return;
    void loadTimelineForContext(activeStockContext, timelineFilters);
  }, [activeStockContext, loadTimelineForContext, timelineFilters]);

  const handleStatusUpdate = async () => {
    if (!pendingStatus || statusUpdateInFlightRef.current) return;
    statusUpdateInFlightRef.current = true;
    setStatusUpdating(true);
    try {
      const updated = await decisionSignalsApi.updateStatus(pendingStatus.item.id, {
        status: pendingStatus.status,
      });
      setPendingStatus(null);
      setLatestItems((current) => current.flatMap((item) => {
        if (item.id !== updated.id) return [item];
        return updated.status === 'active' ? [updated] : [];
      }));
      setTimelineItems((current) => current.flatMap((item) => {
        if (item.id !== updated.id) return [item];
        return appliedTimelineContext?.status === 'active' && updated.status !== 'active' ? [] : [updated];
      }));
      setSelected((current) => {
        if (!current || current.item.id !== updated.id) return current;
        if (current.source === 'latest') {
          return updated.status === 'active' ? { source: 'latest', item: updated } : null;
        }
        if (current.source === 'timeline') {
          return appliedTimelineContext?.status === 'active' && updated.status !== 'active'
            ? null
            : { source: 'timeline', item: updated };
        }
        if (current.source === 'persisted') {
          return { source: 'persisted', item: updated };
        }
        if (!parseSourceReportId(filters.sourceReportId) && filters.status && updated.status !== filters.status) return null;
        return { source: 'list', item: updated };
      });
      setError(null);
      await loadSignalsForPage(page);
      await loadOutcomeStats();
      void loadSummary();
    } catch (err) {
      setError(getParsedApiError(err));
      setPendingStatus(null);
    } finally {
      setStatusUpdating(false);
      statusUpdateInFlightRef.current = false;
    }
  };

  const handleFeedbackSubmit = useCallback(async (feedbackValue: DecisionSignalFeedbackValue) => {
    if (!selected || feedbackSaving) return;
    const signalId = selected.item.id;
    setFeedbackSaving(true);
    try {
      const updated = await decisionSignalsApi.putFeedback(signalId, {
        feedbackValue,
        source: 'web',
      });
      if (selectedSignalIdRef.current !== signalId) return;
      setSelectedFeedback(updated);
      setSelectedFeedbackError(null);
    } catch (err) {
      if (selectedSignalIdRef.current !== signalId) return;
      setSelectedFeedbackError(getParsedApiError(err));
    } finally {
      setFeedbackSaving(false);
    }
  }, [feedbackSaving, selected]);

  const renderReassessPanel = () => {
    const preview = reassessResponse?.preview ?? null;
    const persistedItem = reassessResponse?.item ?? null;
    const persistStatus = reassessResponse?.persistStatus ?? null;
    const terminalExisting = persistStatus === 'existing' && persistedItem?.status !== 'active';
    const persistedAlertVariant = terminalExisting
      ? 'warning'
      : persistStatus === 'existing'
        ? 'info'
        : 'success';
    const persistedTitleKey: UiTextKey = terminalExisting
      ? 'decisionSignals.reassessPersistedTerminalTitle'
      : persistStatus === 'existing'
        ? 'decisionSignals.reassessPersistedExistingTitle'
        : persistStatus === 'refreshed'
          ? 'decisionSignals.reassessPersistedRefreshedTitle'
          : 'decisionSignals.reassessPersistedCreatedTitle';
    const persistedMessageKey: UiTextKey = terminalExisting
      ? 'decisionSignals.reassessPersistedTerminalExisting'
      : persistStatus === 'existing'
        ? 'decisionSignals.reassessPersistedExisting'
        : persistStatus === 'refreshed'
          ? 'decisionSignals.reassessPersistedRefreshed'
          : 'decisionSignals.reassessPersistedCreated';
    const metadata = preview?.metadata ?? {};
    const guardrail = isRecord(metadata.guardrail_result) ? metadata.guardrail_result : null;
    const rawAction = typeof guardrail?.raw_action === 'string' ? guardrail.raw_action : null;
    const finalAction = typeof guardrail?.final_action === 'string' ? guardrail.final_action : null;
    const passed = typeof guardrail?.passed === 'boolean' ? guardrail.passed : null;
    // 風控回傳的是 action 枚舉：依詞彙表顯示；未知值保留原文，不猜語意。
    const actionNameOf = (value: string | null): string => (
      value ? (actionLabels[value as DecisionAction] ?? value) : '-'
    );
    return (
      <div className="rounded-xl border border-border/60 bg-elevated/30 p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-semibold text-foreground">{t('decisionSignals.reassessTitle')}</h3>
            </div>
            <p className="mt-1 text-xs text-secondary-text">
              {reassessSourceReportId
                ? t('decisionSignals.reassessSource', { id: reassessSourceReportId })
                : t('decisionSignals.reassessUnsupported')}
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <select
              className="input-surface input-focus-glow h-10 rounded-xl border bg-transparent px-3 text-sm"
              value={reassessProfile}
              onChange={(event) => setReassessProfile(event.target.value as DecisionProfile)}
              aria-label={t('decisionSignals.reassessProfile')}
              disabled={!reassessSourceReportId || reassessLoading || reassessPersisting}
            >
              {REASSESS_PROFILES.map((profile) => (
                <option key={profile} value={profile}>
                  {t(`decisionSignals.profile.${profile}` as UiTextKey)}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn-secondary inline-flex h-10 items-center justify-center gap-2"
              onClick={() => void handleReassess()}
              disabled={!reassessSourceReportId || reassessLoading || reassessPersisting}
            >
              <RefreshCw className={cn('h-4 w-4', reassessLoading ? 'animate-spin' : '')} />
              {t('decisionSignals.reassessPreview')}
            </button>
          </div>
        </div>

        {!reassessSourceReportId ? (
          <InlineAlert
            className="mt-3"
            variant="warning"
            title={t('decisionSignals.reassessUnsupportedTitle')}
            message={t('decisionSignals.reassessUnsupported')}
          />
        ) : null}
        {reassessError ? <ApiErrorAlert className="mt-3" error={reassessError} /> : null}
        {reassessPersistBlocked ? (
          <div className="mt-3 space-y-2">
            <InlineAlert
              variant="danger"
              title={t('decisionSignals.reassessPersistBlockedTitle')}
              message={reassessPersistBlocked.blockedReason}
            />
            {reassessPersistBlocked.warnings.length ? (
              <ul className="list-disc space-y-1 pl-5 text-sm text-secondary-text">
                {reassessPersistBlocked.warnings.map((warning, index) => (
                  <li key={`${warning.code}-${index}`}>{warning.message || warning.code}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
        {persistedItem ? (
          <InlineAlert
            className="mt-3"
            variant={persistedAlertVariant}
            title={t(persistedTitleKey)}
            message={t(
              persistedMessageKey,
              {
                id: persistedItem.id,
                status: t(STATUS_LABEL_KEYS[persistedItem.status]),
              },
            )}
          />
        ) : null}
        {preview ? (
          <div className="mt-4 space-y-3">
            {reassessResponse?.blockedReason ? (
              <InlineAlert
                variant="warning"
                title={t('decisionSignals.reassessBlockedTitle')}
                message={reassessResponse.blockedReason}
              />
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.action')}</p>
                <p className="mt-1 text-sm font-semibold text-foreground">{actionLabels[preview.action]}</p>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.score')}</p>
                <p className="mt-1 text-sm font-semibold text-foreground">{preview.score ?? '-'}</p>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.confidence')}</p>
                <p className="mt-1 text-sm font-semibold text-foreground">{preview.confidence ?? '-'}</p>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.horizon')}</p>
                <p className="mt-1 text-sm font-semibold text-foreground">{preview.horizon ?? '-'}</p>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.entryRange')}</p>
                <p className="mt-1 text-sm text-foreground">
                  {preview.entryLow || preview.entryHigh
                    ? `${preview.entryLow ?? '-'} ~ ${preview.entryHigh ?? '-'}`
                    : '-'}
                </p>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.stopLoss')}</p>
                <p className="mt-1 text-sm text-foreground">{preview.stopLoss ?? '-'}</p>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.targetPrice')}</p>
                <p className="mt-1 text-sm text-foreground">{preview.targetPrice ?? '-'}</p>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.reassessRawFinal')}</p>
                <p className="mt-1 text-sm text-foreground">{actionNameOf(rawAction)} → {actionNameOf(finalAction)}</p>
              </div>
            </div>
            <div className="space-y-2 text-sm text-secondary-text">
              {passed === false ? (
                <p className="font-medium text-warning">{t('decisionSignals.reassessBlockedNote')}</p>
              ) : null}
              {preview.invalidation ? <p><span className="text-foreground">{t('decisionSignals.invalidation')}:</span> {preview.invalidation}</p> : null}
              {preview.reason ? <p><span className="text-foreground">{t('decisionSignals.reason')}:</span> {preview.reason}</p> : null}
              {formatSignalText(preview.riskSummary) ? <p><span className="text-foreground">{t('decisionSignals.riskSummary')}:</span> {formatSignalText(preview.riskSummary)}</p> : null}
              {formatSignalText(preview.watchConditions) ? <p><span className="text-foreground">{t('decisionSignals.watchConditions')}:</span> {formatSignalText(preview.watchConditions)}</p> : null}
            </div>
            {reassessResponse?.warnings.length ? (
              <div className="rounded-lg border border-warning/30 bg-warning/10 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-warning">{t('decisionSignals.reassessWarnings')}</p>
                <ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-secondary-text">
                  {reassessResponse.warnings.map((warning, index) => (
                    <li key={`${warning.code}-${index}`}>{warning.message || warning.code}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {passed === true ? (
              <div className="flex justify-end">
                <button
                  type="button"
                  className="btn-primary inline-flex h-10 items-center justify-center gap-2"
                  onClick={() => setReassessPersistConfirm(true)}
                  disabled={reassessLoading || reassessPersisting}
                >
                  <ShieldCheck className="h-4 w-4" />
                  {reassessPersisting
                    ? t('decisionSignals.reassessPersisting')
                    : t('decisionSignals.reassessPersist')}
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
        {persistedItem && reassessResponse?.warnings.length ? (
          <div className="mt-3 rounded-lg border border-warning/30 bg-warning/10 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-warning">{t('decisionSignals.reassessWarnings')}</p>
            <ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-secondary-text">
              {reassessResponse.warnings.map((warning, index) => (
                <li key={`${warning.code}-${index}`}>{warning.message || warning.code}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    );
  };

  const activeStockLabel = activeStockContext
    ? [
      activeStockContext.displayCode ?? activeStockContext.code,
      activeStockContext.name,
      activeStockContext.market,
    ].filter(Boolean).join(' / ')
    : null;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const hasMorePages = page + Math.ceil(extraItems.length / PAGE_SIZE) < totalPages;
  const activeFilterCount = [filters.market, filters.action, filters.marketPhase, filters.sourceType]
    .filter(Boolean).length + (filters.status === DEFAULT_LIST_FILTERS.status ? 0 : 1);
  const summaryActions = summary
    ? ACTION_OPTIONS.flatMap((action) => {
      const count = summary.actions[action] ?? 0;
      return count > 0 ? [{ action, count }] : [];
    })
    : [];
  const statsDecidable = outcomeStats ? outcomeStats.hit + outcomeStats.miss : 0;
  const filteredCount = clientStopFilter ? tableItems.length : total;
  // Client-side stop filter only sees loaded rows, so backend pages don't apply. The backend sorts
  // stop-hit rows first, so more may exist only while every loaded row is still a stop hit.
  const showPagination = !clientStopFilter && totalPages > 1;
  const showLoadMore = clientStopFilter
    ? hasMorePages && loadedItems.length > 0 && tableItems.length === loadedItems.length
    : hasMorePages && tableItems.length > 0;
  const hasUrlFilters = urlFilters.holdingOnly || Boolean(urlFilters.action) || urlFilters.stopTriggered;
  // When the backend lacks stopTriggered, stop=triggered falls back to a holdings query, so use the generic filtered copy.
  const emptyTitle = clientStopFilter
    ? signalsText.emptyStopTriggered
    : hasUrlFilters
      ? signalsText.emptyFiltered
      : t('decisionSignals.emptyTitle');
  const filterHeadline = appliedSourceReportId || loading
    ? undefined
    : urlFilters.stopTriggered && !stopFieldMissing
      ? formatUiText(signalsText.headerStopTriggered, { count: filteredCount })
      : urlFilters.stopTriggered
        ? formatUiText(signalsText.headerHolding, { count: filteredCount })
      : urlFilters.holdingOnly && urlFilters.action
        ? formatUiText(signalsText.headerHoldingAction, { action: actionLabels[urlFilters.action], count: filteredCount })
        : urlFilters.holdingOnly
          ? formatUiText(signalsText.headerHolding, { count: filteredCount })
          : undefined;
  const urlFilterChips: Array<{ key: string; label: string; onRemove: () => void }> = [
    ...(urlFilters.holdingOnly
      ? [{ key: 'holding', label: signalsText.holdingChip, onRemove: () => updateFilters({ holdingOnly: false }) }]
      : []),
    ...(urlFilters.action
      ? [{ key: 'action', label: actionLabels[urlFilters.action], onRemove: () => updateFilters({ action: '' }) }]
      : []),
    ...(urlFilters.stopTriggered
      ? [{ key: 'stop', label: signalsText.stopTriggeredChip, onRemove: () => updateFilters({ stopTriggered: false }) }]
      : []),
  ];

  return (
    <AppPage>
      <div className="space-y-4">
        <PageHeader
          title={t('decisionSignals.title')}
          description={filterHeadline}
          actions={(
            <button
              type="button"
              className="btn-secondary inline-flex items-center gap-2"
              onClick={() => {
                void loadSignals();
                void loadOutcomeStats();
                void loadSummary();
              }}
              disabled={loading}
            >
              <RefreshCw className={cn('h-4 w-4', loading ? 'animate-spin' : '')} />
              {t('decisionSignals.refresh')}
            </button>
          )}
        />

        {summary && summary.total > 0 ? (
          <div
            data-testid="signal-action-summary"
            role="group"
            aria-label={t('decisionSignals.actionSummaryLabel')}
            className="flex flex-wrap items-center gap-2 text-sm"
          >
            <span className="text-secondary-text">{t('decisionSignals.summaryStocks', { count: summary.total })}</span>
            {summary.heldCount > 0 ? (
              <span className="text-secondary-text">{t('decisionSignals.summaryHeld', { count: summary.heldCount })}</span>
            ) : null}
            {summary.stopTriggeredCount > 0 ? (
              <span className="rounded-md bg-warning px-2 py-0.5 text-xs font-semibold text-slate-950">
                {t('decisionSignals.summaryStopTriggered', { count: summary.stopTriggeredCount })}
              </span>
            ) : null}
            {summaryActions.map(({ action, count }) => (
              <button
                key={action}
                type="button"
                aria-pressed={filters.action === action}
                onClick={() => updateFilters({ action: filters.action === action ? '' : action })}
                className={cn(
                  'inline-flex h-8 cursor-pointer items-center gap-1 rounded-full border px-3 text-xs transition-colors',
                  filters.action === action
                    ? 'border-cyan/60 bg-cyan/10 text-foreground'
                    : 'border-border/70 text-secondary-text hover:text-foreground',
                )}
              >
                {actionLabels[action]} <span className="tabular-nums">{count}</span>
              </button>
            ))}
            {summary.stopPriceUnavailableCount > 0 ? (
              <span className="text-xs text-muted-text">
                {t('decisionSignals.summaryStopUnavailable', { count: summary.stopPriceUnavailableCount })}
              </span>
            ) : null}
          </div>
        ) : null}

        <div className="space-y-2">
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              handleStockFormSubmit(stockDraft);
            }}
          >
            <div className="relative min-w-0 flex-[1_1_16rem]">
              <StockAutocomplete
                value={stockDraft}
                onChange={setStockDraft}
                onSubmit={handleStockSubmit}
                placeholder={signalsText.stockPlaceholder}
                ariaLabel={t('decisionSignals.stockContextInput')}
                className="pr-9"
              />
              {activeStockContext || stockDraft ? (
                <button
                  type="button"
                  aria-label={t('decisionSignals.stockContextClear')}
                  className="absolute right-2 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full text-muted-text transition-colors hover:bg-elevated hover:text-foreground"
                  onClick={handleClearStockContext}
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              ) : null}
            </div>
            <button
              type="submit"
              className="btn-primary inline-flex h-11 items-center justify-center gap-2"
              disabled={!stockDraft.trim()}
            >
              <Search className="h-4 w-4" />
              {t('decisionSignals.stockContextApply')}
            </button>
            <button
              type="button"
              aria-expanded={filtersOpen}
              className="btn-secondary inline-flex h-11 items-center justify-center gap-2"
              onClick={() => setFiltersOpen((current) => !current)}
            >
              <SlidersHorizontal className="h-4 w-4" />
              {t('decisionSignals.filter')}
              {activeFilterCount > 0 ? <span className="tabular-nums text-cyan">{activeFilterCount}</span> : null}
            </button>
          </form>

          {urlFilterChips.length > 0 ? (
            <div data-testid="signal-url-filters" className="flex flex-wrap items-center gap-2">
              {urlFilterChips.map((chip) => (
                <button
                  key={chip.key}
                  type="button"
                  aria-label={formatUiText(signalsText.removeFilter, { label: chip.label })}
                  onClick={chip.onRemove}
                  className="inline-flex h-8 cursor-pointer items-center gap-1 rounded-full border border-cyan/60 bg-cyan/10 px-3 text-xs text-foreground transition-colors hover:border-cyan"
                >
                  {chip.label}
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              ))}
            </div>
          ) : null}

          {historyCandidatesLoaded && stockCandidates.length > 0 ? (
            <div className="flex items-center gap-2 overflow-x-auto pb-1 pr-6 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden [mask-image:linear-gradient(to_right,black_calc(100%-24px),transparent)] [-webkit-mask-image:linear-gradient(to_right,black_calc(100%-24px),transparent)]">
              <span className="shrink-0 text-xs text-muted-text">
                {stockCandidateMode === 'history'
                  ? t('decisionSignals.stockContextRecent')
                  : t('decisionSignals.stockContextPopular')}
              </span>
              {stockCandidates.slice(0, STOCK_CANDIDATE_LIMIT).map((candidate) => (
                <button
                  key={`${candidate.source}:${getCandidateKey(candidate)}`}
                  type="button"
                  className="inline-flex h-8 shrink-0 cursor-pointer items-center rounded-full border border-border/70 bg-elevated/40 px-3 text-xs text-foreground transition-colors hover:border-primary/60 hover:text-primary"
                  onClick={() => handleCandidateSelect(candidate)}
                >
                  <span className="font-mono">{candidate.displayCode ?? candidate.code}</span>
                  {candidate.name ? <span className="ml-1 max-w-[6rem] truncate text-secondary-text">{candidate.name}</span> : null}
                  {candidate.market ? (
                    <span className="ml-1 text-muted-text">{getDecisionSignalMarketLabel(candidate.market, t)}</span>
                  ) : null}
                </button>
              ))}
            </div>
          ) : historyCandidatesLoaded ? (
            <p className="text-xs text-secondary-text">{t('decisionSignals.stockContextNoCandidates')}</p>
          ) : null}

          {activeStockLabel ? (
            <p className="text-sm text-secondary-text">
              {t('decisionSignals.stockContextCurrent', { stock: activeStockLabel })}
            </p>
          ) : null}

          {filtersOpen ? (
            <div data-testid="signal-filter-panel" className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
              <select
                className="input-surface input-focus-glow h-10 rounded-xl border bg-transparent px-3 text-sm"
                value={filters.market}
                onChange={(event) => updateFilters({ market: event.target.value as ListFilters['market'] })}
                aria-label={t('decisionSignals.market')}
              >
                <option value="">{t('decisionSignals.allMarkets')}</option>
                {MARKET_OPTIONS.map((market) => (
                  <option key={market} value={market}>{getDecisionSignalMarketLabel(market, t)}</option>
                ))}
              </select>
              <select
                className="input-surface input-focus-glow h-10 rounded-xl border bg-transparent px-3 text-sm"
                value={filters.action}
                onChange={(event) => updateFilters({ action: event.target.value as ListFilters['action'] })}
                aria-label={t('decisionSignals.action')}
              >
                <option value="">{t('decisionSignals.allActions')}</option>
                {ACTION_OPTIONS.map((action) => (
                  <option key={action} value={action}>{actionLabels[action]}</option>
                ))}
              </select>
              <select
                className="input-surface input-focus-glow h-10 rounded-xl border bg-transparent px-3 text-sm"
                value={filters.marketPhase}
                onChange={(event) => updateFilters({ marketPhase: event.target.value as ListFilters['marketPhase'] })}
                aria-label={t('decisionSignals.marketPhase')}
              >
                <option value="">{t('decisionSignals.allPhases')}</option>
                {PHASE_OPTIONS.map((phase) => (
                  <option key={phase} value={phase}>{getDecisionSignalMarketPhaseLabel(phase, t)}</option>
                ))}
              </select>
              <select
                className="input-surface input-focus-glow h-10 rounded-xl border bg-transparent px-3 text-sm"
                value={filters.sourceType}
                onChange={(event) => updateFilters({ sourceType: event.target.value as ListFilters['sourceType'] })}
                aria-label={t('decisionSignals.source')}
              >
                <option value="">{t('decisionSignals.allSources')}</option>
                {SOURCE_OPTIONS.map((source) => (
                  <option key={source} value={source}>{getDecisionSignalSourceTypeLabel(source, t)}</option>
                ))}
              </select>
              <select
                className="input-surface input-focus-glow h-10 rounded-xl border bg-transparent px-3 text-sm"
                value={filters.status}
                onChange={(event) => updateFilters({ status: event.target.value as ListFilters['status'] })}
                aria-label={t('decisionSignals.status')}
              >
                <option value="">{t('decisionSignals.allStatuses')}</option>
                {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{t(STATUS_LABEL_KEYS[status])}</option>)}
              </select>
            </div>
          ) : null}
        </div>

        {!selected && appliedSourceReportId ? (
          <Card padding="md">
            {renderReassessPanel()}
          </Card>
        ) : null}

        {error ? (
          <ApiErrorAlert
            error={{ ...error, title: t('decisionSignals.errorTitle') }}
            actionLabel={t('common.retry')}
            onAction={() => void loadSignals()}
          />
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-secondary-text">{t('decisionSignals.total', { total: filteredCount })}</p>
          {loading && items.length > 0 ? <span className="text-xs text-secondary-text">{t('common.loading')}...</span> : null}
          {showPagination ? (
            <div data-testid="signal-pagination-top" className="hidden md:block">
              <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
            </div>
          ) : null}
        </div>

        {loading && tableItems.length === 0 ? (
          <DecisionSignalTableSkeleton />
        ) : tableItems.length === 0 ? (
          <EmptyState
            title={emptyTitle}
            description={hasUrlFilters ? undefined : t('decisionSignals.emptyDescription')}
            icon={<Activity className="h-7 w-7" />}
            action={hasUrlFilters ? (
              <Button
                variant="secondary"
                onClick={() => updateFilters({ holdingOnly: false, action: '', stopTriggered: false })}
              >
                {signalsText.clearFilters}
              </Button>
            ) : undefined}
          />
        ) : (
          <DecisionSignalTable
            items={tableItems}
            quoteFor={quoteFor}
            onSelect={(selectedItem) => setSelected({ source: 'list', item: selectedItem })}
            onShowOlder={(item) => applyStockContext({
              code: item.stockCode,
              displayCode: item.stockCode,
              name: item.stockName ?? undefined,
              market: item.market,
            })}
          />
        )}

        {!clientStopFilter ? (
          <div data-testid="signal-pagination-bottom" className="hidden md:block">
            <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
          </div>
        ) : null}
        {showLoadMore ? (
          <div className="md:hidden">
            <Button
              variant="secondary"
              className="w-full"
              isLoading={loadingMore}
              onClick={() => void handleLoadMore()}
            >
              {t('decisionSignals.loadMore')}
            </Button>
          </div>
        ) : null}

        {activeStockContext ? (
          <>
            <Card title={t('decisionSignals.latestTitle')} subtitle={t('decisionSignals.latestDescription')} padding="md">
              {latestError ? <ApiErrorAlert className="mt-3" error={latestError} /> : null}
              {latestSearched && !latestLoading && !latestError && latestItems.length === 0 ? (
                <EmptyState
                  className="mt-4 border-none bg-transparent py-6 shadow-none"
                  title={t('decisionSignals.noLatestTitle')}
                  description={t('decisionSignals.noLatestDescription')}
                  icon={<Activity className="h-6 w-6" />}
                />
              ) : null}
              {latestLoading ? <p className="mt-3 text-sm text-secondary-text">{t('common.loading')}...</p> : null}
              {latestItems.length > 0 ? (
                <div className="mt-4 grid gap-3 lg:grid-cols-2">
                  {latestItems.map((item) => (
                    <DecisionSignalCard
                      key={item.id}
                      item={item}
                      onSelect={(selectedItem) => setSelected({ source: 'latest', item: selectedItem })}
                      selected={selected?.item.id === item.id}
                    />
                  ))}
                </div>
              ) : null}
            </Card>

            <Card title={t('decisionSignals.timelineTitle')} subtitle={t('decisionSignals.timelineDescription')} padding="md">
              <form className="grid gap-3 md:grid-cols-5" onSubmit={handleTimelineSearch}>
                <select
                  className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
                  value={timelineFilters.market}
                  onChange={(event) => {
                    const market = event.target.value as TimelineFilters['market'];
                    timelineMarketSourceRef.current = market ? 'user' : null;
                    setTimelineFilters((current) => ({ ...current, market }));
                  }}
                  aria-label={t('decisionSignals.timelineMarket')}
                >
                  <option value="">{t('decisionSignals.allMarkets')}</option>
                  {MARKET_OPTIONS.map((market) => (
                    <option key={market} value={market}>{getDecisionSignalMarketLabel(market, t)}</option>
                  ))}
                </select>
                <select
                  className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
                  value={timelineFilters.range}
                  onChange={(event) => setTimelineFilters((current) => ({ ...current, range: event.target.value as TimelineRange }))}
                  aria-label={t('decisionSignals.timelineRange')}
                >
                  <option value="30d">{t('decisionSignals.timelineRange.30d')}</option>
                  <option value="90d">{t('decisionSignals.timelineRange.90d')}</option>
                  <option value="180d">{t('decisionSignals.timelineRange.180d')}</option>
                </select>
                <select
                  className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
                  value={timelineFilters.status}
                  onChange={(event) => setTimelineFilters((current) => ({ ...current, status: event.target.value as TimelineStatusFilter }))}
                  aria-label={t('decisionSignals.timelineStatus')}
                >
                  <option value="all">{t('decisionSignals.timelineStatus.all')}</option>
                  <option value="active">{t('decisionSignals.timelineStatus.active')}</option>
                </select>
                <select
                  className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
                  value={timelineFilters.decisionProfile}
                  onChange={(event) => setTimelineFilters((current) => ({
                    ...current,
                    decisionProfile: event.target.value as TimelineFilters['decisionProfile'],
                  }))}
                  aria-label={t('decisionSignals.timelineProfile')}
                >
                  <option value="">{t('decisionSignals.allProfiles')}</option>
                  {REASSESS_PROFILES.map((profile) => (
                    <option key={profile} value={profile}>
                      {t(`decisionSignals.profile.${profile}` as UiTextKey)}
                    </option>
                  ))}
                  <option value="unknown">{t('decisionSignals.profile.unknown')}</option>
                </select>
                <button
                  type="submit"
                  className="btn-secondary inline-flex h-11 items-center justify-center gap-2"
                  disabled={timelineLoading}
                >
                  <Search className="h-4 w-4" />
                  {t('decisionSignals.timelineSearch')}
                </button>
              </form>
              <div className="mt-4">
                {!timelineSearched ? (
                  <EmptyState
                    className="border-none bg-transparent py-6 shadow-none"
                    title={t('decisionSignals.timelineGuideTitle')}
                    description={t('decisionSignals.timelineGuideDescription')}
                    icon={<Activity className="h-6 w-6" />}
                  />
                ) : (
                  <DecisionSignalTimeline
                    items={timelineItems}
                    selectedId={selected?.item.id ?? null}
                    loading={timelineLoading}
                    error={timelineError?.message ?? null}
                    truncated={timelineTruncated}
                    onSelect={(selectedItem) => setSelected({ source: 'timeline', item: selectedItem })}
                  />
                )}
              </div>
            </Card>
          </>
        ) : null}

        <section data-testid="signal-stats" className="space-y-2">
          {outcomeStats && outcomeStats.total > 0 ? (
            <p data-testid="signal-stats-sentence" className="text-sm tabular-nums text-secondary-text">
              {formatUiText(signalsText.statsSentence, {
                rate: typeof outcomeStats.hitRatePct === 'number' ? `${formatNumber(outcomeStats.hitRatePct, 1)}%` : '—',
                hit: formatNumber(outcomeStats.hit),
                decidable: formatNumber(statsDecidable),
                total: formatNumber(outcomeStats.total),
                unable: formatNumber(outcomeStats.unable),
              })}
              {outcomeStats.neutral > 0 ? `・${t('decisionSignals.statsNeutral', { count: formatNumber(outcomeStats.neutral) })}` : ''}
            </p>
          ) : null}
          <Collapsible title={t('decisionSignals.statsTitle')}>
            <p className="mb-1 text-sm text-secondary-text">{t('decisionSignals.statsDescription')}</p>
            <p className="mb-3 text-sm text-secondary-text">{t('decisionSignals.statsGlobalScope')}</p>
            {statsError ? (
              <ApiErrorAlert
                error={{ ...statsError, title: t('decisionSignals.statsErrorTitle') }}
                actionLabel={t('common.retry')}
                onAction={() => void loadOutcomeStats()}
              />
            ) : statsLoading ? (
              <p className="text-sm text-secondary-text">{t('common.loading')}...</p>
            ) : outcomeStats && outcomeStats.total > 0 ? (
              <div>
                <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
                  {[
                    { label: t('decisionSignals.statsTotal'), value: String(outcomeStats.total) },
                    { label: t('decisionSignals.statsHitRate'), value: formatStatPercent(outcomeStats.hitRatePct) },
                    { label: t('decisionSignals.outcome.hit'), value: String(outcomeStats.hit) },
                    { label: t('decisionSignals.outcome.miss'), value: String(outcomeStats.miss) },
                    { label: t('decisionSignals.outcome.neutral'), value: String(outcomeStats.neutral) },
                    { label: t('decisionSignals.outcome.unable'), value: String(outcomeStats.unable) },
                  ].map((metric) => (
                    <div key={metric.label} className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-3">
                      <p className="text-xs text-secondary-text">{metric.label}</p>
                      {/* 統計不是行情也不是系統狀態，一律中性色。 */}
                      <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">{metric.value}</p>
                    </div>
                  ))}
                </div>
                {outcomeStats.profileCalibration ? (
                  <DecisionSignalProfileCalibration calibration={outcomeStats.profileCalibration} />
                ) : null}
              </div>
            ) : (
              <EmptyState
                className="border-none bg-transparent py-6 shadow-none"
                title={t('decisionSignals.noReviewedStatsTitle')}
                description={t('decisionSignals.noReviewedStatsDescription')}
                icon={<BarChart3 className="h-6 w-6" />}
              />
            )}
          </Collapsible>
        </section>
      </div>

      <Drawer
        isOpen={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={t('decisionSignals.detailTitle')}
        width="max-w-3xl"
      >
        {selected ? (
          <DecisionSignalDetails
            item={selected.item}
            quote={quoteFor(selected.item.stockCode)}
            outcomes={selectedOutcomes}
            outcomesLoading={selectedOutcomesLoading}
            outcomesError={selectedOutcomesError?.message ?? null}
            feedback={selectedFeedback}
            feedbackLoading={selectedFeedbackLoading}
            feedbackSaving={feedbackSaving}
            feedbackError={selectedFeedbackError?.message ?? null}
            onFeedbackSubmit={handleFeedbackSubmit}
            actions={(
              <IconButton
                aria-label={t('decisionSignals.moreActions')}
                aria-expanded={moreOpen}
                variant="secondary"
                icon={<MoreHorizontal className="h-4 w-4" />}
                onClick={() => setMoreOpen((current) => !current)}
              />
            )}
            actionsPanel={moreOpen ? (
              <div data-testid="signal-more-panel" className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  {STATUS_ACTIONS.map((status) => (
                    <button
                      key={status}
                      type="button"
                      className="btn-secondary !px-3 !py-1.5 !text-xs"
                      onClick={() => setPendingStatus({
                        item: selected.item,
                        status,
                        message: t(STATUS_ACTION_CONFIRM_KEYS[status]),
                      })}
                      disabled={statusUpdating || selected.item.status === status}
                    >
                      {t(STATUS_ACTION_LABEL_KEYS[status])}
                    </button>
                  ))}
                </div>
                {renderReassessPanel()}
              </div>
            ) : null}
          />
        ) : null}
      </Drawer>

      {statusUpdating ? (
        <InlineAlert
          className="fixed bottom-[calc(1.25rem+var(--shell-bottom-inset,0px))] right-5 z-[60] max-w-sm"
          variant="info"
          title={t('common.processing')}
          message={t('decisionSignals.confirmStatusTitle')}
        />
      ) : null}

      <ConfirmDialog
        isOpen={reassessPersistConfirm}
        title={t('decisionSignals.reassessPersistConfirmTitle')}
        message={t('decisionSignals.reassessPersistConfirmMessage')}
        confirmText={t('decisionSignals.reassessPersist')}
        confirmDisabled={reassessPersisting}
        cancelDisabled={reassessPersisting}
        onConfirm={() => void handlePersistReassess()}
        onCancel={() => setReassessPersistConfirm(false)}
      />

      <ConfirmDialog
        isOpen={Boolean(pendingStatus)}
        title={t('decisionSignals.confirmStatusTitle')}
        message={pendingStatus?.message ?? ''}
        confirmText={t('common.confirm')}
        confirmDisabled={statusUpdating}
        cancelDisabled={statusUpdating}
        onConfirm={() => void handleStatusUpdate()}
        onCancel={() => setPendingStatus(null)}
      />
    </AppPage>
  );
};

export default DecisionSignalsPage;
