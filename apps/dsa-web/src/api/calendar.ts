import apiClient from './index';
import { toCamelCase } from './utils';
import type { CalendarEventsResponse } from '../types/calendar';

export const calendarApi = {
  async getEvents(from: string, to: string): Promise<CalendarEventsResponse> {
    const response = await apiClient.get('/api/v1/calendar/events', { params: { from, to } });
    return toCamelCase<CalendarEventsResponse>(response.data);
  },
};
