import type React from 'react';
import { Badge, Change } from '../common';
import type { StockQuote } from '../../api/stocks';
import type { StockBarItem as StockBarItemType } from '../../types/analysis';
import { buildDecisionActionLabelMap, getDecisionActionLabel, getDecisionActionTone, type DecisionActionTone } from '../../utils/decisionAction';
import { formatPercent, formatPrice } from '../../utils/format';
import { getStockRowLabels } from '../../utils/stockName';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

interface StockBarItemProps {
  item: StockBarItemType;
  isViewing: boolean;
  onClick: (recordId: number) => void;
  isMarketReview?: boolean;
  /** 批次行情的現價；沒有就顯示 —，analysisPrice 不能拿來當現價。 */
  quote?: StockQuote;
  /** 大盤複盤列的燈號，例如「台股 紅燈」。 */
  marketLightLabel?: string;
}

const ACTION_TAG_CLASS: Record<DecisionActionTone, string> = {
  brand: 'border-primary/30 bg-primary/10 text-primary',
  neutral: 'border-subtle bg-base/40 text-secondary-text',
  caution: 'border-warning/30 bg-warning/10 text-warning',
  default: 'border-subtle bg-base/40 text-secondary-text',
};

/** 動作＋分數小標；動作一律依結構化枚舉查表。 */
export const StockActionTag: React.FC<{ item?: StockBarItemType }> = ({ item }) => {
  const { t } = useUiLanguage();
  const score = typeof item?.sentimentScore === 'number' ? item.sentimentScore : null;
  if (score === null) {
    return null;
  }
  const label = getDecisionActionLabel(
    item?.action,
    item?.actionLabel,
    item?.operationAdvice,
    t('history.sentiment'),
    buildDecisionActionLabelMap(t),
  );
  return (
    <Badge
      variant="default"
      size="sm"
      className={`shrink-0 shadow-none text-[11px] font-semibold leading-none ${ACTION_TAG_CLASS[getDecisionActionTone(item?.action, item?.actionLabel, item?.operationAdvice)]}`}
    >
      {label} {score}
    </Badge>
  );
};

/** 52px 清單列的兩行：股名與現價／代號、漲跌％與動作分數。三個頁籤共用。 */
export const StockRowLines: React.FC<{
  code: string;
  name?: string | null;
  quote?: StockQuote;
  analysisPrice?: number | null;
  item?: StockBarItemType;
  trailing?: React.ReactNode;
}> = ({ code, name, quote, analysisPrice, item, trailing }) => {
  const { t } = useUiLanguage();
  const { primary, secondary } = getStockRowLabels(code, name);
  const hasQuote = typeof quote?.currentPrice === 'number';
  return (
    <div className="min-w-0 flex-1">
      <div className="flex min-w-0 items-baseline justify-between gap-2">
        <span className="min-w-0 truncate text-sm font-semibold text-foreground tracking-tight">{primary}</span>
        <span className="shrink-0 text-sm font-semibold tabular-nums text-foreground" data-testid="stock-row-price">
          {formatPrice(hasQuote ? quote?.currentPrice : null)}
        </span>
      </div>
      <div className="mt-0.5 flex min-w-0 items-center justify-between gap-2" data-testid="history-card-meta">
        <span className="min-w-0 truncate text-[11px] text-secondary-text">{secondary}</span>
        <span className="flex shrink-0 items-center gap-1.5" data-testid="history-card-actions">
          {hasQuote ? (
            <Change value={quote?.changePercent} className="text-[11px] font-medium">
              {formatPercent(quote?.changePercent)}
            </Change>
          ) : typeof analysisPrice === 'number' ? (
            <span className="text-[11px] tabular-nums text-muted-text">
              {t('stockBar.analysisPriceTag', { price: formatPrice(analysisPrice) })}
            </span>
          ) : null}
          <StockActionTag item={item} />
          {trailing}
        </span>
      </div>
    </div>
  );
};

export const StockBarItemComponent: React.FC<StockBarItemProps> = ({
  item,
  isViewing,
  onClick,
  isMarketReview = false,
  quote,
  marketLightLabel,
}) => {
  const { t } = useUiLanguage();
  const stockName = item.stockName || item.stockCode;

  return (
    <button
      type="button"
      onClick={() => onClick(item.id)}
      aria-label={isMarketReview
        ? t('stockBar.marketItemAria', { name: stockName })
        : t('history.itemAria', { name: stockName, code: item.stockCode })}
      className={`home-history-item min-h-[52px] w-full min-w-0 flex-1 text-left px-2.5 py-1.5 group/item ${
        isViewing ? 'home-history-item-selected' : ''
      }`}
    >
      <div className="relative z-10 flex items-center gap-2.5">
        {isMarketReview ? (
          <>
            <div className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold text-foreground tracking-tight">{stockName}</span>
              <span className="mt-0.5 block truncate text-[11px] text-secondary-text" data-testid="market-review-light">
                {marketLightLabel || t('stockBar.market')}
              </span>
            </div>
          </>
        ) : (
          <StockRowLines
            code={item.stockCode}
            name={item.stockName}
            quote={quote}
            analysisPrice={item.analysisPrice}
            item={item}
          />
        )}
      </div>
    </button>
  );
};
