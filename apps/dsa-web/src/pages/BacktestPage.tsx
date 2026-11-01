import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { backtestApi } from '../api/backtest';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import { BacktestTrendCharts } from '../components/backtest/BacktestTrendCharts';
import {
  ApiErrorAlert,
  AppPage,
  Badge,
  Button,
  Card,
  DataTable,
  Drawer,
  EmptyState,
  Metric,
  MetricGroup,
  PageHeader,
  Pagination,
  Segmented,
  Tooltip,
  type DataTableColumn,
} from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { formatUiText, type UiLanguage } from '../i18n/uiText';
import {
  BACKTEST_DIRECTION_EXPECTED_LABELS,
  BACKTEST_EXIT_REASON_LABELS,
  BACKTEST_MOVEMENT_LABELS,
  BACKTEST_OUTCOME_LABELS,
  BACKTEST_OVERVIEW_TEXT,
  BACKTEST_PHASE_FILTER_OPTIONS,
  BACKTEST_PHASE_LABELS,
  BACKTEST_STATUS_LABELS,
  BACKTEST_TEXT,
} from '../locales/featureText';
import type {
  BacktestPhaseFilter,
  BacktestResultItem,
  BacktestRunResponse,
  BacktestSeriesResponse,
  BacktestStatusFilter,
  PerformanceMetrics,
} from '../types/backtest';
import { cn } from '../utils/cn';
import { buildDecisionActionLabelMap, getDecisionActionLabel } from '../utils/decisionAction';
import { formatNumber, formatPercent, formatPrice, NO_VALUE } from '../utils/format';
import { getMarketPhaseSummaryLabel } from '../utils/marketPhase';
import { marketToneClass } from '../utils/marketTone';

const BACKTEST_INPUT_CLASS =
  'input-surface input-focus-glow h-10 w-full rounded-xl border bg-transparent px-3 text-sm transition-all focus:outline-none disabled:cursor-not-allowed disabled:opacity-60';
const BACKTEST_COMPACT_INPUT_CLASS =
  'input-surface input-focus-glow h-10 rounded-xl border bg-transparent px-3 py-2 text-xs transition-all focus:outline-none disabled:cursor-not-allowed disabled:opacity-60';
const PAGE_SIZE = 20;
const INPUT_DEBOUNCE_MS = 300;
// 少於這個筆數的勝率與平均報酬不下結論（研究類結論的底線：樣本不足一律 inconclusive）。
const MIN_CONCLUSION_SAMPLE = 30;

type ResultTab = 'completed' | 'pending' | 'all';
const TAB_STATUS: Record<ResultTab, BacktestStatusFilter | undefined> = {
  completed: 'completed',
  pending: 'pending',
  all: undefined,
};

type BacktestText = (typeof BACKTEST_TEXT)[UiLanguage];

/** 實際用來查資料的條件；輸入框的值在 draft，確定後才寫進來，兩者分開顯示。 */
interface AppliedFilters {
  code?: string;
  windowDays?: number;
  dateFrom?: string;
  dateTo?: string;
  phase: BacktestPhaseFilter;
}

const sameFilters = (left: AppliedFilters | null, right: AppliedFilters): boolean => (
  left !== null
  && left.code === right.code
  && left.windowDays === right.windowDays
  && left.dateFrom === right.dateFrom
  && left.dateTo === right.dateTo
  && left.phase === right.phase
);

const hasNarrowingFilter = (filters: AppliedFilters | null): boolean => Boolean(
  filters && (filters.code || filters.dateFrom || filters.dateTo || filters.phase !== 'all'),
);

// ============ Helpers ============

function phaseLabel(row: BacktestResultItem, language: UiLanguage): string {
  const label = getMarketPhaseSummaryLabel(row.marketPhaseSummary, language);
  if (label) {
    return label
      .replace('市场阶段: ', '')
      .replace('市场阶段：', '')
      .replace('市場階段：', '')
      .replace('Market phase: ', '');
  }
  return (row.marketPhase ? BACKTEST_PHASE_LABELS[language][row.marketPhase] : undefined) || row.marketPhase || NO_VALUE;
}

function normalizeBacktestCode(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed ? trimmed.toUpperCase() : undefined;
}

