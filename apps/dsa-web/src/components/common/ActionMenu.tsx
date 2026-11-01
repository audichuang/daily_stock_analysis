import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { MoreHorizontal } from 'lucide-react';
import { cn } from '../../utils/cn';
import { IconButton } from './Button';

export interface ActionMenuItem {
  key: string;
  label: string;
  onSelect: () => void;
  icon?: React.ReactNode;
  disabled?: boolean;
  danger?: boolean;
}

interface ActionMenuProps {
  /** 「⋯」按鈕的無障礙名稱。 */
  label: string;
  items: ActionMenuItem[];
  /** 放在選項上方的內容（例如設定切換）。 */
  header?: React.ReactNode;
  size?: 'sm' | 'md';
  /** 底部固定列要往上開。 */
  placement?: 'down' | 'up';
  className?: string;
}

type MenuPosition = { right: number; top?: number; bottom?: number };

/** 「⋯」選單。渲染到 body 並用 fixed 定位，放在可橫捲的表格裡才不會被裁掉；點外面或按 Esc 關閉。 */
export const ActionMenu: React.FC<ActionMenuProps> = ({ label, items, header, size = 'md', placement = 'down', className }) => {
  const [position, setPosition] = useState<MenuPosition | null>(null);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const open = position !== null;

  useEffect(() => {
    if (!open) return undefined;
    const close = () => setPosition(null);
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('resize', close);
    };
  }, [open]);

  const toggle = (event: React.MouseEvent) => {
    event.stopPropagation();
    if (open) {
      setPosition(null);
      return;
    }
    const rect = anchorRef.current?.getBoundingClientRect();
    const right = Math.max(8, window.innerWidth - (rect?.right ?? window.innerWidth));
    setPosition(placement === 'up'
      ? { right, bottom: window.innerHeight - (rect?.top ?? window.innerHeight) + 4 }
      : { right, top: (rect?.bottom ?? 0) + 4 });
  };

  return (
    <span ref={anchorRef} className={cn('inline-flex', className)}>
      <IconButton
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        size={size}
        icon={<MoreHorizontal className="h-4 w-4" />}
        onClick={toggle}
      />
      {position
        ? createPortal(
            <div
              ref={menuRef}
              style={position}
              className="fixed z-50 min-w-44 rounded-[var(--radius-control)] border border-border/70 bg-card p-1 text-left shadow-soft-card"
            >
              {header ? <div className="border-b border-border/60 px-2 pb-2 pt-1">{header}</div> : null}
              <div role="menu" aria-label={label}>
                {items.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    role="menuitem"
                    disabled={item.disabled}
                    onClick={(event) => {
                      event.stopPropagation();
                      setPosition(null);
                      item.onSelect();
                    }}
                    className={cn(
                      'flex w-full cursor-pointer items-center gap-2 rounded-[6px] px-2.5 py-2 text-left text-sm hover:bg-hover',
                      'disabled:cursor-not-allowed disabled:opacity-50',
                      item.danger ? 'text-danger' : 'text-foreground',
                    )}
                  >
                    {item.icon}
                    <span className="min-w-0 truncate">{item.label}</span>
                  </button>
                ))}
              </div>
            </div>,
            document.body,
          )
        : null}
    </span>
  );
};
