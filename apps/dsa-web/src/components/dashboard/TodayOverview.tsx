import type React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { decisionSignalsApi } from '../../api/decisionSignals';
import { historyApi } from '../../api/history';
import { portfolioApi } from '../../api/portfolio';
import type { StockQuote } from '../../api/stocks';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { stockQuoteKey } from '../../hooks/useStockQuotes';
import { HOME_TEXT, formatHomeText, formatMonthDay, type HomeText } from '../../locales/homeText';
import { useMarketIndexStore } from '../../stores/marketIndexStore';
import type { MarketReviewPayload } from '../../types/analysis';
import type { DecisionSignalSummaryResponse } from '../../types/decisionSignals';
import type { PortfolioSnapshotResponse } from '../../types/portfolio';
import { formatMoneyValue, formatNumber, formatPercent, NO_VALUE } from '../../utils/format';
import { Card, Change, Skeleton } from '../common';
import { StockRowLines } from '../history/StockBarItem';
import type { HomeWatchlistRow } from '../watchlist/HomeStockWorkspace';

// 總覽的持股幣別：本 fork 的主要帳戶是台股。
const OVERVIEW_DISPLAY_CURRENCY = 'TWD';
// 頂端狀態列已有加權、櫃買、S&P 500、Nasdaq，這裡只補狀態列沒有的。
const OVERVIEW_INDEX_CODES = ['DJI', 'VIX'] as const;
const UPDATED_PREVIEW_LIMIT = 6;
const MARKET_REVIEW_CODE = 'MARKET';

const REDUCE_SIGNALS_PATH = '/decision-signals?holding=1&action=reduce';
const STOP_TRIGGERED_SIGNALS_PATH = '/decision-signals?holding=1&stop=triggered';

type LoadState = 'loading' | 'ready' | 'failed';

interface TodayOverviewProps {
  watchlistRows: HomeWatchlistRow[];
  quotes: Map<string, StockQuote>;
  onOpenReport: (recordId: number) => void;
  /** 「今日已更新」的「看全部 →」；沒給就不顯示連結。 */
  onViewAllUpdated?: () => void;
}

const SummaryTile: React.FC<{
  label: string;
  value: React.ReactNode;
  loading: boolean;
  hint?: React.ReactNode;
  onClick: () => void;
  testId: string;
}> = ({ label, value, loading, hint, onClick, testId }) => (
  <button
    type="button"
    onClick={onClick}
    data-testid={testId}
    className="card-inset flex h-24 min-w-0 flex-col overflow-hidden rounded-[var(--radius-card)] p-3 text-left transition-colors hover:bg-hover"
  >
    <span className="line-clamp-2 text-xs leading-4 text-secondary-text">{label}</span>
    <span className="mt-1 flex h-7 items-center truncate text-lg font-semibold tabular-nums text-foreground">
      {loading ? <Skeleton className="h-7 w-24" /> : value}
    </span>
    {hint ? <span className="mt-0.5 block truncate text-[11px] text-muted-text">{hint}</span> : null}
  </button>
);

const LIGHT_DOT_CLASS: Record<string, string> = {
  green: 'bg-[var(--market-down)]',
  yellow: 'bg-warning',
  red: 'bg-[var(--market-up)]',
};

// Action semantics avoid red/green: brand cyan, muted grey, amber.
const STANCE_CLASS: Record<string, string> = {
  offensive: 'text-cyan',
  balanced: 'text-secondary-text',
  defensive: 'text-warning',
};

const stanceLabel = (stance: string | null | undefined, text: HomeText): string => {
  if (stance === 'offensive') return text.stanceOffensive;
  if (stance === 'balanced') return text.stanceBalanced;
  if (stance === 'defensive') return text.stanceDefensive;
  return '';
};

const regionLabel = (region: string | undefined, text: HomeText): string => {
  const key = (region ?? '').toLowerCase();
  if (key === 'tw') return text.marketTw;
  if (key === 'us') return text.marketUs;
  return key.toUpperCase();
};

/** Picks the market the verdict card reads from: Taiwan first, else the first market with a reading. */
function pickVerdictMarket(
  payload: MarketReviewPayload | null | undefined,
): { region?: string; market: MarketReviewPayload } | null {
  if (!payload) return null;
  const hasReading = (market: MarketReviewPayload) => Boolean(
    market.marketLight?.label || market.marketLight?.guidance || market.nextDayPlan?.stance || market.nextDayPlan?.summary,
  );
  if (payload.markets) {
    const entries = Object.entries(payload.markets);
    const tw = entries.find(([region]) => region.toLowerCase() === 'tw');
    const picked = tw && hasReading(tw[1]) ? tw : entries.find(([, market]) => hasReading(market));
    return picked ? { region: picked[0], market: picked[1] } : null;
  }
  return hasReading(payload) ? { region: payload.region, market: payload } : null;
}