function parseEvalWindowDays(value: string): number | undefined {
  const parsed = parseInt(value.trim(), 10);
  return Number.isNaN(parsed) || parsed < 1 ? undefined : parsed;
}

function labelFromMap(value: string | null | undefined, labels: Record<string, string>): string {
  if (!value) return NO_VALUE;
  return labels[value] ?? value;
}

/** 報酬是損益：紅賺綠賠、帶正負號；沒有讀數顯示 —。 */
const ReturnValue: React.FC<{ value?: number | null; className?: string }> = ({ value, className }) => (
  <span className={cn('tabular-nums', marketToneClass(value), className)}>{formatPercent(value)}</span>
);

function outcomeBadge(outcome: string | null | undefined, language: UiLanguage) {
  const labels = BACKTEST_OUTCOME_LABELS[language];
  switch (outcome) {
    case 'win':
      return <Badge variant="neutral" className="text-market-up">{labels.win}</Badge>;
    case 'loss':
      return <Badge variant="neutral" className="text-market-down">{labels.loss}</Badge>;
    case 'neutral':
      return <Badge variant="neutral">{labels.neutral}</Badge>;
    case undefined:
    case null:
    case '':
      return <span className="text-secondary-text">{NO_VALUE}</span>;
    default:
      return <Badge variant="default">{outcome}</Badge>;
  }
}

function rowStatus(row: BacktestResultItem): string {
  return row.maturityStatus || row.evalStatus;
}

function statusBadge(status: string, language: UiLanguage) {
  const labels = BACKTEST_STATUS_LABELS[language];
  switch (status) {
    case 'completed':
      return <Badge variant="success">{labels.completed}</Badge>;
    case 'pending':
      return <Badge variant="neutral">{labels.pending}</Badge>;
    case 'insufficient':
    case 'insufficient_data':
      return <Badge variant="warning">{labels.insufficient}</Badge>;
    case 'unable':
      return <Badge variant="warning">{labels.unable}</Badge>;
    case 'error':
      return <Badge variant="danger">{labels.error}</Badge>;
    default:
      return <Badge variant="default">{status}</Badge>;
  }
}

function actualMovementBadge(movement: string | null | undefined, language: UiLanguage) {
  const labels = BACKTEST_MOVEMENT_LABELS[language];
  switch (movement) {
    case 'up':
      return <Badge variant="neutral" className="text-market-up">{labels.up}</Badge>;
    case 'down':
      return <Badge variant="neutral" className="text-market-down">{labels.down}</Badge>;
    case 'flat':
      return <Badge variant="neutral">{labels.flat}</Badge>;
    default:
      return null;
  }
}

/** 對錯用中性色：這是判斷準不準，不是損益方向。 */
function directionMark(value: boolean | null | undefined, text: BacktestText) {
  if (value === true) return <span aria-label={text.yes} className="text-foreground">✓</span>;
  if (value === false) return <span aria-label={text.no} className="text-foreground">✕</span>;
  return <span aria-label={text.unknown} className="text-secondary-text">{NO_VALUE}</span>;
}

interface AdviceRow {
  advice: string;
  total: number;
  win: number;
  loss: number;
  neutral: number;
  winRatePct: number | null;
}

/** adviceBreakdown 的 key 是存檔的建議原文；內層數字缺值當 0 只影響這張拆解表。 */
function toAdviceRows(breakdown: Record<string, unknown> | undefined): AdviceRow[] {
  if (!breakdown) return [];
  return Object.entries(breakdown)
    .flatMap(([advice, raw]) => {
      if (!raw || typeof raw !== 'object') return [];
      const bucket = raw as Record<string, unknown>;
      const rate = bucket.winRatePct ?? bucket.win_rate_pct;
      return [{
        advice,
        total: Number(bucket.total ?? 0),
        win: Number(bucket.win ?? 0),
        loss: Number(bucket.loss ?? 0),
        neutral: Number(bucket.neutral ?? 0),
        winRatePct: typeof rate === 'number' ? rate : null,
      }];
    })
    .sort((left, right) => right.total - left.total);
}

