import {
  AlertTriangle,
  BarChart3,
  Calendar,
  CheckCircle2,
  Crosshair,
  FileText,
  Lightbulb,
  Newspaper,
  Shield,
  Target,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react';
import type React from 'react';
import { Children, isValidElement } from 'react';
import Markdown, { type Components, type ExtraProps } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { reportHeadingId, splitLeadingEmoji } from '../../utils/reportMarkdown';

interface ReportMarkdownBodyProps {
  content: string;
  className?: string;
  testId?: string;
}

// 報告模板用到的標題 emoji；沒對到的就單純拿掉，不留彩色字元。
const HEADING_ICONS: Record<string, LucideIcon> = {
  '📊': BarChart3,
  '📈': TrendingUp,
  '📉': TrendingUp,
  '🎯': Target,
  '⚠️': AlertTriangle,
  '🚨': AlertTriangle,
  '📰': Newspaper,
  '📢': Newspaper,
  '💡': Lightbulb,
  '🛡️': Shield,
  '📅': Calendar,
  '📋': FileText,
  '📝': FileText,
  '✅': CheckCircle2,
  '🔫': Crosshair,
};

const nodeText = (node: React.ReactNode): string =>
  Children.toArray(node).map((child) => {
    if (typeof child === 'string' || typeof child === 'number') return String(child);
    return isValidElement<{ children?: React.ReactNode }>(child) ? nodeText(child.props.children) : '';
  }).join('');

type HeadingTag = 'h1' | 'h2' | 'h3' | 'h4';

const makeHeading = (Tag: HeadingTag) =>
  function ReportHeading({ node, children }: React.HTMLAttributes<HTMLHeadingElement> & ExtraProps) {
    const line = node?.position?.start.line;
    const { emoji, rest } = splitLeadingEmoji(nodeText(children));
    const Icon = emoji ? HEADING_ICONS[emoji] : undefined;
    return (
      <Tag id={line ? reportHeadingId(line) : undefined} className={Icon ? 'flex scroll-mt-40 items-center gap-1.5' : 'scroll-mt-40'}>
        {Icon ? <Icon className="h-[1em] w-[1em] shrink-0 text-secondary-text" aria-hidden="true" /> : null}
        {/* 沒有 emoji 時保留原節點，標題裡的粗體、程式碼才不會被壓平 */}
        {emoji ? rest : children}
      </Tag>
    );
  };

const MARKDOWN_COMPONENTS: Components = {
  h1: makeHeading('h1'),
  h2: makeHeading('h2'),
  h3: makeHeading('h3'),
  h4: makeHeading('h4'),
  // 表格自動版面可換行；只有內容真的放不下才在這層橫捲，不撐破抽屜。
  table: ({ children }) => (
    <div className="max-w-full overflow-x-auto" data-testid="report-table-scroll">
      <table>{children}</table>
    </div>
  ),
};

export const ReportMarkdownBody: React.FC<ReportMarkdownBodyProps> = ({
  content,
  className = '',
  testId,
}) => (
  <div
    data-testid={testId}
    className={`home-markdown-prose prose prose-invert prose-sm max-w-none
      prose-headings:text-foreground prose-headings:font-semibold prose-headings:mt-4 prose-headings:mb-2
      prose-h1:text-xl
      prose-h2:text-lg
      prose-h3:text-base
      prose-p:leading-relaxed prose-p:mb-3 prose-p:last:mb-0
      prose-strong:text-foreground prose-strong:font-semibold
      prose-ul:my-2 prose-ol:my-2 prose-li:my-1
      prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none
      prose-pre:border
      prose-table:border-collapse
      prose-hr:my-4
      prose-a:no-underline hover:prose-a:underline
      prose-blockquote:text-secondary-text
      whitespace-pre-line break-words
      ${className}
    `}
  >
    <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
      {content}
    </Markdown>
  </div>
);
