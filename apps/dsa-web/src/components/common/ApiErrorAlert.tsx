import type React from 'react';
import type { ParsedApiError } from '../../api/error';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

const LONG_MESSAGE_THRESHOLD = 200;
const CLAMP_LINES = 3;

interface ApiErrorAlertProps {
  error: ParsedApiError;
  className?: string;
  actionLabel?: string;
  onAction?: () => void;
  dismissLabel?: string;
  onDismiss?: () => void;
}

export const ApiErrorAlert: React.FC<ApiErrorAlertProps> = ({
  error,
  className = '',
  actionLabel,
  onAction,
  dismissLabel,
  onDismiss,
}) => {
  const { t } = useUiLanguage();
  const trimmedMessage = error.message.trim();
  const trimmedRaw = error.rawMessage.trim();
  // Only a long message (over 200 chars or more than three lines) is clamped, and then it always gets its
  // full text in the details, even when identical to rawMessage (the generic path uses rawMessage as the message).
  const isLongMessage = trimmedMessage.length > LONG_MESSAGE_THRESHOLD
    || trimmedMessage.split('\n').length > CLAMP_LINES;
  const showRaw = Boolean(trimmedRaw) && trimmedRaw !== trimmedMessage;
  const detailTexts = [isLongMessage ? error.message : null, showRaw ? error.rawMessage : null].filter(
    (text): text is string => Boolean(text),
  );
  const showDetails = detailTexts.length > 0;

  return (
    <div
      className={`rounded-xl border border-[hsl(var(--color-danger-alert-border)/0.3)] bg-[hsl(var(--color-danger-alert-bg)/0.1)] px-4 py-3 text-[hsl(var(--color-danger-alert-text))] ${className}`}
      role="alert"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">{error.title}</p>
          <p className={`mt-1 ${isLongMessage ? 'line-clamp-3 ' : ''}whitespace-pre-line break-words text-xs opacity-90 [overflow-wrap:anywhere]`}>{error.message}</p>
        </div>
        {onDismiss ? (
          <button
            type="button"
            className="shrink-0 rounded-md border border-[hsl(var(--color-danger-alert-border)/0.3)] bg-[hsl(var(--color-danger-alert-bg)/0.1)] px-2 py-1 text-[11px] text-[hsl(var(--color-danger-alert-text))] transition hover:bg-[hsl(var(--color-danger-alert-bg)/0.15)]"
            onClick={onDismiss}
          >
            {dismissLabel ?? t('common.close')}
          </button>
        ) : null}
      </div>
      {showDetails ? (
        <details className="mt-3 rounded-lg border border-subtle bg-surface-2 px-3 py-2">
          <summary className="cursor-pointer text-xs text-[hsl(var(--color-danger-alert-text))] opacity-90">{t('common.details')}</summary>
          {detailTexts.map((text, index) => (
            <pre
              key={index}
              className="mt-2 whitespace-pre-wrap break-words text-[11px] leading-5 text-[hsl(var(--color-danger-alert-text))] opacity-85 [overflow-wrap:anywhere]"
            >
              {text}
            </pre>
          ))}
        </details>
      ) : null}
      {actionLabel && onAction ? (
        <button
          type="button"
          className="mt-3 inline-flex items-center justify-center rounded-md border border-[hsl(var(--color-danger-alert-border)/0.3)] bg-[hsl(var(--color-danger-alert-bg)/0.1)] px-3 py-1.5 text-xs font-medium text-[hsl(var(--color-danger-alert-text))] transition hover:bg-[hsl(var(--color-danger-alert-bg)/0.15)]"
          onClick={onAction}
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
};
