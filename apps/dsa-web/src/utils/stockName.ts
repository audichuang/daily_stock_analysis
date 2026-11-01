import { isTwStockCode } from './stockCode';

/**
 * Stock name truncation configuration
 * English characters: 15 chars max
 * Chinese characters: 8 chars max
 * Mixed (Chinese + English): 10 chars max
 */
export const STOCK_NAME_MAX_LENGTH = {
  ENGLISH: 15,
  CHINESE: 8,
  MIXED: 10,
} as const;

/**
 * Get max allowed length for a stock name based on character type
 * - Pure English: 15 chars
 * - Pure Chinese: 8 chars
 * - Mixed: 10 chars
 */
function getMaxLength(name: string): number {
  const isChinese = /[\u4e00-\u9fa5]/.test(name);
  const isMixed = isChinese && /[a-zA-Z]/.test(name);
  if (isMixed) return STOCK_NAME_MAX_LENGTH.MIXED;
  if (isChinese) return STOCK_NAME_MAX_LENGTH.CHINESE;
  return STOCK_NAME_MAX_LENGTH.ENGLISH;
}

/**
 * Truncate stock name based on character type
 * - Pure English: max 15 characters
 * - Pure Chinese: max 8 characters
 * - Mixed: max 10 characters
 */
export function truncateStockName(name: string): string {
  if (!name) return name;
  const maxLen = getMaxLength(name);
  if (name.length <= maxLen) return name;
  return name.slice(0, maxLen) + '.';
}

/**
 * Check if stock name will be truncated
 */
export function isStockNameTruncated(name: string): boolean {
  if (!name) return false;
  return name.length > getMaxLength(name);
}

export type StockMarketBucket = 'tw' | 'us' | 'other';

// 美股 ticker 的代號格式（AAPL、BRK.B）；台股後綴由 isTwStockCode 判斷。
const US_TICKER_RE = /^[A-Z]{1,5}(?:[.-][A-Z])?$/;

/** 清單市場篩選用的分類，只看代號格式。 */
export function getStockMarketBucket(code: string | null | undefined): StockMarketBucket {
  const normalized = (code ?? '').trim();
  if (isTwStockCode(normalized)) return 'tw';
  return US_TICKER_RE.test(normalized) ? 'us' : 'other';
}

/** 清單列的兩行文字：美股以 ticker 為主、公司名為輔，其餘以股名為主、代號為輔。 */
export function getStockRowLabels(code: string, name?: string | null): { primary: string; secondary: string } {
  const displayName = name?.trim() || '';
  if (getStockMarketBucket(code) === 'us') {
    return { primary: code, secondary: displayName && displayName !== code ? displayName : '' };
  }
  return { primary: truncateStockName(displayName || code), secondary: displayName ? code : '' };
}
