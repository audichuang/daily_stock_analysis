import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  usageApi,
  type UsageCallRecord,
  type UsageDashboard,
  type UsageDayBreakdown,
  type UsagePeriod,
  type UsageSort,
} from '../api/usage';
import type { ParsedApiError } from '../api/error';
import { ApiErrorAlert, AppPage, Button, Card, DataTable, EmptyState, Loading, PageHeader, Segmented, Select, Tooltip, type DataTableColumn } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { formatUiText, type UiTextKey, type UiTextParams } from '../i18n/uiText';
import { USAGE_TEXT, type UsageText } from '../locales/usageText';
import { cn } from '../utils/cn';
import { formatMoneyValue, formatNumber, formatPercent, NO_VALUE } from '../utils/format';
import { groupRecords, mergeModels, modelDisplayName, prettyModelName, sharePercents, type MergedModel, type RecordEntry } from '../utils/usageSummary';

type Translate = (key: UiTextKey, params?: UiTextParams) => string;

const PAGE_SIZE = 50;
const MAX_DAY_BARS = 60;
// Below this many days with data a bar chart is mostly empty space, so show text instead.
const MIN_DAYS_FOR_BARS = 3;
const ALL_TYPES = 'all';
const PERIOD_OPTIONS: UsagePeriod[] = ['today', 'month', 'all'];

const PERIOD_LABEL_KEYS: Record<UsagePeriod, UiTextKey> = {
  today: 'usage.period.today',
  month: 'usage.period.month',
  all: 'usage.period.all',
};

const CALL_TYPE_LABEL_KEYS: Record<string, UiTextKey> = {
  analysis: 'usage.callType.analysis',
  agent: 'usage.callType.agent',
  market_review: 'usage.callType.marketReview',
  stock_dossier: 'usage.callType.stockDossier',
};

function getCallTypeLabel(callType: string, t: Translate, text: UsageText): string {
  const key = CALL_TYPE_LABEL_KEYS[callType];
  if (key) return t(key);
  const known = text.callTypes[callType];
  if (known) return known;
  return callType ? formatUiText(text.callTypeOther, { type: callType }) : text.callTypeOtherBare;
}

/**
 * The Claude Code CLI backend logs its preset id instead of a model; real Claude ids
 * (claude-opus-4-7) become product names. Callers keep the raw id in a title attribute.
 */
const CLAUDE_MODEL_PATTERN = /^claude[-_]code[-_]cli$/i;
const displayModelName = (model: string, text: UsageText): string => {
  const name = modelDisplayName(model);
  return CLAUDE_MODEL_PATTERN.test(name) ? text.claudeModel : prettyModelName(name);
};

