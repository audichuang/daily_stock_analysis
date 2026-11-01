import type React from 'react';
import { cn } from '../../utils/cn';

// 三層語意；default／bordered／gradient 是舊呼叫點的相容別名，由頁面票逐步換掉（Y01 刪除）。
type CardLevel = 'surface' | 'inset' | 'highlight';
type CardVariant = CardLevel | 'default' | 'bordered' | 'gradient';

interface CardProps {
  title?: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  variant?: CardVariant;
  hoverable?: boolean;
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

const LEVEL_BY_VARIANT: Record<CardVariant, CardLevel> = {
  surface: 'surface',
  inset: 'inset',
  highlight: 'highlight',
  default: 'surface',
  bordered: 'surface',
  gradient: 'highlight',
};

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
  children,
  className = '',
  style,
  variant = 'surface',
  hoverable = false,
  padding = 'md',
}) => {
  const level = LEVEL_BY_VARIANT[variant];
  const hoverStyles = hoverable ? 'terminal-card-hover cursor-pointer' : '';

  return (
    <div
      style={style}
      data-card-level={level}
      className={cn('rounded-[var(--radius-card)]', LEVEL_STYLES[level], hoverStyles, PADDING_STYLES[padding], className)}
    >
      {(title || subtitle) && (
        <div className="mb-3">
          {subtitle ? <span className="label">{subtitle}</span> : null}
          {title ? <h3 className="mt-1 text-base font-semibold text-foreground">{title}</h3> : null}
        </div>
      )}
      {children}
    </div>
  );
};
