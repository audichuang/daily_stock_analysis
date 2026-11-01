import type React from 'react';
import { useLocation } from 'react-router-dom';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { useEmbedMode } from '../../utils/embedMode';
import { ShellHeaderActionsSlot } from './ShellHeaderActions';

// Single source for page names: shell header, document.title and the sidebar share these keys.
const TITLES: Record<string, UiTextKey> = {
  '/': 'layout.route.home.title',
  '/board': 'layout.route.board.title',
  '/calendar': 'layout.route.calendar.title',
  '/chat': 'layout.route.chat.title',
  '/portfolio': 'layout.route.portfolio.title',
  '/funds': 'layout.route.funds.title',
  '/screening': 'layout.route.screening.title',
  '/decision-signals': 'layout.route.decisionSignals.title',
  '/backtest': 'layout.route.backtest.title',
  '/alerts': 'layout.route.alerts.title',
  '/data': 'layout.route.dataCenter.title',
  '/usage': 'layout.route.usage.title',
  '/settings': 'layout.route.settings.title',
};

/** Page-name key for a route, or null for routes outside the navigation (404, login). */
// eslint-disable-next-line react-refresh/only-export-components -- shared lookup used by Shell for document.title
export function resolveShellTitleKey(pathname: string): UiTextKey | null {
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  return TITLES[normalized] ?? null;
}

/** 手機標題列：48px、不透明，高度計算見 index.css 的 --shell-header-height。 */
export const ShellHeader: React.FC = () => {
  const location = useLocation();
  const { t } = useUiLanguage();
  const titleKey = resolveShellTitleKey(location.pathname);
  const embedded = useEmbedMode();

  if (embedded) {
    return null;
  }

  return (
    <header className="sticky top-0 z-30 border-b border-border/60 bg-background pt-[env(safe-area-inset-top,0px)]">
      <div className="flex h-12 items-center gap-3 px-4">
        <p className="min-w-0 truncate text-base font-semibold text-foreground" data-testid="shell-header-title">
          {titleKey ? t(titleKey) : t('layout.appFallbackTitle')}
        </p>
        <ShellHeaderActionsSlot />
      </div>
    </header>
  );
};
