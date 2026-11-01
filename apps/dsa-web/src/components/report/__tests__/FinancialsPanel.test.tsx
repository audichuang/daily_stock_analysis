import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FinancialsPanel } from '../FinancialsPanel';
import { stocksApi } from '../../../api/stocks';
import type { FinancialCommentary, StockFinancials } from '../../../types/financials';
import { formatFinancialAmount, formatMetricValue } from '../../../utils/financialFormat';

vi.mock('../../../api/stocks', () => ({
  stocksApi: { getFinancials: vi.fn(), ensureFinancialCommentary: vi.fn() },
}));

const commentary = (status: FinancialCommentary['status']): FinancialCommentary => ({
  status,
  highlights: status === 'ready' ? [{
    metricKey: 'gross_margin', period: '2099Q2', importance: 'high',
    whatHappened: '毛利率上升', whyItMatters: '定價能力變強', howToRead: '毛利除以營收',
  }] : [],
  headline: status === 'ready' ? '這季重點' : null,
});

const payload = (over: Partial<StockFinancials> = {}): StockFinancials => ({
  stockCode: '2330.TW', status: 'ok', template: 'general', currency: 'TWD', tradingCurrency: 'TWD',
  source: { id: 'x', label: '公開資訊觀測站', sourceUnit: '新台幣千元' },
  periods: [{ key: '2099Q2', label: '2099 Q2', periodEnd: '2099-06-30', announceDate: '2099-08-14', announceDateKind: 'statutory_deadline' }],
  metrics: [
    { key: 'revenue', label: '營收', kind: 'amount', unit: 'TWD', definition: '固定教學', points: [
      { period: '2099Q2', value: 1.27e12, yoyPct: 36.05, qoqPct: 12, yoyPp: null, qoqPp: null, derived: false }] },
    { key: 'gross_margin', label: '毛利率', kind: 'ratio', unit: '%', definition: '毛利教學', points: [
      { period: '2099Q2', value: 67.72, yoyPct: null, qoqPct: null, yoyPp: 9.1, qoqPp: -1.5, derived: false }] },
  ],
  notApplicable: [], monthlyRevenue: [], limitations: [], isStale: false, commentary: commentary('disabled'), ...over,
});

describe('FinancialsPanel', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('shows numbers and does not call the LLM endpoint when disabled', async () => {
    vi.mocked(stocksApi.getFinancials).mockResolvedValue(payload());
    render(<FinancialsPanel stockCode="2330.TW" />);
    expect(await screen.findByText('1.27 兆元')).toBeInTheDocument();
    expect(screen.getByText('67.7%')).toBeInTheDocument();
    expect(stocksApi.ensureFinancialCommentary).not.toHaveBeenCalled();
    expect(screen.queryByText('AI 重点')).not.toBeInTheDocument();
  });

  it('marks the metric the commentary points at and reveals the explanation on tap', async () => {
    vi.mocked(stocksApi.getFinancials).mockResolvedValue(payload({ commentary: commentary('ready') }));
    render(<FinancialsPanel stockCode="2330.TW" />);
    const row = await screen.findByTestId('financials-metric-gross_margin');
    expect(row).toHaveTextContent('AI 重点');
    expect(screen.getByTestId('financials-metric-revenue')).not.toHaveTextContent('AI 重点');
    expect(screen.queryByText(/毛利率上升/)).not.toBeInTheDocument();
    fireEvent.click(row.querySelector('button')!);
    expect(await screen.findByText(/毛利率上升/)).toBeInTheDocument();
    expect(screen.getByText(/毛利教學/)).toBeInTheDocument();
  });

  it('requests generation only when the cache is missing and keeps numbers on failure', async () => {
    vi.mocked(stocksApi.getFinancials).mockResolvedValue(payload({ commentary: commentary('missing') }));
    vi.mocked(stocksApi.ensureFinancialCommentary).mockRejectedValue(new Error('boom'));
    render(<FinancialsPanel stockCode="2330.TW" />);
    expect(await screen.findByText('1.27 兆元')).toBeInTheDocument();
    await waitFor(() => expect(stocksApi.ensureFinancialCommentary).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/AI 导读暂时产生失败/)).toBeInTheDocument();
    expect(screen.getByText('1.27 兆元')).toBeInTheDocument();
  });

  it('never shows the previous stock when switching and the new request fails', async () => {
    vi.mocked(stocksApi.getFinancials).mockResolvedValueOnce(payload({ commentary: commentary('ready') }));
    const { rerender } = render(<FinancialsPanel stockCode="2330.TW" />);
    expect(await screen.findByText('1.27 兆元')).toBeInTheDocument();
    vi.mocked(stocksApi.getFinancials).mockRejectedValueOnce(new Error('boom'));
    rerender(<FinancialsPanel stockCode="AAPL" />);
    expect(screen.queryByText('1.27 兆元')).not.toBeInTheDocument();
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByText('1.27 兆元')).not.toBeInTheDocument();
    expect(screen.queryByText('这季重点')).not.toBeInTheDocument();
  });

  it('ignores a late commentary from the previous stock', async () => {
    let resolveFirst: (value: FinancialCommentary) => void = () => undefined;
    vi.mocked(stocksApi.getFinancials).mockResolvedValueOnce(payload({ commentary: commentary('missing') }));
    vi.mocked(stocksApi.ensureFinancialCommentary).mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }));
    const { rerender } = render(<FinancialsPanel stockCode="2330.TW" />);
    await waitFor(() => expect(stocksApi.ensureFinancialCommentary).toHaveBeenCalledTimes(1));
    vi.mocked(stocksApi.getFinancials).mockResolvedValueOnce(payload({ stockCode: 'AAPL', commentary: commentary('disabled') }));
    rerender(<FinancialsPanel stockCode="AAPL" />);
    await screen.findByText('1.27 兆元');
    resolveFirst(commentary('ready'));
    await waitFor(() => expect(screen.queryByText('这季重点')).not.toBeInTheDocument());
    expect(screen.queryByTestId('financials-headline')).not.toBeInTheDocument();
  });

  it('explains ETFs and hides unsupported markets', async () => {
    vi.mocked(stocksApi.getFinancials).mockResolvedValue(payload({ status: 'not_applicable', statusReason: 'ETF 是基金', metrics: [], periods: [] }));
    const { unmount } = render(<FinancialsPanel stockCode="00631L.TW" />);
    expect(await screen.findByTestId('financials-status')).toHaveTextContent('ETF 是基金');
    unmount();
    vi.mocked(stocksApi.getFinancials).mockResolvedValue(payload({ status: 'unsupported', metrics: [], periods: [] }));
    const { container } = render(<FinancialsPanel stockCode="600519.SH" />);
    await waitFor(() => expect(container.querySelector('[data-testid="financials-panel"]')).toBeNull());
  });
});

describe('financial format', () => {
  it('uses the reporting currency, a real minus and dash for missing', () => {
    expect(formatFinancialAmount(1.27e12, 'TWD')).toBe('1.27 兆元');
    expect(formatFinancialAmount(-3.3e9, 'USD')).toBe('−33.0 億美元');
    expect(formatFinancialAmount(null, 'USD')).toBe('—');
    expect(formatFinancialAmount(0, 'USD')).toBe('0 美元');
    expect(formatMetricValue({ kind: 'per_share', unit: 'TWD/ADR' }, 136.25, 'TWD')).toBe('136.25 元／ADR');
    expect(formatMetricValue({ kind: 'per_share', unit: 'TWD/股' }, 27.25, 'TWD')).toBe('27.25 元');
  });
});
