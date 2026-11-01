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

  it('副標用 .label，不再轉大寫', () => {
    render(<Card subtitle="副標">內容</Card>);
    expect(screen.getByText('副標')).toHaveClass('label');
    expect(screen.getByText('副標')).not.toHaveClass('label-uppercase');
  });
});
