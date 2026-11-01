import React from 'react';
import { cn } from '../../utils/cn';
import { NO_VALUE } from '../../utils/format';

interface MetricProps {
  label: string;
  value?: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ReactNode;
  /** 群組裡的主指標：字級放大、佔兩欄。 */
  hero?: boolean;
  /** 沒有讀數：值顯示 —、改用淡色，標籤照常；不要拿 0 代替。 */
  unavailable?: boolean;
  /** 值前面的幣別或單位前綴（例如 NT$、US$），見 utils/format 的 currencyUnitLabel。 */
  unit?: string;
  /** 框線的語意色，只給系統狀態用；漲跌與損益請把值包在 Change。 */
  tone?: 'default' | 'primary' | 'success' | 'warning' | 'danger';
  className?: string;
}

const TONE_STYLES = {
  default: 'border-subtle',
  primary: 'border-cyan/18',
  success: 'border-success/18',
  warning: 'border-warning/18',
  danger: 'border-danger/18',
} as const;

export const Metric: React.FC<MetricProps> = ({
  label,
  value,
  hint,
  icon,
  hero = false,
  unavailable = false,
  unit,
  tone = 'default',
  className = '',
}) => {
  const missing = unavailable || value === null || value === undefined;
  return (
    <div
      data-metric-state={unavailable ? 'unavailable' : 'available'}
      className={cn(
        'min-w-0 rounded-[var(--radius-card)] border bg-card/75 p-4 shadow-soft-card',
        TONE_STYLES[tone],
        hero && 'col-span-2',
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="label text-secondary-text">{label}</p>
          <div
            data-metric-value=""
            className={cn(
              // Keep figures on one line; the clamp shrinks the font on narrow phones instead of wrapping.
              'mt-2 whitespace-nowrap font-semibold tabular-nums',
              // .type-title is unlayered CSS and would override the clamp utility, so the
              // non-hero size is set here directly with the same line height.
              hero ? 'type-display' : 'text-[clamp(1rem,4.6vw,var(--text-title))] leading-[1.35]',
              missing ? 'text-muted-text' : 'text-foreground',
            )}
          >
            {unit && !missing ? <span className="mr-1 text-xs font-medium text-secondary-text">{unit}</span> : null}
            {missing ? NO_VALUE : value}
          </div>
          {hint ? <div className="mt-2 text-sm text-secondary-text">{hint}</div> : null}
        </div>
        {icon ? <div className="shrink-0 text-cyan">{icon}</div> : null}
      </div>
    </div>
  );
};

// 完整字串才會被 Tailwind 掃到，不能用樣板字串組 class。
const DESKTOP_COLUMNS = {
  1: 'md:grid-cols-1',
  2: 'md:grid-cols-2',
  3: 'md:grid-cols-3',
  4: 'md:grid-cols-4',
  5: 'md:grid-cols-4 xl:grid-cols-5',
  6: 'md:grid-cols-4 xl:grid-cols-6',
} as const;

type DesktopColumns = keyof typeof DESKTOP_COLUMNS;

interface MetricGroupProps {
  children: React.ReactNode;
  /** 桌機欄數上限；實際欄數依子元素數量收斂，不留空格。手機最多 2 欄。 */
  columns?: 4 | 5 | 6;
  className?: string;
}

// Hero metrics span two grid cells, so they count as two slots.
const countSlots = (children: React.ReactNode): number =>
  React.Children.toArray(children).reduce<number>((total, child) => {
    const isHero = React.isValidElement<{ hero?: boolean }>(child) && child.props.hero === true;
    return total + (isHero ? 2 : 1);
  }, 0);

export const MetricGroup: React.FC<MetricGroupProps> = ({ children, columns = 4, className = '' }) => {
  const slots = countSlots(children);
  const desktop = Math.max(1, Math.min(columns, slots)) as DesktopColumns;
  return (
    <div
      data-testid="metric-group"
      className={cn(
        'grid gap-3',
        slots <= 1 ? 'grid-cols-1' : 'grid-cols-2',
        // Odd slot count on the 2-column phone grid: let the last card fill the row.
        slots > 1 && slots % 2 === 1 && 'max-md:[&>*:last-child]:col-span-2',
        DESKTOP_COLUMNS[desktop],
        className,
      )}
    >
      {children}
    </div>
  );
};
