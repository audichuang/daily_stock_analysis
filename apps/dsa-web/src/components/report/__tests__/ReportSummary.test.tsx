import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AnalysisReport } from '../../../types/analysis';
import type { ResearchArtifact } from '../../../types/researchArtifact';
import { ReportSummary } from '../ReportSummary';

// Every section is replaced by a marker so the test only checks the page order.
// vi.mock factories are hoisted above imports, so the helper must be hoisted too.
const { marker, overviewMode } = vi.hoisted(() => ({
  marker: (id: string) => function SectionMarker() {
    return <div data-section={id} />;
  },
  // Key-level tests switch the overview back to the real component to see what it receives.
  overviewMode: { real: false },
}));

vi.mock('../ReportOverview', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../ReportOverview')>();
  const OverviewMarker = marker('overview');
  return {
    ReportOverview: (props: React.ComponentProps<typeof actual.ReportOverview>) => (
      overviewMode.real ? <actual.ReportOverview {...props} /> : <OverviewMarker />
    ),
  };
});
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

  describe('key levels in the overview', () => {
    afterEach(() => {
      overviewMode.real = false;
    });

    const levelReport = (overrides: Partial<AnalysisReport> = {}): AnalysisReport => ({
      ...report,
      meta: {
        ...report.meta,
        reportLanguage: 'en',
        currentPrice: 2350,
        previousReport: { stopLoss: 2370 },
      },
      summary: { ...report.summary, action: 'reduce' },
      strategy: {
        sniperPricesSource: 'structured',
        sniperPrices: { stopLoss: 2320, takeProfit: 2410 },
        stopLoss: '2320',
        takeProfit: '2410',
      },
      ...overrides,
    });

    const renderSummary = (data: AnalysisReport) => {
      overviewMode.real = true;
      return render(
        <MemoryRouter>
          <ReportSummary data={data} />
        </MemoryRouter>,
      );
    };

    it('passes structured sniper prices so the overview shows the key-level strip', () => {
      renderSummary(levelReport());

      const strip = screen.getByTestId('report-key-levels');
      expect(strip).toHaveTextContent(/2,320/);
      expect(strip).toHaveTextContent(/2,410/);
    });

    it('compares the previous stop with the current one', () => {
      renderSummary(levelReport());

      expect(screen.getByTestId('report-comparison')).toHaveTextContent(/2,370(\.0+)? → 2,320/);
    });

    it('hides the strip and the stop comparison when the no-news guardrail blocks levels', () => {
      // Only eventGap matters to ReportSummary here; the rest of the artifact is irrelevant.
      const structuredReport = { eventGap: { triggered: true, blockedWithoutNews: true } } as unknown as ResearchArtifact;
      renderSummary(levelReport({ structuredReport }));

      expect(screen.queryByTestId('report-key-levels')).not.toBeInTheDocument();
      expect(screen.getByTestId('report-comparison')).not.toHaveTextContent('→');
    });
  });
});
