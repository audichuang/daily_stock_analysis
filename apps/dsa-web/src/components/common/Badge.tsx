import React from 'react';
import { cn } from '../../utils/cn';

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'critical' | 'info' | 'history' | 'brand' | 'neutral' | 'caution';

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  children: React.ReactNode;
  variant?: BadgeVariant;
  size?: 'sm' | 'md';
  glow?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

// System states avoid red/green (reserved for price moves, use Change for those):
// success is brand cyan, danger and critical share the orange-red tone.
const CRITICAL_STYLE = 'border-[hsl(14_90%_55%/0.25)] bg-[hsl(14_90%_55%/0.1)] text-[hsl(14_90%_55%)]';

const variantStyles: Record<BadgeVariant, string> = {
  default: 'border-border/55 bg-elevated/75 text-secondary-text',
  success: 'border-cyan/30 bg-cyan/12 text-cyan',
  warning: 'border-warning/20 bg-warning/10 text-warning',
  danger: CRITICAL_STYLE,
  critical: CRITICAL_STYLE,
  info: 'border-cyan/30 bg-cyan/12 text-cyan',
  history: 'border-purple/20 bg-purple/10 text-purple',
  // 動作語意色：不用紅綠，見 utils/marketTone.ts
  brand: 'border-cyan/30 bg-cyan/12 text-cyan',
  // Neutral actions (watch, hold) render as muted text only, no border or fill.
  neutral: 'border-transparent bg-transparent text-muted-text backdrop-blur-none',
  caution: 'border-warning/20 bg-warning/10 text-warning',
};

const glowStyles: Record<BadgeVariant, string> = {
  default: '',
  success: 'shadow-cyan/20',
  warning: 'shadow-warning/20',
  danger: 'shadow-[hsl(14_90%_55%/0.2)]',
  critical: 'shadow-[hsl(14_90%_55%/0.2)]',
  info: 'shadow-cyan/20',
  history: 'shadow-purple/20',
  brand: 'shadow-cyan/20',
  neutral: '',
  caution: 'shadow-warning/20',
};

/**
 * Badge component with multiple variants and optional glow styling.
 */
export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'default',
  size = 'sm',
  glow = false,
  className = '',
  style,
  ...rest
}) => {
  const sizeStyles = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm';

  return (
    <span
      {...rest}
      style={style}
      className={cn(
        'inline-flex items-center gap-1 rounded-full border font-medium backdrop-blur-sm',
        sizeStyles,
        variantStyles[variant],
        glow && `shadow-lg ${glowStyles[variant]}`,
        className,
      )}
    >
      {children}
    </span>
  );
};
