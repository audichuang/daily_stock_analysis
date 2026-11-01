import { describe, expect, it } from 'vitest';
import type { DecisionSignalItem } from '../../types/decisionSignals';
import { distancePct, hasActionChange, signalRemaining, sourceReportHref } from '../decisionSignalRow';

const NOW = Date.now();
const HOUR = 3600_000;

describe('distancePct', () => {
  it('measures a level against the current price', () => {
    expect(distancePct(900, 1000)).toBeCloseTo(-10);
    expect(distancePct(1100, 1000)).toBeCloseTo(10);
  });

  it('has no reading without a level or a usable price', () => {
    expect(distancePct(null, 1000)).toBeNull();
    expect(distancePct(900, null)).toBeNull();
    expect(distancePct(900, 0)).toBeNull();
  });
});

describe('signalRemaining', () => {
  it('counts hours under a day and rounds up', () => {
    expect(signalRemaining(new Date(NOW + 1.5 * HOUR).toISOString(), NOW)).toEqual({ kind: 'hours', count: 2 });
  });

  it('counts whole days from a day onwards', () => {
    expect(signalRemaining(new Date(NOW + 72 * HOUR).toISOString(), NOW)).toEqual({ kind: 'days', count: 3 });
  });

  it('marks a past expiry as expired and a missing one as no reading', () => {
    expect(signalRemaining(new Date(NOW - HOUR).toISOString(), NOW)).toEqual({ kind: 'expired' });
    expect(signalRemaining(null, NOW)).toBeNull();
  });
});

describe('hasActionChange', () => {
  const item = (action: DecisionSignalItem['action'], previousAction?: DecisionSignalItem['action'] | null) => (
    { action, previousAction } as DecisionSignalItem
  );

  it('is true only when the previous action differs', () => {
    expect(hasActionChange(item('reduce', 'buy'))).toBe(true);
    expect(hasActionChange(item('hold', 'hold'))).toBe(false);
    expect(hasActionChange(item('hold', null))).toBe(false);
  });
});

describe('sourceReportHref', () => {
  it('links to the home report deep link', () => {
    expect(sourceReportHref(42)).toBe('/?report=42');
  });
});
