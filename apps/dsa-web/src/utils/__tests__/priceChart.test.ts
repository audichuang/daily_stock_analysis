import { describe, expect, it } from 'vitest';
import type { PriceBar } from '../../api/stocks';
import { priceDomain, sliceByRange, withMovingAverages } from '../priceChart';

// 日期以「今天往回」產生，避免 fixture 落在固定日曆上。
const makeBars = (count: number): PriceBar[] => {
  const start = Date.now() - count * 86_400_000;
  return Array.from({ length: count }, (_, index) => {
    const close = 100 + index;
    return {
      date: new Date(start + index * 86_400_000).toISOString().slice(0, 10),
      open: close,
      high: close + 1,
      low: close - 1,
      close,
    };
  });
};

describe('withMovingAverages', () => {
  it('leaves the leading rows blank instead of inventing a value', () => {
    const bars = withMovingAverages(makeBars(61));
    expect(bars[18].ma20).toBeNull();
    expect(bars[19].ma20).toBeCloseTo(109.5);
    expect(bars[58].ma60).toBeNull();
    expect(bars[59].ma60).toBeCloseTo(129.5);
    // 滾動窗口要扣掉舊值，不是累積平均。
    expect(bars[60].ma60).toBeCloseTo(130.5);
  });

  it('sorts by date before computing', () => {
    const ordered = withMovingAverages(makeBars(25));
    const shuffled = withMovingAverages([...ordered].reverse());
    expect(shuffled.map((bar) => bar.ma20)).toEqual(ordered.map((bar) => bar.ma20));
  });
});

describe('sliceByRange', () => {
  it('keeps MA60 populated at the left edge of the one-year range', () => {
    const visible = sliceByRange(withMovingAverages(makeBars(500)), '1y');
    expect(visible.length).toBeLessThan(500);
    expect(visible.length).toBeGreaterThan(300);
    expect(visible[0].ma60).not.toBeNull();
  });

  it('counts back from the last bar, not from the device clock', () => {
    const old: PriceBar[] = [
      { date: '2019-01-02', open: 1, high: 1, low: 1, close: 1 },
      { date: '2019-05-02', open: 1, high: 1, low: 1, close: 1 },
      { date: '2019-05-30', open: 1, high: 1, low: 1, close: 1 },
    ];
    expect(sliceByRange(withMovingAverages(old), '1m').map((bar) => bar.date)).toEqual(['2019-05-02', '2019-05-30']);
  });

  it('returns nothing for an empty series', () => {
    expect(sliceByRange([], '3m')).toEqual([]);
  });
});

describe('priceDomain', () => {
  it('stretches to include a level outside the traded range', () => {
    const bars = withMovingAverages(makeBars(5));
    const domain = priceDomain(bars, [50, 200]);
    expect(domain?.[0]).toBeLessThan(50);
    expect(domain?.[1]).toBeGreaterThan(200);
  });

  it('returns null without bars', () => {
    expect(priceDomain([], [10])).toBeNull();
  });
});
