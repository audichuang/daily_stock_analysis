import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { EventGapCard, ReportChangeConditions } from '../EventGapCard';

const summary = {
  analysisSummary: '',
  operationAdvice: '',
  trendPrediction: '',
  sentimentScore: 50,
};

describe('EventGapCard', () => {
  it('stays hidden unless triggered', () => {
    const { container } = render(<EventGapCard eventGap={{ triggered: false, eventLow: 90 }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('says event day instead of zero sessions', () => {
    render(<EventGapCard eventGap={{ triggered: true, sessionsSinceEvent: 0, changePct: -15, eventLow: 90 }} language="zh-TW" />);

    expect(screen.getByText('事件當日')).toBeInTheDocument();
    expect(screen.queryByText(/0 個交易日/)).not.toBeInTheDocument();
  });

  it('counts sessions after the event', () => {
    render(<EventGapCard eventGap={{ triggered: true, sessionsSinceEvent: 2 }} language="zh-TW" />);
    expect(screen.getByText('距事件 2 個交易日')).toBeInTheDocument();
  });

  it('turns into a warning and hides prices when blocked without news', () => {
    render(
      <EventGapCard
        eventGap={{
          triggered: true,
          blockedWithoutNews: true,
          reason: '重大波動但沒有新聞，不下買賣結論',
          eventLow: 90,
          latestClose: 95,
          postEventMinClose: 91,
        }}
        language="zh-TW"
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('不下買賣結論');
    expect(screen.queryByTestId('event-gap-card')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).not.toHaveTextContent('90');
    expect(screen.getByRole('alert')).not.toHaveTextContent('95');
  });
});

describe('ReportChangeConditions', () => {
  it('renders the three groups and the next check', () => {
    render(
      <ReportChangeConditions
        summary={{ ...summary, entryConditions: ['站回月線'], exitTriggers: ['跌破季線'], phaseWatchConditions: ['量縮'], nextCheckTime: '明日收盤' }}
        language="zh-TW"
      />,
    );

    expect(screen.getByText('什麼時候改變看法')).toBeInTheDocument();
    expect(screen.getByText('站回月線')).toBeInTheDocument();
    expect(screen.getByText('跌破季線')).toBeInTheDocument();
    expect(screen.getByText('量縮')).toBeInTheDocument();
    expect(screen.getByText(/明日收盤/)).toBeInTheDocument();
  });

  it('hides when an old report has no conditions', () => {
    const { container } = render(<ReportChangeConditions summary={{ ...summary, entryConditions: null, exitTriggers: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
