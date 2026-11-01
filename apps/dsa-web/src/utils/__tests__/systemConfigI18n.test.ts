import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { UI_TEXT } from '../../i18n/uiText';
import { fieldI18nTablesForTest, getFieldOptionLabel, getFieldTitleForLocale } from '../systemConfigI18n';

declare const __dirname: string;

// 只收繁體不會用到的簡體字；新增時先確認對應的繁體字不同形。
const SIMPLIFIED_ONLY = /[这为们时设择将发现开关动实气应该对数从网络账权证错误来过删确认输总历计测试结报储连级启缓复盘义项务种标获监视运执响预览产单类负仅当归状态调读写邮]/;
// 詞彙表（docs/glossary-zh-tw.md）列為不要用的詞。
const FORBIDDEN_TERMS = /渠道|配置|刷新|告警|預警|持倉|股票代碼/;

const registryKeys = (): string[] => {
  const source = readFileSync(`${__dirname}/../../../../../src/core/config_registry.py`, 'utf-8');
  return [...source.matchAll(/^ {4}"([A-Z][A-Z0-9_]+)": \{/gm)].map((match) => match[1]);
};

const findOffenders = (table: Record<string, string>, pattern: RegExp): string[] =>
  Object.entries(table)
    .filter(([, value]) => pattern.test(value))
    .map(([key, value]) => `${key}: ${value}`);

describe('systemConfigI18n zh-TW coverage', () => {
  const { zhTitles, zhDescriptions, zhTwTitles, zhTwDescriptions } = fieldI18nTablesForTest;

  it('has a title and a description for every simplified Chinese key', () => {
    expect(Object.keys(zhTitles).filter((key) => !zhTwTitles[key])).toEqual([]);
    expect(Object.keys(zhDescriptions).filter((key) => !zhTwDescriptions[key])).toEqual([]);
  });

  it('has a title and a description for every registry field', () => {
    const keys = registryKeys();
    expect(keys.length).toBeGreaterThan(100);
    expect(keys.filter((key) => !zhTwTitles[key])).toEqual([]);
    expect(keys.filter((key) => !zhTwDescriptions[key])).toEqual([]);
  });

  it('prefers the zh-TW table and leaves the zh UI alone', () => {
    expect(getFieldTitleForLocale('LLM_CHANNELS', 'fallback', 'zh-TW')).toBe('模型管道清單');
    expect(getFieldTitleForLocale('LLM_CHANNELS', 'fallback', 'zh')).toBe('LLM 渠道列表');
  });

  it('localizes backend option labels', () => {
    expect(getFieldOptionLabel('AGENT_BACKEND', 'codex_app_server', 'Codex local Agent (experimental)', 'zh-TW'))
      .toBe('Codex 本機 Agent（實驗）');
    expect(getFieldOptionLabel('AGENT_CONTEXT_COMPRESSION_PROFILE', 'cost', '成本优先', 'zh-TW')).toBe('成本優先');
    expect(getFieldOptionLabel('MARKET_REVIEW_REGION', 'tw,us', undefined, 'zh-TW')).toBe('台股＋美股');
  });
});

describe('systemConfigI18n zh-TW wording', () => {
  const optionLabels = Object.fromEntries(
    Object.entries(fieldI18nTablesForTest.zhTwOptionLabels).flatMap(([field, labels]) =>
      Object.entries(labels).map(([value, label]) => [`${field}.${value}`, label])),
  );
  const settingsUiText = Object.fromEntries(
    Object.entries(UI_TEXT['zh-TW']).filter(([key]) => key.startsWith('settings.')),
  );
  const tables: Array<[string, Record<string, string>]> = [
    ['titles', fieldI18nTablesForTest.zhTwTitles],
    ['descriptions', fieldI18nTablesForTest.zhTwDescriptions],
    ['categoryTitles', fieldI18nTablesForTest.zhTwCategoryTitles],
    ['categoryDescriptions', fieldI18nTablesForTest.zhTwCategoryDescriptions],
    ['optionLabels', optionLabels],
    ['settingsUiText', settingsUiText],
  ];

  it('the guards detect what they claim to detect', () => {
    expect(SIMPLIFIED_ONLY.test('设置')).toBe(true);
    expect(SIMPLIFIED_ONLY.test('設定')).toBe(false);
    expect(FORBIDDEN_TERMS.test('通知渠道')).toBe(true);
    expect(FORBIDDEN_TERMS.test('通知管道')).toBe(false);
  });

  it.each(tables)('%s contains no simplified characters', (_name, table) => {
    expect(findOffenders(table, SIMPLIFIED_ONLY)).toEqual([]);
  });

  it.each(tables)('%s follows the glossary', (_name, table) => {
    expect(findOffenders(table, FORBIDDEN_TERMS)).toEqual([]);
  });
});
