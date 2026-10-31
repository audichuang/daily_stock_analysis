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

describe('MetricGroup', () => {
  it.each([
    [4, ['grid-cols-2', 'md:grid-cols-4']],
    [5, ['grid-cols-2', 'md:grid-cols-4', 'xl:grid-cols-5']],
    [6, ['grid-cols-2', 'md:grid-cols-4', 'xl:grid-cols-6']],
  ] as const)('%s 欄：手機 2 欄、桌機依設定', (columns, classes) => {
    render(<MetricGroup columns={columns}>內容</MetricGroup>);
    expect(screen.getByTestId('metric-group')).toHaveClass(...classes);
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
