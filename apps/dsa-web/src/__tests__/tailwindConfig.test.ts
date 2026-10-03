import type { Config } from 'tailwindcss';
import { describe, expect, it } from 'vitest';
// @ts-expect-error -- plain JS config without a declaration file; typed via the cast below.
import rawTailwindConfig from '../../tailwind.config.js';

const tailwindConfig = rawTailwindConfig as Config;

// Tailwind 的 `text-<name>` 同时是字级与文字色。颜色 token 若与字级同名，`text-<name>`
// 会被解析成文字色：`colors.base = 背景色` 曾让没另外指定文字色的 `text-base` 整段隐形。
const FONT_SIZE_NAMES = ['xs', 'sm', 'base', 'lg', 'xl', '2xl', '3xl', '4xl', '5xl', '6xl', '7xl', '8xl', '9xl'];

describe('tailwind config', () => {
  it('has no color token named like a font size', () => {
    const theme = tailwindConfig.theme ?? {};
    const colorKeys = [
      ...Object.keys((theme as { colors?: object }).colors ?? {}),
      ...Object.keys((theme.extend as { colors?: object } | undefined)?.colors ?? {}),
    ];
    expect(colorKeys.filter((key) => FONT_SIZE_NAMES.includes(key))).toEqual([]);
  });

  it('keeps the base background utility', () => {
    const backgroundColor = (tailwindConfig.theme?.extend as { backgroundColor?: Record<string, string> } | undefined)
      ?.backgroundColor;
    expect(backgroundColor?.base).toBe('hsl(var(--background))');
  });
});
