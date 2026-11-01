import type React from 'react';
import { useState, useEffect, useCallback } from 'react';
import type { ParsedApiError } from '../../api/error';
import { getParsedApiError } from '../../api/error';
import { ApiErrorAlert, Card } from '../common';
import { DashboardPanelHeader, DashboardStateBlock } from '../dashboard';
import { historyApi } from '../../api/history';
import type { NewsIntelItem, ReportLanguage } from '../../types/analysis';
import { markdownToPlainText } from '../../utils/markdown';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

interface ReportNewsProps {
  recordId?: number;  // 分析歷史紀錄主鍵 ID
  limit?: number;
  language?: ReportLanguage;
}

const DEFAULT_VISIBLE = 3;

// 網址來自外部搜尋結果，只讓 http(s) 變成連結。
const safeNewsUrl = (url?: string | null): string | null => {
  const trimmed = url?.trim() ?? '';
  return /^https?:\/\//i.test(trimmed) ? trimmed : null;
};

const newsDate = (item: NewsIntelItem): string | null =>
  (item.publishedAt || item.publishedDate || '').slice(0, 10) || null;

/**
 * 資訊區：單行列表，預設 3 則；整列可點，來源與日期放右側。
 */
export const ReportNews: React.FC<ReportNewsProps> = ({ recordId, limit = 8, language = 'zh' }) => {
  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const [isLoading, setIsLoading] = useState(false);
  const [items, setItems] = useState<NewsIntelItem[]>([]);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [expanded, setExpanded] = useState(false);

  const fetchNews = useCallback(async () => {
    if (!recordId) return;
    setIsLoading(true);
    setError(null);

    try {
      const response = await historyApi.getNews(recordId, limit);
      setItems(response.items || []);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setIsLoading(false);
    }
  }, [recordId, limit]);

  useEffect(() => {
    setItems([]);
    setError(null);
    setExpanded(false);

    if (recordId) {
      fetchNews();
    }
  }, [recordId, fetchNews]);

  if (!recordId) {
    return null;
  }

  const visibleItems = expanded ? items : items.slice(0, DEFAULT_VISIBLE);

  return (
    <Card variant="surface" padding="md" className="home-panel-card">
      <DashboardPanelHeader
        title={text.relatedNews}
        actions={(
          <div className="flex items-center gap-2">
            {isLoading ? (
              <div className="home-spinner h-3.5 w-3.5 animate-spin border-2" aria-hidden="true" />
            ) : null}
            <button
              type="button"
              onClick={() => void fetchNews()}
              className="home-accent-link text-xs"
              aria-label={text.refresh}
            >
              {text.refresh}
            </button>
          </div>
        )}
      />

      {error && !isLoading && (
        <ApiErrorAlert
          error={error}
          actionLabel={text.retry}
          onAction={() => void fetchNews()}
          dismissLabel={text.dismiss}
        />
      )}

      {isLoading && !error && (
        <DashboardStateBlock
          compact
          loading
          title={text.loadingNews}
        />
      )}

      {!isLoading && !error && items.length === 0 && (
        <DashboardStateBlock
          compact
          title={text.noNews}
          description={text.noNewsDescription}
        />
      )}

      {!isLoading && !error && items.length > 0 && (
        <>
          <ul className="divide-y divide-border/50 text-left" data-testid="report-news-list">
            {visibleItems.map((item, index) => {
              const title = markdownToPlainText(item.title) || item.title;
              const url = safeNewsUrl(item.url);
              const date = newsDate(item);
              const meta = [item.source?.trim(), date].filter(Boolean).join(' · ');
              const row = (
                <>
                  <span className="min-w-0 flex-1 truncate text-sm text-foreground" title={item.keyPoint || title}>{title}</span>
                  {meta ? <span className="max-w-[45%] shrink-0 truncate text-xs tabular-nums text-muted-text">{meta}</span> : null}
                </>
              );
              return (
                <li key={`${item.title}-${index}`}>
                  {url ? (
                    <a href={url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-3 rounded py-2 hover:bg-hover">
                      {row}
                    </a>
                  ) : (
                    <div className="flex items-center gap-3 py-2">{row}</div>
                  )}
                </li>
              );
            })}
          </ul>
          {items.length > DEFAULT_VISIBLE ? (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="home-accent-link mt-2 text-xs"
            >
              {expanded ? text.collapseNews : text.expandNews.replace('{count}', String(items.length))}
            </button>
          ) : null}
        </>
      )}
    </Card>
  );
};
