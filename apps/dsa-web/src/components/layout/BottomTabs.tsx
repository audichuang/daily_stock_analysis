import type React from 'react';
import { BriefcaseBusiness, Ellipsis, Home, LineChart, MessageSquareQuote } from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { useAgentChatStore } from '../../stores/agentChatStore';
import { cn } from '../../utils/cn';
import { StatusDot } from '../common/StatusDot';

const TABS: Array<{
  to: string;
  labelKey: UiTextKey;
  icon: React.ComponentType<{ className?: string }>;
  exact?: boolean;
}> = [
  { to: '/board', labelKey: 'layout.nav.board', icon: LineChart },
  { to: '/', labelKey: 'layout.nav.home', icon: Home, exact: true },
  { to: '/chat', labelKey: 'layout.nav.chat', icon: MessageSquareQuote },
  { to: '/portfolio', labelKey: 'layout.nav.portfolio', icon: BriefcaseBusiness },
];

const TAB_CLASS = 'relative flex h-14 flex-col items-center justify-center gap-1 text-[11px] leading-none transition-colors';

/** 手機底部分頁；其他頁面放在「更多」開啟的導覽抽屜。 */
export const BottomTabs: React.FC<{ onOpenMore: () => void; moreOpen: boolean }> = ({ onOpenMore, moreOpen }) => {
  const { t } = useUiLanguage();
  const { pathname } = useLocation();
  const completionBadge = useAgentChatStore((state) => state.completionBadge);
  const inMore = !TABS.some((tab) => (tab.exact ? pathname === tab.to : pathname.startsWith(tab.to)));

  return (
    <nav
      data-shell-tabbar
      aria-label={t('layout.bottomTabs')}
      className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-border/70 bg-background pb-[env(safe-area-inset-bottom,0px)]"
    >
      {TABS.map(({ to, labelKey, icon: Icon, exact }) => (
        <NavLink
          key={to}
          to={to}
          end={exact}
          className={({ isActive }) => cn(TAB_CLASS, isActive ? 'text-[hsl(var(--primary))]' : 'text-secondary-text')}
        >
          <Icon className="h-5 w-5" />
          <span>{t(labelKey)}</span>
          {to === '/chat' && completionBadge ? (
            <StatusDot tone="info" className="absolute right-1/4 top-2" aria-label={t('layout.newChatMessage')} />
          ) : null}
        </NavLink>
      ))}
      <button
        type="button"
        onClick={onOpenMore}
        aria-expanded={moreOpen}
        className={cn(TAB_CLASS, moreOpen || inMore ? 'text-[hsl(var(--primary))]' : 'text-secondary-text')}
      >
        <Ellipsis className="h-5 w-5" />
        <span>{t('layout.more')}</span>
      </button>
    </nav>
  );
};
