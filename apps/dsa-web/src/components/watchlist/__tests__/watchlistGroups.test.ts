import { describe, expect, it } from 'vitest';
import {
  assignCodeToGroup,
  filterRowsByGroup,
  groupFilterValue,
  moveCodeWithinGroup,
  normalizeNewGroupName,
  resolveGroupFilter,
  WATCHLIST_GROUPS_MAX,
} from '../watchlistGroups';

const groups = [
  { name: 'Tech', codes: ['2317.TW', '2330.TW'] },
  { name: 'Empty', codes: [] },
];
const rows = ['2330.TW', '2317.TW', 'AAPL'];
const code = (row: string) => row;

describe('watchlist groups', () => {
  it('keeps every row in the incoming order for all', () => {
    expect(filterRowsByGroup(rows, code, 'all', groups)).toEqual(rows);
  });

  it('uses the group order for a group and ignores codes without a row', () => {
    expect(filterRowsByGroup(rows, code, groupFilterValue('Tech'), groups)).toEqual(['2317.TW', '2330.TW']);
    expect(filterRowsByGroup(['2330.TW'], code, groupFilterValue('Tech'), groups)).toEqual(['2330.TW']);
  });

  it('returns rows outside every group for ungrouped', () => {
    expect(filterRowsByGroup(rows, code, 'ungrouped', groups)).toEqual(['AAPL']);
  });

  it('falls back to all when the selected group is gone or there are no groups', () => {
    expect(resolveGroupFilter(groupFilterValue('Gone'), groups)).toBe('all');
    expect(resolveGroupFilter(groupFilterValue('Tech'), groups)).toBe('group:Tech');
    expect(resolveGroupFilter('ungrouped', [])).toBe('all');
    expect(filterRowsByGroup(rows, code, groupFilterValue('Gone'), groups)).toEqual(rows);
  });

  it('rejects names the server would reject', () => {
    expect(normalizeNewGroupName('  ', groups)).toBeNull();
    expect(normalizeNewGroupName(' Tech ', groups)).toBeNull();
    expect(normalizeNewGroupName('x'.repeat(33), groups)).toBeNull();
    expect(normalizeNewGroupName('New', Array.from({ length: WATCHLIST_GROUPS_MAX }, (_, i) => ({ name: `g${i}`, codes: [] })))).toBeNull();
    expect(normalizeNewGroupName(' New ', groups)).toBe('New');
    expect(normalizeNewGroupName('x'.repeat(32), groups)).toBe('x'.repeat(32));
  });

  it('keeps single membership when moving and returns to ungrouped on null', () => {
    const moved = assignCodeToGroup(groups, '2330.TW', 'Empty');
    expect(moved[0].codes).toEqual(['2317.TW']);
    expect(moved[1].codes).toEqual(['2330.TW']);
    expect(assignCodeToGroup(moved, '2330.TW', null).flatMap((group) => group.codes)).toEqual(['2317.TW']);
  });

  it('moves within a group and stops at the ends', () => {
    expect(moveCodeWithinGroup(groups, 'Tech', '2330.TW', -1)[0].codes).toEqual(['2330.TW', '2317.TW']);
    expect(moveCodeWithinGroup(groups, 'Tech', '2330.TW', 1)[0].codes).toEqual(['2317.TW', '2330.TW']);
    expect(moveCodeWithinGroup(groups, 'Tech', '2317.TW', -1)[0].codes).toEqual(['2317.TW', '2330.TW']);
    expect(moveCodeWithinGroup(groups, 'Tech', 'AAPL', 1)[0].codes).toEqual(['2317.TW', '2330.TW']);
  });
});
