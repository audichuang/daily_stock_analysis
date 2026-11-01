import { describe, expect, it } from 'vitest';
import { UI_TEXT } from '../uiText';
import * as featureText from '../../locales/featureText';

// 簡體常見字（繁體不會用到的字形）；只抓高頻字，目的在攔新增，不求窮盡。「跌」繁簡同字，不列入。
const SIMPLIFIED_CHARS =
  /[买卖仓价涨设数图页报询议标务资产额点击显录请确认这个们为时间线开关变实钟态应级状况]/g;

// 專案沒裝 @types/node，用 Vite 的 glob 讀原始碼（tsc 與 vitest 都認得）。
const TSX_SOURCES = import.meta.glob<string>(['../../**/*.tsx', '!../../**/__tests__/**', '!../../**/*.test.tsx'], {
  eager: true,
  query: '?raw',
  import: 'default',
});

// 去掉註解與 tsx 內嵌的 zh 語系表；其餘簡體字會在繁中介面直接露出。
const countSimplified = (source: string): number => {
  let count = 0;
  let zhDepth = 0;
  for (const line of source.split('\n')) {
    const trimmed = line.trim();
    if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) continue;
    const delta = (line.match(/\{/g)?.length ?? 0) - (line.match(/\}/g)?.length ?? 0);
    if (zhDepth > 0) {
      zhDepth += delta;
      continue;
    }
    if (/^zh\s*:/.test(trimmed)) {
      zhDepth = Math.max(delta, 0);
      continue;
    }
    count += line.match(SIMPLIFIED_CHARS)?.length ?? 0;
  }
  return count;
};

const collectStrings = (value: unknown, out: string[] = []): string[] => {
  if (typeof value === 'string') out.push(value);
  else if (Array.isArray(value)) value.forEach((item) => collectStrings(item, out));
  else if (value && typeof value === 'object') Object.values(value).forEach((item) => collectStrings(item, out));
  return out;
};

const zhTwFeatureStrings = (): string[] =>
  Object.values(featureText).flatMap((table) =>
    table && typeof table === 'object' && 'zh-TW' in table
      ? collectStrings((table as Record<string, unknown>)['zh-TW'])
      : [],
  );

describe('繁中介面用語守門', () => {
  it('tsx 不含簡體字（白名單已清空）', () => {
    const actual: Record<string, number> = {};
    for (const [file, source] of Object.entries(TSX_SOURCES)) {
      const count = countSimplified(source);
      if (count > 0) actual[file.replace('../../', '')] = count;
    }
    expect(actual).toEqual({});
  });

  it('zh-TW 文案表不再用詞彙表淘汰的詞', () => {
    const banned = /告警|持倉|刷新|渠道|配置|股票代碼|貴州茅台|600519|加倉|減倉|買入/;
    const offenders = [...Object.values(UI_TEXT['zh-TW']), ...zhTwFeatureStrings()].filter((text) => banned.test(text));
    expect(offenders).toEqual([]);
  });

  it('zh-TW 動作詞依詞彙表', () => {
    const zhTw = UI_TEXT['zh-TW'];
    expect(zhTw['history.actionBuy']).toBe('買進');
    expect(zhTw['history.actionAdd']).toBe('加碼');
    expect(zhTw['history.actionHold']).toBe('續抱');
    expect(zhTw['history.actionReduce']).toBe('減碼');
    expect(zhTw['history.actionSell']).toBe('賣出');
    expect(zhTw['history.actionWatch']).toBe('觀望');
  });

  it('掃描會略過 zh 語系表與註解，但抓得到一般字串', () => {
    expect(countSimplified("// 买入\nconst a = { zh: { x: '买入' }, en: { x: 'buy' } };")).toBe(1);
    expect(countSimplified("  zh: {\n    x: '买入',\n  },\n  'zh-TW': { x: '買進' },")).toBe(0);
    expect(countSimplified("<span>买入</span>")).toBe(1);
    expect(countSimplified("<span>漲跌幅</span>")).toBe(0);
  });
});
