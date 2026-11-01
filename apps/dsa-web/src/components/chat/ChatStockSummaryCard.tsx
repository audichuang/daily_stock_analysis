import type React from 'react';
import { Star } from 'lucide-react';
import type { ActiveStockContext, StructuredAnswer } from '../../api/agent';
import type { StockQuote } from '../../api/stocks';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { CHAT_TEXT } from '../../locales/chatText';
import { cn } from '../../utils/cn';
import { Change, Num } from '../common';

interface ChatStockSummaryCardProps {
  stock: ActiveStockContext;
  quote: StockQuote | null;
  structured?: StructuredAnswer | null;
  /** Watchlist toggle is shown only when a handler is provided. */
  inWatchlist?: boolean;
  watchlistPending?: boolean;
  onToggleWatchlist?: () => void;
}

const SummaryCell: React.FC<{ label: React.ReactNode; children: React.ReactNode }> = ({ label, children }) => (
  <div className="min-w-0">
    <p className="text-xs text-secondary-text">{label}</p>
    <p className="mt-0.5 text-sm font-semibold text-foreground">{children}</p>
  </div>
);

const hasLevel = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value);

/**
 * 回答上方的個股摘要：現價與漲跌來自行情（缺值顯示 —），
 * 壓力與支撐來自模型給的結構化值，沒值的那格不畫。
 */
export const ChatStockSummaryCard: React.FC<ChatStockSummaryCardProps> = ({
  stock,
  quote,
  structured,
  inWatchlist = false,
  watchlistPending = false,
  onToggleWatchlist,
}) => {
  const { language, t } = useUiLanguage();
  const chatText = CHAT_TEXT[language];
  const name = stock.stock_name || quote?.stockName;
  const showResistance = hasLevel(structured?.resistance);
  const showSupport = hasLevel(structured?.support);
  const cellCount = 2 + (showResistance ? 1 : 0) + (showSupport ? 1 : 0);
  // 降級來源（fallback）或標記過期的行情不能標「即時」。
  const quoteBadge = !quote
    ? null
    : quote.isStale === true || quote.source === 'fallback' ? chatText.delayed : chatText.live;
  const watchlistLabel = inWatchlist ? chatText.watchlistRemove : chatText.watchlistAdd;
  return (
    <section
      data-testid="chat-stock-summary"
      aria-label={t('chat.summary.label')}
      className="mb-3 rounded-xl border border-border/60 bg-card/70 p-3"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 truncate text-sm font-semibold text-foreground">
          {name ? `${name} · ` : ''}
          <span className="font-normal text-secondary-text">{stock.stock_code}</span>
        </p>
        {onToggleWatchlist ? (
          <button
            type="button"
            data-testid="chat-summary-watchlist"
            className="-mr-1 -mt-1 inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-secondary-text transition-colors hover:bg-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
            aria-label={watchlistLabel}
            aria-pressed={inWatchlist}
            disabled={watchlistPending}
            onClick={onToggleWatchlist}
          >
            <Star
              className={cn('h-4 w-4', inWatchlist ? 'fill-current text-amber-400' : '')}
              aria-hidden="true"
            />
          </button>
        ) : null}
      </div>
      <div
        className={cn(
          'mt-2 grid gap-x-4 gap-y-2',
          cellCount === 2 ? 'grid-cols-2' : cellCount === 3 ? 'grid-cols-3' : 'grid-cols-2 sm:grid-cols-4',
        )}
      >
        <SummaryCell
          label={(
            <>
              {t('chat.summary.price')}
              {quoteBadge ? <span className="ml-1 text-[10px] text-muted-text">{quoteBadge}</span> : null}
            </>
          )}
        >
          <Num kind="price" value={quote?.currentPrice} />
        </SummaryCell>
        <SummaryCell label={t('chat.summary.change')}>
          <Change value={quote?.changePercent}><Num kind="percent" value={quote?.changePercent} /></Change>
        </SummaryCell>
        {showResistance ? (
          <SummaryCell label={t('chat.summary.resistance')}><Num kind="price" value={structured?.resistance} /></SummaryCell>
        ) : null}
        {showSupport ? (
          <SummaryCell label={t('chat.summary.support')}><Num kind="price" value={structured?.support} /></SummaryCell>
        ) : null}
      </div>
      {structured?.conclusion ? (
        <p className="mt-2 text-sm leading-6 text-foreground">
          <span className="mr-1 text-secondary-text">{t('chat.summary.conclusion')}</span>
          {structured.conclusion}
        </p>
      ) : null}
      {structured?.invalidation ? (
        <p className="mt-1 text-xs leading-5 text-secondary-text">
          {t('chat.summary.invalidation')}：{structured.invalidation}
        </p>
      ) : null}
    </section>
  );
};
