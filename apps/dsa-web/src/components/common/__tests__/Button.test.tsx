import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Button, IconButton } from '../Button';
import { readIndexCss } from '../../../__tests__/readCssSource';

describe('Button', () => {
  it('renders children', () => {
    render(<Button>Click me</Button>);

    expect(screen.getByRole('button', { name: 'Click me' })).toBeInTheDocument();
  });

  it('uses button type by default and exposes the selected variant', () => {
    render(<Button variant="danger">Delete</Button>);

    const button = screen.getByRole('button', { name: 'Delete' });
    expect(button).toHaveAttribute('type', 'button');
    expect(button).toHaveAttribute('data-variant', 'danger');
    expect(button.className).toContain('bg-danger');
  });

  it('disables the button when loading and shows loading text', () => {
    render(<Button isLoading loadingText="Saving">Save</Button>);

    const button = screen.getByRole('button', { name: /saving/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByText('Saving')).toBeInTheDocument();
  });

  it.each(['primary', 'secondary', 'ghost', 'danger'] as const)('supports the %s variant', (variant) => {
    render(<Button variant={variant}>Quick Action</Button>);

    expect(screen.getByRole('button', { name: 'Quick Action' })).toHaveAttribute('data-variant', variant);
  });

  it.each([
    ['sm', 'h-8'],
    ['md', 'h-9'],
    ['lg', 'h-11'],
  ] as const)('尺寸 %s 是 %s', (size, height) => {
    render(<Button size={size}>按鈕</Button>);
    expect(screen.getByRole('button', { name: '按鈕' })).toHaveClass(height);
  });

  it('文字不換行，「新建帳戶」不會斷字', () => {
    render(<Button>新建帳戶</Button>);
    expect(screen.getByRole('button', { name: '新建帳戶' })).toHaveClass('whitespace-nowrap');
  });

  it('.btn-* 同樣不換行且與 md 同高', () => {
    const rule = /\.btn-primary,\s*\.btn-secondary \{[^}]*\}/.exec(readIndexCss())?.[0] ?? '';
    expect(rule).toContain('white-space: nowrap;');
    expect(rule).toContain('min-height: 36px;');
  });

  it('IconButton 要有無障礙名稱，且與 Button 同高', () => {
    render(<IconButton aria-label="關閉" size="sm" icon={<svg />} />);
    const button = screen.getByRole('button', { name: '關閉' });
    expect(button).toHaveClass('h-8', 'w-8');
    expect(button).toHaveAttribute('type', 'button');
  });
});
