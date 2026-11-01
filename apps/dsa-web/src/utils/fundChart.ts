import type { FundHoldingItem } from '../types/funds';

/** Y 軸小數位依區間振幅：低淨值基金取整數會讓刻度全部重複。 */
export function navAxisDigits(values: number[]): number {
  if (values.length === 0) return 2;
  const span = Math.max(...values) - Math.min(...values);
  if (span >= 50) return 0;
  if (span >= 5) return 1;
  if (span >= 0.5) return 2;
  return 3;
}

/** 單位成本（總成本÷總單位數）；同基金多個通路合併，沒有持有回 null。 */
export function fundUnitCost(items: FundHoldingItem[], fundId: string): number | null {
  const held = items.filter((item) => item.fundId === fundId);
  const units = held.reduce((sum, item) => sum + item.units, 0);
  if (!(units > 0)) return null;
  return held.reduce((sum, item) => sum + item.costTotal, 0) / units;
}
