import type React from 'react';
import { useMediaQuery } from '../../hooks/useMediaQuery';
import { cn } from '../../utils/cn';
import { useEmbedModeSafe } from './AppPage';

/** Below Tailwind's md breakpoint. Written as max-width so a missing matchMedia means desktop. */
const PAGE_HEADER_COMPACT_QUERY = '(max-width: 767.98px)';

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  className?: string;
}

/**
 * 頁首：無外框單列，標題＋可選說明＋動作。
 * Compact (iOS embed or below md): the shell / native toolbar already shows the page name,
 * so the h1 stays only for screen readers and the row shows description + actions.
 */
export const PageHeader: React.FC<PageHeaderProps> = ({ title, description, actions, className = '' }) => {
  const embedded = useEmbedModeSafe();
  const narrow = useMediaQuery(PAGE_HEADER_COMPACT_QUERY);
  const compact = embedded || narrow;

  if (compact) {
    const hasRow = Boolean(description) || Boolean(actions);
    return (
      <header className={cn(hasRow ? 'flex items-center gap-3' : 'contents', className)} data-compact="true">
        <h1 className="sr-only">{title}</h1>
        {description ? <p className="min-w-0 flex-1 truncate text-xs text-muted-text">{description}</p> : null}
        {actions ? (
          <div className="ml-auto flex min-w-0 items-center justify-end gap-2 overflow-x-auto">{actions}</div>
        ) : null}
      </header>
    );
  }

  return (
    <header className={cn('flex flex-col gap-3 md:flex-row md:items-center md:justify-between', className)}>
      <div className="min-w-0">
        <h1 className="text-[length:var(--text-title)] font-semibold text-foreground md:text-[length:var(--text-display)]">{title}</h1>
        {description ? <p className="mt-1 max-w-2xl text-sm text-secondary-text">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
};
