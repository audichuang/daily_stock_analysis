import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AlertRuleList } from '../AlertRuleList';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import type { AlertRuleItem } from '../../../types/alerts';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';

const priceRule: AlertRuleItem = {
  id: 1,
  name: 'rule-one',
  targetScope: 'single_symbol',
  target: '2330.TW',
  alertType: 'price_cross',
  parameters: { direction: 'above', price: 1100 },
  severity: 'warning',
  enabled: true,
  source: 'api',
  lastTriggeredAt: null,
};

const handlers = {
  onSearchTargetChange: vi.fn(),
  onScopeFilterChange: vi.fn(),
  onEnabledFilterChange: vi.fn(),
  onAlertTypeFilterChange: vi.fn(),
  onLoadMore: vi.fn(),
  onToggleEnabled: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
  onTest: vi.fn(),
  onDismissTest: vi.fn(),
};

function renderList(rules: AlertRuleItem[], extra: Partial<React.ComponentProps<typeof AlertRuleList>> = {}) {
  return render(
    <UiLanguageProvider>
      <AlertRuleList
        rules={rules}
        total={rules.length}
        searchTarget=""
        scopeFilter="all"
        enabledFilter="all"
        alertTypeFilter="all"
        {...handlers}
        {...extra}
      />
    </UiLanguageProvider>,
  );
}

