import type React from 'react';
import { Bell } from 'lucide-react';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { formatUiText } from '../../i18n/uiText';
import { ALERT_PAGE_TEXT } from '../../locales/featureText';
import { cn } from '../../utils/cn';

interface AlertBellLinkProps {
  code: string;
  className?: string;
}

/** 報告、盯盤、持股共用：帶代號開啟新增警報抽屜。用一般連結，這些元件不一定在 Router 內測試與渲染。 */
export const AlertBellLink: React.FC<AlertBellLinkProps> = ({ code, className }) => {
  const { language } = useUiLanguage();
  const label = formatUiText(ALERT_PAGE_TEXT[language].bell, { code });
  return (
    <a
      href={`/alerts?new=1&target=${encodeURIComponent(code)}`}
      aria-label={label}
      onClick={(event) => event.stopPropagation()}
      className={cn('inline-flex h-6 w-6 items-center justify-center rounded text-muted-text hover:bg-hover hover:text-foreground', className)}
    >
      <Bell className="h-3.5 w-3.5" aria-hidden="true" />
    </a>
  );
};
