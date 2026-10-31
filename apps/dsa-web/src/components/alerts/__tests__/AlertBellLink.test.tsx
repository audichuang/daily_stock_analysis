import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AlertBellLink } from '../AlertBellLink';

describe('AlertBellLink', () => {
  it('links to the create drawer with the code preserved', () => {
    render(<AlertBellLink code="00631L.TW" />);
    expect(screen.getByRole('link')).toHaveAttribute('href', '/alerts?new=1&target=00631L.TW');
  });
});