function buildConclusion(metrics: PerformanceMetrics, language: UiLanguage): string {
  const text = BACKTEST_OVERVIEW_TEXT[language];
  if (metrics.completedCount < MIN_CONCLUSION_SAMPLE) {
    return formatUiText(text.conclusionInsufficient, {
      count: metrics.completedCount,
      min: MIN_CONCLUSION_SAMPLE,
    });
  }
  return formatUiText(text.conclusion, {
    count: formatNumber(metrics.completedCount),
    winRate: metrics.winRatePct != null ? `${formatNumber(metrics.winRatePct, 1)}%` : NO_VALUE,
    win: metrics.winCount,
    loss: metrics.lossCount,
    simulated: formatPercent(metrics.avgSimulatedReturnPct),
    stock: formatPercent(metrics.avgStockReturnPct),
  });
}

// ============ Run Summary ============

const RunSummary: React.FC<{ data: BacktestRunResponse; language: UiLanguage }> = ({ data, language }) => {
  const text = BACKTEST_TEXT[language];
  return (
    <div data-testid="backtest-run-summary" className="flex flex-wrap gap-x-4 gap-y-1 rounded-xl border border-border/60 p-3 text-xs text-secondary-text">
      <span>{text.processed} <span className="tabular-nums text-foreground">{data.processed}</span></span>
      <span>{text.saved} <span className="tabular-nums text-foreground">{data.saved}</span></span>
      <span>{text.completed} <span className="tabular-nums text-foreground">{data.completed}</span></span>
      <span>{text.insufficient} <span className="tabular-nums text-foreground">{data.insufficient}</span></span>
      {data.errors > 0 ? <span>{text.errors} <span className="tabular-nums text-danger">{data.errors}</span></span> : null}
      {data.message ? <span className="w-full">{data.message}</span> : null}
    </div>
  );
};

// ============ Main Page ============

