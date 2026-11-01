import { useCallback, useEffect, useRef, useState } from 'react';
import { systemConfigApi, type WatchlistGroup } from '../api/systemConfig';
import { findMatchingStockCode, includesStockCode } from '../utils/stockCode';

export interface UseWatchlistReturn {
  watchlistCodes: string[];
  watchlistGroups: WatchlistGroup[];
  saveWatchlistGroups: (groups: WatchlistGroup[]) => Promise<void>;
  isLoading: boolean;
  isActioning: boolean;
  actionMessage: string | null;
  isInWatchlist: (stockCode: string) => boolean;
  addToWatchlist: (stockCode: string) => Promise<void>;
  removeFromWatchlist: (stockCode: string) => Promise<void>;
  toggleWatchlist: (stockCode: string) => Promise<void>;
  refresh: () => Promise<void>;
}

export function useWatchlist(): UseWatchlistReturn {
  const [codes, setCodes] = useState<string[]>([]);
  const [groups, setGroups] = useState<WatchlistGroup[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isActioning, setIsActioning] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const messageTimerRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (messageTimerRef.current !== null) {
        window.clearTimeout(messageTimerRef.current);
      }
    };
  }, []);

  const loadGroups = useCallback(async () => {
    try {
      const result = await systemConfigApi.getWatchlistGroups();
      if (mountedRef.current) {
        setGroups(result.groups);
      }
    } catch {
      // 分組是附加資訊，讀不到就維持現狀，不影響自選清單。
    }
  }, []);

  const refresh = useCallback(async () => {
    // Codes and groups are independent reads: fire both at once instead of waiting on the codes first.
    const loadCodes = async () => {
      try {
        const result = await systemConfigApi.getWatchlist();
        if (mountedRef.current) {
          setCodes(result);
        }
      } catch {
        // keep existing codes
      }
    };
    await Promise.all([loadCodes(), loadGroups()]);
  }, [loadGroups]);

  useEffect(() => {
    setIsLoading(true);
    void refresh().finally(() => {
      if (mountedRef.current) {
        setIsLoading(false);
      }
    });
  }, [refresh]);

  const showMessage = useCallback((msg: string) => {
    if (messageTimerRef.current !== null) {
      window.clearTimeout(messageTimerRef.current);
    }
    setActionMessage(msg);
    messageTimerRef.current = window.setTimeout(() => {
      if (mountedRef.current) {
        setActionMessage(null);
      }
    }, 3000);
  }, []);

  const isInWatchlist = useCallback(
    (stockCode: string) => includesStockCode(codes, stockCode),
    [codes],
  );

  const addToWatchlist = useCallback(async (stockCode: string) => {
    if (!stockCode || isActioning) return;
    setIsActioning(true);
    try {
      const result = await systemConfigApi.addToWatchlist(stockCode);
      if (mountedRef.current) {
        setCodes(result);
        showMessage(`已加入自选 ${stockCode}`);
      }
    } catch {
      if (mountedRef.current) showMessage('操作失败');
    } finally {
      if (mountedRef.current) setIsActioning(false);
    }
  }, [isActioning, showMessage]);

  const removeFromWatchlist = useCallback(async (stockCode: string) => {
    if (!stockCode || isActioning) return;
    setIsActioning(true);
    try {
      const result = await systemConfigApi.removeFromWatchlist(stockCode);
      if (mountedRef.current) {
        setCodes(result);
        showMessage(`已从自选移除 ${stockCode}`);
        // 後端移除時會連帶清分組。
        void loadGroups();
      }
    } catch {
      if (mountedRef.current) showMessage('操作失败');
    } finally {
      if (mountedRef.current) setIsActioning(false);
    }
  }, [isActioning, loadGroups, showMessage]);

  const saveWatchlistGroups = useCallback(async (nextGroups: WatchlistGroup[]) => {
    setIsActioning(true);
    try {
      const result = await systemConfigApi.saveWatchlistGroups(nextGroups);
      if (mountedRef.current) setGroups(result.groups);
    } catch {
      if (mountedRef.current) showMessage('操作失败');
    } finally {
      if (mountedRef.current) setIsActioning(false);
    }
  }, [showMessage]);

  const toggleWatchlist = useCallback(async (stockCode: string) => {
    const existingStockCode = findMatchingStockCode(codes, stockCode);
    if (existingStockCode) {
      await removeFromWatchlist(existingStockCode);
    } else {
      await addToWatchlist(stockCode);
    }
  }, [codes, removeFromWatchlist, addToWatchlist]);

  return {
    watchlistCodes: codes,
    watchlistGroups: groups,
    saveWatchlistGroups,
    isLoading,
    isActioning,
    actionMessage,
    isInWatchlist,
    addToWatchlist,
    removeFromWatchlist,
    toggleWatchlist,
    refresh,
  };
}
