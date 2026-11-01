import { describe, expect, it } from 'vitest';
import { ACTION_TONE, marketDirection, marketToneClass } from '../marketTone';
import { readIndexCss } from '../../__tests__/readCssSource';

// 專案沒裝 @types/node，用 Vite 的 glob 讀原始碼。
const SOURCES = import.meta.glob<string>(
  [
    '../../pages/PortfolioPage.tsx',
    '../../pages/BacktestPage.tsx',
    '../../pages/FundsPage.tsx',
    '../../pages/RealtimeBoardPage.tsx',
    '../../components/report/ReportOverview.tsx',
    '../../components/history/StockHistoryTrendDrawer.tsx',
  ],
  { eager: true, query: '?raw', import: 'default' },
);

describe('marketTone', () => {
  it('紅漲綠跌，0 與缺值不著色', () => {
    expect(marketToneClass(1)).toBe('text-market-up');
    expect(marketToneClass(-1)).toBe('text-market-down');
    expect(marketToneClass(0)).toBe('text-secondary-text');
    expect(marketToneClass(null, 'text-muted-text')).toBe('text-muted-text');
  });

  it('非有限值是沒有讀數，不是持平', () => {
    expect(marketDirection(Number.NaN)).toBeNull();
    expect(marketDirection(Number.POSITIVE_INFINITY)).toBeNull();
    expect(marketDirection(undefined)).toBeNull();
    expect(marketDirection(0)).toBe('flat');
  });

  it('動作色只有品牌、灰、琥珀', () => {
    expect(new Set(Object.values(ACTION_TONE))).toEqual(new Set(['brand', 'neutral', 'caution']));
    expect(ACTION_TONE.buy).toBe('brand');
    expect(ACTION_TONE.hold).toBe('neutral');
    expect(ACTION_TONE.reduce).toBe('caution');
  });

  it('紅與綠的 token 兩個主題都有定義', () => {
    const css = readIndexCss();
    expect(css.match(/--market-up:/g)).toHaveLength(2);
    expect(css.match(/--market-down:/g)).toHaveLength(2);
    expect(css).not.toContain('--home-price-');
  });
});

// 損益欄的顏色只能走 marketTone。數字是各檔「非損益用途」的現存處數，新增就要先確認不是損益欄。
const SEMANTIC_COLOR_BUDGET: Record<string, number> = {
  'pages/PortfolioPage.tsx': 0,
  'pages/BacktestPage.tsx': 0,
  'pages/FundsPage.tsx': 0,
  'pages/RealtimeBoardPage.tsx': 0,
  'components/report/ReportOverview.tsx': 0,
  'components/history/StockHistoryTrendDrawer.tsx': 0,
};
const RAW_DIRECTION_BUDGET: Record<string, number> = {
  'pages/PortfolioPage.tsx': 0,
  'pages/BacktestPage.tsx': 0,
  'pages/FundsPage.tsx': 0,
  // 不可當沖徽章，不是漲跌。
  'pages/RealtimeBoardPage.tsx': 1,
  'components/report/ReportOverview.tsx': 0,
  'components/history/StockHistoryTrendDrawer.tsx': 0,
};

describe('損益欄不得手寫紅綠', () => {
  const countMatches = (file: string, pattern: RegExp) =>
    SOURCES[`../../${file}`].match(pattern)?.length ?? 0;

  it.each(Object.keys(SEMANTIC_COLOR_BUDGET))('%s 不用 text-success／text-danger', (file) => {
    expect(countMatches(file, /\btext-(?:success|danger)\b/g)).toBe(SEMANTIC_COLOR_BUDGET[file]);
  });

  it.each(Object.keys(RAW_DIRECTION_BUDGET))('%s 不用 text-red／text-emerald', (file) => {
    expect(countMatches(file, /\btext-(?:red|emerald)-\d+/g)).toBe(RAW_DIRECTION_BUDGET[file]);
  });
});
