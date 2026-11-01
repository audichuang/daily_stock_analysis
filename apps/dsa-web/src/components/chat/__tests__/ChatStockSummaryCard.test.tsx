import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { StockQuote } from '../../../api/stocks';
import { ChatStockSummaryCard } from '../ChatStockSummaryCard';

const stock = { stock_code: '2330.TW', stock_name: '台積電', canonical_id: '2330.TW', asset_type: 'stock' as const };
const quoteOf = (overrides: Partial<StockQuote>): StockQuote => ({
  stockCode: '2330.TW',
  stockName: '台積電',
  currentPrice: 1000,
  changePercent: 1,
  ...overrides,
} as StockQuote);

const renderCard = (quote: StockQuote | null) => render(<ChatStockSummaryCard stock={stock} quote={quote} />);

describe('ChatStockSummaryCard live label', () => {
  it('says live for a fresh quote', () => {
    renderCard(quoteOf({ source: 'shioaji', isStale: false }));
    expect(screen.getByText('实时')).toBeInTheDocument();
  });

  it('does not say live for a stale quote', () => {
    renderCard(quoteOf({ source: 'shioaji', isStale: true }));
    expect(screen.queryByText('实时')).not.toBeInTheDocument();
    expect(screen.getByText('延迟')).toBeInTheDocument();
  });

  it('does not say live for a fallback-source quote', () => {
    renderCard(quoteOf({ source: 'fallback', isStale: false }));
    expect(screen.queryByText('实时')).not.toBeInTheDocument();
    expect(screen.getByText('延迟')).toBeInTheDocument();
  });

  it('says nothing when there is no quote', () => {
    renderCard(null);
    expect(screen.queryByText('实时')).not.toBeInTheDocument();
    expect(screen.queryByText('延迟')).not.toBeInTheDocument();
  });
});
