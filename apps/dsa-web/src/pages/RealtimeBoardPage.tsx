import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
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
import { historyApi } from '../api/history';
import { portfolioApi } from '../api/portfolio';
import { fundsApi } from '../api/funds';
import type { FundHoldingItem } from '../types/funds';
import type { PortfolioAccountSnapshot } from '../types/portfolio';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import {
  ApiErrorAlert,
  AppPage,
  Button,
  Card,
  DataTable,
  EmptyState,
  FilterBar,
  Input,
  Loading,
  Metric,
  MetricGroup,
  PageHeader,
  Segmented,
  Tooltip as HintTooltip,
  type DataTableColumn,
  type SortState,
} from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { useStockIndex } from '../hooks/useStockIndex';
import { useMarketIndexStore, type MarketIndexRegion } from '../stores/marketIndexStore';
import { formatDateTime, formatNumber, formatPercent, formatPrice, NO_VALUE } from '../utils/format';
import { cn } from '../utils/cn';
import { isTwStockCode, stockCodeMatchKey } from '../utils/stockCode';
import { BoardDossierCell, BoardDossierPanel } from '../components/board/BoardDossier';
import { FinancialsPanel } from '../components/report/FinancialsPanel';
import { marketToneClass } from '../utils/marketTone';
import { formatUiText } from '../i18n/uiText';
import { BOARD_TEXT } from '../locales/boardText';

const POLL_INTERVAL_MS = 30_000;
// 看板代碼分市場：只有明確的台股／美股格式才參與閘門，其餘（.T、.HK、.KS、A 股…）歸 other 照常輪詢
const boardMarketOf = (c: string): 'tw' | 'us' | 'other' =>
  isTwStockCode(c) ? 'tw' : /^[A-Za-z]{1,5}([.-][A-Za-z]|\.US)?$/i.test(c) ? 'us' : 'other';
const MARKET_STATUS_TTL_MS = 5 * 60_000; // 休市時只每 5 分鐘問一次後端開盤狀態，不打報價
const DOSSIER_CHUNK = 50; // 與後端 MAX_BATCH_CODES 一致
const DOSSIER_REFRESH_MS = 15 * 60_000; // 摘要是日資料，盤中不必跟 30 秒報價一起抓
const OVERVIEW_REFRESH_MS = 5 * 60_000; // 帳戶總覽要帶即時價重算帳本，比報價輪詢重，不跟 30 秒
const SPARK_REFRESH_MS = 3 * 60_000; // 與後端分時快取 TTL 相同，再密也只會拿到同一份
const SCOPE_STORAGE_KEY = 'dsa.board.scope';
const SORT_STORAGE_KEY = 'dsa.board.sort';
const SPARK_STORAGE_KEY = 'dsa.board.spark';
const ATTENTION_MOVE_PCT = 5; // 單日變動超過這個幅度才進「需注意」，常態波動是噪音
const ATTENTION_MAX = 5; // 膠囊最多顯示幾個，其餘收成「還有 N 檔」
const HIGHLIGHT_MS = 1500; // 從需注意跳過去後高亮多久
const DESKTOP_MEDIA_QUERY = '(min-width: 768px)'; // 與 DataTable 的 md 斷點一致

type Scope = 'all' | 'watch' | 'holdings';
const SCOPES: Scope[] = ['all', 'watch', 'holdings'];
const INDEX_REGIONS: MarketIndexRegion[] = ['tw', 'us'];

// 帳本持股（跨帳戶合併同一代碼）：成本以股數加權，用來對即時價算未實現損益。
// key 一律是 stockCodeMatchKey（正規化後整體轉大寫）：自選清單是原樣字串（可能小寫），帳本代碼也不保證是正規形式，兩邊比對都要先過它
type Holding = { quantity: number; avgCost: number; currency: string; accounts: string[]; name?: string | null };

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

function readSort(): SortState | null {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(SORT_STORAGE_KEY) ?? 'null') as Partial<SortState> | null;
    return parsed && typeof parsed.key === 'string' && (parsed.direction === 'asc' || parsed.direction === 'desc')
      ? { key: parsed.key, direction: parsed.direction }
      : null;
  } catch {
    return null;
  }
}

function writeSort(sort: SortState) {
  try {
    window.localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify(sort));
  } catch {
    /* 偏好記不住不影響顯示 */
  }
}

function readSparkEnabled(): boolean {
  try {
    return window.localStorage.getItem(SPARK_STORAGE_KEY) !== 'off';
  } catch {
    return true;
  }
}

function writeSparkEnabled(enabled: boolean) {
  try {
    window.localStorage.setItem(SPARK_STORAGE_KEY, enabled ? 'on' : 'off');
  } catch {
    /* 偏好記不住不影響顯示 */
  }
}

// 迷你分時只在桌機畫（手機卡片沒有這欄），手機就不要花這份 kbars 配額
const isDesktopViewport = () =>
  typeof window.matchMedia === 'function' ? window.matchMedia(DESKTOP_MEDIA_QUERY).matches : true;

const CHUNK = 8; // 每批並發請求的代號數：分批更新，慢的股票不擋快的

const changeClass = (value?: number | null): string => marketToneClass(value);

const signedNumber = (value?: number | null, digits?: number): string => {
  const text = formatNumber(value, digits);
  return value != null && value > 0 && /[1-9]/.test(text) ? `+${text}` : text;
};

// 報價缺值時後端的 current_price 是 0，那不是真實讀數
const hasPrice = (q?: StockQuote | null): q is StockQuote => Boolean(q && q.currentPrice > 0);

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

