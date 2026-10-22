import { describe, expect, it } from 'vitest';
import type { DossierLevel } from '../../api/stocks';
import { nearestLevels } from '../dossierLevels';

const L = (low: number, high: number, bias: DossierLevel['bias'], kind: DossierLevel['kind'] = 'ob'): DossierLevel => ({
  label: `${kind}-${low}`,
  low,
  high,
  kind,
  bias,
});

const levels = [L(1240, 1365, 'bull'), L(1395, 1460, 'bear'), L(1240, 1240, 'bull', 'ssl'), L(1750, 1750, 'bear', 'bsl')];

describe('nearestLevels', () => {
  it('picks the closest zone below as support and above as resistance', () => {
    const { support, resistance } = nearestLevels(levels, 1375);
    expect(support?.level.label).toBe('ob-1240');
    expect(support?.distPct).toBeCloseTo(((1365 - 1375) / 1375) * 100);
    expect(resistance?.level.label).toBe('ob-1395');
    expect(resistance?.distPct).toBeCloseTo(((1395 - 1375) / 1375) * 100);
  });

  it('follows the live price, not the as-of close', () => {
    // 盤中跌進多頭 OB：距離 0；再跌破整個 OB 與 SSL，下方沒有支撐、1240 變壓力
    expect(nearestLevels(levels, 1300).support).toMatchObject({ level: { label: 'ob-1240' }, distPct: 0 });
    const below = nearestLevels(levels, 1238);
    expect(below.support).toBeNull();
    expect(below.resistance?.distPct).toBeCloseTo(((1240 - 1238) / 1238) * 100);
  });

  it('classifies a zone containing the price by its bias and ignores unbiased OTE', () => {
    const inBear = nearestLevels(levels, 1420);
    expect(inBear.resistance).toMatchObject({ level: { label: 'ob-1395' }, distPct: 0 });
    expect(inBear.support?.level.label).toBe('ob-1240');
    const inOte = nearestLevels([L(1500, 1600, null, 'ote')], 1550);
    expect(inOte).toEqual({ support: null, resistance: null });
  });

  it('picks the nearest level regardless of input order', () => {
    const shuffled = [L(900, 950, 'bull'), L(1750, 1750, 'bear', 'bsl'), L(1240, 1365, 'bull'), L(1395, 1460, 'bear'), L(1100, 1120, 'bull')];
    const { support, resistance } = nearestLevels(shuffled, 1375);
    expect(support?.level.label).toBe('ob-1240');
    expect(resistance?.level.label).toBe('ob-1395');
  });
});
