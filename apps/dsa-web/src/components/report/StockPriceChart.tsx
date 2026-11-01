import type React from 'react';
import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { stocksApi, type PriceBar } from '../../api/stocks';
import { getReportPolishText, reducesOnBounce, type ReportPolishText } from '../../locales/reportText';
import type { DecisionAction, ReportLanguage, ReportStrategy } from '../../types/analysis';
import { formatNumber, formatPrice } from '../../utils/format';
import { marketToneClass } from '../../utils/marketTone';
import { priceDomain, sliceByRange, withMovingAverages, type ChartBar, type ChartRange } from '../../utils/priceChart';
import { normalizeReportLanguage } from '../../utils/reportLanguage';
import { Card, Segmented } from '../common';
import { DashboardPanelHeader } from '../dashboard';

interface StockPriceChartProps {
  stockCode: string;
  contextSnapshot?: Record<string, unknown> | null;
  strategy?: ReportStrategy | null;
  currency?: string | null;
  language?: ReportLanguage;
  /** 無新聞護欄擋下時不畫停損目標線。 */
  hideLevels?: boolean;
  /** 減碼／觀望類動作時，目標線改叫「反彈減碼」。 */
  action?: DecisionAction | null;
}

const TEXT = {
  zh: {
    title: '价格走势', range: '区间', m1: '1月', m3: '3月', y1: '1年', stop: '停损', target: '目标',
    open: '开盘', high: '最高', low: '最低', close: '收盘', volume: '成交量', amount: '成交额', volumeRatio: '量比', pe: '本益比', foreign: '外资', trust: '投信',
  },
  en: {
    title: 'Price Chart', range: 'Range', m1: '1M', m3: '3M', y1: '1Y', stop: 'Stop', target: 'Target',
    open: 'Open', high: 'High', low: 'Low', close: 'Close', volume: 'Volume', amount: 'Turnover', volumeRatio: 'Vol ratio', pe: 'P/E', foreign: 'Foreign', trust: 'Trust',
  },
  'zh-TW': {
    title: '價格走勢', range: '區間', m1: '1月', m3: '3月', y1: '1年', stop: '停損', target: '目標',
    open: '開盤', high: '最高', low: '最低', close: '收盤', volume: '成交量', amount: '成交額', volumeRatio: '量比', pe: '本益比', foreign: '外資', trust: '投信',
  },
  ko: {
    title: '가격 차트', range: '기간', m1: '1개월', m3: '3개월', y1: '1년', stop: '손절', target: '목표',
    open: '시가', high: '고가', low: '저가', close: '종가', volume: '거래량', amount: '거래대금', volumeRatio: '거래량 비율', pe: 'PER', foreign: '외국인', trust: '투신',
  },
} as const;

const AXIS_WIDTH = 56;
const CHART_MARGIN = { top: 8, right: 0, bottom: 0, left: 0 };

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};

