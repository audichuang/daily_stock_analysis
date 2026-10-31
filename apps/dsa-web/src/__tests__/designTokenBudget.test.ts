import { describe, expect, it } from 'vitest';
import { readIndexCss } from './readCssSource';

const TSX_SOURCES = import.meta.glob<string>(['../**/*.tsx', '!../**/__tests__/**', '!../**/*.test.tsx'], {
  eager: true,
  query: '?raw',
  import: 'default',
});

// 改版期間的上限：頁面票遷移後要把數字調低，不能調高。新程式碼用 --text-* token 與元件，不要再寫新的。
const ARBITRARY_FONT_SIZE_LIMIT = 115;
const GLOBAL_PAGE_CLASS_LIMIT = 133;

const countArbitraryFontSizes = (source: string): number =>
  source.match(/text-\[\d+(?:\.\d+)?px\]/g)?.length ?? 0;

const countGlobalPageClasses = (css: string): number =>
  css.match(/^\s*\.(?:home|backtest|settings)-/gm)?.length ?? 0;

describe('設計 token 預算', () => {
  it('tsx 的 text-[Npx] 不超過基線', () => {
    const total = Object.values(TSX_SOURCES).reduce((sum, source) => sum + countArbitraryFontSizes(source), 0);
    expect(total).toBeLessThanOrEqual(ARBITRARY_FONT_SIZE_LIMIT);
  });

  it('.home-／.backtest-／.settings- 全域 class 不超過基線', () => {
    expect(countGlobalPageClasses(readIndexCss())).toBeLessThanOrEqual(GLOBAL_PAGE_CLASS_LIMIT);
  });

  it('計數器算得到目標寫法', () => {
    expect(countArbitraryFontSizes("text-[12px] text-[10.5px] text-sm")).toBe(2);
    expect(countGlobalPageClasses('.home-a {}\n  .settings-b {}\n.other {}\n.dark .home-c {}')).toBe(2);
  });

  it('圓角與字級 token 都有定義', () => {
    const css = readIndexCss();
    for (const token of ['--radius-control: 8px', '--radius-card: 12px', '--radius-pill: 999px', '--text-display: 28px', '--text-micro: 11px']) {
      expect(css).toContain(token);
    }
  });

  it('.label 字距 0、不轉大寫', () => {
    const rule = /\.label,\s*\.label-uppercase \{[^}]*\}/.exec(readIndexCss())?.[0] ?? '';
    expect(rule).toContain('letter-spacing: 0;');
    expect(rule).toContain('text-transform: none;');
  });
});
