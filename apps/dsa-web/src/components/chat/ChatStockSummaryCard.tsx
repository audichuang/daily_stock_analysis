import type React from 'react';
import type { ActiveStockContext, StructuredAnswer } from '../../api/agent';
import type { StockQuote } from '../../api/stocks';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Change, Num } from '../common';

interface ChatStockSummaryCardProps {
  stock: ActiveStockContext;
  quote: StockQuote | null;
  structured?: StructuredAnswer | null;
}

const SummaryCell: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="min-w-0">
    <p className="text-xs text-secondary-text">{label}</p>
    <p className="mt-0.5 text-sm font-semibold text-foreground">{children}</p>
  </div>
);

/** 回答上方的個股摘要：現價與漲跌來自行情，結論與壓力支撐來自模型給的結構化值，缺值顯示 —。 */
export const ChatStockSummaryCard: React.FC<ChatStockSummaryCardProps> = ({ stock, quote, structured }) => {
  const { t } = useUiLanguage();
  const name = stock.stock_name || quote?.stockName;
  return (
    <section
      data-testid="chat-stock-summary"
      aria-label={t('chat.summary.label')}
      className="mb-3 rounded-xl border border-border/60 bg-card/70 p-3"
    >
      <p className="truncate text-sm font-semibold text-foreground">
        {name ? `${name} · ` : ''}
        <span className="font-normal text-secondary-text">{stock.stock_code}</span>
      </p>
      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        <SummaryCell label={t('chat.summary.price')}><Num kind="price" value={quote?.currentPrice} /></SummaryCell>
        <SummaryCell label={t('chat.summary.change')}>
          <Change value={quote?.changePercent}><Num kind="percent" value={quote?.changePercent} /></Change>
        </SummaryCell>
        <SummaryCell label={t('chat.summary.resistance')}><Num kind="price" value={structured?.resistance} /></SummaryCell>
        <SummaryCell label={t('chat.summary.support')}><Num kind="price" value={structured?.support} /></SummaryCell>
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
