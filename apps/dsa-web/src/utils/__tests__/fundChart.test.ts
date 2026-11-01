import { describe, expect, it } from 'vitest';
import type { FundHoldingItem } from '../../types/funds';
import { fundUnitCost, navAxisDigits } from '../fundChart';

const holding = (overrides: Partial<FundHoldingItem>): FundHoldingItem => ({
  id: 1, platform: '', fundId: 'A', fundName: 'A', units: 100, costTotal: 1000, currency: 'TWD', asOf: '2026-01-01',
  nav: null, navDate: null, isStale: false, marketValue: null, pnl: null, pnlPct: null,
  ...overrides,
});

describe('navAxisDigits', () => {
  it('uses more decimals as the range narrows so ticks stay distinct', () => {
    expect(navAxisDigits([100, 200])).toBe(0);
    expect(navAxisDigits([10, 16])).toBe(1);
    expect(navAxisDigits([10, 11])).toBe(2);
    expect(navAxisDigits([10.1, 10.2])).toBe(3);
  });
});

describe('fundUnitCost', () => {
  it('weights the cost across platforms of the same fund and ignores other funds', () => {
    const items = [
      holding({ id: 1, units: 100, costTotal: 1000 }),
      holding({ id: 2, units: 300, costTotal: 5000 }),
      holding({ id: 3, fundId: 'B', units: 1, costTotal: 999 }),
    ];
    expect(fundUnitCost(items, 'A')).toBe(15);
  });

  it('returns null for a fund that is not held', () => {
    expect(fundUnitCost([holding({})], 'B')).toBeNull();
  });
});
