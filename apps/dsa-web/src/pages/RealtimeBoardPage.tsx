import type React from 'react';
import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, LineChart as LineChartIcon, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
  stocksApi,
  type StockQuoteBatchItem,
  type TrendPoint,
  type TrendRange,
} from '../api/stocks';
import { systemConfigApi } from '../api/systemConfig';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import { ApiErrorAlert, AppPage, Card, EmptyState, Loading, PageHeader } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { formatSignedPct } from '../utils/portfolioFormat';
import { formatDateTime } from '../utils/format';
import { cn } from '../utils/cn';

const POLL_INTERVAL_MS = 30_000;
const CHUNK = 8; // 每批并发请求的代码数：分批并发刷新，慢的股票不挡快的

// 台股/A股涨跌色：红涨绿跌
function changeClass(value?: number | null): string {
  if (value == null || Number.isNaN(value) || value === 0) return 'text-secondary-text';
  return value > 0 ? 'text-red-500' : 'text-emerald-500';
}

type Freshness = 'live' | 'delayed' | 'unavailable';

function freshnessOf(item?: StockQuoteBatchItem): Freshness {
  if (!item || !item.quote) return 'unavailable';
  if (item.quote.source === 'shioaji' && item.quote.isStale === false) return 'live';
  return 'delayed';
}

// 内联走势图：自管 range + 数据；展开时按 code 懒加载
const TrendChart: React.FC<{ code: string }> = ({ code }) => {
  const { t } = useUiLanguage();
  const [range, setRange] = useState<TrendRange>('month');
  const [points, setPoints] = useState<TrendPoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void (async () => {
      setLoading(true);
      try {
        const p = await stocksApi.getTrend(code, range);
        if (active) setPoints(p);
      } catch {
        if (active) setPoints([]);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [code, range]);

  const ranges: TrendRange[] = ['day', 'month', 'year'];
  const up = points.length >= 2 && points[points.length - 1].price >= points[0].price;

  return (
    <div className="space-y-2 px-3 py-3">
      <div className="flex gap-1">
        {ranges.map((r) => (
          <button
            key={r}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setRange(r);
            }}
            className={cn(
              'rounded-md border px-2.5 py-0.5 text-xs',
              r === range
                ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]'
                : 'border-border text-secondary-text hover:bg-hover',
            )}
          >
            {t(`board.range.${r}` as 'board.range.day')}
          </button>
        ))}
      </div>
      {loading ? (
        <div className="py-8 text-center text-xs text-secondary-text">{t('board.trendLoading')}</div>
      ) : points.length === 0 ? (
        <div className="py-8 text-center text-xs text-secondary-text">{t('board.trendEmpty')}</div>
      ) : (
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <XAxis dataKey="t" tick={false} axisLine={false} height={4} />
            <YAxis
              domain={['auto', 'auto']}
              width={52}
              tick={{ fontSize: 11 }}
              tickFormatter={(v) => Number(v).toFixed(1)}
            />
            <Tooltip
              labelFormatter={(label) => formatDateTime(String(label))}
              formatter={(v) => [Number(v).toFixed(2), t('board.col.price')]}
            />
            <Line
              type="monotone"
              dataKey="price"
              dot={false}
              strokeWidth={1.5}
              stroke={up ? '#ef4444' : '#10b981'}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
};

const RealtimeBoardPage: React.FC = () => {
  const { t } = useUiLanguage();
  const navigate = useNavigate();
  const [codes, setCodes] = useState<string[] | null>(null);
  const [quotes, setQuotes] = useState<Record<string, StockQuoteBatchItem>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const codesRef = useRef<string[]>([]);
  const refreshSeqRef = useRef(0); // 世代守卫：丢弃旧轮询迟到的 chunk，避免覆盖更新的数据

  // 分批并发刷新：每批回来就只 merge 那几列（in-place），不整页清空、不等最慢的
  const refresh = useCallback(() => {
    const seq = ++refreshSeqRef.current;
    const cs = codesRef.current;
    for (let i = 0; i < cs.length; i += CHUNK) {
      const chunk = cs.slice(i, i + CHUNK);
      stocksApi
        .getQuotes(chunk)
        .then((items) => {
          if (seq !== refreshSeqRef.current) return; // 已有更新的刷新发起，丢弃迟到结果
          setQuotes((prev) => {
            const next = { ...prev };
            for (const it of items) next[it.stockCode] = it;
            return next;
          });
          setError(null);
        })
        .catch((err) => setError(getParsedApiError(err))); // 保留旧值，只提示错误
    }
  }, []);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const watchlist = await systemConfigApi.getWatchlist();
        if (!active) return;
        codesRef.current = watchlist;
        setCodes(watchlist);
        refresh();
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

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const badge = (item?: StockQuoteBatchItem) => {
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
        {kind === 'live' && item?.quote?.source ? ` · ${item.quote.source}` : null}
      </span>
    );
  };

  const refreshButton = (
    <button
      type="button"
      className="btn-secondary inline-flex items-center gap-2 text-sm"
      onClick={() => refresh()}
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
                  <th className="w-6 px-2 py-2" />
                  <th className="px-3 py-2">{t('board.col.code')}</th>
                  <th className="px-3 py-2">{t('board.col.name')}</th>
                  <th className="px-3 py-2 text-right">{t('board.col.price')}</th>
                  <th className="px-3 py-2 text-right">{t('board.col.change')}</th>
                  <th className="px-3 py-2 text-right">{t('board.col.volume')}</th>
                  <th className="px-3 py-2">{t('board.col.status')}</th>
                  <th className="px-3 py-2">{t('board.asOf')}</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {(codes ?? []).map((code) => {
                  const item = quotes[code];
                  const q = item?.quote;
                  const isOpen = expanded === code;
                  return (
                    <Fragment key={code}>
                      <tr
                        className="cursor-pointer border-b border-border/50 hover:bg-hover"
                        onClick={() => setExpanded(isOpen ? null : code)}
                      >
                        <td className="px-2 py-2 text-secondary-text">
                          {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        </td>
                        <td className="px-3 py-2 font-mono">{code}</td>
                        <td className="px-3 py-2">{q?.stockName ?? '—'}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{q ? q.currentPrice.toFixed(2) : '—'}</td>
                        <td className={cn('px-3 py-2 text-right tabular-nums', changeClass(q?.changePercent))}>
                          {q ? formatSignedPct(q.changePercent) : '—'}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {q?.volume != null ? q.volume.toLocaleString() : '—'}
                        </td>
                        <td className="px-3 py-2">{badge(item)}</td>
                        <td className="px-3 py-2 text-xs text-secondary-text">{q?.asOf ? formatDateTime(q.asOf) : '—'}</td>
                        <td className="px-3 py-2">
                          <button
                            type="button"
                            className="text-secondary-text hover:text-[hsl(var(--primary))]"
                            title={t('board.analyze')}
                            onClick={(e) => {
                              e.stopPropagation();
                              navigate('/', { state: { stockCode: code } });
                            }}
                          >
                            <LineChartIcon className="h-4 w-4" />
                          </button>
                        </td>
                      </tr>
                      {isOpen ? (
                        <tr className="border-b border-border/50 bg-base/40">
                          <td colSpan={9}>
                            <TrendChart code={code} />
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
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
