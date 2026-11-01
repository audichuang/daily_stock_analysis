import type React from 'react';
import { useEffect, useRef, useState } from 'react';
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
  const containerRef = useRef<HTMLDivElement>(null);
  // True while more options are hidden past the right edge; drives the fade mask.
  const [clippedRight, setClippedRight] = useState(false);

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return undefined;
    const update = () => {
      setClippedRight(node.scrollLeft + node.clientWidth < node.scrollWidth - 1);
    };
    update();
    node.addEventListener('scroll', update, { passive: true });
    // jsdom and some older embedded webviews have no ResizeObserver.
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update);
    observer?.observe(node);
    return () => {
      node.removeEventListener('scroll', update);
      observer?.disconnect();
    };
  }, [options.length]);

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
      ref={containerRef}
      role="radiogroup"
      aria-label={ariaLabel}
      onKeyDown={handleKeyDown}
      data-overflowing={clippedRight || undefined}
      className={cn(
        'inline-flex max-w-full gap-0.5 overflow-x-auto rounded-[var(--radius-control)] border border-border/70 bg-elevated/60 p-0.5',
        // Overflowing options scroll sideways without a visible grey scrollbar.
        '[scrollbar-width:none] [&::-webkit-scrollbar]:hidden',
        clippedRight && '[mask-image:linear-gradient(to_right,black_calc(100%-24px),transparent)]',
        className,
      )}
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
              // Phones (max-sm) bump the option itself to 36px for a larger tap target.
              'inline-flex shrink-0 cursor-pointer items-center justify-center whitespace-nowrap rounded-[6px] px-3 transition-colors',
              // Inset ring: the scrolling container would clip an outer focus ring.
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan/40',
              'disabled:cursor-not-allowed disabled:opacity-50',
              size === 'md' ? 'h-[30px] text-sm max-sm:h-9' : 'h-[26px] text-xs max-sm:h-9',
              selected
                ? 'bg-cyan/15 font-medium text-foreground ring-1 ring-inset ring-cyan/40'
                : 'text-secondary-text hover:text-foreground',
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
