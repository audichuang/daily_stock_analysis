import type React from 'react';
import { cn } from '../../utils/cn';

type CardLevel = 'surface' | 'inset' | 'highlight';

interface CardProps {
  title?: string;
  subtitle?: string;
  /** 標題列右側的附加內容（例如時間、狀態、動作）。 */
  meta?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  variant?: CardLevel;
  hoverable?: boolean;
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

const PADDING_STYLES = {
  none: '',
  sm: 'p-3',
  md: 'p-4',
  lg: 'p-5',
} as const;

const LEVEL_STYLES: Record<CardLevel, string> = {
  surface: 'card-surface',
  inset: 'card-inset',
  highlight: 'terminal-card',
};

/**
 * 卡片分三層：surface 一般內容、inset 卡片內的次層、highlight 單頁唯一的重點（只有它有漸層）。
 */
export const Card: React.FC<CardProps> = ({
  title,
  subtitle,
  meta,
  children,
  className = '',
  style,
  variant: level = 'surface',
  hoverable = false,
  padding = 'md',
}) => {
  const hoverStyles = hoverable ? 'terminal-card-hover cursor-pointer' : '';

  return (
    <div
      style={style}
      data-card-level={level}
      className={cn('rounded-[var(--radius-card)]', LEVEL_STYLES[level], hoverStyles, PADDING_STYLES[padding], className)}
    >
      {(title || subtitle || meta) && (
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            {title ? <h3 className="text-base font-semibold text-foreground">{title}</h3> : null}
            {subtitle ? <p className="mt-0.5 text-xs text-secondary-text">{subtitle}</p> : null}
          </div>
          {meta ? <div className="shrink-0">{meta}</div> : null}
        </div>
      )}
      {children}
    </div>
  );
};
