import type React from 'react';
import { PanelRightOpen } from 'lucide-react';
import type { StockQuote } from '../../api/stocks';
import { Badge, Card, Collapsible, JsonViewer } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiLanguage, UiTextKey } from '../../i18n/uiText';
import type {
  DecisionSignalFeedbackItem,
  DecisionSignalFeedbackValue,
  DecisionSignalItem,
  DecisionSignalOutcomeItem,
  DecisionSignalOutcomeValue,
  DecisionSignalStatus,
} from '../../types/decisionSignals';
import {
  buildDecisionActionLabelMap,
  getDecisionActionLabel,
  getDecisionActionTone,
  type DecisionActionTone,
} from '../../utils/decisionAction';
import { cn } from '../../utils/cn';
import { formatSignalText, parseSignalList } from '../../utils/signalText';
import { parseDecisionSignalDate } from '../../utils/decisionSignalTime';
import { getDecisionSignalProfileLabel } from '../../utils/decisionSignalProfile';
import { signalCurrency, sourceReportHref } from '../../utils/decisionSignalRow';
import { formatPercent as formatSignedPercent, formatPrice } from '../../utils/format';
import { marketToneClass } from '../../utils/marketTone';
import { BACKTEST_DIRECTION_EXPECTED_LABELS } from '../../locales/featureText';
import {
  getDecisionSignalHorizonLabel,
  getDecisionSignalMarketLabel,
  getDecisionSignalMarketPhaseLabel,
  getDecisionSignalPlanQualityLabel,
} from '../../utils/decisionSignalLabels';

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'history' | 'brand' | 'neutral' | 'caution';

const STATUS_LABEL_KEYS: Record<DecisionSignalStatus, UiTextKey> = {
  active: 'decisionSignals.active',
  expired: 'decisionSignals.expired',
  invalidated: 'decisionSignals.invalidated',
  closed: 'decisionSignals.closed',
  archived: 'decisionSignals.archived',
};

const STATUS_VARIANTS: Record<DecisionSignalStatus, BadgeVariant> = {
  active: 'success',
  expired: 'warning',
  invalidated: 'danger',
  closed: 'default',
  archived: 'history',
};

const ACTION_VARIANTS: Record<DecisionActionTone, BadgeVariant> = {
  brand: 'brand',
  neutral: 'neutral',
  caution: 'caution',
  default: 'default',
};

const OUTCOME_VARIANTS: Record<DecisionSignalOutcomeValue, BadgeVariant> = {
  // 命中與否不是系統狀態也不是損益，不用紅綠。
  hit: 'brand',
  miss: 'caution',
  neutral: 'neutral',
};

const LOCALE_BY_LANGUAGE: Record<UiLanguage, string> = {
  zh: 'zh-CN',
  en: 'en-US',
  'zh-TW': 'zh-TW',
};

