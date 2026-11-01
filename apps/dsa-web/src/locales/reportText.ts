import type { UiLanguage } from '../i18n/uiText';
import type { DecisionAction } from '../types/analysis';

// Strings added by the report-body polish (W06). Report components take ReportLanguage,
// which also has 'ko'; getReportPolishText falls back to English for it.
const zhTW = {
  // FinancialsPanel
  financialsShowAll: '看全部指標',
  // StockPriceChart
  chartReboundReduce: '反彈減碼',
  unitWan: '萬',
  unitYi: '億',
  unitLots: '張',
  unitShares: '股',
  unitTimes: '倍',
  // ReportStrategy
  setAlert: '設警報',
  setAlertFor: '為 {label} {price} 設警報',
  ladderStopShort: '風控',
  ladderCurrentShort: '現價',
  ladderReduceShort: '減碼',
  ladderTargetShort: '目標',
  // ReportEventOutlook
  outlookConfidence: '信心',
  colon: '：',
  outlookScenariosToggle: '仍想看三種情況',
  outlookDetailsToggle: '看依據與細節',
};

export type ReportPolishText = typeof zhTW;

export const REPORT_POLISH_TEXT: Record<UiLanguage, ReportPolishText> = {
  'zh-TW': zhTW,
  zh: {
    financialsShowAll: '看全部指标',
    chartReboundReduce: '反弹减码',
    unitWan: '万',
    unitYi: '亿',
    unitLots: '张',
    unitShares: '股',
    unitTimes: '倍',
    setAlert: '设警报',
    setAlertFor: '为 {label} {price} 设警报',
    ladderStopShort: '风控',
    ladderCurrentShort: '现价',
    ladderReduceShort: '减码',
    ladderTargetShort: '目标',
    outlookConfidence: '信心',
    colon: '：',
    outlookScenariosToggle: '仍想看三种情况',
    outlookDetailsToggle: '看依据与细节',
  },
  en: {
    financialsShowAll: 'Show all metrics',
    chartReboundReduce: 'Reduce on bounce',
    // English compacts with K/M/B in StockPriceChart; these two stay unused there.
    unitWan: '',
    unitYi: '',
    unitLots: 'lots',
    unitShares: 'shares',
    unitTimes: 'x',
    setAlert: 'Set alert',
    setAlertFor: 'Set an alert for {label} {price}',
    ladderStopShort: 'Risk',
    ladderCurrentShort: 'Price',
    ladderReduceShort: 'Reduce',
    ladderTargetShort: 'Target',
    outlookConfidence: 'Confidence',
    colon: ': ',
    outlookScenariosToggle: 'Still want the three scenarios',
    outlookDetailsToggle: 'Show reasoning and details',
  },
};

/** Resolve report-language codes (including 'ko') to one of the three UI locales. */
export const getReportPolishText = (language?: string | null): ReportPolishText => {
  if (language === 'zh' || language === 'zh-TW' || language === 'en') {
    return REPORT_POLISH_TEXT[language];
  }
  return REPORT_POLISH_TEXT.en;
};

/**
 * Actions whose takeProfit level means "reduce on a bounce" rather than an upside target.
 * Shared by the level cards' ladder and the price chart's target line label.
 */
export const reducesOnBounce = (action: DecisionAction | null | undefined): boolean =>
  action === 'reduce' || action === 'sell' || action === 'watch' || action === 'avoid' || action === 'alert';
