import type React from 'react';
import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';

type ShellHeaderContextValue = {
  /** Portal target inside the mobile shell header; null when the header is not mounted. */
  actionsTarget: HTMLElement | null;
  setActionsTarget: (element: HTMLElement | null) => void;
  /** Optional page-provided document title (e.g. the open chat conversation). */
  titleDetail: string | null;
  setTitleDetail: (detail: string | null) => void;
};

const ShellHeaderContext = createContext<ShellHeaderContextValue | null>(null);

/** Provided once by Shell; pages talk to the shell header through it. */
export const ShellHeaderProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [actionsTarget, setActionsTarget] = useState<HTMLElement | null>(null);
  const [titleDetail, setTitleDetail] = useState<string | null>(null);
  const value = useMemo(
    () => ({ actionsTarget, setActionsTarget, titleDetail, setTitleDetail }),
    [actionsTarget, titleDetail],
  );
  return <ShellHeaderContext.Provider value={value}>{children}</ShellHeaderContext.Provider>;
};

// eslint-disable-next-line react-refresh/only-export-components -- hook co-located with its context
export function useShellHeaderContext(): ShellHeaderContextValue | null {
  return useContext(ShellHeaderContext);
}

/** True when the mobile shell header is mounted and can host page actions. */
// eslint-disable-next-line react-refresh/only-export-components -- hook co-located with its context
export function useShellHeaderActionsAvailable(): boolean {
  return Boolean(useContext(ShellHeaderContext)?.actionsTarget);
}

/**
 * Let a page override document.title (pure text, no site suffix), e.g. the chat conversation title.
 * Passing null/empty falls back to the route's page name.
 */
// eslint-disable-next-line react-refresh/only-export-components -- hook co-located with its context
export function useShellDocumentTitle(detail: string | null | undefined): void {
  const setTitleDetail = useContext(ShellHeaderContext)?.setTitleDetail;
  const normalized = detail?.trim() || null;
  useEffect(() => {
    if (!setTitleDetail) {
      return undefined;
    }
    setTitleDetail(normalized);
    return () => setTitleDetail(null);
  }, [setTitleDetail, normalized]);
}

/** Slot rendered by ShellHeader at the right edge of the mobile title bar. */
export const ShellHeaderActionsSlot: React.FC = () => {
  const setActionsTarget = useContext(ShellHeaderContext)?.setActionsTarget;
  return (
    <div
      ref={setActionsTarget}
      data-testid="shell-header-actions"
      className="ml-auto flex shrink-0 items-center justify-end gap-2 empty:hidden"
    />
  );
};

/**
 * Render page primary actions into the mobile shell title bar.
 * Renders nothing when the header is not mounted (desktop, iOS embed, or outside Shell),
 * so pages should keep their inline actions for those cases (see useShellHeaderActionsAvailable).
 */
export const ShellHeaderActions: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const target = useContext(ShellHeaderContext)?.actionsTarget;
  return target ? createPortal(children, target) : null;
};
