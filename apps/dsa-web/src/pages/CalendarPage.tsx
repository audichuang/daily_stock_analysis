import { useEffect, useMemo, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, ExternalLink } from 'lucide-react';
import { calendarApi } from '../api/calendar';
import { AppPage, Badge, Button, Card, EmptyState, InlineAlert, Loading, PageHeader } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { CALENDAR_TEXT } from '../locales/calendar';
import type { CalendarEventsResponse } from '../types/calendar';
import { formatDateTime } from '../utils/format';

// 使用者所在地的今天：決定預設月份與「已過去」；事件日期本身不換算時區。
function localToday(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function currentMonth(): string {
  return localToday().slice(0, 7);
}

function monthRange(month: string): { from: string; to: string } {
  const [year, number] = month.split('-').map(Number);
  const lastDay = new Date(Date.UTC(year, number, 0)).getUTCDate();
  return { from: `${month}-01`, to: `${month}-${lastDay}` };
}

function adjacentMonth(month: string, offset: number): string {
  const [year, number] = month.split('-').map(Number);
  return new Date(Date.UTC(year, number - 1 + offset, 1)).toISOString().slice(0, 7);
}

export default function CalendarPage() {
  const { language, t } = useUiLanguage();
  const text = CALENDAR_TEXT[language];
  const [month, setMonth] = useState(currentMonth);
  const [showPast, setShowPast] = useState(false);
  const [result, setResult] = useState<{ key: string; response: CalendarEventsResponse | null; failed: boolean } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const requestKey = `${month}/${attempt}`;
  const loading = result?.key !== requestKey;
  const response = result?.key === requestKey ? result.response : null;
  const failed = result?.key === requestKey && result.failed;

  useEffect(() => {
    let active = true;
    const { from, to } = monthRange(month);
    calendarApi.getEvents(from, to).then((data) => {
      if (active) setResult({ key: requestKey, response: data, failed: false });
    }).catch(() => {
      if (active) setResult({ key: requestKey, response: null, failed: true });
    });
    return () => { active = false; };
  }, [month, requestKey]);

  const days = useMemo(() => {
    const grouped = new Map<string, CalendarEventsResponse['events']>();
    for (const event of response?.events ?? []) {
      const events = grouped.get(event.date) ?? [];
      events.push(event);
      grouped.set(event.date, events);
    }
    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [response]);
  const today = localToday();
  const pastCount = days.filter(([date]) => date < today).length;
  const visibleDays = showPast ? days : days.filter(([date]) => date >= today);

  return (
    <AppPage className="space-y-5">
      <PageHeader title={text.title} description={text.description} />
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Button variant="secondary" aria-label={text.previous} onClick={() => setMonth(adjacentMonth(month, -1))}><ChevronLeft className="h-4 w-4" /></Button>
            <label className="flex items-center gap-2 text-sm">
              <span className="sr-only">{text.month}</span>
              <input aria-label={text.month} type="month" value={month} onChange={(event) => { if (/^[0-9]{4}-[0-9]{2}$/.test(event.target.value)) setMonth(event.target.value); }} className="rounded-lg border border-border bg-background p-2 text-foreground" />
            </label>
            <Button variant="secondary" aria-label={text.next} onClick={() => setMonth(adjacentMonth(month, 1))}><ChevronRight className="h-4 w-4" /></Button>
          </div>
          <p className="text-xs text-secondary-text">{text.cache}: {response?.cacheUpdatedAt ? formatDateTime(response.cacheUpdatedAt) : text.notRefreshed}</p>
        </div>
        <p className="mt-3 text-sm text-secondary-text">{text.timezoneNote}</p>
        <p className="mt-1 text-xs text-muted-text">{text.deadlineNote}</p>
      </Card>

      {loading ? <Loading label={text.loading} /> : failed ? (
        <InlineAlert variant="danger" message={text.loadError} action={<Button variant="secondary" onClick={() => setAttempt((value) => value + 1)}>{t('common.retry')}</Button>} />
      ) : (
        <>
          {pastCount > 0 ? (
            <Button variant="secondary" onClick={() => setShowPast((value) => !value)}>
              {showPast ? text.hidePast : `${text.showPast} (${pastCount})`}
            </Button>
          ) : null}
          {visibleDays.length === 0 ? <EmptyState icon={<CalendarDays className="h-6 w-6" />} title={text.empty} description={text.emptyDescription} /> : visibleDays.map(([date, events]) => (
            <section key={date} aria-label={date} className="space-y-2">
              <h2 className="text-base font-semibold tabular-nums text-foreground"><time dateTime={date}>{date}</time></h2>
              {events.map((event) => (
                <Card key={event.id}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="font-semibold text-foreground">{event.name}{event.code ? <span className="ml-2 font-mono text-sm text-secondary-text">{event.code}</span> : null}</h3>
                      <p className="mt-1 text-xs text-secondary-text">{event.type === 'earnings' || event.type === 'investor_conference' || event.type === 'fomc' || event.type === 'revenue_deadline' || event.type === 'financial_deadline' ? text[event.type] : text.macro} · {event.timezone === 'America/New_York' ? text.eastern : text.taipei}</p>
                    </div>
                    <Badge variant={event.dateKind === 'statutory_deadline' || event.status === 'estimated' ? 'warning' : 'success'}>{event.dateKind === 'statutory_deadline' ? text.deadline : text[event.status]}</Badge>
                  </div>
                  {event.detail ? <p className="mt-3 whitespace-pre-line text-sm text-secondary-text">{event.detail}</p> : null}
                  {/^https?:\/\//.test(event.sourceUrl) ? <a href={event.sourceUrl} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex items-center gap-1 text-xs text-cyan">{text.source}<ExternalLink className="h-3 w-3" /></a> : null}
                </Card>
              ))}
            </section>
          ))}
          {response && response.undated.length > 0 ? (
            <Card>
              <details>
                <summary className="cursor-pointer font-semibold text-foreground">{text.undated} ({response.undated.length})</summary>
                <ul className="divide-y divide-border/50">
                {response.undated.map((item) => <li key={item.code} className="py-3"><span className="font-semibold text-foreground">{item.name} <span className="font-mono text-sm">{item.code}</span></span><p className="mt-1 text-sm text-secondary-text">{item.detail}</p></li>)}
              </ul>
              </details>
            </Card>
          ) : null}
        </>
      )}
    </AppPage>
  );
}
