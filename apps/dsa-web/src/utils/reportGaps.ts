import type { ReportLanguage } from '../types/analysis';
import type { ResearchArtifact, ResearchSourceStatus } from '../types/researchArtifact';
import { normalizeReportLanguage } from './reportLanguage';

const GAP_TEXT = {
  zh: {
    summaryPrefix: '这份报告缺：',
    notice: '部分资料缺漏，这份结论可能不完整。',
    sources: { sec_finra: 'SEC／FINRA', insider: '内部人交易', ratings: '评等', estimates: '法人预估', futu: '富途资金流' },
  },
  en: {
    summaryPrefix: 'This report is missing: ',
    notice: 'Some data is missing, so this conclusion may be incomplete.',
    sources: { sec_finra: 'SEC/FINRA', insider: 'Insider trades', ratings: 'Ratings', estimates: 'Estimates', futu: 'Futu capital flow' },
  },
  'zh-TW': {
    summaryPrefix: '這份報告缺：',
    notice: '部分資料缺漏，這份結論可能不完整。',
    sources: { sec_finra: 'SEC／FINRA', insider: '內部人交易', ratings: '評等', estimates: '法人預估', futu: '富途資金流' },
  },
  ko: {
    summaryPrefix: '이 리포트에 없는 데이터: ',
    notice: '일부 데이터가 없어 결론이 불완전할 수 있습니다.',
    sources: { sec_finra: 'SEC/FINRA', insider: '내부자 거래', ratings: '투자의견', estimates: '추정치', futu: 'Futu 자금 흐름' },
  },
} as const;

// 這幾種代表「該有卻沒拿到」；not_configured、not_supported 是本來就沒有，不算缺。
const MISSING_SOURCE_STATUS: ReadonlySet<ResearchSourceStatus> = new Set<ResearchSourceStatus>([
  'no_data',
  'fetch_failed',
  'timeout',
]);

export interface ReportGaps {
  /** 一行摘要；沒有缺項為 null。 */
  summary: string | null;
  /** 結論下的黃色提示；缺項不影響判斷時為 null。 */
  notice: string | null;
}

/** 全部讀結構化欄位：缺哪些看 missingBlocks 與 sourceStatus，影不影響判斷看後端算的資料品質等級。 */
export const summarizeReportGaps = (
  artifact: ResearchArtifact | null | undefined,
  language?: ReportLanguage | null,
): ReportGaps => {
  if (!artifact) return { summary: null, notice: null };
  const text = GAP_TEXT[normalizeReportLanguage(language)];
  const sourceLabels: Record<string, string> = text.sources;

  const blocks = (artifact.dataQuality?.missingBlocks ?? []).map(
    (key) => artifact.evidence?.find((item) => item.id === `context:${key}`)?.title ?? key,
  );
  const sources = Object.entries(artifact.sourceStatus ?? {})
    .filter(([, status]) => MISSING_SOURCE_STATUS.has(status))
    .map(([key]) => sourceLabels[key] ?? key);
  const items = [...blocks, ...sources];
  const level = artifact.dataQuality?.level;

  return {
    summary: items.length > 0 ? `${text.summaryPrefix}${items.join('、')}` : null,
    notice: level === 'limited' || level === 'poor' ? text.notice : null,
  };
};
