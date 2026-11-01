import { formatUiText, type UiLanguage, type UiTextParams } from '../i18n/uiText';

// 首頁左欄清單與今日總覽（W08）新增的文案；既有的 watchlist.* / overview.* 仍在 uiText。
const zhTW = {
  tabHistory: '紀錄',
  listTitle: '清單',
  closeList: '關閉清單',
  watchlistSubline: '{count} 檔 · 今日 {done}/{count} 已分析',
  todaySubline: '{count} 筆 · 自選 {done}/{total} 已分析 · 最高分 {score}',
  historySubline: '{count} 筆紀錄',
  analyzePendingSplit: '分析未完成 {count}',
  analyzeMenuAria: '更多分析選項',
  analyzeMenuAll: '分析全部',
  analyzeMenuPending: '僅分析未完成',
  latestReview: '最新複盤',
  analysisPriceSuffix: '分析時',
  verdictTitle: '今日判讀',
  verdictAria: '開啟最新大盤複盤',
  verdictClose: '{market} {date} 收盤',
  verdictKeyLevels: '關鍵價 {levels}',
  stanceOffensive: '進攻',
  stanceBalanced: '平衡',
  stanceDefensive: '防守',
  dayPnlLabel: '股票今日損益（台＋美，折台幣）',
  todayUpdated: '今日已更新',
  todayUpdatedEmpty: '今天還沒有更新的分析',
  viewAll: '看全部 →',
  indexDji: '道瓊',
  marketTw: '台股',
  marketUs: '美股',
};

export type HomeText = typeof zhTW;

export const HOME_TEXT: Record<UiLanguage, HomeText> = {
  'zh-TW': zhTW,
  zh: {
    tabHistory: '记录',
    listTitle: '清单',
    closeList: '关闭清单',
    watchlistSubline: '{count} 只 · 今日 {done}/{count} 已分析',
    todaySubline: '{count} 条 · 自选 {done}/{total} 已分析 · 最高分 {score}',
    historySubline: '{count} 条记录',
    analyzePendingSplit: '分析未完成 {count}',
    analyzeMenuAria: '更多分析选项',
    analyzeMenuAll: '分析全部',
    analyzeMenuPending: '仅分析未完成',
    latestReview: '最新复盘',
    analysisPriceSuffix: '分析时',
    verdictTitle: '今日判读',
    verdictAria: '打开最新大盘复盘',
    verdictClose: '{market} {date} 收盘',
    verdictKeyLevels: '关键价 {levels}',
    stanceOffensive: '进攻',
    stanceBalanced: '平衡',
    stanceDefensive: '防守',
    dayPnlLabel: '股票今日损益（台＋美，折台币）',
    todayUpdated: '今日已更新',
    todayUpdatedEmpty: '今天还没有更新的分析',
    viewAll: '看全部 →',
    indexDji: '道琼',
    marketTw: '台股',
    marketUs: '美股',
  },
  en: {
    tabHistory: 'History',
    listTitle: 'List',
    closeList: 'Close list',
    watchlistSubline: '{count} stocks · {done}/{count} analyzed today',
    todaySubline: '{count} items · watchlist {done}/{total} analyzed · top score {score}',
    historySubline: '{count} records',
    analyzePendingSplit: 'Analyze pending {count}',
    analyzeMenuAria: 'More analysis options',
    analyzeMenuAll: 'Analyze all',
    analyzeMenuPending: 'Pending only',
    latestReview: 'Latest review',
    analysisPriceSuffix: 'at analysis',
    verdictTitle: "Today's read",
    verdictAria: 'Open the latest market review',
    verdictClose: '{market} {date} close',
    verdictKeyLevels: 'Key levels {levels}',
    stanceOffensive: 'Offensive',
    stanceBalanced: 'Balanced',
    stanceDefensive: 'Defensive',
    dayPnlLabel: "Stocks today's P&L (TW + US, in TWD)",
    todayUpdated: 'Updated today',
    todayUpdatedEmpty: 'No analysis updated today yet',
    viewAll: 'View all →',
    indexDji: 'Dow',
    marketTw: 'TW',
    marketUs: 'US',
  },
};

/** Interpolates `{name}` placeholders the same way uiText does. */
export const formatHomeText = (template: string, params?: UiTextParams): string => formatUiText(template, params);

/** MM/DD from an ISO date or datetime; empty string when unparsable. */
export const formatMonthDay = (value?: string | null): string => {
  if (!value) return '';
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (dateOnly) return `${dateOnly[2]}/${dateOnly[3]}`;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return `${String(parsed.getMonth() + 1).padStart(2, '0')}/${String(parsed.getDate()).padStart(2, '0')}`;
};