const VerdictCard: React.FC<{
  recordId: number;
  payload: MarketReviewPayload;
  onOpen: (recordId: number) => void;
  text: HomeText;
}> = ({ recordId, payload, onOpen, text }) => {
  const picked = pickVerdictMarket(payload);
  if (!picked) return null;
  const { region, market } = picked;
  const light = market.marketLight;
  const plan = market.nextDayPlan;
  const stance = stanceLabel(plan?.stance, text);
  const sentence = light?.guidance || plan?.summary || '';
  const levels = (plan?.keyLevels ?? [])
    .filter((level) => typeof level.price === 'number')
    .slice(0, 2)
    .map((level) => formatNumber(level.price))
    .join(' / ');
  const date = formatMonthDay(light?.tradeDate ?? market.date ?? payload.date);
  const closeLabel = date
    ? formatHomeText(text.verdictClose, { market: regionLabel(region, text), date }).trim()
    : '';

  return (
    <button
      type="button"
      data-testid="today-verdict-card"
      aria-label={text.verdictAria}
      onClick={() => onOpen(recordId)}
      className="card-inset block w-full min-w-0 rounded-[var(--radius-card)] p-3 text-left transition-colors hover:bg-hover"
    >
      <span className="block text-[11px] text-muted-text">{text.verdictTitle}</span>
      <span className="mt-1 flex min-w-0 items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2 text-sm font-semibold text-foreground">
          <span
            aria-hidden="true"
            className={`h-2.5 w-2.5 shrink-0 rounded-full ${LIGHT_DOT_CLASS[light?.status ?? ''] ?? 'bg-secondary-text'}`}
          />
          <span className="truncate">
            {light?.label ? <span>{light.label}</span> : null}
            {light?.label && stance ? <span className="text-muted-text"> · </span> : null}
            {stance ? <span className={STANCE_CLASS[plan?.stance ?? ''] ?? ''}>{stance}</span> : null}
          </span>
        </span>
        {closeLabel ? <span className="shrink-0 text-[11px] text-muted-text">{closeLabel}</span> : null}
      </span>
      {sentence ? (
        <span className="mt-1.5 line-clamp-2 text-sm text-secondary-text" data-testid="today-verdict-sentence">
          {sentence}
        </span>
      ) : null}
      {levels ? (
        <span className="mt-1.5 block text-xs tabular-nums text-secondary-text">
          {formatHomeText(text.verdictKeyLevels, { levels })}
        </span>
      ) : null}
    </button>
  );
};

const analysisTime = (row: HomeWatchlistRow): number => {
  const parsed = row.latestItem?.lastAnalysisTime ? Date.parse(row.latestItem.lastAnalysisTime) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
};

