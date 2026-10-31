import { AlertBellLink } from '../components/alerts/AlertBellLink';
import type React from 'react';
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, LineChart as LineChartIcon, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
  stocksApi,
  type DossierSummary,
  type MarketIndex,
  type StockQuote,
  type StockQuoteBatchItem,
  type TrendPoint,
  type TrendRange,
} from '../api/stocks';
import { systemConfigApi } from '../api/systemConfig';
import { portfolioApi } from '../api/portfolio';
import { fundsApi } from '../api/funds';
import type { FundHoldingItem } from '../types/funds';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import { ApiErrorAlert, AppPage, Card, EmptyState, Loading, PageHeader, Tooltip as HintTooltip } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { formatSignedPct } from '../utils/portfolioFormat';
import { formatDateTime } from '../utils/format';
import { cn } from '../utils/cn';
import { isTwStockCode, stockCodeMatchKey } from '../utils/stockCode';
import { BoardDossierCell, BoardDossierPanel } from '../components/board/BoardDossier';
import { marketToneClass } from '../utils/marketTone';

const POLL_INTERVAL_MS = 30_000;
// 看板代碼分市場：只有明確的台股／美股格式才參與閘門，其餘（.T、.HK、.KS、A 股…）歸 other 照常輪詢
const boardMarketOf = (c: string): 'tw' | 'us' | 'other' =>
  isTwStockCode(c) ? 'tw' : /^[A-Za-z]{1,5}([.-][A-Za-z]|\.US)?$/i.test(c) ? 'us' : 'other';
const MARKET_STATUS_TTL_MS = 5 * 60_000; // 休市時只每 5 分鐘問一次後端開盤狀態，不打報價
const DOSSIER_CHUNK = 50; // 與後端 MAX_BATCH_CODES 一致
const DOSSIER_REFRESH_MS = 15 * 60_000; // 摘要是日資料，盤中不必跟 30 秒報價一起抓
const SCOPE_STORAGE_KEY = 'dsa.board.scope';

type Scope = 'all' | 'watch' | 'holdings';
const SCOPES: Scope[] = ['all', 'watch', 'holdings'];

// 帳本持股（跨帳戶合併同一代碼）：成本以股數加權，用來對即時價算未實現損益。
// key 一律是 stockCodeMatchKey（正規化後整體轉大寫）：自選清單是原樣字串（可能小寫），帳本代碼也不保證是正規形式，兩邊比對都要先過它
type Holding = { quantity: number; avgCost: number; currency: string; accounts: string[] };

function readScope(): Scope {
  try {
    const v = window.localStorage.getItem(SCOPE_STORAGE_KEY);
    return v === 'watch' || v === 'holdings' ? v : 'all';
  } catch {
    return 'all';
  }
}

function writeScope(scope: Scope) {
  try {
    window.localStorage.setItem(SCOPE_STORAGE_KEY, scope);
  } catch {
    /* 偏好記不住不影響顯示 */
  }
}
const CHUNK = 8; // 每批并发请求的代码数：分批并发刷新，慢的股票不挡快的

const changeClass = (value?: number | null): string => marketToneClass(value);

// 均价多空分界：站上均价偏多(红)、跌破偏空(绿)。台股当沖盘中第一条纪律。
function avgClass(price?: number | null, avg?: number | null): string {
  if (price == null || avg == null || avg === 0) return 'text-secondary-text';
  return marketToneClass(price - avg);
}

type Freshness = 'live' | 'delayed' | 'unavailable';

function freshnessOf(item?: StockQuoteBatchItem): Freshness {
  if (!item || !item.quote) return 'unavailable';
  if (item.quote.source === 'shioaji' && item.quote.isStale === false) return 'live';
  return 'delayed';
}

// 大盤指數條的時效標示：照後端回的 source 分，不能一律寫延遲（Shioaji 有設定時指數是即時快照）
type IndexSourceKind = 'live' | 'close' | 'delayed';
const INDEX_HINT_KEY = {
  live: 'board.indices.liveHint',
  close: 'board.indices.closeHint',
  delayed: 'board.indices.delay',
} as const;

