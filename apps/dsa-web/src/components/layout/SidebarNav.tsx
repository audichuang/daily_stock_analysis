import React, { useState } from 'react';
import { Activity, BarChart3, Bell, BriefcaseBusiness, CalendarDays, Database, Gauge, Home, Landmark, LineChart, LogOut, MessageSquareQuote, PanelLeftClose, PanelLeftOpen, Search, Settings2 } from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useAgentChatStore } from '../../stores/agentChatStore';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { ConfirmDialog } from '../common/ConfirmDialog';
import { StatusDot } from '../common/StatusDot';
import { UiLanguageToggle } from '../i18n/UiLanguageToggle';
import { ThemeToggle } from '../theme/ThemeToggle';

type SidebarNavProps = {
  collapsed?: boolean;
  onNavigate?: () => void;
  variant?: 'default' | 'rail';
  /** 桌機 rail 的展開／收合；不給就不顯示切換鈕。 */
  onToggleCollapsed?: () => void;
};

type NavItem = {
  key: string;
  labelKey: UiTextKey;
  shortLabelKey: UiTextKey;
  to: string;
  icon: React.ComponentType<{ className?: string }>;
  exact?: boolean;
  badge?: 'completion';
};

const TOOLBAR_BUTTON_CLASS =
  'inline-flex h-9 w-9 items-center justify-center rounded-xl border border-transparent text-secondary-text transition-colors hover:bg-[var(--nav-hover-bg)] hover:text-foreground';

const NAV_GROUPS: Array<{ key: string; labelKey: UiTextKey; items: NavItem[] }> = [
  {
    key: 'watch',
    labelKey: 'layout.navGroup.watch',
    items: [
      { key: 'board', labelKey: 'layout.nav.board', shortLabelKey: 'layout.navShort.board', to: '/board', icon: LineChart },
      { key: 'home', labelKey: 'layout.nav.home', shortLabelKey: 'layout.navShort.home', to: '/', icon: Home, exact: true },
      { key: 'portfolio', labelKey: 'layout.nav.portfolio', shortLabelKey: 'layout.navShort.portfolio', to: '/portfolio', icon: BriefcaseBusiness },
      { key: 'funds', labelKey: 'layout.nav.funds', shortLabelKey: 'layout.navShort.funds', to: '/funds', icon: Landmark },
      { key: 'calendar', labelKey: 'layout.nav.calendar', shortLabelKey: 'layout.navShort.calendar', to: '/calendar', icon: CalendarDays },
      { key: 'alerts', labelKey: 'layout.nav.alerts', shortLabelKey: 'layout.navShort.alerts', to: '/alerts', icon: Bell },
    ],
  },
  {
    key: 'research',
    labelKey: 'layout.navGroup.research',
    items: [
      { key: 'chat', labelKey: 'layout.nav.chat', shortLabelKey: 'layout.navShort.chat', to: '/chat', icon: MessageSquareQuote, badge: 'completion' },
      { key: 'screening', labelKey: 'layout.nav.screening', shortLabelKey: 'layout.navShort.screening', to: '/screening', icon: Search },
      { key: 'decision-signals', labelKey: 'layout.nav.decisionSignals', shortLabelKey: 'layout.navShort.decisionSignals', to: '/decision-signals', icon: Activity },
      { key: 'backtest', labelKey: 'layout.nav.backtest', shortLabelKey: 'layout.navShort.backtest', to: '/backtest', icon: BarChart3 },
    ],
  },
  {
    key: 'system',
    labelKey: 'layout.navGroup.system',
    items: [
      { key: 'data', labelKey: 'layout.nav.dataCenter', shortLabelKey: 'layout.navShort.dataCenter', to: '/data', icon: Database },
      { key: 'usage', labelKey: 'layout.nav.usage', shortLabelKey: 'layout.navShort.usage', to: '/usage', icon: Gauge },
      { key: 'settings', labelKey: 'layout.nav.settings', shortLabelKey: 'layout.navShort.settings', to: '/settings', icon: Settings2 },
    ],
  },
];

