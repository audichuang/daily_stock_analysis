import { describe, expect, it } from 'vitest';
import { getStatusPresentation } from '../statusLabels';

describe('statusLabels', () => {
  it('狀態碼轉繁中與 tone', () => {
    expect(getStatusPresentation('fetch_failed')).toEqual({ label: '取得失敗', tone: 'danger' });
    expect(getStatusPresentation('partial')).toEqual({ label: '部分資料', tone: 'warning' });
    expect(getStatusPresentation('COMPLETED')).toEqual({ label: '已完成', tone: 'success' });
  });

  it('依介面語言', () => {
    expect(getStatusPresentation('failed', 'en')?.label).toBe('Failed');
    expect(getStatusPresentation('failed', 'zh')?.label).toBe('失败');
  });

  it('未知碼保留原文、中性灰', () => {
    expect(getStatusPresentation('brand_new_state')).toEqual({ label: 'brand_new_state', tone: 'neutral' });
    // Object 原型上的鍵不能被當成已知狀態。
    expect(getStatusPresentation('constructor')).toEqual({ label: 'constructor', tone: 'neutral' });
  });

  it('空值回 null', () => {
    expect(getStatusPresentation(null)).toBeNull();
    expect(getStatusPresentation('  ')).toBeNull();
  });
});
