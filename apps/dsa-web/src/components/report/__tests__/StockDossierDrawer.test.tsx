import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const themeState = vi.hoisted(() => ({ resolved: 'dark' }));
vi.mock('next-themes', () => ({ useTheme: () => ({ resolvedTheme: themeState.resolved }) }));

const getDossierHtml = vi.fn();
vi.mock('../../../api/stocks', () => ({ stocksApi: { getDossierHtml: (...args: unknown[]) => getDossierHtml(...args) } }));

const { StockDossierDrawer } = await import('../StockDossierDrawer');

const deferred = () => {
  let resolve!: (v: string) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<string>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

const frame = () => document.querySelector('iframe');
const frameHtml = () => frame()?.getAttribute('srcdoc');

describe('StockDossierDrawer', () => {
  afterEach(() => {
    cleanup();
    getDossierHtml.mockReset();
    themeState.resolved = 'dark';
  });

  it('shows the pending hint again when the theme changes mid-way', async () => {
    const light = deferred();
    getDossierHtml.mockImplementation((_code: string, opts: { theme: string; narrative?: boolean }) =>
      opts.theme === 'light' && opts.narrative ? light.promise : Promise.resolve(`<p>${opts.theme}</p>`));
    const { rerender } = render(<StockDossierDrawer stockCode="3324.TWO" onClose={vi.fn()} />);
    await waitFor(() => expect(frameHtml()).toBe('<p>dark</p>'));
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());

    themeState.resolved = 'light';
    rerender(<StockDossierDrawer stockCode="3324.TWO" onClose={vi.fn()} />);
    await waitFor(() => expect(frameHtml()).toBe('<p>light</p>'));
    expect(screen.getByRole('status')).toBeInTheDocument(); // 解讀版還在跑
    light.resolve('<p>light narrative</p>');
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
    expect(frameHtml()).toBe('<p>light narrative</p>');
  });

  it('shows the numbers first, then swaps in the narrative version', async () => {
    const numbers = deferred();
    const narrative = deferred();
    getDossierHtml.mockImplementation((_code: string, opts: { narrative?: boolean }) =>
      opts.narrative ? narrative.promise : numbers.promise);
    render(<StockDossierDrawer stockCode="3324.TWO" stockName="雙鴻" onClose={vi.fn()} />);

    expect(getDossierHtml).toHaveBeenCalledWith('3324.TWO', { theme: 'dark' });

    numbers.resolve('<p>numbers</p>');
    await waitFor(() => expect(frameHtml()).toBe('<p>numbers</p>'));
    expect(getDossierHtml).toHaveBeenCalledWith('3324.TWO', { theme: 'dark', narrative: true });
    expect(screen.getByRole('status')).toBeInTheDocument();

    narrative.resolve('<p>narrative</p>');
    await waitFor(() => expect(frameHtml()).toBe('<p>narrative</p>'));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('requests the narrative only after the numbers arrive', async () => {
    const numbers = deferred();
    getDossierHtml.mockImplementation((_code: string, opts: { narrative?: boolean }) =>
      opts.narrative ? Promise.resolve('<p>narrative</p>') : numbers.promise);
    render(<StockDossierDrawer stockCode="3324.TWO" onClose={vi.fn()} />);

    expect(getDossierHtml).toHaveBeenCalledTimes(1);
    numbers.resolve('<p>numbers</p>');
    await waitFor(() => expect(frameHtml()).toBe('<p>narrative</p>'));
    expect(getDossierHtml).toHaveBeenCalledTimes(2);
  });

  it('shows the error when the numbers request fails', async () => {
    getDossierHtml.mockRejectedValue(new Error('boom'));
    render(<StockDossierDrawer stockCode="3324.TWO" onClose={vi.fn()} />);

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(getDossierHtml).toHaveBeenCalledTimes(1);
  });

  it('keeps the numbers when the narrative request fails', async () => {
    getDossierHtml.mockImplementation((_code: string, opts: { narrative?: boolean }) =>
      opts.narrative ? Promise.reject(new Error('timeout')) : Promise.resolve('<p>numbers</p>'));
    render(<StockDossierDrawer stockCode="3324.TWO" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
    expect(frameHtml()).toBe('<p>numbers</p>');
    expect(frame()?.getAttribute('sandbox')).toBe('');
  });
});
