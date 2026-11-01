import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Metric, MetricGroup } from '../Metric';
import { PageHeader } from '../PageHeader';
import { StatCard } from '../StatCard';

describe('Metric', () => {
  it('沒有讀數顯示 —，不顯示傳進來的值', () => {
    render(<Metric label="總資產" value="123" unavailable />);
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText('123')).not.toBeInTheDocument();
  });

  it('unavailable 不整格淡化：值顯示 — 並用淡色，標籤照常', () => {
    render(<Metric label="總資產" value="123" unit="NT$" unavailable />);
    const card = screen.getByText('總資產').closest('[data-metric-state]');
    expect(card).toHaveAttribute('data-metric-state', 'unavailable');
    expect(card).not.toHaveClass('opacity-60');
    expect(screen.getByText('—')).toHaveClass('text-muted-text');
    expect(screen.getByText('總資產')).toHaveClass('text-secondary-text');
    expect(screen.queryByText('NT$')).not.toBeInTheDocument();
  });

  it('數字不斷行：不用 overflow-wrap、改 whitespace-nowrap', () => {
    render(<Metric label="市值" value="12,345,678" />);
    const value = screen.getByText('12,345,678');
    expect(value.className).not.toContain('overflow-wrap');
    expect(value).toHaveClass('whitespace-nowrap', 'tabular-nums');
  });

  it('unit 渲染在值之前', () => {
    render(<Metric label="市值" value="12,345" unit="NT$" />);
    const unit = screen.getByText('NT$');
    const value = unit.parentElement as HTMLElement;
    expect(value).toHaveTextContent('NT$12,345');
    expect(value.firstChild).toBe(unit);
    expect(unit).toHaveClass('mr-1', 'text-xs', 'text-secondary-text');
  });

  it('value 是 0 仍是真實讀數', () => {
    render(<Metric label="今日損益" value={0} />);
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  it('hero 佔兩欄並放大字級', () => {
    render(<Metric label="總資產" value="123" hero />);
    expect(screen.getByText('123')).toHaveClass('type-display');
    expect(screen.getByText('總資產').closest('[data-metric-state]')).toHaveClass('col-span-2');
  });

  it('StatCard 轉接 Metric', () => {
    render(<StatCard label="報酬" value="5%" hint="較上月" tone="primary" />);
    expect(screen.getByText('報酬').closest('[data-metric-state]')).toHaveClass('border-cyan/18');
    expect(screen.getByText('較上月')).toBeInTheDocument();
  });
});

const metrics = (count: number) =>
  Array.from({ length: count }, (_, index) => <Metric key={index} label={`指標${index}`} value={index} />);

describe('MetricGroup', () => {
  it.each([
    [4, ['grid-cols-2', 'md:grid-cols-4']],
    [5, ['grid-cols-2', 'md:grid-cols-4', 'xl:grid-cols-5']],
    [6, ['grid-cols-2', 'md:grid-cols-4', 'xl:grid-cols-6']],
  ] as const)('%s 欄：手機 2 欄、桌機依設定', (columns, classes) => {
    render(<MetricGroup columns={columns}>{metrics(columns)}</MetricGroup>);
    expect(screen.getByTestId('metric-group')).toHaveClass(...classes);
  });

  it('子元素比欄數少時收斂欄數，不留空格', () => {
    render(<MetricGroup columns={6}>{metrics(3)}{null}{false}</MetricGroup>);
    const group = screen.getByTestId('metric-group');
    expect(group).toHaveClass('md:grid-cols-3');
    expect(group).not.toHaveClass('xl:grid-cols-6');
  });

  it('hero 算兩格；奇數格時手機最後一張補滿整列', () => {
    render(
      <MetricGroup columns={4}>
        <Metric label="總資產" value="1" hero />
        {metrics(3)}
      </MetricGroup>,
    );
    const group = screen.getByTestId('metric-group');
    expect(group).toHaveClass('md:grid-cols-4');
    expect(group).toHaveClass('max-md:[&>*:last-child]:col-span-2');
  });

  it('只有一張時手機也是單欄', () => {
    render(<MetricGroup>{metrics(1)}</MetricGroup>);
    expect(screen.getByTestId('metric-group')).toHaveClass('grid-cols-1', 'md:grid-cols-1');
  });
});

describe('PageHeader', () => {
  it('無外框，只有標題、說明與動作', () => {
    render(<PageHeader title="資產" description="說明" actions={<button>新增</button>} />);
    const header = screen.getByRole('banner');
    expect(header).not.toHaveClass('glass-panel-lg');
    expect(screen.getByRole('heading', { level: 1, name: '資產' })).toBeInTheDocument();
    expect(screen.getByText('說明')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '新增' })).toBeInTheDocument();
  });
});
