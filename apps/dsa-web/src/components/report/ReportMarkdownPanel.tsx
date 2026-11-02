import { Check, Copy } from 'lucide-react';
import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { historyApi } from '../../api/history';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { ReportLanguage, ReportSummary } from '../../types/analysis';
import { buildDecisionActionLabelMap, getDecisionActionLabel } from '../../utils/decisionAction';
import { markdownToPlainText } from '../../utils/markdown';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { extractReportHeadings, stripTrailingGeneratedAt } from '../../utils/reportMarkdown';
import { ReportMarkdownBody } from './ReportMarkdownBody';
import { ShareImageButton } from './ShareImageButton';

export interface ReportMarkdownPanelProps {
  recordId: number;
  stockName: string;
  stockCode: string;
  onRequestClose: () => void;
  reportLanguage?: ReportLanguage;
  /** 固定結論列的內容；沒給就只顯示股名。 */
  summary?: ReportSummary;
}

const SKELETON_WIDTHS = ['w-1/3', 'w-full', 'w-11/12', 'w-4/5', 'w-1/4', 'w-full', 'w-3/4'];

export const ReportMarkdownPanel: React.FC<ReportMarkdownPanelProps> = ({
  recordId,
  stockName,
  stockCode,
  onRequestClose,
  reportLanguage = 'zh',
  summary,
}) => {
  const { t } = useUiLanguage();
  const text = getReportText(normalizeReportLanguage(reportLanguage));
  const loadReportFailedText = text.loadReportFailed;
  const [content, setContent] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [copiedType, setCopiedType] = useState<'markdown' | 'text' | null>(null);
  const [copyMenuOpen, setCopyMenuOpen] = useState(false);
  const copyMenuRef = useRef<HTMLDivElement>(null);

  const copyToClipboard = useCallback(async (value: string, type: 'markdown' | 'text') => {
    setCopyMenuOpen(false);
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopiedType(type);
      setTimeout(() => setCopiedType(null), 2000);
    } catch (copyError) {
      console.error('Copy failed:', copyError);
    }
  }, []);

  useEffect(() => {
    if (!copyMenuOpen) return undefined;
    const handlePointer = (event: MouseEvent) => {
      if (!copyMenuRef.current?.contains(event.target as Node)) setCopyMenuOpen(false);
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        // 只收選單，不要連抽屜一起關。
        event.stopPropagation();
        setCopyMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handlePointer);
    document.addEventListener('keydown', handleKey, true);
    return () => {
      document.removeEventListener('mousedown', handlePointer);
      document.removeEventListener('keydown', handleKey, true);
    };
  }, [copyMenuOpen]);

  useEffect(() => {
    let isMounted = true;

    const fetchMarkdown = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const markdownContent = await historyApi.getMarkdown(recordId);
        if (isMounted) {
          setContent(markdownContent);
        }
      } catch (err) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : loadReportFailedText);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };

    fetchMarkdown();

    return () => {
      isMounted = false;
    };
  }, [recordId, loadReportFailedText, reloadKey]);

  const bodyContent = useMemo(() => stripTrailingGeneratedAt(content), [content]);
  const headings = useMemo(() => extractReportHeadings(bodyContent), [bodyContent]);
  const actionLabel = summary
    ? getDecisionActionLabel(summary.action, summary.actionLabel, summary.operationAdvice, null, buildDecisionActionLabelMap(t))
    : null;
  const conclusion = summary?.oneSentence?.trim() || summary?.analysisSummary?.trim() || null;

  return (
    <>
      {/* Drawer 內容區有 p-6：Chrome 的 sticky 從 padding 內側起算，top 要用 -top-6 抵消，
          否則固定列一直停在上緣下方 24px，露縫並在剛打開時壓住首個標題。負邊距讓它貼齊捲動區兩側與上緣。 */}
      <div className="sticky -top-6 z-10 -mx-6 -mt-6 mb-4 border-b border-border/60 bg-card px-6 py-3" data-testid="report-drawer-header">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-semibold text-foreground">{stockName || stockCode}</h2>
            <p className="text-xs text-muted-text">{text.fullReport}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <ShareImageButton
              recordId={recordId}
              reportTitle={`${stockName || stockCode}-${stockCode}`}
              reportLanguage={reportLanguage}
            />
            <div className="relative" ref={copyMenuRef}>
              <button
                type="button"
                aria-haspopup="menu"
                aria-expanded={copyMenuOpen}
                disabled={isLoading || !content}
                onClick={() => setCopyMenuOpen((open) => !open)}
                className="home-surface-button flex h-10 items-center gap-1.5 rounded-lg px-3 text-sm text-secondary-text hover:text-foreground disabled:opacity-50"
              >
                {copiedType ? <Check className="h-4 w-4 text-success" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
                {copiedType ? text.copied : text.copyMenu}
              </button>
              {copyMenuOpen ? (
                <div role="menu" className="absolute right-0 top-full z-20 mt-1 w-48 rounded-lg border border-border/70 bg-card p-1 shadow-soft-card">
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => void copyToClipboard(content, 'markdown')}
                    className="w-full rounded px-3 py-2 text-left text-sm text-foreground hover:bg-hover"
                  >
                    {text.copyMarkdownSource}
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => void copyToClipboard(markdownToPlainText(content), 'text')}
                    className="w-full rounded px-3 py-2 text-left text-sm text-foreground hover:bg-hover"
                  >
                    {text.copyPlainText}
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </div>
        {actionLabel || conclusion ? (
          <p data-testid="report-drawer-conclusion" className="mt-2 line-clamp-2 text-sm leading-6 text-foreground">
            {actionLabel ? <span className="mr-2 font-semibold">{actionLabel}</span> : null}
            {conclusion}
          </p>
        ) : null}
        {headings.length > 1 && !isLoading && !error ? (
          <nav aria-label={text.tableOfContents} className="mt-2 flex gap-3 overflow-x-auto whitespace-nowrap pb-1 text-xs">
            {headings.filter((heading) => heading.level <= 2).map((heading) => (
              <button
                key={heading.id}
                type="button"
                className="home-accent-link shrink-0"
                onClick={() => document.getElementById(heading.id)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })}
              >
                {heading.title}
              </button>
            ))}
          </nav>
        ) : null}
      </div>

      {isLoading ? (
        <div data-testid="report-drawer-skeleton" role="status" aria-label={text.loadingReport} className="animate-pulse space-y-3">
          {SKELETON_WIDTHS.map((width, index) => (
            <div key={index} className={`h-4 rounded bg-border/50 ${width}`} />
          ))}
        </div>
      ) : error ? (
        <div className="flex h-64 flex-col items-center justify-center">
          <p role="alert" className="text-sm text-danger">{error}</p>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => setReloadKey((key) => key + 1)}
              className="home-surface-button rounded-lg px-4 py-2 text-sm text-foreground"
            >
              {text.retry}
            </button>
            <button
              type="button"
              onClick={onRequestClose}
              className="home-surface-button rounded-lg px-4 py-2 text-sm text-secondary-text"
            >
              {text.dismiss}
            </button>
          </div>
        </div>
      ) : (
        <ReportMarkdownBody content={bodyContent} />
      )}
    </>
  );
};
