import type React from 'react';
import { Activity } from 'lucide-react';
import { Badge, Card, EmptyState, Loading } from '../common';
import type { AlertTriggerItem } from '../../types/alerts';
import { formatDateTime } from '../../utils/format';
import { getMarketPhaseSummaryLabel } from '../../utils/marketPhase';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';

const STATUS_KEYS: Record<string, UiTextKey> = {
  triggered: 'alertsHistory.status.triggered',
  skipped: 'alertsHistory.status.skipped',
  degraded: 'alertsHistory.status.degraded',
  failed: 'alertsHistory.status.failed',
};

function statusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'triggered') return 'success';
  if (status === 'skipped' || status === 'degraded') return 'warning';
  if (status === 'failed') return 'danger';
  return 'default';
}

function formatNullable(value?: string | number | null): string {
  if (value === null || value === undefined || value === '') return '--';
  return String(value);
}

function renderPhaseQuality(trigger: AlertTriggerItem, t: ReturnType<typeof useUiLanguage>['t']): React.ReactNode {
  const phase = getMarketPhaseSummaryLabel(trigger.marketPhaseSummary, 'zh');
  const quality = trigger.analysisContextPackOverview?.dataQuality?.level;
  const limitations = trigger.analysisContextPackOverview?.dataQuality?.limitations?.slice(0, 2) ?? [];
  if (!phase && !quality && limitations.length === 0) {
    return <span className="text-xs text-muted-text">--</span>;
  }
  return (
    <div className="space-y-1">
      {phase ? <Badge variant="default">{phase.replace('市场阶段: ', '').replace('市场阶段：', '')}</Badge> : null}
      {quality ? <div className="text-xs text-secondary-text">{t('alertsHistory.quality', { quality })}</div> : null}
      {limitations.length ? (
        <div className="max-w-[180px] text-xs text-muted-text">{limitations.join('；')}</div>
      ) : null}
    </div>
  );
}

interface AlertTriggerHistoryProps {
  triggers: AlertTriggerItem[];
  isLoading?: boolean;
}

export const AlertTriggerHistory: React.FC<AlertTriggerHistoryProps> = ({ triggers, isLoading = false }) => {
  const { t } = useUiLanguage();
  return (
    <Card title={t('alertsHistory.title')} subtitle={t('alertsHistory.subtitle')} variant="bordered" padding="md">
      {isLoading ? <Loading label={t('alertsHistory.loading')} /> : null}
      {!isLoading && triggers.length === 0 ? (
        <EmptyState
          icon={<Activity className="h-6 w-6" />}
          title={t('alertsHistory.empty')}
          description={t('alertsHistory.emptyDescription')}
        />
      ) : null}
      {!isLoading && triggers.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead className="border-b border-border/60 text-xs uppercase text-muted-text">
              <tr>
                <th className="px-3 py-2 font-medium">{t('alertsHistory.col.status')}</th>
                <th className="px-3 py-2 font-medium">{t('alertsHistory.col.phaseQuality')}</th>
                <th className="px-3 py-2 font-medium">{t('alertsHistory.col.target')}</th>
                <th className="px-3 py-2 font-medium">{t('alertsHistory.col.observed')}</th>
                <th className="px-3 py-2 font-medium">{t('alertsHistory.col.threshold')}</th>
                <th className="px-3 py-2 font-medium">{t('alertsHistory.col.source')}</th>
                <th className="px-3 py-2 font-medium">{t('alertsHistory.col.dataTime')}</th>
                <th className="px-3 py-2 font-medium">{t('alertsHistory.col.reason')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {triggers.map((trigger) => (
                <tr key={trigger.id} className="align-top">
                  <td className="px-3 py-3">
                    <Badge variant={statusVariant(trigger.status)}>
                      {STATUS_KEYS[trigger.status] ? t(STATUS_KEYS[trigger.status]) : trigger.status}
                    </Badge>
                  </td>
                  <td className="px-3 py-3">{renderPhaseQuality(trigger, t)}</td>
                  <td className="px-3 py-3 font-mono text-secondary-text">{trigger.target}</td>
                  <td className="px-3 py-3 text-secondary-text">{formatNullable(trigger.observedValue)}</td>
                  <td className="px-3 py-3 text-secondary-text">{formatNullable(trigger.threshold)}</td>
                  <td className="px-3 py-3 text-secondary-text">{formatNullable(trigger.dataSource)}</td>
                  <td className="px-3 py-3 text-xs text-secondary-text">
                    {formatDateTime(trigger.dataTimestamp ?? trigger.triggeredAt)}
                  </td>
                  <td className="px-3 py-3 text-secondary-text">
                    {trigger.reason || trigger.diagnostics || '--'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Card>
  );
};
