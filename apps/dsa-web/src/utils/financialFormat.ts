import type { FinancialMetric, FinancialMetricPoint } from '../types/financials';

const MINUS = '−';
const currencyWord = (currency?: string | null) =>
  currency === 'TWD' ? '元' : currency === 'USD' ? '美元' : currency ? ` ${currency}` : '';

/** 沒有讀數顯示 —，不顯示 0。 */
export function formatFinancialAmount(value: number | null | undefined, currency?: string | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const sign = value < 0 ? MINUS : '';
  const magnitude = Math.abs(value);
  const unit = currencyWord(currency);
  if (magnitude >= 1e12) return `${sign}${(magnitude / 1e12).toFixed(2)} 兆${unit}`;
  if (magnitude >= 1e8) return `${sign}${(magnitude / 1e8).toLocaleString('zh-TW', { maximumFractionDigits: 1, minimumFractionDigits: 1 })} 億${unit}`;
  if (magnitude >= 1e4) return `${sign}${(magnitude / 1e4).toLocaleString('zh-TW', { maximumFractionDigits: 0 })} 萬${unit}`;
  return `${sign}${magnitude.toLocaleString('zh-TW', { maximumFractionDigits: 0 })} ${unit}`.trim();
}

export function formatMetricValue(metric: Pick<FinancialMetric, 'kind' | 'unit'>, value: number | null | undefined, currency?: string | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const sign = value < 0 ? MINUS : '';
  if (metric.kind === 'ratio') return `${sign}${Math.abs(value).toFixed(1)}%`;
  if (metric.kind === 'per_share') {
    // unit 帶出 TWD/ADR 這類口徑，不能省略：ADR 的 EPS 和原股不同基準。
    const per = metric.unit.split('/')[1];
    return `${sign}${Math.abs(value).toFixed(2)} ${currencyWord(currency).trim()}${per && per !== '股' ? `／${per}` : ''}`.trim();
  }
  return formatFinancialAmount(value, currency);
}

export function formatChange(value: number | null | undefined, points = false): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const sign = value > 0 ? '+' : value < 0 ? MINUS : '';
  return `${sign}${Math.abs(value).toFixed(1)}${points ? ' 個百分點' : '%'}`;
}

export function yoyOf(metric: Pick<FinancialMetric, 'kind'>, point: FinancialMetricPoint): string {
  return metric.kind === 'ratio' ? formatChange(point.yoyPp, true) : formatChange(point.yoyPct);
}

export function qoqOf(metric: Pick<FinancialMetric, 'kind'>, point: FinancialMetricPoint): string {
  return metric.kind === 'ratio' ? formatChange(point.qoqPp, true) : formatChange(point.qoqPct);
}
