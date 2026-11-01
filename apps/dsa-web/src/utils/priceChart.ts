import type { PriceBar } from '../api/stocks';

export type ChartRange = '1m' | '3m' | '1y';

export type ChartBar = PriceBar & {
  /** 前面列數不足時為 null：起始段留白，不補值。 */
  ma20: number | null;
  ma60: number | null;
};

const RANGE_MONTHS: Record<ChartRange, number> = { '1m': 1, '3m': 3, '1y': 12 };

const movingAverage = (closes: number[], window: number): Array<number | null> => {
  let sum = 0;
  return closes.map((close, index) => {
    sum += close;
    if (index >= window) sum -= closes[index - window];
    return index >= window - 1 ? sum / window : null;
  });
};

/** 要用完整序列算，再切區間：這樣「1 年」最左端的 MA60 才有值。 */
export const withMovingAverages = (bars: PriceBar[]): ChartBar[] => {
  const ordered = [...bars].sort((a, b) => a.date.localeCompare(b.date));
  const closes = ordered.map((bar) => bar.close);
  const ma20 = movingAverage(closes, 20);
  const ma60 = movingAverage(closes, 60);
  return ordered.map((bar, index) => ({ ...bar, ma20: ma20[index], ma60: ma60[index] }));
};

/** 依最後一根 K 的日期往回算日曆月，不用裝置時鐘：休市或資料停更時區間仍是滿的。 */
export const sliceByRange = (bars: ChartBar[], range: ChartRange): ChartBar[] => {
  const last = bars[bars.length - 1];
  if (!last) return [];
  const cutoff = new Date(`${last.date.slice(0, 10)}T00:00:00Z`);
  cutoff.setUTCMonth(cutoff.getUTCMonth() - RANGE_MONTHS[range]);
  const cutoffText = cutoff.toISOString().slice(0, 10);
  return bars.filter((bar) => bar.date.slice(0, 10) >= cutoffText);
};

/** Y 軸範圍含價位線，停損或目標離現價再遠都看得到。 */
export const priceDomain = (bars: ChartBar[], levels: number[]): [number, number] | null => {
  if (bars.length === 0) return null;
  const values = [...bars.flatMap((bar) => [bar.low, bar.high]), ...levels];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const padding = (max - min) * 0.04 || max * 0.01;
  return [min - padding, max + padding];
};
