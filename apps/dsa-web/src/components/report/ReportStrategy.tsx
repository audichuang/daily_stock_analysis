import { Bell } from 'lucide-react';
import type React from 'react';
import { Link } from 'react-router-dom';
import { getReportPolishText, reducesOnBounce, type ReportPolishText } from '../../locales/reportText';
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
  /** 有代號才顯示一鍵設警報的鈴鐺。 */
  stockCode?: string | null;
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

// Grid columns follow how many level cards are shown.
const LEVEL_GRID_COLS: Record<number, string> = { 1: '', 2: 'xl:grid-cols-2', 3: 'xl:grid-cols-3', 4: 'xl:grid-cols-4' };

// Levels that get a one-tap price alert (secondaryBuy is skipped on purpose).
const ALERT_LEVELS: ReadonlySet<LevelKey> = new Set<LevelKey>(['stopLoss', 'takeProfit', 'idealBuy']);

/** Stop loss always alerts on a cross below; other levels compare with the current price. */
const alertDirection = (key: LevelKey, value: number, price: number | null): 'above' | 'below' => {
  if (key === 'stopLoss') return 'below';
  return price !== null && value > price ? 'above' : 'below';
};

const buildAlertHref = (code: string, key: LevelKey, value: number, price: number | null): string => {
  const params = [
    'new=1',
    `target=${encodeURIComponent(code)}`,
    'type=price_cross',
    `direction=${alertDirection(key, value, price)}`,
    `price=${encodeURIComponent(String(value))}`,
  ];
  return `/alerts?${params.join('&')}`;
};

const finite = (value?: number | null): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

interface LevelLadderProps {
  stop: number | null;
  price: number;
  target: number | null;
  currency?: string;
  text: ReportText;
  polish: ReportPolishText;
  stopLabel: string;
  targetLabel: string;
  /** Short names for narrow screens. */
  stopShort: string;
  targetShort: string;
}

type LadderPoint = { key: string; label: string; short: string; value: number; current: boolean };

/** 橫向階梯只表達相對位置，中性色，不用紅綠。 */
const LevelLadder: React.FC<LevelLadderProps> = ({
  stop, price, target, currency, text, polish, stopLabel, targetLabel, stopShort, targetShort,
}) => {
  const points = [
    stop !== null ? { key: 'stop', label: stopLabel, short: stopShort, value: stop, current: false } : null,
    { key: 'price', label: text.levelCurrent, short: polish.ladderCurrentShort, value: price, current: true },
    target !== null ? { key: 'target', label: targetLabel, short: targetShort, value: target, current: false } : null,
  ]
    .filter((point): point is LadderPoint => point !== null)
    .sort((a, b) => a.value - b.value);
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const span = Math.max(...values) - min;
  const positionOf = (value: number) => (span > 0 ? 8 + ((value - min) / span) * 84 : 50);

  return (
    <div data-testid="level-ladder" className="relative mt-4 h-16">
      <span className="absolute inset-x-0 top-1/2 h-px bg-border" />
      {points.map((point, index) => {
        // Edge points anchor inward so their labels never spill past the card.
        const isFirst = points.length > 1 && index === 0;
        const isLast = points.length > 1 && index === points.length - 1;
        const anchor = isFirst
          ? 'translate-x-0 items-start'
          : isLast
            ? '-translate-x-full items-end'
            : '-translate-x-1/2 items-center';
        return (
        <div
          key={point.key}
          data-testid={`ladder-${point.key}`}
          className={`absolute top-0 flex h-full ${anchor} flex-col justify-between whitespace-nowrap text-xs`}
          style={{ left: `${positionOf(point.value)}%` }}
        >
          <span className={point.current ? 'font-semibold text-foreground' : 'text-secondary-text'}>
            <span className="md:hidden">{point.short}</span>
            <span className="hidden md:inline">{point.label}</span>
          </span>
          <span
            className={point.current ? 'h-3 w-3 rounded-full' : 'h-3 w-1 rounded-full'}
            style={{ backgroundColor: point.current ? 'hsl(var(--foreground))' : 'var(--text-muted-text)' }}
          />
          <span className="tabular-nums text-secondary-text">{formatPrice(point.value, currency)}</span>
        </div>
        );
      })}
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
  stockCode,
}) => {
  if (!strategy) {
    return null;
  }

  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const polish = getReportPolishText(reportLanguage);
  const code = stockCode?.trim() || null;
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
      <div
        data-testid="levels-grid"
        className={`grid grid-cols-1 gap-3 ${present.length > 1 ? 'md:grid-cols-2' : ''} ${LEVEL_GRID_COLS[present.length] ?? ''}`.replace(/\s+/g, ' ').trim()}
      >
        {present.map((level) => {
          // raw 就只是同一個數字時不當理由重印。
          const reason = level.value !== null && level.raw && Number(level.raw) !== level.value ? level.raw : null;
          // Only structured numbers are trusted enough to prefill an alert; legacy text never is.
          const alertHref = structured && code && level.value !== null && ALERT_LEVELS.has(level.key)
            ? buildAlertHref(code, level.key, level.value, priceBase)
            : null;
          return (
            <div key={level.key} data-testid={`level-${level.key}`} className="home-subpanel relative min-w-0 p-3">
              <p className={`text-xs text-secondary-text ${alertHref ? 'pr-8' : ''}`.trim()}>{level.label}</p>
              {alertHref ? (
                <Link
                  to={alertHref}
                  data-testid={`level-alert-${level.key}`}
                  aria-label={polish.setAlertFor.replace('{label}', level.label).replace('{price}', formatPrice(level.value, currencyCode))}
                  title={polish.setAlert}
                  className="absolute right-2 top-2 inline-flex h-7 w-7 items-center justify-center rounded-md text-secondary-text transition-colors hover:bg-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan/40"
                >
                  <Bell className="h-4 w-4" aria-hidden="true" />
                </Link>
              ) : null}
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
          polish={polish}
          stopLabel={labelOf('stopLoss') ?? text.levelStopLoss}
          targetLabel={labelOf('takeProfit') ?? text.levelTarget}
          stopShort={polish.ladderStopShort}
          targetShort={reducesOnBounce(action) ? polish.ladderReduceShort : polish.ladderTargetShort}
        />
      ) : null}
    </Card>
  );
};
