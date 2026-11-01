import type React from 'react';
import { cn } from '../../utils/cn';

type StatusDotTone = 'success' | 'warning' | 'danger' | 'critical' | 'info' | 'neutral';

interface StatusDotProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: StatusDotTone;
  pulse?: boolean;
  className?: string;
}

// System states avoid red/green (reserved for price moves): success is brand cyan,
// failures use the orange-red critical tone, warnings stay amber. danger is kept for
// existing callers and renders the same as critical.
const CRITICAL_STYLE = 'bg-[hsl(14_90%_55%)] shadow-[0_0_0_3px_hsl(14_90%_55%/0.14)]';

const TONE_STYLES: Record<StatusDotTone, string> = {
  success: 'bg-cyan shadow-[0_0_0_3px_hsl(var(--primary)/0.12)]',
  warning: 'bg-warning shadow-[0_0_0_3px_hsl(var(--warning)/0.14)]',
  danger: CRITICAL_STYLE,
  critical: CRITICAL_STYLE,
  info: 'bg-cyan shadow-[0_0_0_3px_hsl(var(--primary)/0.12)]',
  neutral: 'bg-muted-text shadow-[0_0_0_3px_hsl(var(--muted-text)/0.12)]',
};

export const StatusDot: React.FC<StatusDotProps> = ({
  tone = 'neutral',
  pulse = false,
  className = '',
  ...rest
}) => {
  const hasAccessibleLabel = typeof rest['aria-label'] === 'string' && rest['aria-label'].length > 0;

  return (
    <span
      {...rest}
      aria-hidden={hasAccessibleLabel ? undefined : true}
      className={cn(
        'inline-flex h-2.5 w-2.5 shrink-0 rounded-full',
        TONE_STYLES[tone],
        pulse ? 'animate-pulse' : '',
        className,
      )}
    />
  );
};
