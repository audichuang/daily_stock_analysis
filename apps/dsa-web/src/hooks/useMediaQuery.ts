import { useCallback, useSyncExternalStore } from 'react';

/** 外框斷點：不用 CSS 隱藏，因為隱藏的導覽仍在 DOM 裡，會被輔助工具重複讀到。 */
export const MOBILE_LAYOUT_QUERY = '(max-width: 1023.98px)';

function getMediaQueryList(query: string): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return null;
  }
  return window.matchMedia(query) ?? null;
}

export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = getMediaQueryList(query);
      list?.addEventListener?.('change', onChange);
      return () => list?.removeEventListener?.('change', onChange);
    },
    [query],
  );
  const getSnapshot = useCallback(() => Boolean(getMediaQueryList(query)?.matches), [query]);
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
