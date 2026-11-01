import { describe, expect, it } from 'vitest';
import type { ChatSessionItem } from '../../api/agent';
import { filterSessions, groupSessionsByRecency, isFromEarlierDay } from '../chatSessions';

const DAY_MS = 24 * 60 * 60 * 1000;

const session = (id: string, lastActive: string | null, extra: Partial<ChatSessionItem> = {}): ChatSessionItem => ({
  session_id: id, title: id, message_count: 1, created_at: null, last_active: lastActive, ...extra,
});

describe('isFromEarlierDay', () => {
  it('flags an earlier day but not today', () => {
    const now = new Date();
    expect(isFromEarlierDay(new Date(now.getTime() - 2 * DAY_MS).toISOString(), now)).toBe(true);
    expect(isFromEarlierDay(now.toISOString(), now)).toBe(false);
  });

  it('fails open for missing or unreadable times', () => {
    expect(isFromEarlierDay(null)).toBe(false);
    expect(isFromEarlierDay(undefined)).toBe(false);
    expect(isFromEarlierDay('not-a-date')).toBe(false);
  });
});

describe('groupSessionsByRecency', () => {
  it('splits today, the last seven days and earlier, dropping empty groups', () => {
    const now = new Date();
    const groups = groupSessionsByRecency([
      session('a', now.toISOString()),
      session('b', new Date(now.getTime() - 3 * DAY_MS).toISOString()),
      session('c', new Date(now.getTime() - 30 * DAY_MS).toISOString()),
      session('d', null),
    ], now);
    expect(groups.map((g) => [g.id, g.sessions.map((s) => s.session_id)])).toEqual([
      ['today', ['a']], ['week', ['b']], ['earlier', ['c', 'd']],
    ]);
    expect(groupSessionsByRecency([session('a', now.toISOString())], now).map((g) => g.id)).toEqual(['today']);
  });
});

describe('filterSessions', () => {
  const sessions = [session('台積電走勢', null, { stock_code: '2330.TW', stock_name: '台積電' }), session('大盤', null)];

  it('matches title, code and name case-insensitively', () => {
    expect(filterSessions(sessions, '2330.tw').map((s) => s.title)).toEqual(['台積電走勢']);
    expect(filterSessions(sessions, '大盤').map((s) => s.title)).toEqual(['大盤']);
  });

  it('returns everything for a blank keyword', () => {
    expect(filterSessions(sessions, '  ')).toEqual(sessions);
  });
});
