import type React from 'react';
import { cn } from '../../utils/cn';

export interface SegmentedOption<T extends string> {
  value: T;
  label: React.ReactNode;
  disabled?: boolean;
}

interface SegmentedProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  options: SegmentedOption<T>[];
  'aria-label': string;
  size?: 'sm' | 'md';
  className?: string;
}

/** 二到五個互斥選項的切換；方向鍵移動選取，與原生 radio 的操作一致。 */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  'aria-label': ariaLabel,
  size = 'md',
  className = '',
}: SegmentedProps<T>): React.ReactElement {
  const enabled = options.filter((option) => !option.disabled);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0;
    if (step === 0 || enabled.length === 0) return;
    event.preventDefault();
    const index = enabled.findIndex((option) => option.value === value);
    const next = enabled[(index + step + enabled.length) % enabled.length];
    onChange(next.value);
    const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');
    buttons[enabled.indexOf(next)]?.focus();
  };

  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      onKeyDown={handleKeyDown}
      className={cn('inline-flex max-w-full gap-0.5 rounded-[var(--radius-control)] border border-border/70 bg-elevated/60 p-0.5', className)}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={option.disabled}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(option.value)}
            className={cn(
              // 內層 30px＋外框 padding 4px＋框線 2px，總高與 md 控制項同為 36px。
              'inline-flex cursor-pointer items-center justify-center whitespace-nowrap rounded-[6px] px-3 font-medium transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan/30',
              'disabled:cursor-not-allowed disabled:opacity-50',
              size === 'md' ? 'h-[30px] text-sm' : 'h-[26px] text-xs',
              selected ? 'bg-card text-foreground shadow-soft-card' : 'text-secondary-text hover:text-foreground',
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
