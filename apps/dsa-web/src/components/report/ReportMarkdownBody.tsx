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

const BLOCK_TAGS = new Set(['ul', 'ol', 'p', 'pre', 'blockquote', 'table', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr']);
// Our own overrides (headings, table wrapper) are function components and all render blocks.
const isBlockChild = (child: React.ReactNode): boolean =>
  isValidElement(child) && (typeof child.type !== 'string' || BLOCK_TAGS.has(child.type));

/**
 * Soft line breaks inside a tight list item used to show via the container's pre-line. Turn them into <br>
 * for the item's own text only: the newline-only text nodes react-markdown puts around nested lists and
 * loose-item paragraphs are dropped, so they never become blank lines.
 */
const withSoftBreaks = (children: React.ReactNode): React.ReactNode[] => {
  const items = Children.toArray(children);
  return items.flatMap<React.ReactNode>((child, index) => {
    if (typeof child !== 'string') return [child];
    let text = child;
    const previous = index > 0 ? items[index - 1] : null;
    if (previous && isBlockChild(previous)) text = text.replace(/^\n+/, '');
    // A hard break (two trailing spaces or a backslash) already arrives as <br> followed by "\n…"; drop that one newline.
    else if (isValidElement(previous) && previous.type === 'br') text = text.replace(/^\n/, '');
    if (index === items.length - 1 || isBlockChild(items[index + 1])) text = text.replace(/\n+$/, '');
    return text.split('\n').flatMap((line, lineIndex) => (lineIndex === 0 ? [line] : [<br key={`br-${index}-${lineIndex}`} />, line]));
  });
};

const MARKDOWN_COMPONENTS: Components = {
  h1: makeHeading('h1'),
  h2: makeHeading('h2'),
  h3: makeHeading('h3'),
  h4: makeHeading('h4'),
  // 表格自動版面可換行；只有內容真的放不下才在這層橫捲，不撐破抽屜。
  // className carries GFM's task-list-item and id the footnote anchor; nothing else from the hast node is needed.
  li: ({ id, className, children }) => <li id={id} className={className}>{withSoftBreaks(children)}</li>,
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
      [&_p]:whitespace-pre-line break-words
      ${className}
    `}
  >
    <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
      {content}
    </Markdown>
  </div>
);
