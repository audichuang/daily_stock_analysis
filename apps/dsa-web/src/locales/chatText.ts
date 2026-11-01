import type { UiLanguage } from '../i18n/uiText';

// 問股頁改版（W13）新增的文案；舊的 chat.* 鍵仍在 uiText，這裡只放新版面用到的。
const zhTW = {
  skillSheetTitle: '策略',
  skillDone: '完成',
  skillClear: '清除選擇',
  historyClose: '關閉歷史對話',
  exportMarkdown: '匯出 Markdown',
  pushToNotify: '推送到通知',
  live: '即時',
  watchlistAdd: '加入自選',
  watchlistRemove: '移出自選',
  undo: '復原',
};

export type ChatText = typeof zhTW;

export const CHAT_TEXT: Record<UiLanguage, ChatText> = {
  'zh-TW': zhTW,
  zh: {
    skillSheetTitle: '策略',
    skillDone: '完成',
    skillClear: '清除选择',
    historyClose: '关闭历史对话',
    exportMarkdown: '导出 Markdown',
    pushToNotify: '推送到通知',
    live: '实时',
    watchlistAdd: '加入自选',
    watchlistRemove: '移出自选',
    undo: '撤销',
  },
  en: {
    skillSheetTitle: 'Strategies',
    skillDone: 'Done',
    skillClear: 'Clear selection',
    historyClose: 'Close chat history',
    exportMarkdown: 'Export Markdown',
    pushToNotify: 'Push to notifications',
    live: 'Live',
    watchlistAdd: 'Add to watchlist',
    watchlistRemove: 'Remove from watchlist',
    undo: 'Undo',
  },
};
