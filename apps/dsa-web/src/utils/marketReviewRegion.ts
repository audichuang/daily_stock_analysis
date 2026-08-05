import type { MarketReviewRegion } from '../types/analysis';

export type { MarketReviewRegion };

// 与后端 src/utils/market_review_region.py 的 MARKET_REVIEW_REGION_ORDER 保持一致（本 fork 含 tw）。
export const MARKET_REVIEW_REGION_ORDER: readonly MarketReviewRegion[] = ['cn', 'hk', 'us', 'tw', 'jp', 'kr'];

export function serializeMarketReviewRegions(regions: readonly MarketReviewRegion[]): string {
  const ordered = MARKET_REVIEW_REGION_ORDER.filter((region) => regions.includes(region));
  return ordered.length === MARKET_REVIEW_REGION_ORDER.length ? 'both' : ordered.join(',');
}
