import type { WatchlistGroup } from '../../api/systemConfig';

/** 與 iOS 的 WatchlistGroupFilter 同語意；字串形式是為了放進 <select>。 */
export type WatchlistGroupFilter = 'all' | 'ungrouped' | `group:${string}`;

export const WATCHLIST_GROUP_NAME_MAX = 32;
export const WATCHLIST_GROUPS_MAX = 30;

export const groupFilterValue = (name: string): WatchlistGroupFilter => `group:${name}`;

const groupNameOf = (filter: WatchlistGroupFilter): string | null =>
  filter.startsWith('group:') ? filter.slice('group:'.length) : null;

/** 選中的分組已不存在、或根本沒有分組時退回全部。 */
export function resolveGroupFilter(filter: WatchlistGroupFilter, groups: WatchlistGroup[]): WatchlistGroupFilter {
  if (groups.length === 0) return 'all';
  const name = groupNameOf(filter);
  if (name !== null && !groups.some((group) => group.name === name)) return 'all';
  return filter;
}

/**
 * 依分組篩選清單列。全部與未分組維持傳入順序；單組照組內順序。
 * 成員以傳入的列（STOCK_LIST）為準，分組裡多出來的代號不會變出列。
 */
export function filterRowsByGroup<T>(
  rows: T[],
  getCode: (row: T) => string,
  filter: WatchlistGroupFilter,
  groups: WatchlistGroup[],
): T[] {
  const active = resolveGroupFilter(filter, groups);
  if (active === 'all') return rows;
  if (active === 'ungrouped') {
    const grouped = new Set(groups.flatMap((group) => group.codes));
    return rows.filter((row) => !grouped.has(getCode(row)));
  }
  const name = groupNameOf(active);
  const codes = groups.find((group) => group.name === name)?.codes ?? [];
  const rowByCode = new Map(rows.map((row) => [getCode(row), row]));
  return codes.flatMap((code) => {
    const row = rowByCode.get(code);
    return row === undefined ? [] : [row];
  });
}

/** 可新增才回傳整理後的組名，否則 null。 */
export function normalizeNewGroupName(raw: string, groups: WatchlistGroup[]): string | null {
  const name = raw.trim();
  if (!name || name.length > WATCHLIST_GROUP_NAME_MAX) return null;
  if (groups.length >= WATCHLIST_GROUPS_MAX) return null;
  if (groups.some((group) => group.name === name)) return null;
  return name;
}

/** 一檔只屬於一組：先從所有組拿掉，target 為 null 就是回到未分組。 */
export function assignCodeToGroup(groups: WatchlistGroup[], code: string, target: string | null): WatchlistGroup[] {
  return groups.map((group) => {
    const codes = group.codes.filter((item) => item !== code);
    return { name: group.name, codes: group.name === target ? [...codes, code] : codes };
  });
}

/** 在組內上移（-1）或下移（1）；到頭就不動。 */
export function moveCodeWithinGroup(
  groups: WatchlistGroup[],
  groupName: string,
  code: string,
  delta: -1 | 1,
): WatchlistGroup[] {
  return groups.map((group) => {
    if (group.name !== groupName) return group;
    const index = group.codes.indexOf(code);
    const nextIndex = index + delta;
    if (index < 0 || nextIndex < 0 || nextIndex >= group.codes.length) return group;
    const codes = [...group.codes];
    [codes[index], codes[nextIndex]] = [codes[nextIndex], codes[index]];
    return { name: group.name, codes };
  });
}
