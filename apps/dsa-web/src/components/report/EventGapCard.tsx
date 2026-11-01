import type React from 'react';
import type { ReportLanguage, ReportSummary } from '../../types/analysis';
import type { ResearchEventGap } from '../../types/researchArtifact';
import { formatPercent, formatPrice } from '../../utils/format';
import { marketToneClass } from '../../utils/marketTone';
import { normalizeReportLanguage } from '../../utils/reportLanguage';
import { Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';

const TEXT = {
  zh: {
    title: '重大波动事件', eventDate: '事件日', sameDay: '事件当日', sessionsAfter: '距事件 {n} 个交易日',
    change: '事件日涨跌', low: '事件日低点', postMin: '事件后最低收盘', latest: '最新收盘',
    lowBroken: '已跌破事件日低点', lowHeld: '尚未跌破事件日低点',
    noNews: '重大波动但没有新闻，不下买卖结论',
    changeMind: '什么时候改变看法', entry: '进场条件', exit: '出场或改判', watch: '观察条件', nextCheck: '下次检查',
  },
  en: {
    title: 'Major price move', eventDate: 'Event date', sameDay: 'Event day', sessionsAfter: '{n} sessions since the event',
    change: 'Event-day move', low: 'Event-day low', postMin: 'Lowest close since', latest: 'Latest close',
    lowBroken: 'Closed below the event-day low', lowHeld: 'Has not closed below the event-day low',
    noNews: 'Major price move without news evidence; no buy or sell conclusion.',
    changeMind: 'What would change this view', entry: 'Entry conditions', exit: 'Exit or re-rate', watch: 'Watch', nextCheck: 'Next check',
  },
  'zh-TW': {
    title: '重大波動事件', eventDate: '事件日', sameDay: '事件當日', sessionsAfter: '距事件 {n} 個交易日',
    change: '事件日幅度', low: '事件日低點', postMin: '事件後最低收盤', latest: '最新收盤',
    lowBroken: '已收在事件日低點下方', lowHeld: '仍守住事件日低點',
    noNews: '重大波動但沒有新聞，不下買賣結論',
    changeMind: '什麼時候改變看法', entry: '進場條件', exit: '出場或改判', watch: '觀察條件', nextCheck: '下次檢查',
  },
  ko: {
    title: '큰 주가 변동', eventDate: '이벤트일', sameDay: '이벤트 당일', sessionsAfter: '이벤트 후 {n}거래일',
    change: '이벤트일 등락', low: '이벤트일 저가', postMin: '이후 최저 종가', latest: '최근 종가',
    lowBroken: '이벤트일 저가 하회', lowHeld: '이벤트일 저가 유지',
    noNews: '큰 주가 변동에 대한 뉴스 근거가 없어 매수·매도 결론을 내리지 않습니다.',
    changeMind: '판단이 바뀌는 조건', entry: '진입 조건', exit: '청산 또는 재평가', watch: '관찰 조건', nextCheck: '다음 확인',
  },
} as const;

interface EventGapCardProps {
  eventGap?: ResearchEventGap | null;
  currency?: string | null;
  language?: ReportLanguage;
}

/** 條件式事件卡：triggered 才出現。無新聞護欄擋下時只留警告，不露任何價位。 */
export const EventGapCard: React.FC<EventGapCardProps> = ({ eventGap, currency, language = 'zh' }) => {
  if (eventGap?.triggered !== true) {
    return null;
  }
  const text = TEXT[normalizeReportLanguage(language)];

  if (eventGap.blockedWithoutNews === true) {
    return (
      <div
        role="alert"
        data-testid="event-gap-blocked"
        className="rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 text-left text-sm leading-6 text-foreground"
      >
        <span className="font-semibold">{text.title}</span>
        {eventGap.eventDate ? <span className="ml-2 text-xs text-secondary-text">{eventGap.eventDate}</span> : null}
        <p>{eventGap.reason?.trim() || text.noNews}</p>
      </div>
    );
  }

  const code = currency ?? undefined;
  const sessions = eventGap.sessionsSinceEvent;
  const sessionText = sessions === 0
    ? text.sameDay
    : typeof sessions === 'number'
      ? text.sessionsAfter.replace('{n}', String(sessions))
      : null;
  const prices: Array<[string, number | null | undefined]> = [
    [text.low, eventGap.eventLow],
    [text.postMin, eventGap.postEventMinClose],
    [text.latest, eventGap.latestClose],
  ];

  return (
    <Card variant="surface" padding="md" className="home-panel-card text-left">
      <section data-testid="event-gap-card">
        <DashboardPanelHeader
          title={text.title}
          className="mb-2"
          actions={sessionText ? <span className="text-xs text-secondary-text">{sessionText}</span> : undefined}
        />
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm md:grid-cols-5">
          {eventGap.eventDate ? (
            <div>
              <dt className="text-xs text-muted-text">{text.eventDate}</dt>
              <dd className="font-medium tabular-nums text-foreground">{eventGap.eventDate}</dd>
            </div>
          ) : null}
          {typeof eventGap.changePct === 'number' ? (
            <div>
              <dt className="text-xs text-muted-text">{text.change}</dt>
              <dd className={`font-medium tabular-nums ${marketToneClass(eventGap.changePct)}`}>{formatPercent(eventGap.changePct)}</dd>
            </div>
          ) : null}
          {prices.map(([label, value]) => (typeof value === 'number' ? (
            <div key={label}>
              <dt className="text-xs text-muted-text">{label}</dt>
              <dd className="font-medium tabular-nums text-foreground">{formatPrice(value, code)}</dd>
            </div>
          ) : null))}
        </dl>
        {typeof eventGap.eventLowBroken === 'boolean' ? (
          <p className={`mt-2 text-xs ${eventGap.eventLowBroken ? 'text-warning' : 'text-secondary-text'}`}>
            {eventGap.eventLowBroken ? text.lowBroken : text.lowHeld}
          </p>
        ) : null}
      </section>
    </Card>
  );
};

interface ReportChangeConditionsProps {
  summary: ReportSummary;
  language?: ReportLanguage;
}

/** 「什麼時候改變看法」三組條件與下次檢查；舊報告全空就不顯示。 */
export const ReportChangeConditions: React.FC<ReportChangeConditionsProps> = ({ summary, language = 'zh' }) => {
  const text = TEXT[normalizeReportLanguage(language)];
  const groups: Array<[string, string[]]> = (
    [
      [text.entry, summary.entryConditions ?? []],
      [text.exit, summary.exitTriggers ?? []],
      [text.watch, summary.phaseWatchConditions ?? []],
    ] as Array<[string, string[]]>
  ).filter(([, items]) => items.length > 0);
  const nextCheck = summary.nextCheckTime?.trim() || null;

  if (groups.length === 0 && !nextCheck) {
    return null;
  }

  return (
    <Card variant="surface" padding="md" className="home-panel-card text-left">
      <section data-testid="report-change-conditions">
        <DashboardPanelHeader title={text.changeMind} className="mb-2" />
        {groups.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {groups.map(([title, items]) => (
              <div key={title} className="min-w-0">
                <h4 className="text-xs font-medium text-muted-text">{title}</h4>
                <ul className="mt-1 list-disc space-y-1 pl-4 text-sm leading-6 text-foreground">
                  {items.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </div>
            ))}
          </div>
        ) : null}
        {nextCheck ? (
          <p className="mt-2 text-xs text-secondary-text">{text.nextCheck}：{nextCheck}</p>
        ) : null}
      </section>
    </Card>
  );
};
