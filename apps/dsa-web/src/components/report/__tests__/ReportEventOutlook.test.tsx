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
});
