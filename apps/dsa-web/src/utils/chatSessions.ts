import type { ChatSessionItem } from '../api/agent';

/** 上次活動不在今天（裝置時區）就不自動接回；沒有時間的舊資料照舊還原。 */
export const isFromEarlierDay = (value: string | null | undefined, now = new Date()): boolean => {
  if (!value) return false;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return false;
  return parsed.toDateString() !== now.toDateString();
};

export type SessionGroupId = 'today' | 'week' | 'earlier';

export interface SessionGroup {
  id: SessionGroupId;
  sessions: ChatSessionItem[];
}

const startOfDay = (date: Date): number => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();

/** 依上次活動分成今天、近七天、更早；沒有時間的放更早，空組不回傳。 */
export const groupSessionsByRecency = (sessions: ChatSessionItem[], now = new Date()): SessionGroup[] => {
  const today = startOfDay(now);
  const weekAgo = today - 6 * 24 * 60 * 60 * 1000;
  const groups: Record<SessionGroupId, ChatSessionItem[]> = { today: [], week: [], earlier: [] };
  for (const session of sessions) {
    const stamp = session.last_active ?? session.created_at;
    const parsed = stamp ? new Date(stamp) : null;
    const day = parsed && !Number.isNaN(parsed.getTime()) ? startOfDay(parsed) : null;
    if (day !== null && day >= today) groups.today.push(session);
    else if (day !== null && day >= weekAgo) groups.week.push(session);
    else groups.earlier.push(session);
  }
  return (['today', 'week', 'earlier'] as const)
    .filter((id) => groups[id].length > 0)
    .map((id) => ({ id, sessions: groups[id] }));
};

/** 歷史清單搜尋：比對標題、股票代號與名稱，不分大小寫。 */
export const filterSessions = (sessions: ChatSessionItem[], keyword: string): ChatSessionItem[] => {
  const needle = keyword.trim().toLowerCase();
  if (!needle) return sessions;
  return sessions.filter((session) =>
    [session.title, session.stock_code, session.stock_name]
      .some((field) => (field ?? '').toLowerCase().includes(needle)));
};
