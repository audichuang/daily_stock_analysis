import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { BellRing, Plus } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { alertsApi } from '../api/alerts';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import { stocksApi } from '../api/stocks';
import { AlertRuleForm, type AlertRuleFormInitial } from '../components/alerts/AlertRuleForm';
import {
  AlertRuleList,
  type AlertQuoteView,
  type AlertRuleBusyState,
  type AlertRuleEnabledFilter,
  type AlertScopeFilter,
  type AlertTypeFilter,
} from '../components/alerts/AlertRuleList';
import { ruleCondition } from '../components/alerts/alertRuleText';
import { AlertTriggerHistory, type AlertActivityTab } from '../components/alerts/AlertTriggerHistory';
import { ApiErrorAlert, AppPage, Button, Card, Drawer, EmptyState, InlineAlert, Loading, PageHeader } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { formatUiText } from '../i18n/uiText';
import { ALERT_PAGE_TEXT } from '../locales/featureText';
import type {
  AlertMonitorStatus,
  AlertNotificationItem,
  AlertRuleCreateRequest,
  AlertRuleItem,
  AlertRuleListResponse,
  AlertRuleTestResponse,
  AlertTriggerItem,
  AlertTriggerSummary,
} from '../types/alerts';
import { formatDateTime } from '../utils/format';

const PAGE_SIZE = 20;
const ISSUE_STATUSES = 'degraded,failed,skipped';
type MobileTab = 'rules' | 'activity' | 'diagnostics';

