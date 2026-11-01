import type { UiLanguage, UiTextKey, UiTextParams } from '../i18n/uiText';
import type { SetupStatusCheck } from '../types/systemConfig';

type TranslateFn = (key: UiTextKey, params?: UiTextParams) => string;

// 後端 message_code 對應的文案；查無 code 時顯示後端 message。
const SETUP_MESSAGE_KEYS: Record<string, UiTextKey> = {
  'storage.app_db.connected': 'settings.setupMessage.storageConnected',
  'storage.app_db.running_sqlite': 'settings.setupMessage.storageRunningSqlite',
  'storage.app_db.unreachable': 'settings.setupMessage.storageUnreachable',
};

// 後端標題只有簡中，繁中介面依穩定的 check.key 查表；未知的 key 顯示後端 title。
const SETUP_TITLE_ZH_TW: Record<string, string> = {
  llm_primary: '模型主管道',
  llm_agent: 'Agent 管道',
  stock_list: '自選',
  notification: '通知管道',
  storage: '資料庫與本機儲存',
};

/** 依 message_code 組句；params 經 toCamelCase 後鍵名是 camelCase（error_type 變 errorType）。 */
export function getSetupCheckMessage(check: SetupStatusCheck, t: TranslateFn): string {
  const key = check.messageCode ? SETUP_MESSAGE_KEYS[check.messageCode] : undefined;
  return key ? t(key, check.messageParams) : check.message;
}

export function getSetupCheckTitle(check: SetupStatusCheck, language: UiLanguage): string {
  return (language === 'zh-TW' && SETUP_TITLE_ZH_TW[check.key]) || check.title;
}
