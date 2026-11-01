import type React from 'react';
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
import { BACKTEST_OVERVIEW_TEXT } from '../../locales/featureText';
import type { BacktestSeriesResponse } from '../../types/backtest';
import { formatDateTime, formatNumber, formatPercent } from '../../utils/format';

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

const shortDate = (value: string): string => value.slice(5).replace('-', '/');
const percentTick = (value: number): string => `${formatNumber(value, 0)}%`;

/** 無資料整塊不渲染：沒有已完成回測時，空的圖沒有資訊。 */
export const BacktestTrendCharts: React.FC<BacktestTrendChartsProps> = ({ series, phaseFiltered, fallbackUpdatedAt }) => {
  const { language } = useUiLanguage();
  const text = BACKTEST_OVERVIEW_TEXT[language];
  const points = series?.points ?? [];
  const monthly = (series?.monthly ?? []).filter((month) => typeof month.winRatePct === 'number');
  if (points.length === 0 && monthly.length === 0) return null;

  // 舊後端沒有個股累計欄位，或這批列全無個股報酬時不畫第二條線。
  const hasStockLine = points.some((point) => typeof point.stockReturnPct === 'number');
  const updatedAt = series?.updatedAt ?? fallbackUpdatedAt;

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
          <div className="h-56 min-w-0 lg:col-span-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={GRID_COLOR} vertical={false} />
                <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 11, fill: 'currentColor' }} stroke={AXIS_COLOR} minTickGap={32} />
                <YAxis tickFormatter={percentTick} tick={{ fontSize: 11, fill: 'currentColor' }} stroke={AXIS_COLOR} width={48} />
                <ReferenceLine y={0} stroke={AXIS_COLOR} />
                <ChartTooltip formatter={(value: unknown) => formatPercent(Number(value))} />
                <Line type="monotone" dataKey="cumulativeReturnPct" name={text.chartSimulated} stroke={SIMULATED_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} />
                {hasStockLine ? (
                  <Line type="monotone" dataKey="cumulativeStockReturnPct" name={text.chartStock} stroke={STOCK_COLOR} strokeWidth={1.5} dot={false} isAnimationActive={false} />
                ) : null}
              </LineChart>
            </ResponsiveContainer>
            <div className="mt-1 flex flex-wrap gap-3 text-xs text-secondary-text">
              <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-3" style={{ backgroundColor: SIMULATED_COLOR }} />{text.chartSimulated}</span>
              {hasStockLine ? (
                <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-3" style={{ backgroundColor: STOCK_COLOR }} />{text.chartStock}</span>
              ) : null}
            </div>
          </div>
        ) : null}
        {monthly.length > 0 ? (
          <div data-testid="backtest-monthly" className="h-56 min-w-0">
            <p className="mb-1 text-xs text-secondary-text">{text.monthlyWinRate}</p>
            <ResponsiveContainer width="100%" height="90%">
              <BarChart data={monthly} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={GRID_COLOR} vertical={false} />
                <XAxis dataKey="month" tickFormatter={(value: string) => value.slice(2)} tick={{ fontSize: 11, fill: 'currentColor' }} stroke={AXIS_COLOR} />
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
