export interface ReportHeading {
  id: string;
  /** 1～3 */
  level: number;
  title: string;
}

/** 以來源行號當錨點：目錄與標題元件各自算出來一定相同，重複標題也不衝突。 */
export const reportHeadingId = (line: number): string => `report-section-${line}`;

// 開頭的 emoji（含變體選擇符與連接序列）與其後空白。
const LEADING_EMOJI_RE = /^((?:\p{Extended_Pictographic}|\p{Regional_Indicator})(?:️|‍\p{Extended_Pictographic})*)\s*/u;

export const splitLeadingEmoji = (title: string): { emoji: string | null; rest: string } => {
  const matched = LEADING_EMOJI_RE.exec(title);
  return matched ? { emoji: matched[1], rest: title.slice(matched[0].length) } : { emoji: null, rest: title };
};

const plainHeadingTitle = (raw: string): string =>
  splitLeadingEmoji(raw.replace(/\s*#+\s*$/, '').replace(/[*_`]/g, '').trim()).rest;

/** 列出 1～3 級標題給目錄用；圍欄程式碼裡的 # 不算。 */
export const extractReportHeadings = (markdown: string): ReportHeading[] => {
  const headings: ReportHeading[] = [];
  let inFence = false;
  markdown.split('\n').forEach((line, index) => {
    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence;
      return;
    }
    if (inFence) return;
    const matched = /^(#{1,3})\s+(.+)$/.exec(line);
    if (!matched) return;
    const title = plainHeadingTitle(matched[2]);
    if (title) headings.push({ id: reportHeadingId(index + 1), level: matched[1].length, title });
  });
  return headings;
};

// report_language.py 的 generated_at_label／report_time_label，是模板寫死的頁尾，不是模型輸出。
const GENERATED_AT_LINE_RE = /^\*(?:报告生成时间|報告生成時間|生成时间|生成時間|Generated At|Report Time|생성 시각)\s*[:：].*\*\s*$/;

/** 拿掉報告結尾的產生時間：抽屜標頭已經有了。只看最後幾行，內文同樣的字不動；複製仍用原文。 */
export const stripTrailingGeneratedAt = (markdown: string): string => {
  const lines = markdown.split('\n');
  const tailStart = Math.max(0, lines.length - 4);
  return lines
    .filter((line, index) => index < tailStart || !GENERATED_AT_LINE_RE.test(line.trim()))
    .join('\n')
    .trimEnd();
};
