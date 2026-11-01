import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ActionMenu } from '../ActionMenu';

describe('ActionMenu', () => {
  it('keeps items hidden until opened and closes after selecting', () => {
    const onSelect = vi.fn();
    render(<ActionMenu label="More" items={[{ key: 'a', label: 'Item A', onSelect }]} />);

    expect(screen.queryByRole('menuitem', { name: 'Item A' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'More' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Item A' }));

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('closes on Escape and outside clicks', () => {
    render(<ActionMenu label="More" items={[{ key: 'a', label: 'Item A', onSelect: vi.fn() }]} />);

    fireEvent.click(screen.getByRole('button', { name: 'More' }));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'More' }));
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
});
