import type { DossierLevel } from '../api/stocks';

export type NearLevel = { level: DossierLevel; distPct: number };

/**
 * 用即時價找最近的支撐與壓力（後端只給絕對價位，因為資料包的價格是上一個收盤）。
 * 價位區間完全在現價之下算支撐、之上算壓力；現價落在區間裡時依多空屬性歸類
 * （多頭區＝支撐、空頭區＝壓力，距離 0），沒有方向的 OTE 區不算。
 */
export function nearestLevels(levels: DossierLevel[], price: number): { support: NearLevel | null; resistance: NearLevel | null } {
  let support: NearLevel | null = null;
  let resistance: NearLevel | null = null;
  for (const level of levels) {
    const inside = level.low <= price && price <= level.high && level.low !== level.high;
    const isSupport = inside ? level.bias === 'bull' : level.high <= price;
    const isResistance = inside ? level.bias === 'bear' : level.low > price;
    if (isSupport) {
      const distPct = ((Math.min(level.high, price) - price) / price) * 100;
      if (!support || distPct > support.distPct) support = { level, distPct };
    } else if (isResistance) {
      const distPct = ((Math.max(level.low, price) - price) / price) * 100;
      if (!resistance || distPct < resistance.distPct) resistance = { level, distPct };
    }
  }
  return { support, resistance };
}
