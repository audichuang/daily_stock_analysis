import type {
  PortfolioCashDirection,
  PortfolioCorporateActionType,
  PortfolioFxRefreshResponse,
  PortfolioImportCommitResponse,
  PortfolioImportParseResponse,
  PortfolioPositionItem,
  PortfolioSide,
} from '../types/portfolio';
import type { UiLanguage } from '../i18n/uiText';
import { formatUiText } from '../i18n/uiText';
import {
  PORTFOLIO_CASH_DIRECTION_LABELS,
  PORTFOLIO_CORPORATE_ACTION_LABELS,
  PORTFOLIO_FORMAT_TEXT,
  PORTFOLIO_SIDE_LABELS,
  PORTFOLIO_TEXT,
} from '../locales/featureText';
import { PORTFOLIO_W10_TEXT } from '../locales/portfolioText';
import { formatMoneyValue, formatPrice, MINUS_SIGN, NO_VALUE, toDateInputValue } from './format';
import { stockCodeMatchKey } from './stockCode';

export type FxRefreshFeedback = {
  tone: 'neutral' | 'success' | 'warning';
  text: string;
};

export type PortfolioAlertVariant = 'info' | 'success' | 'warning' | 'danger';

export function getTodayIso(): string {
  return toDateInputValue(new Date());
}

export function formatMoney(value: number | undefined | null, currency?: string): string {
  if (value == null || !Number.isFinite(value)) return NO_VALUE;
  return formatMoneyValue(value, currency);
}

export function formatPct(value: number | undefined | null): string {
  if (value == null || Number.isNaN(value)) return NO_VALUE;
  return `${value < 0 ? MINUS_SIGN : ''}${Math.abs(value).toFixed(2)}%`;
}

export function formatSignedPct(value: number | undefined | null): string {
  if (value == null || Number.isNaN(value)) return '--';
  const text = Math.abs(value).toFixed(2);
  if (value < 0 && /[1-9]/.test(text)) return `${MINUS_SIGN}${text}%`;
  return value > 0 && /[1-9]/.test(text) ? `+${text}%` : `${text}%`;
}

export function hasPositionPrice(row: PortfolioPositionItem): boolean {
  return row.priceAvailable !== false && row.priceSource !== 'missing';
}

export function formatPositionPrice(row: PortfolioPositionItem): string {
  if (!hasPositionPrice(row)) return NO_VALUE;
  // lastPrice 是原幣報價；valuationCurrency 是帳戶基準幣別，不能拿來決定精度。
  return formatPrice(row.lastPrice, row.currency);
}

export function formatPositionMoney(value: number, row: PortfolioPositionItem): string {
  if (!hasPositionPrice(row)) return NO_VALUE;
  return formatMoney(value, row.valuationCurrency);
}

export function getPositionPriceLabel(row: PortfolioPositionItem, language: UiLanguage = 'zh'): string {
  const text = PORTFOLIO_FORMAT_TEXT[language];
  if (!hasPositionPrice(row)) return text.priceMissing;
  if (row.priceSource === 'realtime_quote') {
    return row.priceProvider ? `${text.priceRealtime} · ${row.priceProvider}` : text.priceRealtime;
  }
  if (row.priceSource === 'history_close') {
    return row.priceStale && row.priceDate ? `${text.priceClose} · ${row.priceDate}` : text.priceClose;
  }
  return row.priceSource || text.priceUnknown;
}

export function formatSideLabel(value: PortfolioSide, language: UiLanguage = 'zh'): string {
  return PORTFOLIO_SIDE_LABELS[language][value];
}

export function formatCashDirectionLabel(value: PortfolioCashDirection, language: UiLanguage = 'zh'): string {
  return PORTFOLIO_CASH_DIRECTION_LABELS[language][value];
}

export function formatCorporateActionLabel(value: PortfolioCorporateActionType, language: UiLanguage = 'zh'): string {
  return PORTFOLIO_CORPORATE_ACTION_LABELS[language][value];
}

