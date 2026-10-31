export interface CalendarEvent {
  id: string;
  type: string;
  code: string | null;
  name: string;
  date: string;
  status: 'confirmed' | 'estimated';
  detail: string;
  sourceUrl: string;
  timezone: 'America/New_York' | 'Asia/Taipei';
  dateKind: 'release' | 'statutory_deadline';
  updatedAt: string | null;
}

export interface CalendarEventsResponse {
  events: CalendarEvent[];
  undated: Array<{ code: string; name: string; detail: string }>;
  cacheUpdatedAt: string | null;
}
