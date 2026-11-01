import type React from 'react';
import { useMemo } from 'react';
import type { StockQuote } from '../../api/stocks';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { formatUiText } from '../../i18n/uiText';
import { SIGNALS_TEXT } from '../../locales/signalsText';
import type { DecisionSignalItem } from '../../types/decisionSignals';
import { cn } from '../../utils/cn';
import { buildDecisionActionLabelMap } from '../../utils/decisionAction';
import { getDecisionSignalHorizonLabel } from '../../utils/decisionSignalLabels';
import {
  distancePct,
  hasActionChange,
  signalCurrency,
  signalRemaining,
  sourceReportHref,
} from '../../utils/decisionSignalRow';
import { formatNumber, formatPercent, formatPrice } from '../../utils/format';
import { marketToneClass } from '../../utils/marketTone';
import { formatSignalText } from '../../utils/signalText';
import { Badge, DataTable, Tooltip, type DataTableColumn } from '../common';
import { formatConfidence, formatSignalDateTime, SignalActionTag } from './DecisionSignalDisplay';

type DecisionSignalTableProps = {
  items: DecisionSignalItem[];
  /** 依代號查批次行情；沒有讀數回 undefined，畫面顯示 —，不退回訊號當時價。 */
  quoteFor: (stockCode: string) => StockQuote | undefined;
  onSelect: (item: DecisionSignalItem) => void;
  onShowOlder: (item: DecisionSignalItem) => void;
};

const stopRowEvent = (event: React.SyntheticEvent) => event.stopPropagation();

/** US tickers are recognised by symbol, so the code leads; other markets lead with the name. */
const stockPrimaryAndSecondary = (item: DecisionSignalItem): { primary: string; secondary: string | null } => {
  if (item.market === 'us') {
    const name = item.stockName && item.stockName !== item.stockCode ? item.stockName : null;
    return { primary: item.stockCode, secondary: name };
  }
  return { primary: item.stockName || item.stockCode, secondary: item.stockCode };
};