export function formatBrokerLabel(value: string, displayName?: string): string {
  if (displayName && displayName.trim()) return `${value}（${displayName.trim()}）`;
  if (value === 'huatai') return 'huatai（华泰）';
  if (value === 'citic') return 'citic（中信）';
  if (value === 'cmb') return 'cmb（招商）';
  return value;
}

export function buildFxRefreshFeedback(data: PortfolioFxRefreshResponse, language: UiLanguage = 'zh'): FxRefreshFeedback {
  const text = PORTFOLIO_FORMAT_TEXT[language];
  if (data.refreshEnabled === false) {
    return { tone: 'neutral', text: text.fxDisabled };
  }

  if (data.pairCount === 0) {
    return { tone: 'neutral', text: text.fxNoPairs };
  }

  if (data.updatedCount > 0 && data.staleCount === 0 && data.errorCount === 0) {
    return { tone: 'success', text: formatUiText(text.fxUpdated, { count: data.updatedCount }) };
  }

  const summary = formatUiText(text.fxSummary, {
    updated: data.updatedCount,
    stale: data.staleCount,
    errors: data.errorCount,
  });
  if (data.staleCount > 0) {
    return { tone: 'warning', text: `${text.fxStillStale}${summary}` };
  }

  return { tone: 'warning', text: `${text.fxPartial}${summary}` };
}

export function getFxRefreshFeedbackVariant(tone: FxRefreshFeedback['tone']): PortfolioAlertVariant {
  if (tone === 'success') return 'success';
  if (tone === 'warning') return 'warning';
  return 'info';
}

export function getCsvParseVariant(result: PortfolioImportParseResponse): PortfolioAlertVariant {
  return result.errorCount > 0 || result.skippedCount > 0 || (result.missingCost?.length ?? 0) > 0 ? 'warning' : 'info';
}

export function getCsvCommitVariant(result: PortfolioImportCommitResponse, isDryRun: boolean): PortfolioAlertVariant {
  if (isDryRun) return 'info';
  return result.failedCount > 0 || result.duplicateCount > 0 ? 'warning' : 'success';
}

export type PendingTone = 'danger' | 'warning';

/** One anomaly for one holding (stop loss, AI signal, missing quote) before merging. */
export interface PendingEntry {
  symbol: string;
  tone: PendingTone;
  text: string;
  name?: string | null;
  accountName?: string | null;
  rowKey?: string;
}

/** All anomalies of one holding merged into a single pending row. */
export interface PendingGroup {
  key: string;
  symbol: string;
  name: string | null;
  tone: PendingTone;
  parts: string[];
  accountNames: string[];
  rowKey?: string;
}

/** Merges pending entries by stock code (2330 / 2330.TW count as one), keeping first-seen order. */
export function mergePendingBySymbol(entries: PendingEntry[]): PendingGroup[] {
  const groups: PendingGroup[] = [];
  const byKey = new Map<string, PendingGroup>();
  for (const entry of entries) {
    const matchKey = stockCodeMatchKey(entry.symbol);
    const existing = byKey.get(matchKey);
    if (!existing) {
      const group: PendingGroup = {
        key: `pending-${groups.length}-${matchKey}`,
        symbol: entry.symbol,
        name: entry.name || null,
        tone: entry.tone,
        parts: [entry.text],
        accountNames: entry.accountName ? [entry.accountName] : [],
        rowKey: entry.rowKey,
      };
      byKey.set(matchKey, group);
      groups.push(group);
      continue;
    }
    if (!existing.parts.includes(entry.text)) existing.parts.push(entry.text);
    if (entry.tone === 'danger') existing.tone = 'danger';
    if (!existing.name && entry.name) existing.name = entry.name;
    if (!existing.rowKey && entry.rowKey) existing.rowKey = entry.rowKey;
    if (entry.accountName && !existing.accountNames.includes(entry.accountName)) {
      existing.accountNames.push(entry.accountName);
    }
  }
  return groups;
}

