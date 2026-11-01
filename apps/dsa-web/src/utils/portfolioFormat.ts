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
} from '../locales/featureText';
import { formatMoneyValue, formatPrice, MINUS_SIGN, NO_VALUE, toDateInputValue } from './format';

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
