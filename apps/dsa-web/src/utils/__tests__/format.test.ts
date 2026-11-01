import { describe, expect, it } from 'vitest';
import { formatDateTime, formatMoneyValue, formatNumber, formatPercent, formatPrice, MINUS_SIGN, NO_VALUE } from '../format';

describe('數字格式', () => {
  it('負號統一用 U+2212', () => {
    expect(MINUS_SIGN).toBe('−');
    expect(formatNumber(-1234.5, 1)).toBe('−1,234.5');
    expect(formatPercent(-1.5)).toBe('−1.50%');
    expect(formatMoneyValue(-1000, 'TWD', 0)).toBe('TWD −1,000');
  });

  it('百分比正值帶 +，0 不帶正負號', () => {
    expect(formatPercent(1.5)).toBe('+1.50%');
    expect(formatPercent(0)).toBe('0.00%');
    expect(formatPercent(1.234, 1)).toBe('+1.2%');
  });

  it('沒有讀數顯示 —，0 是真實讀數', () => {
    for (const missing of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(formatNumber(missing)).toBe(NO_VALUE);
      expect(formatPercent(missing)).toBe(NO_VALUE);
      expect(formatPrice(missing, 'TWD')).toBe(NO_VALUE);
      expect(formatMoneyValue(missing, 'TWD')).toBe(NO_VALUE);
    }
    expect(formatNumber(0)).toBe('0');
    expect(formatPrice(0, 'USD')).toBe('0.00');
  });

  it('價格小數依幣別與價位，並加千分位', () => {
    expect(formatPrice(1005, 'TWD')).toBe('1,005');
    expect(formatPrice(512.5, 'TWD')).toBe('512.5');
    expect(formatPrice(45.35, 'TWD')).toBe('45.35');
    expect(formatPrice(443.15, 'TWD')).toBe('443.15');
    expect(formatPrice(1.231, 'CNY')).toBe('1.231');
    expect(formatPrice(1.234, 'CNY')).toBe('1.234');
    expect(formatPrice(3.875, 'CNY')).toBe('3.875');
    expect(formatPrice(1040.5, 'TWD')).toBe('1,040.5');
    expect(formatPrice(1234.5, 'USD')).toBe('1,234.50');
    expect(formatPrice(0.1234, 'USD')).toBe('0.1234');
    expect(formatPrice(12.3)).toBe('12.30');
  });

  it('金額沒給幣別時不補任何幣別', () => {
    expect(formatMoneyValue(1234.5)).toBe('1,234.50');
    expect(formatMoneyValue(1234.5, 'USD')).toBe('USD 1,234.50');
  });

  it('日期時間用 zh-TW 與 24 小時制', () => {
    const text = formatDateTime('2026-03-05T15:07:00');
    expect(text).toContain('2026/03/05');
    expect(text).toContain('15:07');
    expect(text).not.toContain('下午');
  });
});