// 展開區左欄：預設當日走勢，有昨收就畫基準線，線色也以昨收為準
const TrendChart: React.FC<{ code: string; prevClose?: number | null }> = ({ code, prevClose }) => {
  const { t } = useUiLanguage();
  const [range, setRange] = useState<TrendRange>('day');
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
  const baseline = range === 'day' && prevClose ? prevClose : null;
  const up = points.length >= 1 && points[points.length - 1].price >= (baseline ?? points[0].price);

  return (
    <div className="min-w-0 space-y-2 px-3 py-3">
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
            {baseline != null ? (
              <ReferenceLine
                y={baseline}
                stroke="hsl(var(--secondary-text))"
                strokeDasharray="4 3"
                label={{ value: t('board.detail.prevClose'), position: 'insideTopRight', fontSize: 10, fill: 'hsl(var(--secondary-text))' }}
              />
            ) : null}
            <Line
              type="monotone"
              dataKey="price"
              dot={false}
              strokeWidth={1.5}
              stroke={up ? 'var(--market-up)' : 'var(--market-down)'}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
};

const SPARK_WIDTH = 80;
const SPARK_HEIGHT = 28;

// 迷你分時用純 SVG：一頁可能幾十列，不值得每列掛一個 recharts。沒有資料就留白，不畫假線
const Sparkline: React.FC<{ points?: TrendPoint[]; prevClose?: number | null; label: string }> = ({ points, prevClose, label }) => {
  if (!points || points.length < 2) {
    return <span className="text-secondary-text" data-testid="board-spark-empty">{NO_VALUE}</span>;
  }
  const prices = points.map((p) => p.price);
  const baseline = prevClose && prevClose > 0 ? prevClose : prices[0];
  const min = Math.min(...prices, baseline);
  const max = Math.max(...prices, baseline);
  const spread = max - min || 1;
  const x = (i: number) => (i / (points.length - 1)) * (SPARK_WIDTH - 2) + 1;
  const y = (v: number) => SPARK_HEIGHT - 2 - ((v - min) / spread) * (SPARK_HEIGHT - 4);
  const path = prices.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const last = prices[prices.length - 1];
  return (
    <svg width={SPARK_WIDTH} height={SPARK_HEIGHT} viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`} role="img" aria-label={label} data-testid="board-spark">
      <line x1={0} x2={SPARK_WIDTH} y1={y(baseline)} y2={y(baseline)} stroke="hsl(var(--secondary-text))" strokeWidth={0.5} strokeDasharray="2 2" />
      <polyline points={path} fill="none" strokeWidth={1.25} stroke={last >= baseline ? 'var(--market-up)' : 'var(--market-down)'} />
    </svg>
  );
};

type BoardRow = {
  code: string;
  key: string;
  item?: StockQuoteBatchItem;
  q?: StockQuote | null;
  name: string | null;
  holding?: Holding;
  dossier?: DossierSummary | null;
  currency?: string;
};

type SectionId = 'holdingsTw' | 'holdingsUs' | 'watch';
const SECTION_ORDER: SectionId[] = ['holdingsTw', 'holdingsUs', 'watch'];

const unrealizedPnl = (row: BoardRow): number | null =>
  row.holding && hasPrice(row.q) ? (row.q.currentPrice - row.holding.avgCost) * row.holding.quantity : null;
const holdingPct = (row: BoardRow): number | null =>
  row.holding?.avgCost && hasPrice(row.q) ? (row.q.currentPrice / row.holding.avgCost - 1) * 100 : null;
const avgDeviationPct = (q?: StockQuote | null): number | null =>
  hasPrice(q) && q.averagePrice ? (q.currentPrice / q.averagePrice - 1) * 100 : null;

const SORT_VALUE: Record<string, (row: BoardRow) => number | string | null | undefined> = {
  stock: (row) => row.name ?? row.code,
  price: (row) => (hasPrice(row.q) ? row.q.currentPrice : null),
  change: (row) => row.q?.change,
  changePct: (row) => row.q?.changePercent,
  avg: (row) => avgDeviationPct(row.q),
  volume: (row) => row.q?.volume,
  quantity: (row) => row.holding?.quantity,
  pnl: (row) => unrealizedPnl(row),
};

// 沒有讀數的一律排最後，不論升降冪：缺值不是最小也不是最大
function sortRows(rows: BoardRow[], sort: SortState | null): BoardRow[] {
  const read = sort ? SORT_VALUE[sort.key] : undefined;
  if (!sort || !read) return rows;
  const factor = sort.direction === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = read(a);
    const bv = read(b);
    if (av == null) return bv == null ? 0 : 1;
    if (bv == null) return -1;
    if (typeof av === 'string' || typeof bv === 'string') return factor * String(av).localeCompare(String(bv));
    return factor * (av - bv);
  });
}

type CurrencyTotal = { currency: string; dayPnl: number | null; unrealized: number | null };

// 今日損益的唯一來源是帳本的 day_pnl；同幣別才相加，任一帳戶算不出就整組沒有讀數，不拿部分合計充數
function totalsByCurrency(accounts: PortfolioAccountSnapshot[]): CurrencyTotal[] {
  const totals = new Map<string, CurrencyTotal>();
  for (const account of accounts) {
    const currency = account.baseCurrency;
    const entry = totals.get(currency) ?? { currency, dayPnl: 0, unrealized: 0 };
    entry.dayPnl = entry.dayPnl == null || account.dayPnl == null ? null : entry.dayPnl + account.dayPnl;
    entry.unrealized = entry.unrealized == null || account.unrealizedPnl == null ? null : entry.unrealized + account.unrealizedPnl;
    totals.set(currency, entry);
  }
  return [...totals.values()];
}

const CURRENCY_LABEL: Record<string, string> = { TWD: 'NT$', USD: 'US$' };

// 跨帳戶合併同一代碼的持股；股數 0（已出清）不算
function mergeHoldings(accounts: PortfolioAccountSnapshot[]): Record<string, Holding> {
  const merged: Record<string, Holding> = {};
  for (const acc of accounts) {
    for (const p of acc.positions) {
      if (!(p.quantity > 0)) continue;
      const key = stockCodeMatchKey(p.symbol);
      const h = merged[key];
      if (h) {
        const qty = h.quantity + p.quantity;
        h.avgCost = (h.avgCost * h.quantity + p.avgCost * p.quantity) / qty;
        h.quantity = qty;
        h.name = h.name ?? p.name;
        if (!h.accounts.includes(acc.accountName)) h.accounts.push(acc.accountName);
      } else {
        merged[key] = { quantity: p.quantity, avgCost: p.avgCost, currency: p.currency, accounts: [acc.accountName], name: p.name };
      }
    }
  }
  return merged;
}

const formatClock = (iso: string): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : `${_pad(d.getHours())}:${_pad(d.getMinutes())}`;
};

const RealtimeBoardPage: React.FC = () => {
  const { t, language } = useUiLanguage();
  const bt = BOARD_TEXT[language] ?? BOARD_TEXT.zh;
  const navigate = useNavigate();
  const [watchCodes, setWatchCodes] = useState<string[]>([]);
  const [holdings, setHoldings] = useState<Record<string, Holding>>({});
  const [holdingsFailed, setHoldingsFailed] = useState(false);
  const [funds, setFunds] = useState<FundHoldingItem[]>([]);
  const [scope, setScope] = useState<Scope>(readScope);
  const [sort, setSort] = useState<SortState | null>(readSort);
  const [filter, setFilter] = useState('');
  const [sparkEnabled, setSparkEnabled] = useState(readSparkEnabled);
  const [sparks, setSparks] = useState<Record<string, TrendPoint[]>>({});
  const [quotes, setQuotes] = useState<Record<string, StockQuoteBatchItem>>({});
  // 報價請求失敗的代碼：漲跌家數的「載入中 N/M」要把它們算成已回來，否則會一直卡在載入中
  const [quoteFailed, setQuoteFailed] = useState<Record<string, true>>({});
  const [flashes, setFlashes] = useState<Record<string, { dir: 'up' | 'down'; seq: number }>>({});
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [marketOpen, setMarketOpen] = useState<Record<string, boolean>>({});
  const [overview, setOverview] = useState<CurrencyTotal[]>([]);
  // 自選與帳本各自回來就先畫：自選一到就打報價，持股等帳本快照回來再補一批
  const [watchSettled, setWatchSettled] = useState(false);
  const [holdingsSettled, setHoldingsSettled] = useState(false);
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const highlightTimerRef = useRef<number | null>(null);
  const holdingsLoadedRef = useRef(false);
  const aliveRef = useRef(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [dossier, setDossier] = useState<Record<string, DossierSummary | null>>({});
  const [levelAlertsEnabled, setLevelAlertsEnabled] = useState(false);
  const [dossierTick, setDossierTick] = useState(0); // 遞增即重抓四維度摘要（手動刷新／15 分鐘）
  const [overviewTick, setOverviewTick] = useState(0);
  const [sparkTick, setSparkTick] = useState(0);
  const indexRegionStates = useMarketIndexStore((state) => state.regions);
  const loadIndices = useMarketIndexStore((state) => state.load);
  const { index: stockIndex } = useStockIndex();
  const codesRef = useRef<string[]>([]);
  const quotesRef = useRef<Record<string, StockQuoteBatchItem>>({});
  const flashSeqRef = useRef(0);
  const refreshSeqRef = useRef(0);
  // 世代守卫（逐代码）：只丢弃「之后又被别的刷新抓过」的代码的迟到结果；子集轮询不会作废没涵盖的代码
  const codeSeqRef = useRef<Map<string, number>>(new Map());

  // 分批并发刷新：每批回来就只 merge 那几列（in-place），不整页清空、不等最慢的
  // 手動刷新／初次載入全抓；輪詢時傳入已濾掉休市市場的代碼，並以 indexRegions 決定要抓哪些市場的指數
  const refresh = useCallback((targetCodes?: string[], indexRegions: MarketIndexRegion[] = INDEX_REGIONS, forceIndices = false) => {
    // 大盘指数（盯盘辅助，失败不影响个股；沿用同一刷新 timer，不另开）
    if (indexRegions.length > 0) void loadIndices(indexRegions, { force: forceIndices });
    const seq = ++refreshSeqRef.current;
    const cs = targetCodes ?? codesRef.current;
    for (const c of cs) codeSeqRef.current.set(stockCodeMatchKey(c), seq);
    for (let i = 0; i < cs.length; i += CHUNK) {
      const chunk = cs.slice(i, i + CHUNK);
      stocksApi
        .getQuotes(chunk)
        .then((items) => {
          const fresh = items.filter((it) => codeSeqRef.current.get(stockCodeMatchKey(it.stockCode)) === seq);
          if (!fresh.length) return; // 這些代號已有更新的請求，丟棄遲到結果
          const changed: Record<string, { dir: 'up' | 'down'; seq: number }> = {};
          for (const it of fresh) {
            const before = quotesRef.current[it.stockCode]?.quote?.currentPrice;
            const after = it.quote?.currentPrice;
            if (before && after && before !== after) {
              changed[it.stockCode] = { dir: after > before ? 'up' : 'down', seq: ++flashSeqRef.current };
            }
            quotesRef.current[it.stockCode] = it;
          }
          if (Object.keys(changed).length > 0) setFlashes((prev) => ({ ...prev, ...changed }));
          setQuotes((prev) => {
            const next = { ...prev };
            for (const it of fresh) next[it.stockCode] = it;
            return next;
          });
          setUpdatedAt(new Date().toISOString());
          setError(null);
        })
        .catch((err) => {
          setError(getParsedApiError(err)); // 保留旧值，只提示错误
          const stale = chunk.filter((c) => codeSeqRef.current.get(stockCodeMatchKey(c)) === seq);
          if (stale.length) {
            setQuoteFailed((prev) => {
              const next = { ...prev };
              for (const c of stale) next[c] = true;
              return next;
            });
          }
        });
    }
  }, [loadIndices]);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      if (highlightTimerRef.current !== null) window.clearTimeout(highlightTimerRef.current);
    };
  }, []);

  // 自選清單（STOCK_LIST）與基金持倉各自載入，任一失敗不擋其他來源，也不等帳本
  useEffect(() => {
    let active = true;
    systemConfigApi
      .getWatchlist()
      .then((codes) => {
        if (active) setWatchCodes(codes);
      })
      .catch((err) => {
        if (active) setError(getParsedApiError(err));
      })
      .finally(() => {
        if (active) setWatchSettled(true);
      });
    fundsApi
      .listHoldings()
      .then((list) => {
        if (active) setFunds(list.items);
      })
      .catch(() => {
        /* 基金卡是輔助資料，失敗就不顯示 */
      });
    return () => {
      active = false;
    };
  }, []);

  // 帳本快照只打一支帶即時價的：同時給帳戶總覽與持股清單（全部帳戶，含美股複委託）。
  // 持股清單只在第一次成功時建立，之後的 5 分鐘重抓只更新總覽，避免整頁報價跟著重打
  useEffect(() => {
    let active = true;
    portfolioApi
      .getSnapshot({ includeRealtime: true })
      .then((snap) => {
        if (!active) return;
        setOverview(totalsByCurrency(snap.accounts));
        if (!holdingsLoadedRef.current) {
          holdingsLoadedRef.current = true;
          setHoldings(mergeHoldings(snap.accounts));
          setHoldingsFailed(false);
        }
      })
      .catch(() => {
        // 總覽保留舊值；持股從沒成功過才提示只剩自選
        if (active && !holdingsLoadedRef.current) setHoldingsFailed(true);
      })
      .finally(() => {
        if (active) setHoldingsSettled(true);
      });
    return () => {
      active = false;
    };
  }, [overviewTick]);

  // 自選回來就能先畫；持股範圍、或自選是空的時候要等帳本，否則會閃一下「沒有股票」
  const loading = !watchSettled || (!holdingsSettled && (scope === 'holdings' || watchCodes.length === 0));

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

  // 清單變動時只補抓還沒問過報價的代碼（自選先一批、持股回來再一批）；已抓過的交給輪詢與手動刷新。
  // 第一次一定呼叫一次，即使清單是空的也要載入大盤指數
  const quoteRequestedRef = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!codes) return;
    codesRef.current = codes;
    const first = quoteRequestedRef.current === null;
    const requested = quoteRequestedRef.current ?? new Set<string>();
    quoteRequestedRef.current = requested;
    const added = codes.filter((c) => !requested.has(c));
    for (const c of added) requested.add(c);
    if (first || added.length > 0) refresh(added, first ? INDEX_REGIONS : []);
  }, [codes, refresh]);

  // 四維度摘要在清單改變、手動刷新、每 15 分鐘時重抓（日資料，不跟 30 秒報價輪詢）；只送台股、失敗不影響報價
  // key 一律正規化：後端回大寫代碼，自選清單可能是小寫
  // 清單只是多了代碼時只補新的那批；tick 變了（手動刷新／15 分鐘）才整份重抓。
  // 不用 effect 的 cleanup 作廢在途請求：清單分兩批到時，第一批的結果不能被第二批丟掉
  const dossierRequestedRef = useRef<{ tick: number; codes: Set<string> } | null>(null);
  useEffect(() => {
    const allTw = (codes ?? []).filter(isTwStockCode);
    const prev = dossierRequestedRef.current;
    const fresh = !prev || prev.tick !== dossierTick;
    const requested = fresh ? new Set<string>() : prev.codes;
    dossierRequestedRef.current = { tick: dossierTick, codes: requested };
    const tw = allTw.filter((c) => !requested.has(stockCodeMatchKey(c)));
    for (const c of tw) requested.add(stockCodeMatchKey(c));
    for (let i = 0; i < tw.length; i += DOSSIER_CHUNK) {
      stocksApi
        .getDossierSummaries(tw.slice(i, i + DOSSIER_CHUNK))
        .then(({ items, levelAlertsEnabled: enabled }) => {
          if (!aliveRef.current) return;
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
  }, [codes, dossierTick]);

  // 迷你分時只查持股；關閉或手機就完全不發請求
  useEffect(() => {
    if (!sparkEnabled || !isDesktopViewport()) return;
    const held = (codes ?? []).filter((c) => holdings[stockCodeMatchKey(c)]);
    let active = true;
    for (let i = 0; i < held.length; i += DOSSIER_CHUNK) {
      stocksApi
        .getIntradayTrends(held.slice(i, i + DOSSIER_CHUNK))
        .then((items) => {
          if (!active) return;
          setSparks((prev) => {
            const next = { ...prev };
            for (const it of items) next[stockCodeMatchKey(it.stockCode)] = it.points;
            return next;
          });
        })
        .catch(() => {
          /* 迷你圖是輔助資料，失敗保留舊圖 */
        });
    }
    return () => {
      active = false;
    };
  }, [codes, holdings, sparkEnabled, sparkTick]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) setDossierTick((n) => n + 1);
    }, DOSSIER_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let status: Record<string, boolean> = {}; // 缺值＝當開盤
    let checkedAt = Date.now();
    let cancelled = false;
    const statusMarkets = () =>
      // 台股、美股永遠帶上（頁首與指數列依它們決定）；other（日港陸韓等）後端不分流，一律當開盤
      Array.from(new Set(['tw', 'us', ...(codesRef.current ?? []).map(boardMarketOf)])).filter((m) => m !== 'other');
    const queryStatus = () =>
      stocksApi
        .getMarketStatus(statusMarkets())
        .catch(() => null) // 查不到就當開盤，寧可多打不凍結看板；頁首顯示狀態未知
        .then((m) => {
          status = m ?? {};
          if (!cancelled) setMarketOpen(status);
        });
    // 第一次載入就查：不查的話收盤後進頁面，頁首與指數列會有 5 分鐘標成「即時」
    void queryStatus();
    const overviewTimer = window.setInterval(() => {
      if (!document.hidden && (status.tw !== false || status.us !== false)) setOverviewTick((n) => n + 1);
    }, OVERVIEW_REFRESH_MS);
    const sparkTimer = window.setInterval(() => {
      if (!document.hidden && (status.tw !== false || status.us !== false)) setSparkTick((n) => n + 1);
    }, SPARK_REFRESH_MS);
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      const run = () => {
        // 逐市場濾掉休市的代碼；指數只抓開盤中的市場
        const live = (codesRef.current ?? []).filter((c) => status[boardMarketOf(c)] !== false);
        const regions = INDEX_REGIONS.filter((region) => status[region] !== false);
        if (live.length || regions.length) refresh(live, regions);
      };
      if (Date.now() - checkedAt < MARKET_STATUS_TTL_MS) return run();
      checkedAt = Date.now();
      void queryStatus().then(run);
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.clearInterval(overviewTimer);
      window.clearInterval(sparkTimer);
    };
  }, [refresh]);

  const indexNames = useMemo(() => {
    const names = new Map<string, string>();
    for (const item of stockIndex) names.set(item.canonicalCode.toUpperCase(), item.nameZh);
    return names;
  }, [stockIndex]);

  const rows = useMemo<BoardRow[]>(
    () =>
      (codes ?? []).map((code) => {
        const key = stockCodeMatchKey(code);
        const item = quotes[code];
        const holding = holdings[key];
        const summary = dossier[key];
        return {
          code,
          key,
          item,
          q: item?.quote,
          holding,
          dossier: summary,
          currency: holding?.currency ?? (isTwStockCode(code) ? 'TWD' : undefined),
          // 名稱不依賴報價：帳本與索引有就先用，報價失敗時列上仍認得出是哪一檔
          name: holding?.name || indexNames.get(key) || summary?.name || item?.quote?.stockName || null,
        };
      }),
    [codes, quotes, holdings, dossier, indexNames],
  );

  const sectionRows = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const visible = needle
      ? rows.filter((row) => row.code.toLowerCase().includes(needle) || (row.name ?? '').toLowerCase().includes(needle))
      : rows;
    const groups: Record<SectionId, BoardRow[]> = { holdingsTw: [], holdingsUs: [], watch: [] };
    for (const row of visible) {
      // 自選範圍只有一段「自選」，持股列靠列上的「持股」小標辨識；只有「全部」才把持股拆出去
      if (scope === 'watch' || !row.holding) groups.watch.push(row);
      else if (isTwStockCode(row.code)) groups.holdingsTw.push(row);
      else groups.holdingsUs.push(row);
    }
    return groups;
  }, [rows, filter, scope]);

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
          'ml-1.5 inline-flex rounded border px-1.5 py-0.5 align-middle text-[10px]',
          isNo
            ? 'border-red-500/25 bg-red-500/10 text-red-600'
            : 'border-amber-500/25 bg-amber-500/10 text-amber-600',
        )}
      >
        {isNo ? t('board.dayTrade.no') : t('board.dayTrade.onlyBuy')}
      </span>
    );
  };

  // 有報告就開報告，沒有就帶代號回首頁等使用者決定；兩條路都不自動觸發分析（會花錢）
  const openAnalysis = useCallback(
    (code: string) => {
      const key = stockCodeMatchKey(code);
      historyApi
        .getList({ stockCode: key, limit: 1 })
        .then(({ items }) => items[0]?.id ?? null)
        .catch(() => null)
        .then((reportId) => {
          navigate(reportId != null ? `/?report=${reportId}` : `/?stock=${encodeURIComponent(code)}`);
        });
    },
    [navigate],
  );

  // 報價的三種沒有讀數狀態：還在載入、後端回沒有報價、資料較舊（盤中才提醒，收盤後舊是正常）
  const quoteStateNote = (row: BoardRow) => {
    if (!row.item) return <div className="text-[10px] text-secondary-text">{t('board.quote.loading')}</div>;
    if (!hasPrice(row.q)) return <div className="text-[10px] text-secondary-text">{t('board.quote.none')}</div>;
    const open = marketOpen[boardMarketOf(row.code)] !== false;
    if (row.q.isStale === true && open) return <div className="text-[10px] text-warning">{t('board.quote.stale')}</div>;
    return null;
  };

  const priceValue = (row: BoardRow) => {
    const flash = flashes[row.code];
    return (
      <span key={flash?.seq ?? 0} className={cn('px-0.5', flash && `board-flash-${flash.dir}`)}>
        {hasPrice(row.q) ? formatPrice(row.q.currentPrice, row.currency) : NO_VALUE}
      </span>
    );
  };

  const volumeValue = (row: BoardRow) => {
    const volume = row.q?.volume;
    if (volume == null) return NO_VALUE;
    // 報價的 volume 一律是股；台股看盤習慣看張
    return isTwStockCode(row.code) ? (
      <>
        {formatNumber(volume / 1000, 0)}
        <span className="ml-0.5 text-[10px] text-secondary-text">{t('board.unit.lot')}</span>
      </>
    ) : (
      <>
        {formatNumber(volume, 0)}
        <span className="ml-0.5 text-[10px] text-secondary-text">{t('board.unit.share')}</span>
      </>
    );
  };

  const analyzeButton = (row: BoardRow) => (
    <Button
      variant="ghost"
      size="sm"
      onClick={(e) => {
        e.stopPropagation();
        openAnalysis(row.code);
      }}
    >
      {t('board.action.analyze')}
    </Button>
  );

  const columnsFor = (section: SectionId): DataTableColumn<BoardRow>[] => {
    const isHolding = section !== 'watch';
    const columns: DataTableColumn<BoardRow>[] = [
      {
        key: 'stock',
        header: t('board.col.stock'),
        sortable: true,
        sticky: true,
        minWidth: 160,
        priority: 'primary',
        render: (row) => (
          <div className="flex items-center gap-2 py-1.5">
            {expanded === row.code ? <ChevronDown className="h-4 w-4 shrink-0 text-secondary-text" /> : <ChevronRight className="h-4 w-4 shrink-0 text-secondary-text" />}
            <div className="min-w-0">
              <div className="truncate font-medium">
                {row.name ?? NO_VALUE}
                {dayTradeBadge(row.q)}
              </div>
              <div className="font-mono text-xs text-secondary-text">
                <span data-testid="board-code">{row.code}</span>
                {row.holding ? (
                  <span className="ml-1.5 inline-flex rounded border border-[hsl(var(--primary))]/30 px-1 align-middle font-sans text-[10px] text-[hsl(var(--primary))]">
                    {t('board.tag.holding')}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        ),
      },
      {
        key: 'price',
        header: t('board.col.price'),
        numeric: true,
        sortable: true,
        render: (row) => {
          const li = limitInfo(row.q);
          return (
            <>
              <div>{priceValue(row)}</div>
              {quoteStateNote(row)}
              {li ? <div className={cn('text-[10px]', li.cls)}>{li.text}</div> : null}
            </>
          );
        },
      },
      {
        key: 'change',
        header: t('board.col.changeAmount'),
        numeric: true,
        sortable: true,
        render: (row) => <span className={changeClass(row.q?.change)}>{signedNumber(row.q?.change, 2)}</span>,
      },
      {
        key: 'changePct',
        header: t('board.col.changePct'),
        numeric: true,
        sortable: true,
        render: (row) => <span className={cn('font-semibold', changeClass(row.q?.changePercent))}>{formatPercent(row.q?.changePercent)}</span>,
      },
      {
        key: 'avg',
        header: t('board.col.avg'),
        numeric: true,
        sortable: true,
        render: (row) => {
          const deviation = avgDeviationPct(row.q);
          return (
            <>
              <div>{row.q?.averagePrice != null ? formatPrice(row.q.averagePrice, row.currency) : NO_VALUE}</div>
              {deviation != null ? <div className={cn('text-[10px]', changeClass(deviation))}>{formatPercent(deviation)}</div> : null}
            </>
          );
        },
      },
      { key: 'volume', header: t('board.col.volume'), numeric: true, sortable: true, render: volumeValue },
    ];
    if (isHolding) {
      columns.push(
        {
          key: 'quantity',
          header: t('board.col.quantity'),
          numeric: true,
          sortable: true,
          render: (row) =>
            row.holding ? (
              <HintTooltip content={row.holding.accounts.join('、')}>
                <span>{formatNumber(row.holding.quantity)}</span>
              </HintTooltip>
            ) : (
              NO_VALUE
            ),
        },
        {
          key: 'pnl',
          header: t('board.col.pnl'),
          numeric: true,
          sortable: true,
          render: (row) => {
            const pnl = unrealizedPnl(row);
            const pct = holdingPct(row);
            return (
              <div className={changeClass(pnl)}>
                <div>{pnl != null ? `${signedNumber(pnl, 0)} ${row.holding?.currency ?? ''}`.trim() : NO_VALUE}</div>
                {pct != null ? <div className="text-[10px]">{formatPercent(pct)}</div> : null}
              </div>
            );
          },
        },
      );
      if (sparkEnabled) {
        columns.push({
          key: 'spark',
          header: t('board.col.spark'),
          align: 'center',
          minWidth: 104,
          render: (row) => (
            <Sparkline
              points={sparks[row.key]}
              prevClose={row.q?.prevClose}
              label={`${row.name ?? row.code} ${t('board.col.spark')}`}
            />
          ),
        });
      }
    }
    columns.push(
      {
        key: 'structure',
        header: t('board.col.structure'),
        render: (row) => <BoardDossierCell summary={row.dossier} price={hasPrice(row.q) ? row.q.currentPrice : null} />,
      },
      { key: 'action', header: '', align: 'right', render: analyzeButton },
    );
    return columns;
  };

  const expandedContent = (row: BoardRow) => {
    const q = row.q;
    const tick =
      q?.lastTickType === 1
        ? { text: t('board.detail.tickBuy'), cls: 'text-market-up' }
        : q?.lastTickType === 2
          ? { text: t('board.detail.tickSell'), cls: 'text-market-down' }
          : { text: t('board.detail.tickNeutral'), cls: 'text-secondary-text' };
    const priceCell = (label: string, value?: number | null) =>
      value != null
        ? { label, value: <span className={changeClass(q?.prevClose ? value - q.prevClose : null)}>{formatPrice(value, row.currency)}</span> }
        : null;
    // 委買委賣都照「相對昨收」上色，與全站紅漲綠跌同一套，不再固定一紅一綠
    const bookCell = (label: string, price?: number | null, volume?: number | null) =>
      price != null
        ? {
            label,
            value: (
              <span className={changeClass(q?.prevClose ? price - q.prevClose : null)}>
                {formatPrice(price, row.currency)}
                <span className="ml-1 text-secondary-text">{formatNumber(volume, 0)}</span>
              </span>
            ),
          }
        : null;
    const cells = ([
      priceCell(t('board.detail.open'), q?.open),
      priceCell(t('board.detail.high'), q?.high),
      priceCell(t('board.detail.low'), q?.low),
      q?.prevClose != null ? { label: t('board.detail.prevClose'), value: formatPrice(q.prevClose, row.currency) } : null,
      bookCell(t('board.detail.bid'), q?.bestBid, q?.bestBidVolume),
      bookCell(t('board.detail.ask'), q?.bestAsk, q?.bestAskVolume),
      q?.lastTickType != null ? { label: t('board.detail.tick'), value: <span className={tick.cls}>{tick.text}</span> } : null,
      q?.averagePrice != null ? { label: t('board.detail.avg'), value: formatPrice(q.averagePrice, row.currency) } : null,
      q?.limitUp != null ? { label: t('board.detail.limitUp'), value: <span className="text-market-up">{formatPrice(q.limitUp, row.currency)}</span> } : null,
      q?.limitDown != null ? { label: t('board.detail.limitDown'), value: <span className="text-market-down">{formatPrice(q.limitDown, row.currency)}</span> } : null,
      q?.volumeRatio != null ? { label: t('board.detail.volumeRatio'), value: formatNumber(q.volumeRatio, 2) } : null,
      q?.amplitude != null ? { label: t('board.detail.amplitude'), value: `${formatNumber(q.amplitude, 2)}%` } : null,
    ] as Array<{ label: string; value: React.ReactNode } | null>).filter((c): c is { label: string; value: React.ReactNode } => c !== null);
    return (
      // 寬表橫捲時展開內容黏在左邊，不用橫滑整張表才找得到按鈕
      <div data-testid="board-expanded" className="sticky left-0 w-[min(100%,calc(100vw-4rem))] bg-base/40">
        <BoardDossierPanel
          code={row.code}
          name={row.name}
          summary={row.dossier}
          price={hasPrice(q) ? q.currentPrice : null}
          levelAlertsEnabled={levelAlertsEnabled}
        />
        <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
          <TrendChart code={row.code} prevClose={q?.prevClose} />
          <div className="min-w-0 px-3 py-3">
            {cells.length > 0 ? (
              <dl data-testid="board-detail-grid" className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm tabular-nums sm:grid-cols-3">
                {cells.map((c) => (
                  <div key={c.label} className="min-w-0">
                    <dt className="text-xs text-secondary-text">{c.label}</dt>
                    <dd>{c.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
            {q?.volumeRatio != null ? <div className="mt-2 text-[10px] text-secondary-text">{t('board.detail.volumeRatioHint')}</div> : null}
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate(`/alerts?new=1&target=${encodeURIComponent(row.code)}`);
                }}
              >
                {t('board.action.createAlert')}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  openAnalysis(row.code);
                }}
              >
                {t('board.action.fullAnalysis')}
              </Button>
            </div>
          </div>
        </div>
        <div className="px-3 pb-3">
          <FinancialsPanel stockCode={row.code} />
        </div>
      </div>
    );
  };

  // 手機三段式列：名稱代號｜現價｜漲跌幅，點開才看其餘；持股多一行股數與未實現損益
  const mobileCard = (row: BoardRow) => {
    const isOpen = expanded === row.code;
    const pnl = unrealizedPnl(row);
    const pct = holdingPct(row);
    return (
      <div>
        <div
          role="button"
          tabIndex={0}
          aria-expanded={isOpen}
          onClick={() => setExpanded(isOpen ? null : row.code)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              setExpanded(isOpen ? null : row.code);
            }
          }}
          className="grid min-h-11 cursor-pointer grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-x-3 gap-y-0.5 px-3 py-2 text-sm"
        >
          <div className="min-w-0">
            <div className="truncate font-medium">{row.name ?? NO_VALUE}</div>
            <div className="truncate font-mono text-xs text-secondary-text">
              {row.code}
              {row.holding ? (
                <span className="ml-1.5 inline-flex rounded border border-[hsl(var(--primary))]/30 px-1 align-middle font-sans text-[10px] text-[hsl(var(--primary))]">
                  {t('board.tag.holding')}
                </span>
              ) : null}
            </div>
          </div>
          <div className="text-right tabular-nums">
            <div>{priceValue(row)}</div>
            {quoteStateNote(row)}
          </div>
          <div className={cn('min-w-16 text-right font-semibold tabular-nums', changeClass(row.q?.changePercent))}>
            {formatPercent(row.q?.changePercent)}
          </div>
          <ChevronRight
            aria-hidden="true"
            className={cn('h-4 w-4 shrink-0 text-secondary-text transition-transform', isOpen && 'rotate-90')}
          />
          {row.holding ? (
            <div data-testid="board-mobile-holding" className={cn('col-span-4 text-xs tabular-nums', changeClass(pnl))}>
              {pnl != null
                ? formatUiText(bt.mobileHolding, {
                    qty: formatNumber(row.holding.quantity),
                    pnl: signedNumber(pnl, 0),
                    pct: formatPercent(pct, 1),
                  })
                : formatUiText(bt.mobileHoldingQty, { qty: formatNumber(row.holding.quantity) })}
            </div>
          ) : null}
        </div>
        {isOpen && !isDesktopViewport() ? expandedContent(row) : null}
      </div>
    );
  };

  const breadth = useMemo(() => {
    const counts = { up: 0, down: 0, flat: 0 };
    for (const row of rows) {
      const pct = row.q?.changePercent;
      if (pct == null) continue;
      if (pct > 0) counts.up += 1;
      else if (pct < 0) counts.down += 1;
      else counts.flat += 1;
    }
    return counts;
  }, [rows]);
  const quotesDone = rows.filter((row) => row.item || quoteFailed[row.code]).length;
  const breadthValue =
    quotesDone < rows.length
      ? formatUiText(bt.breadthLoading, { done: quotesDone, total: rows.length })
      : t('board.overview.breadthValue', { up: breadth.up, down: breadth.down, flat: breadth.flat });

  // 兩市都休市：今日損益其實是上一交易日的，需注意也不能寫「今日」
  const bothClosed = marketOpen.tw === false && marketOpen.us === false;

  // 需注意只放結構化的事實（板位、單日大動、持股沒有報價），不從文字猜。
  // 只看篩選後畫面上的列：篩掉的股票不該還掛在膠囊上
  const attention = (() => {
    const visible = SECTION_ORDER.flatMap((section) => sectionRows[section]);
    const items = visible.flatMap((row) => {
      const q = row.q;
      const pct = q?.changePercent;
      const magnitude = pct != null ? Math.abs(pct) : 0;
      if (row.holding && row.item && !hasPrice(q)) {
        return [{ row, text: t('board.quote.none'), cls: 'text-warning', hit: false, magnitude }];
      }
      const li = limitInfo(q);
      const hit = Boolean(q && q.currentPrice && ((q.limitUp != null && q.currentPrice >= q.limitUp) || (q.limitDown != null && q.currentPrice <= q.limitDown)));
      if (li) return [{ row, text: li.text, cls: li.cls, hit, magnitude }];
      if (pct != null && Math.abs(pct) >= ATTENTION_MOVE_PCT) {
        const text = bothClosed
          ? formatUiText(bt.attentionMoveClosed, { pct: formatPercent(pct, 1) })
          : t('board.attention.bigMove', { pct: formatPercent(pct, 1) });
        return [{ row, text, cls: changeClass(pct), hit: false, magnitude }];
      }
      return [];
    });
    // 觸板優先，其餘依 |漲跌幅| 由大到小
    return items.sort((a, b) => Number(b.hit) - Number(a.hit) || b.magnitude - a.magnitude);
  })();
  const attentionShown = attention.slice(0, ATTENTION_MAX);
  const attentionHidden = attention.length - attentionShown.length;

  // 點膠囊：清篩選 → 切到含該檔的範圍 → 展開 → 下一格畫面捲到那列置中並短暫高亮
  const jumpToRow = (row: BoardRow) => {
    setFilter('');
    const inScope =
      scope === 'all' ||
      (scope === 'holdings' ? Boolean(row.holding) : watchCodes.some((c) => stockCodeMatchKey(c) === row.key));
    if (!inScope) {
      setScope('all');
      writeScope('all');
    }
    setExpanded(row.code);
    setHighlighted(row.code);
    if (highlightTimerRef.current !== null) window.clearTimeout(highlightTimerRef.current);
    highlightTimerRef.current = window.setTimeout(() => {
      if (aliveRef.current) setHighlighted(null);
      highlightTimerRef.current = null;
    }, HIGHLIGHT_MS);
    const selector = `${isDesktopViewport() ? 'tr' : 'li'}[data-row-key="${row.code.replace(/["\\]/g, '\\$&')}"]`;
    window.requestAnimationFrame(() => {
      document.querySelector(selector)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
  };

  // 今日損益標籤寫清範圍；兩市都休市時改叫上一交易日損益
  const dayPnlLabel = (currency: string): string => {
    if (currency === 'TWD') return bothClosed ? bt.prevPnlTw : bt.dayPnlTw;
    if (currency === 'USD') return bothClosed ? bt.prevPnlUs : bt.dayPnlUs;
    return formatUiText(bothClosed ? bt.prevPnlOther : bt.dayPnlOther, { currency: CURRENCY_LABEL[currency] ?? currency });
  };

  const marketStatusText = (market: 'tw' | 'us') => {
    const open = marketOpen[market];
    return open === undefined ? t('board.market.unknown') : open ? t('board.market.open') : t('board.market.closed');
  };

  const indexRow = (region: MarketIndexRegion, indices: MarketIndex[]) => {
    const tag = indexSourceTag(indices[0]);
    // 收盤後快照就是收盤價：來源仍是 Shioaji 也不能標「即時」
    const closed = marketOpen[region] === false;
    const label =
      tag.kind === 'close'
        ? t('board.indices.close', { date: tag.asOf ?? '—' })
        : closed
          ? t('board.market.closed')
          : tag.kind === 'live'
            ? `${t('board.source.live')}${tag.asOf ? ` · ${formatDateTime(tag.asOf)}` : ''}`
            : t('board.source.delayed');
    const hint = t(INDEX_HINT_KEY[tag.kind]);
    return (
      <div key={region} className="flex flex-col gap-1 md:flex-row md:flex-wrap md:items-baseline md:gap-x-8 md:gap-y-2">
        <HintTooltip content={hint}>
          <span className="whitespace-nowrap text-xs text-secondary-text" aria-label={hint}>
            {label}
          </span>
        </HintTooltip>
        {/* Phones: two indices per row instead of one per line, so the first stock row stays above the fold. */}
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 md:flex md:flex-wrap md:items-baseline md:gap-x-8 md:gap-y-2">
          {indices.map((idx) => (
            <div key={idx.code} className="flex min-w-0 flex-wrap items-baseline gap-x-2 tabular-nums">
              <span className="truncate text-sm text-secondary-text">{idx.name}</span>
              <span className="text-base font-medium">{formatNumber(idx.current, 2)}</span>
              <span className={cn('text-sm', changeClass(idx.changePct))}>{formatPercent(idx.changePct)}</span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const indexRegionsWithData = INDEX_REGIONS.filter((region) => (indexRegionStates[region]?.items.length ?? 0) > 0);

  const fundsCard =
    scope !== 'watch' && funds.length > 0 ? (
      <Card variant="surface" padding="md">
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
              <span className={cn('text-sm', changeClass(f.pnlPct))}>{formatPercent(f.pnlPct)}</span>
            </button>
          ))}
        </div>
      </Card>
    ) : null;

  const refreshButton = (
    <button
      type="button"
      aria-label={t('board.refresh')}
      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border text-secondary-text hover:bg-hover hover:text-foreground"
      onClick={() => {
        refresh(undefined, INDEX_REGIONS, true);
        setDossierTick((n) => n + 1);
        setOverviewTick((n) => n + 1);
        setSparkTick((n) => n + 1);
      }}
    >
      <RefreshCw aria-hidden="true" className="h-4 w-4" />
    </button>
  );

  // DataTable 兩種版面都會掛載、靠 CSS 切換；展開區含圖表與請求，只在實際看得到的那一邊渲染
  const desktop = isDesktopViewport();
  const visibleSections = SECTION_ORDER.filter((section) => sectionRows[section].length > 0);

  return (
    <AppPage className="space-y-5">
      <PageHeader
        title={t('board.title')}
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-3 text-xs text-secondary-text" data-testid="board-market-status">
              {(['tw', 'us'] as const).map((market) => (
                <span key={market} className="whitespace-nowrap">
                  {t(`board.market.${market}`)} {marketStatusText(market)}
                </span>
              ))}
              {updatedAt ? <span className="whitespace-nowrap">{formatUiText(bt.quoteFetchedAt, { time: formatClock(updatedAt) })}</span> : null}
            </div>
            {refreshButton}
          </div>
        }
      />
      {holdingsFailed ? <div className="text-xs text-warning">{t('board.holdingsError')}</div> : null}
      {error ? <ApiErrorAlert error={error} onDismiss={() => setError(null)} /> : null}
      {indexRegionsWithData.length > 0 ? (
        <Card variant="surface" padding="md">
          <div className="mb-2 text-sm font-medium">{t('board.indices.title')}</div>
          <div className="space-y-2">{indexRegionsWithData.map((region) => indexRow(region, indexRegionStates[region]?.items ?? []))}</div>
        </Card>
      ) : null}
      {overview.length > 0 || rows.length > 0 ? (
        <MetricGroup columns={4}>
          {overview.map((total) => (
            <Metric
              key={total.currency}
              label={dayPnlLabel(total.currency)}
              unavailable={total.dayPnl == null}
              value={total.dayPnl != null ? <span className={changeClass(total.dayPnl)}>{signedNumber(total.dayPnl, 0)}</span> : undefined}
              hint={
                total.unrealized != null
                  ? `${t('board.overview.unrealized')} ${signedNumber(total.unrealized, 0)}`
                  : undefined
              }
            />
          ))}
          <Metric
            label={t('board.overview.breadth')}
            value={<span className="whitespace-nowrap">{breadthValue}</span>}
          />
        </MetricGroup>
      ) : null}
      {attentionShown.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2" data-testid="board-attention">
          <span className="text-xs font-medium text-secondary-text">{t('board.attention.title')}</span>
          {attentionShown.map(({ row, text, cls }) => (
            <button
              key={row.code}
              type="button"
              onClick={() => jumpToRow(row)}
              className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-0.5 text-xs hover:bg-hover"
            >
              {/* US names are long English company names; the ticker is what traders recognise */}
              <span className="max-w-[10rem] truncate">{boardMarketOf(row.code) === 'us' ? row.code : row.name ?? row.code}</span>
              <span className={cn('whitespace-nowrap tabular-nums', cls)}>{text}</span>
            </button>
          ))}
          {attentionHidden > 0 ? (
            <span className="text-xs text-secondary-text">{formatUiText(bt.attentionMore, { count: attentionHidden })}</span>
          ) : null}
        </div>
      ) : null}
      <FilterBar
        primary={
          <>
            <Segmented
              aria-label={t('board.scope.label')}
              value={scope}
              onChange={(next) => {
                setScope(next);
                writeScope(next);
              }}
              options={SCOPES.map((sc) => ({ value: sc, label: t(`board.scope.${sc}` as 'board.scope.all') }))}
            />
            <Input
              aria-label={t('board.filter.placeholder')}
              placeholder={t('board.filter.placeholder')}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </>
        }
        actions={
          <Button
            variant={sparkEnabled ? 'secondary' : 'ghost'}
            aria-pressed={sparkEnabled}
            className="hidden md:inline-flex"
            onClick={() => {
              setSparkEnabled(!sparkEnabled);
              writeSparkEnabled(!sparkEnabled);
            }}
          >
            {t('board.spark.toggle')}
          </Button>
        }
      />
      {loading ? (
        <Card variant="surface" padding="md">
          <Loading label={t('board.title')} />
        </Card>
      ) : codes && codes.length === 0 ? (
        <Card variant="surface" padding="md">
          <EmptyState title={scope === 'holdings' ? t('board.emptyHoldings') : t('board.empty')} />
        </Card>
      ) : visibleSections.length === 0 ? (
        <Card variant="surface" padding="md">
          <EmptyState title={t('board.filter.empty')} />
        </Card>
      ) : (
        visibleSections.map((section) => (
          <Card key={section} variant="surface" padding="md">
            <div className="mb-2 text-sm font-medium">
              {t(`board.section.${section}`)}
              <span className="ml-1.5 text-xs font-normal text-secondary-text">{sectionRows[section].length}</span>
            </div>
            <DataTable
              aria-label={t(`board.section.${section}`)}
              columns={columnsFor(section)}
              rows={sortRows(sectionRows[section], sort)}
              rowKey={(row) => row.code}
              density="compact"
              isRowHighlighted={(row) => row.code === highlighted}
              sort={sort}
              onSortChange={(next) => {
                setSort(next);
                writeSort(next);
              }}
              onRowClick={(row) => setExpanded(expanded === row.code ? null : row.code)}
              expandedRowKey={desktop ? expanded : null}
              renderExpandedRow={expandedContent}
              renderMobileCard={mobileCard}
            />
          </Card>
        ))
      )}
      {fundsCard}
    </AppPage>
  );
};

export default RealtimeBoardPage;
