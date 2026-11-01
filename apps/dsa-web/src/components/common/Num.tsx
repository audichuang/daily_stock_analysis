import type React from 'react';
import { cn } from '../../utils/cn';
import { formatMoneyValue, formatNumber, formatPercent, formatPrice } from '../../utils/format';

interface NumProps {
  value?: number | null;
  /** number：千分位；percent：帶正負號；price：小數位依幣別與價位。 */
  kind?: 'number' | 'percent' | 'price';
  currency?: string;
  digits?: number;
  className?: string;
}

/** 數字的統一顯示：千分位、統一負號、tabular 對齊，缺值顯示 —。 */
export const Num: React.FC<NumProps> = ({ value, kind = 'number', currency, digits, className }) => {
  const text =
    kind === 'percent'
      ? formatPercent(value, digits)
      : kind === 'price'
        ? formatPrice(value, currency)
        : formatNumber(value, digits);
  return <span className={cn('tabular-nums', className)}>{text}</span>;
};

interface MoneyProps {
  value?: number | null;
  currency?: string;
  digits?: number;
  className?: string;
}

/** 金額的統一顯示：幣別在前，缺值顯示 —。 */
export const Money: React.FC<MoneyProps> = ({ value, currency, digits, className }) => (
  <span className={cn('tabular-nums', className)}>{formatMoneyValue(value, currency, digits)}</span>
);
