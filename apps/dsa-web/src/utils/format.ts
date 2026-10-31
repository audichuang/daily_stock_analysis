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

export const formatMoneyValue = (value?: number | null, currency?: string, digits = 2): string => {
  if (!isReading(value)) return NO_VALUE;
  const text = groupDigits(value, digits, digits);
  return currency ? `${currency} ${text}` : text;
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
