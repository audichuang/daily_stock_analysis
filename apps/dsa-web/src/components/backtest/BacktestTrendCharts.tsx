import type React from 'react';
import { useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { formatUiText } from '../../i18n/uiText';
import { BACKTEST_OVERVIEW_TEXT } from '../../locales/featureText';
import { SIGNALS_TEXT } from '../../locales/signalsText';
import type { BacktestSeriesResponse } from '../../types/backtest';
import { formatDateTime, formatNumber, formatPercent } from '../../utils/format';
import { Segmented } from '../common';

// 兩條線都不是行情方向，不用紅綠：模擬用品牌色、個股用灰。
const SIMULATED_COLOR = '#0891b2';
const STOCK_COLOR = '#64748b';
const GRID_COLOR = 'rgba(148, 163, 184, 0.18)';
const AXIS_COLOR = 'rgba(148, 163, 184, 0.5)';

interface BacktestTrendChartsProps {
  series: BacktestSeriesResponse | null;
  /** 序列端點不支援階段篩選：有套用階段時要明說圖不受它影響。 */
  phaseFiltered: boolean;
  /** 序列沒有評估時間時退回績效彙總的計算時間。 */
  fallbackUpdatedAt?: string | null;
}

type LineMode = 'simulated' | 'withStock';

const shortDate = (value: string): string => value.slice(5).replace('-', '/');
const percentTick = (value: number): string => `${formatNumber(value, 0)}%`;
// Cumulative returns can reach thousands of percent; abbreviate so the 60px axis keeps the sign visible.
const cumulativeTick = (value: number): string => (
  Math.abs(value) >= 1000 ? `${formatNumber(value / 1000, 1)}k%` : percentTick(value)
);
const MONTH_SHORT_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** 無資料整塊不渲染：沒有已完成回測時，空的圖沒有資訊。 */
export const BacktestTrendCharts: React.FC<BacktestTrendChartsProps> = ({ series, phaseFiltered, fallbackUpdatedAt }) => {
  const { language } = useUiLanguage();
  const text = BACKTEST_OVERVIEW_TEXT[language];
  const signalsText = SIGNALS_TEXT[language];
  const [lineMode, setLineMode] = useState<LineMode>('simulated');
  const points = series?.points ?? [];
  const monthly = (series?.monthly ?? []).filter((month) => typeof month.winRatePct === 'number');
  if (points.length === 0 && monthly.length === 0) return null;

  // 舊後端沒有個股累計欄位，或這批列全無個股報酬時不畫第二條線。
  const hasStockLine = points.some((point) => typeof point.stockReturnPct === 'number');
  const updatedAt = series?.updatedAt ?? fallbackUpdatedAt;
  const showStockLine = hasStockLine && lineMode === 'withStock';
  // "2026-07" -> "7月" (zh) / "Jul" (en).
  const monthTick = (value: string): string => {
    const month = Number(value.slice(5, 7));
    if (!Number.isInteger(month) || month < 1 || month > 12) return value;
    return formatUiText(signalsText.monthTick, { month, monthShort: MONTH_SHORT_EN[month - 1] });
  };

  return (
    <section data-testid="backtest-trend" aria-label={text.chartTitle} className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">{text.chartTitle}</h2>
        {updatedAt ? (
          <span data-testid="backtest-trend-updated" className="text-xs text-secondary-text">
            {text.updatedAt.replace('{time}', formatDateTime(updatedAt))}
          </span>
        ) : null}
      </div>
      {series?.truncated ? <p className="text-xs text-warning">{text.chartTruncated}</p> : null}
      {phaseFiltered ? <p className="text-xs text-secondary-text">{text.chartPhaseIgnored}</p> : null}
      <div className="grid gap-3 lg:grid-cols-3">
        {points.length > 0 ? (
          <div className="flex h-56 min-w-0 flex-col lg:col-span-2">
            {/* Legend sits above the plot so it never overlaps the lines or the x axis. */}
            <div data-testid="backtest-trend-legend" className="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs text-secondary-text">
              <span className="flex flex-wrap gap-3">
                <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-3" style={{ backgroundColor: SIMULATED_COLOR }} />{text.chartSimulated}</span>
                {showStockLine ? (
                  <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-3" style={{ backgroundColor: STOCK_COLOR }} />{text.chartStock}</span>
                ) : null}
              </span>
              {hasStockLine ? (
                <Segmented<LineMode>
                  aria-label={signalsText.chartLineMode}
                  size="sm"
                  value={lineMode}
                  onChange={setLineMode}
                  options={[
                    { value: 'simulated', label: signalsText.chartSimulatedOnly },
                    { value: 'withStock', label: signalsText.chartWithStock },
                  ]}
                />
              ) : null}
            </div>
            <div className="min-h-0 flex-1">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke={GRID_COLOR} vertical={false} />
                  <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 11, fill: 'currentColor' }} stroke={AXIS_COLOR} minTickGap={32} />
                  <YAxis tickFormatter={cumulativeTick} tick={{ fontSize: 11, fill: 'currentColor' }} stroke={AXIS_COLOR} width={60} />
                  <ReferenceLine y={0} stroke={AXIS_COLOR} />
                  <ChartTooltip formatter={(value: unknown) => formatPercent(Number(value))} />
                  <Line type="monotone" dataKey="cumulativeReturnPct" name={text.chartSimulated} stroke={SIMULATED_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} />
                  {showStockLine ? (
                    <Line type="monotone" dataKey="cumulativeStockReturnPct" name={text.chartStock} stroke={STOCK_COLOR} strokeWidth={1.5} dot={false} isAnimationActive={false} />
                  ) : null}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        ) : null}
        {monthly.length > 0 ? (
          <div data-testid="backtest-monthly" className="h-56 min-w-0">
            <p className="mb-1 text-xs text-secondary-text">{text.monthlyWinRate}</p>
            <ResponsiveContainer width="100%" height="90%">
              <BarChart data={monthly} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={GRID_COLOR} vertical={false} />
                <XAxis dataKey="month" tickFormatter={monthTick} tick={{ fontSize: 11, fill: 'currentColor' }} stroke={AXIS_COLOR} />
                <YAxis domain={[0, 100]} tickFormatter={percentTick} tick={{ fontSize: 11, fill: 'currentColor' }} stroke={AXIS_COLOR} width={44} />
                <ChartTooltip formatter={(value: unknown) => `${formatNumber(Number(value), 1)}%`} />
                <Bar dataKey="winRatePct" name={text.monthlyWinRate} fill={SIMULATED_COLOR} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : null}
      </div>
    </section>
  );
};
