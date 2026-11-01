import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, BarChart3, Bell, BriefcaseBusiness, CalendarDays, Database, Ellipsis, Gauge, Home, Landmark, LineChart, LogOut, MessageSquareQuote, PanelLeftClose, PanelLeftOpen, Search, Settings2 } from 'lucide-react';
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
import { BOTTOM_TAB_PATHS } from './BottomTabs';

type SidebarNavProps = {
  collapsed?: boolean;
  onNavigate?: () => void;
  /** `rail` is the desktop sidebar; `default` is the mobile "more" drawer. */
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

const LOGO_TOGGLE_BUTTON_CLASS =
  'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-transparent text-secondary-text transition-colors hover:bg-[var(--nav-hover-bg)] hover:text-foreground';

const MORE_ITEM_CLASS =
  'flex h-10 w-full items-center gap-3 rounded-xl border border-transparent px-3 text-sm leading-none text-secondary-text transition-colors hover:bg-[var(--nav-hover-bg)] hover:text-foreground';

// Fade the bottom edge while more rail items sit below the fold.
const NAV_OVERFLOW_MASK_CLASS =
  '[mask-image:linear-gradient(to_bottom,black_calc(100%_-_28px),transparent)] [-webkit-mask-image:linear-gradient(to_bottom,black_calc(100%_-_28px),transparent)]';

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
      // The full name ("AI 建議") wraps to two lines in the collapsed rail; the old short key read as bare "建議".
      { key: 'decision-signals', labelKey: 'layout.nav.decisionSignals', shortLabelKey: 'layout.nav.decisionSignals', to: '/decision-signals', icon: Activity },
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

// The mobile drawer only lists pages the bottom tabs cannot reach.
const DRAWER_NAV_GROUPS = NAV_GROUPS
  .map((group) => ({ ...group, items: group.items.filter((item) => !BOTTOM_TAB_PATHS.includes(item.to)) }))
  .filter((group) => group.items.length > 0);

export const SidebarNav: React.FC<SidebarNavProps> = ({ collapsed = false, onNavigate, variant = 'default', onToggleCollapsed }) => {
  const { authEnabled, logout } = useAuth();
  const location = useLocation();
  const { t } = useUiLanguage();
  const completionBadge = useAgentChatStore((state) => state.completionBadge);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [navOverflowing, setNavOverflowing] = useState(false);
  const navRef = useRef<HTMLElement | null>(null);
  const moreRef = useRef<HTMLDivElement | null>(null);
  const isRail = variant === 'rail';
  const isTwoLineRail = isRail && collapsed;
  const navGroups = isRail ? NAV_GROUPS : DRAWER_NAV_GROUPS;
  const itemBaseClass = cn(
    'group relative flex w-full overflow-hidden rounded-2xl border border-transparent text-sm leading-none text-secondary-text transition-all',
    isTwoLineRail
      ? 'h-11 flex-col items-center justify-center gap-0.5 px-0.5'
      : isRail
        ? 'h-11 items-center gap-3 px-3'
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

  const updateNavOverflow = useCallback(() => {
    const nav = navRef.current;
    if (!nav) {
      return;
    }
    // 1px slack absorbs sub-pixel rounding at the end of the scroll range.
    setNavOverflowing(nav.scrollTop + nav.clientHeight < nav.scrollHeight - 1);
  }, []);

  // Keep the current page visible in a short rail, on mount and after every navigation.
  useEffect(() => {
    if (!isRail) {
      return;
    }
    const current = navRef.current?.querySelector<HTMLElement>('[aria-current="page"]');
    // jsdom (and very old engines) lack scrollIntoView; skipping it only loses the auto-scroll.
    current?.scrollIntoView?.({ block: 'nearest' });
    updateNavOverflow();
  }, [isRail, location.pathname, updateNavOverflow]);

  useEffect(() => {
    const nav = navRef.current;
    if (!isRail || !nav) {
      return undefined;
    }
    updateNavOverflow();
    window.addEventListener('resize', updateNavOverflow);
    // ResizeObserver catches the rail growing/shrinking without a window resize (collapse toggle).
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(updateNavOverflow);
    observer?.observe(nav);
    return () => {
      window.removeEventListener('resize', updateNavOverflow);
      observer?.disconnect();
    };
  }, [isRail, collapsed, updateNavOverflow]);

  useEffect(() => {
    if (!moreOpen) {
      return undefined;
    }
    const handlePointerDown = (event: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(event.target as Node)) {
        setMoreOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMoreOpen(false);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [moreOpen]);

  const collapseToggle = isRail && onToggleCollapsed ? (
    <button
      type="button"
      onClick={onToggleCollapsed}
      className={cn(LOGO_TOGGLE_BUTTON_CLASS, collapsed ? '' : 'ml-auto')}
      aria-label={collapsed ? t('layout.expandSidebar') : t('layout.collapseSidebar')}
    >
      {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
    </button>
  ) : null;

  return (
    <div className={cn('flex min-h-0 w-full flex-col', isRail ? '' : 'h-full')}>
      {isRail ? (
        <div
          className={cn(
            'flex shrink-0 items-center',
            collapsed ? 'mb-2 flex-col gap-1 pt-1' : 'mb-3 gap-3 px-2 pt-1'
          )}
        >
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[1rem] bg-primary-gradient text-[hsl(var(--primary-foreground))] shadow-[0_12px_28px_var(--nav-brand-shadow)]"
          >
            <BarChart3 className="h-[19px] w-[19px]" />
          </div>
          {!collapsed ? (
            <p className="min-w-0 truncate text-[0.95rem] font-semibold leading-none text-foreground">DSA</p>
          ) : null}
          {collapseToggle}
        </div>
      ) : null}

      <nav
        ref={navRef}
        onScroll={isRail ? updateNavOverflow : undefined}
        data-overflowing={isRail && navOverflowing ? 'true' : undefined}
        className={cn(
          'flex flex-col',
          isRail ? 'min-h-0 gap-1 overflow-y-auto' : 'flex-1 gap-1.5',
          isRail && navOverflowing ? NAV_OVERFLOW_MASK_CLASS : ''
        )}
        aria-label={t('layout.mainNav')}
      >
        {navGroups.map((group, groupIndex) => (
          <div key={group.key} role="group" aria-label={t(group.labelKey)} className={cn('flex flex-col', isRail ? 'gap-1' : 'gap-1.5')}>
            {collapsed ? (
              groupIndex > 0 ? <div className={cn('mx-2 border-t border-border/60', isRail ? 'my-1.5' : 'my-1')} aria-hidden="true" /> : null
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
                      {isTwoLineRail ? (
                        <span
                          data-testid="rail-short-label"
                          className="line-clamp-2 w-full break-words text-center text-[10px] leading-[1.1]"
                        >
                          {t(shortLabelKey)}
                        </span>
                      ) : null}
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
          ref={moreRef}
          data-testid="sidebar-toolbar"
          className={cn('relative mt-2 flex shrink-0 items-center border-t border-border/60 pt-2', collapsed ? 'justify-center' : 'px-1')}
        >
          <button
            type="button"
            onClick={() => setMoreOpen((open) => !open)}
            className={cn(TOOLBAR_BUTTON_CLASS, moreOpen ? itemActiveClass : '')}
            aria-haspopup="true"
            aria-expanded={moreOpen}
            aria-label={t('layout.more')}
            title={t('layout.more')}
          >
            <Ellipsis className="h-[18px] w-[18px] shrink-0" />
          </button>
          {moreOpen ? (
            <div
              data-testid="sidebar-more-panel"
              className="absolute bottom-0 left-full z-[95] ml-3 flex w-max min-w-[11rem] flex-col gap-1 rounded-2xl border border-border/70 bg-elevated p-1.5 shadow-[0_24px_48px_rgba(3,8,20,0.32)] backdrop-blur-xl"
            >
              <ThemeToggle
                variant="nav"
                collapsed={false}
                wrapperClassName="w-full"
                triggerClassName={MORE_ITEM_CLASS}
                triggerActiveClassName={itemActiveClass}
                iconClassName="h-[18px] w-[18px] shrink-0"
                labelClassName={itemLabelClass}
              />
              <UiLanguageToggle
                variant="nav"
                collapsed={false}
                wrapperClassName="w-full"
                triggerClassName={MORE_ITEM_CLASS}
                triggerActiveClassName={itemActiveClass}
                iconClassName="h-[18px] w-[18px] shrink-0"
                labelClassName={itemLabelClass}
              />
              {authEnabled ? (
                <button
                  type="button"
                  onClick={() => {
                    setMoreOpen(false);
                    setShowLogoutConfirm(true);
                  }}
                  className={MORE_ITEM_CLASS}
                  aria-label={t('layout.logout')}
                >
                  <LogOut className="h-[18px] w-[18px] shrink-0" />
                  <span className={itemLabelClass}>{t('layout.logout')}</span>
                </button>
              ) : null}
            </div>
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
