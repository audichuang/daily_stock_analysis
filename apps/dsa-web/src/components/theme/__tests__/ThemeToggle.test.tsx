import { fireEvent, render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { ThemeProvider } from '../ThemeProvider';
import { ThemeToggle } from '../ThemeToggle';

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: query === '(prefers-color-scheme: dark)',
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

describe('ThemeToggle', () => {
  it('opens the theme menu and shows all theme modes', async () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: '切换主题' }));

    expect(await screen.findByRole('menu', { name: '主题模式' })).toBeInTheDocument();
    expect(screen.getByRole('menuitemradio', { name: '浅色' })).toBeInTheDocument();
    expect(screen.getByRole('menuitemradio', { name: '深色' })).toBeInTheDocument();
    expect(screen.getByRole('menuitemradio', { name: '跟随系统' })).toBeInTheDocument();
  });

  it('nav variant uses labelClassName instead of the hard-coded label size', () => {
    render(
      <ThemeProvider>
        <ThemeToggle variant="nav" labelClassName="truncate" />
      </ThemeProvider>
    );

    const label = screen.getByRole('button', { name: '切换主题' }).querySelector('span');
    expect(label).not.toBeNull();
    expect(label).toHaveClass('truncate');
    expect(label?.className).not.toContain('text-[1.02rem]');
  });

  it('nav variant keeps the default label size when labelClassName is omitted', () => {
    render(
      <ThemeProvider>
        <ThemeToggle variant="nav" />
      </ThemeProvider>
    );

    const label = screen.getByRole('button', { name: '切换主题' }).querySelector('span');
    expect(label?.className).toContain('text-[1.02rem]');
  });
});
