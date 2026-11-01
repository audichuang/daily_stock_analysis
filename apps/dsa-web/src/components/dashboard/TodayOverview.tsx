import type React from 'react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { decisionSignalsApi } from '../../api/decisionSignals';
import { portfolioApi } from '../../api/portfolio';
import type { StockQuote } from '../../api/stocks';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { stockQuoteKey } from '../../hooks/useStockQuotes';
import { useMarketIndexStore } from '../../stores/marketIndexStore';
import type { DecisionSignalSummaryResponse } from '../../types/decisionSignals';
import type { PortfolioSnapshotResponse } from '../../types/portfolio';
import { formatMoneyValue, formatNumber, formatPercent, NO_VALUE } from '../../utils/format';
import { Card, Change } from '../common';
import { StockRowLines } from '../history/StockBarItem';
import type { HomeWatchlistRow } from '../watchlist/HomeStockWorkspace';

// 總覽的市場與持股幣別：本 fork 的主要帳戶是台股。
const OVERVIEW_REGIONS = ['tw', 'us'] as const;
const OVERVIEW_DISPLAY_CURRENCY = 'TWD';
const WATCHLIST_PREVIEW_LIMIT = 8;

interface TodayOverviewProps {
  watchlistRows: HomeWatchlistRow[];
  quotes: Map<string, StockQuote>;
  onOpenReport: (recordId: number) => void;
}

const SummaryTile: React.FC<{
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  onClick: () => void;
}> = ({ label, value, hint, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className="card-inset min-w-0 rounded-[var(--radius-card)] p-3 text-left transition-colors hover:bg-hover"
  >
    <span className="block text-xs text-secondary-text">{label}</span>
    <span className="mt-1 block truncate text-lg font-semibold tabular-nums text-foreground">{value}</span>
    {hint ? <span className="mt-0.5 block truncate text-[11px] text-muted-text">{hint}</span> : null}
  </button>
);

/** 未選股時的首頁：大盤、持股與待處理、自選最新。一選股就換成報告。 */
export const TodayOverview: React.FC<TodayOverviewProps> = ({ watchlistRows, quotes, onOpenReport }) => {
  const { t } = useUiLanguage();
  const navigate = useNavigate();
  const regions = useMarketIndexStore((state) => state.regions);
  const loadIndices = useMarketIndexStore((state) => state.load);
  const [snapshot, setSnapshot] = useState<PortfolioSnapshotResponse | null>(null);
  const [signalSummary, setSignalSummary] = useState<DecisionSignalSummaryResponse | null>(null);

  useEffect(() => {
    OVERVIEW_REGIONS.forEach((region) => void loadIndices(region));
  }, [loadIndices]);

  useEffect(() => {
    let active = true;
    // 各區塊獨立失敗：拿不到就顯示 —，不擋其他區塊。
    portfolioApi.getSnapshot({ displayCurrency: OVERVIEW_DISPLAY_CURRENCY })
      .then((data) => {
        if (active) setSnapshot(data);
      })
      .catch(() => undefined);
    decisionSignalsApi.getSummary({ holdingOnly: true })
      .then((data) => {
        if (active) setSignalSummary(data);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const indices = OVERVIEW_REGIONS.flatMap((region) => regions[region]?.items ?? []);
  const isLoadingIndices = OVERVIEW_REGIONS.some((region) => regions[region]?.isLoading);
  const reduceCount = signalSummary ? signalSummary.actions?.reduce ?? 0 : null;
  const stopUnavailable = signalSummary?.stopPriceUnavailableCount ?? 0;
  const dayPnl = snapshot?.consolidatedDayPnlBase;
  const previewRows = watchlistRows.slice(0, WATCHLIST_PREVIEW_LIMIT);

  return (
    <div data-testid="today-overview" className="max-w-4xl space-y-3 pb-8">
      <h2 className="text-lg font-semibold text-foreground">{t('overview.title')}</h2>

      <Card variant="surface" padding="md" title={t('overview.indices')}>
        {indices.length > 0 ? (
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {indices.map((index) => (
              <div key={index.code} className="min-w-0" data-testid={`overview-index-${index.code}`}>
                <p className="truncate text-xs text-secondary-text">{index.name || index.code}</p>
                <p className="mt-0.5 text-sm font-semibold tabular-nums text-foreground">{formatNumber(index.current, 2)}</p>
                <Change value={index.changePct} className="text-xs">{formatPercent(index.changePct)}</Change>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-secondary-text">{isLoadingIndices ? NO_VALUE : t('overview.indicesEmpty')}</p>
        )}
      </Card>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <SummaryTile
          label={t('overview.dayPnl')}
          value={(
            <Change value={dayPnl}>
              {formatMoneyValue(dayPnl, OVERVIEW_DISPLAY_CURRENCY, 0)}
            </Change>
          )}
          onClick={() => navigate('/portfolio')}
        />
        <SummaryTile
          label={t('overview.marketValue')}
          value={formatMoneyValue(snapshot?.consolidatedMarketValueBase, OVERVIEW_DISPLAY_CURRENCY, 0)}
          onClick={() => navigate('/portfolio')}
        />
        <SummaryTile
          label={t('overview.pendingReduce')}
          value={formatNumber(reduceCount, 0)}
          onClick={() => navigate('/decision-signals')}
        />
        <SummaryTile
          label={t('overview.stopTriggered')}
          value={formatNumber(signalSummary?.stopTriggeredCount, 0)}
          hint={stopUnavailable > 0 ? t('overview.stopUnavailable', { count: stopUnavailable }) : undefined}
          onClick={() => navigate('/decision-signals')}
        />
      </div>

      <Card variant="surface" padding="md" title={t('overview.watchlistLatest')}>
        {previewRows.length > 0 ? (
          <div className="grid grid-cols-1 gap-1.5 md:grid-cols-2">
            {previewRows.map((row) => {
              const recordId = row.latestItem?.id;
              return (
                <button
                  key={row.code}
                  type="button"
                  disabled={typeof recordId !== 'number'}
                  onClick={() => {
                    if (typeof recordId === 'number') onOpenReport(recordId);
                  }}
                  className="home-subpanel flex min-h-[52px] min-w-0 items-center gap-2 px-2.5 py-1.5 text-left disabled:cursor-default"
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
          <p className="text-sm text-secondary-text">{t('overview.watchlistEmpty')}</p>
        )}
      </Card>
    </div>
  );
};
