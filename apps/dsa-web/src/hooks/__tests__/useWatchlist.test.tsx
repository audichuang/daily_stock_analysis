import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useWatchlist } from '../useWatchlist';

const {
  mockGetWatchlist,
  mockAddToWatchlist,
  mockRemoveFromWatchlist,
  mockGetWatchlistGroups,
  mockSaveWatchlistGroups,
} = vi.hoisted(() => ({
  mockGetWatchlist: vi.fn(),
  mockAddToWatchlist: vi.fn(),
  mockRemoveFromWatchlist: vi.fn(),
  mockGetWatchlistGroups: vi.fn(),
  mockSaveWatchlistGroups: vi.fn(),
}));

vi.mock('../../api/systemConfig', () => ({
  systemConfigApi: {
    getWatchlist: mockGetWatchlist,
    addToWatchlist: mockAddToWatchlist,
    removeFromWatchlist: mockRemoveFromWatchlist,
    getWatchlistGroups: mockGetWatchlistGroups,
    saveWatchlistGroups: mockSaveWatchlistGroups,
  },
}));

describe('useWatchlist', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetWatchlist.mockResolvedValue([]);
    mockAddToWatchlist.mockResolvedValue([]);
    mockRemoveFromWatchlist.mockResolvedValue([]);
    mockGetWatchlistGroups.mockResolvedValue({ groups: [], ungrouped: [] });
    mockSaveWatchlistGroups.mockResolvedValue({ groups: [], ungrouped: [] });
  });

  it('keeps the watchlist usable when groups cannot be loaded', async () => {
    mockGetWatchlist.mockResolvedValue(['2330.TW']);
    mockGetWatchlistGroups.mockRejectedValue(new Error('404'));

    const { result } = renderHook(() => useWatchlist());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });
    expect(result.current.watchlistCodes).toEqual(['2330.TW']);
    expect(result.current.watchlistGroups).toEqual([]);
  });

  it('reloads groups after removing a code because the server prunes them', async () => {
    mockGetWatchlist.mockResolvedValue(['2330.TW']);
    mockGetWatchlistGroups.mockResolvedValue({ groups: [{ name: 'Tech', codes: ['2330.TW'] }], ungrouped: [] });

    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => {
      expect(result.current.watchlistGroups).toHaveLength(1);
    });

    mockGetWatchlistGroups.mockResolvedValue({ groups: [{ name: 'Tech', codes: [] }], ungrouped: [] });
    await act(async () => {
      await result.current.removeFromWatchlist('2330.TW');
    });

    await waitFor(() => {
      expect(result.current.watchlistGroups).toEqual([{ name: 'Tech', codes: [] }]);
    });
  });

  it('stores the groups the server returns after saving', async () => {
    mockSaveWatchlistGroups.mockResolvedValue({ groups: [{ name: 'Saved', codes: [] }], ungrouped: [] });

    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });
    await act(async () => {
      await result.current.saveWatchlistGroups([{ name: 'Sent', codes: [] }]);
    });

    expect(mockSaveWatchlistGroups).toHaveBeenCalledWith([{ name: 'Sent', codes: [] }]);
    expect(result.current.watchlistGroups).toEqual([{ name: 'Saved', codes: [] }]);
  });

  it('matches raw HK watchlist entries against prefixed and suffixed variants', async () => {
    mockGetWatchlist.mockResolvedValue(['00700']);

    const { result } = renderHook(() => useWatchlist());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isInWatchlist('00700')).toBe(true);
    expect(result.current.isInWatchlist('HK00700')).toBe(true);
    expect(result.current.isInWatchlist('00700.HK')).toBe(true);
    expect(result.current.isInWatchlist('HK01810')).toBe(false);
  });

  it('removes the matched raw watchlist entry instead of adding a duplicate variant', async () => {
    mockGetWatchlist.mockResolvedValue(['00700']);
    mockRemoveFromWatchlist.mockResolvedValue([]);

    const { result } = renderHook(() => useWatchlist());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.toggleWatchlist('HK00700');
    });

    expect(mockRemoveFromWatchlist).toHaveBeenCalledWith('00700');
    expect(mockAddToWatchlist).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(result.current.watchlistCodes).toEqual([]);
    });
  });

  it('compares submitted and stored US tickers case-insensitively', async () => {
    mockGetWatchlist.mockResolvedValue(['aapl']);
    mockRemoveFromWatchlist.mockResolvedValue([]);

    const { result } = renderHook(() => useWatchlist());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isInWatchlist('AAPL')).toBe(true);

    await act(async () => {
      await result.current.toggleWatchlist('AAPL');
    });

    expect(mockRemoveFromWatchlist).toHaveBeenCalledWith('aapl');
    expect(mockAddToWatchlist).not.toHaveBeenCalled();
  });
});
