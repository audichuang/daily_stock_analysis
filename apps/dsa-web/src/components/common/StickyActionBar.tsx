import type React from 'react';
import { cn } from '../../utils/cn';

interface StickyActionBarProps {
  children: React.ReactNode;
  className?: string;
  /** Full-width content (e.g. an error alert) shown above the action row. */
  notice?: React.ReactNode;
  /**
   * Keep the actions on one row on narrow screens instead of wrapping:
   * children do not shrink below their content and buttons use the 36px control height.
   */
  singleRow?: boolean;
}

export const StickyActionBar: React.FC<StickyActionBarProps> = ({ children, className = '', notice, singleRow = false }) => {
  return (
    <div className={cn('sticky bottom-[calc(1rem+var(--shell-bottom-inset,0px))] z-20 rounded-2xl border border-subtle bg-card/85 p-3 shadow-soft-card backdrop-blur-md', className)}>
      {notice ? <div className="mb-2">{notice}</div> : null}
      <div
        className={cn(
          'flex items-center justify-end gap-2',
          singleRow ? 'flex-nowrap [&>button]:h-9 [&>button]:shrink-0' : 'flex-wrap',
        )}
      >
        {children}
      </div>
    </div>
  );
};
