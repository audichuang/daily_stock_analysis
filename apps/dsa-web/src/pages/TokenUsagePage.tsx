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
import { ApiErrorAlert, AppPage, Button, Card, DataTable, EmptyState, PageHeader, Segmented, Select, type DataTableColumn } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { formatUiText, type UiTextKey, type UiTextParams } from '../i18n/uiText';
import { USAGE_TEXT, type UsageText } from '../locales/usageText';
import { cn } from '../utils/cn';
import { formatMoneyValue, formatNumber, formatPercent, NO_VALUE } from '../utils/format';
import { groupRecords, mergeModels, modelDisplayName, sharePercents, type MergedModel, type RecordEntry } from '../utils/usageSummary';

type Translate = (key: UiTextKey, params?: UiTextParams) => string;

const PAGE_SIZE = 50;
const MAX_DAY_BARS = 60;
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
  return text.callTypes[callType] ?? t('usage.callType.unknown', { type: callType || NO_VALUE });
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

  let costLine: string;
  if (cost.estimatedTotal != null) {
    costLine = formatCost(cost.estimatedTotal, cost.currency);
    if (!cost.complete) costLine += `（${text.costPartial}）`;
  } else {
    costLine = cost.subscriptionTokens > 0 && cost.complete ? text.costSubscription : text.costUnpriced;
  }

  const changeLabel = period === 'today' ? text.changeToday : text.changeMonth;
  const stats = [
    { label: text.metricCalls, value: formatNumber(dashboard.totalCalls) },
    { label: text.metricInOut, value: `${formatNumber(dashboard.totalPromptTokens)} / ${formatNumber(dashboard.totalCompletionTokens)}` },
    { label: text.metricCache, value: cache.hitRatio == null ? NO_VALUE : `${formatNumber(cache.hitRatio * 100, 1)}%` },
  ];

  return (
    <Card variant="bordered" padding="md">
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" data-testid="usage-summary">
        <div className="min-w-0">
          <p className="text-xs text-secondary-text">{text.totalLabel}</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums text-foreground" data-testid="usage-total">{formatNumber(dashboard.totalTokens)}</p>
          <p className="mt-2 text-sm text-foreground">
            <span className="text-secondary-text">{`${text.costLabel} `}</span>
            <span className="tabular-nums" data-testid="usage-cost">{costLine}</span>
          </p>
          {cost.estimatedTotal != null && cost.subscriptionTokens > 0 ? (
            <p className="mt-1 text-xs text-secondary-text">{formatUiText(text.subscriptionNote, { tokens: formatNumber(cost.subscriptionTokens) })}</p>
          ) : null}
          {previous ? (
            <p className="mt-1 text-xs text-secondary-text" data-testid="usage-change">
              {`${changeLabel} `}
              <span className="tabular-nums">{previous.tokensChangePct == null ? text.noPrevious : formatPercent(previous.tokensChangePct, 1)}</span>
            </p>
          ) : null}
          <p className="mt-2 text-sm text-secondary-text">{sentence}</p>
        </div>
        <dl className="grid grid-cols-3 gap-2 self-start">
          {stats.map((stat) => (
            <div key={stat.label} className="min-w-0 rounded-lg border border-border/60 px-2 py-2 sm:px-3">
              <dt className="text-xs text-secondary-text">{stat.label}</dt>
              <dd className="mt-1 break-words text-sm font-medium tabular-nums text-foreground">{stat.value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </Card>
  );
};

const DailyBars: React.FC<{ days: UsageDayBreakdown[]; selected: string | null; onSelect: (day: string | null) => void; text: UsageText }> = ({ days, selected, onSelect, text }) => {
  const shown = days.slice(-MAX_DAY_BARS);
  const max = Math.max(...shown.map((day) => day.totalTokens), 1);
  return (
    <Card title={text.dailyTitle} subtitle={text.dailyHint} variant="bordered" padding="md">
      <div className="mb-2 flex items-center gap-3 text-xs text-secondary-text">
        <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-cyan" aria-hidden="true" />{text.input}</span>
        <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-cyan/40" aria-hidden="true" />{text.output}</span>
      </div>
      <div className="flex h-32 items-end gap-[2px]" data-testid="usage-daily-bars">
        {shown.map((day) => {
          const label = formatUiText(text.dayBar, {
            date: day.date,
            total: formatNumber(day.totalTokens),
            input: formatNumber(day.promptTokens),
            output: formatNumber(day.completionTokens),
          });
          const isSelected = selected === day.date;
          return (
            <button
              key={day.date}
              type="button"
              aria-label={label}
              aria-pressed={isSelected}
              onClick={() => onSelect(isSelected ? null : day.date)}
              className={cn(
                'flex h-full min-w-0 max-w-12 flex-1 cursor-pointer flex-col justify-end gap-[2px] rounded-t hover:bg-hover',
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
      {shown.length > 1 ? (
        <div className="mt-1 flex justify-between text-xs tabular-nums text-muted-text">
          <span>{shown[0].date.slice(5)}</span>
          <span>{shown[shown.length - 1].date.slice(5)}</span>
        </div>
      ) : null}
    </Card>
  );
};

const CallTypeShare: React.FC<{ dashboard: UsageDashboard; text: UsageText; t: Translate }> = ({ dashboard, text, t }) => {
  const shares = sharePercents(dashboard.byCallType.map((item) => item.totalTokens));
  return (
    <Card title={text.shareTitle} variant="bordered" padding="md">
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
  const columns: DataTableColumn<MergedModel>[] = [
    { key: 'name', header: text.model, priority: 'primary', render: (row) => <span className="break-all text-foreground">{row.name}</span> },
    { key: 'calls', header: text.calls, numeric: true, render: (row) => formatNumber(row.calls) },
    { key: 'input', header: text.input, numeric: true, render: (row) => formatNumber(row.promptTokens) },
    { key: 'output', header: text.output, numeric: true, render: (row) => formatNumber(row.completionTokens) },
    { key: 'total', header: text.total, numeric: true, priority: 'primary', render: (row) => <span className="font-medium text-foreground">{formatNumber(row.totalTokens)}</span> },
    { key: 'peak', header: text.peak, numeric: true, render: (row) => formatNumber(row.maxTotalTokens) },
    { key: 'cost', header: text.cost, numeric: true, render: costCell },
  ];
  return (
    <Card title={text.modelTitle} variant="bordered" padding="md">
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
    <td className="max-w-[18rem] truncate px-3 py-2 text-secondary-text" title={record.model}>{modelDisplayName(record.model)}</td>
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
        <td className="max-w-[18rem] truncate px-3 py-2 text-secondary-text" title={first.model}>{modelDisplayName(first.model)}</td>
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
      {`${modelDisplayName(record.model)} · ${text.input} ${formatNumber(record.promptTokens)} · ${text.output} ${formatNumber(record.completionTokens)}`}
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
          {`${modelDisplayName(first.model)} · ${text.input} ${formatNumber(entry.promptTokens)} · ${text.output} ${formatNumber(entry.completionTokens)}`}
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
          <div className="h-40 animate-pulse rounded-2xl border border-border/70 bg-card/60" data-testid="usage-loading" />
        ) : null}

        {dashboard && dashboard.totalCalls === 0 ? (
          <EmptyState title={t('usage.emptyTitle')} description={t('usage.emptyDescription')} />
        ) : null}

        {dashboard && dashboard.totalCalls > 0 ? (
          <>
            <UsageSummaryBand dashboard={dashboard} period={dashboard.period} text={text} t={t} />

            <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
              <DailyBars days={dashboard.byDay} selected={day} onSelect={setDay} text={text} />
              <CallTypeShare dashboard={dashboard} text={text} t={t} />
            </div>

            <ModelTable dashboard={dashboard} text={text} />

            <Card title={text.recordsTitle} subtitle={formatUiText(text.recordsCount, { count: formatNumber(dashboard.recentTotal) })} variant="bordered" padding="md">
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
