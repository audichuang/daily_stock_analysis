import type { UiLanguage } from '../i18n/uiText';

// 盯盤清單與全站狀態列改版（W04）新增的文案；舊的 board.* 鍵仍在 uiText，這裡只放新版面用到的。
const zhTW = {
  attentionMore: '還有 {count} 檔',
  attentionMoveClosed: '漲跌 {pct}',
  dayPnlTw: '台股今日損益',
  dayPnlUs: '美股今日損益',
  dayPnlOther: '今日損益 {currency}',
  prevPnlTw: '台股上一交易日損益',
  prevPnlUs: '美股上一交易日損益',
  prevPnlOther: '上一交易日損益 {currency}',
  quoteFetchedAt: '報價抓取 {time}',
  breadthLoading: '載入中 {done}/{total}',
  mobileHolding: '{qty} 股 · {pnl}（{pct}）',
  mobileHoldingQty: '{qty} 股',
  statusBarAsOf: '行情 {time}',
};

export type BoardText = typeof zhTW;

export const BOARD_TEXT: Record<UiLanguage, BoardText> = {
  'zh-TW': zhTW,
  zh: {
    attentionMore: '还有 {count} 只',
    attentionMoveClosed: '涨跌 {pct}',
    dayPnlTw: '台股今日损益',
    dayPnlUs: '美股今日损益',
    dayPnlOther: '今日损益 {currency}',
    prevPnlTw: '台股上一交易日损益',
    prevPnlUs: '美股上一交易日损益',
    prevPnlOther: '上一交易日损益 {currency}',
    quoteFetchedAt: '报价抓取 {time}',
    breadthLoading: '加载中 {done}/{total}',
    mobileHolding: '{qty} 股 · {pnl}（{pct}）',
    mobileHoldingQty: '{qty} 股',
    statusBarAsOf: '行情 {time}',
  },
  en: {
    attentionMore: '+{count} more',
    attentionMoveClosed: 'Change {pct}',
    dayPnlTw: 'Day P/L (TW)',
    dayPnlUs: 'Day P/L (US)',
    dayPnlOther: 'Day P/L {currency}',
    prevPnlTw: 'Previous session P&L (TW)',
    prevPnlUs: 'Previous session P&L (US)',
    prevPnlOther: 'Previous session P&L {currency}',
    quoteFetchedAt: 'Quotes fetched {time}',
    breadthLoading: 'Loading {done}/{total}',
    mobileHolding: '{qty} sh · {pnl} ({pct})',
    mobileHoldingQty: '{qty} sh',
    statusBarAsOf: 'Quotes {time}',
  },
};
