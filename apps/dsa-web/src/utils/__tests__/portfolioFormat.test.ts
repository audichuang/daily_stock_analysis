import { describe, expect, it } from 'vitest';
import {
  buildFxRefreshFeedback,
  computeTradeAmount,
  formatBrokerLabel,
  formatBrokerOptionLabel,
  formatAmount,
  formatLossPct,
  formatMoney,
  formatPendingGroupLabel,
  formatPositionMoney,
  formatPositionPrice,
  formatSignedPct,
  getCsvCommitVariant,
  getCsvParseVariant,
  getFxBadge,
  getPositionPriceLabel,
  mergePendingBySymbol,
  parsePortfolioEntryParam,
  removeSearchParam,
  shortAccountName,
  sortPendingBySeverity,
  splitPendingRows,
} from '../portfolioFormat';
import type { PortfolioPositionItem } from '../../types/portfolio';

const pricedPosition: PortfolioPositionItem = {
  symbol: 'HK00700',
  market: 'hk',
  currency: 'HKD',
  quantity: 100,
  avgCost: 300,
  totalCost: 30000,
  lastPrice: 321.12345,
  marketValueBase: 32112.345,
  unrealizedPnlBase: 2112.345,
  unrealizedPnlPct: 7.04,
  valuationCurrency: 'CNY',
  priceSource: 'realtime_quote',
  priceProvider: 'longbridge',
  priceAvailable: true,
};

