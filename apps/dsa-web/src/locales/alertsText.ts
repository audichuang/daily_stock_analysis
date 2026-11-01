import type { UiLanguage } from '../i18n/uiText';

// 警報頁 W14 新增的文案；舊的 ALERT_PAGE_TEXT／ALERT_FORM_TEXT 仍在 featureText，這裡只放新版面用到的。
const zhTW = {
  noChannelTitle: '通知還沒設定',
  noChannelBody: '規則觸發時不會推播，先到設定加一個通知管道。',
  goSettings: '去設定',
  tplPriceHint: '指定價位，站上或跌破時提醒',
  tplChangeHint: '單日跌幅達 3% 時提醒',
  tplMarketHint: '台股大盤信號轉紅燈時提醒',
  skippedHint: '略過 {count}',
  activityTabs: '動態分類',
  chipCurrent: '現價',
  chipUp: '+5% {price}',
  chipDown: '−5% {price}',
  chipGroup: '快速填入價位',
  pricePlaceholder: '例如 2,500',
  pickedName: '已選：{name}',
};

export type AlertsText = typeof zhTW;

export const ALERTS_TEXT: Record<UiLanguage, AlertsText> = {
  'zh-TW': zhTW,
  zh: {
    noChannelTitle: '通知还没设置',
    noChannelBody: '规则触发时不会推送，先到设置添加一个通知渠道。',
    goSettings: '去设置',
    tplPriceHint: '指定价位，站上或跌破时提醒',
    tplChangeHint: '单日跌幅达 3% 时提醒',
    tplMarketHint: '台股大盘信号转红灯时提醒',
    skippedHint: '跳过 {count}',
    activityTabs: '动态分类',
    chipCurrent: '现价',
    chipUp: '+5% {price}',
    chipDown: '−5% {price}',
    chipGroup: '快速填入价位',
    pricePlaceholder: '例如 2,500',
    pickedName: '已选：{name}',
  },
  en: {
    noChannelTitle: 'Notifications are not set up',
    noChannelBody: 'Triggered rules will not push anything. Add a notification channel in Settings first.',
    goSettings: 'Open settings',
    tplPriceHint: 'Alert when the price crosses a level',
    tplChangeHint: 'Alert on a 3% daily drop',
    tplMarketHint: 'Alert when the Taiwan market light turns red',
    skippedHint: '{count} skipped',
    activityTabs: 'Activity type',
    chipCurrent: 'Current',
    chipUp: '+5% {price}',
    chipDown: '−5% {price}',
    chipGroup: 'Quick-fill price',
    pricePlaceholder: 'e.g. 2,500',
    pickedName: 'Selected: {name}',
  },
};
