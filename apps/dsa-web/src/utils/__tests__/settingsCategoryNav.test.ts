import { describe, expect, it } from 'vitest';
import { formatUiText, UI_TEXT, type UiTextKey, type UiTextParams } from '../../i18n/uiText';
import type { SystemConfigItem } from '../../types/systemConfig';
import { getSettingsCategoryStatus, orderSettingsCategories, searchSettingsItems } from '../settingsCategoryNav';

const t = (key: UiTextKey, params?: UiTextParams) => formatUiText(UI_TEXT['zh-TW'][key], params);

const item = (key: string, value: string, title?: string): SystemConfigItem => ({
  key,
  value,
  rawValueExists: Boolean(value),
  isMasked: false,
  schema: title
    ? {
        key,
        title,
        category: 'base',
        dataType: 'string',
        uiControl: 'text',
        isSensitive: false,
        isRequired: false,
        isEditable: true,
        options: [],
        validation: {},
        displayOrder: 1,
      }
    : undefined,
});

describe('orderSettingsCategories', () => {
  it('puts everyday categories first and system last, without mutating the input', () => {
    const input = [{ category: 'system' }, { category: 'ai_model' }, { category: 'notification' }, { category: 'base' }];
    expect(orderSettingsCategories(input).map((c) => c.category)).toEqual(['base', 'notification', 'ai_model', 'system']);
    expect(input[0].category).toBe('system');
  });

  it('keeps unknown categories after the known ones', () => {
    const ordered = orderSettingsCategories([{ category: 'future' }, { category: 'uncategorized' }, { category: 'base' }]);
    expect(ordered.map((c) => c.category)).toEqual(['base', 'uncategorized', 'future']);
  });
});

describe('getSettingsCategoryStatus', () => {
  it('counts watchlist stocks', () => {
    expect(getSettingsCategoryStatus('base', [item('STOCK_LIST', '2330.TW,AAPL')], t)).toBe('自選 2 檔');
    expect(getSettingsCategoryStatus('base', [], t)).toBe('自選 0 檔');
  });

  it('counts configured notification channels and reports none as not set', () => {
    expect(getSettingsCategoryStatus('notification', [item('TELEGRAM_BOT_TOKEN', '******')], t)).toBe('1 個管道');
    expect(getSettingsCategoryStatus('notification', [item('TELEGRAM_BOT_TOKEN', '')], t)).toBe('未設定');
  });

  it('does not report the model category as not set when it runs without a channel list', () => {
    expect(getSettingsCategoryStatus('ai_model', [item('LLM_CHANNELS', 'a,b')], t)).toBe('2 個管道');
    expect(getSettingsCategoryStatus('ai_model', [item('GENERATION_BACKEND', 'claude_code_cli')], t)).toBe('已設定');
    expect(getSettingsCategoryStatus('ai_model', [item('ANTHROPIC_API_KEY', '******')], t)).toBe('已設定');
    expect(getSettingsCategoryStatus('ai_model', [item('GENERATION_BACKEND', 'litellm')], t)).toBe('未設定');
  });

  it('reads switches', () => {
    expect(getSettingsCategoryStatus('agent', [item('AGENT_MODE', 'true')], t)).toBe(t('common.enabled'));
    expect(getSettingsCategoryStatus('backtest', [item('BACKTEST_ENABLED', 'false')], t)).toBe(t('common.disabled'));
  });
});

describe('searchSettingsItems', () => {
  const items = { notification: [item('TELEGRAM_BOT_TOKEN', '', 'Telegram Bot Token')], base: [item('STOCK_LIST', '', 'Stock List')] };

  it('matches key case-insensitively and the localized title', () => {
    expect(searchSettingsItems(items, 'telegram_bot', 'zh-TW').map((hit) => hit.item.key)).toEqual(['TELEGRAM_BOT_TOKEN']);
    expect(searchSettingsItems(items, '自選股', 'zh-TW').map((hit) => hit.category)).toEqual(['base']);
  });

  it('returns nothing for a blank query', () => {
    expect(searchSettingsItems(items, '   ', 'zh-TW')).toEqual([]);
  });
});
