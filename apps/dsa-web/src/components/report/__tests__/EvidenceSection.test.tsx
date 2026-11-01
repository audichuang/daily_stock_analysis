import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ResearchEvidenceItem } from '../../../types/researchArtifact';
import { EvidenceSection } from '../EvidenceSection';

const item = (overrides: Partial<ResearchEvidenceItem> & { id: string }): ResearchEvidenceItem => ({
  sourceType: 'us_evidence',
  title: overrides.id,
  freshness: 'unknown',
  qualityLevel: 'unknown',
  metadata: {},
  ...overrides,
});

describe('EvidenceSection', () => {
  it('renders nothing without evidence or gaps', () => {
    const { container } = render(<EvidenceSection evidence={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('keeps context blocks out and groups the rest by source, collapsed', () => {
    render(
      <EvidenceSection
        evidence={[
          item({ id: 'context:quote', group: 'context' }),
          item({ id: 'sec:8k:1', group: 'sec_filing' }),
          item({ id: 'ratings:recent', group: 'ratings' }),
        ]}
        language="zh-TW"
      />,
    );

    expect(screen.queryByTestId('evidence-group-context')).not.toBeInTheDocument();
    expect(screen.getByTestId('evidence-group-sec_filing')).not.toHaveAttribute('open');
    expect(screen.getByTestId('evidence-group-ratings')).toBeInTheDocument();
  });

  it('renders an SEC excerpt as plain text', () => {
    render(
      <EvidenceSection
        evidence={[item({ id: 'sec:8k:1', group: 'sec_filing', excerpt: '<b>raw</b> **text**' })]}
        language="zh-TW"
      />,
    );

    const excerpt = screen.getByTestId('evidence-excerpt');
    expect(excerpt).toHaveTextContent('<b>raw</b> **text**');
    expect(excerpt.querySelector('b')).toBeNull();
  });

  it('sums ratings by action enum', () => {
    render(
      <EvidenceSection
        evidence={[item({
          id: 'ratings:recent',
          group: 'ratings',
          series: [{ action: 'up' }, { action: 'up' }, { action: 'down' }, { action: 'weird' }],
        })]}
        language="zh-TW"
      />,
    );

    const counts = screen.getByTestId('evidence-rating-counts');
    expect(counts).toHaveTextContent('上調 2');
    expect(counts).toHaveTextContent('下調 1');
    expect(counts).toHaveTextContent('其他 1');
    expect(counts).not.toHaveTextContent('weird');
  });

  it('labels the short-interest date as a settlement date, not today', () => {
    render(
      <EvidenceSection
        evidence={[item({ id: 'us:short_interest', group: 'short_interest', observedAt: '2026-10-15', facts: { sharesShort: 1000 } })]}
        language="zh-TW"
      />,
    );

    const row = screen.getByTestId('evidence-us:short_interest');
    expect(row).toHaveTextContent('申報結算日（非當日） 2026-10-15');
    expect(within(row).getByText('放空股數')).toBeInTheDocument();
    expect(within(row).getByText('1,000')).toBeInTheDocument();
  });

  it('marks capital flow as not scored', () => {
    render(
      <EvidenceSection
        evidence={[item({ id: 'futu:capital_flow', group: 'capital_flow', countsTowardScore: false })]}
        language="zh-TW"
      />,
    );

    expect(within(screen.getByTestId('evidence-futu:capital_flow')).getByText('未計分')).toBeInTheDocument();
  });

  it('shows the one-line gap summary on its own', () => {
    render(<EvidenceSection gapSummary="這份報告缺：新聞" language="zh-TW" />);
    expect(screen.getByTestId('report-gap-summary')).toHaveTextContent('這份報告缺：新聞');
  });
});
