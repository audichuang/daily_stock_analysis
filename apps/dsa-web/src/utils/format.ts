const DEFAULT_LOCALE = 'zh-TW';

/** 統一負號（U+2212），與 iOS DisplayFormat 同一個字。 */
export const MINUS_SIGN = '\u2212';
/** 沒有讀數的佔位；0 是真實讀數，不用這個。 */
export const NO_VALUE = '—';

const isReading = (value?: number | null): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const groupDigits = (value: number, minDigits: number, maxDigits: number): string => {
  const text = Math.abs(value).toLocaleString(DEFAULT_LOCALE, {
    minimumFractionDigits: minDigits,
    maximumFractionDigits: maxDigits,
  });
  // 四捨五入後變 0 就不帶負號，避免出現「−0.00」。
  return value < 0 && /[1-9]/.test(text) ? `${MINUS_SIGN}${text}` : text;
};

export const formatNumber = (value?: number | null, digits?: number): string => {
  if (!isReading(value)) return NO_VALUE;
  return digits === undefined ? groupDigits(value, 0, 2) : groupDigits(value, digits, digits);
};

/** 百分比帶正負號；value 已是百分比數值（1.5 代表 1.5%）。 */
export const formatPercent = (value?: number | null, digits = 2): string => {
  if (!isReading(value)) return NO_VALUE;
  const text = groupDigits(value, digits, digits);
  return value > 0 && /[1-9]/.test(text) ? `+${text}%` : `${text}%`;
};

// 第二個值是上限：報價的有效小數一律保留到四位，不依價位捨入（00631L 443.15、滬市 ETF 1.231）。
// 第一個值只決定補幾個 0：台股高價股不補，其他市場一元以下固定四位。
const PRICE_MAX_DIGITS = 4;
const priceDigits = (value: number, currency?: string): [number, number] => {
  const abs = Math.abs(value);
  if (currency === 'TWD') {
    if (abs >= 1000) return [0, PRICE_MAX_DIGITS];
    if (abs >= 100) return [1, PRICE_MAX_DIGITS];
    return [2, PRICE_MAX_DIGITS];
  }
  return [abs > 0 && abs < 1 ? PRICE_MAX_DIGITS : 2, PRICE_MAX_DIGITS];
};

export const formatPrice = (value?: number | null, currency?: string): string => {
  if (!isReading(value)) return NO_VALUE;
  const [minDigits, maxDigits] = priceDigits(value, currency);
  return groupDigits(value, minDigits, maxDigits);
};

export interface MoneyFormatOptions {
  /** 萬／億縮寫（與 iOS DisplayNumber.compact 同規則），給窄格放大數字。 */
  compact?: boolean;
}

// Currencies whose aggregate amounts carry no minor unit in summaries (mirrors iOS summaryMoney).
const ZERO_DECIMAL_CURRENCIES = new Set(['TWD', 'JPY', 'KRW']);

const moneyDigits = (currency?: string): number =>
  currency && ZERO_DECIMAL_CURRENCIES.has(currency.toUpperCase()) ? 0 : 2;

const compactMoney = (value: number): string => {
  const abs = Math.abs(value);
  if (abs >= 100_000_000) return `${groupDigits(value / 100_000_000, 0, 2)} 億`;
  if (abs >= 10_000) return `${groupDigits(value / 10_000, 0, 2)} 萬`;
  return groupDigits(value, 0, 0);
};

/**
 * 金額格式，兩種呼叫方式：
 * - 第三參數給數字（舊用法）：固定小數位，前面帶幣別代碼，例如 `USD 1,234.50`。
 * - 第三參數給選項物件：彙總金額，小數依幣別（TWD／JPY／KRW 0 位、其他 2 位），
 *   只回數字本身；幣別前綴由呼叫端用 currencyUnitLabel 另外渲染（Metric 的 unit）。
 */
export function formatMoneyValue(value?: number | null, currency?: string, digits?: number): string;
export function formatMoneyValue(value: number | null | undefined, currency: string | undefined, options: MoneyFormatOptions): string;
export function formatMoneyValue(
  value?: number | null,
  currency?: string,
  digitsOrOptions: number | MoneyFormatOptions = 2,
): string {
  if (!isReading(value)) return NO_VALUE;
  if (typeof digitsOrOptions === 'object') {
    if (digitsOrOptions.compact) return compactMoney(value);
    const digits = moneyDigits(currency);
    return groupDigits(value, digits, digits);
  }
  const text = groupDigits(value, digitsOrOptions, digitsOrOptions);
  return currency ? `${currency} ${text}` : text;
}

const CURRENCY_UNIT_LABELS: Record<string, string> = {
  TWD: 'NT$',
  USD: 'US$',
};

/** 金額前綴：TWD→NT$、USD→US$，其他回原代碼；與 iOS summaryMoney 同一套。 */
export const currencyUnitLabel = (code?: string | null): string => {
  if (!code) return '';
  return CURRENCY_UNIT_LABELS[code.toUpperCase()] ?? code;
};

export const formatDateTime = (value?: string | null): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat(DEFAULT_LOCALE, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(date);
};

export const formatDate = (value?: string): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat(DEFAULT_LOCALE, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
};

export const toDateInputValue = (date: Date): string => {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
};

/**
 * Returns the date N days ago as YYYY-MM-DD in Asia/Shanghai timezone.
 * Consistent with getTodayInShanghai() so both ends of the date range
 * are expressed in the same timezone as the backend.
 */
export const getRecentStartDate = (days: number): string => {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(date);
};

/**
 * Returns today's date as YYYY-MM-DD in Asia/Shanghai timezone.
 * Use this instead of the browser-local date for market-day UI semantics.
 */
export const getTodayInShanghai = (): string =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());

export const formatReportType = (value?: string): string => {
  if (!value) return '—';
  if (value === 'simple') return '普通';
  if (value === 'detailed') return '标准';
  if (value === 'full') return '完整';
  if (value === 'brief') return '简版';
  if (value === 'market_review') return '大盘';
  return value;
};