export const SidebarNav: React.FC<SidebarNavProps> = ({ collapsed = false, onNavigate, variant = 'default', onToggleCollapsed }) => {
  const { authEnabled, logout } = useAuth();
  const location = useLocation();
  const { t } = useUiLanguage();
  const completionBadge = useAgentChatStore((state) => state.completionBadge);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const isRail = variant === 'rail';
  const isTwoLineRail = isRail && collapsed;
  const itemBaseClass = cn(
    'group relative flex w-full overflow-hidden rounded-2xl border border-transparent text-sm leading-none text-secondary-text transition-all',
    isTwoLineRail
      ? 'h-[52px] flex-col items-center justify-center gap-1 px-0'
      : isRail
        ? 'h-[var(--nav-item-height)] items-center gap-3 px-3'
        : collapsed
          ? 'h-[var(--nav-item-height)] items-center justify-center px-0'
          : 'h-[var(--nav-item-height)] items-center gap-3 px-[var(--nav-item-padding-x)]'
  );
  const itemInteractiveClass = cn(
    itemBaseClass,
    'hover:bg-[var(--nav-hover-bg)] hover:text-foreground'
  );
  const itemActiveClass = 'border-[var(--nav-active-border)] bg-[var(--nav-active-bg)] font-medium text-[hsl(var(--primary))]';
  const itemIconClass = cn(isRail ? 'h-[18px] w-[18px]' : 'h-5 w-5', 'shrink-0');
  const itemLabelClass = 'truncate';

  return (
    <div className={cn('flex min-h-0 w-full flex-col', isRail ? '' : 'h-full')}>
      <div
        className={cn(
          'flex shrink-0 items-center',
          isRail ? (collapsed ? 'mb-3 pt-1' : 'mb-4 gap-3 px-2 pt-1') : 'mb-4 gap-2 px-1',
          collapsed ? 'justify-center' : ''
        )}
      >
        <div
          className={cn(
            'flex items-center justify-center bg-primary-gradient text-[hsl(var(--primary-foreground))] shadow-[0_12px_28px_var(--nav-brand-shadow)]',
            isRail ? 'h-9 w-9 rounded-[1rem]' : 'h-10 w-10 rounded-2xl'
          )}
        >
          <BarChart3 className={cn(isRail ? 'h-[19px] w-[19px]' : 'h-5 w-5')} />
        </div>
        {!collapsed ? (
          <p className={cn('min-w-0 truncate font-semibold text-foreground', isRail ? 'text-[0.95rem] leading-none' : 'text-sm')}>DSA</p>
        ) : null}
      </div>

      <nav className={cn('flex flex-col gap-1.5', isRail ? 'min-h-0 overflow-y-auto' : 'flex-1')} aria-label={t('layout.mainNav')}>
        {NAV_GROUPS.map((group, groupIndex) => (
          <div key={group.key} role="group" aria-label={t(group.labelKey)} className="flex flex-col gap-1.5">
            {collapsed ? (
              groupIndex > 0 ? <div className="mx-2 my-1 border-t border-border/60" aria-hidden="true" /> : null
            ) : (
              <p className={cn('px-3 pb-0.5 text-xs text-muted-text', groupIndex > 0 ? 'pt-3' : '')}>{t(group.labelKey)}</p>
            )}
            {group.items.map(({ key, labelKey, shortLabelKey, to, icon: Icon, exact, badge }) => {
              const label = t(labelKey);
              return (
                <NavLink
                  key={key}
                  to={to}
                  end={exact}
                  onClick={onNavigate}
                  aria-label={label}
                  className={({ isActive }) =>
                    cn(
                      itemInteractiveClass,
                      'shrink-0',
                      isActive ? itemActiveClass : ''
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon className={cn(itemIconClass, isActive ? 'text-[var(--nav-icon-active)]' : 'text-current')} />
                      {isTwoLineRail ? <span className="text-[11px] leading-none">{t(shortLabelKey)}</span> : null}
                      {!collapsed ? <span className={itemLabelClass}>{label}</span> : null}
                      {badge === 'completion' && completionBadge ? (
                        <StatusDot
                          tone="info"
                          data-testid="chat-completion-badge"
                          className={cn(
                            'absolute right-3 border-2 border-background shadow-[0_0_10px_var(--nav-indicator-shadow)]',
                            collapsed ? 'right-2 top-2' : ''
                          )}
                          aria-label={t('layout.newChatMessage')}
                        />
                      ) : null}
                    </>
                  )}
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      {isRail ? (
        <div
          data-testid="sidebar-toolbar"
          className={cn('mt-2 flex shrink-0 items-center gap-1 border-t border-border/60 pt-2', collapsed ? 'flex-col' : 'justify-between')}
        >
          <ThemeToggle
            variant="nav"
            collapsed
            triggerClassName={TOOLBAR_BUTTON_CLASS}
            triggerActiveClassName={itemActiveClass}
            iconClassName="h-[18px] w-[18px] shrink-0"
          />
          <UiLanguageToggle
            variant="nav"
            collapsed
            triggerClassName={TOOLBAR_BUTTON_CLASS}
            triggerActiveClassName={itemActiveClass}
            iconClassName="h-[18px] w-[18px] shrink-0"
          />
          {authEnabled ? (
            <button
              type="button"
              onClick={() => setShowLogoutConfirm(true)}
              className={TOOLBAR_BUTTON_CLASS}
              aria-label={t('layout.logout')}
              title={t('layout.logout')}
            >
              <LogOut className="h-[18px] w-[18px] shrink-0" />
            </button>
          ) : null}
          {onToggleCollapsed ? (
            <button
              type="button"
              onClick={onToggleCollapsed}
              className={TOOLBAR_BUTTON_CLASS}
              aria-label={collapsed ? t('layout.expandSidebar') : t('layout.collapseSidebar')}
            >
              {collapsed ? <PanelLeftOpen className="h-[18px] w-[18px]" /> : <PanelLeftClose className="h-[18px] w-[18px]" />}
            </button>
          ) : null}
        </div>
      ) : (
        <div className="mt-4 flex shrink-0 flex-col gap-1.5 border-t border-border/60 pt-3">
          <ThemeToggle
            variant="nav"
            collapsed={collapsed}
            wrapperClassName="w-full"
            triggerClassName={itemInteractiveClass}
            triggerActiveClassName={itemActiveClass}
            iconClassName={itemIconClass}
            labelClassName={itemLabelClass}
          />
          <UiLanguageToggle
            variant="nav"
            collapsed={collapsed}
            wrapperClassName="w-full"
            triggerClassName={itemInteractiveClass}
            triggerActiveClassName={itemActiveClass}
            iconClassName={itemIconClass}
            labelClassName={itemLabelClass}
          />
          {authEnabled ? (
            <button
              type="button"
              onClick={() => setShowLogoutConfirm(true)}
              className={cn(itemInteractiveClass, 'shrink-0')}
              aria-label={t('layout.logout')}
            >
              <LogOut className={itemIconClass} />
              {!collapsed ? <span className={itemLabelClass}>{t('layout.logout')}</span> : null}
            </button>
          ) : null}
        </div>
      )}

      <ConfirmDialog
        isOpen={showLogoutConfirm}
        title={t('layout.logoutTitle')}
        message={t(/^\/settings\/?$/.test(location.pathname) ? 'layout.logoutSettingsMessage' : 'layout.logoutMessage')}
        confirmText={t('layout.logoutConfirm')}
        cancelText={t('common.cancel')}
        isDanger
        onConfirm={() => {
          setShowLogoutConfirm(false);
          onNavigate?.();
          void logout();
        }}
        onCancel={() => setShowLogoutConfirm(false)}
      />
    </div>
  );
};