describe('AlertRuleList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh-TW');
  });
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
  });

  it('renders a price rule as a sentence with price and distance', () => {
    renderList([priceRule], { quotes: { '2330.TW': { price: 1000, name: '台積電' } } });
    expect(screen.getByText('當 台積電 2330.TW 站上 1,100 時提醒')).toBeInTheDocument();
    expect(screen.getByText(/現價 1,000 · 距離 \+10\.0%/)).toBeInTheDocument();
    expect(screen.getByText(/尚未觸發/)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('uses the unified minus sign when the target is below the current price', () => {
    renderList([priceRule], { quotes: { '2330.TW': { price: 1250, name: '台積電' } } });
    expect(screen.getByText(/距離 \u221212\.0%/)).toBeInTheDocument();
  });

  it('does not show machine values for portfolio or market rules', () => {
    const { container } = renderList([
      { ...priceRule, id: 2, targetScope: 'portfolio_account', target: 'all', alertType: 'portfolio_concentration', parameters: {} },
      { ...priceRule, id: 3, targetScope: 'portfolio_holdings', target: 'all', alertType: 'portfolio_price_stale', parameters: {} },
      { ...priceRule, id: 4, targetScope: 'market', target: 'tw', alertType: 'market_light_status', parameters: { statuses: ['red'] } },
    ]);
    expect(screen.getByText('當 全部帳戶 持股集中度超過上限 時提醒')).toBeInTheDocument();
    expect(screen.getByText('當 台股 大盤信號轉為 紅燈 時提醒')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/top_weight_pct|price_stale|single_symbol|portfolio_account/);
  });

  it('shows cooldown from backend cooldownActive only', () => {
    renderList([{ ...priceRule, cooldownActive: false, cooldownUntil: '2099-05-18T10:30:00' }]);
    expect(screen.queryByText(/冷卻到/)).not.toBeInTheDocument();
    cleanup();
    renderList([{ ...priceRule, cooldownActive: true, cooldownUntil: '2099-05-18T10:30:00' }]);
    expect(screen.getByText(/冷卻到/)).toBeInTheDocument();
  });

  it('toggles from the switch and runs actions from the menu', () => {
    renderList([priceRule]);
    fireEvent.click(screen.getByRole('switch', { name: '啟用 rule-one' }));
    expect(handlers.onToggleEnabled).toHaveBeenCalledWith(priceRule);

    fireEvent.click(screen.getByRole('button', { name: 'rule-one 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '編輯' }));
    expect(handlers.onEdit).toHaveBeenCalledWith(priceRule);

    fireEvent.click(screen.getByRole('button', { name: 'rule-one 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '試算目前條件' }));
    expect(handlers.onTest).toHaveBeenCalledWith(priceRule);
  });

  it('expands the dry-run result in place and says no notification is sent', () => {
    renderList([priceRule], {
      testResults: { 1: { ruleId: 1, status: 'triggered', triggered: true, observedValue: 1200, message: 'raw' } },
    });
    const card = within(screen.getByTestId('alert-rule-1'));
    expect(card.getByText('目前條件已達成')).toBeInTheDocument();
    expect(card.getByText(/只試算，不會送出通知/)).toBeInTheDocument();
    expect(card.getByText(/目前數值 1200/)).toBeInTheDocument();
  });

  it('does not call a skipped single target an unmet condition', () => {
    renderList([priceRule], {
      testResults: {
        1: {
          ruleId: 1, status: 'not_triggered', triggered: false, message: 'No realtime quote available',
          evaluatedCount: 1, skippedCount: 1, triggeredCount: 0, degradedCount: 0,
          targetResults: [{ target: '2330.TW', status: 'not_triggered', recordStatus: 'skipped', triggered: false, message: 'No realtime quote available' }],
        },
      },
    });
    const card = within(screen.getByTestId('alert-rule-1'));
    expect(card.getByText('無法評估目前條件')).toBeInTheDocument();
    expect(card.queryByText('目前條件未達成')).not.toBeInTheDocument();
    expect(card.getByText('No realtime quote available')).toBeInTheDocument();
  });

  it('shows the target reason instead of the aggregate count text', () => {
    renderList([priceRule], {
      testResults: {
        1: {
          ruleId: 1, status: 'not_triggered', triggered: false, evaluatedCount: 1, skippedCount: 1,
          message: 'Evaluated 1 targets: 0 triggered, 0 degraded, 1 skipped, 0 failed',
          targetResults: [{ target: 'tw', status: 'not_triggered', recordStatus: 'skipped', triggered: false, message: 'tw market is not a trading day' }],
        },
      },
    });
    const card = within(screen.getByTestId('alert-rule-1'));
    expect(card.getByText('tw market is not a trading day')).toBeInTheDocument();
    expect(card.queryByText(/Evaluated 1 targets/)).not.toBeInTheDocument();
  });

  it('treats a target failure without counters as not evaluated', () => {
    renderList([priceRule], {
      testResults: {
        1: {
          ruleId: 1, status: 'not_triggered', triggered: false, message: 'x', evaluatedCount: 2,
          targetResults: [
            { target: 'A', status: 'not_triggered', recordStatus: 'failed', triggered: false, message: 'boom' },
            { target: 'B', status: 'not_triggered', triggered: false, message: 'below' },
          ],
        },
      },
    });
    const card = within(screen.getByTestId('alert-rule-1'));
    expect(card.getByText('部分標的無法評估')).toBeInTheDocument();
    expect(card.getByText('A：boom')).toBeInTheDocument();
    expect(card.queryByText('B：below')).not.toBeInTheDocument();
  });

  it('keeps partial batch failures visible even when a target triggered', () => {
    renderList([priceRule], {
      testResults: {
        1: {
          ruleId: 1, status: 'triggered', triggered: true, message: 'x',
          evaluatedCount: 3, triggeredCount: 1, degradedCount: 1, skippedCount: 0,
          targetResults: [
            { target: 'A', status: 'triggered', recordStatus: 'triggered', triggered: true, message: 'ok' },
            { target: 'B', displayTarget: '自選 B', status: 'not_triggered', recordStatus: 'degraded', triggered: false, message: 'snapshot gone' },
            { target: 'C', status: 'not_triggered', triggered: false, message: 'below' },
          ],
        },
      },
    });
    const card = within(screen.getByTestId('alert-rule-1'));
    expect(card.getByText('目前條件已達成')).toBeInTheDocument();
    expect(card.getByText(/1 檔無法評估/)).toBeInTheDocument();
    expect(card.getByText('自選 B：snapshot gone')).toBeInTheDocument();
  });

  it('still reports a real miss when every target was evaluated', () => {
    renderList([priceRule], {
      testResults: {
        1: {
          ruleId: 1, status: 'not_triggered', triggered: false, message: 'below', evaluatedCount: 1, skippedCount: 0, degradedCount: 0,
          targetResults: [{ target: '2330.TW', status: 'not_triggered', triggered: false, message: 'below' }],
        },
      },
    });
    const card = within(screen.getByTestId('alert-rule-1'));
    expect(card.getByText('目前條件未達成')).toBeInTheDocument();
    expect(card.queryByText('無法評估目前條件')).not.toBeInTheDocument();
  });

  it('confirms deletion before calling onDelete', () => {
    renderList([priceRule]);
    fireEvent.click(screen.getByRole('button', { name: 'rule-one 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '刪除' }));
    expect(handlers.onDelete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '刪除' }));
    expect(handlers.onDelete).toHaveBeenCalledWith(priceRule);
  });

  it('shows the guide only without filters and load more only when rows remain', () => {
    renderList([], { guide: <div>guide</div> });
    expect(screen.getByText('guide')).toBeInTheDocument();
    cleanup();
    renderList([], { guide: <div>guide</div>, hasFilters: true });
    expect(screen.queryByText('guide')).not.toBeInTheDocument();
    expect(screen.getByText('沒有符合篩選條件的規則')).toBeInTheDocument();
    cleanup();
    renderList([priceRule], { total: 5 });
    fireEvent.click(screen.getByRole('button', { name: '載入更多' }));
    expect(handlers.onLoadMore).toHaveBeenCalled();
  });
});
