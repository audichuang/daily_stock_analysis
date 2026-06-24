import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { stocksApi, type StockQuoteBatchItem } from '../api/stocks';
import { systemConfigApi } from '../api/systemConfig';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import { ApiErrorAlert, AppPage, Card, EmptyState, Loading, PageHeader } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { formatSignedPct } from '../utils/portfolioFormat';
import { formatDateTime } from '../utils/format';
import { cn } from '../utils/cn';

const POLL_INTERVAL_MS = 30_000;

// 台股/A股涨跌色：红涨绿跌
function changeClass(value?: number | null): string {
  if (value == null || Number.isNaN(value) || value === 0) return 'text-secondary-text';
  return value > 0 ? 'text-red-500' : 'text-emerald-500';
}

type Freshness = 'live' | 'delayed' | 'unavailable';

function freshnessOf(item: StockQuoteBatchItem): Freshness {
  if (!item.quote) return 'unavailable';
  // 严格要求 isStale === false 才算实时：isStale 为 null/undefined（如 provider_timestamp 解析失败）
  // 不可乐观当成实时。
  if (item.quote.source === 'shioaji' && item.quote.isStale === false) return 'live';
  return 'delayed';
}

const RealtimeBoardPage: React.FC = () => {
  const { t } = useUiLanguage();
  const navigate = useNavigate();
  const [codes, setCodes] = useState<string[] | null>(null);
  const [items, setItems] = useState<StockQuoteBatchItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const codesRef = useRef<string[]>([]);

  const refresh = useCallback(async () => {
    const current = codesRef.current;
    if (current.length === 0) {
      setItems([]);
      return;
    }
    try {
      const result = await stocksApi.getQuotes(current);
      setItems(result);
      setError(null);
    } catch (err) {
      setError(getParsedApiError(err));
    }
  }, []);

  // 初次加载 watchlist
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const watchlist = await systemConfigApi.getWatchlist();
        if (!active) return;
        codesRef.current = watchlist;
        setCodes(watchlist);
        await refresh();
      } catch (err) {
        if (active) setError(getParsedApiError(err));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [refresh]);

  // 30s 轮询，tab 不可见时暂停
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const badge = (item: StockQuoteBatchItem) => {
    const kind = freshnessOf(item);
    const styles: Record<Freshness, string> = {
      live: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-600',
      delayed: 'border-amber-500/25 bg-amber-500/10 text-amber-600',
      unavailable: 'border-border bg-hover text-secondary-text',
    };
    const label = t(`board.source.${kind}` as 'board.source.live');
    return (
      <span className={cn('inline-flex rounded-md border px-2 py-0.5 text-xs', styles[kind])}>
        {label}
        {kind === 'live' && item.quote?.source ? ` · ${item.quote.source}` : null}
      </span>
    );
  };

  const refreshButton = (
    <button
      type="button"
      className="btn-secondary inline-flex items-center gap-2 text-sm"
      onClick={() => void refresh()}
    >
      <RefreshCw className="h-4 w-4" />
      {t('board.refresh')}
    </button>
  );

  return (
    <AppPage className="space-y-5">
      <PageHeader title={t('board.title')} description={t('board.delayNote')} actions={refreshButton} />
      {error ? <ApiErrorAlert error={error} onDismiss={() => setError(null)} /> : null}
      <Card variant="bordered" padding="md">
        {loading ? (
          <Loading label={t('board.title')} />
        ) : codes && codes.length === 0 ? (
          <EmptyState title={t('board.empty')} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-secondary-text">
                  <th className="px-3 py-2">{t('board.col.code')}</th>
                  <th className="px-3 py-2">{t('board.col.name')}</th>
                  <th className="px-3 py-2 text-right">{t('board.col.price')}</th>
                  <th className="px-3 py-2 text-right">{t('board.col.change')}</th>
                  <th className="px-3 py-2 text-right">{t('board.col.volume')}</th>
                  <th className="px-3 py-2">{t('board.col.status')}</th>
                  <th className="px-3 py-2">{t('board.asOf')}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const q = item.quote;
                  return (
                    <tr
                      key={item.stockCode}
                      className="cursor-pointer border-b border-border/50 hover:bg-hover"
                      onClick={() => navigate('/', { state: { stockCode: item.stockCode } })}
                    >
                      <td className="px-3 py-2 font-mono">{item.stockCode}</td>
                      <td className="px-3 py-2">{q?.stockName ?? '—'}</td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {q ? q.currentPrice.toFixed(2) : '—'}
                      </td>
                      <td className={cn('px-3 py-2 text-right tabular-nums', changeClass(q?.changePercent))}>
                        {q ? formatSignedPct(q.changePercent) : '—'}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {q?.volume != null ? q.volume.toLocaleString() : '—'}
                      </td>
                      <td className="px-3 py-2">{badge(item)}</td>
                      <td className="px-3 py-2 text-xs text-secondary-text">
                        {q?.asOf ? formatDateTime(q.asOf) : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </AppPage>
  );
};

export default RealtimeBoardPage;
