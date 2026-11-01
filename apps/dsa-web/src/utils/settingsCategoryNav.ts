import type { UiLanguage, UiTextKey, UiTextParams } from '../i18n/uiText';
import type { SystemConfigItem } from '../types/systemConfig';
import { countConfiguredNotificationChannels } from './notificationChannels';
import { parseStockListValue } from './stockList';
import { getFieldDescriptionForLocale, getFieldTitleForLocale } from './systemConfigI18n';

type TranslateFn = (key: UiTextKey, params?: UiTextParams) => string;

// 依日常使用頻率排序，與後端 display_order 無關。
const CATEGORY_ORDER = ['base', 'notification', 'ai_model', 'data_source', 'agent', 'backtest', 'system', 'uncategorized'];

export function orderSettingsCategories<T extends { category: string }>(categories: T[]): T[] {
  const rank = (category: string) => {
    const index = CATEGORY_ORDER.indexOf(category);
    return index === -1 ? CATEGORY_ORDER.length : index;
  };
  return [...categories].sort((left, right) => rank(left.category) - rank(right.category));
}

function configValue(items: SystemConfigItem[], key: string): string {
  return String(items.find((item) => item.key === key)?.value ?? '').trim();
}

function switchStatus(items: SystemConfigItem[], key: string, t: TranslateFn): string {
  return t(configValue(items, key).toLowerCase() === 'true' ? 'common.enabled' : 'common.disabled');
}

/** 分類列右側的狀態值。 */
export function getSettingsCategoryStatus(category: string, items: SystemConfigItem[], t: TranslateFn): string {
  switch (category) {
    case 'base':
      return t('settings.categoryStatusStocks', { count: parseStockListValue(configValue(items, 'STOCK_LIST')).length });
    case 'notification': {
      const count = countConfiguredNotificationChannels(items);
      return count > 0 ? t('settings.categoryStatusChannels', { count }) : t('settings.categoryStatusNotSet');
    }
    case 'ai_model': {
      const count = configValue(items, 'LLM_CHANNELS').split(',').filter((name) => name.trim()).length;
      if (count > 0) return t('settings.categoryStatusChannels', { count });
      // 本機 CLI、單一金鑰或舊式 provider 設定都不經管道清單，不能因此顯示未設定。
      const backend = configValue(items, 'GENERATION_BACKEND');
      const hasOtherSource = (backend !== '' && backend !== 'litellm')
        || ['LITELLM_MODEL', 'LITELLM_CONFIG'].some((key) => configValue(items, key) !== '')
        || items.some((item) => /_KEYS?$/.test(item.key) && String(item.value ?? '').trim() !== '');
      return hasOtherSource ? t('settings.setupStatusConfigured') : t('settings.categoryStatusNotSet');
    }
    case 'agent':
      return switchStatus(items, 'AGENT_MODE', t);
    case 'backtest':
      return switchStatus(items, 'BACKTEST_ENABLED', t);
    case 'system':
      return `${t('settings.categoryStatusSchedule')} ${switchStatus(items, 'SCHEDULE_ENABLED', t)}`;
    default:
      return t('settings.categoryStatusFields', { count: items.length });
  }
}

export interface SettingsSearchHit {
  category: string;
  item: SystemConfigItem;
}

/** 比對欄位 key、目前語言的欄位名與說明，不分大小寫。 */
export function searchSettingsItems(
  itemsByCategory: Record<string, SystemConfigItem[]>,
  query: string,
  language: UiLanguage,
): SettingsSearchHit[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const hits: SettingsSearchHit[] = [];
  for (const [category, items] of Object.entries(itemsByCategory)) {
    for (const item of items) {
      const key = item.schema?.key ?? item.key;
      const haystack = language === 'en'
        ? [item.key, item.schema?.title, item.schema?.description]
        : [
            item.key,
            getFieldTitleForLocale(key, item.schema?.title, language),
            getFieldDescriptionForLocale(key, item.schema?.description, language),
          ];
      if (haystack.some((text) => (text ?? '').toLowerCase().includes(needle))) {
        hits.push({ category, item });
      }
    }
  }
  return hits;
}
