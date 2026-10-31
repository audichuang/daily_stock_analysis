import type React from 'react';
import { cn } from '../../utils/cn';
import { NO_VALUE } from '../../utils/format';

interface MetricProps {
  label: string;
  value?: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ReactNode;
  /** 群組裡的主指標：字級放大、佔兩欄。 */
  hero?: boolean;
  /** 沒有讀數：值顯示 —、整格淡化，不要拿 0 代替。 */
  unavailable?: boolean;
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
  tone = 'default',
  className = '',
}) => (
  <div
    data-metric-state={unavailable ? 'unavailable' : 'available'}
    className={cn(
      'min-w-0 rounded-[var(--radius-card)] border bg-card/75 p-4 shadow-soft-card',
      TONE_STYLES[tone],
      hero && 'col-span-2',
      unavailable && 'opacity-60',
      className,
    )}
  >
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="label text-secondary-text">{label}</p>
        <div
          className={cn(
            'mt-2 font-semibold tabular-nums',
            hero ? 'type-display' : 'type-title',
            unavailable ? 'text-secondary-text' : 'text-foreground',
          )}
        >
          {unavailable ? NO_VALUE : (value ?? NO_VALUE)}
        </div>
        {hint ? <div className="mt-2 text-sm text-secondary-text">{hint}</div> : null}
      </div>
      {icon ? <div className="shrink-0 text-cyan">{icon}</div> : null}
    </div>
  </div>
);

// 完整字串才會被 Tailwind 掃到，不能用樣板字串組 class。
const DESKTOP_COLUMNS = {
  4: 'md:grid-cols-4',
  5: 'md:grid-cols-4 xl:grid-cols-5',
  6: 'md:grid-cols-4 xl:grid-cols-6',
} as const;

interface MetricGroupProps {
  children: React.ReactNode;
  /** 桌機欄數；手機固定 2 欄。 */
  columns?: keyof typeof DESKTOP_COLUMNS;
  className?: string;
}

export const MetricGroup: React.FC<MetricGroupProps> = ({ children, columns = 4, className = '' }) => (
  <div data-testid="metric-group" className={cn('grid grid-cols-2 gap-3', DESKTOP_COLUMNS[columns], className)}>
    {children}
  </div>
);
