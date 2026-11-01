import { render as rtlRender, screen } from '@testing-library/react';
import type React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { ReportStrategy } from '../ReportStrategy';

// The alert bell is a router Link, so every render needs a router.
const render = (ui: React.ReactElement) => rtlRender(<MemoryRouter>{ui}</MemoryRouter>);

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

  it('sizes the grid to the number of cards instead of always four columns', () => {
    const { unmount } = render(
      <ReportStrategy strategy={{ sniperPricesSource: 'structured', sniperPrices: { stopLoss: 80 }, stopLoss: '80' }} action="hold" language="zh-TW" />,
    );
    const single = screen.getByTestId('levels-grid');
    expect(single.className).not.toContain('xl:grid-cols-3');
    expect(single.className).not.toContain('xl:grid-cols-4');
    expect(single.className).not.toContain('xl:grid-cols-2');
    unmount();

    render(<ReportStrategy strategy={structured} action="buy" currentPrice={100} language="zh-TW" />);
    expect(screen.getByTestId('levels-grid').className).toContain('xl:grid-cols-4');
  });

  it('links a structured stop loss to a prefilled below-price alert', () => {
    render(<ReportStrategy strategy={structured} action="hold" currentPrice={100} stockCode="2330.TW" language="zh-TW" />);

    const bell = screen.getByTestId('level-alert-stopLoss');
    const href = bell.getAttribute('href') ?? '';
    expect(href).toContain('/alerts?new=1&target=2330.TW&type=price_cross');
    expect(href).toContain('direction=below&price=80');
    expect(bell).toHaveAttribute('title', '設警報');
  });

  it('points target and entry alerts above or below the current price', () => {
    render(<ReportStrategy strategy={structured} action="buy" currentPrice={100} stockCode="2330.TW" language="zh-TW" />);

    expect(screen.getByTestId('level-alert-takeProfit').getAttribute('href')).toContain('direction=above&price=120');
    expect(screen.getByTestId('level-alert-idealBuy').getAttribute('href')).toContain('direction=below&price=95');
    // secondaryBuy gets no bell.
    expect(screen.queryByTestId('level-alert-secondaryBuy')).not.toBeInTheDocument();
  });

  it('shows no bell for legacy free-text levels', () => {
    render(<ReportStrategy strategy={legacy} action="reduce" currentPrice={42.55} stockCode="1257.TW" language="zh-TW" />);

    expect(screen.getByTestId('level-stopLoss')).toBeInTheDocument();
    expect(screen.queryByTestId('level-alert-stopLoss')).not.toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('keeps ladder labels on one line and anchors the edge points inward', () => {
    render(<ReportStrategy strategy={structured} action="reduce" currentPrice={100} language="zh-TW" />);

    const stop = screen.getByTestId('ladder-stop');
    const target = screen.getByTestId('ladder-target');
    expect(stop.className).toContain('whitespace-nowrap');
    expect(stop.className).toContain('translate-x-0');
    expect(stop.className).toContain('items-start');
    expect(target.className).toContain('-translate-x-full');
    expect(target.className).toContain('items-end');
    expect(screen.getByTestId('ladder-price').className).toContain('-translate-x-1/2');
    // Short names for phones.
    expect(stop).toHaveTextContent('風控');
    expect(target).toHaveTextContent('減碼');
  });
});
