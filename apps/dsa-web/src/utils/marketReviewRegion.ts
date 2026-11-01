import type { MarketReviewLight, MarketReviewPayload, MarketReviewRegion } from '../types/analysis';

export type { MarketReviewRegion };

// 与后端 src/utils/market_review_region.py 的 MARKET_REVIEW_REGION_ORDER 保持一致（本 fork 含 tw）。
export const MARKET_REVIEW_REGION_ORDER: readonly MarketReviewRegion[] = ['cn', 'hk', 'us', 'tw', 'jp', 'kr'];

export function serializeMarketReviewRegions(regions: readonly MarketReviewRegion[]): string {
  const ordered = MARKET_REVIEW_REGION_ORDER.filter((region) => regions.includes(region));
  return ordered.length === MARKET_REVIEW_REGION_ORDER.length ? 'both' : ordered.join(',');
}

const isMarketReviewRegion = (value: string): value is MarketReviewRegion =>
  (MARKET_REVIEW_REGION_ORDER as readonly string[]).includes(value);

/** 把後端的市場範圍字串（tw,us／both）轉成顯示文字；不認得的代號原樣顯示，不吞掉。 */
export function formatMarketReviewRegion(
  region: string | null | undefined,
  labels: Record<MarketReviewRegion, string>,
  separator = '＋',
): string {
  const tokens = (region ?? '').split(',').map((token) => token.trim().toLowerCase()).filter(Boolean);
  if (tokens.includes('both')) {
    return MARKET_REVIEW_REGION_ORDER.map((item) => labels[item]).join(separator);
  }
  return tokens.map((token) => (isMarketReviewRegion(token) ? labels[token] : token)).join(separator);
}

/** 取出複盤 payload 裡每個市場的燈號；沒有讀數的市場不列。 */
export function getMarketReviewLights(
  payload?: MarketReviewPayload | null,
): Array<{ region: string; light: MarketReviewLight }> {
  if (!payload) return [];
  const entries: Array<[string, MarketReviewPayload]> = payload.markets
    ? Object.entries(payload.markets)
    : [[payload.region ?? '', payload]];
  return entries.flatMap(([region, market]) => (
    market.marketLight?.status && market.marketLight.status !== 'unavailable'
      ? [{ region, light: market.marketLight }]
      : []
  ));
}
