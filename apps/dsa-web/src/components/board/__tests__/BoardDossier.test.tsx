import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
    expect(cell.container.textContent).toContain('结构突破'); // 結構方向不受影響；沒有 Provider 時預設 zh
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
    expect(container.textContent).toContain('结构突破'); // 沒有 Provider 時預設 zh
    expect(container.textContent).not.toContain('BOS');
    rerender(<BoardDossierCell summary={{ ...summary, structure: { ...summary.structure!, kind: 'SWEEP' } }} price={1400} />);
    expect(container.textContent).toContain('SWEEP');
  });
});
