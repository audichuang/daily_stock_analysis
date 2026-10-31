import { describe, expect, it, vi } from 'vitest';
import { calendarApi } from '../calendar';
import apiClient from '../index';

vi.mock('../index', () => ({ default: { get: vi.fn() } }));

describe('calendarApi', () => {
  it('sends date bounds and maps the API snake_case contract', async () => {
    const from = new Date().toISOString().slice(0, 10);
    vi.mocked(apiClient.get).mockResolvedValue({ data: {
      events: [{ id: 'e', source_url: 'https://www.nasdaq.com', date_kind: 'release', updated_at: null }],
      undated: [{ code: 'GOOGL', name: 'Alphabet', detail: '未定' }],
      cache_updated_at: null,
    } });
    const result = await calendarApi.getEvents(from, from);
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/calendar/events', { params: { from, to: from } });
    expect(result.events[0]).toMatchObject({ sourceUrl: 'https://www.nasdaq.com', dateKind: 'release', updatedAt: null });
    expect(result.cacheUpdatedAt).toBeNull();
  });
});
