import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import NotFoundPage from '../NotFoundPage';

const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => navigate };
});

describe('NotFoundPage', () => {
  it('uses translated copy, stays inside the shell height and returns home', () => {
    const { container } = render(<NotFoundPage />);

    expect(screen.getByRole('heading', { name: '页面未找到' })).toBeInTheDocument();
    expect(document.title).toBe('页面未找到 - DSA');
    expect(container.firstElementChild).not.toHaveClass('min-h-screen');

    fireEvent.click(screen.getByRole('button', { name: '返回首页' }));
    expect(navigate).toHaveBeenCalledWith('/');
  });
});