function formatDateTime(value: string | null | undefined, language: UiLanguage): string {
  const date = parseDecisionSignalDate(value);
  if (!date) return '-';
  return new Intl.DateTimeFormat(LOCALE_BY_LANGUAGE[language], {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(date);
}

export const formatSignalDateTime = formatDateTime;

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return Number(value).toFixed(2).replace(/\.?0+$/, '');
}

export function formatConfidence(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${formatNumber(normalized)}%`;
}

function formatEntryRange(item: DecisionSignalItem): string {
  const hasLow = item.entryLow !== null && item.entryLow !== undefined;
  const hasHigh = item.entryHigh !== null && item.entryHigh !== undefined;
  if (hasLow && hasHigh) {
    return item.entryLow === item.entryHigh
      ? formatNumber(item.entryLow)
      : `${formatNumber(item.entryLow)} - ${formatNumber(item.entryHigh)}`;
  }
  if (hasLow) return formatNumber(item.entryLow);
  if (hasHigh) return formatNumber(item.entryHigh);
  return '-';
}

function formatJsonish(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return value.trim() || null;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function asJsonViewerData(value: unknown): Record<string, unknown> | unknown[] | null {
  if (Array.isArray(value)) return value;
  if (value && typeof value === 'object') return value as Record<string, unknown>;
  return null;
}

function getActionLabel(item: DecisionSignalItem, t: (key: UiTextKey) => string): string {
  return getDecisionActionLabel(
    item.action,
    item.actionLabel,
    null,
    t('decisionSignals.action'),
    buildDecisionActionLabelMap(t),
  ) ?? t('decisionSignals.action');
}

function getActionVariant(item: DecisionSignalItem): BadgeVariant {
  return ACTION_VARIANTS[getDecisionActionTone(item.action, item.actionLabel, null)];
}

function getOutcomeLabel(value: DecisionSignalOutcomeValue | null | undefined, t: (key: UiTextKey) => string): string {
  if (!value) return '-';
  const key = `decisionSignals.outcome.${value}` as UiTextKey;
  return t(key);
}

function getFeedbackLabel(value: DecisionSignalFeedbackValue | null | undefined, t: (key: UiTextKey) => string): string {
  if (!value) return t('decisionSignals.feedbackNone');
  const key = `decisionSignals.feedback.${value}` as UiTextKey;
  return t(key);
}

function hasDisplayValue(value: string): boolean {
  return value !== '-';
}

const SOLID_TONE_CLASS: Record<DecisionActionTone, string> = {
  brand: 'bg-cyan text-slate-950',
  neutral: 'bg-secondary-text text-background',
  caution: 'bg-warning text-slate-950',
  default: 'bg-elevated text-secondary-text',
};

/** 實心動作標籤：顯示依 action 枚舉查表，顏色依 ACTION_TONE，不用紅綠。 */
export const SignalActionTag: React.FC<{ item: DecisionSignalItem }> = ({ item }) => {
  const { t } = useUiLanguage();
  return (
    <span
      data-tone={getDecisionActionTone(item.action, item.actionLabel, null)}
      className={cn(
        'inline-flex shrink-0 items-center rounded-md px-2 py-0.5 text-xs font-semibold',
        SOLID_TONE_CLASS[getDecisionActionTone(item.action, item.actionLabel, null)],
      )}
    >
      {getActionLabel(item, t)}
    </span>
  );
};

type SignalMetricTone = 'default' | 'success' | 'warning' | 'danger';

const metricToneClass: Record<SignalMetricTone, string> = {
  default: 'text-foreground',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
};

type SignalMetricProps = {
  label: string;
  value: string;
  tone?: SignalMetricTone;
};

const SignalMetric: React.FC<SignalMetricProps> = ({ label, value, tone = 'default' }) => (
  <div className="min-w-0 rounded-xl border border-border/60 bg-elevated/45 px-3 py-2">
    <p className="truncate text-[11px] text-muted-text">{label}</p>
    <p className={cn('mt-1 truncate text-sm font-semibold tabular-nums', metricToneClass[tone])}>{value}</p>
  </div>
);

type SignalTextTone = 'default' | 'warning' | 'danger' | 'info';

const textToneClass: Record<SignalTextTone, string> = {
  default: 'border-border/55 bg-elevated/35 text-secondary-text',
  warning: 'border-warning/25 bg-warning/10 text-warning',
  danger: 'border-danger/25 bg-danger/10 text-danger',
  info: 'border-cyan/25 bg-cyan/10 text-cyan',
};

type SignalTextBlockProps = {
  label: string;
  value?: string | null;
  tone?: SignalTextTone;
  clamp?: boolean;
};

const SignalTextBlock: React.FC<SignalTextBlockProps> = ({ label, value, tone = 'default', clamp = true }) => {
  // 條列欄位在庫裡是 JSON 陣列字串：卡片摘要接成一行，詳情逐條列出
  const list = parseSignalList(value);
  const normalized = formatSignalText(value);
  if (!normalized) return null;
  return (
    <div className={cn('rounded-xl border px-3 py-2.5', textToneClass[tone])}>
      <p className="text-[11px] font-medium text-current/80">{label}</p>
      {list && !clamp ? (
        <ul className="mt-1 list-disc space-y-1 pl-4 text-sm leading-5 text-current">
          {list.map((entry, idx) => (
            <li key={idx} className="whitespace-pre-wrap">{entry}</li>
          ))}
        </ul>
      ) : (
        <p className={cn('mt-1 text-sm leading-5 text-current', clamp ? 'line-clamp-2' : 'whitespace-pre-wrap')}>
          {normalized}
        </p>
      )}
    </div>
  );
};

type DecisionSignalCardProps = {
  item: DecisionSignalItem;
  onSelect?: (item: DecisionSignalItem) => void;
  selected?: boolean;
};

export const DecisionSignalCard: React.FC<DecisionSignalCardProps> = ({ item, onSelect, selected = false }) => {
  const { language, t } = useUiLanguage();
  const actionLabel = getActionLabel(item, t);
  const profileLabel = getDecisionSignalProfileLabel(item, t);
  const interactive = Boolean(onSelect);
  const entryRange = formatEntryRange(item);
  const pricePlanItems = [
    { label: t('decisionSignals.entryRange'), value: entryRange, tone: 'default' as const },
    { label: t('decisionSignals.stopLoss'), value: formatNumber(item.stopLoss), tone: 'danger' as const },
    { label: t('decisionSignals.targetPrice'), value: formatNumber(item.targetPrice), tone: 'success' as const },
  ].filter((entry) => hasDisplayValue(entry.value));
  const className = cn(
    'block w-full rounded-2xl border bg-card/75 p-4 text-left',
    interactive ? 'transition-colors hover:border-cyan/40 hover:bg-hover/70' : '',
    selected ? 'border-cyan/50 bg-cyan/10' : 'border-border/70',
  );
  const content = (
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={getActionVariant(item)}>{actionLabel}</Badge>
            <Badge variant={STATUS_VARIANTS[item.status]}>{t(STATUS_LABEL_KEYS[item.status])}</Badge>
            <Badge variant="info">{t('decisionSignals.profile')}: {profileLabel}</Badge>
            <span className="font-mono text-sm text-secondary-text">{item.stockCode}</span>
          </div>
          <h3 className="mt-2 text-base font-semibold text-foreground">
            {item.stockName || item.stockCode}
          </h3>
        </div>
        <div className="text-right text-xs text-secondary-text">
          <div>{getDecisionSignalMarketLabel(item.market, t)}</div>
          <div className="mt-1">{formatDateTime(item.createdAt, language)}</div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2">
        <SignalMetric label={t('decisionSignals.score')} value={formatNumber(item.score)} />
        <SignalMetric label={t('decisionSignals.confidence')} value={formatConfidence(item.confidence)} />
        <SignalMetric label={t('decisionSignals.horizon')} value={getDecisionSignalHorizonLabel(item.horizon, t)} />
      </div>

      {pricePlanItems.length > 0 ? (
        <div className="mt-3 rounded-xl border border-border/60 bg-elevated/35 px-3 py-2.5">
          <div className="grid gap-2 sm:grid-cols-3">
            {pricePlanItems.map((entry) => (
              <div key={entry.label} className="min-w-0">
                <p className="truncate text-[11px] text-muted-text">{entry.label}</p>
                <p className={cn('mt-1 truncate text-sm font-semibold tabular-nums', metricToneClass[entry.tone])}>
                  {entry.value}
                </p>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-3 grid gap-2">
        <SignalTextBlock label={t('decisionSignals.reason')} value={item.reason} />
        <SignalTextBlock label={t('decisionSignals.catalystSummary')} value={item.catalystSummary} tone="info" />
        <SignalTextBlock label={t('decisionSignals.watchConditions')} value={item.watchConditions} />
        <SignalTextBlock label={t('decisionSignals.riskSummary')} value={item.riskSummary} tone="warning" />
        <SignalTextBlock label={t('decisionSignals.invalidation')} value={item.invalidation} tone="danger" />
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-text">
        <span>{t('decisionSignals.planQuality')}: {getDecisionSignalPlanQualityLabel(item.planQuality, t)}</span>
        <span>{t('decisionSignals.marketPhase')}: {getDecisionSignalMarketPhaseLabel(item.marketPhase, t)}</span>
        <span>{t('decisionSignals.expiresAt')}: {formatDateTime(item.expiresAt, language)}</span>
        {item.sourceReportId ? <span>{t('decisionSignals.sourceReport')}: #{item.sourceReportId}</span> : null}
      </div>
    </>
  );

  if (!interactive) {
    return <div className={className}>{content}</div>;
  }

  return (
    <div className={className}>
      {content}
      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={() => onSelect?.(item)}
          className="btn-secondary inline-flex items-center gap-1.5 !px-3 !py-1.5 !text-xs"
          aria-label={t('decisionSignals.viewDetailsFor', { stock: item.stockName || item.stockCode })}
        >
          <PanelRightOpen className="h-3.5 w-3.5" />
          {t('common.details')}
        </button>
      </div>
    </div>
  );
};

type DetailRowProps = {
  label: string;
  value?: React.ReactNode;
};

const DetailRow: React.FC<DetailRowProps> = ({ label, value }) => (
  <div className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-2">
    <p className="text-xs text-secondary-text">{label}</p>
    <div className="mt-1 text-sm text-foreground">{value || '-'}</div>
  </div>
);

const CurrentPriceBlock: React.FC<{ item: DecisionSignalItem; quote?: StockQuote }> = ({ item, quote }) => {
  const { t } = useUiLanguage();
  const currency = signalCurrency(item.market);
  return (
    <div data-testid="signal-current-price">
      <p className="text-xs text-secondary-text">{t('decisionSignals.currentPrice')}</p>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-2xl font-semibold tabular-nums text-foreground">{formatPrice(quote?.currentPrice, currency)}</span>
        <span className={cn('text-sm tabular-nums', marketToneClass(quote?.changePercent))}>{formatSignedPercent(quote?.changePercent)}</span>
        {typeof item.signalPrice === 'number' ? (
          <span className="text-xs text-secondary-text">
            {t('decisionSignals.signalPriceAt', { price: formatPrice(item.signalPrice, currency) })}
          </span>
        ) : null}
      </div>
    </div>
  );
};

type RulerMark = { key: string; label: string; value: number; text: string; tone: string };

/** 價位尺：把停損、進場、現價、目標放在同一條軸上。可比較的價位不到兩個就不畫。 */
export const PriceRuler: React.FC<{ item: DecisionSignalItem; currentPrice?: number | null }> = ({ item, currentPrice }) => {
  const { t } = useUiLanguage();
  const currency = signalCurrency(item.market);
  const candidates: Array<[string, string, number | null | undefined, string]> = [
    ['stop', t('decisionSignals.stopLoss'), item.stopLoss, 'bg-warning'],
    ['entryLow', t('decisionSignals.entryRange'), item.entryLow, 'bg-secondary-text'],
    ['entryHigh', t('decisionSignals.entryRange'), item.entryHigh, 'bg-secondary-text'],
    ['current', t('decisionSignals.currentPrice'), currentPrice, 'bg-foreground'],
    ['target', t('decisionSignals.targetPrice'), item.targetPrice, 'bg-cyan'],
  ];
  const marks: RulerMark[] = candidates.flatMap(([key, label, value, tone]) => (
    typeof value === 'number' && Number.isFinite(value)
      ? [{ key, label, value, text: formatPrice(value, currency), tone }]
      : []
  ));
  const values = marks.map((mark) => mark.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (marks.length < 2 || max <= min) return null;
  const position = (value: number) => ((value - min) / (max - min)) * 100;
  const legend = [...marks]
    .sort((left, right) => left.value - right.value)
    .filter((mark) => mark.key !== 'entryHigh' || item.entryLow === null || item.entryLow === undefined);

  return (
    <div data-testid="signal-price-ruler" role="group" aria-label={t('decisionSignals.priceRuler')}>
      <div className="relative mx-1 my-2 h-1.5 rounded-full bg-elevated">
        {marks.map((mark) => (
          <span
            key={mark.key}
            data-mark={mark.key}
            className={cn('absolute top-1/2 h-3.5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full', mark.tone)}
            style={{ left: `${position(mark.value)}%` }}
          />
        ))}
      </div>
      <dl className="mt-2 flex flex-wrap justify-between gap-x-4 gap-y-1 text-xs">
        {legend.map((mark) => (
          <div key={mark.key} className="min-w-0">
            <dt className="text-secondary-text">{mark.label}</dt>
            <dd className="tabular-nums text-foreground">
              {mark.key.startsWith('entry') ? formatEntryRange(item) : mark.text}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
};

type DecisionSignalDetailsProps = {
  item: DecisionSignalItem;
  /** 批次行情；沒有讀數時現價顯示 —，不退回訊號當時價。 */
  quote?: StockQuote;
  /** 頁首右側的「⋯」鈕。 */
  actions?: React.ReactNode;
  /** 「⋯」展開的內容：重評估與狀態操作。 */
  actionsPanel?: React.ReactNode;
  outcomes?: DecisionSignalOutcomeItem[];
  outcomesLoading?: boolean;
  outcomesError?: string | null;
  feedback?: DecisionSignalFeedbackItem | null;
  feedbackLoading?: boolean;
  feedbackSaving?: boolean;
  feedbackError?: string | null;
  onFeedbackSubmit?: (value: DecisionSignalFeedbackValue) => void;
};

export const DecisionSignalDetails: React.FC<DecisionSignalDetailsProps> = ({
  item,
  quote,
  actions,
  actionsPanel,
  outcomes = [],
  outcomesLoading = false,
  outcomesError = null,
  feedback = null,
  feedbackLoading = false,
  feedbackSaving = false,
  feedbackError = null,
  onFeedbackSubmit,
}) => {
  const { language, t } = useUiLanguage();
  const profileLabel = getDecisionSignalProfileLabel(item, t);
  const evidenceData = asJsonViewerData(item.evidence);
  const qualityData = asJsonViewerData(item.dataQualitySummary);
  const metadataData = asJsonViewerData(item.metadata);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <SignalActionTag item={item} />
            <Badge variant={STATUS_VARIANTS[item.status]} size="md">{t(STATUS_LABEL_KEYS[item.status])}</Badge>
          </div>
          <h3 className="mt-3 text-xl font-semibold text-foreground">{item.stockName || item.stockCode}</h3>
          <p className="mt-1 font-mono text-sm text-secondary-text">{item.stockCode} · {getDecisionSignalMarketLabel(item.market, t)}</p>
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>

      {actionsPanel}

      <CurrentPriceBlock item={item} quote={quote} />

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-secondary-text">
        <span>{t('decisionSignals.score')} <span className="tabular-nums text-foreground">{formatNumber(item.score)}</span></span>
        <span>{t('decisionSignals.confidence')} <span className="tabular-nums text-foreground">{formatConfidence(item.confidence)}</span></span>
        <span>{t('decisionSignals.horizon')} <span className="text-foreground">{getDecisionSignalHorizonLabel(item.horizon, t)}</span></span>
      </div>

      <PriceRuler item={item} currentPrice={quote?.currentPrice} />

      <SignalTextBlock label={t('decisionSignals.reason')} value={formatJsonish(item.reason)} clamp={false} />

      <div className="grid gap-3 sm:grid-cols-2">
        <SignalTextBlock label={t('decisionSignals.catalystSummary')} value={formatJsonish(item.catalystSummary)} tone="info" clamp={false} />
        <SignalTextBlock label={t('decisionSignals.riskSummary')} value={formatJsonish(item.riskSummary)} tone="warning" clamp={false} />
      </div>

      <div className="grid gap-3">
        <SignalTextBlock label={t('decisionSignals.watchConditions')} value={formatJsonish(item.watchConditions)} clamp={false} />
        <SignalTextBlock label={t('decisionSignals.invalidation')} value={formatJsonish(item.invalidation)} tone="warning" clamp={false} />
      </div>

      <Card title={t('decisionSignals.outcomes')} padding="sm" className="rounded-xl">
        {outcomesLoading ? (
          <p className="text-sm text-secondary-text">{t('common.loading')}...</p>
        ) : outcomesError ? (
          <p className="text-sm text-danger">{outcomesError}</p>
        ) : outcomes.length === 0 ? (
          <p className="text-sm text-secondary-text">{t('decisionSignals.noOutcomes')}</p>
        ) : (
          <div className="grid gap-3">
            {outcomes.map((outcome) => (
              <div key={outcome.id} className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-foreground">{getDecisionSignalHorizonLabel(outcome.horizon, t)}</span>
                    {outcome.outcome ? (
                      <Badge variant={OUTCOME_VARIANTS[outcome.outcome]}>
                        {getOutcomeLabel(outcome.outcome, t)}
                      </Badge>
                    ) : (
                      <Badge variant="warning">{t('decisionSignals.outcome.unable')}</Badge>
                    )}
                  </div>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-3">
                  <DetailRow
                    label={t('decisionSignals.returnPct')}
                    value={<span className={cn('tabular-nums', marketToneClass(outcome.stockReturnPct))}>{formatSignedPercent(outcome.stockReturnPct)}</span>}
                  />
                  <DetailRow
                    label={t('decisionSignals.directionExpected')}
                    value={outcome.directionExpected ? (BACKTEST_DIRECTION_EXPECTED_LABELS[language][outcome.directionExpected] ?? outcome.directionExpected) : '-'}
                  />
                  <DetailRow label={t('decisionSignals.unableReason')} value={outcome.unableReason || '-'} />
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title={t('decisionSignals.feedbackTitle')} padding="sm" className="rounded-xl">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm text-foreground">
              {feedbackLoading ? `${t('common.loading')}...` : getFeedbackLabel(feedback?.feedbackValue, t)}
            </p>
            {feedback?.reasonCode ? (
              <p className="mt-1 text-xs text-secondary-text">{feedback.reasonCode}</p>
            ) : null}
            {feedbackError ? <p className="mt-2 text-sm text-danger">{feedbackError}</p> : null}
          </div>
          {onFeedbackSubmit ? (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-secondary !px-3 !py-1.5 !text-xs"
                disabled={feedbackSaving}
                onClick={() => onFeedbackSubmit('useful')}
              >
                {t('decisionSignals.feedback.useful')}
              </button>
              <button
                type="button"
                className="btn-secondary !px-3 !py-1.5 !text-xs"
                disabled={feedbackSaving}
                onClick={() => onFeedbackSubmit('not_useful')}
              >
                {t('decisionSignals.feedback.not_useful')}
              </button>
            </div>
          ) : null}
        </div>
      </Card>

      <Collapsible title={t('decisionSignals.technicalData')}>
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <DetailRow label={t('decisionSignals.profile')} value={profileLabel} />
            <DetailRow label={t('decisionSignals.planQuality')} value={getDecisionSignalPlanQualityLabel(item.planQuality, t)} />
            <DetailRow label={t('decisionSignals.marketPhase')} value={getDecisionSignalMarketPhaseLabel(item.marketPhase, t)} />
            <DetailRow
              label={t('decisionSignals.sourceReport')}
              value={item.sourceReportId ? (
                <a href={sourceReportHref(item.sourceReportId)} className="text-cyan hover:underline">#{item.sourceReportId}</a>
              ) : '-'}
            />
            <DetailRow label={t('decisionSignals.createdAt')} value={formatDateTime(item.createdAt, language)} />
            <DetailRow label={t('decisionSignals.expiresAt')} value={formatDateTime(item.expiresAt, language)} />
          </div>
          {evidenceData ? (
            <div>
              <p className="mb-1 text-xs text-secondary-text">{t('decisionSignals.evidence')}</p>
              <JsonViewer data={evidenceData} maxHeight="240px" />
            </div>
          ) : null}
          {qualityData ? (
            <div>
              <p className="mb-1 text-xs text-secondary-text">{t('decisionSignals.dataQuality')}</p>
              <JsonViewer data={qualityData} maxHeight="240px" />
            </div>
          ) : null}
          {metadataData ? (
            <div>
              <p className="mb-1 text-xs text-secondary-text">{t('decisionSignals.metadata')}</p>
              <JsonViewer data={metadataData} maxHeight="240px" />
            </div>
          ) : null}
        </div>
      </Collapsible>
    </div>
  );
};

type PortfolioSignalSummaryProps = {
  item?: DecisionSignalItem;
  loading?: boolean;
};

export const PortfolioSignalSummary: React.FC<PortfolioSignalSummaryProps> = ({ item, loading = false }) => {
  const { t } = useUiLanguage();
  if (loading && !item) {
    return <span className="text-xs text-secondary-text">{t('decisionSignals.portfolioLoading')}</span>;
  }
  if (!item) {
    return <span className="text-xs text-muted-text">{t('decisionSignals.portfolioEmpty')}</span>;
  }
  const actionLabel = getActionLabel(item, t);
  const riskText = formatSignalText(item.riskSummary);
  const watchText = formatSignalText(item.watchConditions);
  return (
    <div className="min-w-[11rem] max-w-[18rem] text-left">
      <div className="flex flex-wrap items-center justify-end gap-1.5">
        <Badge variant={getActionVariant(item)}>{actionLabel}</Badge>
        {item.horizon ? <span className="text-[11px] text-secondary-text">{getDecisionSignalHorizonLabel(item.horizon, t)}</span> : null}
      </div>
      {riskText ? <p className="mt-1 line-clamp-2 text-[11px] text-warning">{riskText}</p> : null}
      {watchText ? <p className="mt-1 line-clamp-2 text-[11px] text-secondary-text">{watchText}</p> : null}
    </div>
  );
};
