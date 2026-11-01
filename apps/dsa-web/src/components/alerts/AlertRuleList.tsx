import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { MoreHorizontal } from 'lucide-react';
import { Button, Card, ConfirmDialog, InlineAlert, Input, Select } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { formatUiText, type UiLanguage } from '../../i18n/uiText';
import {
  ALERT_ENABLED_FILTER_OPTIONS,
  ALERT_MARKET_REGION_LABELS,
  ALERT_PAGE_TEXT,
  ALERT_SCOPE_LABELS,
  ALERT_TYPE_FILTER_OPTIONS,
} from '../../locales/featureText';
import type {
  AlertRuleItem,
  AlertRuleTestResponse,
  AlertTargetScope,
  AlertType,
  MarketRegion,
} from '../../types/alerts';
import { formatDateTime, formatNumber, formatPercent } from '../../utils/format';
import { ruleCondition, summarizeDryRun, type AlertPageText } from './alertRuleText';

export type AlertRuleEnabledFilter = 'all' | 'enabled' | 'disabled';
export type AlertTypeFilter = 'all' | AlertType;
export type AlertScopeFilter = 'all' | AlertTargetScope;
export type AlertRuleBusyAction = 'test' | 'toggle' | 'delete';

export interface AlertRuleBusyState {
  id: number;
  action: AlertRuleBusyAction;
}

export interface AlertQuoteView {
  price: number;
  name?: string | null;
}

type PageText = AlertPageText;

function ruleTarget(rule: AlertRuleItem, language: UiLanguage, text: PageText, quote?: AlertQuoteView): string {
  if (rule.targetScope === 'market') return ALERT_MARKET_REGION_LABELS[language][rule.target as MarketRegion] ?? rule.target;
  if (rule.targetScope === 'watchlist') return text.watchlist;
  if (rule.targetScope === 'portfolio_holdings') return text.holdings;
  if (rule.targetScope === 'portfolio_account') {
    return rule.target === 'all' ? text.allAccounts : formatUiText(text.account, { target: rule.target });
  }
  return quote?.name ? `${quote.name} ${rule.target}` : rule.target;
}

function frequencyLabel(rule: AlertRuleItem, text: PageText): string {
  const seconds = (rule.cooldownPolicy as { cooldownSeconds?: unknown } | null | undefined)?.cooldownSeconds;
  if (typeof seconds !== 'number' || seconds === 86400) return text.daily;
  if (seconds === 3600) return text.hourly;
  return formatUiText(text.everyCustom, { minutes: Math.round(seconds / 60) });
}

function hasChildTargets(rule: AlertRuleItem): boolean {
  return rule.targetScope === 'watchlist' || rule.targetScope === 'portfolio_holdings';
}

const DryRunResult: React.FC<{ result: AlertRuleTestResponse; text: PageText; onClose: () => void }> = ({ result, text, onClose }) => {
  const { outcome, unableCount, unableTargets } = summarizeDryRun(result);
  const headline = {
    hit: text.dryRunHit,
    miss: text.dryRunMiss,
    unable: text.dryRunUnable,
    partial: text.dryRunPartial,
    error: text.dryRunError,
  }[outcome];
  const variant = { hit: 'success', miss: 'info', unable: 'warning', partial: 'warning', error: 'danger' } as const;
  const details: string[] = [text.dryRunNote];
  if (result.observedValue != null) details.push(formatUiText(text.dryRunObserved, { value: String(result.observedValue) }));
  if ((result.evaluatedCount ?? 0) > 1) {
    details.push(formatUiText(text.dryRunSummary, { evaluated: result.evaluatedCount ?? 0, triggered: result.triggeredCount ?? 0 }));
    if (unableCount > 0) details.push(formatUiText(text.dryRunUnableCount, { count: unableCount }));
  }
  // 聚合回應的 message 只是筆數摘要，真正原因在各標的。
  const reasons = unableTargets.length > 0
    ? unableTargets.map((item) => ((result.evaluatedCount ?? 0) > 1 ? `${item.displayTarget ?? item.target}：${item.message}` : item.message))
    : (outcome === 'unable' || outcome === 'error') ? [result.message] : [];
  return (
    <InlineAlert
      className="mt-3"
      title={headline}
      message={(
        <>
          <div>{details.join(' · ')}</div>
          {reasons.map((reason) => <div key={reason} className="break-words text-xs">{reason}</div>)}
        </>
      )}
      variant={variant[outcome]}
      action={(
        <button type="button" className="text-sm underline" onClick={onClose}>
          {text.dryRunClose}
        </button>
      )}
    />
  );
};

