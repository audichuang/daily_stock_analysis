import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { AlertTriggerHistory } from '../AlertTriggerHistory';
import type { AlertTriggerItem } from '../../../types/alerts';

const trigger = {
  id: 1,
  status: 'skipped',
  target: '2330.TW',
  observedValue: 1000,
  threshold: 990,
  dataSource: 'shioaji',
  dataTimestamp: '2026-10-22T05:30:00Z',
  reason: 'cooldown',
} as unknown as AlertTriggerItem;

function renderIn(language: string, triggers: AlertTriggerItem[]) {
  window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, language);
  return render(
    <UiLanguageProvider>
      <AlertTriggerHistory triggers={triggers} />
    </UiLanguageProvider>,
  );
}

describe('AlertTriggerHistory', () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
  });

  it('uses Traditional Chinese copy in the zh-TW UI', () => {
    const { container, unmount } = renderIn('zh-TW', []);
    expect(screen.getByText('動態')).toBeInTheDocument();
    expect(screen.getByText('還沒有觸發紀錄')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/触发|评估|暂无|记录/);
    unmount();
    const list = renderIn('zh-TW', [trigger]);
    expect(list.container.textContent).toContain('略過');
    expect(list.container.textContent).not.toMatch(/跳过|数据源|观察值|阈值|skipped/);
  });

  it('keeps the Simplified Chinese copy for the zh UI', () => {
    const { container } = renderIn('zh', [trigger]);
    expect(screen.getByText('动态')).toBeInTheDocument();
    expect(container.textContent).toContain('跳过');
  });

  it('shows the rule name and the issue reason separately for named issues', () => {
    const { container } = renderIn('zh-TW', [
      { ...trigger, id: 21, status: 'failed', ruleName: 'named-failed', reason: 'quote fetch failed', diagnostics: 'trace-failed' },
      { ...trigger, id: 22, status: 'degraded', ruleName: 'named-degraded', reason: 'snapshot unavailable', diagnostics: 'trace-degraded' },
    ]);
    for (const value of ['named-failed', 'quote fetch failed', 'named-degraded', 'snapshot unavailable']) {
      expect(screen.getByText(value)).toBeInTheDocument();
    }
    expect(screen.getAllByText('查看診斷')).toHaveLength(2);
    expect(container.querySelectorAll('details pre')[0].textContent).toBe('trace-failed');
    expect(container.querySelectorAll('details pre')[1].textContent).toBe('trace-degraded');
  });

  it('keeps diagnostics reachable when a failed row has no reason', () => {
    const { container } = renderIn('zh-TW', [
      { ...trigger, id: 23, status: 'failed', ruleName: 'named', reason: null, diagnostics: 'only-diagnostics' },
    ]);
    expect(container.querySelector('details pre')?.textContent).toBe('only-diagnostics');
  });

  it('does not repeat the machine reason on named triggered rows', () => {
    renderIn('zh-TW', [{ ...trigger, id: 24, status: 'triggered', ruleName: 'named', reason: '2330.TW price above 1000', diagnostics: null }]);
    expect(screen.getByText('named')).toBeInTheDocument();
    expect(screen.queryByText('2330.TW price above 1000')).not.toBeInTheDocument();
    expect(screen.queryByText('查看診斷')).not.toBeInTheDocument();
  });

  it('colours triggered rows by severity and shows the real quote source', () => {
    const base = { ...trigger, status: 'triggered', quoteSource: 'yfinance' };
    const { container, unmount } = renderIn('zh-TW', [{ ...base, severity: 'critical' }]);
    expect(container.querySelector('.bg-danger')).not.toBeNull();
    expect(container.textContent).toContain('yfinance（可能延遲）');
    unmount();
    const info = renderIn('zh-TW', [{ ...base, severity: 'info' }]);
    expect(info.container.querySelector('.bg-danger')).toBeNull();
  });
});
