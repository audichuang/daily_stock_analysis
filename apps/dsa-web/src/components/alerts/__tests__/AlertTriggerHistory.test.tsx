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
    expect(screen.getByText('觸發歷史')).toBeInTheDocument();
    expect(screen.getByText('暫無觸發歷史')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/触发|评估|暂无|记录/);
    unmount();
    const table = renderIn('zh-TW', [trigger]);
    expect(screen.getByText('已略過')).toBeInTheDocument();
    expect(screen.getByText('資料來源')).toBeInTheDocument();
    expect(table.container.textContent).not.toMatch(/跳过|数据源|观察值|阈值/);
  });

  it('keeps the Simplified Chinese copy for the zh UI', () => {
    renderIn('zh', [trigger]);
    expect(screen.getByText('触发历史')).toBeInTheDocument();
    expect(screen.getByText('已跳过')).toBeInTheDocument();
    expect(screen.getByText('数据源')).toBeInTheDocument();
  });
});