const BacktestPage: React.FC = () => {
  const { language, t } = useUiLanguage();
  const text = BACKTEST_TEXT[language];
  const overview = BACKTEST_OVERVIEW_TEXT[language];
  const phaseFilterOptions = BACKTEST_PHASE_FILTER_OPTIONS[language];
  const actionLabels = useMemo(() => buildDecisionActionLabelMap(t), [t]);

  useEffect(() => {
    document.title = text.documentTitle;
  }, [text.documentTitle]);

  // 輸入值（draft）
  const [codeFilter, setCodeFilter] = useState('');
  const [analysisDateFrom, setAnalysisDateFrom] = useState('');
  const [analysisDateTo, setAnalysisDateTo] = useState('');
  const [phaseFilter, setPhaseFilter] = useState<BacktestPhaseFilter>('all');
  const [evalDays, setEvalDays] = useState('');
  // 已套用條件；null 表示初始化還沒結束，不查資料。
  const [applied, setApplied] = useState<AppliedFilters | null>(null);
  const [tab, setTab] = useState<ResultTab>('completed');
  const [currentPage, setCurrentPage] = useState(1);
  const [reloadToken, setReloadToken] = useState(0);

  // 重新計算
  const [runOpen, setRunOpen] = useState(false);
  const [forceRerun, setForceRerun] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [runResult, setRunResult] = useState<BacktestRunResponse | null>(null);
  const [runError, setRunError] = useState<ParsedApiError | null>(null);

  const [resultsError, setResultsError] = useState<ParsedApiError | null>(null);
  const [perfError, setPerfError] = useState<ParsedApiError | null>(null);
  const [results, setResults] = useState<BacktestResultItem[]>([]);
  const [totalResults, setTotalResults] = useState(0);
  const [statusCounts, setStatusCounts] = useState<Record<string, number>>({});
  const [isLoadingResults, setIsLoadingResults] = useState(true);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const [overallPerf, setOverallPerf] = useState<PerformanceMetrics | null>(null);
  const [stockPerf, setStockPerf] = useState<PerformanceMetrics | null>(null);
  const [series, setSeries] = useState<BacktestSeriesResponse | null>(null);

  const resultsRequestRef = useRef(0);
  const perfRequestRef = useRef(0);
  const seriesRequestRef = useRef(0);

  const applyFilters = useCallback((next: AppliedFilters) => {
    setApplied((current) => {
      if (sameFilters(current, next)) return current;
      setCurrentPage(1);
      return next;
    });
  }, []);

  const buildDraftFilters = useCallback((): AppliedFilters => ({
    code: normalizeBacktestCode(codeFilter),
    windowDays: parseEvalWindowDays(evalDays),
    dateFrom: analysisDateFrom || undefined,
    dateTo: analysisDateTo || undefined,
    phase: phaseFilter,
  }), [analysisDateFrom, analysisDateTo, codeFilter, evalDays, phaseFilter]);

  // 初始化：先問最新一批的窗口，清單和績效才會用同一個窗口。績效讀不到也要往下走，頁面不能卡在空白。
  useEffect(() => {
    let cancelled = false;
    const init = async () => {
      let windowDays: number | undefined;
      try {
        const overall = await backtestApi.getOverallPerformance();
        if (cancelled) return;
        windowDays = overall?.evalWindowDays;
        if (windowDays) setEvalDays(String(windowDays));
      } catch (err) {
        if (cancelled) return;
        console.error('Failed to initialize backtest page:', err);
        setPerfError(getParsedApiError(err));
      }
      setApplied({ windowDays, phase: 'all' });
    };
    void init();
    return () => {
      cancelled = true;
    };
  }, []);

  // 篩選列改動即查：打字防抖，其餘同一條路徑。
  const initialized = applied !== null;
  useEffect(() => {
    if (!initialized) return undefined;
    const timer = window.setTimeout(() => applyFilters(buildDraftFilters()), INPUT_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [applyFilters, buildDraftFilters, initialized]);

  // 清單
  useEffect(() => {
    if (!applied) return undefined;
    const requestId = resultsRequestRef.current + 1;
    resultsRequestRef.current = requestId;
    setIsLoadingResults(true);
    setExpandedKey(null);
    void backtestApi.getResults({
      code: applied.code,
      evalWindowDays: applied.windowDays,
      analysisDateFrom: applied.dateFrom,
      analysisDateTo: applied.dateTo,
      analysisPhase: applied.phase !== 'all' ? applied.phase : undefined,
      status: TAB_STATUS[tab],
      page: currentPage,
      limit: PAGE_SIZE,
    })
      .then((response) => {
        if (resultsRequestRef.current !== requestId) return;
        setResults(response.items);
        setTotalResults(response.total);
        setStatusCounts(response.statusCounts ?? {});
        setResultsError(null);
      })
      .catch((err) => {
        if (resultsRequestRef.current !== requestId) return;
        console.error('Failed to fetch backtest results:', err);
        setResults([]);
        setTotalResults(0);
        setResultsError(getParsedApiError(err));
      })
      .finally(() => {
        if (resultsRequestRef.current === requestId) setIsLoadingResults(false);
      });
    return () => {
      resultsRequestRef.current += 1;
    };
  }, [applied, currentPage, reloadToken, tab]);

  // 績效彙總
  useEffect(() => {
    if (!applied) return undefined;
    const requestId = perfRequestRef.current + 1;
    perfRequestRef.current = requestId;
    const params = {
      evalWindowDays: applied.windowDays,
      analysisDateFrom: applied.dateFrom,
      analysisDateTo: applied.dateTo,
      analysisPhase: applied.phase !== 'all' ? applied.phase : undefined,
    };
    const load = async () => {
      try {
        const overall = await backtestApi.getOverallPerformance(params);
        const stock = applied.code ? await backtestApi.getStockPerformance(applied.code, params) : null;
        if (perfRequestRef.current !== requestId) return;
        setOverallPerf(overall);
        setStockPerf(stock);
        setPerfError(null);
      } catch (err) {
        if (perfRequestRef.current !== requestId) return;
        console.error('Failed to fetch performance:', err);
        setPerfError(getParsedApiError(err));
      }
    };
    void load();
    return () => {
      perfRequestRef.current += 1;
    };
  }, [applied, reloadToken]);

  // 趨勢圖只是補充：失敗就隱藏，不擋清單與績效。
  useEffect(() => {
    if (!applied) return undefined;
    const requestId = seriesRequestRef.current + 1;
    seriesRequestRef.current = requestId;
    void backtestApi.getSeries({
      code: applied.code,
      evalWindowDays: applied.windowDays,
      analysisDateFrom: applied.dateFrom,
      analysisDateTo: applied.dateTo,
    })
      .then((response) => {
        if (seriesRequestRef.current === requestId) setSeries(response);
      })
      .catch((err) => {
        if (seriesRequestRef.current !== requestId) return;
        console.error('Failed to fetch backtest series:', err);
        setSeries(null);
      });
    return () => {
      seriesRequestRef.current += 1;
    };
  }, [applied, reloadToken]);

  const handleRun = async () => {
    setIsRunning(true);
    setRunResult(null);
    setRunError(null);
    try {
      const draft = buildDraftFilters();
      const response = await backtestApi.run({
        code: draft.code,
        force: forceRerun || undefined,
        minAgeDays: forceRerun ? 0 : undefined,
        evalWindowDays: draft.windowDays,
        analysisDateFrom: draft.dateFrom,
        analysisDateTo: draft.dateTo,
      });
      setRunResult(response);
      const effectiveWindow = response.appliedEvalWindowDays ?? draft.windowDays ?? overallPerf?.evalWindowDays;
      if (effectiveWindow != null) setEvalDays(String(effectiveWindow));
      applyFilters({ ...draft, windowDays: effectiveWindow });
      setReloadToken((current) => current + 1);
    } catch (err) {
      setRunError(getParsedApiError(err));
    } finally {
      setIsRunning(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') applyFilters(buildDraftFilters());
  };

  const handleClearFilters = () => {
    setCodeFilter('');
    setAnalysisDateFrom('');
    setAnalysisDateTo('');
    setPhaseFilter('all');
    applyFilters({ windowDays: parseEvalWindowDays(evalDays), phase: 'all' });
  };

  const handleTabChange = (next: ResultTab) => {
    setTab(next);
    setCurrentPage(1);
  };

  const metrics = stockPerf ?? overallPerf;
  const windowDays = applied?.windowDays ?? metrics?.evalWindowDays;
  const isNextDay = windowDays === 1;
  const totalPages = Math.ceil(totalResults / PAGE_SIZE);
  const adviceRows = useMemo(() => toAdviceRows(metrics?.adviceBreakdown), [metrics?.adviceBreakdown]);

  const appliedChips = applied ? [
    applied.code ? formatUiText(text.filteredStock, { code: applied.code }) : text.allStocks,
    windowDays ? formatUiText(text.dayWindow, { days: windowDays }) : null,
    applied.phase !== 'all' ? (phaseFilterOptions.find((item) => item.value === applied.phase)?.label ?? applied.phase) : null,
    applied.dateFrom ? formatUiText(text.fromDate, { date: applied.dateFrom }) : null,
    applied.dateTo ? formatUiText(text.toDate, { date: applied.dateTo }) : null,
  ].filter((chip): chip is string => Boolean(chip)) : [];

  const tabCount = (status: string): string => {
    const count = statusCounts[status];
    return typeof count === 'number' ? ` ${count}` : '';
  };

  const renderPrediction = (row: BacktestResultItem) => {
    const actionLabel = getDecisionActionLabel(row.action, row.actionLabel, null, null, actionLabels);
    const parts = [actionLabel, row.trendPrediction, row.operationAdvice].filter((part): part is string => Boolean(part));
    if (parts.length === 0) return NO_VALUE;
    return (
      <Tooltip content={parts.join(' / ')} focusable>
        <span className="flex max-w-[16rem] items-baseline gap-1.5">
          <span className="shrink-0 text-foreground">{parts[0]}</span>
          {parts.slice(1).map((part) => (
            <span key={part} className="min-w-0 truncate text-xs text-secondary-text">{part}</span>
          ))}
        </span>
      </Tooltip>
    );
  };

  const renderReturn = (row: BacktestResultItem) => (
    <span className="inline-flex items-center gap-2">
      {actualMovementBadge(row.actualMovement, language)}
      <ReturnValue value={row.actualReturnPct} />
    </span>
  );

  const renderStatus = (row: BacktestResultItem) => (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      {statusBadge(rowStatus(row), language)}
      {rowStatus(row) === 'pending' && row.maturesBy ? (
        <span className="text-xs text-secondary-text">{formatUiText(overview.maturesBy, { date: row.maturesBy })}</span>
      ) : null}
    </span>
  );

  const renderExpanded = (row: BacktestResultItem) => {
    const entries: Array<[string, React.ReactNode]> = [
      [overview.entryDate, row.entryDate || NO_VALUE],
      [overview.entryPrice, formatPrice(row.simulatedEntryPrice)],
      [overview.exitPrice, formatPrice(row.simulatedExitPrice)],
      [overview.exitReason, labelFromMap(row.simulatedExitReason, BACKTEST_EXIT_REASON_LABELS[language])],
      [overview.simulatedReturn, <ReturnValue key="simulated" value={row.simulatedNetReturnPct ?? row.simulatedReturnPct} />],
      [overview.stopLoss, formatPrice(row.stopLoss)],
      [overview.takeProfit, formatPrice(row.takeProfit)],
      [overview.firstHit, labelFromMap(row.firstHit, BACKTEST_EXIT_REASON_LABELS[language])],
    ];
    return (
      <dl data-testid={`backtest-row-detail-${row.analysisHistoryId}`} className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs md:grid-cols-4">
        {entries.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="text-secondary-text">{label}</dt>
            <dd className="mt-0.5 tabular-nums text-foreground">{value}</dd>
          </div>
        ))}
      </dl>
    );
  };

  const toggleExpanded = (row: BacktestResultItem) => {
    const key = String(row.analysisHistoryId);
    setExpandedKey((current) => (current === key ? null : key));
  };

  const columns: DataTableColumn<BacktestResultItem>[] = [
    {
      key: 'stock',
      header: text.stock,
      render: (row) => (
        <span className="flex flex-col leading-tight">
          <span className="font-mono text-foreground">{row.code}</span>
          <span className="text-xs text-secondary-text">{row.stockName || NO_VALUE}</span>
        </span>
      ),
    },
    { key: 'analysisDate', header: text.analysisDate, render: (row) => <span className="tabular-nums text-secondary-text">{row.analysisDate || NO_VALUE}</span> },
    { key: 'phase', header: text.phase, render: (row) => <span className="text-secondary-text">{phaseLabel(row, language)}</span> },
    { key: 'prediction', header: text.aiPrediction, render: renderPrediction },
    { key: 'return', header: isNextDay ? text.actualPerformance : text.windowReturn, render: renderReturn },
    {
      key: 'direction',
      header: isNextDay ? text.accuracy : text.directionMatch,
      render: (row) => (
        <span className="inline-flex items-center gap-2">
          {directionMark(row.directionCorrect, text)}
          <span className="text-secondary-text">
            {row.directionExpected ? labelFromMap(row.directionExpected, BACKTEST_DIRECTION_EXPECTED_LABELS[language]) : ''}
          </span>
        </span>
      ),
    },
    { key: 'result', header: text.result, render: (row) => outcomeBadge(row.outcome, language) },
    { key: 'status', header: text.status, render: renderStatus },
  ];

  const renderMobileCard = (row: BacktestResultItem) => {
    const key = String(row.analysisHistoryId);
    const expanded = expandedKey === key;
    const actionLabel = getDecisionActionLabel(row.action, row.actionLabel, null, null, actionLabels);
    return (
      <div>
        <button
          type="button"
          data-testid={`backtest-mobile-row-${row.analysisHistoryId}`}
          aria-expanded={expanded}
          onClick={() => toggleExpanded(row)}
          className="flex w-full cursor-pointer flex-col gap-1 px-3 py-2 text-left"
        >
          <span className="flex items-center justify-between gap-2">
            <span className="min-w-0 truncate font-medium text-foreground">{row.stockName || row.code}</span>
            <ReturnValue value={row.actualReturnPct} />
          </span>
          <span className="flex items-center justify-between gap-2 text-xs text-secondary-text">
            <span className="min-w-0 truncate tabular-nums">{row.analysisDate || NO_VALUE}・{actionLabel || NO_VALUE}</span>
            <span className="inline-flex shrink-0 items-center gap-1.5">
              {directionMark(row.directionCorrect, text)}
              {statusBadge(rowStatus(row), language)}
            </span>
          </span>
        </button>
        {expanded ? <div className="px-3 pb-3">{renderExpanded(row)}</div> : null}
      </div>
    );
  };

  const adviceColumns: DataTableColumn<AdviceRow>[] = [
    {
      key: 'advice',
      header: overview.adviceColumn,
      priority: 'primary',
      render: (row) => (row.advice === '(unknown)' ? overview.adviceUnclassified : row.advice),
    },
    { key: 'total', header: overview.countColumn, numeric: true, render: (row) => formatNumber(row.total) },
    {
      key: 'outcomes',
      header: text.outcomeSummary,
      numeric: true,
      render: (row) => `${row.win}／${row.loss}／${row.neutral}`,
    },
    {
      key: 'winRate',
      header: text.winRate,
      numeric: true,
      priority: 'primary',
      render: (row) => (row.winRatePct != null ? `${formatNumber(row.winRatePct, 1)}%` : NO_VALUE),
    },
  ];

  const renderEmptyState = () => {
    if (hasNarrowingFilter(applied)) {
      return (
        <EmptyState
          title={overview.emptyFilteredTitle}
          description={overview.emptyFilteredDescription}
          action={<Button variant="secondary" onClick={handleClearFilters}>{overview.clearFilters}</Button>}
        />
      );
    }
    if (tab === 'pending') {
      return <EmptyState title={overview.emptyPendingTitle} description={overview.emptyPendingDescription} />;
    }
    return (
      <EmptyState
        title={text.noResultsTitle}
        description={text.noResultsDescription}
        action={<Button variant="secondary" onClick={() => setRunOpen(true)}>{overview.recalculate}</Button>}
      />
    );
  };

  return (
    <AppPage>
      <div className="space-y-4">
        <PageHeader
          title={overview.pageTitle}
          actions={<Button variant="secondary" onClick={() => setRunOpen(true)}>{overview.recalculate}</Button>}
        />

        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-[1_1_220px]">
              <input
                type="text"
                value={codeFilter}
                onChange={(e) => setCodeFilter(e.target.value.toUpperCase())}
                onKeyDown={handleKeyDown}
                placeholder={text.codePlaceholder}
                className={BACKTEST_INPUT_CLASS}
              />
            </div>
            <label className="flex items-center gap-2 whitespace-nowrap">
              <span className="text-xs text-secondary-text">{text.evalWindow}</span>
              <input
                type="number"
                min={1}
                max={120}
                value={evalDays}
                onChange={(e) => setEvalDays(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="10"
                className={`${BACKTEST_COMPACT_INPUT_CLASS} w-20 text-center tabular-nums`}
              />
            </label>
            <button
              type="button"
              aria-pressed={isNextDay}
              onClick={() => setEvalDays('1')}
              className={cn(
                'h-10 cursor-pointer whitespace-nowrap rounded-xl border px-3 text-xs transition-colors',
                isNextDay ? 'border-cyan/60 bg-cyan/10 text-foreground' : 'border-border/70 text-secondary-text hover:text-foreground',
              )}
            >
              {text.oneDayValidation}
            </button>
            <label className="flex items-center gap-2 whitespace-nowrap">
              <span className="text-xs text-secondary-text">{text.phase}</span>
              <select
                value={phaseFilter}
                onChange={(e) => setPhaseFilter(e.target.value as BacktestPhaseFilter)}
                className={`${BACKTEST_COMPACT_INPUT_CLASS} w-28`}
              >
                {phaseFilterOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <input
              type="date"
              aria-label={text.startDateAria}
              value={analysisDateFrom}
              onChange={(e) => setAnalysisDateFrom(e.target.value)}
              onKeyDown={handleKeyDown}
              className={`${BACKTEST_COMPACT_INPUT_CLASS} w-36 text-center tabular-nums`}
            />
            <input
              type="date"
              aria-label={text.endDateAria}
              value={analysisDateTo}
              onChange={(e) => setAnalysisDateTo(e.target.value)}
              onKeyDown={handleKeyDown}
              className={`${BACKTEST_COMPACT_INPUT_CLASS} w-36 text-center tabular-nums`}
            />
          </div>
          {appliedChips.length > 0 ? (
            <p data-testid="backtest-applied" className="text-xs text-secondary-text">
              {overview.appliedLabel}{appliedChips.join('・')}
            </p>
          ) : null}
          <p className="text-xs text-muted-text">{isNextDay ? text.oneDayModeDescription : text.windowModeDescription}</p>
        </div>

        {perfError ? <ApiErrorAlert error={perfError} /> : null}

        {metrics ? (
          <section aria-label={text.overallPerformance} className="space-y-3">
            <p data-testid="backtest-conclusion" className="text-sm text-foreground">
              {buildConclusion(metrics, language)}
            </p>
            <MetricGroup>
              <Metric
                label={text.winRate}
                value={metrics.winRatePct != null ? `${formatNumber(metrics.winRatePct, 1)}%` : undefined}
                hint={`${metrics.winCount}／${metrics.lossCount}／${metrics.neutralCount}`}
              />
              <Metric label={text.avgSimulatedReturn} value={<ReturnValue value={metrics.avgSimulatedReturnPct} />} />
              <Metric label={text.avgStockReturn} value={<ReturnValue value={metrics.avgStockReturnPct} />} />
              <Metric
                label={text.directionAccuracy}
                value={metrics.directionAccuracyPct != null ? `${formatNumber(metrics.directionAccuracyPct, 1)}%` : undefined}
                hint={`${text.evaluationCount} ${Number(metrics.completedCount)} / ${Number(metrics.totalEvaluations)}`}
              />
            </MetricGroup>
          </section>
        ) : null}

        <BacktestTrendCharts
          series={series}
          phaseFiltered={applied?.phase !== undefined && applied.phase !== 'all'}
          fallbackUpdatedAt={metrics?.computedAt}
        />

        {adviceRows.length > 0 ? (
          <Card title={overview.adviceTitle} padding="sm">
            <DataTable
              aria-label={overview.adviceTitle}
              columns={adviceColumns}
              rows={adviceRows}
              rowKey={(row) => row.advice}
              density="compact"
            />
          </Card>
        ) : null}

        <section aria-label={isNextDay ? text.nextDayValidation : text.resultSet} className="space-y-3">
          <Segmented<ResultTab>
            aria-label={text.status}
            value={tab}
            onChange={handleTabChange}
            options={[
              { value: 'completed', label: `${overview.tabCompleted}${tabCount('completed')}` },
              { value: 'pending', label: `${overview.tabPending}${tabCount('pending')}` },
              { value: 'all', label: overview.tabAll },
            ]}
          />

          {resultsError ? <ApiErrorAlert error={resultsError} /> : null}

          {isLoadingResults && results.length === 0 ? (
            <p role="status" className="py-8 text-center text-sm text-secondary-text">{text.loadingResults}</p>
          ) : results.length === 0 ? (
            resultsError ? null : renderEmptyState()
          ) : (
            <>
              <DataTable
                aria-label={isNextDay ? text.nextDayValidation : text.resultSet}
                columns={columns}
                rows={results}
                rowKey={(row) => String(row.analysisHistoryId)}
                onRowClick={toggleExpanded}
                expandedRowKey={expandedKey}
                renderExpandedRow={renderExpanded}
                renderMobileCard={renderMobileCard}
              />
              <Pagination currentPage={currentPage} totalPages={totalPages} onPageChange={setCurrentPage} />
              <p className="text-center text-xs text-muted-text">
                {formatUiText(text.totalPage, { total: totalResults, page: currentPage, pages: Math.max(totalPages, 1) })}
              </p>
            </>
          )}
        </section>
      </div>

      <Drawer isOpen={runOpen} onClose={() => setRunOpen(false)} title={overview.recalculate}>
        <div className="space-y-4">
          <p className="text-sm text-secondary-text">{overview.recalculateDescription}</p>
          {appliedChips.length > 0 ? <p className="text-xs text-secondary-text">{overview.appliedLabel}{appliedChips.join('・')}</p> : null}
          <label className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={forceRerun}
              onChange={(e) => setForceRerun(e.target.checked)}
              disabled={isRunning}
            />
            {text.forceRerun}
          </label>
          <Button variant="primary" isLoading={isRunning} disabled={isRunning} onClick={() => void handleRun()}>
            {isRunning ? text.running : text.runBacktest}
          </Button>
          {runResult ? <RunSummary data={runResult} language={language} /> : null}
          {runError ? <ApiErrorAlert error={runError} /> : null}
        </div>
      </Drawer>
    </AppPage>
  );
};

export default BacktestPage;
