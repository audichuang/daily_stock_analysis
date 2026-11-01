import { describe, expect, it } from 'vitest';
import { extractReportHeadings, reportHeadingId, splitLeadingEmoji, stripTrailingGeneratedAt } from '../reportMarkdown';

describe('splitLeadingEmoji', () => {
  it('splits an emoji with a variation selector', () => {
    expect(splitLeadingEmoji('⚠️ 風險')).toEqual({ emoji: '⚠️', rest: '風險' });
  });

  it('leaves digits and plain text alone', () => {
    expect(splitLeadingEmoji('2330 結論')).toEqual({ emoji: null, rest: '2330 結論' });
  });
});

describe('extractReportHeadings', () => {
  it('uses source lines as ids and ignores fenced code', () => {
    const markdown = '# 📊 總覽\n\n```\n# not a heading\n```\n\n## 風險\n## 風險\n#### 太深';
    expect(extractReportHeadings(markdown)).toEqual([
      { id: reportHeadingId(1), level: 1, title: '總覽' },
      { id: reportHeadingId(7), level: 2, title: '風險' },
      { id: reportHeadingId(8), level: 2, title: '風險' },
    ]);
  });
});

describe('stripTrailingGeneratedAt', () => {
  it('removes the template footer and keeps the model line', () => {
    const markdown = '內文\n\n*報告生成時間：2026-10-30 12:00:00*\n*分析模型：x*\n';
    const stripped = stripTrailingGeneratedAt(markdown);
    expect(stripped).not.toContain('報告生成時間');
    expect(stripped).toContain('*分析模型：x*');
  });

  it('does not touch the same text in the body', () => {
    const body = ['*報告生成時間：內文引用*', 'a', 'b', 'c', 'd', 'e'].join('\n');
    expect(stripTrailingGeneratedAt(body)).toContain('內文引用');
  });
});
