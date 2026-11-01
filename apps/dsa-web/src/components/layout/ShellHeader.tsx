import type React from 'react';
import { useLocation } from 'react-router-dom';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { useEmbedMode } from '../../utils/embedMode';

const TITLES: Record<string, UiTextKey> = {
  '/': 'layout.nav.home',
  '/board': 'layout.nav.board',
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

/** 手機標題列：48px、不透明，高度計算見 index.css 的 --shell-header-height。 */
export const ShellHeader: React.FC = () => {
  const location = useLocation();
  const { t } = useUiLanguage();
  const titleKey = TITLES[location.pathname];
  const embedded = useEmbedMode();

  if (embedded) {
    return null;
  }

  return (
    <header className="sticky top-0 z-30 border-b border-border/60 bg-background pt-[env(safe-area-inset-top,0px)]">
      <div className="flex h-12 items-center px-4">
        <p className="truncate text-sm font-semibold text-foreground">
          {titleKey ? t(titleKey) : t('layout.appFallbackTitle')}
        </p>
      </div>
    </header>
  );
};