function indexSourceTag(idx?: MarketIndex): { kind: IndexSourceKind; asOf: string | null } {
  if (idx?.source === 'shioaji') return { kind: 'live', asOf: idx.asOf };
  if (idx?.source === 'official_close') return { kind: 'close', asOf: idx.asOf };
  return { kind: 'delayed', asOf: null };
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
  const [watchCodes, setWatchCodes] = useState<string[]>([]);
  const [holdings, setHoldings] = useState<Record<string, Holding>>({});
  const [holdingsFailed, setHoldingsFailed] = useState(false);
  const [funds, setFunds] = useState<FundHoldingItem[]>([]);
  const [scope, setScope] = useState<Scope>(readScope);
  const [quotes, setQuotes] = useState<Record<string, StockQuoteBatchItem>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [dossier, setDossier] = useState<Record<string, DossierSummary | null>>({});
  const [levelAlertsEnabled, setLevelAlertsEnabled] = useState(false);
  const [dossierTick, setDossierTick] = useState(0); // 遞增即重抓四維度摘要（手動刷新／15 分鐘）
  const [indices, setIndices] = useState<MarketIndex[]>([]);
  const codesRef = useRef<string[]>([]);
  // 展開列是 colSpan 整張表寬（手機上被欄位撐到 1000px 以上）：內容改成黏在左邊、寬度跟著可視的捲動框，
  // 不用橫滑整張表才找得到撐壓、結論卡與「四維度分析」按鈕
  const tableBoxRef = useRef<HTMLDivElement | null>(null);
  const [tableBoxWidth, setTableBoxWidth] = useState<number | null>(null);
  const refreshSeqRef = useRef(0);
  // 世代守卫（逐代码）：只丢弃「之后又被别的刷新抓过」的代码的迟到结果；子集轮询不会作废没涵盖的代码
  const codeSeqRef = useRef<Map<string, number>>(new Map());

  // 分批并发刷新：每批回来就只 merge 那几列（in-place），不整页清空、不等最慢的
  // 手動刷新／初次載入全抓；輪詢時傳入已濾掉休市市場的代碼，並以 withIndices 決定要不要抓台股指數
  const refresh = useCallback((targetCodes?: string[], withIndices = true) => {
    // 大盘指数（盯盘辅助，失败不影响个股；沿用同一刷新 timer，不另开）
    if (withIndices) {
      stocksApi
        .getIndices('tw')
        .then(setIndices)
        .catch(() => {
          /* 指数为辅助资料，失败保留旧值、不报错 */
        });
    }
    const seq = ++refreshSeqRef.current;
    const cs = targetCodes ?? codesRef.current;
    for (const c of cs) codeSeqRef.current.set(stockCodeMatchKey(c), seq);
    for (let i = 0; i < cs.length; i += CHUNK) {
      const chunk = cs.slice(i, i + CHUNK);
      stocksApi
        .getQuotes(chunk)
        .then((items) => {
          const fresh = items.filter((it) => codeSeqRef.current.get(stockCodeMatchKey(it.stockCode)) === seq);
          if (!fresh.length) return; // 这些代码已有更新的刷新发起，丢弃迟到结果
          setQuotes((prev) => {
            const next = { ...prev };
            for (const it of fresh) next[it.stockCode] = it;
            return next;
          });
          setError(null);
        })
        .catch((err) => setError(getParsedApiError(err))); // 保留旧值，只提示错误
    }
  }, []);

  // 自選清單（STOCK_LIST）＋帳本持股（全部帳戶，含美股複委託）＋基金持倉；任一來源失敗不擋其他兩個
  useEffect(() => {
    let active = true;
    void (async () => {
      const [watch, snap, fundList] = await Promise.allSettled([
        systemConfigApi.getWatchlist(),
        portfolioApi.getSnapshot({ includeRealtime: false }),
        fundsApi.listHoldings(),
      ]);
      if (!active) return;
      if (watch.status === 'fulfilled') setWatchCodes(watch.value);
      else setError(getParsedApiError(watch.reason));
      if (snap.status === 'fulfilled') {
        const merged: Record<string, Holding> = {};
        for (const acc of snap.value.accounts) {
          for (const p of acc.positions) {
            if (!(p.quantity > 0)) continue;
            const key = stockCodeMatchKey(p.symbol);
            const h = merged[key];
            if (h) {
              const qty = h.quantity + p.quantity;
              h.avgCost = (h.avgCost * h.quantity + p.avgCost * p.quantity) / qty;
              h.quantity = qty;
              if (!h.accounts.includes(acc.accountName)) h.accounts.push(acc.accountName);
            } else {
              merged[key] = { quantity: p.quantity, avgCost: p.avgCost, currency: p.currency, accounts: [acc.accountName] };
            }
          }
        }
        setHoldings(merged);
      } else {
        setHoldingsFailed(true);
      }
      if (fundList.status === 'fulfilled') setFunds(fundList.value.items);
      setLoading(false);
    })();
    return () => {
      active = false;
    };
  }, []);

  // 顯示清單隨範圍切換；輪詢只抓畫面上的代碼
  const codes = useMemo<string[] | null>(() => {
    if (loading) return null;
    const held = Object.keys(holdings).sort((a, b) => a.localeCompare(b));
    // 自選寫成 `2330.tw`／`nvda`、帳本是 `2330.TW`／`NVDA` 也是同一檔：比對前兩邊都轉成 match key，列上沿用自選的寫法
    const watchSet = new Set(watchCodes.map(stockCodeMatchKey));
    if (scope === 'watch') return watchCodes;
    if (scope === 'holdings') return held;
    return [...watchCodes, ...held.filter((c) => !watchSet.has(c))];
  }, [loading, scope, watchCodes, holdings]);

  useEffect(() => {
    if (!codes) return;
    codesRef.current = codes;
    refresh();
  }, [codes, refresh]);

  // 四維度摘要在清單改變、手動刷新、每 15 分鐘時重抓（日資料，不跟 30 秒報價輪詢）；只送台股、失敗不影響報價
  // key 一律正規化：後端回大寫代碼，自選清單可能是小寫
  useEffect(() => {
    const tw = (codes ?? []).filter(isTwStockCode);
    let active = true;
    for (let i = 0; i < tw.length; i += DOSSIER_CHUNK) {
      stocksApi
        .getDossierSummaries(tw.slice(i, i + DOSSIER_CHUNK))
        .then(({ items, levelAlertsEnabled: enabled }) => {
          if (!active) return;
          setLevelAlertsEnabled(enabled);
          setDossier((prev) => {
            const next = { ...prev };
            for (const it of items) next[stockCodeMatchKey(it.stockCode)] = it.summary;
            return next;
          });
        })
        .catch(() => {
          /* 摘要是輔助資料，失敗只是該欄顯示「—」 */
        });
    }
    return () => {
      active = false;
    };
  }, [codes, dossierTick]);

  useEffect(() => {
    const box = tableBoxRef.current;
    if (!box) return;
    const measure = () => setTableBoxWidth(box.clientWidth || null);
    measure();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure);
      return () => window.removeEventListener('resize', measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    return () => observer.disconnect();
  }, [loading, codes]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) setDossierTick((n) => n + 1);
    }, DOSSIER_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let status: Record<string, boolean> = {}; // 缺值＝當開盤
    let checkedAt = Date.now(); // 進頁面的首次刷新已在別處發出
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      const run = () => {
        // 逐市場濾掉休市的代碼；台股指數只看台股是否開盤
        const live = (codesRef.current ?? []).filter((c) => status[boardMarketOf(c)] !== false);
        const withIndices = status.tw !== false;
        if (live.length || withIndices) refresh(live, withIndices);
      };
      if (Date.now() - checkedAt < MARKET_STATUS_TTL_MS) return run();
      checkedAt = Date.now();
      // 台股永遠帶上（指數列依它決定）；other（日港陸韓等）後端不分流，一律當開盤
      const markets = Array.from(new Set(['tw', ...(codesRef.current ?? []).map(boardMarketOf)])).filter((m) => m !== 'other');
      stocksApi
        .getMarketStatus(markets)
        .catch(() => ({}) as Record<string, boolean>) // 查不到就當開盤，寧可多打不凍結看板
        .then((m) => {
          status = m;
          run();
        });
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
      <span className={cn('inline-flex whitespace-nowrap rounded-md border px-2 py-0.5 text-xs', styles[kind])}>
        {label}
        {kind === 'live' && item?.quote?.source ? ` · ${item.quote.source}` : null}
      </span>
    );
  };

  // 距涨跌停板：触及板 → 实心标注；未触及 → 显示距较近一侧板的百分比（台股 ±10% 当沖最先看的盘口）
  const limitInfo = (q?: StockQuote | null): { text: string; cls: string } | null => {
    if (!q || q.limitUp == null || q.limitDown == null || !q.currentPrice) return null;
    const price = q.currentPrice;
    if (price >= q.limitUp) return { text: t('board.limit.hitUp'), cls: 'text-market-up font-medium' };
    if (price <= q.limitDown) return { text: t('board.limit.hitDown'), cls: 'text-market-down font-medium' };
    const toUp = ((q.limitUp - price) / price) * 100;
    const toDown = ((price - q.limitDown) / price) * 100;
    // 离板远（两侧都 >3%）时不显示——对当冲只有接近板才有意义，常态显示是噪音。
    if (toUp > LIMIT_NEAR_PCT && toDown > LIMIT_NEAR_PCT) return null;
    return toUp <= toDown
      ? { text: `${t('board.limit.toUp')} ${toUp.toFixed(1)}%`, cls: 'text-market-up' }
      : { text: `${t('board.limit.toDown')} ${toDown.toFixed(1)}%`, cls: 'text-market-down' };
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
        ? { text: t('board.detail.tickBuy'), cls: 'text-market-up' }
        : q.lastTickType === 2
          ? { text: t('board.detail.tickSell'), cls: 'text-market-down' }
          : { text: t('board.detail.tickNeutral'), cls: 'text-secondary-text' };
    const fmt = (v?: number | null) => (v != null ? v.toFixed(2) : '—');
    const lot = (v?: number | null) => (v != null ? v.toLocaleString() : '—');
    const cells: Array<{ label: string; value: React.ReactNode } | null> = [
      q.bestBid != null
        ? {
            label: t('board.detail.bid'),
            value: (
              <span className="text-market-down">
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
              <span className="text-market-up">
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
      q.limitUp != null ? { label: t('board.detail.limitUp'), value: <span className="text-market-up">{fmt(q.limitUp)}</span> } : null,
      q.limitDown != null ? { label: t('board.detail.limitDown'), value: <span className="text-market-down">{fmt(q.limitDown)}</span> } : null,
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

  // 持股欄：股數＋以即時價算的未實現損益（%），成本用帳本跨帳戶加權平均
  const positionCell = (code: string, q?: StockQuote | null) => {
    const h = holdings[stockCodeMatchKey(code)];
    if (!h) return <span className="text-secondary-text">—</span>;
    const price = q?.currentPrice;
    const pnl = price ? (price - h.avgCost) * h.quantity : null;
    const pct = price && h.avgCost ? (price / h.avgCost - 1) * 100 : null;
    return (
      <HintTooltip content={h.accounts.join('、')}>
        <div>
          <div>{h.quantity.toLocaleString()}</div>
          <div className={cn('text-[10px]', changeClass(pnl))}>
            {pnl != null ? `${pnl > 0 ? '+' : ''}${Math.round(pnl).toLocaleString()} ${h.currency}` : '—'}
            {pct != null ? ` (${formatSignedPct(pct)})` : ''}
          </div>
        </div>
      </HintTooltip>
    );
  };

  const fundsCard =
    scope !== 'watch' && funds.length > 0 ? (
      <Card variant="bordered" padding="md">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-sm font-medium">{t('board.funds.title')}</span>
          <button type="button" className="text-xs text-[hsl(var(--primary))] hover:underline" onClick={() => navigate('/funds')}>
            {t('board.funds.more')}
          </button>
        </div>
        <div className="mb-2 text-[11px] text-secondary-text">{t('board.funds.note')}</div>
        <div className="flex flex-wrap gap-x-8 gap-y-2">
          {funds.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => navigate(`/funds?fund=${encodeURIComponent(f.fundId)}`)}
              className="inline-flex items-baseline gap-2 text-left tabular-nums hover:text-[hsl(var(--primary))]"
            >
              <span className="text-sm">{f.fundName}</span>
              <span className="text-base font-medium">{f.nav != null ? f.nav.toFixed(2) : '—'}</span>
              <span className={cn('whitespace-nowrap text-xs', f.isStale ? 'text-warning' : 'text-secondary-text')}>{f.navDate ?? t('funds.noNav')}</span>
              <span className={cn('text-sm', changeClass(f.pnlPct))}>{f.pnlPct != null ? formatSignedPct(f.pnlPct) : '—'}</span>
            </button>
          ))}
        </div>
      </Card>
    ) : null;

  const refreshButton = (
    <button
      type="button"
      className="btn-secondary inline-flex items-center gap-2 text-sm"
      onClick={() => {
        refresh();
        setDossierTick((n) => n + 1);
      }}
    >
      <RefreshCw className="h-4 w-4" />
      {t('board.refresh')}
    </button>
  );

  return (
    <AppPage className="space-y-5">
      <PageHeader
        title={t('board.title')}
        description={t('board.delayNote')}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-lg border border-border p-0.5" role="group" aria-label={t('board.scope.label')}>
              {SCOPES.map((sc) => (
                <button
                  key={sc}
                  type="button"
                  aria-pressed={scope === sc}
                  onClick={() => {
                    setScope(sc);
                    writeScope(sc);
                  }}
                  className={cn(
                    'rounded-md px-2.5 py-1 text-xs',
                    scope === sc ? 'bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]' : 'text-secondary-text hover:bg-hover',
                  )}
                >
                  {t(`board.scope.${sc}` as 'board.scope.all')}
                </button>
              ))}
            </div>
            {refreshButton}
          </div>
        }
      />
      {holdingsFailed ? <div className="text-xs text-warning">{t('board.holdingsError')}</div> : null}
      {error ? <ApiErrorAlert error={error} onDismiss={() => setError(null)} /> : null}
      {indices.length > 0 ? (
        <Card variant="bordered" padding="md">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-sm font-medium">{t('board.indices.title')}</span>
            {(() => {
              const tag = indexSourceTag(indices[0]);
              const label =
                tag.kind === 'live'
                  ? `${t('board.source.live')}${tag.asOf ? ` · ${formatDateTime(tag.asOf)}` : ''}`
                  : tag.kind === 'close'
                    ? t('board.indices.close', { date: tag.asOf ?? '—' })
                    : t('board.source.delayed');
              const hint = t(INDEX_HINT_KEY[tag.kind]);
              return (
                <HintTooltip content={hint}>
                  <span className="text-xs text-secondary-text" aria-label={hint}>
                    {label}
                  </span>
                </HintTooltip>
              );
            })()}
          </div>
          <div className="flex flex-wrap gap-x-8 gap-y-2">
            {indices.map((idx) => (
              <div key={idx.code} className="inline-flex items-baseline gap-2 tabular-nums">
                <span className="text-sm text-secondary-text">{idx.name}</span>
                <span className="text-base font-medium">
                  {idx.current != null ? idx.current.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
                </span>
                <span className={cn('text-sm', changeClass(idx.changePct))}>
                  {idx.changePct != null ? formatSignedPct(idx.changePct) : '—'}
                </span>
              </div>
            ))}
          </div>
        </Card>
      ) : null}
      <Card variant="bordered" padding="md">
        {loading ? (
          <Loading label={t('board.title')} />
        ) : codes && codes.length === 0 ? (
          <EmptyState title={scope === 'holdings' ? t('board.emptyHoldings') : t('board.empty')} />
        ) : (
          <div ref={tableBoxRef} className="overflow-x-auto">
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
                  <th className="px-3 py-2 text-right">{t('board.col.position')}</th>
                  <th className="px-3 py-2">{t('board.col.dossier')}</th>
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
                        <td className="whitespace-nowrap px-3 py-2 font-mono">
                          {code}
                          <AlertBellLink code={code} className="ml-1 align-middle" />
                          {holdings[stockCodeMatchKey(code)] ? (
                            <span className="ml-1.5 inline-flex rounded border border-[hsl(var(--primary))]/30 px-1 py-0.5 align-middle font-sans text-[10px] text-[hsl(var(--primary))]">
                              {t('board.tag.holding')}
                            </span>
                          ) : null}
                        </td>
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
                        <td className="px-3 py-2 text-right tabular-nums">{positionCell(code, q)}</td>
                        <td className="px-3 py-2">
                          <BoardDossierCell summary={dossier[stockCodeMatchKey(code)]} price={q?.currentPrice} />
                        </td>
                        <td className="whitespace-nowrap px-3 py-2">{badge(item)}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-xs text-secondary-text">{q?.asOf ? formatDateTime(q.asOf) : '—'}</td>
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
                          <td colSpan={12} className="p-0">
                            <div
                              data-testid="board-expanded"
                              className="sticky left-0"
                              style={tableBoxWidth ? { width: tableBoxWidth } : undefined}
                            >
                              <BoardDossierPanel
                                code={code}
                                name={q?.stockName}
                                summary={dossier[stockCodeMatchKey(code)]}
                                price={q?.currentPrice}
                                levelAlertsEnabled={levelAlertsEnabled}
                              />
                              {quoteDetail(q)}
                              <TrendChart code={code} />
                            </div>
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
      {fundsCard}
    </AppPage>
  );
};

export default RealtimeBoardPage;
