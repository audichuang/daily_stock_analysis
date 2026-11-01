import { describe, expect, it } from 'vitest';
import type {
  PortfolioAccountSnapshot,
  PortfolioPositionItem,
  PortfolioSnapshotResponse,
} from '../../types/portfolio';
import {
  buildHoldingRows,
  getCommonScales,
  getConsolidatedFactor,
  groupHoldingRows,
} from '../portfolioHoldings';

function position(overrides: Partial<PortfolioPositionItem>): PortfolioPositionItem {
  return {
    symbol: '2330.TW',
    market: 'tw',
    currency: 'TWD',
    quantity: 1,
    avgCost: 100,
    totalCost: 100,
    lastPrice: 100,
    marketValueBase: 100,
    unrealizedPnlBase: 0,
    unrealizedPnlPct: 0,
    valuationCurrency: 'TWD',
    priceSource: 'history_close',
    priceDate: '2026-10-30',
    priceStale: false,
    priceAvailable: true,
    ...overrides,
  };
}

function account(overrides: Partial<PortfolioAccountSnapshot>): PortfolioAccountSnapshot {
  return {
    accountId: 1,
    accountName: '國泰台股',
    market: 'tw',
    baseCurrency: 'TWD',
    asOf: '2026-10-30',
    costMethod: 'fifo',
    totalCash: 0,
    totalMarketValue: 0,
    totalMarketValueAggregate: null,
    totalEquity: 0,
    realizedPnl: 0,
    unrealizedPnl: 0,
    feeTotal: 0,
    taxTotal: 0,
    fxStale: false,
    fxMissing: false,
    positions: [],
    ...overrides,
  };
}

// CNY is the backend aggregate currency; TWD is the display currency the Metric cards use.
// Rates: TWD→CNY 0.225, USD→CNY 7.2, CNY→TWD 1,320,000 / 297,000 (so USD→TWD 32).
function mixedSnapshot(options: { fxStale: boolean; fxMissing: boolean }): PortfolioSnapshotResponse {
  const twAccount = account({
    accountId: 1,
    accountName: '國泰台股',
    baseCurrency: 'TWD',
    totalMarketValue: 1_000_000,
    totalMarketValueAggregate: 225_000,
    fxStale: options.fxStale,
    fxMissing: false,
    positions: [
      position({ symbol: '2330.TW', marketValueBase: 600_000, unrealizedPnlBase: 100_000 }),
      position({ symbol: '2303.TW', marketValueBase: 400_000, unrealizedPnlBase: -50_000 }),
    ],
  });
  const usAccount = account({
    accountId: 8,
    accountName: '永豐複委託',
    market: 'us',
    baseCurrency: 'USD',
    totalMarketValue: 10_000,
    totalMarketValueAggregate: options.fxMissing ? 10_000 : 72_000,
    fxStale: options.fxStale,
    fxMissing: options.fxMissing,
    positions: [
      position({
        symbol: 'AAPL',
        market: 'us',
        currency: 'USD',
        valuationCurrency: 'USD',
        marketValueBase: 10_000,
        unrealizedPnlBase: 1_000,
      }),
    ],
  });
  return {
    asOf: '2026-11-01',
    costMethod: 'fifo',
    currency: 'CNY',
    accountCount: 2,
    totalCash: 0,
    totalMarketValue: 297_000,
    totalEquity: 297_000,
    realizedPnl: 0,
    unrealizedPnl: 0,
    feeTotal: 0,
    taxTotal: 0,
    fxStale: options.fxStale,
    fxMissing: options.fxMissing,
    fxMissingPairs: options.fxMissing ? ['USD/CNY'] : [],
    accounts: [twAccount, usAccount],
    displayCurrency: 'TWD',
    consolidatedMarketValueBase: 1_320_000,
    consolidatedFxStale: options.fxStale,
    consolidatedFxMissing: false,
  };
}

describe('portfolioHoldings with stale FX', () => {
  it('keeps the Taiwan subtotal and every weight when cross-currency FX is only stale', () => {
    const snapshot = mixedSnapshot({ fxStale: true, fxMissing: false });
    const rows = buildHoldingRows(snapshot);
    const scales = getCommonScales(snapshot);

    expect(scales).not.toBeNull();
    expect(scales?.currency).toBe('TWD');
    expect(scales?.fxStale).toBe(true);
    for (const row of rows) {
      expect(row.weightPct).not.toBeNull();
    }
    const bySymbol = new Map(rows.map((row) => [row.symbol, row]));
    expect(bySymbol.get('2330.TW')?.weightPct).toBeCloseTo((600_000 / 1_320_000) * 100, 4);
    // USD is converted with the same consolidated ratio the summary cards use.
    expect(bySymbol.get('AAPL')?.commonValue).toBeCloseTo(320_000, 4);

    const groups = groupHoldingRows(rows, scales?.currency);
    const taiwan = groups.find((group) => group.market === 'tw');
    expect(taiwan?.currency).toBe('TWD');
    expect(taiwan?.value).toBe(1_000_000);
    expect(taiwan?.pnl).toBe(50_000);
    expect(taiwan?.weightPct).toBeCloseTo((1_000_000 / 1_320_000) * 100, 4);
    const us = groups.find((group) => group.market === 'us');
    expect(us?.currency).toBe('USD');
    expect(us?.value).toBe(10_000);
  });

  it('still blanks weights when an FX rate is genuinely missing', () => {
    const snapshot = mixedSnapshot({ fxStale: true, fxMissing: true });
    const rows = buildHoldingRows(snapshot);

    expect(getCommonScales(snapshot)).toBeNull();
    for (const row of rows) {
      expect(row.weightPct).toBeNull();
      expect(row.commonValue).toBeNull();
    }
    // A same-currency group needs no FX at all, so its own-currency subtotal stays.
    const groups = groupHoldingRows(rows, null);
    const taiwan = groups.find((group) => group.market === 'tw');
    expect(taiwan?.value).toBe(1_000_000);
    expect(taiwan?.currency).toBe('TWD');
    expect(taiwan?.weightPct).toBeNull();
  });

  it('leaves a mixed-currency group without a subtotal when there is no common currency', () => {
    const snapshot = mixedSnapshot({ fxStale: true, fxMissing: true });
    // Force both currencies into one market group.
    const rows = buildHoldingRows(snapshot).map((row) => ({ ...row, market: 'tw' }));
    const [group] = groupHoldingRows(rows, null);
    expect(group.value).toBeNull();
    expect(group.currency).toBeNull();
  });

  it('does not sum a same-currency group that has a holding without a usable quote', () => {
    const snapshot = mixedSnapshot({ fxStale: false, fxMissing: false });
    snapshot.accounts[0].positions[1] = position({
      symbol: '2303.TW',
      marketValueBase: 0,
      priceAvailable: false,
      priceSource: 'missing',
      lastPrice: 0,
    });
    const groups = groupHoldingRows(buildHoldingRows(snapshot), getCommonScales(snapshot)?.currency);
    expect(groups.find((group) => group.market === 'tw')?.value).toBeNull();
  });

  it('derives the display factor from consolidated market value and drops it when display FX is missing', () => {
    const snapshot = mixedSnapshot({ fxStale: true, fxMissing: false });
    expect(getConsolidatedFactor(snapshot)).toBeCloseTo(1_320_000 / 297_000, 8);
    expect(getConsolidatedFactor({ ...snapshot, consolidatedFxMissing: true })).toBeNull();
    expect(getConsolidatedFactor({ ...snapshot, displayCurrency: null })).toBeNull();
  });
});
