import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { AnalysisReport } from '../../../types/analysis';
import { ReportSummary } from '../ReportSummary';

// Every section is replaced by a marker so the test only checks the page order.
// vi.mock factories are hoisted above imports, so the helper must be hoisted too.
const { marker } = vi.hoisted(() => ({
  marker: (id: string) => function SectionMarker() {
    return <div data-section={id} />;
  },
}));

vi.mock('../ReportOverview', () => ({ ReportOverview: marker('overview') }));
vi.mock('../EventGapCard', () => ({
  EventGapCard: marker('event-gap'),
  ReportChangeConditions: marker('change-conditions'),
}));
vi.mock('../ReportStrategy', () => ({ ReportStrategy: marker('strategy') }));
vi.mock('../StockPriceChart', () => ({ StockPriceChart: marker('price-chart') }));
vi.mock('../ReportEventOutlook', () => ({ ReportEventOutlook: marker('event-outlook') }));
vi.mock('../FinancialsPanel', () => ({ FinancialsPanel: marker('financials') }));
vi.mock('../EvidenceSection', () => ({ EvidenceSection: marker('evidence') }));
vi.mock('../ReportNews', () => ({ ReportNews: marker('news') }));
vi.mock('../AnalysisContextSummary', () => ({ AnalysisContextSummary: marker('context') }));
vi.mock('../ReportDiagnostics', () => ({ ReportDiagnostics: marker('diagnostics') }));
vi.mock('../ReportDetails', () => ({ ReportDetails: marker('details') }));
vi.mock('../MarketReviewReportView', () => ({ MarketReviewReportView: marker('market-review') }));

const report: AnalysisReport = {
  meta: {
    id: 1257,
    queryId: 'q-1',
    stockCode: '2330.TW',
    stockName: '台積電',
    reportType: 'detailed',
    reportLanguage: 'zh-TW',
    createdAt: '2099-01-01T00:00:00Z',
    currentPrice: 100,
    currency: 'TWD',
  },
  summary: {
    analysisSummary: '',
    operationAdvice: '',
    action: 'reduce',
    trendPrediction: '',
    sentimentScore: 50,
  },
  strategy: {
    sniperPricesSource: 'structured',
    sniperPrices: { stopLoss: 80, takeProfit: 120 },
    stopLoss: '80',
    takeProfit: '120',
  },
};

describe('ReportSummary', () => {
  it('puts key levels and the chart before the financials', () => {
    const { container } = render(
      <MemoryRouter>
        <ReportSummary data={report} />
      </MemoryRouter>,
    );

    const order = Array.from(container.querySelectorAll('[data-section]')).map((node) => node.getAttribute('data-section'));
    expect(order).toEqual([
      'overview',
      'event-gap',
      'strategy',
      'price-chart',
      'change-conditions',
      'event-outlook',
      'financials',
      'evidence',
      'news',
      'context',
      'diagnostics',
      'details',
    ]);
    expect(order.indexOf('strategy')).toBeLessThan(order.indexOf('financials'));
    expect(screen.getByTestId('report-data-quality')).toBeInTheDocument();
  });
});
