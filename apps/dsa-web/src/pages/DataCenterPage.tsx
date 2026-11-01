import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Database, RefreshCw, Settings2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { dataCapabilityApi } from '../api/dataCapability';
import {
  AppPage, Badge, Button, Card, DataTable, EmptyState, InlineAlert, Loading, Metric, MetricGroup, PageHeader,
  type DataTableColumn,
} from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { formatUiText } from '../i18n/uiText';
import { DATA_CENTER_TEXT, type DataCenterText as Text } from '../locales/dataCenterText';
import type { DataCapabilityOverview, DataPriorityView, DataProviderCapability } from '../types/dataCapability';
import {
  buildConclusion,
  buildMarketRows,
  buildSystemRows,
  countBuckets,
  FOCUS_MARKETS,
  rowLabel,
  translateWarnings,
  type DataRow,
} from '../utils/dataCenterSummary';
import { formatDateTime, NO_VALUE } from '../utils/format';

function statusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'ok') return 'success';
  if (status === 'partial' || status === 'degraded' || status === 'stale') return 'warning';
  if (status === 'unavailable') return 'danger';
  return 'default';
}

const StatusBadge: React.FC<{ status: string; text: Text }> = ({ status, text }) => (
  <Badge variant={statusVariant(status)}>{text.status[status] ?? status}</Badge>
);

const Fold: React.FC<{ title: string; children: React.ReactNode; testId?: string }> = ({ title, children, testId }) => (
  <details className="rounded-xl border border-border/60 p-3 sm:p-4" data-testid={testId}>
    <summary className="cursor-pointer text-sm font-medium text-foreground">{title}</summary>
    <div className="mt-3">{children}</div>
  </details>
);

function dateText(row: DataRow, text: Text): string {
  if (!row.dataDate) return NO_VALUE;
  if (row.status === 'stale' && row.expectedDate) return formatUiText(text.dateBehind, { date: row.dataDate, expected: row.expectedDate });
  return row.dataDate;
}

function noteParts(row: DataRow, text: Text): string[] {
  const parts: string[] = [];
  if (row.reason) parts.push(text.reasons[row.reason] ?? row.reason);
  if (row.fallbackFrom.length > 0) {
    const sources = row.fallbackFrom.join('、');
    parts.push(row.source ? formatUiText(text.skipped, { sources, source: row.source }) : formatUiText(text.skippedNoSource, { sources }));
  }
  if (!row.dataDate && row.lastSuccess) parts.push(formatUiText(text.realtimeSuccess, { time: formatDateTime(row.lastSuccess) }));
  return parts;
}

const RowsTable: React.FC<{ rows: DataRow[]; text: Text; ariaLabel: string }> = ({ rows, text, ariaLabel }) => {
  const columns: DataTableColumn<DataRow>[] = [
    { key: 'data', header: text.colData, priority: 'primary', render: (row) => <span className="text-foreground">{rowLabel(row, text)}</span> },
    { key: 'status', header: text.colStatus, priority: 'primary', render: (row) => <StatusBadge status={row.status} text={text} /> },
    { key: 'source', header: text.colSource, render: (row) => row.source ?? NO_VALUE },
    { key: 'date', header: text.colDate, render: (row) => <span className="whitespace-nowrap tabular-nums">{dateText(row, text)}</span> },
    { key: 'note', header: text.colNote, render: (row) => <span className="break-words text-xs text-secondary-text">{noteParts(row, text).join('；') || NO_VALUE}</span> },
  ];
  return (
    <DataTable
      aria-label={ariaLabel}
      columns={columns}
      rows={rows}
      rowKey={(row) => row.id}
      density="compact"
      renderMobileCard={(row) => {
        const notes = noteParts(row, text);
        return (
          <div className="space-y-1 px-1 py-2 text-sm" data-testid={`data-row-mobile-${row.id}`}>
            <div className="flex items-center justify-between gap-3">
              <span className="min-w-0 break-words text-foreground">{rowLabel(row, text)}</span>
              <StatusBadge status={row.status} text={text} />
            </div>
            <p className="text-xs text-secondary-text">{[row.source, row.dataDate ? dateText(row, text) : null].filter(Boolean).join(' · ') || NO_VALUE}</p>
            {notes.length ? <p className="break-words text-xs text-secondary-text">{notes.join('；')}</p> : null}
          </div>
        );
      }}
    />
  );
};