/** Compact token count for one-line summaries: 953412 -> 953K, 1234 -> 1.2K, 2500000 -> 2.5M. */
const compactTokens = (value: number): string => {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${formatNumber(value / 1_000_000, 1)}M`;
  if (abs >= 10_000) return `${formatNumber(Math.round(value / 1000))}K`;
  if (abs >= 1000) return `${formatNumber(value / 1000, 1)}K`;
  return formatNumber(value);
};

const shortDate = (date: string): string => date.slice(5).replace('-', '/');

const DAY_MS = 86_400_000;
const parseIsoDay = (value: string): number | null => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const time = Date.parse(`${value}T00:00:00Z`);
  return Number.isNaN(time) ? null : time;
};

/** Every calendar day in [fromDate, toDate] (last MAX_DAY_BARS), zero-filled where there is no data. */
function fillDays(days: UsageDayBreakdown[], fromDate: string, toDate: string): Array<UsageDayBreakdown | { date: string; empty: true }> {
  const start = parseIsoDay(fromDate);
  const end = parseIsoDay(toDate);
  if (start == null || end == null || end < start) return days.slice(-MAX_DAY_BARS);
  const byDate = new Map(days.map((day) => [day.date, day]));
  const first = Math.max(start, end - (MAX_DAY_BARS - 1) * DAY_MS);
  const filled: Array<UsageDayBreakdown | { date: string; empty: true }> = [];
  for (let time = first; time <= end; time += DAY_MS) {
    const date = new Date(time).toISOString().slice(0, 10);
    filled.push(byDate.get(date) ?? { date, empty: true });
  }
  // A long 'all' range whose last call is older than the window would render only empty slots.
  return filled.some((day) => !('empty' in day)) ? filled : days.slice(-MAX_DAY_BARS);
}

function buildParsedError(error: unknown, t: Translate): ParsedApiError {
  if (error && typeof error === 'object' && 'parsedError' in error) {
    const parsedError = (error as { parsedError?: ParsedApiError }).parsedError;
    if (parsedError) {
      return parsedError;
    }
  }

  const message = error instanceof Error ? error.message : t('usage.error.message');
  return {
    title: t('usage.error.title'),
    message,
    rawMessage: message,
    category: 'http_error',
  };
}

const formatCost = (value: number | null, currency: string): string => (
  // 單次費用常低於一分錢，兩位小數會變 0.00。
  formatMoneyValue(value, currency, value != null && Math.abs(value) < 1 ? 4 : 2)
);

const shareText = (value: number): string => `${formatNumber(value, 1)}%`;

const UsageSummaryBand: React.FC<{ dashboard: UsageDashboard; period: UsagePeriod; text: UsageText; t: Translate }> = ({ dashboard, period, text, t }) => {
  const { cost, previous, cache } = dashboard;
  const shares = sharePercents(dashboard.byCallType.map((item) => item.totalTokens));
  const topIndex = shares.indexOf(Math.max(...shares, 0));
  const top = dashboard.byCallType[topIndex];
  const periodLabel = t(PERIOD_LABEL_KEYS[period]);
  const sentence = top
    ? formatUiText(text.conclusion, {
      period: periodLabel,
      calls: formatNumber(dashboard.totalCalls),
      top: getCallTypeLabel(top.callType, t, text),
      share: shareText(shares[topIndex]),
    })
    : formatUiText(text.conclusionPlain, { period: periodLabel, calls: formatNumber(dashboard.totalCalls) });

  // No unit price at all means there is nothing to estimate; hide the line instead of saying so.
  let costLine: string | null = null;
  if (cost.estimatedTotal != null) {
    costLine = formatCost(cost.estimatedTotal, cost.currency);
    if (!cost.complete) costLine += `（${text.costPartial}）`;
  } else if (cost.subscriptionTokens > 0 && cost.complete) {
    costLine = text.costSubscription;
  }

  const changeLabel = period === 'today' ? text.changeToday : text.changeMonth;
  const stats = [
    { label: text.metricCalls, value: formatNumber(dashboard.totalCalls) },
    { label: text.metricInOut, value: `${compactTokens(dashboard.totalPromptTokens)} / ${compactTokens(dashboard.totalCompletionTokens)}` },
    {
      label: text.metricCache,
      value: cache.hitRatio == null
        ? <Tooltip content={text.cacheUnreported} focusable><span aria-label={text.cacheUnreported}>{NO_VALUE}</span></Tooltip>
        : `${formatNumber(cache.hitRatio * 100, 1)}%`,
    },
  ];

  return (
    <Card variant="surface" padding="md">
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" data-testid="usage-summary">
        <div className="min-w-0">
          <p className="text-xs text-secondary-text">{text.totalLabel}</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums text-foreground" data-testid="usage-total">{formatNumber(dashboard.totalTokens)}</p>
          {costLine ? (
            <p className="mt-2 text-sm text-foreground">
              <span className="text-secondary-text">{`${text.costLabel} `}</span>
              <span className="tabular-nums" data-testid="usage-cost">{costLine}</span>
            </p>
          ) : null}
          {cost.estimatedTotal != null && cost.subscriptionTokens > 0 ? (
            <p className="mt-1 text-xs text-secondary-text">{formatUiText(text.subscriptionNote, { tokens: formatNumber(cost.subscriptionTokens) })}</p>
          ) : null}
          {previous && previous.tokensChangePct != null ? (
            <p className="mt-1 text-xs text-secondary-text" data-testid="usage-change">
              {`${changeLabel} `}
              <span className="tabular-nums">{formatPercent(previous.tokensChangePct, 1)}</span>
            </p>
          ) : null}
          <p className="mt-2 text-sm text-secondary-text">{sentence}</p>
        </div>
        {/* Columns never shrink below their nowrap value (equal thirds left 77px for ~91px of "12.5M / 953K" at 390px);
            labels may wrap instead, and leftover width is still shared evenly. */}
        <dl className="grid grid-cols-[repeat(3,minmax(min-content,1fr))] gap-2 self-start">
          {stats.map((stat) => (
            // Column layout pushes values to the bottom so they share a baseline when one label wraps.
            <div key={stat.label} className="flex min-w-0 flex-col rounded-lg border border-border/60 px-2 py-2 sm:px-3">
              <dt className="text-xs text-secondary-text">{stat.label}</dt>
              <dd className="mt-auto whitespace-nowrap pt-1 text-sm font-medium tabular-nums text-foreground">{stat.value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </Card>
  );
};

interface DailyBarsProps {
  days: UsageDayBreakdown[];
  fromDate: string;
  toDate: string;
  selected: string | null;
  onSelect: (day: string | null) => void;
  text: UsageText;
}

const DailyBars: React.FC<DailyBarsProps> = ({ days, fromDate, toDate, selected, onSelect, text }) => {
  const dayLabel = (day: UsageDayBreakdown) => formatUiText(text.dayBar, {
    date: day.date,
    total: formatNumber(day.totalTokens),
    input: formatNumber(day.promptTokens),
    output: formatNumber(day.completionTokens),
  });

  if (days.length < MIN_DAYS_FOR_BARS) {
    return (
      <Card title={text.dailyTitle} variant="surface" padding="md">
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm" data-testid="usage-daily-summary">
          {days.map((day) => {
            const isSelected = selected === day.date;
            return (
              <button
                key={day.date}
                type="button"
                aria-label={dayLabel(day)}
                aria-pressed={isSelected}
                onClick={() => onSelect(isSelected ? null : day.date)}
                className={cn(
                  'cursor-pointer rounded px-1 text-left tabular-nums text-foreground hover:bg-hover',
                  isSelected && 'text-cyan',
                )}
              >
                {formatUiText(text.daySummary, {
                  date: shortDate(day.date),
                  input: compactTokens(day.promptTokens),
                  output: compactTokens(day.completionTokens),
                })}
              </button>
            );
          })}
        </div>
      </Card>
    );
  }

  const shown = fillDays(days, fromDate, toDate);
  const max = Math.max(...shown.map((day) => ('empty' in day ? 0 : day.totalTokens)), 1);
  return (
    <Card title={text.dailyTitle} subtitle={text.dailyHint} variant="surface" padding="md">
      <div className="mb-2 flex items-center gap-3 text-xs text-secondary-text">
        <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-cyan" aria-hidden="true" />{text.input}</span>
        <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-cyan/40" aria-hidden="true" />{text.output}</span>
      </div>
      <div className="flex h-32 items-end gap-[2px]" data-testid="usage-daily-bars">
        {shown.map((day) => {
          if ('empty' in day) {
            // Days without calls keep their slot so the axis reads as real calendar time.
            return <span key={day.date} className="h-full min-w-0 max-w-8 flex-1" aria-hidden="true" />;
          }
          const isSelected = selected === day.date;
          return (
            <button
              key={day.date}
              type="button"
              aria-label={dayLabel(day)}
              aria-pressed={isSelected}
              onClick={() => onSelect(isSelected ? null : day.date)}
              className={cn(
                'flex h-full min-w-0 max-w-8 flex-1 cursor-pointer flex-col justify-end gap-[2px] rounded-t hover:bg-hover',
                selected && !isSelected && 'opacity-40',
              )}
            >
              {/* 比例用 flex 分配，段間 2px 空隙不會把總高撐過長條。 */}
              <span className="flex min-h-[2px] w-full flex-col gap-[2px]" style={{ height: `${(day.totalTokens / max) * 100}%` }}>
                <span className="min-h-0 w-full rounded-t-[4px] bg-cyan/40" style={{ flexGrow: day.completionTokens }} />
                <span className="min-h-0 w-full bg-cyan" style={{ flexGrow: day.promptTokens }} />
              </span>
            </button>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-xs tabular-nums text-muted-text">
        <span>{shortDate(shown[0].date)}</span>
        <span>{shortDate(shown[shown.length - 1].date)}</span>
      </div>
    </Card>
  );
};

const CallTypeShare: React.FC<{ dashboard: UsageDashboard; text: UsageText; t: Translate }> = ({ dashboard, text, t }) => {
  const shares = sharePercents(dashboard.byCallType.map((item) => item.totalTokens));
  return (
    <Card title={text.shareTitle} variant="surface" padding="md">
      <ul className="space-y-3">
        {dashboard.byCallType.map((item, index) => (
          <li key={item.callType} data-testid={`usage-share-${item.callType}`}>
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="min-w-0 break-words text-foreground">{getCallTypeLabel(item.callType, t, text)}</span>
              <span className="shrink-0 tabular-nums text-foreground">{shareText(shares[index])}</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-border/70">
              <div className="h-full rounded-full bg-cyan" style={{ width: `${shares[index]}%` }} />
            </div>
            <p className="mt-1 text-xs text-secondary-text">
              {formatUiText(text.shareDetail, { calls: formatNumber(item.calls), tokens: formatNumber(item.totalTokens) })}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  );
};

const ModelTable: React.FC<{ dashboard: UsageDashboard; text: UsageText }> = ({ dashboard, text }) => {
  const rows = useMemo(() => mergeModels(dashboard.byModel, dashboard.cost), [dashboard.byModel, dashboard.cost]);
  const costCell = (row: MergedModel): string => {
    if (row.costState === 'subscription') return text.costSubscription;
    if (row.costState === 'unpriced') return text.costUnpriced;
    if (row.cost == null) return NO_VALUE;
    const value = formatCost(row.cost, dashboard.cost.currency);
    return row.costState === 'partial' ? `${value}（${text.costPartial}）` : value;
  };
  // Without any unit price every cell would just say "unpriced"; drop the column instead.
  const hasCost = rows.some((row) => row.costState !== 'unpriced' && row.costState !== 'unknown');
  const costColumn: DataTableColumn<MergedModel> = { key: 'cost', header: text.cost, numeric: true, render: costCell };
  const columns: DataTableColumn<MergedModel>[] = [
    { key: 'name', header: text.model, priority: 'primary', render: (row) => {
      const shown = displayModelName(row.name, text);
      // The raw id only adds information when it was renamed; Tooltip renders bare children without content.
      return <Tooltip content={shown !== row.name ? row.name : undefined} focusable><span className="break-all text-foreground">{shown}</span></Tooltip>;
    } },
    { key: 'calls', header: text.calls, numeric: true, render: (row) => formatNumber(row.calls) },
    { key: 'input', header: text.input, numeric: true, render: (row) => formatNumber(row.promptTokens) },
    { key: 'output', header: text.output, numeric: true, render: (row) => formatNumber(row.completionTokens) },
    { key: 'total', header: text.total, numeric: true, priority: 'primary', render: (row) => <span className="font-medium text-foreground">{formatNumber(row.totalTokens)}</span> },
    { key: 'peak', header: text.peak, numeric: true, render: (row) => formatNumber(row.maxTotalTokens) },
    ...(hasCost ? [costColumn] : []),
  ];
  return (
    <Card title={text.modelTitle} variant="surface" padding="md">
      <DataTable aria-label={text.modelTitle} columns={columns} rows={rows} rowKey={(row) => row.name} density="compact" />
    </Card>
  );
};

const timeText = (calledAt: string, flat: boolean): string => {
  // called_at 是後端本地時間，直接取字串，與分日的天界一致。
  const value = flat ? calledAt.slice(5, 16) : calledAt.slice(11, 16);
  return value.replace('T', ' ') || NO_VALUE;
};

const StockLink: React.FC<{ code?: string | null }> = ({ code }) => (code ? (
  <Link to={`/?stock=${encodeURIComponent(code)}`} className="text-cyan hover:underline" onClick={(event) => event.stopPropagation()}>
    {code}
  </Link>
) : null);

interface RecordRowsProps {
  entry: RecordEntry;
  flat: boolean;
  expanded: boolean;
  onToggle: (id: string) => void;
  text: UsageText;
  t: Translate;
}

const DesktopRecordCells: React.FC<{ record: UsageCallRecord; flat: boolean; text: UsageText; t: Translate; nested?: boolean }> = ({ record, flat, text, t, nested }) => (
  <tr className="border-b border-border/40" data-testid={`usage-record-${record.id}`}>
    <td className={cn('whitespace-nowrap px-3 py-2 tabular-nums text-secondary-text', nested && 'pl-6')}>{timeText(record.calledAt, flat)}</td>
    <td className="whitespace-nowrap px-3 py-2 text-foreground">{getCallTypeLabel(record.callType, t, text)}</td>
    <td className="px-3 py-2"><StockLink code={record.stockCode} /></td>
    <td className="max-w-[18rem] truncate px-3 py-2 text-secondary-text" title={record.model}>{displayModelName(record.model, text)}</td>
    <td className="px-3 py-2 text-right tabular-nums text-secondary-text">{formatNumber(record.promptTokens)}</td>
    <td className="px-3 py-2 text-right tabular-nums text-secondary-text">{formatNumber(record.completionTokens)}</td>
    <td className="px-3 py-2 text-right font-medium tabular-nums text-foreground">{formatNumber(record.totalTokens)}</td>
  </tr>
);

const DesktopEntry: React.FC<RecordRowsProps> = ({ entry, flat, expanded, onToggle, text, t }) => {
  if (entry.kind === 'single') return <DesktopRecordCells record={entry.record} flat={flat} text={text} t={t} />;
  const first = entry.records[0];
  const count = entry.records.length;
  return (
    <>
      <tr className="border-b border-border/40">
        <td className="whitespace-nowrap px-3 py-2 tabular-nums text-secondary-text">{timeText(first.calledAt, flat)}</td>
        <td className="whitespace-nowrap px-3 py-2 text-foreground">
          {getCallTypeLabel(first.callType, t, text)}
          <button
            type="button"
            aria-expanded={expanded}
            className="ml-2 cursor-pointer text-xs text-cyan hover:underline"
            onClick={() => onToggle(entry.id)}
          >
            {formatUiText(expanded ? text.collapseRounds : text.expandRounds, { count })}
          </button>
        </td>
        <td className="px-3 py-2"><StockLink code={first.stockCode} /></td>
        <td className="max-w-[18rem] truncate px-3 py-2 text-secondary-text" title={first.model}>{displayModelName(first.model, text)}</td>
        <td className="px-3 py-2 text-right tabular-nums text-secondary-text">{formatNumber(entry.promptTokens)}</td>
        <td className="px-3 py-2 text-right tabular-nums text-secondary-text">{formatNumber(entry.completionTokens)}</td>
        <td className="px-3 py-2 text-right font-medium tabular-nums text-foreground">{formatNumber(entry.totalTokens)}</td>
      </tr>
      {expanded ? entry.records.map((record) => <DesktopRecordCells key={record.id} record={record} flat={flat} text={text} t={t} nested />) : null}
    </>
  );
};

const MobileRecord: React.FC<{ record: UsageCallRecord; flat: boolean; text: UsageText; t: Translate; nested?: boolean }> = ({ record, flat, text, t, nested }) => (
  <li className={cn('py-2 text-sm', nested && 'pl-3')}>
    <div className="flex items-baseline justify-between gap-3">
      <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
        <span className="tabular-nums text-secondary-text">{timeText(record.calledAt, flat)}</span>
        <span className="text-foreground">{getCallTypeLabel(record.callType, t, text)}</span>
        <StockLink code={record.stockCode} />
      </span>
      {/* 合計固定在第一行右側，手機不用橫捲就看得到。 */}
      <span className="shrink-0 font-medium tabular-nums text-foreground" data-testid={`usage-mobile-total-${record.id}`}>{formatNumber(record.totalTokens)}</span>
    </div>
    <p className="mt-0.5 break-all text-xs text-secondary-text">
      {`${displayModelName(record.model, text)} · ${text.input} ${formatNumber(record.promptTokens)} · ${text.output} ${formatNumber(record.completionTokens)}`}
    </p>
  </li>
);

const MobileEntry: React.FC<RecordRowsProps> = ({ entry, flat, expanded, onToggle, text, t }) => {
  if (entry.kind === 'single') return <MobileRecord record={entry.record} flat={flat} text={text} t={t} />;
  const first = entry.records[0];
  const count = entry.records.length;
  return (
    <>
      <li className="py-2 text-sm">
        <div className="flex items-baseline justify-between gap-3">
          <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
            <span className="tabular-nums text-secondary-text">{timeText(first.calledAt, flat)}</span>
            <span className="text-foreground">{getCallTypeLabel(first.callType, t, text)}</span>
            <StockLink code={first.stockCode} />
          </span>
          <span className="shrink-0 font-medium tabular-nums text-foreground">{formatNumber(entry.totalTokens)}</span>
        </div>
        <p className="mt-0.5 break-all text-xs text-secondary-text">
          {`${displayModelName(first.model, text)} · ${text.input} ${formatNumber(entry.promptTokens)} · ${text.output} ${formatNumber(entry.completionTokens)}`}
        </p>
        <button type="button" aria-expanded={expanded} className="mt-0.5 cursor-pointer text-xs text-cyan" onClick={() => onToggle(entry.id)}>
          {formatUiText(expanded ? text.collapseRounds : text.expandRounds, { count })}
        </button>
      </li>
      {expanded ? entry.records.map((record) => <MobileRecord key={record.id} record={record} flat={flat} text={text} t={t} nested />) : null}
    </>
  );
};

const TokenUsagePage: React.FC = () => {
  const { language, t } = useUiLanguage();
  const text = USAGE_TEXT[language];
  const [period, setPeriod] = useState<UsagePeriod>('month');
  const [callType, setCallType] = useState(ALL_TYPES);
  const [sort, setSort] = useState<UsageSort>('newest');
  const [day, setDay] = useState<string | null>(null);
  const [dashboard, setDashboard] = useState<UsageDashboard | null>(null);
  const [records, setRecords] = useState<UsageCallRecord[]>([]);
  const [expandedRounds, setExpandedRounds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const requestSeqRef = useRef(0);

  const query = useMemo(() => ({
    period,
    limit: PAGE_SIZE,
    callType: callType === ALL_TYPES ? undefined : callType,
    sort,
    day: day ?? undefined,
  }), [callType, day, period, sort]);

  const loadDashboard = useCallback(async () => {
    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    try {
      const data = await usageApi.getDashboard(query);
      if (requestSeq !== requestSeqRef.current) {
        return;
      }
      setDashboard(data);
      setRecords(data.recentCalls);
    } catch (err) {
      if (requestSeq !== requestSeqRef.current) {
        return;
      }
      setError(buildParsedError(err, t));
    } finally {
      if (requestSeq === requestSeqRef.current) {
        setLoading(false);
      }
    }
  }, [query, t]);

  useEffect(() => {
    void loadDashboard();
    return () => {
      requestSeqRef.current += 1;
    };
  }, [loadDashboard]);

  const loadMore = async () => {
    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;
    setLoadingMore(true);
    setError(null);
    try {
      const data = await usageApi.getDashboard({ ...query, offset: records.length });
      if (requestSeq !== requestSeqRef.current) return;
      // 載入期間有新呼叫時分頁會位移，同一筆可能再出現一次。
      setRecords((current) => {
        const seen = new Set(current.map((record) => record.id));
        return [...current, ...data.recentCalls.filter((record) => !seen.has(record.id))];
      });
      setDashboard((current) => (current ? { ...current, recentTotal: data.recentTotal } : current));
    } catch (err) {
      if (requestSeq === requestSeqRef.current) setError(buildParsedError(err, t));
    } finally {
      if (requestSeq === requestSeqRef.current) setLoadingMore(false);
    }
  };

  const handlePeriodChange = (next: UsagePeriod) => {
    setPeriod(next);
    // 日期與用途是上一段期間的選項，留著會篩成空表。
    setDay(null);
    setCallType(ALL_TYPES);
  };

  const toggleRound = (id: string) => setExpandedRounds((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });

  const groups = useMemo(() => groupRecords(records, sort), [records, sort]);
  const flat = sort === 'tokens';
  const typeOptions = [
    { value: ALL_TYPES, label: text.filterAll },
    ...(dashboard?.byCallType ?? []).map((item) => ({ value: item.callType, label: getCallTypeLabel(item.callType, t, text) })),
  ];
  const sortOptions: Array<{ value: UsageSort; label: string }> = [
    { value: 'newest', label: text.sortNewest },
    { value: 'oldest', label: text.sortOldest },
    { value: 'tokens', label: text.sortTokens },
  ];

  return (
    <AppPage>
      <div className="space-y-4">
        <PageHeader
          title={t('usage.title')}
          actions={(
            <>
              <Segmented
                aria-label={t('usage.title')}
                size="sm"
                value={period}
                onChange={handlePeriodChange}
                options={PERIOD_OPTIONS.map((option) => ({ value: option, label: t(PERIOD_LABEL_KEYS[option]) }))}
              />
              <Button size="sm" variant="secondary" disabled={loading} onClick={() => void loadDashboard()}>
                <RefreshCw className={cn('h-4 w-4', loading ? 'animate-spin' : '')} />
                {t('usage.refresh')}
              </Button>
            </>
          )}
        />

        {error ? <ApiErrorAlert error={error} actionLabel={t('common.retry')} onAction={() => void loadDashboard()} /> : null}

        {loading && !dashboard ? (
          <div data-testid="usage-loading"><Loading label={text.loading} /></div>
        ) : null}

        {dashboard && dashboard.totalCalls === 0 ? (
          <EmptyState title={t('usage.emptyTitle')} description={t('usage.emptyDescription')} />
        ) : null}

        {dashboard && dashboard.totalCalls > 0 ? (
          <>
            <UsageSummaryBand dashboard={dashboard} period={dashboard.period} text={text} t={t} />

            <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
              <DailyBars days={dashboard.byDay} fromDate={dashboard.fromDate} toDate={dashboard.toDate} selected={day} onSelect={setDay} text={text} />
              <CallTypeShare dashboard={dashboard} text={text} t={t} />
            </div>

            <ModelTable dashboard={dashboard} text={text} />

            <Card title={text.recordsTitle} subtitle={formatUiText(text.recordsCount, { count: formatNumber(dashboard.recentTotal) })} variant="surface" padding="md">
              <div className="mb-3 grid grid-cols-2 gap-3 md:max-w-md">
                <Select label={text.filterType} value={callType} options={typeOptions} onChange={setCallType} />
                <Select label={text.filterSort} value={sort} options={sortOptions} onChange={(value) => setSort(value as UsageSort)} />
              </div>
              {day ? (
                <p className="mb-3 flex flex-wrap items-center gap-2 text-xs text-secondary-text">
                  <span>{formatUiText(text.dayChip, { date: day })}</span>
                  <button type="button" className="cursor-pointer text-cyan hover:underline" onClick={() => setDay(null)}>{text.clearDay}</button>
                </p>
              ) : null}

              {groups.length === 0 ? (
                <p className="py-6 text-center text-sm text-secondary-text">{text.noRecords}</p>
              ) : (
                <>
                  <div className="hidden overflow-x-auto md:block" data-testid="usage-records-desktop">
                    <table className="w-full border-collapse text-sm" aria-label={text.recordsTitle}>
                      <thead>
                        <tr className="border-b border-border/60 text-xs text-secondary-text">
                          <th scope="col" className="px-3 py-2 text-left font-medium">{text.time}</th>
                          <th scope="col" className="px-3 py-2 text-left font-medium">{text.type}</th>
                          <th scope="col" className="px-3 py-2 text-left font-medium">{text.stock}</th>
                          <th scope="col" className="px-3 py-2 text-left font-medium">{text.model}</th>
                          <th scope="col" className="px-3 py-2 text-right font-medium">{text.input}</th>
                          <th scope="col" className="px-3 py-2 text-right font-medium">{text.output}</th>
                          <th scope="col" className="px-3 py-2 text-right font-medium">{text.total}</th>
                        </tr>
                      </thead>
                      {groups.map((group) => (
                        <tbody key={group.day ?? 'flat'}>
                          {group.day ? (
                            <tr>
                              <th scope="rowgroup" colSpan={7} className="bg-elevated/50 px-3 py-1.5 text-left text-xs font-medium tabular-nums text-secondary-text">{group.day}</th>
                            </tr>
                          ) : null}
                          {group.entries.map((entry) => (
                            <DesktopEntry key={entry.id} entry={entry} flat={flat} expanded={expandedRounds.has(entry.id)} onToggle={toggleRound} text={text} t={t} />
                          ))}
                        </tbody>
                      ))}
                    </table>
                  </div>
                  <div className="md:hidden" data-testid="usage-records-mobile">
                    {groups.map((group) => (
                      <section key={group.day ?? 'flat'}>
                        {group.day ? <h3 className="bg-elevated/50 px-2 py-1 text-xs font-medium tabular-nums text-secondary-text">{group.day}</h3> : null}
                        <ul className="divide-y divide-border/40">
                          {group.entries.map((entry) => (
                            <MobileEntry key={entry.id} entry={entry} flat={flat} expanded={expandedRounds.has(entry.id)} onToggle={toggleRound} text={text} t={t} />
                          ))}
                        </ul>
                      </section>
                    ))}
                  </div>
                </>
              )}

              {records.length < dashboard.recentTotal ? (
                <div className="mt-4 flex justify-center">
                  <Button variant="secondary" size="sm" isLoading={loadingMore} onClick={() => void loadMore()}>{text.loadMore}</Button>
                </div>
              ) : null}
            </Card>
          </>
        ) : null}
      </div>
    </AppPage>
  );
};

export default TokenUsagePage;