/** "聯電 2303.TW · 停損已觸發 −35.4% · AI 減碼"; the name is omitted when unknown. */
export function formatPendingGroupLabel(group: Pick<PendingGroup, 'symbol' | 'name' | 'parts'>): string {
  const title = group.name ? `${group.name} ${group.symbol}` : group.symbol;
  return [title, ...group.parts].join(' · ');
}

/** Danger rows first; rows of equal severity keep their order. */
export function sortPendingBySeverity<T extends { tone: PendingTone }>(items: T[]): T[] {
  const rank = (tone: PendingTone) => (tone === 'danger' ? 0 : 1);
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => rank(a.item.tone) - rank(b.item.tone) || a.index - b.index)
    .map(({ item }) => item);
}

export function splitPendingRows<T>(items: T[], limit = 5): { visible: T[]; hidden: T[] } {
  return { visible: items.slice(0, limit), hidden: items.slice(limit) };
}

/** Loss percentage shown as a negative number with one decimal, e.g. 35.42 → "−35.4%". */
export function formatLossPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return NO_VALUE;
  return `${MINUS_SIGN}${Math.abs(value).toFixed(1)}%`;
}

const ACCOUNT_NAME_SUFFIXES = ['複委託', '复委托', '台股', '美股', '港股', '帳戶', '账户', '證券', '证券'];

/** Short account label for the phone segmented control: "永豐複委託" → "永豐"; falls back to the full name. */
export function shortAccountName(name: string): string {
  const full = name.trim();
  let short = full;
  let changed = true;
  while (changed) {
    changed = false;
    for (const suffix of ACCOUNT_NAME_SUFFIXES) {
      if (short.length > suffix.length && short.endsWith(suffix)) {
        short = short.slice(0, -suffix.length).trim();
        changed = true;
      }
    }
  }
  return short || full;
}

/** Broker option label in the UI language; known brokers never fall back to the API's simplified name. */
export function formatBrokerOptionLabel(broker: string, displayName: string | undefined, language: UiLanguage = 'zh'): string {
  const known = PORTFOLIO_W10_TEXT[language].brokerNames[broker];
  if (known) return known;
  return displayName && displayName.trim() ? displayName.trim() : broker;
}

export type FxBadge = { variant: 'warning' | 'success'; label: string };

/** FX status badge; null when the status is unknown (no snapshot yet). */
export function getFxBadge(
  fxMissing: boolean,
  fxStale: boolean | undefined,
  language: UiLanguage = 'zh',
): FxBadge | null {
  if (fxMissing) return { variant: 'warning', label: PORTFOLIO_TEXT[language].fxMissing };
  if (fxStale === true) return { variant: 'warning', label: PORTFOLIO_W10_TEXT[language].fxStale };
  if (fxStale === false) return { variant: 'success', label: PORTFOLIO_W10_TEXT[language].fxToday };
  return null;
}

/** Trade value preview (quantity × price); null until both are positive numbers. */
export function computeTradeAmount(quantity: string, price: string): number | null {
  if (!quantity.trim() || !price.trim()) return null;
  const q = Number(quantity);
  const p = Number(price);
  if (!Number.isFinite(q) || !Number.isFinite(p) || q <= 0 || p <= 0) return null;
  return q * p;
}

export type PortfolioEntryParam = 'trade' | 'cash' | 'account' | 'import';
const PORTFOLIO_ENTRY_PARAMS: PortfolioEntryParam[] = ['trade', 'cash', 'account', 'import'];

/** Reads the `?entry=` deep link (iOS links straight into a drawer); unknown values are ignored. */
export function parsePortfolioEntryParam(search: string): PortfolioEntryParam | null {
  const value = new URLSearchParams(search).get('entry');
  return PORTFOLIO_ENTRY_PARAMS.find((item) => item === value) ?? null;
}

/** Returns the search string without `key` ("" when nothing is left). */
export function removeSearchParam(search: string, key: string): string {
  const params = new URLSearchParams(search);
  params.delete(key);
  const next = params.toString();
  return next ? `?${next}` : '';
}