/** 未選股時的首頁：今日判讀、待處理、補充指數、今日已更新。一選股就換成報告。 */
export const TodayOverview: React.FC<TodayOverviewProps> = ({ watchlistRows, quotes, onOpenReport, onViewAllUpdated }) => {
  const { t, language } = useUiLanguage();
  const homeText = HOME_TEXT[language];
  const navigate = useNavigate();
  const usIndices = useMarketIndexStore((state) => state.regions.us);
  const loadIndices = useMarketIndexStore((state) => state.load);
  const [snapshot, setSnapshot] = useState<PortfolioSnapshotResponse | null>(null);
  const [snapshotState, setSnapshotState] = useState<LoadState>('loading');
  const [signalSummary, setSignalSummary] = useState<DecisionSignalSummaryResponse | null>(null);
  const [signalState, setSignalState] = useState<LoadState>('loading');
  const [verdict, setVerdict] = useState<{ id: number; payload: MarketReviewPayload } | null>(null);

  useEffect(() => {
    void loadIndices('us');
  }, [loadIndices]);

  useEffect(() => {
    let active = true;
    // 各區塊獨立失敗：拿不到就顯示 —，不擋其他區塊。
    portfolioApi.getSnapshot({ displayCurrency: OVERVIEW_DISPLAY_CURRENCY })
      .then((data) => {
        if (!active) return;
        setSnapshot(data);
        setSnapshotState('ready');
      })
      .catch(() => {
        if (active) setSnapshotState('failed');
      });
    decisionSignalsApi.getSummary({ holdingOnly: true })
      .then((data) => {
        if (!active) return;
        setSignalSummary(data);
        setSignalState('ready');
      })
      .catch(() => {
        if (active) setSignalState('failed');
      });
    // 今日判讀卡：最新一份大盤複盤的 payload；取不到就不渲染這張卡。
    historyApi.getList({ stockCode: MARKET_REVIEW_CODE, reportType: 'market_review', page: 1, limit: 1 })
      .then(async (list) => {
        const latest = list.items[0];
        // Mocked or legacy list responses may ignore the filter; only a market review carries the payload.
        if (!latest || !active) return;
        if (latest.stockCode !== MARKET_REVIEW_CODE && latest.reportType !== 'market_review') return;
        const report = await historyApi.getDetail(latest.id);
        const payload = report?.details?.contextSnapshot?.marketReviewPayload;
        if (active && payload) setVerdict({ id: latest.id, payload });
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const indexItems = useMemo(
    () => OVERVIEW_INDEX_CODES.flatMap((code) => {
      const found = usIndices?.items.find((item) => item.code === code);
      return found ? [found] : [];
    }),
    [usIndices],
  );
  // 還沒抓過（undefined）也算載入中，避免第一個 render 就閃「—」。
  const isLoadingIndices = !usIndices || (usIndices.isLoading && usIndices.items.length === 0);
  const reduceCount = signalSummary ? signalSummary.actions?.reduce ?? 0 : null;
  const stopUnavailable = signalSummary?.stopPriceUnavailableCount ?? 0;
  const dayPnl = snapshot?.consolidatedDayPnlBase;
  const updatedRows = useMemo(
    () => watchlistRows
      .filter((row) => row.analyzedToday && typeof row.latestItem?.id === 'number')
      .sort((left, right) => analysisTime(right) - analysisTime(left))
      .slice(0, UPDATED_PREVIEW_LIMIT),
    [watchlistRows],
  );

  return (
    <div data-testid="today-overview" className="max-w-4xl space-y-3 pb-8">
      <h2 className="text-lg font-semibold text-foreground">{t('overview.title')}</h2>

      {verdict ? (
        <VerdictCard recordId={verdict.id} payload={verdict.payload} onOpen={onOpenReport} text={homeText} />
      ) : null}

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <SummaryTile
          testId="overview-tile-day-pnl"
          label={homeText.dayPnlLabel}
          loading={snapshotState === 'loading'}
          value={(
            <Change value={dayPnl}>
              {formatMoneyValue(dayPnl, OVERVIEW_DISPLAY_CURRENCY, 0)}
            </Change>
          )}
          onClick={() => navigate('/portfolio')}
        />
        <SummaryTile
          testId="overview-tile-market-value"
          label={t('overview.marketValue')}
          loading={snapshotState === 'loading'}
          value={formatMoneyValue(snapshot?.consolidatedMarketValueBase, OVERVIEW_DISPLAY_CURRENCY, 0)}
          onClick={() => navigate('/portfolio')}
        />
        <SummaryTile
          testId="overview-tile-reduce"
          label={t('overview.pendingReduce')}
          loading={signalState === 'loading'}
          value={formatNumber(reduceCount, 0)}
          onClick={() => navigate(REDUCE_SIGNALS_PATH)}
        />
        <SummaryTile
          testId="overview-tile-stop"
          label={t('overview.stopTriggered')}
          loading={signalState === 'loading'}
          value={formatNumber(signalSummary?.stopTriggeredCount, 0)}
          hint={stopUnavailable > 0 ? t('overview.stopUnavailable', { count: stopUnavailable }) : undefined}
          onClick={() => navigate(STOP_TRIGGERED_SIGNALS_PATH)}
        />
      </div>

      <div className="flex min-h-7 flex-wrap items-center gap-x-4 gap-y-1 text-xs" data-testid="overview-indices">
        {isLoadingIndices ? (
          OVERVIEW_INDEX_CODES.map((code) => <Skeleton key={code} className="h-7 w-24" />)
        ) : indexItems.length > 0 ? (
          indexItems.map((index) => (
            <span key={index.code} className="inline-flex min-w-0 items-baseline gap-1.5" data-testid={`overview-index-${index.code}`}>
              <span className="text-secondary-text">{index.code === 'DJI' ? homeText.indexDji : index.code}</span>
              <span className="font-medium tabular-nums text-foreground">{formatNumber(index.current, 2)}</span>
              <Change value={index.changePct} className="text-xs">{formatPercent(index.changePct)}</Change>
            </span>
          ))
        ) : (
          <span className="text-secondary-text">{NO_VALUE}</span>
        )}
      </div>

      <Card
        variant="surface"
        padding="md"
        title={homeText.todayUpdated}
        meta={onViewAllUpdated ? (
          <button
            type="button"
            onClick={onViewAllUpdated}
            className="text-xs font-medium text-cyan hover:underline"
          >
            {homeText.viewAll}
          </button>
        ) : undefined}
      >
        {updatedRows.length > 0 ? (
          <div className="grid grid-cols-1 gap-1.5 md:grid-cols-2">
            {updatedRows.map((row) => {
              const recordId = row.latestItem?.id;
              return (
                <button
                  key={row.code}
                  type="button"
                  onClick={() => {
                    if (typeof recordId === 'number') onOpenReport(recordId);
                  }}
                  className="home-subpanel flex min-h-[52px] min-w-0 items-center gap-2 px-2.5 py-1.5 text-left"
                >
                  <StockRowLines
                    code={row.code}
                    name={row.latestItem?.stockName}
                    quote={row.assetType === 'index' ? undefined : quotes.get(stockQuoteKey(row.code))}
                    analysisPrice={row.latestItem?.analysisPrice}
                    item={row.latestItem}
                  />
                </button>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-secondary-text">
            {watchlistRows.length === 0 ? t('overview.watchlistEmpty') : homeText.todayUpdatedEmpty}
          </p>
        )}
      </Card>
    </div>
  );
};
