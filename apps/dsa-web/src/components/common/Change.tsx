import type React from 'react';
import { cn } from '../../utils/cn';
import { marketToneClass } from '../../utils/marketTone';

interface ChangeProps {
  /** 決定顏色的數值：正紅、負綠、0 灰，缺值灰。 */
  value?: number | null;
  /** 顯示內容；不給就顯示 value 本身。 */
  children?: React.ReactNode;
  className?: string;
}

/** 行情方向與損益的著色元件，頁面不要再自己判斷正負選色。 */
export const Change: React.FC<ChangeProps> = ({ value, children, className }) => (
  <span className={cn('tabular-nums', marketToneClass(value), className)}>{children ?? value ?? '—'}</span>
);
