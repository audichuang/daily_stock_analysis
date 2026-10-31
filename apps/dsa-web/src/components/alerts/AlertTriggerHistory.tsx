import type React from 'react';
import { Button, Card, Loading } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { formatUiText, type UiLanguage } from '../../i18n/uiText';
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
  onTabChange,
  onLoadMore,
  className,
}) => {
  const { language } = useUiLanguage();
  const text = ALERT_PAGE_TEXT[language];
  const tabs: Array<{ id: AlertActivityTab; label: string; count?: number }> = [
    { id: 'triggered', label: text.tabTriggered, count: triggeredCount },
    { id: 'issues', label: text.tabIssues, count: issueCount },
  ];

  return (
    <Card title={text.activityTitle} variant="bordered" padding="md" className={className}>
      <div role="tablist" className="mb-3 flex gap-2">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={`rounded-full border px-3 py-1 text-xs ${tab === item.id ? 'border-primary text-foreground' : 'border-border/60 text-secondary-text'}`}
            onClick={() => onTabChange?.(item.id)}
          >
            {item.count == null ? item.label : `${item.label} ${item.count}`}
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
                <p className="text-xs text-secondary-text">{trigger.ruleName || trigger.reason || trigger.diagnostics || '--'}</p>
                {facts.length ? <p className="text-xs text-secondary-text">{facts.join(' · ')}</p> : null}
                <p className="text-xs text-muted-text">{formatDateTime(trigger.triggeredAt ?? trigger.dataTimestamp)}</p>
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
