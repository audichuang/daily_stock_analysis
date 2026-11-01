import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { StockBarItemComponent } from '../StockBarItem';
import type { StockBarItem } from '../../../types/analysis';

const issue1600Item: StockBarItem = {
  id: 1,
  stockCode: '600519',
  stockName: '贵州茅台股票股份有限公司',
  sentimentScore: 62,
  operationAdvice: '观望',
  analysisCount: 2,
  lastAnalysisTime: '2026-05-31T04:52:00Z',
  marketPhaseSummary: {
    market: 'CN',
    phase: 'non_trading',
    warnings: [],
  },
};

describe('StockBarItemComponent', () => {
  it('renders two lines without a delete button or the market phase', () => {
    render(
      <StockBarItemComponent
        item={issue1600Item}
        isViewing={false}
        onClick={vi.fn()}
      />,
    );

    const actions = screen.getByTestId('history-card-actions');
    expect(within(actions).getByText('观望 62')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /删除/ })).not.toBeInTheDocument();
    expect(screen.queryByText('CN · 非交易日')).not.toBeInTheDocument();

    expect(screen.getByText('贵州茅台股票股份.')).toBeVisible();
    expect(
      screen.getByRole('button', {
        name: /^贵州茅台股票股份有限公司 600519 历史记录$/,
      }),
    ).toBeInTheDocument();
  });

  it('shows the US ticker first and hides the MARKET code on the market row', () => {
    const { rerender } = render(
      <StockBarItemComponent
        item={{ ...issue1600Item, stockCode: 'AAPL', stockName: 'Apple' }}
        isViewing={false}
        onClick={vi.fn()}
      />,
    );
    const meta = screen.getByTestId('history-card-meta');
    expect(within(meta).getByText('Apple')).toBeInTheDocument();
    expect(screen.getByText('AAPL')).toBeInTheDocument();

    rerender(
      <StockBarItemComponent
        item={{ ...issue1600Item, stockCode: 'MARKET', stockName: '大盘复盘' }}
        isViewing={false}
        onClick={vi.fn()}
        isMarketReview
        marketLightLabel="台股 红灯"
      />,
    );
    expect(screen.getByTestId('market-review-light')).toHaveTextContent('台股 红灯');
    expect(screen.queryByText('MARKET')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '大盘复盘 历史记录' })).toBeInTheDocument();
  });

  it('uses structured action before legacy operation advice', () => {
    render(
      <StockBarItemComponent
        item={{
          ...issue1600Item,
          action: 'avoid',
          actionLabel: '回避',
          operationAdvice: '买入',
          sentimentScore: 35,
        }}
        isViewing={false}
        onClick={vi.fn()}
      />,
    );

    const actions = screen.getByTestId('history-card-actions');
    expect(within(actions).getByText('回避 35')).toBeInTheDocument();
    expect(within(actions).queryByText('买入 35')).not.toBeInTheDocument();
  });

  it('uses the unified legacy fallback for negated buy advice without structured action', () => {
    render(
      <StockBarItemComponent
        item={{
          ...issue1600Item,
          action: null,
          actionLabel: null,
          operationAdvice: '不建议买入，等待确认',
          sentimentScore: 28,
        }}
        isViewing={false}
        onClick={vi.fn()}
      />,
    );

    const actions = screen.getByTestId('history-card-actions');
    expect(within(actions).getByText('回避 28')).toBeInTheDocument();
    expect(within(actions).queryByText('买入 28')).not.toBeInTheDocument();
  });

  it('uses the unified legacy fallback for backend-aligned hold advice without structured action', () => {
    render(
      <StockBarItemComponent
        item={{
          ...issue1600Item,
          action: null,
          actionLabel: null,
          operationAdvice: '洗盘观察',
          sentimentScore: 48,
        }}
        isViewing={false}
        onClick={vi.fn()}
      />,
    );

    const actions = screen.getByTestId('history-card-actions');
    expect(within(actions).getByText('持有 48')).toBeInTheDocument();
  });

  it('does not render ambiguous English legacy advice as a buy action', () => {
    render(
      <StockBarItemComponent
        item={{
          ...issue1600Item,
          action: null,
          actionLabel: null,
          operationAdvice: 'buy or sell',
          sentimentScore: 28,
        }}
        isViewing={false}
        onClick={vi.fn()}
      />,
    );

    const actions = screen.getByTestId('history-card-actions');
    expect(within(actions).queryByText('buy 28')).not.toBeInTheDocument();
    expect(within(actions).getByText(/28/)).toBeInTheDocument();
  });

  it('does not render financial compound English advice as an action badge', () => {
    const { rerender } = render(
      <StockBarItemComponent
        item={{
          ...issue1600Item,
          action: null,
          actionLabel: null,
          operationAdvice: 'no selloff risk',
          sentimentScore: 28,
        }}
        isViewing={false}
        onClick={vi.fn()}
      />,
    );

    let actions = screen.getByTestId('history-card-actions');
    expect(within(actions).queryByText('持有 28')).not.toBeInTheDocument();
    expect(within(actions).getByText(/28/)).toBeInTheDocument();

    rerender(
      <StockBarItemComponent
        item={{
          ...issue1600Item,
          action: null,
          actionLabel: null,
          operationAdvice: 'sell-off risk remains low',
          sentimentScore: 31,
        }}
        isViewing={false}
        onClick={vi.fn()}
      />,
    );

    actions = screen.getByTestId('history-card-actions');
    expect(within(actions).queryByText('卖出 31')).not.toBeInTheDocument();
    expect(within(actions).getByText(/31/)).toBeInTheDocument();
  });

  it('does not render Chinese financial context legacy advice as an action badge', () => {
    const { rerender } = render(
      <StockBarItemComponent
        item={{
          ...issue1600Item,
          action: null,
          actionLabel: null,
          operationAdvice: '买盘增强，继续观察',
          sentimentScore: 32,
        }}
        isViewing={false}
        onClick={vi.fn()}
      />,
    );

    let actions = screen.getByTestId('history-card-actions');
    expect(within(actions).queryByText('买入 32')).not.toBeInTheDocument();
    expect(within(actions).getByText(/32/)).toBeInTheDocument();

    rerender(
      <StockBarItemComponent
        item={{
          ...issue1600Item,
          action: null,
          actionLabel: null,
          operationAdvice: '卖压缓解，继续观察',
          sentimentScore: 34,
        }}
        isViewing={false}
        onClick={vi.fn()}
      />,
    );

    actions = screen.getByTestId('history-card-actions');
    expect(within(actions).queryByText('卖出 34')).not.toBeInTheDocument();
    expect(within(actions).getByText(/34/)).toBeInTheDocument();
  });

  it('does not render multi-guard legacy advice as an action badge', () => {
    render(
      <StockBarItemComponent
        item={{
          ...issue1600Item,
          action: null,
          actionLabel: null,
          operationAdvice: 'risk alert, avoid buying',
          sentimentScore: 28,
        }}
        isViewing={false}
        onClick={vi.fn()}
      />,
    );

    const actions = screen.getByTestId('history-card-actions');
    expect(within(actions).queryByText('回避 28')).not.toBeInTheDocument();
    expect(within(actions).queryByText('预警 28')).not.toBeInTheDocument();
    expect(within(actions).getByText(/28/)).toBeInTheDocument();
  });
});
