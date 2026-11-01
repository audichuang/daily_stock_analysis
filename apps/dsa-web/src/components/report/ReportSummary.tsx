import { ChevronDown } from 'lucide-react';
import React from 'react';
import type { AnalysisResult, AnalysisReport } from '../../types/analysis';
import { summarizeReportGaps } from '../../utils/reportGaps';
import { formatModelLabel, getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { AnalysisContextSummary } from './AnalysisContextSummary';
import { EventGapCard, ReportChangeConditions } from './EventGapCard';
import { EvidenceSection } from './EvidenceSection';
import { FinancialsPanel } from './FinancialsPanel';
import { MarketReviewReportView } from './MarketReviewReportView';
import { ReportDetails } from './ReportDetails';
import { ReportDiagnostics } from './ReportDiagnostics';
import { ReportEventOutlook } from './ReportEventOutlook';
import { ReportNews } from './ReportNews';
import { ReportOverview } from './ReportOverview';
import { ReportStrategy } from './ReportStrategy';
import { StockPriceChart } from './StockPriceChart';

interface ReportSummaryProps {
  data: AnalysisResult | AnalysisReport;
  isHistory?: boolean;
  /** 自選相關 */
  watchlist?: {
    isInWatchlist: (code: string) => boolean;
    onToggle: (code: string) => void;
    isActioning: boolean;
    actionMessage: string | null;
  };
  onOpenRunFlow?: (recordId: number) => void;
  /** 併入個股標題列的動作（完整報告、追問 AI、⋯）。 */
  headerActions?: React.ReactNode;
}

/**
 * 完整報告：結論 → 事件 → 關鍵價位與 K 線 → 改判條件 → 事件展望 → 財報 → 證據與新聞，
 * 資料品質與來源收合在最後。先看價位再看財報。
 */
export const ReportSummary: React.FC<ReportSummaryProps> = ({
  data,
  isHistory = false,
  watchlist,
  onOpenRunFlow,
  headerActions,
}) => {
  // 相容 AnalysisResult 和 AnalysisReport 兩種資料格式
  const report: AnalysisReport = 'report' in data ? data.report : data;
  // 用 report id：queryId 在批次分析時可能重複，歷史報告詳情介面也要 recordId
  const recordId = report.meta.id;
  const diagnosticSummary = 'diagnosticSummary' in data ? data.diagnosticSummary : undefined;

  const { meta, summary, strategy, details, structuredReport } = report;
  const reportLanguage = normalizeReportLanguage(meta.reportLanguage);
  const text = getReportText(reportLanguage);
  const modelUsed = (meta.modelUsed || '').trim();
  const shouldShowModel = Boolean(
    modelUsed && !['unknown', 'error', 'none', 'null', 'n/a'].includes(modelUsed.toLowerCase()),
  );

  if (meta.reportType === 'market_review') {
    return (
      <MarketReviewReportView
        report={report}
        recordId={recordId}
        reportLanguage={reportLanguage}
        onOpenRunFlow={onOpenRunFlow}
      />
    );
  }

  const eventGap = structuredReport?.eventGap;
  // 無新聞護欄擋下時，任何價位都不該留在畫面上。
  const levelsBlocked = eventGap?.triggered === true && eventGap.blockedWithoutNews === true;
  const gaps = summarizeReportGaps(structuredReport, reportLanguage);

  return (
    <div className="space-y-4 pb-8 animate-fade-in">
      {/* 首屏：結論列與分持股建議 */}
      <ReportOverview
        meta={meta}
        summary={summary}
        details={details}
        isHistory={isHistory}
        notice={gaps.notice}
        watchlist={watchlist}
        headerActions={headerActions}
      />

      <EventGapCard eventGap={eventGap} currency={meta.currency} language={reportLanguage} />

      {levelsBlocked ? null : (
        <ReportStrategy
          strategy={strategy}
          language={reportLanguage}
          action={summary.action}
          currentPrice={meta.currentPrice}
          currency={meta.currency}
          stockCode={meta.stockCode}
        />
      )}

      <StockPriceChart
        stockCode={meta.stockCode}
        contextSnapshot={details?.contextSnapshot}
        strategy={strategy}
        currency={meta.currency}
        language={reportLanguage}
        hideLevels={levelsBlocked}
        action={summary.action}
      />

      <ReportChangeConditions summary={summary} language={reportLanguage} />

      {/* 事件展望：判斷與各情境動作；資料不足時收成一行 */}
      <ReportEventOutlook outlook={report.eventOutlook} language={reportLanguage} />

      {meta.stockCode ? <FinancialsPanel stockCode={meta.stockCode} /> : null}

      <EvidenceSection evidence={structuredReport?.evidence} gapSummary={gaps.summary} language={reportLanguage} />

      <ReportNews recordId={recordId} limit={8} language={reportLanguage} />

      {/* 資料品質與來源：輸入資料、執行診斷、資料追溯預設收合 */}
      <details data-testid="report-data-quality" className="group/quality">
        <summary className="home-surface-button flex cursor-pointer list-none items-center justify-between gap-3 rounded-lg px-4 py-3 text-left">
          <span className="min-w-0">
            <span className="block text-sm font-semibold text-foreground">{text.dataQualityTitle}</span>
            <span className="block text-xs text-muted-text">{text.dataQualityHint}</span>
          </span>
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-text transition-transform group-open/quality:rotate-180" aria-hidden="true" />
        </summary>
        <div className="mt-3 space-y-4">
          <AnalysisContextSummary overview={details?.analysisContextPackOverview} language={reportLanguage} />
          <ReportDiagnostics
            recordId={recordId}
            summary={diagnosticSummary}
            language={reportLanguage}
            onOpenRunFlow={onOpenRunFlow}
          />
          <ReportDetails details={details} recordId={recordId} language={reportLanguage} />
        </div>
      </details>

      {shouldShowModel && (
        <p className="px-1 text-xs text-muted-text">
          {text.analysisModel}: {formatModelLabel(modelUsed)}
        </p>
      )}
    </div>
  );
};
