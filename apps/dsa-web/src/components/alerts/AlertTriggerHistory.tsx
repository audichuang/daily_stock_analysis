import type React from 'react';
import { Button, Card, Loading } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { formatUiText, type UiLanguage } from '../../i18n/uiText';
import { ALERTS_TEXT } from '../../locales/alertsText';
import { ALERT_PAGE_TEXT, ALERT_SEVERITY_LABELS } from '../../locales/featureText';
import type { AlertTriggerItem } from '../../types/alerts';
import { formatDateTime } from '../../utils/format';

export type AlertActivityTab = 'triggered' | 'issues';
type PageText = (typeof ALERT_PAGE_TEXT)[UiLanguage];

// 已觸發依嚴重度著色，異常依狀態著色，一眼分得出要不要處理。
function dotClass(trigger: AlertTriggerItem): string {
  if (trigger.status === 'failed') return 'bg-danger';
  if (trigger.status === 'degraded') return 'bg-warning';
  if (trigger.status === 'skipped') return 'bg-muted-text';
  if (trigger.severity === 'critical') return 'bg-danger';
  if (trigger.severity === 'info') return 'bg-primary';
  return 'bg-warning';
}

function statusLabel(status: string, text: PageText): string {
  if (status === 'failed') return text.statusFailed;
  if (status === 'degraded') return text.statusDegraded;
  if (status === 'skipped') return text.statusSkipped;
  if (status === 'triggered') return text.statusTriggered;
  return status;
}

function sourceLabel(source: string, text: PageText): string {
  if (source === 'shioaji') return text.sourceShioaji;
  if (source === 'yfinance') return text.sourceYfinance;
  if (source === 'fallback') return text.sourceFallback;
  return source;
}

interface AlertTriggerHistoryProps {
  triggers: AlertTriggerItem[];
  total?: number;
  isLoading?: boolean;
  tab?: AlertActivityTab;
  triggeredCount?: number;
  issueCount?: number;
  /** Skipped rows are listed under issues but not counted as issues; shown as a separate muted count. */
  skippedCount?: number;
  onTabChange?: (tab: AlertActivityTab) => void;
  onLoadMore?: () => void;
  className?: string;
}

export const AlertTriggerHistory: React.FC<AlertTriggerHistoryProps> = ({
  triggers,
  total = 0,
  isLoading = false,
  tab = 'triggered',
  triggeredCount,
  issueCount,
  skippedCount,
  onTabChange,
  onLoadMore,
  className,
}) => {
  const { language } = useUiLanguage();
  const text = ALERT_PAGE_TEXT[language];
  const alertsText = ALERTS_TEXT[language];
  const tabs: Array<{ id: AlertActivityTab; label: string; count?: number; extra?: string }> = [
    { id: 'triggered', label: text.tabTriggered, count: triggeredCount },
    {
      id: 'issues',
      label: text.tabIssues,
      count: issueCount,
      extra: skippedCount ? formatUiText(alertsText.skippedHint, { count: skippedCount }) : undefined,
    },
  ];

  return (
    <Card variant="surface" padding="md" className={className}>
      {/* Phones already show 動態 as the page tab; repeating it as a heading would stack two titles. */}
      <h2 className="mb-3 hidden text-base font-semibold text-foreground lg:block">{text.activityTitle}</h2>
      <div role="tablist" aria-label={alertsText.activityTabs} className="mb-3 flex gap-4 border-b border-border/50">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={`-mb-px inline-flex h-7 items-center gap-1 border-b-2 text-xs ${tab === item.id ? 'border-primary font-medium text-foreground' : 'border-transparent text-secondary-text hover:text-foreground'}`}
            onClick={() => onTabChange?.(item.id)}
          >
            {item.count == null ? item.label : `${item.label} ${item.count}`}
            {item.extra ? <span className="text-muted-text">{`· ${item.extra}`}</span> : null}
          </button>
        ))}
      </div>

      {isLoading && triggers.length === 0 ? <Loading /> : null}
      {!isLoading && triggers.length === 0 ? (
        <p className="py-8 text-center text-sm text-secondary-text">{tab === 'triggered' ? text.noTriggered : text.noIssues}</p>
      ) : null}
      <ol className="space-y-3">
        {triggers.map((trigger) => {
          const facts: string[] = [];
          if (trigger.observedValue != null) facts.push(formatUiText(text.observed, { value: trigger.observedValue.toLocaleString() }));
          if (trigger.threshold != null) facts.push(formatUiText(text.threshold, { value: trigger.threshold.toLocaleString() }));
          if (trigger.quoteSource) facts.push(formatUiText(text.source, { source: sourceLabel(trigger.quoteSource, text) }));
          if (trigger.status === 'triggered' && trigger.severity) {
            facts.push(ALERT_SEVERITY_LABELS[language][trigger.severity] ?? String(trigger.severity));
          }
          return (
            <li key={trigger.id} className="flex gap-3" data-testid={`alert-trigger-${trigger.id}`}>
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${dotClass(trigger)}`} aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="break-words text-sm text-foreground">
                  {trigger.stockName ? `${trigger.stockName} ` : ''}
                  <span className="font-mono">{trigger.target}</span>
                  {' · '}
                  {statusLabel(trigger.status, text)}
                </p>
                {trigger.ruleName ? <p className="break-words text-xs text-secondary-text">{trigger.ruleName}</p> : null}
                {/* 異常的原因不能被規則名稱蓋掉；已觸發有名稱時原因只是機器字串，收進診斷。 */}
                {trigger.reason && (trigger.status !== 'triggered' || !trigger.ruleName) ? (
                  <p className="break-words text-xs text-secondary-text">{trigger.reason}</p>
                ) : null}
                {facts.length ? <p className="text-xs text-secondary-text">{facts.join(' · ')}</p> : null}
                <p className="text-xs text-muted-text">{formatDateTime(trigger.triggeredAt ?? trigger.dataTimestamp)}</p>
                {trigger.diagnostics ? (
                  <details className="mt-1 text-xs text-secondary-text">
                    <summary className="cursor-pointer">{text.viewDiagnostics}</summary>
                    <pre className="mt-1 whitespace-pre-wrap break-all font-mono text-muted-text">{trigger.diagnostics}</pre>
                  </details>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
      {triggers.length < total ? (
        <div className="mt-4 flex justify-center">
          <Button variant="secondary" size="sm" isLoading={isLoading} onClick={onLoadMore}>
            {text.loadMore}
          </Button>
        </div>
      ) : null}
    </Card>
  );
};
