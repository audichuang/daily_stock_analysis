import type { DecisionSignalItem, DecisionSignalMarket } from '../types/decisionSignals';
import { parseDecisionSignalDate } from './decisionSignalTime';

const MARKET_CURRENCY: Partial<Record<DecisionSignalMarket, string>> = { tw: 'TWD' };
const HOUR_MS = 3600_000;

/** 只有台幣的價位小數規則不同（見 formatPrice），其他市場不用傳幣別。 */
export const signalCurrency = (market: DecisionSignalMarket): string | undefined => MARKET_CURRENCY[market];

/** 價位相對現價的距離（%）。沒有現價或沒有價位回 null，不要拿訊號當時價代替現價。 */
export const distancePct = (level?: number | null, price?: number | null): number | null => {
  if (typeof level !== 'number' || !Number.isFinite(level)) return null;
  if (typeof price !== 'number' || !Number.isFinite(price) || price <= 0) return null;
  return ((level - price) / price) * 100;
};

export type SignalRemaining =
  | { kind: 'expired' }
  | { kind: 'hours'; count: number }
  | { kind: 'days'; count: number };

/** 剩餘時效：不足一天算小時，無條件進位（剩 90 分鐘顯示 2 小時）。沒有到期時間回 null。 */
export const signalRemaining = (expiresAt: string | null | undefined, now: number = Date.now()): SignalRemaining | null => {
  const expires = parseDecisionSignalDate(expiresAt)?.getTime();
  if (expires === undefined) return null;
  const left = expires - now;
  if (left <= 0) return { kind: 'expired' };
  const hours = Math.ceil(left / HOUR_MS);
  return hours < 24 ? { kind: 'hours', count: hours } : { kind: 'days', count: Math.floor(hours / 24) };
};

/** 動作變化：前一筆與目前不同才算，舊資料或只有一筆回 false。 */
export const hasActionChange = (item: DecisionSignalItem): boolean =>
  Boolean(item.previousAction) && item.previousAction !== item.action;

/** 來源報告深連結，首頁依 ?report= 開啟那份報告。 */
export const sourceReportHref = (reportId: number): string => `/?report=${reportId}`;