interface RuleCardProps {
  rule: AlertRuleItem;
  quote?: AlertQuoteView;
  busy: AlertRuleBusyState | null;
  testResult?: AlertRuleTestResponse;
  onToggleEnabled: (rule: AlertRuleItem) => void;
  onEdit: (rule: AlertRuleItem) => void;
  onTest: (rule: AlertRuleItem) => void;
  onDismissTest: (rule: AlertRuleItem) => void;
  onRequestDelete: (rule: AlertRuleItem) => void;
}

const RuleCard: React.FC<RuleCardProps> = ({
  rule, quote, busy, testResult, onToggleEnabled, onEdit, onTest, onDismissTest, onRequestDelete,
}) => {
  const { language } = useUiLanguage();
  const text = ALERT_PAGE_TEXT[language];
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const isBusy = busy?.id === rule.id;

  useEffect(() => {
    if (!menuOpen) return undefined;
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [menuOpen]);

  const threshold = rule.alertType === 'price_cross' ? rule.parameters.price : undefined;
  const distance = quote && quote.price > 0 && threshold
    ? formatPercent((threshold / quote.price - 1) * 100, 1)
    : null;
  const facts: string[] = [];
  if (rule.alertType === 'price_cross' && rule.targetScope === 'single_symbol') {
    facts.push(quote ? formatUiText(text.current, { price: formatNumber(quote.price) }) : text.noQuote);
    if (distance) facts.push(formatUiText(text.distance, { pct: distance }));
  }
  facts.push(rule.lastTriggeredAt ? formatUiText(text.lastTriggered, { time: formatDateTime(rule.lastTriggeredAt) }) : text.neverTriggered);
  if (rule.cooldownActive) facts.push(formatUiText(text.cooling, { time: formatDateTime(rule.cooldownUntil) }));
  if (hasChildTargets(rule)) facts.push(text.childCooldown);
  facts.push(frequencyLabel(rule, text));
  if (rule.source === 'tw_levels') facts.push(text.levelSource);

  return (
    <li className="rounded-xl border border-border/60 p-3 sm:p-4" data-testid={`alert-rule-${rule.id}`}>
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          role="switch"
          className="mt-1 h-4 w-4 shrink-0"
          aria-label={formatUiText(text.switchOn, { name: rule.name })}
          checked={rule.enabled}
          disabled={isBusy}
          onChange={() => onToggleEnabled(rule)}
        />
        <div className="min-w-0 flex-1">
          <p className={rule.enabled ? 'text-sm font-medium text-foreground' : 'text-sm font-medium text-muted-text'}>
            {`${text.whenPrefix} ${ruleTarget(rule, language, text, quote)} ${ruleCondition(rule, language, text)} ${text.remind}`.trim()}
          </p>
          <p className="mt-1 break-words text-xs text-secondary-text">{facts.join(' · ')}</p>
          <p className="mt-0.5 truncate text-xs text-muted-text">{rule.name}</p>
        </div>
        <div className="relative shrink-0" ref={menuRef}>
          <button
            type="button"
            aria-label={formatUiText(text.menu, { name: rule.name })}
            aria-expanded={menuOpen}
            className="rounded p-1 text-secondary-text hover:bg-hover"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
          </button>
          {menuOpen ? (
            <div role="menu" className="absolute right-0 z-20 mt-1 w-44 rounded-lg border border-border/60 bg-card p-1 shadow-lg">
              {[
                { label: text.edit, run: () => onEdit(rule) },
                { label: busy?.id === rule.id && busy.action === 'test' ? text.dryRunning : text.dryRun, run: () => onTest(rule) },
                { label: text.delete, run: () => onRequestDelete(rule), danger: true },
              ].map((item) => (
                <button
                  key={item.label}
                  type="button"
                  role="menuitem"
                  disabled={isBusy}
                  className={`block w-full rounded px-3 py-2 text-left text-sm hover:bg-hover ${item.danger ? 'text-danger' : 'text-foreground'}`}
                  onClick={() => {
                    setMenuOpen(false);
                    item.run();
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      {testResult ? <DryRunResult result={testResult} text={text} onClose={() => onDismissTest(rule)} /> : null}
    </li>
  );
};

interface AlertRuleListProps {
  rules: AlertRuleItem[];
  total: number;
  className?: string;
  isLoading?: boolean;
  hasFilters?: boolean;
  searchTarget: string;
  scopeFilter: AlertScopeFilter;
  enabledFilter: AlertRuleEnabledFilter;
  alertTypeFilter: AlertTypeFilter;
  quotes?: Record<string, AlertQuoteView>;
  testResults?: Record<number, AlertRuleTestResponse>;
  onSearchTargetChange: (value: string) => void;
  onScopeFilterChange: (value: AlertScopeFilter) => void;
  onEnabledFilterChange: (value: AlertRuleEnabledFilter) => void;
  onAlertTypeFilterChange: (value: AlertTypeFilter) => void;
  onLoadMore: () => void;
  onToggleEnabled: (rule: AlertRuleItem) => void;
  onEdit: (rule: AlertRuleItem) => void;
  onDelete: (rule: AlertRuleItem) => void;
  onTest: (rule: AlertRuleItem) => void;
  onDismissTest: (rule: AlertRuleItem) => void;
  guide?: React.ReactNode;
  busyRule?: AlertRuleBusyState | null;
}

export const AlertRuleList: React.FC<AlertRuleListProps> = ({
  rules,
  total,
  className,
  isLoading = false,
  hasFilters = false,
  searchTarget,
  scopeFilter,
  enabledFilter,
  alertTypeFilter,
  quotes = {},
  testResults = {},
  onSearchTargetChange,
  onScopeFilterChange,
  onEnabledFilterChange,
  onAlertTypeFilterChange,
  onLoadMore,
  onToggleEnabled,
  onEdit,
  onDelete,
  onTest,
  onDismissTest,
  guide,
  busyRule = null,
}) => {
  const { language } = useUiLanguage();
  const text = ALERT_PAGE_TEXT[language];
  const [pendingDelete, setPendingDelete] = useState<AlertRuleItem | null>(null);
  const scopeOptions = [
    { value: 'all', label: text.allGroups },
    ...Object.entries(ALERT_SCOPE_LABELS[language]).map(([value, label]) => ({ value, label })),
  ];

  return (
    <Card variant="surface" padding="md" className={className}>
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Input
          label={text.search}
          value={searchTarget}
          placeholder={text.searchPlaceholder}
          onChange={(event) => onSearchTargetChange(event.target.value)}
        />
        <Select
          label={text.group}
          value={scopeFilter}
          options={scopeOptions}
          onChange={(value) => onScopeFilterChange(value as AlertScopeFilter)}
        />
        <Select
          label={text.status}
          value={enabledFilter}
          options={ALERT_ENABLED_FILTER_OPTIONS[language]}
          onChange={(value) => onEnabledFilterChange(value as AlertRuleEnabledFilter)}
        />
        <Select
          label={text.type}
          value={alertTypeFilter}
          options={ALERT_TYPE_FILTER_OPTIONS[language]}
          onChange={(value) => onAlertTypeFilterChange(value as AlertTypeFilter)}
        />
      </div>

      {rules.length === 0 && !isLoading ? (
        hasFilters ? <p className="py-8 text-center text-sm text-secondary-text">{text.noMatch}</p> : guide
      ) : (
        <ul className="space-y-3">
          {rules.map((rule) => (
            <RuleCard
              key={rule.id}
              rule={rule}
              quote={quotes[rule.target]}
              busy={busyRule}
              testResult={testResults[rule.id]}
              onToggleEnabled={onToggleEnabled}
              onEdit={onEdit}
              onTest={onTest}
              onDismissTest={onDismissTest}
              onRequestDelete={setPendingDelete}
            />
          ))}
        </ul>
      )}

      {rules.length < total ? (
        <div className="mt-4 flex justify-center">
          <Button variant="secondary" size="sm" isLoading={isLoading} onClick={onLoadMore}>
            {text.loadMore}
          </Button>
        </div>
      ) : null}

      <ConfirmDialog
        isOpen={pendingDelete != null}
        title={text.deleteTitle}
        message={pendingDelete ? formatUiText(text.deleteMessage, { name: pendingDelete.name }) : ''}
        confirmText={text.delete}
        cancelText={text.cancel}
        isDanger
        onConfirm={() => {
          if (pendingDelete) onDelete(pendingDelete);
          setPendingDelete(null);
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </Card>
  );
};
