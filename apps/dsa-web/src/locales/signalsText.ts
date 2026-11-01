import type { UiLanguage } from '../i18n/uiText';

// AI 建議頁與回測頁 UI 打磨（W12）新增的文案；舊的 decisionSignals.* 鍵仍在 uiText。
const zhTW = {
  // AI 建議
  statsSentence: '過去訊號命中率 {rate}（可判定 {decidable} 筆中命中 {hit} 筆）・另有 {unable} 筆尚無法評估',
  stockPlaceholder: '代號或名稱',
  remainingDays: '有效 {count} 天',
  heldHint: '持股中',
  holdingChip: '持股',
  stopTriggeredChip: '已觸停損',
  removeFilter: '移除篩選：{label}',
  headerHoldingAction: '持股中待{action} {count} 檔',
  headerHolding: '持股中 {count} 檔',
  headerStopTriggered: '已觸停損 {count} 檔',
  // 回測
  winLossHint: '{win} 勝／{loss} 負／{neutral} 平',
  smallSample: '樣本少',
  dateFrom: '起',
  dateTo: '迄',
  chartLineMode: '比較線',
  chartSimulatedOnly: '只看模擬',
  chartWithStock: '加上個股',
  monthTick: '{month}月',
};

export type SignalsText = typeof zhTW;

export const SIGNALS_TEXT: Record<UiLanguage, SignalsText> = {
  'zh-TW': zhTW,
  zh: {
    statsSentence: '过去信号命中率 {rate}（可判定 {decidable} 笔中命中 {hit} 笔）・另有 {unable} 笔尚无法评估',
    stockPlaceholder: '代码或名称',
    remainingDays: '剩 {count} 天',
    heldHint: '持股中',
    holdingChip: '持股',
    stopTriggeredChip: '已触停损',
    removeFilter: '移除筛选：{label}',
    headerHoldingAction: '持股中待{action} {count} 档',
    headerHolding: '持股中 {count} 档',
    headerStopTriggered: '已触停损 {count} 档',
    winLossHint: '{win} 胜／{loss} 负／{neutral} 平',
    smallSample: '样本少',
    dateFrom: '起',
    dateTo: '止',
    chartLineMode: '对比线',
    chartSimulatedOnly: '只看模拟',
    chartWithStock: '加上个股',
    monthTick: '{month}月',
  },
  en: {
    statsSentence: 'Past hit rate {rate} ({hit} of {decidable} decidable) · {unable} more not yet evaluable',
    stockPlaceholder: 'Code or name',
    remainingDays: '{count}d left',
    heldHint: 'Held',
    holdingChip: 'Held',
    stopTriggeredChip: 'Stop hit',
    removeFilter: 'Remove filter: {label}',
    headerHoldingAction: '{count} held to {action}',
    headerHolding: '{count} held',
    headerStopTriggered: '{count} stop hit',
    winLossHint: '{win} W / {loss} L / {neutral} flat',
    smallSample: 'Small sample',
    dateFrom: 'From',
    dateTo: 'To',
    chartLineMode: 'Compare line',
    chartSimulatedOnly: 'Simulated only',
    chartWithStock: 'With stock',
    monthTick: '{monthShort}',
  },
};
