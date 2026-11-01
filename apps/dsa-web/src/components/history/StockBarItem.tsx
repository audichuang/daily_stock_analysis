import type React from 'react';
import { Badge, Change } from '../common';
import type { StockQuote } from '../../api/stocks';
import type { StockBarItem as StockBarItemType } from '../../types/analysis';
import { buildDecisionActionLabelMap, getDecisionActionLabel, getDecisionActionTone, type DecisionActionTone } from '../../utils/decisionAction';
import { formatPercent, formatPrice } from '../../utils/format';
import { getStockRowLabels } from '../../utils/stockName';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { HOME_TEXT, formatMonthDay } from '../../locales/homeText';

interface StockBarItemProps {
  item: StockBarItemType;
  isViewing: boolean;
  onClick: (recordId: number) => void;
  isMarketReview?: boolean;
  /** 批次行情的現價；沒有就顯示 —，analysisPrice 不能拿來當現價。 */
  quote?: StockQuote;
  /** 大盤複盤列的燈號，例如「台股 紅燈」。 */
  marketLightLabel?: string;
  /** 大盤複盤列標題裡的市場，例如「美股」；沒給就只寫日期。 */
  marketReviewRegionLabel?: string;
}

// Only buy/add (brand) and reduce/sell (caution) get a fill; neutral and unknown actions are muted text.
const ACTION_TAG_VARIANT: Record<DecisionActionTone, 'brand' | 'neutral' | 'caution'> = {
  brand: 'brand',
  neutral: 'neutral',
  caution: 'caution',
  default: 'neutral',
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
      variant={ACTION_TAG_VARIANT[getDecisionActionTone(item?.action, item?.actionLabel, item?.operationAdvice)]}
      size="sm"
      className="shrink-0 shadow-none text-[11px] font-semibold leading-none"
    >
      {label} {score}
    </Badge>
  );
};

/**
 * 52px 清單列的兩行：股名與現價／代號、漲跌％與動作分數。三個頁籤共用。
 * 沒有行情時第一行價格位置改放分析時價（muted，標「分析時」），第二行只剩代號與動作。
 */
export const StockRowLines: React.FC<{
  code: string;
  name?: string | null;
  quote?: StockQuote;
  analysisPrice?: number | null;
  item?: StockBarItemType;
  trailing?: React.ReactNode;
}> = ({ code, name, quote, analysisPrice, item, trailing }) => {
  const { language } = useUiLanguage();
  const homeText = HOME_TEXT[language];
  const { primary, secondary } = getStockRowLabels(code, name);
  const hasQuote = typeof quote?.currentPrice === 'number';
  const showAnalysisPrice = !hasQuote && typeof analysisPrice === 'number';
  return (
    <div className="min-w-0 flex-1">
      <div className="flex min-w-0 items-baseline justify-between gap-2">
        <span className="min-w-0 truncate text-sm font-semibold text-foreground tracking-tight">{primary}</span>
        {showAnalysisPrice ? (
          <span className="shrink-0 text-xs tabular-nums text-muted-text" data-testid="stock-row-price">
            {formatPrice(analysisPrice)} · {homeText.analysisPriceSuffix}
          </span>
        ) : (
          <span className="shrink-0 text-sm font-semibold tabular-nums text-foreground" data-testid="stock-row-price">
            {formatPrice(hasQuote ? quote?.currentPrice : null)}
          </span>
        )}
      </div>
      <div className="mt-0.5 flex min-w-0 items-center justify-between gap-2" data-testid="history-card-meta">
        <span className="min-w-0 truncate text-[11px] text-secondary-text">{secondary}</span>
        <span className="flex shrink-0 items-center gap-1.5" data-testid="history-card-actions">
          {hasQuote ? (
            <Change value={quote?.changePercent} className="text-[11px] font-medium">
              {formatPercent(quote?.changePercent)}
            </Change>
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
  marketReviewRegionLabel,
}) => {
  const { t, language } = useUiLanguage();
  const stockName = item.stockName || item.stockCode;
  const marketReviewTitle = [
    HOME_TEXT[language].latestReview,
    [marketReviewRegionLabel, formatMonthDay(item.lastAnalysisTime)].filter(Boolean).join(' '),
  ].filter(Boolean).join(' · ');

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
              <span className="block truncate text-sm font-semibold text-foreground tracking-tight" data-testid="market-review-title">
                {marketReviewTitle}
              </span>
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
