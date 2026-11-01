import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { StockQuote } from '../../../api/stocks';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import type { DecisionSignalItem } from '../../../types/decisionSignals';
import { DecisionSignalTable } from '../DecisionSignalTable';

const signal: DecisionSignalItem = {
  id: 7,
  stockCode: '2330.TW',
  stockName: '台積電',
  market: 'tw',
  sourceType: 'analysis',
  sourceReportId: 3001,
  triggerSource: 'web',
  action: 'reduce',
  actionLabel: '减仓',
  confidence: 0.72,
  score: 82,
  horizon: '3d',
  stopLoss: 900,
  targetPrice: 1100,
  reason: '["外資連賣","跌破月線"]',
  planQuality: 'complete',
  status: 'active',
  signalPrice: 777,
  isHeld: true,
  stopTriggered: false,
};

const quote: StockQuote = { stockCode: '2330.TW', currentPrice: 1000, changePercent: -1.5 };

function renderTable(item: DecisionSignalItem = signal, currentQuote: StockQuote | null = quote) {
  window.localStorage.setItem('dsa.uiLanguage', 'zh');
  const onSelect = vi.fn();
  const onShowOlder = vi.fn();
  render(
    <UiLanguageProvider>
      <DecisionSignalTable items={[item]} quoteFor={() => currentQuote ?? undefined} onSelect={onSelect} onShowOlder={onShowOlder} />
    </UiLanguageProvider>,
  );
  return { onSelect, onShowOlder };
}

describe('DecisionSignalTable', () => {
  it('labels the action from the enum on a solid tag, not from the stored label', () => {
    renderTable();

    const row = within(screen.getByTestId('data-table-desktop'));
    const tag = row.getByText('减仓');
    expect(tag).toHaveAttribute('data-tone', 'caution');
    expect(tag).toHaveClass('bg-warning');
    expect(tag).not.toHaveClass('text-market-down');
  });

  it('renders JSON-array reasons as one readable line', () => {
    renderTable();

    expect(within(screen.getByTestId('data-table-desktop')).getByText('外資連賣；跌破月線')).toBeInTheDocument();
  });

  it('renders a two-line row at 88px on phones with the live quote and stop distance', () => {
    const { onSelect } = renderTable();

    const row = screen.getByTestId('signal-mobile-row-7');
    expect(row).toHaveClass('min-h-[88px]');
    expect(row).toHaveTextContent('1,000');
    expect(row).toHaveTextContent('−1.50%');
    expect(row).toHaveTextContent('（−10.0%）');
    expect(row).not.toHaveTextContent('777');
    fireEvent.click(row);
    expect(onSelect).toHaveBeenCalledWith(signal);
  });

  it('shows no reading on a phone row when the quote is missing', () => {
    renderTable(signal, null);

    const row = screen.getByTestId('signal-mobile-row-7');
    expect(row).toHaveTextContent('—');
    expect(row).not.toHaveTextContent('777');
    expect(row).not.toHaveTextContent('（');
  });

  it('opens the stock history from the older count without opening the drawer', () => {
    const { onSelect, onShowOlder } = renderTable({ ...signal, olderCount: 3 });

    fireEvent.click(within(screen.getByTestId('data-table-desktop')).getByRole('button', { name: /另有 3 笔/ }));

    expect(onShowOlder).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();
  });
});
