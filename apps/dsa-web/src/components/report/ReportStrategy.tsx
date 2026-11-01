import type React from 'react';
import type { DecisionAction, ReportLanguage, ReportStrategy as ReportStrategyType, SniperPrices } from '../../types/analysis';
import { formatPercent, formatPrice } from '../../utils/format';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';

interface ReportStrategyProps {
  strategy?: ReportStrategyType;
  language?: ReportLanguage;
  /** 結構化動作決定顯示哪幾格；舊報告沒有動作時四格都列。 */
  action?: DecisionAction | null;
  currentPrice?: number | null;
  currency?: string | null;
}

type LevelKey = keyof SniperPrices;
type ReportText = ReturnType<typeof getReportText>;

const levelsForAction = (action: DecisionAction | null | undefined, text: ReportText): Array<[LevelKey, string]> => {
  const entryLevels: Array<[LevelKey, string]> = [
    ['idealBuy', text.levelEntry],
    ['secondaryBuy', text.levelAdd],
    ['stopLoss', text.levelStopLoss],
    ['takeProfit', text.levelTarget],
  ];
  switch (action) {
    case 'buy':
    case 'add':
      return entryLevels;
    case 'hold':
      return [['stopLoss', text.levelRiskLine], ['takeProfit', text.levelTarget]];
    case 'reduce':
    case 'sell':
    case 'watch':
    case 'avoid':
    case 'alert':
      return [['stopLoss', text.levelRiskLine], ['takeProfit', text.levelReduce]];
    default:
      return entryLevels;
  }
};

const finite = (value?: number | null): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

interface LevelLadderProps {
  stop: number | null;
  price: number;
  target: number | null;
  currency?: string;
  text: ReportText;
  stopLabel: string;
  targetLabel: string;
}

/** 橫向階梯只表達相對位置，中性色，不用紅綠。 */
const LevelLadder: React.FC<LevelLadderProps> = ({ stop, price, target, currency, text, stopLabel, targetLabel }) => {
  const points = [
    stop !== null ? { key: 'stop', label: stopLabel, value: stop, current: false } : null,
    { key: 'price', label: text.levelCurrent, value: price, current: true },
    target !== null ? { key: 'target', label: targetLabel, value: target, current: false } : null,
  ].filter((point): point is { key: string; label: string; value: number; current: boolean } => point !== null);
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const span = Math.max(...values) - min;
  const positionOf = (value: number) => (span > 0 ? 8 + ((value - min) / span) * 84 : 50);

  return (
    <div data-testid="level-ladder" className="relative mt-4 h-16">
      <span className="absolute inset-x-0 top-1/2 h-px bg-border" />
      {points.map((point) => (
        <div
          key={point.key}
          data-testid={`ladder-${point.key}`}
          className="absolute top-0 flex h-full -translate-x-1/2 flex-col items-center justify-between text-xs"
          style={{ left: `${positionOf(point.value)}%` }}
        >
          <span className={point.current ? 'font-semibold text-foreground' : 'text-secondary-text'}>{point.label}</span>
          <span
            className={point.current ? 'h-3 w-3 rounded-full' : 'h-3 w-1 rounded-full'}
            style={{ backgroundColor: point.current ? 'hsl(var(--foreground))' : 'var(--text-muted-text)' }}
          />
          <span className="tabular-nums text-secondary-text">{formatPrice(point.value, currency)}</span>
        </div>
      ))}
    </div>
  );
};

/**
 * 關鍵價位：依結構化動作切換格子。只有 structured 的數字才算距現價與階梯；
 * legacy 的長句不解析，顯示原文。
 */
export const ReportStrategy: React.FC<ReportStrategyProps> = ({
  strategy,
  language = 'zh',
  action,
  currentPrice,
  currency,
}) => {
  if (!strategy) {
    return null;
  }

  const text = getReportText(normalizeReportLanguage(language));
  const structured = strategy.sniperPricesSource === 'structured';
  const price = finite(currentPrice);
  const priceBase = price !== null && price > 0 ? price : null;
  const currencyCode = currency ?? undefined;
  const numberOf = (key: LevelKey) => (structured ? finite(strategy.sniperPrices?.[key]) : null);
  const levels = levelsForAction(action, text).map(([key, label]) => {
    const raw = strategy[key]?.trim() || null;
    return { key, label, raw, value: numberOf(key) };
  });
  const present = levels.filter((level) => level.value !== null || level.raw);
  const missing = levels.filter((level) => level.value === null && !level.raw);

  if (present.length === 0) {
    return null;
  }

  const labelOf = (key: LevelKey) => levels.find((level) => level.key === key)?.label;
  const stop = numberOf('stopLoss');
  const target = numberOf('takeProfit');
  const showLadder = priceBase !== null && (stop !== null || target !== null);

  return (
    <Card variant="surface" padding="md" className="home-panel-card">
      <DashboardPanelHeader title={text.levelsTitle} className="mb-3" />
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        {present.map((level) => {
          // raw 就只是同一個數字時不當理由重印。
          const reason = level.value !== null && level.raw && Number(level.raw) !== level.value ? level.raw : null;
          return (
            <div key={level.key} data-testid={`level-${level.key}`} className="home-subpanel min-w-0 p-3">
              <p className="text-xs text-secondary-text">{level.label}</p>
              {level.value !== null ? (
                <>
                  <p className="mt-1 text-2xl font-bold tabular-nums text-foreground">
                    {formatPrice(level.value, currencyCode)}
                  </p>
                  {priceBase !== null ? (
                    <p className="mt-0.5 text-xs tabular-nums text-secondary-text">
                      {text.levelFromPrice} {formatPercent(((level.value - priceBase) / priceBase) * 100)}
                    </p>
                  ) : null}
                  {reason ? <p className="mt-1 text-xs leading-5 text-muted-text">{reason}</p> : null}
                </>
              ) : (
                <p className="mt-1 break-words text-sm leading-6 text-foreground">{level.raw}</p>
              )}
            </div>
          );
        })}
      </div>
      {missing.length > 0 ? (
        <p data-testid="levels-missing" className="mt-2 text-xs text-muted-text">
          {text.levelNotProvided}：{missing.map((level) => level.label).join('、')}
        </p>
      ) : null}
      {showLadder && priceBase !== null ? (
        <LevelLadder
          stop={stop}
          price={priceBase}
          target={target}
          currency={currencyCode}
          text={text}
          stopLabel={labelOf('stopLoss') ?? text.levelStopLoss}
          targetLabel={labelOf('takeProfit') ?? text.levelTarget}
        />
      ) : null}
    </Card>
  );
};
