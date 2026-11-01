import type { UiLanguage } from '../i18n/uiText';

// 資產頁數字修正（W09）新增的文案；舊的 portfolio.* 鍵仍在 featureText。
const zhTW = {
  weightFxStale: '匯率過期',
  dayPnlOn: '{date} 損益',
  marketClosed: '台美股休市',
  dayBreakdown: '股票 {stock}／基金 {fund}',
  approx: '≈ {amount}',
  shares: '{quantity} 股',
  dividendPerShare: '每股 {amount}',
  splitRatio: '比例 {ratio}',
};

export type PortfolioW09Text = typeof zhTW;

export const PORTFOLIO_W09_TEXT: Record<UiLanguage, PortfolioW09Text> = {
  'zh-TW': zhTW,
  zh: {
    weightFxStale: '汇率过期',
    dayPnlOn: '{date} 损益',
    marketClosed: '台美股休市',
    dayBreakdown: '股票 {stock}／基金 {fund}',
    approx: '≈ {amount}',
    shares: '{quantity} 股',
    dividendPerShare: '每股 {amount}',
    splitRatio: '比例 {ratio}',
  },
  en: {
    weightFxStale: 'Stale FX',
    dayPnlOn: '{date} P/L',
    marketClosed: 'TW/US markets closed',
    dayBreakdown: 'Stocks {stock} / Funds {fund}',
    approx: '≈ {amount}',
    shares: '{quantity} sh',
    dividendPerShare: 'Per share {amount}',
    splitRatio: 'Ratio {ratio}',
  },
};
