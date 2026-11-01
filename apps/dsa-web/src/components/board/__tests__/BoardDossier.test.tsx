import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DossierSummary } from '../../../api/stocks';

const { createLevelAlerts } = vi.hoisted(() => ({ createLevelAlerts: vi.fn() }));
vi.mock('../../../api/stocks', () => ({ stocksApi: { createLevelAlerts } }));

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
    expect(screen.getAllByRole('button')).toHaveLength(1);      // 警報預設關閉：沒有「建立價位警報」
    fireEvent.click(screen.getByRole('button'));
    expect(screen.getByRole('dialog')).toHaveTextContent('drawer 3324.TWO');
  });

  it('does not measure old-basis levels against the live price after an ex-dividend or capital reduction', () => {
    const adjusted = { ...summary, adjustedAfter: true };
    const cell = render(<BoardDossierCell summary={adjusted} price={1400} />);
    expect(cell.container.textContent).not.toMatch(/%/);
    expect(cell.container.textContent).toMatch(/ex-div|除權息|除权息/);
    expect(cell.container.textContent).toContain('▼突破'); // 結構方向不受影響；沒有 Provider 時預設 zh
    cell.unmount();
    render(<BoardDossierPanel code="1516.TW" summary={adjusted} price={24.73} levelAlertsEnabled />);
    expect(screen.getByRole('note')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Create level alerts|建立价位警报|建立價位警報/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/%）/)).not.toBeInTheDocument();
  });

  it('keeps distances and the alert button when there was no adjustment', () => {
    const cell = render(<BoardDossierCell summary={{ ...summary, adjustedAfter: false }} price={1400} />);
    expect(cell.container.textContent).toMatch(/-2\.5%/);
    expect(cell.container.textContent).not.toMatch(/ex-div|除權息|除权息/);
    cell.unmount();
    render(<BoardDossierPanel code="3324.TWO" summary={{ ...summary, adjustedAfter: false }} price={1375} levelAlertsEnabled />);
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Create level alerts|建立价位警报|建立價位警報/ })).toBeInTheDocument();
  });

  it('renders a dash without a summary', () => {
    render(<BoardDossierCell summary={null} price={100} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  const dialogButton = (name: RegExp) => screen.getByRole('button', { name });
  const CONFIRM = /^(OK|确定|確定)$/;
  const CANCEL = /^(Cancel|取消)$/;

  it('creates alerts at the displayed nearest levels only after confirmation', async () => {
    createLevelAlerts.mockReset();
    createLevelAlerts.mockResolvedValue(2);
    const nativeConfirm = vi.spyOn(window, 'confirm');
    render(<BoardDossierPanel code="3324.TWO" summary={summary} price={1375} levelAlertsEnabled />);
    const button = screen.getByRole('button', { name: /Create level alerts|建立价位警报|建立價位警報/ });
    fireEvent.click(button);
    expect(createLevelAlerts).not.toHaveBeenCalled();
    fireEvent.click(dialogButton(CANCEL));
    expect(createLevelAlerts).not.toHaveBeenCalled();
    fireEvent.click(button);
    fireEvent.click(dialogButton(CONFIRM));
    expect(createLevelAlerts).toHaveBeenCalledWith('3324.TWO', {
      support: summary.levels[0],
      resistance: summary.levels[1],
    });
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/2/));
    // 不再走瀏覽器原生對話框
    expect(nativeConfirm).not.toHaveBeenCalled();
    nativeConfirm.mockRestore();
  });

  it('locks the alert button while the request is in flight, then unlocks it', async () => {
    let finish!: (n: number) => void;
    createLevelAlerts.mockReset();
    createLevelAlerts.mockReturnValueOnce(new Promise<number>((res) => { finish = res; })).mockRejectedValueOnce(new Error('boom'));
    render(<BoardDossierPanel code="3324.TWO" summary={summary} price={1375} levelAlertsEnabled />);
    const button = screen.getByRole('button', { name: /Create level alerts|建立价位警报|建立價位警報/ });
    fireEvent.click(button);
    fireEvent.click(dialogButton(CONFIRM));
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(createLevelAlerts).toHaveBeenCalledTimes(1);
    finish(1);
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    fireEvent.click(dialogButton(CONFIRM));
    expect(createLevelAlerts).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/boom/));
    expect(button).toBeEnabled();
  });

  it('shows the structure kind in plain words only under Chinese UI, keeping unknown kinds', () => {
    const { container, rerender } = render(<BoardDossierCell summary={summary} price={1400} />);
    expect(container.textContent).toContain('▼突破'); // 沒有 Provider 時預設 zh
    expect(container.textContent).not.toContain('BOS');
    rerender(<BoardDossierCell summary={{ ...summary, structure: { ...summary.structure!, kind: 'SWEEP' } }} price={1400} />);
    expect(container.textContent).toContain('SWEEP');
  });

  it('keeps the structure cell on one line: direction · support · resistance', () => {
    render(<BoardDossierCell summary={summary} price={1375} />);
    const cell = screen.getByTestId('board-dossier-cell');
    expect(cell).toHaveClass('whitespace-nowrap');
    expect(cell.textContent).toBe('▼突破 · 撑 -0.7% · 压 +1.5%');
    // no stacked block rows inside
    expect(cell.querySelectorAll('div')).toHaveLength(0);
  });

  const jargon: DossierSummary = {
    ...summary,
    levels: [
      { label: 'SSL', low: 1300, high: 1300, kind: 'ssl', bias: null },
      { label: '空頭 FVG', low: 1390, high: 1400, kind: 'fvg', bias: 'bear' },
    ],
  };

  it('translates SSL / FVG / OB into plain words and keeps the raw label in the tooltip', async () => {
    render(<BoardDossierPanel code="3324.TWO" summary={jargon} price={1375} />);
    const lines = screen.getByTestId('board-dossier-summary');
    expect(lines.textContent).not.toMatch(/SSL|FVG|\bOB\b/);
    expect(lines.textContent).toContain('前低流动性');
    expect(lines.textContent).toContain('空头缺口未补');
    fireEvent.mouseEnter(within(lines).getByText('前低流动性').parentElement!);
    expect(await screen.findByRole('tooltip')).toHaveTextContent('SSL');
    // OB from the base fixture too
    cleanup();
    render(<BoardDossierPanel code="3324.TWO" summary={summary} price={1375} />);
    expect(screen.getByTestId('board-dossier-summary').textContent).not.toMatch(/\bOB\b/);
    expect(screen.getByTestId('board-dossier-summary').textContent).toContain('多头订单块');
  });

  it('splits the summary into a text-sm numbers line and a muted text-xs structure/date line', () => {
    render(<BoardDossierPanel code="3324.TWO" summary={summary} price={1375} />);
    const [numbers, meta] = Array.from(screen.getByTestId('board-dossier-summary').children);
    expect(numbers).toHaveClass('text-sm');
    expect(numbers.textContent).toContain('-0.7%');
    expect(meta).toHaveClass('text-xs', 'text-secondary-text');
    expect(meta.textContent).toContain('2026-10-21');
    expect(meta.textContent).toContain('10-19');
  });

  describe('action row mode', () => {
    it('puts View report, Four pillars and Create alert in one row, and the alert opens a menu when level alerts exist', () => {
      const onOpenReport = vi.fn();
      const onCreateAlert = vi.fn();
      render(
        <BoardDossierPanel code="3324.TWO" summary={summary} price={1375} levelAlertsEnabled onOpenReport={onOpenReport} onCreateAlert={onCreateAlert} />,
      );
      const row = screen.getByTestId('board-expanded-actions');
      const names = within(row).getAllByRole('button').map((b) => b.textContent);
      expect(names).toEqual(['看报告', '四维度', '建立警报']);
      fireEvent.click(within(row).getByRole('button', { name: '看报告' }));
      expect(onOpenReport).toHaveBeenCalledTimes(1);
      fireEvent.click(within(row).getByRole('button', { name: '建立警报' }));
      const menu = screen.getByRole('menu');
      expect(within(menu).getAllByRole('menuitem').map((m) => m.textContent)).toEqual(['自定义警报', '建立价位警报']);
      fireEvent.click(within(menu).getByRole('menuitem', { name: '自定义警报' }));
      expect(onCreateAlert).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
      fireEvent.click(within(row).getByRole('button', { name: '四维度' }));
      expect(screen.getByRole('dialog')).toHaveTextContent('drawer 3324.TWO');
    });

    it('uses a plain Create alert button when there is only the custom alert', () => {
      const onCreateAlert = vi.fn();
      render(<BoardDossierPanel code="3324.TWO" summary={summary} price={1375} onOpenReport={vi.fn()} onCreateAlert={onCreateAlert} />);
      fireEvent.click(screen.getByRole('button', { name: '建立警报' }));
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
      expect(onCreateAlert).toHaveBeenCalledTimes(1);
    });

    it('still shows the actions for a stock without a summary, minus Four pillars', () => {
      render(<BoardDossierPanel code="NVDA" summary={null} onOpenReport={vi.fn()} onCreateAlert={vi.fn()} />);
      const names = within(screen.getByTestId('board-expanded-actions')).getAllByRole('button').map((b) => b.textContent);
      expect(names).toEqual(['看报告', '建立警报']);
    });
  });
});
