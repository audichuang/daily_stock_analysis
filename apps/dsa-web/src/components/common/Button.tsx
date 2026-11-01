import React from 'react';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { cn } from '../../utils/cn';

// primary／secondary／ghost／danger 是正式 variant；其餘是舊呼叫點的相容別名，由頁面票逐步換掉（Y01 刪除）。
type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type LegacyButtonVariant = 'outline' | 'gradient' | 'danger-subtle' | 'settings-primary' | 'settings-secondary' | 'action-primary' | 'action-secondary' | 'home-action-ai' | 'home-action-report';
// 正式尺寸 sm 32／md 36／lg 44；xsm、xl 是相容別名。
type ButtonSize = 'sm' | 'md' | 'lg' | 'xsm' | 'xl';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant | LegacyButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
  /** Custom loading text. */
  loadingText?: string;
  glow?: boolean;
}

const BUTTON_SIZE_STYLES: Record<ButtonSize, string> = {
  xsm: 'h-8 rounded-[var(--radius-control)] px-2.5 text-sm',
  sm: 'h-8 rounded-[var(--radius-control)] px-2.5 text-sm',
  md: 'h-9 rounded-[var(--radius-control)] px-3.5 text-sm',
  lg: 'h-11 rounded-[var(--radius-control)] px-5 text-sm',
  xl: 'h-11 rounded-[var(--radius-control)] px-5 text-sm',
};

const ACTION_AI_STYLES = 'bg-[var(--home-action-ai-bg)] border border-[var(--home-action-ai-border)] text-[var(--home-action-ai-text)] hover:bg-[var(--home-action-ai-hover-bg)]';
const ACTION_REPORT_STYLES = 'bg-[var(--home-action-report-bg)] border border-[var(--home-action-report-border)] text-[var(--home-action-report-text)] hover:bg-[var(--home-action-report-hover-bg)]';

const BUTTON_VARIANT_STYLES = {
  primary: 'border border-cyan/30 bg-primary-gradient text-primary-foreground hover:brightness-105',
  secondary: 'border border-border/70 bg-card text-foreground shadow-soft-card hover:bg-hover',
  'settings-primary': 'border settings-button-primary hover:brightness-105 hover:shadow-xl',
  'settings-secondary': 'border settings-button-secondary hover:translate-y-[-1px]',
  outline: 'border border-cyan/25 bg-transparent text-cyan hover:bg-cyan/10',
  ghost: 'border border-transparent bg-transparent text-secondary-text hover:bg-hover hover:text-foreground',
  gradient: 'border border-cyan/20 bg-gradient-to-r from-cyan to-purple text-primary-foreground shadow-lg shadow-cyan/20 hover:brightness-105',
  danger: 'border border-danger/40 bg-danger text-destructive-foreground hover:brightness-105',
  'danger-subtle': 'border border-danger/60 bg-danger/10 text-danger hover:bg-danger/15',
  'action-primary': ACTION_AI_STYLES,
  'action-secondary': ACTION_REPORT_STYLES,
  'home-action-ai': ACTION_AI_STYLES,
  'home-action-report': ACTION_REPORT_STYLES,
} as const;

/**
 * Button component with multiple variants and terminal-inspired styling.
 */
export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'primary',
  size = 'md',
  isLoading = false,
  loadingText,
  glow = false,
  className = '',
  disabled,
  type = 'button',
  ...props
}) => {
  const { t } = useUiLanguage();
  const glowStyles = glow ? 'shadow-glow-cyan settings-glow-cyan-hover' : '';

  return (
    <button
      type={type}
      aria-busy={isLoading || undefined}
      data-variant={variant}
      className={cn(
        'inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 whitespace-nowrap font-medium transition-all duration-200',
        'focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan/15 focus-visible:ring-offset-0',
        'disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 disabled:transform-none',
        BUTTON_SIZE_STYLES[size],
        BUTTON_VARIANT_STYLES[variant],
        glowStyles,
        className,
      )}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <span className="flex items-center justify-center gap-2">
          <svg
            className="h-4 w-4 animate-spin text-current"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
          {loadingText ?? t('common.processing')}
        </span>
      ) : (
        children
      )}
    </button>
  );
};

const ICON_BUTTON_SIZE_STYLES = {
  sm: 'h-8 w-8',
  md: 'h-9 w-9',
  lg: 'h-11 w-11',
} as const;

interface IconButtonProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label' | 'children'> {
  /** 只有圖示時的無障礙名稱，必填。 */
  'aria-label': string;
  icon: React.ReactNode;
  variant?: ButtonVariant;
  size?: keyof typeof ICON_BUTTON_SIZE_STYLES;
}

/** 只放圖示的正方形按鈕，尺寸與 Button 同高。 */
export const IconButton: React.FC<IconButtonProps> = ({
  icon,
  variant = 'ghost',
  size = 'md',
  className = '',
  type = 'button',
  ...props
}) => (
  <button
    type={type}
    data-variant={variant}
    className={cn(
      'inline-flex shrink-0 cursor-pointer items-center justify-center rounded-[var(--radius-control)] transition-all duration-200',
      'focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan/15',
      'disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50',
      ICON_BUTTON_SIZE_STYLES[size],
      BUTTON_VARIANT_STYLES[variant],
      className,
    )}
    {...props}
  >
    {icon}
  </button>
);
