import { useEffect, useMemo, useState } from 'react';
import { stocksApi, type StockQuote } from '../api/stocks';
import { toAssetAwareCodeKey } from '../utils/stockCode';

/** 清單查報價用的鍵；後端可能把代號正規化，兩邊都經過同一個函式才對得起來。 */
export const stockQuoteKey = (code: string): string => toAssetAwareCodeKey(code, 'stock');

/** 只在代號集合或 refreshVersion 變動時查一次批次行情，不輪詢（輪詢是盯盤頁的事）。 */
export function useStockQuotes(codes: string[], refreshVersion = 0): Map<string, StockQuote> {
  const signature = useMemo(() => Array.from(new Set(codes)).sort().join(','), [codes]);
  const [quotes, setQuotes] = useState<Map<string, StockQuote>>(new Map());

  useEffect(() => {
    if (!signature) {
      setQuotes(new Map());
      return undefined;
    }
    let active = true;
    void stocksApi.getQuotesBatched(signature.split(',')).then((items) => {
      if (!active) return;
      const next = new Map<string, StockQuote>();
      for (const item of items) {
        if (item.quote) next.set(stockQuoteKey(item.stockCode), item.quote);
      }
      setQuotes(next);
    });
    return () => {
      active = false;
    };
  }, [refreshVersion, signature]);

  return quotes;
}
