import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Card } from '../Card';

const cardOf = (text: string) => screen.getByText(text).closest('[data-card-level]');

describe('Card', () => {
  it.each([
    ['surface', 'surface', 'card-surface'],
    ['inset', 'inset', 'card-inset'],
    ['highlight', 'highlight', 'terminal-card'],
  ] as const)('%s 對應 %s 層', (variant, level, className) => {
    render(<Card variant={variant}>內容</Card>);
    expect(cardOf('內容')).toHaveAttribute('data-card-level', level);
    expect(cardOf('內容')).toHaveClass(className);
  });

  it('漸層只留給 highlight', () => {
    render(<Card>一般</Card>);
    expect(cardOf('一般')).not.toHaveClass('terminal-card');
  });

  it.each([
    ['sm', 'p-3'],
    ['md', 'p-4'],
    ['lg', 'p-5'],
  ] as const)('padding %s 是 %s', (padding, className) => {
    render(<Card padding={padding}>內容</Card>);
    expect(cardOf('內容')).toHaveClass(className);
  });

  it('副標是次要小字，不轉大寫', () => {
    render(<Card subtitle="副標">內容</Card>);
    expect(screen.getByText('副標')).toHaveClass('text-xs', 'text-secondary-text');
    expect(screen.getByText('副標')).not.toHaveClass('label-uppercase');
  });

  it('標題在上、副標在下', () => {
    render(<Card title="標題" subtitle="副標">內容</Card>);
    const title = screen.getByRole('heading', { name: '標題' });
    const subtitle = screen.getByText('副標');
    // DOCUMENT_POSITION_FOLLOWING: subtitle comes after the title in document order.
    expect(title.compareDocumentPosition(subtitle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('meta 放在標題列右側', () => {
    render(<Card title="標題" meta={<span>10:30 更新</span>}>內容</Card>);
    const meta = screen.getByText('10:30 更新');
    const header = screen.getByRole('heading', { name: '標題' }).parentElement?.parentElement;
    expect(header).toHaveClass('justify-between');
    expect(header).toContainElement(meta);
  });
});