export const DecisionSignalTable: React.FC<DecisionSignalTableProps> = ({ items, quoteFor, onSelect, onShowOlder }) => {
  const { language, t } = useUiLanguage();
  const signalsText = SIGNALS_TEXT[language];
  const actionLabels = useMemo(() => buildDecisionActionLabelMap(t), [t]);

  const remainingLabel = (item: DecisionSignalItem): string | null => {
    const remaining = signalRemaining(item.expiresAt);
    if (!remaining) return null;
    if (remaining.kind === 'expired') return t('decisionSignals.remainingExpired');
    if (remaining.kind === 'days') return formatUiText(signalsText.remainingDays, { count: remaining.count });
    return t('decisionSignals.remainingHours', { count: remaining.count });
  };

  const renderLevel = (item: DecisionSignalItem, level: number | null | undefined) => {
    if (level === null || level === undefined) return <span className="text-secondary-text">—</span>;
    const distance = distancePct(level, quoteFor(item.stockCode)?.currentPrice);
    return (
      <span className="inline-flex flex-col items-end leading-tight">
        <span>{formatPrice(level, signalCurrency(item.market))}</span>
        {/* 距離不是行情方向，用中性色。 */}
        <span className="text-xs text-secondary-text">{formatPercent(distance, 1)}</span>
      </span>
    );
  };

  const renderOlder = (item: DecisionSignalItem) => {
    const older = item.olderCount ?? 0;
    if (older <= 0) return null;
    return (
      <button
        type="button"
        className="shrink-0 cursor-pointer text-xs text-cyan hover:underline"
        onClick={(event) => {
          stopRowEvent(event);
          onShowOlder(item);
        }}
      >
        {t('decisionSignals.olderCount', { count: older })}
        {hasActionChange(item) && item.previousAction
          ? `・${t('decisionSignals.actionChange', { from: actionLabels[item.previousAction], to: actionLabels[item.action] })}`
          : ''}
      </button>
    );
  };

  const renderStopFlag = (item: DecisionSignalItem) => (
    item.stopTriggered ? <Badge variant="caution" className="shrink-0">{t('decisionSignals.stopTriggered')}</Badge> : null
  );

  // Held marker: a 6px cyan dot before the name; the word stays for screen readers and in the tooltip.
  const renderHeldDot = (item: DecisionSignalItem) => (
    item.isHeld ? (
      <Tooltip content={signalsText.heldHint} className="shrink-0 items-center">
        <span data-testid={`signal-held-dot-${item.id}`} aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-cyan" />
        <span className="sr-only">{t('decisionSignals.held')}</span>
      </Tooltip>
    ) : null
  );

  const columns: DataTableColumn<DecisionSignalItem>[] = [
    {
      key: 'action',
      header: t('decisionSignals.colAction'),
      minWidth: 64,
      render: (item) => <SignalActionTag item={item} />,
    },
    {
      key: 'stock',
      header: t('decisionSignals.colStock'),
      minWidth: 170,
      render: (item) => {
        const { primary, secondary } = stockPrimaryAndSecondary(item);
        return (
          <div className="min-w-0 py-1">
            <div className="flex flex-wrap items-center gap-1.5">
              {renderHeldDot(item)}
              <button
                type="button"
                className={cn(
                  'cursor-pointer truncate text-left font-medium text-foreground hover:text-cyan',
                  item.market === 'us' && 'font-mono',
                )}
                aria-label={t('decisionSignals.viewDetailsFor', { stock: item.stockName || item.stockCode })}
              >
                {primary}
              </button>
              {renderStopFlag(item)}
            </div>
            {secondary ? (
              <div className={cn('text-xs text-secondary-text', item.market !== 'us' && 'font-mono')}>{secondary}</div>
            ) : null}
          </div>
        );
      },
    },
    {
      key: 'price',
      header: t('decisionSignals.colPrice'),
      numeric: true,
      render: (item) => {
        const quote = quoteFor(item.stockCode);
        return (
          <span className="inline-flex flex-col items-end leading-tight">
            <span>{formatPrice(quote?.currentPrice, signalCurrency(item.market))}</span>
            <span className={cn('text-xs', marketToneClass(quote?.changePercent))}>{formatPercent(quote?.changePercent)}</span>
          </span>
        );
      },
    },
    {
      key: 'score',
      header: t('decisionSignals.colScore'),
      numeric: true,
      render: (item) => {
        const score = <span className="whitespace-nowrap tabular-nums">{formatNumber(item.score, 0)}</span>;
        if (item.confidence === null || item.confidence === undefined) return score;
        return (
          <Tooltip content={`${t('decisionSignals.confidence')} ${formatConfidence(item.confidence)}`}>
            {score}
          </Tooltip>
        );
      },
    },
    {
      key: 'stop',
      header: t('decisionSignals.colStop'),
      numeric: true,
      render: (item) => renderLevel(item, item.stopLoss),
    },
    {
      key: 'target',
      header: t('decisionSignals.colTarget'),
      numeric: true,
      render: (item) => renderLevel(item, item.targetPrice),
    },
    {
      key: 'horizon',
      header: t('decisionSignals.colHorizon'),
      render: (item) => (
        <span className="inline-flex flex-col leading-tight">
          <span>{getDecisionSignalHorizonLabel(item.horizon, t)}</span>
          <span className="text-xs text-secondary-text">{remainingLabel(item) ?? '—'}</span>
        </span>
      ),
    },
    {
      key: 'reason',
      header: t('decisionSignals.colReason'),
      minWidth: 220,
      render: (item) => (
        <div className="max-w-[22rem]">
          <p className="truncate text-secondary-text">{formatSignalText(item.reason) ?? '—'}</p>
          {renderOlder(item)}
        </div>
      ),
    },
    {
      key: 'source',
      header: t('decisionSignals.colSource'),
      render: (item) => (
        <span className="inline-flex flex-col whitespace-nowrap text-xs leading-tight text-secondary-text">
          <span className="tabular-nums">{formatSignalDateTime(item.createdAt, language)}</span>
          {item.sourceReportId ? (
            <a
              href={sourceReportHref(item.sourceReportId)}
              className="text-cyan hover:underline"
              aria-label={t('decisionSignals.sourceReportLink', { id: item.sourceReportId })}
              onClick={stopRowEvent}
            >
              #{item.sourceReportId}
            </a>
          ) : null}
        </span>
      ),
    },
  ];

  const renderMobileCard = (item: DecisionSignalItem) => {
    const quote = quoteFor(item.stockCode);
    const currency = signalCurrency(item.market);
    const stopDistance = distancePct(item.stopLoss, quote?.currentPrice);
    return (
      <button
        type="button"
        data-testid={`signal-mobile-row-${item.id}`}
        onClick={() => onSelect(item)}
        className="flex min-h-[88px] w-full cursor-pointer flex-col justify-center gap-2 px-3 py-2 text-left"
      >
        <span className="grid grid-cols-[auto_1fr_auto] items-center gap-2">
          <SignalActionTag item={item} />
          <span className="flex min-w-0 items-center gap-1.5">
            {renderHeldDot(item)}
            <span className={cn('min-w-0 truncate font-medium text-foreground', item.market === 'us' && 'font-mono')}>
              {stockPrimaryAndSecondary(item).primary}
            </span>
            {renderStopFlag(item)}
          </span>
          <span className="shrink-0 justify-self-end text-right tabular-nums">
            <span className="text-foreground">{formatPrice(quote?.currentPrice, currency)}</span>{' '}
            <span className={cn('text-xs', marketToneClass(quote?.changePercent))}>{formatPercent(quote?.changePercent)}</span>
          </span>
        </span>
        <span className="flex items-center justify-between gap-2 text-xs tabular-nums text-secondary-text">
          <span className="truncate">
            {t('decisionSignals.stopLoss')} {formatPrice(item.stopLoss, currency)}
            {stopDistance !== null ? `（${formatPercent(stopDistance, 1)}）` : ''}
            {'・'}
            {t('decisionSignals.targetPrice')} {formatPrice(item.targetPrice, currency)}
          </span>
          <span className="shrink-0">{remainingLabel(item) ?? getDecisionSignalHorizonLabel(item.horizon, t)}</span>
        </span>
      </button>
    );
  };

  return (
    <DataTable
      aria-label={t('decisionSignals.title')}
      columns={columns}
      rows={items}
      rowKey={(item) => String(item.id)}
      onRowClick={onSelect}
      renderMobileCard={renderMobileCard}
    />
  );
};

export const DecisionSignalTableSkeleton: React.FC = () => {
  const { t } = useUiLanguage();
  return (
    <div data-testid="signal-table-skeleton" role="status" aria-label={t('decisionSignals.loadingList')} className="space-y-2">
      {[0, 1, 2, 3, 4, 5].map((index) => (
        <div key={index} className="h-[88px] animate-pulse rounded-[var(--radius-card)] bg-elevated/60 md:h-12" />
      ))}
    </div>
  );
};
