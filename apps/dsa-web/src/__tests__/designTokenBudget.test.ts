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

  it('卡片裁切溢出，長字串不會把手機頁面撐寬', () => {
    const css = readIndexCss();
    for (const selector of ['.card-surface', '.card-inset']) {
      const rule = new RegExp(`\\${selector} \\{[^}]*\\}`).exec(css)?.[0] ?? '';
      expect(rule).toContain('overflow: hidden;');
    }
  });

  it('.label 字距 0、不轉大寫', () => {
    const rule = /\.label,\s*\.label-uppercase \{[^}]*\}/.exec(readIndexCss())?.[0] ?? '';
    expect(rule).toContain('letter-spacing: 0;');
    expect(rule).toContain('text-transform: none;');
  });

  it('深色主題漲跌色亮度拉平，綠色不比紅色刺眼', () => {
    const darkBlock = /\n\.dark\s*\{([\s\S]*?)\n\}/.exec(readIndexCss())?.[1] ?? '';
    const tokenValue = (name: string): string => new RegExp(`${name}:\\s*([^;]+);`).exec(darkBlock)?.[1]?.trim() ?? '';
    const up = relativeLuminance(tokenValue('--market-up'));
    const down = relativeLuminance(tokenValue('--market-down'));
    expect(Math.abs(up - down)).toBeLessThanOrEqual(0.1);
  });

  it('文字色不在 muted／secondary token 上疊透明度', () => {
    expect(countAlphaOnTextTokens(readIndexCss())).toBe(0);
  });

  it('a 與表單元件的 inherit 規則不留在 @layer 外，否則會蓋掉 text-* utility', () => {
    const unlayered = stripLayerBlocks(readIndexCss());
    expect(unlayered).not.toMatch(/button,\s*input,\s*select,\s*textarea\s*\{[^}]*font:\s*inherit/);
    expect(unlayered).not.toMatch(/^\s*a\s*\{[^}]*color:\s*inherit/m);
  });

  it('亮度、透明度與 layer 輔助函式算得對', () => {
    expect(relativeLuminance('#ffffff')).toBeCloseTo(1, 3);
    expect(relativeLuminance('#000')).toBeCloseTo(0, 3);
    expect(relativeLuminance('hsl(149 100% 44%)')).toBeCloseTo(relativeLuminance('#00e06c'), 2);
    expect(Math.abs(relativeLuminance('#FF7075') - relativeLuminance('hsl(149 100% 44%)'))).toBeGreaterThan(0.1);
    expect(countAlphaOnTextTokens('.a { color: hsl(var(--muted-text) / 0.6); }\n.b { --x: hsl(var(--muted-text) / 0.6); background: hsl(var(--secondary-text) / 0.5); }')).toBe(1);
    expect(countAlphaOnTextTokens('.a {\n  -webkit-text-fill-color: hsl(var(--secondary-text) / 0.62);\n}')).toBe(1);
    expect(stripLayerBlocks('@layer base { a { color: inherit; } }\n.x { color: red; }')).not.toContain('inherit');
    expect(stripLayerBlocks('@layer components { .y { color: blue; } }\nbutton, input, select, textarea { font: inherit; }')).toContain('font: inherit');
  });
});

/** WCAG relative luminance for `#rgb`, `#rrggbb` or `hsl(h s% l%)`; NaN for anything else. */
function relativeLuminance(color: string): number {
  const rgb = parseColor(color);
  if (!rgb) return Number.NaN;
  const [r, g, b] = rgb.map((channel) => (channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function parseColor(color: string): [number, number, number] | null {
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color.trim());
  if (hex) {
    const digits = hex[1].length === 3 ? [...hex[1]].map((d) => d + d).join('') : hex[1];
    return [0, 2, 4].map((i) => parseInt(digits.slice(i, i + 2), 16) / 255) as [number, number, number];
  }
  const hsl = /^hsl\(\s*([\d.]+)\s+([\d.]+)%\s+([\d.]+)%\s*\)$/i.exec(color.trim());
  if (!hsl) return null;
  const h = Number(hsl[1]);
  const s = Number(hsl[2]) / 100;
  const l = Number(hsl[3]) / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
  return [f(0), f(8), f(4)];
}

/** Counts color / -webkit-text-fill-color declarations that stack alpha on a muted/secondary text token. */
function countAlphaOnTextTokens(css: string): number {
  const declarations = css.matchAll(/(?:^|[;{])\s*(?:color|-webkit-text-fill-color)\s*:\s*([^;}]+)/gm);
  return [...declarations].filter((match) => /(muted|secondary)-text\)\s*\/\s*0\./.test(match[1])).length;
}

/** Removes every `@layer … { … }` block (brace-depth aware) so only unlayered CSS remains. */
function stripLayerBlocks(css: string): string {
  let result = '';
  let index = 0;
  const layerPattern = /@layer\b[^;{]*\{/g;
  let match: RegExpExecArray | null;
  while ((match = layerPattern.exec(css))) {
    result += css.slice(index, match.index);
    let depth = 1;
    let cursor = match.index + match[0].length;
    while (cursor < css.length && depth > 0) {
      if (css[cursor] === '{') depth += 1;
      else if (css[cursor] === '}') depth -= 1;
      cursor += 1;
    }
    index = cursor;
    layerPattern.lastIndex = cursor;
  }
  return result + css.slice(index);
}
