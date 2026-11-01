import type React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { PageHeader } from '../PageHeader';

const viewport = { narrow: false };
const originalMatchMedia = window.matchMedia;

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      // Only the "below md" query is width-dependent; everything else stays false.
      matches: viewport.narrow && query.includes('max-width: 767'),
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

afterAll(() => {
  Object.defineProperty(window, 'matchMedia', { writable: true, value: originalMatchMedia });
});

const renderAt = (entry: string, props: Partial<React.ComponentProps<typeof PageHeader>> = {}) =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <PageHeader title="Alerts" description="Rules and history" actions={<button type="button">New</button>} {...props} />
    </MemoryRouter>
  );

describe('PageHeader', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    viewport.narrow = false;
  });

  it('keeps a visible h1 on desktop width outside embed mode', () => {
    renderAt('/alerts');
    const heading = screen.getByRole('heading', { level: 1, name: 'Alerts' });
    expect(heading).not.toHaveClass('sr-only');
    expect(screen.getByText('Rules and history')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New' })).toBeInTheDocument();
  });

  it('hides the h1 visually (screen readers only) in iOS embed mode even at desktop width', () => {
    renderAt('/alerts?embed=ios');
    const heading = screen.getByRole('heading', { level: 1, name: 'Alerts' });
    expect(heading).toHaveClass('sr-only');
    expect(screen.getByText('Rules and history')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New' }).parentElement).toHaveClass('overflow-x-auto', 'justify-end');
  });

  it('hides the h1 visually below md', () => {
    viewport.narrow = true;
    renderAt('/alerts');
    expect(screen.getByRole('heading', { level: 1, name: 'Alerts' })).toHaveClass('sr-only');
  });

  it('renders only the screen-reader h1 when compact with no description or actions', () => {
    const { container } = renderAt('/alerts?embed=ios', { description: undefined, actions: undefined });
    expect(screen.getByRole('heading', { level: 1, name: 'Alerts' })).toHaveClass('sr-only');
    expect(container.querySelector('p')).toBeNull();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('works without a Router (pages are rendered bare in some tests)', () => {
    render(<PageHeader title="Funds" />);
    expect(screen.getByRole('heading', { level: 1, name: 'Funds' })).not.toHaveClass('sr-only');
  });
});
