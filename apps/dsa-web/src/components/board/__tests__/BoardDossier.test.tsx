import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DossierSummary } from '../../../api/stocks';

vi.mock('../../report/StockDossierDrawer', () => ({
  StockDossierDrawer: ({ stockCode }: { stockCode: string }) => <div role="dialog">drawer {stockCode}</div>,
}));

const { BoardDossierCell, BoardDossierPanel } = await import('../BoardDossier');

const summary: DossierSummary = {
  asOf: '2026-10-21',
  close: 1375,
  structure: { kind: 'BOS', bias: 'bear', date: '2026-10-19', level: 1395 },
  levels: [
    { label: '多頭 OB', low: 1240, high: 1365, kind: 'ob', bias: 'bull' },
    { label: '空頭 OB', low: 1395, high: 1460, kind: 'ob', bias: 'bear' },
  ],
  changes: [{ kind: 'foreign', tone: 'pos', text: '外資 5 日轉買 +587 張（20 日 -3,840）' }],
  verdicts: null,
};

describe('BoardDossier', () => {
  afterEach(cleanup);

  it('measures distances from the live quote, falling back to the as-of close', () => {
    const { rerender } = render(<BoardDossierCell summary={summary} price={1400} />);
    expect(screen.getByText(/-2\.5%/)).toBeInTheDocument(); // 1365 vs 1400 live
    expect(screen.getByText(/0\.0%/)).toBeInTheDocument(); // inside the bearish OB
    rerender(<BoardDossierCell summary={summary} price={null} />);
    expect(screen.getByText(/-0\.7%/)).toBeInTheDocument(); // 1365 vs 1375 close
    expect(screen.getByText(/\+1\.5%/)).toBeInTheDocument();
  });

  it('shows changes and opens the full report drawer', () => {
    render(<BoardDossierPanel code="3324.TWO" summary={summary} price={1375} />);
    expect(screen.getByText('外資 5 日轉買 +587 張（20 日 -3,840）')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button'));
    expect(screen.getByRole('dialog')).toHaveTextContent('drawer 3324.TWO');
  });

  it('renders a dash without a summary', () => {
    render(<BoardDossierCell summary={null} price={100} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
