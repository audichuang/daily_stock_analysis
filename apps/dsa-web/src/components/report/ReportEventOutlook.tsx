import type React from 'react';
import type { EventOutlook, ReportLanguage } from '../../types/analysis';
import { Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

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

/**
 * 事件展望：判斷與理由放最前面，接著是各情境怎麼做，佐證資料放最後。
 */
export const ReportEventOutlook: React.FC<ReportEventOutlookProps> = ({ outlook, language = 'zh' }) => {
  if (!outlook) {
    return null;
  }
  const text = getReportText(normalizeReportLanguage(language));
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
  const currency = consensus?.currency ? ` ${consensus.currency}` : '';
  const consensusParts = [
    consensus?.eps != null ? `${text.eventConsensusEps} ${consensus.eps.toFixed(2)}${currency}` : null,
    consensus?.revenue != null ? `${text.eventConsensusRevenue} ${formatRevenue(consensus.revenue)}${currency}` : null,
    consensus?.analysts != null ? `${consensus.analysts} ${text.eventConsensusAnalysts}` : null,
  ].filter(Boolean);
  const notes: Array<[string, string | null | undefined]> = [
    [text.eventTrackRecord, outlook.trackRecord],
    [text.eventRevisionTrend, outlook.revisionTrend],
    [text.eventVerifyAfter, outlook.verifyAfter],
  ];

  return (
    <Card variant="bordered" padding="md" className="home-panel-card" data-testid="report-event-outlook">
      <DashboardPanelHeader
        eyebrow={text.eventOutlook}
        title={`${outlook.event ?? text.eventOutlook} · ${outlook.eventDate ?? text.eventDateUnknown}`}
        className="mb-3"
      />
      <p className="text-lg font-bold text-foreground">
        {expectationLabel}
        {confidenceLabel && (
          <span className="ml-2 text-xs font-normal text-muted-text">
            {text.eventConfidence}: {confidenceLabel}
          </span>
        )}
      </p>
      {outlook.reasoning && <p className="mt-2 text-sm leading-relaxed text-secondary-text">{outlook.reasoning}</p>}

      {Boolean(outlook.scenarios?.length) && (
        <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
          {outlook.scenarios?.map((scenario) => (
            <div key={scenario.case} className="home-subpanel p-3 text-sm">
              <p className="font-semibold text-foreground">{caseLabels[scenario.case]}</p>
              {scenario.expectedReaction && <p className="mt-1 text-secondary-text">{scenario.expectedReaction}</p>}
              {scenario.actionIfHolding && (
                <p className="mt-1 text-secondary-text">
                  <span className="text-muted-text">{text.eventIfHolding}: </span>
                  {scenario.actionIfHolding}
                </p>
              )}
              {scenario.actionIfFlat && (
                <p className="mt-1 text-secondary-text">
                  <span className="text-muted-text">{text.eventIfFlat}: </span>
                  {scenario.actionIfFlat}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {outlook.newsImpact && (
        <p className="mt-3 text-sm text-secondary-text">
          <span className="font-semibold text-foreground">{text.eventNewsImpact}: </span>
          {outlook.newsImpact}
        </p>
      )}
      <p className="mt-3 text-xs text-muted-text">
        {consensusParts.length > 0 ? consensusParts.join(' · ') : text.eventNoConsensus}
      </p>
      {notes.filter(([, value]) => value).map(([label, value]) => (
        <p key={label} className="mt-1 text-xs text-muted-text">
          {label}: {value}
        </p>
      ))}
    </Card>
  );
};
