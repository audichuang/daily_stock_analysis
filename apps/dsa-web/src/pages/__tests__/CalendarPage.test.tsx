import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import CalendarPage from '../CalendarPage';

const { getEvents } = vi.hoisted(() => ({ getEvents: vi.fn() }));
vi.mock('../../api/calendar', () => ({ calendarApi: { getEvents } }));

const month = (() => {
  const parts = new Intl.DateTimeFormat('en', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit' }).formatToParts(new Date());
  return `${parts.find((part) => part.type === 'year')!.value}-${parts.find((part) => part.type === 'month')!.value}`;
})();
const date = `${month}-05`;
const response = {
  events: [
    { id: 'confirmed', type: 'earnings', code: 'BRK.B', name: 'Berkshire Hathaway', date, status: 'confirmed', detail: 'Before market open · EPS 7.5', sourceUrl: 'https://www.nasdaq.com/market-activity/stocks/brk.b/earnings', timezone: 'America/New_York', dateKind: 'release', updatedAt: null },
    { id: 'estimated', type: 'earnings', code: 'AAPL', name: 'Apple', date, status: 'estimated', detail: '', sourceUrl: 'https://finance.yahoo.com/quote/AAPL', timezone: 'America/New_York', dateKind: 'release', updatedAt: null },
    { id: 'deadline', type: 'financial_deadline', code: '2330.TW', name: '台積電', date, status: 'confirmed', detail: '', sourceUrl: 'https://www.twse.com.tw', timezone: 'Asia/Taipei', dateKind: 'statutory_deadline', updatedAt: null },
  ],
  undated: [{ code: 'GOOGL', name: 'Alphabet', detail: 'Not announced' }],
  cacheUpdatedAt: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.setItem('dsa.uiLanguage', 'en');
  getEvents.mockResolvedValue(response);
});

function renderPage() { return render(<UiLanguageProvider><CalendarPage /></UiLanguageProvider>); }

describe('CalendarPage', () => {
  it('groups dates without converting ET, distinguishes estimates and deadlines, and keeps undated companies separate', async () => {
    renderPage();
    expect(await screen.findByText('Berkshire Hathaway')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: date })).toBeInTheDocument();
    expect(screen.getByText('BRK.B')).toBeInTheDocument();
    expect(screen.getByText('Confirmed')).toBeInTheDocument();
    expect(screen.getByText('Estimated')).toBeInTheDocument();
    expect(screen.getByText('Statutory deadline')).toBeInTheDocument();
    expect(screen.getAllByText(/US Eastern date/)).toHaveLength(2);
    expect(screen.getByRole('heading', { name: 'Next earnings date undetermined' })).toBeInTheDocument();
    expect(screen.getByText('Not announced')).toBeInTheDocument();
    expect(getEvents).toHaveBeenCalledWith(`${month}-01`, expect.stringMatching(new RegExp(`^${month}-[0-9]{2}$`)));
    expect(screen.getAllByRole('link', { name: 'Source' })[0]).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('loads the next month from the month control', async () => {
    renderPage();
    await screen.findByText('Berkshire Hathaway');
    fireEvent.click(screen.getByRole('button', { name: 'Next month' }));
    const [year, number] = month.split('-').map(Number);
    const nextMonth = new Date(Date.UTC(year, number, 1)).toISOString().slice(0, 7);
    await waitFor(() => expect(getEvents).toHaveBeenLastCalledWith(`${nextMonth}-01`, expect.any(String)));
  });

  it('shows the cached empty state and does not invent a date', async () => {
    getEvents.mockResolvedValue({ ...response, events: [] });
    renderPage();
    expect(await screen.findByText('No cached events this month')).toBeInTheDocument();
    expect(screen.getByText('GOOGL')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: date })).not.toBeInTheDocument();
  });

  it('retries a failed cache request', async () => {
    getEvents.mockRejectedValueOnce(new Error('offline'));
    renderPage();
    expect(await screen.findByText('The calendar could not be loaded.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Berkshire Hathaway')).toBeInTheDocument();
    expect(getEvents).toHaveBeenCalledTimes(2);
  });

  it('renders Traditional Chinese calendar wording', async () => {
    localStorage.setItem('dsa.uiLanguage', 'zh-TW');
    renderPage();
    expect(await screen.findByText('Berkshire Hathaway')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '事件行事曆' })).toBeInTheDocument();
    expect(screen.getByText('推估')).toBeInTheDocument();
    expect(screen.getByText('法定期限')).toBeInTheDocument();
  });

  it('shows additional economic-release types using the event name', async () => {
    getEvents.mockResolvedValue({ ...response, events: [{ ...response.events[0], type: 'cpi', code: null, name: 'US CPI' }] });
    renderPage();
    expect(await screen.findByRole('heading', { name: 'US CPI' })).toBeInTheDocument();
    expect(screen.getByText('Economic release · US Eastern date (ET)')).toBeInTheDocument();
  });
});
