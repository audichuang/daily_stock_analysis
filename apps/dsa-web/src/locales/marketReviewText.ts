import type { UiLanguage } from '../i18n/uiText';

// W07：大盤複盤頁、首頁複盤觸發鈕、個股報告標題列與護欄呈現新增的文案。
const zhTW = {
  // 首頁複盤觸發鈕
  viewReview: '看複盤',
  generateReview: '產生複盤…',
  generateConfirmTitle: '產生大盤複盤',
  generateConfirmMessage: '將產生 {region} 複盤，約 {minutes} 分鐘',
  generateConfirmAction: '產生',
  // 大盤複盤頁
  overviewSection: '摘要',
  fullReport: '完整報告',
  lightCaution: '警戒',
  lightNeutral: '中性',
  lightTailwind: '順風',
  sentimentShort: '情緒',
  // 個股報告：護欄
  modelIntent: '模型原意：{sentence}',
  guardrailDataTag: '護欄：資料缺，動作降為{action}',
  guardrailMarketTag: '護欄已調整',
  guardrailVersion: '護欄版結論：{sentence}',
  modelOriginal: '模型原本建議：{sentence}',
  // 個股報告：關鍵價位條
  keyLevels: '關鍵價位',
  levelEntry: '進場',
  levelStop: '停損',
  levelRebound: '反彈減碼',
  stopChange: '停損 {from} → {to}',
  previousStop: '前份停損 {value}',
  // 分享鈕
  shareReadyToast: '分享圖已準備好，再按一次「分享」送出',
  // 板塊英文名稱對照（yfinance 等英文來源）
  boardNames: {
    Technology: '科技',
    'Information Technology': '資訊科技',
    Semiconductors: '半導體',
    'Financial Services': '金融服務',
    Financials: '金融',
    Healthcare: '醫療保健',
    'Health Care': '醫療保健',
    'Consumer Cyclical': '非必需消費',
    'Consumer Discretionary': '非必需消費',
    'Consumer Defensive': '必需消費',
    'Consumer Staples': '必需消費',
    Industrials: '工業',
    Energy: '能源',
    'Basic Materials': '原物料',
    Materials: '原物料',
    'Communication Services': '通訊服務',
    Utilities: '公用事業',
    'Real Estate': '不動產',
  } as Record<string, string>,
};

export type MarketReviewUiText = typeof zhTW;

export const MARKET_REVIEW_UI_TEXT: Record<UiLanguage, MarketReviewUiText> = {
  'zh-TW': zhTW,
  zh: {
    viewReview: '看复盘',
    generateReview: '产生复盘…',
    generateConfirmTitle: '产生大盘复盘',
    generateConfirmMessage: '将产生 {region} 复盘，约 {minutes} 分钟',
    generateConfirmAction: '产生',
    overviewSection: '摘要',
    fullReport: '完整报告',
    lightCaution: '警戒',
    lightNeutral: '中性',
    lightTailwind: '顺风',
    sentimentShort: '情绪',
    modelIntent: '模型原意：{sentence}',
    guardrailDataTag: '护栏：数据缺，动作降为{action}',
    guardrailMarketTag: '护栏已调整',
    guardrailVersion: '护栏版结论：{sentence}',
    modelOriginal: '模型原本建议：{sentence}',
    keyLevels: '关键价位',
    levelEntry: '进场',
    levelStop: '停损',
    levelRebound: '反弹减仓',
    stopChange: '停损 {from} → {to}',
    previousStop: '前份停损 {value}',
    shareReadyToast: '分享图已准备好，再按一次「分享」发送',
    boardNames: {
      Technology: '科技',
      'Information Technology': '信息技术',
      Semiconductors: '半导体',
      'Financial Services': '金融服务',
      Financials: '金融',
      Healthcare: '医疗保健',
      'Health Care': '医疗保健',
      'Consumer Cyclical': '可选消费',
      'Consumer Discretionary': '可选消费',
      'Consumer Defensive': '必需消费',
      'Consumer Staples': '必需消费',
      Industrials: '工业',
      Energy: '能源',
      'Basic Materials': '原材料',
      Materials: '原材料',
      'Communication Services': '通信服务',
      Utilities: '公用事业',
      'Real Estate': '房地产',
    },
  },
  en: {
    viewReview: 'View review',
    generateReview: 'Generate review…',
    generateConfirmTitle: 'Generate market review',
    generateConfirmMessage: 'This generates a {region} review and takes about {minutes} min.',
    generateConfirmAction: 'Generate',
    overviewSection: 'Summary',
    fullReport: 'Full report',
    lightCaution: 'Caution',
    lightNeutral: 'Neutral',
    lightTailwind: 'Tailwind',
    sentimentShort: 'Sentiment',
    modelIntent: 'Model view: {sentence}',
    guardrailDataTag: 'Guardrail: data missing, action lowered to {action}',
    guardrailMarketTag: 'Guardrail adjusted',
    guardrailVersion: 'Guardrail version: {sentence}',
    modelOriginal: 'Model originally suggested: {sentence}',
    keyLevels: 'Key levels',
    levelEntry: 'Entry',
    levelStop: 'Stop',
    levelRebound: 'Trim on bounce',
    stopChange: 'Stop {from} → {to}',
    previousStop: 'Previous stop {value}',
    shareReadyToast: 'Share image ready. Press Share again to send it.',
    boardNames: {},
  },
};

/** 報告語言含 ko，這份文案沒有韓文，退回英文。 */
export const getMarketReviewUiText = (language?: string | null): MarketReviewUiText => {
  if (language === 'zh' || language === 'zh-TW' || language === 'en') {
    return MARKET_REVIEW_UI_TEXT[language];
  }
  return MARKET_REVIEW_UI_TEXT.en;
};
