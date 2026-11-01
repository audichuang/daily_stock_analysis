import type React from 'react';
import type { EventOutlook, ReportLanguage } from '../../types/analysis';
import { Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { getReportPolishText } from '../../locales/reportText';

interface ReportEventOutlookProps {
  outlook?: EventOutlook | null;
  language?: ReportLanguage;
}

/** 營收金額縮寫；缺值不補 0。 */
const formatRevenue = (value: number): string => {
  if (Math.abs(value) >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (Math.abs(value) >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  return value.toLocaleString();
};

/** Title shows the event only when the date is missing or already part of the event text. */
const outlookTitle = (event: string | null | undefined, eventDate: string | null | undefined, fallback: string): string => {
  const name = event?.trim() || fallback;
  const date = eventDate?.trim();
  if (!date || name.includes(date)) return name;
  return `${name} · ${date}`;
};

/**
 * 事件展望：判斷與理由放最前面，接著是各情境怎麼做，佐證資料放最後。
 * 資料不足時只留一行判斷，情境與佐證收進 details。
 */
export const ReportEventOutlook: React.FC<ReportEventOutlookProps> = ({ outlook, language = 'zh' }) => {
  if (!outlook) {
    return null;
  }
  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const polish = getReportPolishText(reportLanguage);
  // Korean keeps its existing label; the three UI locales use the new wording.
  const confidenceTitle = reportLanguage === 'ko' ? text.eventConfidence : polish.outlookConfidence;
  const colon = reportLanguage === 'ko' ? ': ' : polish.colon;
  const insufficient = (outlook.expectation ?? 'insufficient_data') === 'insufficient_data';
  const expectationLabel = {
    beat: text.eventExpectationBeat,
    inline: text.eventExpectationInline,
    miss: text.eventExpectationMiss,
    insufficient_data: text.eventExpectationInsufficient,
  }[outlook.expectation ?? 'insufficient_data'];
  const confidenceLabel = outlook.confidence
    ? { high: text.eventConfidenceHigh, medium: text.eventConfidenceMedium, low: text.eventConfidenceLow }[outlook.confidence]
    : null;
  const caseLabels = { beat: text.eventCaseBeat, inline: text.eventCaseInline, miss: text.eventCaseMiss };
  const consensus = outlook.consensus;
  const withCurrency = (value: string, currency?: string | null) => (currency ? `${value} ${currency}` : value);
  const consensusParts = [
    consensus?.eps != null ? `${text.eventConsensusEps} ${withCurrency(consensus.eps.toFixed(2), consensus.epsCurrency)}` : null,
    consensus?.revenue != null ? `${text.eventConsensusRevenue} ${withCurrency(formatRevenue(consensus.revenue), consensus.revenueCurrency)}` : null,
    consensus?.analysts != null ? `${consensus.analysts} ${text.eventConsensusAnalysts}` : null,
  ].filter(Boolean);
  const notes: Array<[string, string | null | undefined]> = [
    [text.eventTrackRecord, outlook.trackRecord],
    [text.eventRevisionTrend, outlook.revisionTrend],
    [text.eventVerifyAfter, outlook.verifyAfter],
  ];

  const scenarios = outlook.scenarios ?? [];
  const scenarioGrid = scenarios.length > 0 ? (
    <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3" data-testid="event-outlook-scenarios">
      {scenarios.map((scenario) => (
        <div key={scenario.case} className="home-subpanel p-3 text-sm">
          <p className="font-semibold text-foreground">{caseLabels[scenario.case]}</p>
          {scenario.expectedReaction && <p className="mt-1 text-secondary-text">{scenario.expectedReaction}</p>}
          {scenario.actionIfHolding && (
            <p className="mt-1 text-secondary-text">
              <span className="text-muted-text">{text.eventIfHolding}{colon}</span>
              {scenario.actionIfHolding}
            </p>
          )}
          {scenario.actionIfFlat && (
            <p className="mt-1 text-secondary-text">
              <span className="text-muted-text">{text.eventIfFlat}{colon}</span>
              {scenario.actionIfFlat}
            </p>
          )}
        </div>
      ))}
    </div>
  ) : null;

  const evidence = (
    <>
      {outlook.newsImpact && (
        <p className="mt-3 text-sm text-secondary-text">
          <span className="font-semibold text-foreground">{text.eventNewsImpact}{colon}</span>
          {outlook.newsImpact}
        </p>
      )}
      <p className="mt-3 text-xs text-muted-text">
        {consensusParts.length > 0 ? consensusParts.join(' · ') : text.eventNoConsensus}
      </p>
      {notes.filter(([, value]) => value).map(([label, value]) => (
        <p key={label} className="mt-1 text-xs text-muted-text">
          {label}{colon}{value}
        </p>
      ))}
    </>
  );

  const reasoning = outlook.reasoning
    ? <p className="mt-2 text-sm leading-relaxed text-secondary-text">{outlook.reasoning}</p>
    : null;

  return (
    <Card variant="surface" padding="md" className="home-panel-card" data-testid="report-event-outlook">
      <DashboardPanelHeader
        eyebrow={text.eventOutlook}
        title={outlookTitle(outlook.event, outlook.eventDate, text.eventOutlook)}
        className={insufficient ? 'mb-1' : 'mb-3'}
      />
      <p className={insufficient ? 'text-sm font-semibold text-foreground' : 'text-lg font-bold text-foreground'} data-testid="event-outlook-call">
        {expectationLabel}
        {confidenceLabel && (
          <span className="ml-2 text-xs font-normal text-muted-text">
            {confidenceTitle}{colon}{confidenceLabel}
          </span>
        )}
      </p>
      {insufficient ? (
        <details className="group/outlook mt-2" data-testid="event-outlook-more">
          <summary className="cursor-pointer text-xs text-secondary-text hover:text-foreground">
            {scenarios.length > 0 ? polish.outlookScenariosToggle : polish.outlookDetailsToggle}
          </summary>
          {reasoning}
          {scenarioGrid}
          {evidence}
        </details>
      ) : (
        <>
          {reasoning}
          {scenarioGrid}
          {evidence}
        </>
      )}
    </Card>
  );
};
