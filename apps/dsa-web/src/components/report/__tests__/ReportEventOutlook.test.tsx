import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ReportEventOutlook } from '../ReportEventOutlook';

describe('ReportEventOutlook', () => {
  it('renders nothing without an outlook', () => {
    const { container } = render(<ReportEventOutlook outlook={null} language="en" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the call, consensus and what to do per scenario', () => {
    render(
      <ReportEventOutlook
        language="en"
        outlook={{
          event: 'Q3 earnings',
          eventDate: '2030-11-18',
          expectation: 'beat',
          confidence: 'medium',
          reasoning: 'Four straight beats',
          consensus: { eps: 2.47, revenue: 109000000000, analysts: 44, epsCurrency: 'USD', revenueCurrency: 'TWD' },
          scenarios: [{ case: 'miss', expectedReaction: 'Falls', actionIfHolding: 'Trim', actionIfFlat: 'Wait' }],
        }}
      />,
    );
    expect(screen.getByText('Expect a beat')).toBeInTheDocument();
    expect(screen.getByText('Four straight beats')).toBeInTheDocument();
    expect(screen.getByText('If it misses')).toBeInTheDocument();
    expect(screen.getByText(/EPS estimate 2\.47 USD/)).toHaveTextContent('109.0B TWD');
    expect(screen.getByText('Trim')).toBeInTheDocument();
  });

  it('says data is missing rather than showing numbers', () => {
    render(<ReportEventOutlook language="en" outlook={{ event: 'Conference', expectation: 'insufficient_data' }} />);
    expect(screen.getByText('Not enough data to call')).toBeInTheDocument();
    expect(screen.getByText('No reliable analyst estimates available')).toBeInTheDocument();
  });

  it('does not repeat the date when the event already names it or the date is missing', () => {
    const { unmount } = render(
      <ReportEventOutlook language="zh-TW" outlook={{ event: '下次財報（日期未定）', eventDate: null, expectation: 'insufficient_data' }} />,
    );
    expect(screen.getByText('下次財報（日期未定）')).toBeInTheDocument();
    expect(screen.queryByText(/日期未定 · |· 日期未定/)).not.toBeInTheDocument();
    unmount();

    const { unmount: unmountSecond } = render(
      <ReportEventOutlook language="zh-TW" outlook={{ event: '2030-11-18 法說會', eventDate: '2030-11-18', expectation: 'beat' }} />,
    );
    expect(screen.getByText('2030-11-18 法說會')).toBeInTheDocument();
    unmountSecond();

    render(<ReportEventOutlook language="zh-TW" outlook={{ event: '法說會', eventDate: '2030-11-18', expectation: 'beat' }} />);
    expect(screen.getByText('法說會 · 2030-11-18')).toBeInTheDocument();
  });

  it('folds the scenarios into a closed details when data is insufficient', () => {
    render(
      <ReportEventOutlook
        language="zh-TW"
        outlook={{
          event: '下次財報（日期未定）',
          expectation: 'insufficient_data',
          confidence: 'low',
          scenarios: [{ case: 'miss', expectedReaction: '再探低', actionIfHolding: '減碼', actionIfFlat: '不進場' }],
        }}
      />,
    );
    const more = screen.getByTestId('event-outlook-more');
    expect(more.tagName).toBe('DETAILS');
    expect(more).not.toHaveAttribute('open');
    expect(more).toHaveTextContent('仍想看三種情況');
    expect(more).toContainElement(screen.getByTestId('event-outlook-scenarios'));
    expect(screen.getByTestId('event-outlook-call')).toHaveTextContent('信心：低');
  });

  it('keeps scenarios open when there is a call', () => {
    render(
      <ReportEventOutlook
        language="en"
        outlook={{ event: 'Q3 earnings', expectation: 'beat', confidence: 'high', scenarios: [{ case: 'beat', expectedReaction: 'Rallies' }] }}
      />,
    );
    expect(screen.queryByTestId('event-outlook-more')).not.toBeInTheDocument();
    expect(screen.getByTestId('event-outlook-scenarios')).toBeInTheDocument();
    expect(screen.getByTestId('event-outlook-call')).toHaveTextContent('Confidence: High');
  });
});
