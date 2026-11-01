import type { UiLanguage } from '../i18n/uiText';

// 基金頁改版（W11）新增的文案；舊的 funds.* 鍵仍在 uiText，這裡只放新版面用到的。
const zhTW = {
  addFund: '新增基金',
  dayPnl: '日損益',
  totalReturn: '累計',
  rowActions: '更多操作',
  rangeLabel: '走勢區間',
  myHolding: '我的持有',
  units: '單位',
  cost: '成本',
  pnl: '損益',
};

export type FundsText = typeof zhTW;

export const FUNDS_TEXT: Record<UiLanguage, FundsText> = {
  'zh-TW': zhTW,
  zh: {
    addFund: '新增基金',
    dayPnl: '日盈亏',
    totalReturn: '累计',
    rowActions: '更多操作',
    rangeLabel: '走势区间',
    myHolding: '我的持有',
    units: '单位',
    cost: '成本',
    pnl: '盈亏',
  },
  en: {
    addFund: 'Add fund',
    dayPnl: 'Day P/L',
    totalReturn: 'Total',
    rowActions: 'More actions',
    rangeLabel: 'Chart range',
    myHolding: 'My holding',
    units: 'units',
    cost: 'Cost',
    pnl: 'P/L',
  },
};