const AlertsPage: React.FC = () => {
  const { language } = useUiLanguage();
  const text = ALERT_PAGE_TEXT[language];
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    document.title = `${text.title} - DSA`;
  }, [text.title]);

  const queryTarget = searchParams.get('target') ?? '';
  const [monitor, setMonitor] = useState<AlertMonitorStatus | null>(null);
  const [monitorFailed, setMonitorFailed] = useState(false);

  const [rules, setRules] = useState<AlertRuleItem[]>([]);
  const [rulesTotal, setRulesTotal] = useState(0);
  const [ruleSources, setRuleSources] = useState<AlertRuleListResponse['ruleSources']>(null);
  const [rulesPage, setRulesPage] = useState(1);
  const [searchTarget, setSearchTarget] = useState(searchParams.get('new') ? '' : queryTarget);
  const [scopeFilter, setScopeFilter] = useState<AlertScopeFilter>('all');
  const [enabledFilter, setEnabledFilter] = useState<AlertRuleEnabledFilter>('all');
  const [alertTypeFilter, setAlertTypeFilter] = useState<AlertTypeFilter>('all');
  const [rulesLoading, setRulesLoading] = useState(false);
  const [rulesError, setRulesError] = useState<ParsedApiError | null>(null);
  const [rulesRefreshKey, setRulesRefreshKey] = useState(0);
  const [quotes, setQuotes] = useState<Record<string, AlertQuoteView>>({});
  const rulesRequestIdRef = useRef(0);

  const [activityTab, setActivityTab] = useState<AlertActivityTab>('triggered');
  const [triggers, setTriggers] = useState<AlertTriggerItem[]>([]);
  const [triggersTotal, setTriggersTotal] = useState(0);
  const [triggersPage, setTriggersPage] = useState(1);
  const [summary, setSummary] = useState<AlertTriggerSummary | null>(null);
  const [triggersLoading, setTriggersLoading] = useState(false);
  const [triggersError, setTriggersError] = useState<ParsedApiError | null>(null);
  const triggersRequestIdRef = useRef(0);

  const [notifications, setNotifications] = useState<AlertNotificationItem[]>([]);
  const [notificationsLoading, setNotificationsLoading] = useState(false);
  const [notificationsError, setNotificationsError] = useState<ParsedApiError | null>(null);

  const [drawerInitial, setDrawerInitial] = useState<AlertRuleFormInitial | null>(
    searchParams.get('new') ? { target: queryTarget } : null,
  );
  const [drawerOpen, setDrawerOpen] = useState(Boolean(searchParams.get('new')));
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ParsedApiError | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [busyRule, setBusyRule] = useState<AlertRuleBusyState | null>(null);
  const [testResults, setTestResults] = useState<Record<number, AlertRuleTestResponse>>({});
  const [mobileTab, setMobileTab] = useState<MobileTab>('rules');

  const refreshRules = useCallback(() => {
    setRulesPage(1);
    setRulesRefreshKey((value) => value + 1);
  }, []);

  const loadMonitor = useCallback(async () => {
    try {
      setMonitor(await alertsApi.getMonitorStatus());
      setMonitorFailed(false);
    } catch {
      setMonitorFailed(true);
    }
  }, []);

  useEffect(() => {
    void loadMonitor();
  }, [loadMonitor, rulesRefreshKey]);

  useEffect(() => {
    const requestId = rulesRequestIdRef.current + 1;
    rulesRequestIdRef.current = requestId;
    const isLatest = () => rulesRequestIdRef.current === requestId;
    setRulesLoading(true);
    void (async () => {
      try {
        const response = await alertsApi.listRules({
          enabled: enabledFilter === 'all' ? undefined : enabledFilter === 'enabled',
          alertType: alertTypeFilter === 'all' ? undefined : alertTypeFilter,
          targetScope: scopeFilter === 'all' ? undefined : scopeFilter,
          target: searchTarget.trim().toUpperCase() || undefined,
          page: rulesPage,
          pageSize: PAGE_SIZE,
        });
        if (!isLatest()) return;
        setRules((current) => (rulesPage === 1 ? response.items : [...current, ...response.items]));
        setRulesTotal(response.total);
        setRuleSources(response.ruleSources ?? null);
        setRulesError(null);
      } catch (error) {
        if (isLatest()) setRulesError(getParsedApiError(error));
      } finally {
        if (isLatest()) setRulesLoading(false);
      }
    })();
  }, [alertTypeFilter, enabledFilter, rulesPage, rulesRefreshKey, scopeFilter, searchTarget]);

  // 現價只補單檔價格規則；抓不到就顯示「暫無報價」，不影響規則列表。
  const quoteCodes = Array.from(new Set(
    rules.filter((rule) => rule.targetScope === 'single_symbol').map((rule) => rule.target),
  )).slice(0, 50).join(',');
  useEffect(() => {
    if (!quoteCodes) return undefined;
    let cancelled = false;
    void stocksApi.getQuotes(quoteCodes.split(','))
      .then((items) => {
        if (cancelled) return;
        const next: Record<string, AlertQuoteView> = {};
        for (const item of items ?? []) {
          if (item.quote?.currentPrice) {
            next[item.stockCode] = { price: item.quote.currentPrice, name: item.quote.stockName };
          }
        }
        setQuotes(next);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [quoteCodes]);

  useEffect(() => {
    const requestId = triggersRequestIdRef.current + 1;
    triggersRequestIdRef.current = requestId;
    const isLatest = () => triggersRequestIdRef.current === requestId;
    setTriggersLoading(true);
    void (async () => {
      try {
        const response = await alertsApi.listTriggers({
          status: activityTab === 'triggered' ? 'triggered' : ISSUE_STATUSES,
          page: triggersPage,
          pageSize: PAGE_SIZE,
        });
        if (!isLatest()) return;
        setTriggers((current) => (triggersPage === 1 ? response.items : [...current, ...response.items]));
        setTriggersTotal(response.total);
        setSummary(response.summary ?? null);
        setTriggersError(null);
      } catch (error) {
        if (isLatest()) setTriggersError(getParsedApiError(error));
      } finally {
        if (isLatest()) setTriggersLoading(false);
      }
    })();
  }, [activityTab, triggersPage]);

  useEffect(() => {
    setNotificationsLoading(true);
    void alertsApi.listNotifications({ page: 1, pageSize: PAGE_SIZE })
      .then((response) => {
        setNotifications(response.items);
        setNotificationsError(null);
      })
      .catch((error: unknown) => setNotificationsError(getParsedApiError(error)))
      .finally(() => setNotificationsLoading(false));
  }, []);

  const openDrawer = (initial: AlertRuleFormInitial | null) => {
    setSaveError(null);
    setDrawerInitial(initial);
    setDrawerOpen(true);
  };

  const closeDrawer = () => {
    setDrawerOpen(false);
    if (searchParams.get('new')) {
      const next = new URLSearchParams(searchParams);
      next.delete('new');
      next.delete('target');
      setSearchParams(next, { replace: true });
    }
  };

  const handleSave = async (payload: AlertRuleCreateRequest) => {
    setSaving(true);
    setSaveError(null);
    setSaveMessage(null);
    try {
      const editing = drawerInitial?.id;
      let saved: AlertRuleItem;
      if (editing != null) {
        // 看板價位規則只改提醒方式；目標與價位要回看板重建。
        const update = drawerInitial?.source === 'tw_levels'
          ? { name: payload.name, severity: payload.severity, cooldownSeconds: payload.cooldownSeconds }
          : payload;
        saved = await alertsApi.updateRule(editing, update);
        setSaveMessage(formatUiText(text.updated, { name: saved.name }));
      } else {
        // 沒填名稱時用看得懂的句子，否則後端預設是英文的機器字串（2330.TW price above 1.0）。
        const condition = ruleCondition({ alertType: payload.alertType, parameters: payload.parameters, name: '' }, language, text);
        saved = await alertsApi.createRule({
          ...payload,
          name: payload.name ?? (condition ? `${payload.target} ${condition}`.slice(0, 64) : undefined),
        });
        setSaveMessage(formatUiText(text.created, { name: saved.name }));
      }
      closeDrawer();
      refreshRules();
      return true;
    } catch (error) {
      setSaveError(getParsedApiError(error));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const runBusy = async (rule: AlertRuleItem, action: AlertRuleBusyState['action'], work: () => Promise<unknown>) => {
    setBusyRule({ id: rule.id, action });
    try {
      await work();
    } catch (error) {
      setRulesError(getParsedApiError(error));
    } finally {
      setBusyRule(null);
    }
  };

  const channelLabel = (channel: string): string => ({
    __cooldown__: text.channelCooldown,
    __cooldown_read_failed__: text.channelCooldownFail,
    __noise_suppressed__: text.channelNoise,
    __no_channel__: text.channelNone,
    __dispatch__: text.channelDispatch,
    __context__: text.channelContext,
  } as Record<string, string>)[channel] ?? channel;

  const resultLabel = (item: AlertNotificationItem): string => {
    if (item.success) return text.resultOk;
    if (item.errorCode === 'cooldown_active') return text.resultCooldown;
    if (item.errorCode === 'cooldown_read_failed') return text.channelCooldownFail;
    if (item.errorCode === 'noise_suppressed') return text.resultNoise;
    if (item.errorCode === 'no_channel') return text.resultNoChannel;
    return text.resultFail;
  };

  const reasonText = monitor?.reason === 'monitor_disabled'
    ? text.reasonDisabled
    : monitor?.reason === 'monitor_thread_not_running'
      ? text.reasonThread
      : text.reasonSchedule;

  const stats = [
    { label: text.statRules, value: monitor?.enabledRules },
    { label: text.statTriggered, value: summary?.triggered },
    { label: text.statIssues, value: summary ? summary.degraded + summary.failed : undefined },
    { label: text.statSkipped, value: summary?.skipped },
  ];

  const mobileTabs: Array<{ id: MobileTab; label: string }> = [
    { id: 'rules', label: text.tabRules },
    { id: 'activity', label: text.tabActivity },
    { id: 'diagnostics', label: text.tabDiagnostics },
  ];
  const paneClass = (tab: MobileTab) => (mobileTab === tab ? '' : 'hidden lg:block');

  const hasFilters = Boolean(searchTarget.trim()) || scopeFilter !== 'all' || enabledFilter !== 'all' || alertTypeFilter !== 'all';
  const templates: Array<{ label: string; initial: AlertRuleFormInitial }> = [
    { label: text.tplPrice, initial: { alertType: 'price_cross' } },
    { label: text.tplChange, initial: { alertType: 'price_change_percent', parameters: { direction: 'down', changePct: 3 } } },
    { label: text.tplMarket, initial: { targetScope: 'market', target: 'tw', alertType: 'market_light_status', parameters: { statuses: ['red'] } } },
  ];

  return (
    <AppPage className="space-y-4">
      <PageHeader
        title={text.title}
        actions={(
          <Button size="sm" onClick={() => openDrawer(null)}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            {text.newRule}
          </Button>
        )}
      />

      {monitor && !monitor.running ? (
        <InlineAlert title={text.monitorDownTitle} message={reasonText} variant="danger" />
      ) : null}
      {monitor?.running ? (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-secondary-text" data-testid="alert-monitor-bar">
          <span className="h-2 w-2 rounded-full bg-success" aria-hidden="true" />
          <span className="font-medium text-foreground">{text.monitorRunning}</span>
          <span>{formatUiText(text.monitorEvery, { minutes: Math.round(monitor.intervalSeconds / 60) })}</span>
          <span>
            {monitor.lastRunAt ? formatUiText(text.monitorLastRun, { time: formatDateTime(monitor.lastRunAt) }) : text.monitorNotYet}
          </span>
          <span className={monitor.channels.length ? '' : 'text-warning'}>
            {monitor.channels.length ? formatUiText(text.monitorChannels, { channels: monitor.channels.join('、') }) : text.monitorNoChannel}
          </span>
          {monitor.lastError ? <span className="text-danger">{formatUiText(text.monitorError, { error: monitor.lastError })}</span> : null}
        </p>
      ) : null}
      {monitorFailed ? <p className="text-xs text-warning">{text.monitorUnknown}</p> : null}

      <dl className="grid grid-cols-4 gap-2">
        {stats.map((stat) => (
          <div key={stat.label} className="rounded-xl border border-border/60 px-2 py-2 text-center sm:px-3">
            <dd className="text-lg font-semibold tabular-nums text-foreground">{stat.value ?? '--'}</dd>
            <dt className="text-xs text-secondary-text">{stat.label}</dt>
          </div>
        ))}
      </dl>

      {saveMessage ? (
        <InlineAlert
          message={saveMessage}
          variant="success"
          action={(
            <button type="button" className="text-sm underline" onClick={() => setSaveMessage(null)}>
              {text.close}
            </button>
          )}
        />
      ) : null}
      {rulesError ? <ApiErrorAlert error={rulesError} onDismiss={() => setRulesError(null)} /> : null}
      {!rulesError && ruleSources && ruleSources.legacyConfigured > 0 ? (
        <InlineAlert
          title={text.legacyTitle}
          variant="warning"
          message={formatUiText(text.legacyMessage, { configured: ruleSources.legacyConfigured, effective: ruleSources.legacyEffective })}
        />
      ) : null}

      <div role="tablist" className="flex gap-1 lg:hidden">
        {mobileTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={mobileTab === tab.id}
            className={`flex-1 rounded-lg border px-2 py-2 text-sm ${mobileTab === tab.id ? 'border-primary text-foreground' : 'border-border/60 text-secondary-text'}`}
            onClick={() => setMobileTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className={paneClass('rules')}>
          <AlertRuleList
            rules={rules}
            total={rulesTotal}
            isLoading={rulesLoading}
            hasFilters={hasFilters}
            searchTarget={searchTarget}
            scopeFilter={scopeFilter}
            enabledFilter={enabledFilter}
            alertTypeFilter={alertTypeFilter}
            quotes={quotes}
            testResults={testResults}
            busyRule={busyRule}
            onSearchTargetChange={(value) => {
              setSearchTarget(value);
              setRulesPage(1);
            }}
            onScopeFilterChange={(value) => {
              setScopeFilter(value);
              setRulesPage(1);
            }}
            onEnabledFilterChange={(value) => {
              setEnabledFilter(value);
              setRulesPage(1);
            }}
            onAlertTypeFilterChange={(value) => {
              setAlertTypeFilter(value);
              setRulesPage(1);
            }}
            onLoadMore={() => setRulesPage((page) => page + 1)}
            onEdit={(rule) => openDrawer(rule)}
            onToggleEnabled={(rule) => void runBusy(rule, 'toggle', async () => {
              await (rule.enabled ? alertsApi.disableRule(rule.id) : alertsApi.enableRule(rule.id));
              refreshRules();
            })}
            onDelete={(rule) => void runBusy(rule, 'delete', async () => {
              await alertsApi.deleteRule(rule.id);
              refreshRules();
            })}
            onTest={(rule) => void runBusy(rule, 'test', async () => {
              const result = await alertsApi.testRule(rule.id);
              setTestResults((current) => ({ ...current, [rule.id]: result }));
            })}
            onDismissTest={(rule) => setTestResults((current) => {
              const next = { ...current };
              delete next[rule.id];
              return next;
            })}
            guide={(
              <div className="py-6 text-center">
                <p className="text-sm font-medium text-foreground">{text.guideTitle}</p>
                <p className="mt-1 text-xs text-secondary-text">{text.guideBody}</p>
                <div className="mx-auto mt-4 grid max-w-md gap-2">
                  {templates.map((template) => (
                    <Button key={template.label} variant="secondary" size="sm" onClick={() => openDrawer(template.initial)}>
                      {template.label}
                    </Button>
                  ))}
                </div>
              </div>
            )}
          />
        </div>
        <div className={paneClass('activity')}>
          {triggersError ? <ApiErrorAlert error={triggersError} onDismiss={() => setTriggersError(null)} /> : null}
          <AlertTriggerHistory
            triggers={triggers}
            total={triggersTotal}
            isLoading={triggersLoading}
            tab={activityTab}
            triggeredCount={summary?.triggered}
            issueCount={summary ? summary.degraded + summary.failed + summary.skipped : undefined}
            onTabChange={(tab) => {
              setActivityTab(tab);
              setTriggers([]);
              setTriggersPage(1);
            }}
            onLoadMore={() => setTriggersPage((page) => page + 1)}
          />
        </div>
      </div>

      <div className={paneClass('diagnostics')}>
        {notificationsError ? <ApiErrorAlert error={notificationsError} onDismiss={() => setNotificationsError(null)} /> : null}
        <Card title={text.diagnostics} subtitle={text.diagnosticsHint} variant="bordered" padding="md">
          {notificationsLoading ? <Loading /> : null}
          {!notificationsLoading && notifications.length === 0 ? (
            <EmptyState icon={<BellRing className="h-6 w-6" />} title={text.noNotifications} />
          ) : null}
          <ul className="divide-y divide-border/40">
            {notifications.map((item) => (
              <li key={item.id} className="py-2 text-xs text-secondary-text">
                <span className="text-foreground">{channelLabel(item.channel)}</span>
                {` · ${resultLabel(item)} · ${formatDateTime(item.createdAt)}`}
                {item.latencyMs == null ? '' : ` · ${item.latencyMs}ms`}
                {item.diagnostics ? <div className="break-words text-muted-text">{item.diagnostics}</div> : null}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Drawer
        isOpen={drawerOpen}
        onClose={closeDrawer}
        title={drawerInitial?.id != null ? text.editRule : text.newRule}
      >
        {saveError ? <ApiErrorAlert error={saveError} onDismiss={() => setSaveError(null)} className="mb-4" /> : null}
        {drawerOpen ? (
          <AlertRuleForm
            key={drawerInitial?.id ?? JSON.stringify(drawerInitial)}
            initial={drawerInitial}
            isSubmitting={saving}
            onSubmit={handleSave}
            onCancel={closeDrawer}
          />
        ) : null}
      </Drawer>
    </AppPage>
  );
};

export default AlertsPage;