const ProviderList: React.FC<{ title: string; providers: DataProviderCapability[]; text: Text }> = ({ title, providers, text }) => {
  if (providers.length === 0) return null;
  return (
    <section>
      <h3 className="mb-2 text-xs font-medium text-secondary-text">{`${title}（${providers.length}）`}</h3>
      <ul className="divide-y divide-border/40">
        {providers.map((provider) => {
          const { messages } = translateWarnings(provider.warnings, text);
          const markets = provider.markets.map((market) => text.markets[market] ?? market).join('、') || NO_VALUE;
          const datasets = provider.datasets.map((dataset) => text.datasets[dataset] ?? dataset).join('、') || NO_VALUE;
          return (
            <li key={provider.name} className="py-2 text-xs text-secondary-text">
              <div className="flex items-center justify-between gap-3">
                <span className="min-w-0 break-words text-sm text-foreground">{provider.label || provider.name}</span>
                <StatusBadge status={provider.status} text={text} />
              </div>
              <p className="mt-1 break-words">{formatUiText(text.providerMarkets, { markets })}</p>
              <p className="break-words">{formatUiText(text.providerDatasets, { datasets })}</p>
              {messages.length ? <p className="mt-1 break-words text-warning">{messages.join('；')}</p> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
};

const PriorityGroup: React.FC<{ title: string; priorities: DataPriorityView[]; text: Text }> = ({ title, priorities, text }) => {
  if (priorities.length === 0) return null;
  return (
    <section>
      <h3 className="mb-2 text-xs font-medium text-secondary-text">{title}</h3>
      <div className="grid gap-2 md:grid-cols-2">
        {priorities.map((priority) => (
          <div key={priority.scenario} className="min-w-0 rounded-lg border border-border/60 p-3" data-testid={`priority-${priority.scenario}`}>
            <div className="break-words text-sm font-medium text-foreground">{text.scenarios[priority.scenario] ?? priority.scenario}</div>
            {/* 來源名稱可能很長，逐項換行，不撐破卡片。 */}
            <div className="mt-1 flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs text-secondary-text">
              {priority.providers.length === 0 ? NO_VALUE : priority.providers.map((provider, index) => (
                <span key={provider} className="min-w-0 break-all">{index > 0 ? `→ ${provider}` : provider}</span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
};

const technicalLines = (overview: DataCapabilityOverview): string[] => [
  ...overview.warnings,
  ...overview.datasets.flatMap((dataset) => [
    ...dataset.warnings.map((code) => `${dataset.dataset}: ${code}`),
    ...(dataset.lastError ? [`${dataset.dataset}: ${dataset.lastError}`] : []),
  ]),
  ...overview.providers.flatMap((provider) => [
    ...provider.warnings.map((code) => `${provider.name}: ${code}`),
    ...(provider.lastError ? [`${provider.name}: ${provider.lastError}`] : []),
  ]),
  ...overview.priorities.map((priority) => `${priority.scenario}: ${priority.source}`),
];

const DataCenterPage: React.FC = () => {
  const { language, t } = useUiLanguage();
  const text = DATA_CENTER_TEXT[language];
  const [overview, setOverview] = useState<DataCapabilityOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const requestGeneration = useRef(0);

  useEffect(() => {
    document.title = `${t('dataCenter.title')} - DSA`;
  }, [t]);

  const load = useCallback(async () => {
    const generation = ++requestGeneration.current;
    setLoading(true);
    setError('');
    try {
      const nextOverview = await dataCapabilityApi.getOverview();
      if (generation !== requestGeneration.current) return;
      setOverview(nextOverview);
    } catch {
      if (generation !== requestGeneration.current) return;
      setOverview(null);
      setError(t('dataCenter.loadError'));
    } finally {
      if (generation === requestGeneration.current) setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
    return () => {
      requestGeneration.current += 1;
    };
  }, [load]);

  const view = useMemo(() => {
    if (!overview) return null;
    const marketRows = buildMarketRows(overview.datasets);
    return {
      focusRows: marketRows.filter((row) => row.root && FOCUS_MARKETS.includes(row.root)),
      otherRows: marketRows.filter((row) => !row.root || !FOCUS_MARKETS.includes(row.root)),
      systemRows: buildSystemRows(overview.datasets),
      counts: countBuckets(overview.datasets),
      conclusion: buildConclusion(marketRows, formatDateTime(overview.asOf), text),
      hints: translateWarnings(overview.warnings, text),
      technical: technicalLines(overview),
    };
  }, [overview, text]);

  const providers = overview?.providers ?? [];
  const priorities = overview?.priorities ?? [];
  const isEmpty = overview != null && overview.providers.length === 0 && overview.datasets.length === 0;
  const otherTitle = view ? formatUiText(text.otherMarkets, { count: view.otherRows.length }) : '';

  return (
    <AppPage className="space-y-4">
      <PageHeader
        title={t('dataCenter.title')}
        actions={(
          <>
            <Link
              to="/settings"
              className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-transparent px-3 text-sm font-medium text-secondary-text transition-all hover:bg-hover hover:text-foreground"
            >
              <Settings2 className="h-4 w-4" />{t('dataCenter.openSettings')}
            </Link>
            <Button size="sm" variant="secondary" isLoading={loading} loadingText={t('dataCenter.refreshing')} onClick={() => void load()}>
              <RefreshCw className="h-4 w-4" />{t('dataCenter.refresh')}
            </Button>
          </>
        )}
      />

      {error ? (
        <InlineAlert
          variant="danger"
          title={t('dataCenter.loadErrorTitle')}
          message={error}
          action={<Button size="sm" variant="secondary" onClick={() => void load()}>{t('common.retry')}</Button>}
        />
      ) : null}

      {loading && !overview ? <Loading label={t('dataCenter.loading')} /> : null}

      {!loading && !error && isEmpty ? (
        <EmptyState icon={<Database className="h-6 w-6" />} title={t('dataCenter.emptyTitle')} description={t('dataCenter.emptyDescription')} />
      ) : null}

      {overview && view && !isEmpty ? (
        <>
          <div data-testid="data-center-conclusion">
            <InlineAlert variant={view.conclusion.variant} title={view.conclusion.title} message={view.conclusion.message} />
          </div>

          <MetricGroup>
            <Metric label={text.countOk} value={view.counts.ok} hint={formatUiText(text.countNote, { total: overview.datasets.length })} />
            <Metric label={text.countUnchecked} value={view.counts.unchecked} />
            <Metric label={text.countOff} value={view.counts.off} />
            <Metric label={text.countIssue} value={view.counts.issue} tone={view.counts.issue > 0 ? 'warning' : 'default'} />
          </MetricGroup>

          <Card title={text.tableTitle} subtitle={formatDateTime(overview.asOf)} variant="bordered" padding="md">
            <RowsTable rows={view.focusRows} text={text} ariaLabel={text.tableTitle} />
          </Card>

          {view.otherRows.length > 0 ? (
            <Fold title={otherTitle} testId="data-center-other">
              <RowsTable rows={view.otherRows} text={text} ariaLabel={otherTitle} />
            </Fold>
          ) : null}

          {view.systemRows.length > 0 ? (
            <Card title={text.systemTitle} variant="bordered" padding="md">
              <RowsTable rows={view.systemRows} text={text} ariaLabel={text.systemTitle} />
            </Card>
          ) : null}

          {view.hints.messages.length > 0 || view.hints.unknownCount > 0 ? (
            <div data-testid="data-center-hints">
              <InlineAlert
                variant="warning"
                title={formatUiText(text.hintsTitle, { count: view.hints.messages.length + view.hints.unknownCount })}
                message={(
                  <>
                    {view.hints.messages.map((message) => <div key={message}>{message}</div>)}
                    {view.hints.unknownCount > 0 ? <div>{formatUiText(text.hintUnknown, { count: view.hints.unknownCount })}</div> : null}
                  </>
                )}
              />
            </div>
          ) : null}

          <Fold title={formatUiText(text.providersTitle, { count: providers.length })} testId="data-center-providers">
            <div className="space-y-4">
              <ProviderList title={text.providerUsable} providers={providers.filter((item) => item.status === 'ok')} text={text} />
              <ProviderList title={text.providerAttention} providers={providers.filter((item) => item.status !== 'ok' && item.status !== 'unconfigured')} text={text} />
              <ProviderList title={text.providerUnconfigured} providers={providers.filter((item) => item.status === 'unconfigured')} text={text} />
            </div>
          </Fold>

          <Fold title={text.prioritiesTitle} testId="data-center-priorities">
            {priorities.length === 0 ? <p className="text-sm text-secondary-text">{t('dataCenter.noPriorities')}</p> : (
              <div className="space-y-4">
                <PriorityGroup title={text.priorityTw} priorities={priorities.filter((item) => item.scenario.startsWith('tw.'))} text={text} />
                <PriorityGroup title={text.priorityUs} priorities={priorities.filter((item) => item.scenario.startsWith('us.'))} text={text} />
                <PriorityGroup title={text.priorityOther} priorities={priorities.filter((item) => !item.scenario.startsWith('tw.') && !item.scenario.startsWith('us.'))} text={text} />
              </div>
            )}
          </Fold>

          <Fold title={text.technicalTitle} testId="data-center-technical">
            {view.technical.length === 0 ? <p className="text-sm text-secondary-text">{text.technicalEmpty}</p> : (
              <pre className="whitespace-pre-wrap break-all font-mono text-xs text-muted-text">{view.technical.join('\n')}</pre>
            )}
          </Fold>
        </>
      ) : null}
    </AppPage>
  );
};

export default DataCenterPage;
