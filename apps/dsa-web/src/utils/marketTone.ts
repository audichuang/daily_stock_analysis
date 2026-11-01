import type { DecisionAction } from '../types/analysis';

export type MarketDirection = 'up' | 'down' | 'flat';
export type ActionTone = 'brand' | 'neutral' | 'caution';

// 行情方向與損益的唯一入口：紅漲綠跌、紅賺綠賠。success／danger 只留給系統狀態。
export const MARKET_TONE_CLASS: Record<MarketDirection, string> = {
  up: 'text-market-up',
  down: 'text-market-down',
  flat: 'text-secondary-text',
};

/** 沒有讀數回 null，呼叫端不要把缺值當成持平。 */
export const marketDirection = (value?: number | null): MarketDirection | null => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  if (value > 0) return 'up';
  if (value < 0) return 'down';
  return 'flat';
};

export const marketToneClass = (value?: number | null, missingClass = 'text-secondary-text'): string => {
  const direction = marketDirection(value);
  return direction ? MARKET_TONE_CLASS[direction] : missingClass;
};

// 動作色不用紅綠，避免和行情方向混淆：買進類品牌色、持有觀望灰、減碼賣出與警示琥珀。
export const ACTION_TONE: Record<DecisionAction, ActionTone> = {
  buy: 'brand',
  add: 'brand',
  hold: 'neutral',
  watch: 'neutral',
  avoid: 'caution',
  reduce: 'caution',
  sell: 'caution',
  alert: 'caution',
};

export const actionTone = (action: DecisionAction): ActionTone => ACTION_TONE[action];
