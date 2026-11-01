import type {
  PortfolioAccountSnapshot,
  PortfolioPositionItem,
  PortfolioSnapshotResponse,
} from '../types/portfolio';

export type HoldingSource = { accountId: number; accountName: string };

/** 持股表的一列；同檔跨帳戶已合併，sources 留各帳戶給分析與警報用。 */
export type HoldingRow = PortfolioPositionItem & {
  key: string;
  sources: HoldingSource[];
  /** 佔比；金額無法放到同一幣別比較時為 null，不拿部分資料算。 */
  weightPct: number | null;
  /** 換成全表共同幣別的市值與損益，只給排序與小計用。 */
  commonValue: number | null;
  commonPnl: number | null;
};

export type HoldingGroup = {
  market: string;
  rows: HoldingRow[];
  /** 整組都能比較才有小計。 */
  value: number | null;
  pnl: number | null;
  pnlPct: number | null;
  weightPct: number | null;
};

export type HoldingSortKey = 'marketValue' | 'pnl' | 'returnPct' | 'name';

const MARKET_ORDER = ['tw', 'us'];

const isUsableQuote = (position: PortfolioPositionItem): boolean =>
  position.priceAvailable === true
  && position.priceSource !== 'missing'
  && Number.isFinite(position.lastPrice)
  && position.lastPrice > 0;

const nullableSum = (values: Array<number | null | undefined>): number | null => {
  let total = 0;
  for (const value of values) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
    total += value;
  }
  return total;
};

/** 全表共同幣別：全部同幣就直接用；跨幣別才需要彙總幣別與新鮮匯率。 */
export function getCommonScales(snapshot: PortfolioSnapshotResponse | null): {
  currency: string;
  scaleFor: (account: PortfolioAccountSnapshot) => number | null;
} | null {
  if (!snapshot) return null;
  const accounts = snapshot.accounts ?? [];
  const positions = accounts.flatMap((account) => account.positions ?? []);
  if (positions.length === 0 || !positions.every(isUsableQuote)) return null;
  const currencies = new Set(
    positions
      .filter((position) => Number(position.marketValueBase) !== 0)
      .map((position) => String(position.valuationCurrency).toUpperCase()),
  );
  if (currencies.size <= 1) {
    const [currency = String(positions[0].valuationCurrency).toUpperCase()] = Array.from(currencies);
    return { currency, scaleFor: () => 1 };
  }
  const fresh = snapshot.fxStale === false && accounts.every((account) => account.fxStale === false);
  if (!fresh || snapshot.fxMissing === true) return null;
  const snapshotCurrency = String(snapshot.currency).toUpperCase();
  return {
    currency: snapshotCurrency,
    scaleFor: (account) => {
      const base = String(account.baseCurrency).toUpperCase();
      if ((account.positions ?? []).some((position) => String(position.valuationCurrency).toUpperCase() !== base)) return null;
      if (base === snapshotCurrency) return 1;
      const aggregate = account.totalMarketValueAggregate;
      if (typeof aggregate !== 'number' || !Number.isFinite(aggregate) || !(account.totalMarketValue > 0)) return null;
      return aggregate / account.totalMarketValue;
    },
  };
}

