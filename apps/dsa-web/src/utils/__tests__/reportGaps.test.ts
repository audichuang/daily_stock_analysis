import { describe, expect, it } from 'vitest';
import type { ResearchArtifact } from '../../types/researchArtifact';
import { summarizeReportGaps } from '../reportGaps';

const artifact = (overrides: Partial<ResearchArtifact>): ResearchArtifact => ({
  schemaVersion: 'research-artifact-v1',
  artifactId: 'a',
  subject: { stockCode: 'AAPL' },
  thesis: { direction: 'neutral', summary: '', reasons: [], risks: [] },
  evidence: [],
  invalidationConditions: [],
  nextActions: [],
  dataQuality: { level: 'good', sourceCount: 0, staleCount: 0, missingBlocks: [], limitations: [] },
  metadata: {},
  ...overrides,
});

describe('summarizeReportGaps', () => {
  it('returns nothing for old reports without an artifact', () => {
    expect(summarizeReportGaps(null)).toEqual({ summary: null, notice: null });
  });

  it('lists missing blocks by their localized evidence title and failed sources only', () => {
    const gaps = summarizeReportGaps(artifact({
      evidence: [{
        id: 'context:news', sourceType: 'analysis_context', title: '新聞',
        freshness: 'unknown', qualityLevel: 'poor', metadata: {},
      }],
      dataQuality: { level: 'good', sourceCount: 0, staleCount: 0, missingBlocks: ['news'], limitations: [] },
      sourceStatus: { insider: 'timeout', futu: 'not_configured', ratings: 'ok' },
    }), 'zh-TW');

    expect(gaps.summary).toBe('這份報告缺：新聞、內部人交易');
    // 等級沒下降就不打擾結論。
    expect(gaps.notice).toBeNull();
  });

  it('raises the notice only when the backend quality level is limited or poor', () => {
    const limited = artifact({ dataQuality: { level: 'limited', sourceCount: 0, staleCount: 0, missingBlocks: [], limitations: [] } });
    const usable = artifact({ dataQuality: { level: 'usable', sourceCount: 0, staleCount: 0, missingBlocks: [], limitations: [] } });
    expect(summarizeReportGaps(limited, 'zh-TW').notice).not.toBeNull();
    expect(summarizeReportGaps(usable, 'zh-TW').notice).toBeNull();
  });
});
