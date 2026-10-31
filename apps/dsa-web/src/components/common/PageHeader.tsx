import type React from 'react';
import { cn } from '../../utils/cn';

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  className?: string;
}

/** 頁首：無外框單列，標題＋可選說明＋動作。 */
export const PageHeader: React.FC<PageHeaderProps> = ({ title, description, actions, className = '' }) => (
  <header className={cn('flex flex-col gap-3 md:flex-row md:items-center md:justify-between', className)}>
    <div className="min-w-0">
      <h1 className="text-[length:var(--text-title)] font-semibold text-foreground md:text-[length:var(--text-display)]">{title}</h1>
      {description ? <p className="mt-1 max-w-2xl text-sm text-secondary-text">{description}</p> : null}
    </div>
    {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
  </header>
);
