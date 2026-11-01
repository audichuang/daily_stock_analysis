import type React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { stocksApi } from '../../api/stocks';
import { getParsedApiError } from '../../api/error';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type {
  FinancialCommentary,
  FinancialHighlight,
  FinancialMetric,
  FinancialPeriod,
  StockFinancials,
} from '../../types/financials';
import { cn } from '../../utils/cn';
import { formatFinancialAmount, formatChange, formatMetricValue, qoqOf, yoyOf } from '../../utils/financialFormat';
import { Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';

const AI_BADGE = 'inline-flex shrink-0 items-center rounded-full border border-cyan/40 bg-cyan/10 px-2 py-0.5 text-xs font-medium text-cyan';

const HighlightNote: React.FC<{ highlight: FinancialHighlight }> = ({ highlight }) => {
  const { t } = useUiLanguage();
  return (
    <div className="space-y-2 rounded-lg border border-cyan/30 bg-cyan/5 p-3 text-sm leading-6" data-testid="financials-highlight">
      <p className="text-foreground">
        <span className="font-medium">{t('financials.whatHappened')}：</span>{highlight.whatHappened}
      </p>
      <p className="text-secondary-text">
        <span className="font-medium text-foreground">{t('financials.whyItMatters')}：</span>{highlight.whyItMatters}
      </p>
      <p className="text-secondary-text">
        <span className="font-medium text-foreground">{t('financials.howToRead')}：</span>{highlight.howToRead}
      </p>
    </div>
  );
};

/** 走勢縮圖：比率與金額同一畫法；負值向下，顏色不用紅綠（紅綠只給漲跌與損益）。 */
const MiniBars: React.FC<{ values: Array<number | null> }> = ({ values }) => {
  const peak = Math.max(...values.map((value) => Math.abs(value ?? 0)), 0);
  if (!peak) return null;
  return (
    <div className="flex h-8 w-20 shrink-0 items-center gap-0.5" aria-hidden="true">
      {values.map((value, index) => {
        const ratio = Math.abs(value ?? 0) / peak;
        return (
          <div key={index} className="flex h-full flex-1 flex-col justify-center">
            <div className="flex h-1/2 items-end">
              {value != null && value >= 0 ? (
                <div className={cn('w-full rounded-t-sm', index === values.length - 1 ? 'bg-cyan' : 'bg-secondary-text/40')} style={{ height: `${Math.max(ratio * 100, 4)}%` }} />
              ) : null}
            </div>
            <div className="flex h-1/2 items-start">
              {value != null && value < 0 ? (
                <div className={cn('w-full rounded-b-sm', index === values.length - 1 ? 'bg-cyan' : 'bg-secondary-text/40')} style={{ height: `${Math.max(ratio * 100, 4)}%` }} />
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
};

const MetricRow: React.FC<{
  metric: FinancialMetric;
  periods: FinancialPeriod[];
  currency?: string | null;
  highlights: FinancialHighlight[];
}> = ({ metric, periods, currency, highlights }) => {
  const { t } = useUiLanguage();
  const [open, setOpen] = useState(false);
  const latest = metric.points[metric.points.length - 1];
  const flagged = highlights.length > 0;
  const labelOf = (key: string) => periods.find((period) => period.key === key)?.label ?? key;
  return (
    <div className={cn('home-subpanel min-w-0', flagged && 'border-l-2 border-l-cyan')} data-testid={`financials-metric-${metric.key}`}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full min-w-0 items-center gap-3 p-3 text-left"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-medium text-foreground">{metric.label}</span>
            {flagged ? <span className={AI_BADGE}>{t('financials.aiFlag')}</span> : null}
          </div>
          <p className="mt-0.5 text-base font-semibold tabular-nums text-foreground">
            {formatMetricValue(metric, latest?.value, currency)}
          </p>
          <p className="text-xs tabular-nums text-secondary-text">
            {t('financials.yoy')} {latest ? yoyOf(metric, latest) : '—'} · {t('financials.qoq')} {latest ? qoqOf(metric, latest) : '—'}
          </p>
        </div>
        <MiniBars values={metric.points.map((point) => point.value)} />
        <span className={cn('text-secondary-text transition-transform', open && 'rotate-90')} aria-hidden="true">›</span>
      </button>
      {open ? (
        <div className="space-y-3 px-3 pb-3">
          {highlights.map((highlight) => (
            <HighlightNote key={`${highlight.metricKey}-${highlight.period}`} highlight={highlight} />
          ))}
          <p className="text-xs leading-5 text-secondary-text">
            <span className="font-medium text-foreground">{t('financials.basics')}：</span>{metric.definition}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[17rem] text-xs tabular-nums">
              <thead>
                <tr className="text-secondary-text">
                  <th className="py-1 pr-2 text-left font-normal">{t('financials.period')}</th>
                  <th className="py-1 pr-2 text-right font-normal">{t('financials.value')}</th>
                  <th className="py-1 text-right font-normal">{t('financials.yoy')}</th>
                </tr>
              </thead>
              <tbody>
                {[...metric.points].reverse().map((point) => (
                  <tr key={point.period} className="border-t border-border/40">
                    <td className="py-1 pr-2 text-left text-secondary-text">{labelOf(point.period)}</td>
                    <td className="py-1 pr-2 text-right text-foreground">
                      {formatMetricValue(metric, point.value, currency)}
                      {point.derived ? <span className="ml-1 text-xs text-secondary-text">{t('financials.derived')}</span> : null}
                    </td>
                    <td className="py-1 text-right text-secondary-text">{yoyOf(metric, point)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
};

const MonthlyRevenue: React.FC<{ data: StockFinancials; highlights: FinancialHighlight[] }> = ({ data, highlights }) => {
  const { t } = useUiLanguage();
  const recent = [...data.monthlyRevenue].slice(-6).reverse();
  if (!recent.length) return null;
  return (
    <div className={cn('home-subpanel min-w-0 p-3', highlights.length > 0 && 'border-l-2 border-l-cyan')} data-testid="financials-monthly">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <span className="text-sm font-medium text-foreground">{t('financials.monthly')}</span>
        {highlights.length > 0 ? <span className={AI_BADGE}>{t('financials.aiFlag')}</span> : null}
        {data.ttmRevenueYoyPct != null ? (
          <span className="text-xs tabular-nums text-secondary-text">{t('financials.ttmYoy')} {formatChange(data.ttmRevenueYoyPct)}</span>
        ) : null}
      </div>
      {highlights.map((highlight) => (
        <div className="mb-2" key={highlight.period}><HighlightNote highlight={highlight} /></div>
      ))}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[17rem] text-xs tabular-nums">
          <thead>
            <tr className="text-secondary-text">
              <th className="py-1 pr-2 text-left font-normal">{t('financials.month')}</th>
              <th className="py-1 pr-2 text-right font-normal">{t('financials.value')}</th>
              <th className="py-1 pr-2 text-right font-normal">{t('financials.yoy')}</th>
              <th className="py-1 text-right font-normal">{t('financials.mom')}</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((row) => (
              <tr key={row.month} className="border-t border-border/40">
                <td className="py-1 pr-2 text-left text-secondary-text">{row.month}</td>
                <td className="py-1 pr-2 text-right text-foreground">{formatFinancialAmount(row.revenue, data.currency)}</td>
                <td className="py-1 pr-2 text-right text-secondary-text">{formatChange(row.yoyPct)}</td>
                <td className="py-1 text-right text-secondary-text">{formatChange(row.momPct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

/**
 * 個股財報：數字先出，AI 導讀到了再補上。導讀失敗或關閉時，數字與固定教學照常顯示。
 */
export const FinancialsPanel: React.FC<{ stockCode: string }> = ({ stockCode }) => {
  const { t } = useUiLanguage();
  // 狀態全部綁請求的代號：切股後不符的舊值一律不顯示，A 的數字不會留在 B 的報告下。
  const [loaded, setLoaded] = useState<{ code: string; data: StockFinancials | null; error: string | null } | null>(null);
  const [commentaryState, setCommentaryState] = useState<{ code: string; value: FinancialCommentary } | null>(null);
  const [generatingCode, setGeneratingCode] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    stocksApi.getFinancials(stockCode).then(
      (payload) => {
        if (cancelled) return;
        setLoaded({ code: stockCode, data: payload, error: null });
        setCommentaryState({ code: stockCode, value: payload.commentary });
        if (payload.status === 'ok' && payload.commentary.status === 'missing') {
          setGeneratingCode(stockCode);
          stocksApi.ensureFinancialCommentary(stockCode).then(
            (result) => { if (!cancelled) setCommentaryState({ code: stockCode, value: result }); },
            () => { if (!cancelled) setCommentaryState({ code: stockCode, value: { status: 'failed', highlights: [], message: null } }); },
          ).finally(() => { if (!cancelled) setGeneratingCode(null); });
        }
      },
      (err) => {
        if (cancelled) return;
        setLoaded({ code: stockCode, data: null, error: getParsedApiError(err).message });
      },
    );
    return () => { cancelled = true; };
  }, [stockCode]);

  const stale = loaded?.code !== stockCode;
  const current = stale ? null : loaded.data;
  const error = stale ? null : loaded.error;
  const commentary = commentaryState?.code === stockCode ? commentaryState.value : null;
  const generating = generatingCode === stockCode;

  const highlightsByMetric = useMemo(() => {
    const map = new Map<string, FinancialHighlight[]>();
    for (const highlight of commentary?.highlights ?? []) {
      map.set(highlight.metricKey, [...(map.get(highlight.metricKey) ?? []), highlight]);
    }
    return map;
  }, [commentary]);

  // 非台美市場不支援：整塊不佔版面。
  if (current?.status === 'unsupported') return null;
  const latest = current?.periods[current.periods.length - 1];
  const showCommentary = commentary?.status === 'ready' && commentary.headline;

  return (
    <Card variant="bordered" padding="md" className="home-panel-card min-w-0" data-testid="financials-panel">
      <DashboardPanelHeader
        eyebrow={t('financials.title')}
        title={latest ? t('financials.latest', { period: latest.label, end: latest.periodEnd }) : t('financials.title')}
        className="mb-3"
      />
      {stale ? <p className="text-sm text-secondary-text" role="status">{t('financials.loading')}</p> : null}
      {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
      {current && current.status !== 'ok' ? (
        <p className="text-sm leading-6 text-secondary-text" data-testid="financials-status">{current.statusReason}</p>
      ) : null}
      {current?.status === 'ok' ? (
        <div className="min-w-0 space-y-3">
          <p className="text-xs leading-5 text-secondary-text" data-testid="financials-source">
            {t('financials.reportedIn', { currency: current.currency ?? '—' })}
            {current.source ? ` · ${current.source.label}` : ''}
            {latest?.announceDate
              ? ` · ${latest.announceDateKind === 'filed' ? t('financials.filedOn') : t('financials.deadlineOn')} ${latest.announceDate}`
              : ''}
          </p>
          {showCommentary ? (
            <div className="rounded-lg border border-cyan/30 bg-cyan/5 p-3" data-testid="financials-headline">
              <span className={AI_BADGE}>{t('financials.aiGuide')}</span>
              <p className="mt-2 text-sm font-medium leading-6 text-foreground">{commentary.headline}</p>
              <p className="mt-1 text-xs text-secondary-text">{t('financials.tapHint')}</p>
            </div>
          ) : null}
          {generating ? <p className="text-xs text-secondary-text" role="status">{t('financials.generating')}</p> : null}
          {commentary?.status === 'failed' ? (
            <p className="text-xs text-secondary-text" role="note">{commentary.message ?? t('financials.commentaryFailed')}</p>
          ) : null}
          <div className="grid min-w-0 gap-2 md:grid-cols-2">
            {current.metrics.map((metric) => (
              <MetricRow
                key={`${stockCode}-${metric.key}`}
                metric={metric}
                periods={current.periods}
                currency={current.currency}
                highlights={highlightsByMetric.get(metric.key) ?? []}
              />
            ))}
          </div>
          <MonthlyRevenue data={current} highlights={highlightsByMetric.get('monthly_revenue') ?? []} />
          {current.notApplicable.length > 0 ? (
            <details className="text-xs leading-5 text-secondary-text">
              <summary className="cursor-pointer">{t('financials.hidden', { count: current.notApplicable.length })}</summary>
              <ul className="mt-1 list-disc space-y-1 pl-4">
                {current.notApplicable.map((item) => (
                  <li key={item.key}>{item.label}：{item.reason}</li>
                ))}
              </ul>
            </details>
          ) : null}
          {current.limitations.length > 0 ? (
            <ul className={cn('space-y-1 text-xs leading-5', current.isStale ? 'text-warning' : 'text-secondary-text')} data-testid="financials-limitations">
              {current.limitations.map((text) => <li key={text}>{text}</li>)}
            </ul>
          ) : null}
          <p className="text-xs text-secondary-text">{t('financials.disclaimer')}</p>
        </div>
      ) : null}
    </Card>
  );
};
