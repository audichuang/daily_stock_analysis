import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ReportStrategy } from '../ReportStrategy';

const structured = {
  sniperPricesSource: 'structured' as const,
  sniperPrices: { idealBuy: 95, secondaryBuy: 90, stopLoss: 80, takeProfit: 120 },
  idealBuy: '95',
  secondaryBuy: '90',
  stopLoss: '80（跌破季線）',
  takeProfit: '120',
};

const legacy = {
  sniperPricesSource: 'legacy' as const,
  sniperPrices: { stopLoss: 40.2 },
  stopLoss: '40.2元（今日收盤 42.55 減一個 ATR）',
};

describe('ReportStrategy', () => {
  it.each(['reduce', 'watch'] as const)('hides entry levels for %s and shows risk line and bounce-reduce price', (action) => {
    render(<ReportStrategy strategy={structured} action={action} currentPrice={100} language="zh-TW" />);

    expect(screen.queryByText('進場價')).not.toBeInTheDocument();
    expect(screen.queryByText('加碼價')).not.toBeInTheDocument();
    expect(screen.getAllByText('風控線').length).toBeGreaterThan(0);
    expect(screen.getAllByText('反彈減碼價').length).toBeGreaterThan(0);
  });

  it('shows entry levels when the action is buy', () => {
    render(<ReportStrategy strategy={structured} action="buy" currentPrice={100} language="zh-TW" />);

    expect(screen.getByText('進場價')).toBeInTheDocument();
    expect(screen.getByText('關鍵價位')).toBeInTheDocument();
  });

  it('computes distance and the ladder for structured prices, keeping the reason as small text', () => {
    render(<ReportStrategy strategy={structured} action="hold" currentPrice={100} language="zh-TW" />);

    const stop = screen.getByTestId('level-stopLoss');
    expect(stop).toHaveTextContent('距現價 −20.00%');
    expect(stop).toHaveTextContent('80（跌破季線）');
    expect(screen.getByTestId('level-takeProfit')).toHaveTextContent('距現價 +20.00%');
    expect(screen.getByTestId('level-ladder')).toBeInTheDocument();
  });

  it('shows legacy text verbatim with no distance or ladder, even when a parsed number exists', () => {
    render(<ReportStrategy strategy={legacy} action="reduce" currentPrice={42.55} language="zh-TW" />);

    const stop = screen.getByTestId('level-stopLoss');
    expect(stop).toHaveTextContent('40.2元（今日收盤 42.55 減一個 ATR）');
    expect(stop).not.toHaveTextContent('距現價');
    expect(screen.queryByTestId('level-ladder')).not.toBeInTheDocument();
  });

  it('merges empty levels into one grey line', () => {
    render(<ReportStrategy strategy={legacy} action="reduce" language="zh-TW" />);

    expect(screen.getByTestId('levels-missing')).toHaveTextContent('未提供：反彈減碼價');
    expect(screen.queryByTestId('level-takeProfit')).not.toBeInTheDocument();
  });

  it('lists all four levels for old reports without an action', () => {
    render(<ReportStrategy strategy={{ idealBuy: '120' }} language="zh-TW" />);

    expect(screen.getByText('進場價')).toBeInTheDocument();
    expect(screen.getByTestId('levels-missing')).toHaveTextContent('加碼價、停損、目標價');
  });

  it('renders nothing when no level has a value', () => {
    const { container } = render(<ReportStrategy strategy={{}} action="buy" />);
    expect(container).toBeEmptyDOMElement();
  });
});
