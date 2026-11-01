import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { MoreHorizontal } from 'lucide-react';
import { cn } from '../../utils/cn';

export interface ActionMenuItem {
  key: string;
  label: string;
  icon?: React.ReactNode;
  disabled?: boolean;
  onSelect: () => void;
}

interface ActionMenuProps {
  /** 「⋯」按鈕的無障礙名稱。 */
  label: string;
  items: ActionMenuItem[];
  /** 底部固定列要往上開。 */
  placement?: 'down' | 'up';
  className?: string;
}

/** 收合次要動作的「⋯」選單；點外面或按 Esc 關閉。 */
export const ActionMenu: React.FC<ActionMenuProps> = ({ label, items, placement = 'down', className }) => {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return undefined;
    const handlePointerDown = (event: MouseEvent) => {
      if (event.target instanceof Node && containerRef.current?.contains(event.target)) return;
      setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  return (
    <div ref={containerRef} className={cn('relative inline-flex', className)}>
      <button
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="home-surface-button flex h-9 w-9 items-center justify-center rounded-lg text-secondary-text hover:text-foreground"
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label={label}
          className={cn(
            'absolute right-0 z-50 min-w-[11rem] rounded-xl border border-subtle bg-elevated p-1.5 text-sm text-foreground shadow-2xl',
            placement === 'up' ? 'bottom-11' : 'top-11',
          )}
        >
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {item.icon}
              <span className="min-w-0 truncate">{item.label}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
};
