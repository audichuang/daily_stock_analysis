import type React from 'react';
import { useEffect } from 'react';
import type { MarketIndex, MarketIndexSnapshot } from '../../api/stocks';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { MARKET_INDEX_TTL_MS, useMarketIndexStore, type MarketIndexRegionState } from '../../stores/marketIndexStore';
import { formatNumber, formatPercent } from '../../utils/format';
import { Change } from '../common/Change';

type IndexSpec = { code: string; labelKey: UiTextKey };

const TW_INDICES: IndexSpec[] = [
  { code: 'TWII', labelKey: 'layout.statusBar.twii' },
  { code: 'TPEX', labelKey: 'layout.statusBar.tpex' },
];
const US_INDICES: IndexSpec[] = [
  { code: 'SPX', labelKey: 'layout.statusBar.spx' },
  { code: 'IXIC', labelKey: 'layout.statusBar.ixic' },
];

const PHASE_KEYS: Record<string, UiTextKey> = {
  premarket: 'layout.statusBar.phase.premarket',
  intraday: 'layout.statusBar.phase.intraday',
  lunch_break: 'layout.statusBar.phase.lunch_break',
  closing_auction: 'layout.statusBar.phase.closing_auction',
  postmarket: 'layout.statusBar.phase.postmarket',
  non_trading: 'layout.statusBar.phase.non_trading',
};

/** 取各指數裡最新的 as_of；只有日期的官方收盤值就顯示日期，不假裝成當下時間。 */
function formatLatestAsOf(indices: MarketIndex[]): string | null {
  const latest = indices
    .flatMap((idx) => (idx.asOf ? [{ asOf: idx.asOf, time: new Date(idx.asOf).getTime() }] : []))
    .filter((row) => !Number.isNaN(row.time))
    .sort((a, b) => b.time - a.time)[0];
  if (!latest) {
    return null;
  }
  if (!latest.asOf.includes('T')) {
    return latest.asOf;
  }
  const date = new Date(latest.time);
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

const MarketGroup: React.FC<{
  snapshot: MarketIndexSnapshot | null;
  specs: IndexSpec[];
  marketKey: UiTextKey;
}> = ({ snapshot, specs, marketKey }) => {
  const { t } = useUiLanguage();
  const rows = specs.flatMap((spec) => {
    const index = snapshot?.items.find((item) => item.code === spec.code);
    return index ? [{ spec, index }] : [];
  });
  if (rows.length === 0) {
    return null;
  }
  const phaseKey = snapshot?.marketPhase ? PHASE_KEYS[snapshot.marketPhase] : undefined;

  return (
    <div className="flex shrink-0 items-center gap-3">
      {rows.map(({ spec, index }) => (
        <span key={spec.code} className="inline-flex items-center gap-1.5" data-testid={`status-index-${spec.code}`}>
          <span className="text-secondary-text">{t(spec.labelKey)}</span>
          <span className="tabular-nums text-foreground">{formatNumber(index.current, 2)}</span>
          <Change value={index.changePct}>{formatPercent(index.changePct)}</Change>
        </span>
      ))}
      {phaseKey ? (
        <span className="text-muted-text">{t(marketKey)} {t(phaseKey)}</span>
      ) : null}
    </div>
  );
};

/** 全站細長狀態列：只在可見時輪詢，切回分頁時補抓（60 秒內不重抓）。內嵌模式由 Shell 決定不掛載。 */
/** 還沒成功抓過視為無資料，首次載入中不要畫出空的市場列。 */
const loadedRegion = (region: MarketIndexRegionState | undefined) => (region && region.fetchedAt > 0 ? region : null);

export const MarketStatusBar: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  const { t } = useUiLanguage();
  const tw = useMarketIndexStore((state) => loadedRegion(state.regions.tw));
  const us = useMarketIndexStore((state) => loadedRegion(state.regions.us));
  const load = useMarketIndexStore((state) => state.load);

  useEffect(() => {
    let timer: number | null = null;
    const stop = () => {
      if (timer !== null) {
        window.clearInterval(timer);
        timer = null;
      }
    };
    const start = () => {
      stop();
      void load(['tw', 'us']);
      timer = window.setInterval(() => {
        void load(['tw', 'us'], { force: true });
      }, MARKET_INDEX_TTL_MS);
    };
    const handleVisibility = () => {
      if (document.visibilityState === 'hidden') {
        stop();
      } else {
        start();
      }
    };
    if (document.visibilityState !== 'hidden') {
      start();
    }
    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [load]);

  const updatedAt = formatLatestAsOf([...(tw?.items ?? []), ...(us?.items ?? [])]);

  return (
    <div
      role="region"
      aria-label={t('layout.statusBar.label')}
      className="shell-status-bar sticky z-30 border-b border-border/60 bg-background text-xs"
    >
      <div className="mx-auto flex h-full w-full max-w-[1680px] items-center gap-4 px-3 sm:px-4 lg:px-5">
        <div className="flex min-w-0 flex-1 items-center gap-4 overflow-x-auto whitespace-nowrap [scrollbar-width:none]">
          <MarketGroup snapshot={tw} specs={TW_INDICES} marketKey="layout.statusBar.tw" />
          <MarketGroup snapshot={us} specs={US_INDICES} marketKey="layout.statusBar.us" />
          {updatedAt ? (
            <span className="shrink-0 text-muted-text">{t('layout.statusBar.updated', { time: updatedAt })}</span>
          ) : null}
        </div>
        {children}
      </div>
    </div>
  );
};
