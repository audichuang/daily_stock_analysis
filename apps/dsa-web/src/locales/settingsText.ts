import type { UiLanguage } from '../i18n/uiText';

// 設定頁版面整理新增的文案（W16）；既有的 settings.* 鍵仍在 uiText。
const zhTW = {
  importConfirmCleanTitle: '匯入 .env 會覆蓋已儲存的設定',
  importConfirmCleanMessage: '匯入會立即用備份檔案中的鍵值更新已儲存的設定，無法自動復原。需要的話請先匯出目前的設定備份。',
};

export type SettingsText = typeof zhTW;

export const SETTINGS_TEXT: Record<UiLanguage, SettingsText> = {
  'zh-TW': zhTW,
  zh: {
    importConfirmCleanTitle: '导入 .env 会覆盖已保存的配置',
    importConfirmCleanMessage: '导入会立即用备份文件中的键值更新已保存的配置，无法自动恢复。需要的话请先导出当前配置备份。',
  },
  en: {
    importConfirmCleanTitle: 'Importing .env overwrites saved settings',
    importConfirmCleanMessage: 'Importing immediately updates saved configuration with keys from the backup file and cannot be undone automatically. Export a backup of the current settings first if you need one.',
  },
};