describe('portfolioFormat', () => {
  it('formats money and signed percentages consistently', () => {
    expect(formatMoney(1234.5, 'USD')).toBe('USD 1,234.50');
    expect(formatMoney(null)).toBe('—');
    // 不再預設 CNY：快照沒帶幣別時只顯示數字，不亂標幣別。
    expect(formatMoney(1234.5)).toBe('1,234.50');
    expect(formatSignedPct(3.456)).toBe('+3.46%');
    expect(formatSignedPct(-1.2)).toBe('\u22121.20%');
  });

  it('formats aggregate amounts with NT$/US$ prefixes and currency-specific decimals', () => {
    // TWD aggregates drop decimals (mutation guard: two decimals here would read "NT$ 829,916.75").
    expect(formatAmount(829916.75, 'TWD')).toBe('NT$ 829,917');
    expect(formatAmount(829916.75, 'twd')).toBe('NT$ 829,917');
    expect(formatAmount(1234.5, 'USD')).toBe('US$ 1,234.50');
    // Other currencies keep their code as prefix and two decimals.
    expect(formatAmount(123, 'CNY')).toBe('CNY 123.00');
    expect(formatAmount(1234.5)).toBe('1,234.50');
    expect(formatAmount(null, 'TWD')).toBe('—');
    expect(formatAmount(Number.NaN, 'TWD')).toBe('—');
  });

  it('signs aggregate amounts with "+" and the unified minus sign', () => {
    expect(formatAmount(619805.4, 'TWD', { signed: true })).toBe('NT$ +619,805');
    expect(formatAmount(-619805.4, 'TWD', { signed: true })).toBe('NT$ \u2212619,805');
    expect(formatAmount(12.5, 'USD', { signed: true })).toBe('US$ +12.50');
    expect(formatAmount(-12.5, 'USD', { signed: true })).toBe('US$ \u221212.50');
    // Unsigned positives get no "+"; values rounding to zero get no sign either way.
    expect(formatAmount(12.5, 'USD')).toBe('US$ 12.50');
    expect(formatAmount(0.4, 'TWD', { signed: true })).toBe('NT$ 0');
    expect(formatAmount(-0.4, 'TWD', { signed: true })).toBe('NT$ 0');
  });

  it('keeps decimals for prices and single trades formatted with formatMoney', () => {
    // Reverse guard: formatAmount's TWD rounding must not leak into formatMoney.
    expect(formatMoney(50.35, 'TWD')).toBe('TWD 50.35');
    expect(formatMoney(829916.75, 'TWD')).toBe('TWD 829,916.75');
  });

  it('formats position price fields based on price availability', () => {
    expect(formatPositionPrice(pricedPosition)).toBe('321.1235');
    expect(formatPositionMoney(123, pricedPosition)).toBe('CNY 123.00');
    expect(formatPositionMoney(829916.75, { ...pricedPosition, valuationCurrency: 'TWD' })).toBe('NT$ 829,917');
    expect(getPositionPriceLabel(pricedPosition)).toBe('实时价 · longbridge');

    // 報價幣別決定精度，帳戶基準幣別不影響。
    const usdInTwdAccount = { ...pricedPosition, currency: 'USD', lastPrice: 1264.5, valuationCurrency: 'TWD' };
    expect(formatPositionPrice(usdInTwdAccount)).toBe('1,264.50');

    const missingPosition = { ...pricedPosition, priceAvailable: false, priceSource: 'missing' };
    expect(formatPositionPrice(missingPosition)).toBe('—');
    expect(formatPositionMoney(123, missingPosition)).toBe('—');
    expect(getPositionPriceLabel(missingPosition)).toBe('缺价');
  });

  it('formats broker labels and CSV result variants', () => {
    expect(formatBrokerLabel('huatai')).toBe('huatai（华泰）');
    expect(formatBrokerLabel('custom', ' 自定义 ')).toBe('custom（自定义）');
    expect(getCsvParseVariant({ broker: 'huatai', recordCount: 1, skippedCount: 1, errorCount: 0, records: [], errors: [] })).toBe('warning');
    expect(getCsvCommitVariant({ accountId: 1, recordCount: 1, insertedCount: 1, duplicateCount: 0, failedCount: 0, dryRun: false, errors: [] }, false)).toBe('success');
  });

  it('builds FX refresh feedback from refresh outcomes', () => {
    expect(buildFxRefreshFeedback({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: false,
      disabledReason: 'disabled',
      pairCount: 1,
      updatedCount: 0,
      staleCount: 0,
      errorCount: 0,
    })).toMatchObject({ tone: 'neutral' });

    expect(buildFxRefreshFeedback({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: true,
      disabledReason: null,
      pairCount: 1,
      updatedCount: 1,
      staleCount: 0,
      errorCount: 0,
    })).toMatchObject({ tone: 'success' });
  });

  it('merges pending entries of one stock code into one row and keeps the worst severity', () => {
    const groups = mergePendingBySymbol([
      { symbol: '2303.TW', tone: 'danger', text: '停損已觸發 −35.4%', name: '聯電', accountName: '美好台股', rowKey: 'tw:2303' },
      { symbol: '2330.TW', tone: 'warning', text: '缺報價' },
      { symbol: '2303.tw', tone: 'warning', text: 'AI 減碼', accountName: '國泰台股' },
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0]).toMatchObject({ tone: 'danger', rowKey: 'tw:2303', accountNames: ['美好台股', '國泰台股'] });
    expect(formatPendingGroupLabel(groups[0])).toBe('聯電 2303.TW · 停損已觸發 −35.4% · AI 減碼');
    expect(formatPendingGroupLabel(groups[1])).toBe('2330.TW · 缺報價');
  });

  it('sorts pending rows by severity without reordering equals and splits off the overflow', () => {
    const rows = [
      { key: 'a', tone: 'warning' as const },
      { key: 'b', tone: 'danger' as const },
      { key: 'c', tone: 'warning' as const },
    ];
    expect(sortPendingBySeverity(rows).map((row) => row.key)).toEqual(['b', 'a', 'c']);
    const { visible, hidden } = splitPendingRows([1, 2, 3, 4, 5, 6, 7], 5);
    expect(visible).toEqual([1, 2, 3, 4, 5]);
    expect(hidden).toEqual([6, 7]);
  });

  it('formats loss percentages as negative with one decimal', () => {
    expect(formatLossPct(35.42)).toBe('\u221235.4%');
    expect(formatLossPct(-12)).toBe('\u221212.0%');
    expect(formatLossPct(null)).toBe('—');
  });

  it('shortens account names by trailing market words only', () => {
    expect(shortAccountName('美好台股')).toBe('美好');
    expect(shortAccountName('國泰台股')).toBe('國泰');
    expect(shortAccountName('永豐複委託')).toBe('永豐');
    expect(shortAccountName('Main')).toBe('Main');
    // Never shortens a name down to nothing.
    expect(shortAccountName('台股')).toBe('台股');
  });

  it('labels known brokers in the UI language instead of the API name', () => {
    expect(formatBrokerOptionLabel('huatai', '华泰', 'zh-TW')).toBe('華泰');
    expect(formatBrokerOptionLabel('huatai', '华泰', 'en')).toBe('Huatai');
    expect(formatBrokerOptionLabel('custom', ' 自訂 ', 'zh-TW')).toBe('自訂');
    expect(formatBrokerOptionLabel('custom', undefined, 'zh-TW')).toBe('custom');
  });

  it('builds the FX badge from missing / stale / fresh state', () => {
    expect(getFxBadge(true, false, 'zh-TW')).toEqual({ variant: 'warning', label: '缺匯率' });
    expect(getFxBadge(false, true, 'zh-TW')).toEqual({ variant: 'warning', label: '匯率 過期' });
    expect(getFxBadge(false, false, 'zh-TW')).toEqual({ variant: 'success', label: '匯率 今日' });
    expect(getFxBadge(false, undefined, 'zh-TW')).toBeNull();
  });

  it('previews the trade amount only for positive quantity and price', () => {
    expect(computeTradeAmount('1000', '52.5')).toBe(52500);
    expect(computeTradeAmount('', '52.5')).toBeNull();
    expect(computeTradeAmount('10', '0')).toBeNull();
    expect(computeTradeAmount('abc', '1')).toBeNull();
  });

  it('reads and removes the entry deep-link parameter', () => {
    expect(parsePortfolioEntryParam('?entry=import')).toBe('import');
    expect(parsePortfolioEntryParam('?embed=ios&entry=cash')).toBe('cash');
    expect(parsePortfolioEntryParam('?entry=delete')).toBeNull();
    expect(parsePortfolioEntryParam('')).toBeNull();
    expect(removeSearchParam('?embed=ios&entry=trade', 'entry')).toBe('?embed=ios');
    expect(removeSearchParam('?entry=trade', 'entry')).toBe('');
  });
});