const readNumber = (source: Record<string, unknown>, key: string): number | null => {
  const value = source[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
};

type CandleShapeProps = {
  x: number;
  y: number;
  width: number;
  height: number;
  payload: ChartBar;
  /** Plot-area band recharts passes to each bar; used to keep candles inside the chart. */
  background?: { y?: number; height?: number };
};

// recharts 的 range bar 給的是 low～high 的矩形，開收盤的位置由這段比例換算。
const renderCandle = (raw: unknown): React.ReactElement => {
  const { x, y, width, height, payload, background } = raw as CandleShapeProps;
  const { open, high, low, close } = payload;
  const unit = high > low ? height / (high - low) : 0;
  const yOf = (value: number) => y + (high - value) * unit;
  const color = close > open ? 'var(--market-up)' : close < open ? 'var(--market-down)' : 'var(--text-muted-text)';
  const center = x + width / 2;
  // Clamp to the plot area so a bar outside the price domain never floats above or below the chart.
  const top = typeof background?.y === 'number' ? background.y : -Infinity;
  const bottom = typeof background?.y === 'number' && typeof background.height === 'number'
    ? background.y + background.height
    : Infinity;
  const clamp = (value: number) => Math.min(Math.max(value, top), bottom);
  const wickTop = clamp(y);
  const wickBottom = clamp(y + height);
  const bodyTop = clamp(yOf(Math.max(open, close)));
  const bodyBottom = clamp(yOf(Math.max(open, close)) + Math.max(Math.abs(open - close) * unit, 1));
  return (
    <g>
      {wickBottom > wickTop ? <line x1={center} x2={center} y1={wickTop} y2={wickBottom} stroke={color} strokeWidth={1} /> : null}
      {bodyBottom > bodyTop ? (
        <rect x={x} y={bodyTop} width={Math.max(width, 1)} height={bodyBottom - bodyTop} fill={color} />
      ) : null}
    </g>
  );
};

type LabelViewBox = { x?: number; y?: number; width?: number; height?: number };

// Rough glyph widths at 11px: CJK is about one em, Latin about 0.6 em.
const estimateLabelWidth = (value: string): number =>
  Array.from(value).reduce((sum, char) => sum + (char.charCodeAt(0) > 0x2e7f ? 11 : 6.6), 0);

/** Reference-line label pinned inside the right edge, on a translucent plate so candles stay readable. */
const levelLabel = (value: string, color: string) => {
  // recharts passes a cartesian viewBox for reference lines; typed loosely to match its union.
  const renderLabel = (props: { viewBox?: unknown }) => {
    const { x = 0, y = 0, width = 0 } = (props.viewBox ?? {}) as LabelViewBox;
    const textWidth = estimateLabelWidth(value);
    const right = x + width - 4;
    return (
      <g>
        <rect x={right - textWidth - 8} y={y - 9} width={textWidth + 8} height={18} rx={4} fill="hsl(var(--card))" fillOpacity={0.85} />
        <text x={right - 4} y={y} dy={4} textAnchor="end" fontSize={11} fill={color}>{value}</text>
      </g>
    );
  };
  return renderLabel;
};

const TW_CODE = /\.(TW|TWO)$/i;

/**
 * Compact a count for a narrow cell. CJK: 萬 / 億 with about three significant digits, unit glued on
 * ("3.66 萬張"). English: K/M/B. Small values stay grouped integers ("−8,633 張").
 */
const compactWithUnit = (value: number, unit: string, polish: ReportPolishText, cjk: boolean): string => {
  const abs = Math.abs(value);
  const tail = unit ? ` ${unit}` : '';
  if (cjk) {
    if (abs >= 1e8) return `${formatNumber(value / 1e8, abs >= 1e9 ? 1 : 2)} ${polish.unitYi}${unit}`;
    if (abs >= 1e4) {
      // Keep about three significant digits: 3.66 萬, 36.6 萬, 366 萬, 3,660 萬.
      const digits = abs >= 1e6 ? 0 : abs >= 1e5 ? 1 : 2;
      return `${formatNumber(value / 1e4, digits)} ${polish.unitWan}${unit}`;
    }
    return `${formatNumber(value, 0)}${tail}`;
  }
  if (abs >= 1e9) return `${formatNumber(value / 1e9, 2)}B${tail}`;
  if (abs >= 1e6) return `${formatNumber(value / 1e6, 2)}M${tail}`;
  if (abs >= 1e4) return `${formatNumber(value / 1e3, 1)}K${tail}`;
  return `${formatNumber(value, 0)}${tail}`;
};

const candleRange = (bar: ChartBar): [number, number] => [bar.low, bar.high];

const shortDateTick = (value: string): string => {
  const parts = String(value).slice(0, 10).split('-');
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : String(value);
};

/**
 * 報告的日 K：用完整序列算均線再切區間；沒有 K 線也沒有關鍵數字時整區不顯示。
 */
export const StockPriceChart: React.FC<StockPriceChartProps> = ({
  stockCode,
  contextSnapshot,
  strategy,
  currency,
  language = 'zh',
  hideLevels = false,
  action,
}) => {
  const reportLanguage = normalizeReportLanguage(language);
  const text = TEXT[reportLanguage];
  const polish = getReportPolishText(reportLanguage);
  const cjk = reportLanguage === 'zh' || reportLanguage === 'zh-TW';
  const isTw = TW_CODE.test(stockCode.trim());
  const targetName = reducesOnBounce(action) ? polish.chartReboundReduce : text.target;
  const [loaded, setLoaded] = useState<{ code: string; bars: PriceBar[] } | null>(null);
  const [range, setRange] = useState<ChartRange>('3m');

  useEffect(() => {
    let active = true;
    stocksApi.getDailyHistory(stockCode)
      .then((bars) => {
        if (active) setLoaded({ code: stockCode, bars });
      })
      .catch(() => {
        // K 線只是輔助：抓不到就收起圖，不影響報告其他區塊。
        if (active) setLoaded({ code: stockCode, bars: [] });
      });
    return () => {
      active = false;
    };
  }, [stockCode]);

  const allBars = useMemo(
    () => (loaded?.code === stockCode ? withMovingAverages(loaded.bars) : []),
    [loaded, stockCode],
  );
  const visibleBars = useMemo(() => sliceByRange(allBars, range), [allBars, range]);

  const prices = strategy?.sniperPricesSource === 'structured' && !hideLevels ? strategy.sniperPrices : null;
  const stop = typeof prices?.stopLoss === 'number' ? prices.stopLoss : null;
  const target = typeof prices?.takeProfit === 'number' ? prices.takeProfit : null;
  const domain = priceDomain(visibleBars, [stop, target].filter((level): level is number => level !== null));
  const currencyCode = currency ?? undefined;

  const enhanced = asRecord(contextSnapshot?.enhancedContext);
  const today = asRecord(enhanced.today);
  const realtime = asRecord(enhanced.realtime);
  const institutionBlock = asRecord(asRecord(enhanced.fundamentalContext).institution);
  const institution = institutionBlock.status === 'ok' ? asRecord(institutionBlock.data) : {};
  const metrics: Array<{ key: string; label: string; unit?: string; value: string; toneClass?: string }> = [];
  const pushMetric = (
    key: string,
    label: string,
    value: number | null,
    format: (reading: number) => string,
    unit?: string,
    toneClass?: string,
  ) => {
    if (value !== null) metrics.push({ key, label, unit, value: format(value), toneClass });
  };
  const asPrice = (reading: number) => formatPrice(reading, currencyCode);
  const asDecimal = (reading: number) => formatNumber(reading, 2);
  // Snapshot volume and institutional nets are in shares; Taiwan quotes them in lots of 1,000.
  const shareUnit = isTw ? polish.unitLots : polish.unitShares;
  const toShareUnit = (shares: number) => (isTw ? shares / 1000 : shares);
  const asVolume = (shares: number) => compactWithUnit(toShareUnit(shares), shareUnit, polish, cjk);
  const asAmount = (amount: number) => compactWithUnit(amount, '', polish, cjk);
  const asNet = (shares: number) => `${formatNumber(toShareUnit(shares), 0)} ${shareUnit}`;
  pushMetric('open', text.open, readNumber(today, 'open'), asPrice, currencyCode);
  pushMetric('high', text.high, readNumber(today, 'high'), asPrice, currencyCode);
  pushMetric('low', text.low, readNumber(today, 'low'), asPrice, currencyCode);
  pushMetric('volume', text.volume, readNumber(today, 'volume'), asVolume, shareUnit);
  pushMetric('amount', text.amount, readNumber(today, 'amount'), asAmount, currencyCode);
  pushMetric('volumeRatio', text.volumeRatio, readNumber(realtime, 'volumeRatio'), asDecimal, polish.unitTimes);
  pushMetric('pe', text.pe, readNumber(realtime, 'peRatio'), asDecimal, polish.unitTimes);
  const foreignNet = readNumber(institution, 'foreignNet');
  const trustNet = readNumber(institution, 'trustNet');
  pushMetric('foreign', text.foreign, foreignNet, asNet, shareUnit, marketToneClass(foreignNet));
  pushMetric('trust', text.trust, trustNet, asNet, shareUnit, marketToneClass(trustNet));

  if (visibleBars.length === 0 && metrics.length === 0) {
    return null;
  }

  return (
    <Card variant="surface" padding="md" className="home-panel-card min-w-0">
      <section data-testid="stock-price-chart" className="min-w-0">
        {visibleBars.length > 0 && domain ? (
          <>
            <DashboardPanelHeader
              title={text.title}
              className="mb-2"
              actions={(
                <Segmented<ChartRange>
                  size="sm"
                  aria-label={text.range}
                  value={range}
                  onChange={setRange}
                  options={[
                    { value: '1m', label: text.m1 },
                    { value: '3m', label: text.m3 },
                    { value: '1y', label: text.y1 },
                  ]}
                />
              )}
            />
            <div className="h-64 w-full min-w-0">
              <ResponsiveContainer width="100%" height="100%">
                {/* recharts clips bars and lines to the plot area via YAxis allowDataOverflow; renderCandle also clamps */}
                <ComposedChart data={visibleBars} syncId="report-price" margin={CHART_MARGIN}>
                  <XAxis dataKey="date" hide />
                  <YAxis
                    orientation="right"
                    width={AXIS_WIDTH}
                    domain={domain}
                    allowDataOverflow
                    tick={{ fontSize: 11 }}
                    tickFormatter={(value: number) => formatPrice(value, currencyCode)}
                  />
                  <Tooltip
                    content={({ active, payload }) => {
                      const bar = payload?.[0]?.payload as ChartBar | undefined;
                      if (!active || !bar) return null;
                      return (
                        <div className="rounded-lg border border-border/70 bg-card px-3 py-2 text-xs tabular-nums text-foreground shadow-soft-card">
                          <p className="mb-1 text-secondary-text">{String(bar.date).slice(0, 10)}</p>
                          <p>{text.open} {asPrice(bar.open)}{' '}{text.close} {asPrice(bar.close)}</p>
                          <p>{text.high} {asPrice(bar.high)}{' '}{text.low} {asPrice(bar.low)}</p>
                          {bar.ma20 !== null ? <p>MA20 {asPrice(bar.ma20)}</p> : null}
                          {bar.ma60 !== null ? <p>MA60 {asPrice(bar.ma60)}</p> : null}
                        </div>
                      );
                    }}
                  />
                  <Bar dataKey={candleRange} shape={renderCandle} isAnimationActive={false} />
                  <Line dataKey="ma20" stroke="var(--color-cyan)" strokeWidth={1} dot={false} connectNulls={false} isAnimationActive={false} />
                  <Line dataKey="ma60" stroke="hsl(var(--muted-text))" strokeWidth={1} dot={false} connectNulls={false} isAnimationActive={false} />
                  {stop !== null ? (
                    <ReferenceLine
                      y={stop}
                      stroke="hsl(var(--warning))"
                      strokeDasharray="4 3"
                      label={levelLabel(`${text.stop} ${asPrice(stop)}`, 'hsl(var(--warning))')}
                    />
                  ) : null}
                  {target !== null ? (
                    <ReferenceLine
                      y={target}
                      stroke="hsl(var(--muted-text))"
                      strokeDasharray="4 3"
                      label={levelLabel(`${targetName} ${asPrice(target)}`, 'hsl(var(--muted-text))')}
                    />
                  ) : null}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="h-20 w-full min-w-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={visibleBars} syncId="report-price" margin={CHART_MARGIN}>
                  <XAxis dataKey="date" tickFormatter={shortDateTick} minTickGap={32} tick={{ fontSize: 11 }} />
                  <YAxis orientation="right" width={AXIS_WIDTH} tick={false} axisLine={false} />
                  <Bar dataKey="volume" fill="hsl(var(--muted-text))" fillOpacity={0.5} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </>
        ) : null}
        {metrics.length > 0 ? (
          <dl data-testid="stock-key-numbers" className="mt-3 grid grid-cols-3 gap-x-4 gap-y-2 text-sm md:grid-cols-4 xl:grid-cols-5">
            {metrics.map((metric) => (
              <div key={metric.key} className="min-w-0">
                <dt className="text-xs text-muted-text">
                  {metric.label}
                  {metric.unit ? <span className="block text-[11px] leading-4 text-muted-text/80">{metric.unit}</span> : null}
                </dt>
                <dd
                  data-testid={`key-number-${metric.key}`}
                  className={`whitespace-nowrap font-medium tabular-nums ${metric.toneClass ?? 'text-foreground'}`}
                >
                  {metric.value}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
      </section>
    </Card>
  );
};
