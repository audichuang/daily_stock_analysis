import type React from 'react';
import { useCallback, useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Drawer } from '../common/Drawer';
import { BottomTabs } from './BottomTabs';
import { GlobalStockSearch } from './GlobalStockSearch';
import { MarketStatusBar } from './MarketStatusBar';
import { ShellHeader } from './ShellHeader';
import { SidebarNav } from './SidebarNav';
import { DesktopUpdateIndicator } from './DesktopUpdateIndicator';
import { cn } from '../../utils/cn';
import { MOBILE_LAYOUT_QUERY, useMediaQuery } from '../../hooks/useMediaQuery';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { useEmbedMode } from '../../utils/embedMode';

type ShellProps = {
  children?: React.ReactNode;
};

const RAIL_EXPANDED_STORAGE_KEY = 'dsa.sidebarExpanded';
const RAIL_DEFAULT_EXPANDED_MIN_WIDTH = 1680;

function readRailExpanded(): boolean {
  try {
    const stored = window.localStorage.getItem(RAIL_EXPANDED_STORAGE_KEY);
    if (stored === 'true' || stored === 'false') {
      return stored === 'true';
    }
  } catch {
    // 讀不到偏好就走視窗寬度的預設值。
  }
  return window.innerWidth >= RAIL_DEFAULT_EXPANDED_MIN_WIDTH;
}

export const Shell: React.FC<ShellProps> = ({ children }) => {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [railExpanded, setRailExpanded] = useState(readRailExpanded);
  const { t } = useUiLanguage();
  const embedded = useEmbedMode();
  const isMobile = useMediaQuery(MOBILE_LAYOUT_QUERY);

  const toggleRail = useCallback(() => {
    const next = !railExpanded;
    setRailExpanded(next);
    try {
      window.localStorage.setItem(RAIL_EXPANDED_STORAGE_KEY, String(next));
    } catch {
      // 存不了只影響下次開啟的預設，這次切換仍然生效。
    }
  }, [railExpanded]);

  // 轉成桌機寬度就收掉抽屜，轉回手機時不會突然彈出。
  if (!isMobile && mobileOpen) {
    setMobileOpen(false);
  }

  if (embedded) {
    // iOS 工具頁內嵌：外框由原生 App 提供，這裡只留頁面內容。
    return (
      <div className="shell-root min-h-[100dvh] bg-background text-foreground" data-embedded="true">
        <div className="mx-auto flex w-full max-w-[1680px] px-3 py-3 sm:px-4 sm:py-4 lg:px-5">
          <main className="min-h-0 min-w-0 flex-1 touch-pan-y">
            {children ?? <Outlet />}
          </main>
        </div>
      </div>
    );
  }

  return (
    <div className="shell-root min-h-[100dvh] bg-background text-foreground">
      {isMobile ? <ShellHeader /> : null}
      <MarketStatusBar>
        <DesktopUpdateIndicator />
        {!isMobile ? <GlobalStockSearch /> : null}
      </MarketStatusBar>

      <div className="mx-auto flex w-full max-w-[1680px] px-3 py-3 sm:px-4 sm:py-4 lg:px-5">
        {!isMobile ? (
          <aside
            className={cn(
              'sticky top-[calc(var(--shell-status-height)+var(--shell-page-padding-y))] z-40 flex shrink-0 flex-col self-start overflow-visible rounded-[1.5rem] border border-[var(--shell-sidebar-border)] bg-card/72 p-2.5 shadow-soft-card backdrop-blur-sm transition-[width] duration-200',
              'max-h-[calc(100dvh-var(--shell-page-offset))]',
              railExpanded ? 'w-[172px]' : 'w-[72px]'
            )}
            aria-label={t('layout.desktopSidebar')}
          >
            <SidebarNav collapsed={!railExpanded} variant="rail" onToggleCollapsed={toggleRail} />
          </aside>
        ) : null}

        <main className="min-h-0 min-w-0 flex-1 touch-pan-y pb-[var(--shell-bottom-inset,0px)] lg:pl-3">
          {children ?? <Outlet />}
        </main>
      </div>

      {isMobile ? (
        <>
          <BottomTabs moreOpen={mobileOpen} onOpenMore={() => setMobileOpen(true)} />
          <Drawer
            isOpen={mobileOpen}
            onClose={() => setMobileOpen(false)}
            title={t('layout.navMenu')}
            width="max-w-xs"
            zIndex={90}
            side="left"
          >
            <SidebarNav onNavigate={() => setMobileOpen(false)} />
          </Drawer>
        </>
      ) : null}
    </div>
  );
};
