import type React from 'react';
import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, LineChart as LineChartIcon, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
  stocksApi,
  type StockQuote,
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

// 均价多空分界：站上均价偏多(红)、跌破偏空(绿)。台股当沖盘中第一条纪律。
function avgClass(price?: number | null, avg?: number | null): string {
  if (price == null || avg == null || avg === 0) return 'text-secondary-text';
  if (price > avg) return 'text-red-500';
  if (price < avg) return 'text-emerald-500';
  return 'text-secondary-text';
}

type Freshness = 'live' | 'delayed' | 'unavailable';

function freshnessOf(item?: StockQuoteBatchItem): Freshness {
  if (!item || !item.quote) return 'unavailable';
  if (item.quote.source === 'shioaji' && item.quote.isStale === false) return 'live';
  return 'delayed';
}

// 内联走势图：自管 range + 数据；展开时按 code 懒加载
// 距涨跌停板：仅在距任一侧 <= 此百分比时显示（当冲接近板才有意义，常态显示是噪音）。
const LIMIT_NEAR_PCT = 3;

const _pad = (n: number) => String(n).padStart(2, '0');
// X 轴刻度：日→时:分、月→月/日、年→年/月。
const formatTrendTick = (raw: string, range: TrendRange): string => {
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  if (range === 'day') return `${_pad(d.getHours())}:${_pad(d.getMinutes())}`;
  if (range === 'month') return `${d.getMonth() + 1}/${d.getDate()}`;
  return `${d.getFullYear()}/${_pad(d.getMonth() + 1)}`;
};
// Tooltip 标签：日范围显示到分钟，月/年只到日期。
const formatTrendLabel = (raw: string, range: TrendRange): string => {
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  const date = `${d.getFullYear()}/${_pad(d.getMonth() + 1)}/${_pad(d.getDate())}`;
  return range === 'day' ? `${date} ${_pad(d.getHours())}:${_pad(d.getMinutes())}` : date;
};

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
            <XAxis
              dataKey="t"
              tick={{ fontSize: 10, fill: 'hsl(var(--secondary-text))' }}
              axisLine={false}
              tickLine={false}
              height={18}
              minTickGap={44}
              tickFormatter={(v) => formatTrendTick(String(v), range)}
            />
            <YAxis
              domain={['auto', 'auto']}
              width={52}
              tick={{ fontSize: 11 }}
              tickFormatter={(v) => Number(v).toFixed(1)}
            />
            <Tooltip
              labelFormatter={(label) => formatTrendLabel(String(label), range)}
              formatter={(v) => [Number(v).toFixed(2), t('board.col.price')]}
              contentStyle={{
                background: 'hsl(var(--popover))',
                border: '1px solid hsl(var(--border))',
                borderRadius: 8,
                fontSize: 12,
                padding: '6px 10px',
              }}
              labelStyle={{ color: 'hsl(var(--foreground))', fontWeight: 600, marginBottom: 2 }}
              itemStyle={{ color: 'hsl(var(--foreground))' }}
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

  // 距涨跌停板：触及板 → 实心标注；未触及 → 显示距较近一侧板的百分比（台股 ±10% 当沖最先看的盘口）
  const limitInfo = (q?: StockQuote | null): { text: string; cls: string } | null => {
    if (!q || q.limitUp == null || q.limitDown == null || !q.currentPrice) return null;
    const price = q.currentPrice;
    if (price >= q.limitUp) return { text: t('board.limit.hitUp'), cls: 'text-red-500 font-medium' };
    if (price <= q.limitDown) return { text: t('board.limit.hitDown'), cls: 'text-emerald-500 font-medium' };
    const toUp = ((q.limitUp - price) / price) * 100;
    const toDown = ((price - q.limitDown) / price) * 100;
    // 离板远（两侧都 >3%）时不显示——对当冲只有接近板才有意义，常态显示是噪音。
    if (toUp > LIMIT_NEAR_PCT && toDown > LIMIT_NEAR_PCT) return null;
    return toUp <= toDown
      ? { text: `${t('board.limit.toUp')} ${toUp.toFixed(1)}%`, cls: 'text-red-400' }
      : { text: `${t('board.limit.toDown')} ${toDown.toFixed(1)}%`, cls: 'text-emerald-400' };
  };

  // 现股当沖资格：仅在「非可双向当沖」时示警（Yes 为常态不显示，避免噪音）
  const dayTradeBadge = (q?: StockQuote | null) => {
    if (!q || !q.dayTrade || q.dayTrade === 'Yes') return null;
    const isNo = q.dayTrade === 'No';
    return (
      <span
        className={cn(
          'ml-1.5 inline-flex rounded border px-1.5 py-0.5 text-[10px]',
          isNo
            ? 'border-red-500/25 bg-red-500/10 text-red-600'
            : 'border-amber-500/25 bg-amber-500/10 text-amber-600',
        )}
      >
        {isNo ? t('board.dayTrade.no') : t('board.dayTrade.onlyBuy')}
      </span>
    );
  };

  // 展开明细：台股盘中盘口（委买委卖一档、最后一笔内外盘、均价、涨跌停价、量比、振幅）。仅在有值时渲染。
  const quoteDetail = (q?: StockQuote | null) => {
    if (!q) return null;
    const tick =
      q.lastTickType === 1
        ? { text: t('board.detail.tickBuy'), cls: 'text-red-500' }
        : q.lastTickType === 2
          ? { text: t('board.detail.tickSell'), cls: 'text-emerald-500' }
          : { text: t('board.detail.tickNeutral'), cls: 'text-secondary-text' };
    const fmt = (v?: number | null) => (v != null ? v.toFixed(2) : '—');
    const lot = (v?: number | null) => (v != null ? v.toLocaleString() : '—');
    const cells: Array<{ label: string; value: React.ReactNode } | null> = [
      q.bestBid != null
        ? {
            label: t('board.detail.bid'),
            value: (
              <span className="text-emerald-500">
                {fmt(q.bestBid)}
                <span className="ml-1 text-secondary-text">{lot(q.bestBidVolume)}</span>
              </span>
            ),
          }
        : null,
      q.bestAsk != null
        ? {
            label: t('board.detail.ask'),
            value: (
              <span className="text-red-500">
                {fmt(q.bestAsk)}
                <span className="ml-1 text-secondary-text">{lot(q.bestAskVolume)}</span>
              </span>
            ),
          }
        : null,
      q.lastTickType != null ? { label: t('board.detail.tick'), value: <span className={tick.cls}>{tick.text}</span> } : null,
      q.averagePrice != null
        ? { label: t('board.detail.avg'), value: <span className={avgClass(q.currentPrice, q.averagePrice)}>{fmt(q.averagePrice)}</span> }
        : null,
      q.limitUp != null ? { label: t('board.detail.limitUp'), value: <span className="text-red-500">{fmt(q.limitUp)}</span> } : null,
      q.limitDown != null ? { label: t('board.detail.limitDown'), value: <span className="text-emerald-500">{fmt(q.limitDown)}</span> } : null,
      q.volumeRatio != null ? { label: t('board.detail.volumeRatio'), value: q.volumeRatio.toFixed(2) } : null,
      q.amplitude != null ? { label: t('board.detail.amplitude'), value: `${q.amplitude.toFixed(2)}%` } : null,
    ];
    const visible = cells.filter((c): c is { label: string; value: React.ReactNode } => c !== null);
    if (visible.length === 0) return null;
    return (
      <div className="px-3 pt-3">
        <div className="mb-1 text-xs font-medium text-secondary-text">{t('board.detail.title')}</div>
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm tabular-nums">
          {visible.map((c) => (
            <span key={c.label} className="inline-flex items-baseline gap-1">
              <span className="text-xs text-secondary-text">{c.label}</span>
              {c.value}
            </span>
          ))}
        </div>
        {q.volumeRatio != null ? (
          <div className="mt-1 text-[10px] text-secondary-text">{t('board.detail.volumeRatioHint')}</div>
        ) : null}
      </div>
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
                  <th className="px-3 py-2 text-right">{t('board.col.avg')}</th>
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
                        <td className="px-3 py-2">
                          {q?.stockName ?? '—'}
                          {dayTradeBadge(q)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          <div>{q ? q.currentPrice.toFixed(2) : '—'}</div>
                          {(() => {
                            const li = limitInfo(q);
                            return li ? <div className={cn('text-[10px]', li.cls)}>{li.text}</div> : null;
                          })()}
                        </td>
                        <td className={cn('px-3 py-2 text-right tabular-nums', changeClass(q?.changePercent))}>
                          {q ? formatSignedPct(q.changePercent) : '—'}
                        </td>
                        <td className={cn('px-3 py-2 text-right tabular-nums', avgClass(q?.currentPrice, q?.averagePrice))}>
                          {q?.averagePrice != null ? q.averagePrice.toFixed(2) : '—'}
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
                            aria-label={t('board.analyze')}
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
                          <td colSpan={10}>
                            {quoteDetail(q)}
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
