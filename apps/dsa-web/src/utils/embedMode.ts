import { useLocation } from 'react-router-dom';

export const EMBED_MODE_STORAGE_KEY = 'dsa.embedMode';
const EMBED_QUERY_PARAM = 'embed';
const EMBED_IOS = 'ios';

function getEmbedStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/**
 * 判斷是否為內嵌模式（iOS 工具頁以 ?embed=ios 開啟）。
 * 站內換頁會丟掉 query，所以第一次看到參數就寫進 sessionStorage，之後同分頁都沿用。
 */
export function resolveEmbedMode(search: string, storage: Storage | null): boolean {
  const requested = new URLSearchParams(search).get(EMBED_QUERY_PARAM);
  if (requested === EMBED_IOS) {
    try {
      storage?.setItem(EMBED_MODE_STORAGE_KEY, EMBED_IOS);
    } catch {
      // 寫不進去只影響換頁後的判斷，這一頁仍以參數為準。
    }
    return true;
  }
  if (requested !== null) {
    return false;
  }
  try {
    return storage?.getItem(EMBED_MODE_STORAGE_KEY) === EMBED_IOS;
  } catch {
    return false;
  }
}

/** 外框元件（標頭、側欄、底部分頁、狀態列、⌘K、rail）一律走這個判斷。 */
export function useEmbedMode(): boolean {
  const { search } = useLocation();
  return resolveEmbedMode(search, getEmbedStorage());
}