/** 把快照攤平成持股列，同帳本幣別的同一檔跨帳戶合併成一列。 */
export function buildHoldingRows(snapshot: PortfolioSnapshotResponse | null): HoldingRow[] {
  if (!snapshot) return [];
  const common = getCommonScales(snapshot);
  const merged = new Map<string, HoldingRow>();
  const order: string[] = [];

  for (const account of snapshot.accounts ?? []) {
    const scale = common ? common.scaleFor(account) : null;
    for (const position of account.positions ?? []) {
      const key = `${position.market}:${position.symbol}:${position.valuationCurrency}`;
      const source = { accountId: account.accountId, accountName: account.accountName };
      const rawValue = Number(position.marketValueBase);
      const commonValue = scale !== null && Number.isFinite(rawValue) ? rawValue * scale : null;
      const commonPnl = scale !== null && Number.isFinite(position.unrealizedPnlBase) ? position.unrealizedPnlBase * scale : null;
      const existing = merged.get(key);
      if (!existing) {
        merged.set(key, { ...position, key, sources: [source], weightPct: null, commonValue, commonPnl });
        order.push(key);
        continue;
      }
      const quantity = existing.quantity + position.quantity;
      const marketValueBase = existing.marketValueBase + position.marketValueBase;
      const unrealizedPnlBase = existing.unrealizedPnlBase + position.unrealizedPnlBase;
      const costInValuation = marketValueBase - unrealizedPnlBase;
      merged.set(key, {
        ...existing,
        quantity,
        avgCost: quantity > 0 ? (existing.avgCost * existing.quantity + position.avgCost * position.quantity) / quantity : existing.avgCost,
        totalCost: existing.totalCost + position.totalCost,
        marketValueBase,
        unrealizedPnlBase,
        unrealizedPnlPct: costInValuation > 0 ? (unrealizedPnlBase / costInValuation) * 100 : null,
        priceAvailable: existing.priceAvailable === true && position.priceAvailable === true,
        priceStale: Boolean(existing.priceStale || position.priceStale),
        dayPnlBase: nullableSum([existing.dayPnlBase, position.dayPnlBase]),
        // 同一帳戶的重複列也算一次來源就好。
        sources: existing.sources.some((item) => item.accountId === source.accountId)
          ? existing.sources
          : [...existing.sources, source],
        commonValue: nullableSum([existing.commonValue, commonValue]),
        commonPnl: nullableSum([existing.commonPnl, commonPnl]),
      });
    }
  }

  const rows = order.map((key) => merged.get(key) as HoldingRow);
  const totalValue = common ? nullableSum(rows.map((row) => row.commonValue)) : null;
  if (totalValue !== null && totalValue > 0) {
    for (const row of rows) {
      row.weightPct = row.commonValue !== null ? (row.commonValue / totalValue) * 100 : null;
    }
  }
  return rows;
}

const compareNullable = (left: number | null | undefined, right: number | null | undefined): number => {
  const a = typeof left === 'number' && Number.isFinite(left) ? left : Number.NEGATIVE_INFINITY;
  const b = typeof right === 'number' && Number.isFinite(right) ? right : Number.NEGATIVE_INFINITY;
  if (a === b) return 0;
  return a < b ? -1 : 1;
};

export function sortHoldingRows(rows: HoldingRow[], key: HoldingSortKey, direction: 'asc' | 'desc'): HoldingRow[] {
  const sign = direction === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    switch (key) {
      case 'name':
        return sign * (a.name || a.symbol).localeCompare(b.name || b.symbol, 'zh-Hant');
      case 'pnl':
        return sign * compareNullable(a.commonPnl ?? a.unrealizedPnlBase, b.commonPnl ?? b.unrealizedPnlBase);
      case 'returnPct':
        return sign * compareNullable(a.unrealizedPnlPct, b.unrealizedPnlPct);
      default:
        return sign * compareNullable(a.commonValue ?? a.marketValueBase, b.commonValue ?? b.marketValueBase);
    }
  });
}

/** 依市場分組（台股、美股在前）並算小計；組內維持傳入的排序。 */
export function groupHoldingRows(rows: HoldingRow[]): HoldingGroup[] {
  const groups = new Map<string, HoldingRow[]>();
  for (const row of rows) {
    const market = String(row.market).toLowerCase();
    groups.set(market, [...(groups.get(market) ?? []), row]);
  }
  const rank = (market: string) => {
    const index = MARKET_ORDER.indexOf(market);
    return index === -1 ? MARKET_ORDER.length : index;
  };
  return Array.from(groups.entries())
    .sort(([left], [right]) => rank(left) - rank(right) || left.localeCompare(right))
    .map(([market, items]) => {
      const value = nullableSum(items.map((row) => row.commonValue));
      const pnl = nullableSum(items.map((row) => row.commonPnl));
      const cost = value !== null && pnl !== null ? value - pnl : null;
      return {
        market,
        rows: items,
        value,
        pnl,
        pnlPct: cost !== null && cost > 0 && pnl !== null ? (pnl / cost) * 100 : null,
        weightPct: nullableSum(items.map((row) => row.weightPct)),
      };
    });
}

/** 所有持股共用的報價日；日期不一致或缺值時不放到表頭。 */
export function getSharedPriceDate(rows: HoldingRow[]): string | null {
  const dates = new Set(rows.map((row) => row.priceDate));
  if (dates.size !== 1) return null;
  const [date] = Array.from(dates);
  return date || null;
}
