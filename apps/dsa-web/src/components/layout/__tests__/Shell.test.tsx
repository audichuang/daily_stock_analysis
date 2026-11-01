import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Link, MemoryRouter } from 'react-router-dom';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { useMarketIndexStore } from '../../../stores/marketIndexStore';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { ThemeProvider } from '../../theme/ThemeProvider';
import { Shell } from '../Shell';
import { ShellHeader } from '../ShellHeader';
import { ShellHeaderActions, useShellDocumentTitle } from '../ShellHeaderActions';

const mockLogout = vi.fn().mockResolvedValue(undefined);
const { getIndicesSnapshot } = vi.hoisted(() => ({ getIndicesSnapshot: vi.fn() }));

vi.mock('../../../api/stocks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/stocks')>();
  return { ...actual, stocksApi: { ...actual.stocksApi, getIndicesSnapshot } };
});

// 搜尋對話框只驗開關，不載入真的股票索引。
vi.mock('../../StockAutocomplete', () => ({
  StockAutocomplete: () => <input aria-label="stock search stub" />,
}));

vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({
    authEnabled: true,
    logout: mockLogout,
  }),
}));

vi.mock('../../../stores/agentChatStore', () => ({
  useAgentChatStore: (selector: (state: { completionBadge: boolean }) => unknown) =>
    selector({ completionBadge: true }),
}));

const viewport = { mobile: false };

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: query === '(prefers-color-scheme: dark)' || (viewport.mobile && query.includes('max-width: 1023')),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

const snapshot = (codes: string[]) => ({
  items: codes.map((code) => ({
    code, name: code, current: 100, change: 1, changePct: 1, source: null, asOf: '2026-11-01T05:00:00Z',
  })),
  marketPhase: 'intraday',
  marketOpen: true,
});

const renderShellAt = (entry: string) =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <ThemeProvider>
        <Shell>
          <Link to="/alerts">go to alerts</Link>
        </Shell>
      </ThemeProvider>
    </MemoryRouter>
  );

describe('Shell', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
    viewport.mobile = false;
    useMarketIndexStore.getState().reset();
    getIndicesSnapshot.mockReset();
    getIndicesSnapshot.mockImplementation(async (region: string) =>
      snapshot(region === 'tw' ? ['TWII', 'TPEX'] : ['SPX', 'IXIC', 'DJI', 'VIX']));
  });

  afterEach(() => {
    delete (window as { dsaDesktop?: unknown }).dsaDesktop;
    vi.useRealTimers();
  });
  it.skip('renders navigation, theme toggle and completion badge', () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ThemeProvider>
          <Shell>
            <div>page content</div>
          </Shell>
        </ThemeProvider>
      </MemoryRouter>
    );

    expect(screen.getAllByRole('button', { name: '切换主题' }).length).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: '问股' })).toBeInTheDocument();
    expect(screen.getByTestId('chat-completion-badge')).toBeInTheDocument();
    const logoutButton = screen.getByRole('button', { name: '退出' });
    expect(logoutButton).toBeInTheDocument();
    expect(logoutButton).toHaveClass('cursor-pointer');
  });

  it.skip('opens the theme menu from the sidebar toggle', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ThemeProvider>
          <Shell>
            <div>page content</div>
          </Shell>
        </ThemeProvider>
      </MemoryRouter>
    );

    fireEvent.click(screen.getAllByRole('button', { name: '切换主题' })[0]);

    expect(await screen.findByRole('menu', { name: '主题模式' })).toBeInTheDocument();
  });

  it('hides the desktop update entry outside Electron runtime', () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ThemeProvider>
          <Shell>
            <div>page content</div>
          </Shell>
        </ThemeProvider>
      </MemoryRouter>
    );

    expect(screen.queryByRole('button', { name: '桌面端更新' })).not.toBeInTheDocument();
  });

  it('shows the desktop update entry in Electron runtime', async () => {
    (window as { dsaDesktop?: unknown }).dsaDesktop = {
      version: '3.30.0',
      getUpdateState: vi.fn().mockResolvedValue({ status: 'idle', currentVersion: '3.30.0' }),
      checkForUpdates: vi.fn(),
      openReleasePage: vi.fn(),
      onUpdateStateChange: vi.fn(() => () => undefined),
    };

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ThemeProvider>
          <Shell>
            <div>page content</div>
          </Shell>
        </ThemeProvider>
      </MemoryRouter>
    );

    expect(await screen.findByRole('button', { name: '桌面端更新' })).toBeInTheDocument();
  });

  it('hides the whole frame with ?embed=ios and keeps it hidden after in-app navigation', () => {
    viewport.mobile = true;
    renderShellAt('/portfolio?embed=ios');

    const expectNoFrame = () => {
      expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
      expect(screen.queryByRole('banner')).not.toBeInTheDocument();
      expect(screen.queryByRole('navigation', { name: '底部分页' })).not.toBeInTheDocument();
      expect(screen.queryByRole('region', { name: '大盘状态' })).not.toBeInTheDocument();
    };
    expectNoFrame();
    expect(getIndicesSnapshot).not.toHaveBeenCalled();

    // 換頁後 query 已不在，只有 sessionStorage 的旗標能維持內嵌。
    fireEvent.click(screen.getByRole('link', { name: 'go to alerts' }));

    expect(screen.getByRole('link', { name: 'go to alerts' })).toBeInTheDocument();
    expectNoFrame();
    expect(getIndicesSnapshot).not.toHaveBeenCalled();
  });

  it('does not open the global search with the shortcut in embed mode', () => {
    renderShellAt('/portfolio?embed=ios');
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    expect(screen.queryByRole('dialog', { name: '搜索股票' })).not.toBeInTheDocument();
  });

  it('keeps the normal frame without the parameter or with another value', () => {
    const { unmount } = renderShellAt('/portfolio');
    expect(screen.getByRole('complementary')).toBeInTheDocument();
    unmount();

    renderShellAt('/portfolio?embed=web');
    expect(screen.getByRole('complementary')).toBeInTheDocument();
  });

  it('uses bottom tabs and a header on mobile, the sidebar on desktop', () => {
    viewport.mobile = true;
    const { unmount } = renderShellAt('/decision-signals');

    const tabs = screen.getByRole('navigation', { name: '底部分页' });
    expect(within(tabs).getAllByRole('link').map((link) => link.getAttribute('href')))
      .toEqual(['/board', '/', '/chat', '/portfolio']);
    expect(screen.getByRole('banner')).toHaveTextContent('AI 建议');
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument();

    // 「更多」開抽屜，看得到底部分頁放不下的頁面。
    fireEvent.click(within(tabs).getByRole('button', { name: '更多' }));
    expect(screen.getByRole('link', { name: '设置' })).toBeInTheDocument();
    unmount();

    viewport.mobile = false;
    renderShellAt('/portfolio');
    expect(screen.queryByRole('navigation', { name: '底部分页' })).not.toBeInTheDocument();
    expect(screen.queryByRole('banner')).not.toBeInTheDocument();
    expect(screen.getByRole('complementary')).toBeInTheDocument();
  });

  it('shows TW and US indices and only the requested US codes', async () => {
    renderShellAt('/portfolio');

    expect(await screen.findByTestId('status-index-SPX')).toBeInTheDocument();
    expect(screen.getByTestId('status-index-TWII')).toBeInTheDocument();
    expect(screen.getByTestId('status-index-TPEX')).toBeInTheDocument();
    expect(screen.getByTestId('status-index-IXIC')).toBeInTheDocument();
    expect(screen.queryByTestId('status-index-VIX')).not.toBeInTheDocument();
    expect(screen.getByText('台股 盘中')).toBeInTheDocument();
  });

  it('still shows TW indices when the US request fails', async () => {
    getIndicesSnapshot.mockImplementation(async (region: string) => {
      if (region === 'us') {
        throw new Error('us down');
      }
      return snapshot(['TWII', 'TPEX']);
    });
    renderShellAt('/portfolio');

    expect(await screen.findByTestId('status-index-TWII')).toBeInTheDocument();
    expect(screen.queryByTestId('status-index-SPX')).not.toBeInTheDocument();
  });

  it('polls every 60 seconds and pauses while the tab is hidden', async () => {
    vi.useFakeTimers();
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    try {
      renderShellAt('/portfolio');
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(getIndicesSnapshot).toHaveBeenCalledTimes(2);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      expect(getIndicesSnapshot).toHaveBeenCalledTimes(4);

      visibility.mockReturnValue('hidden');
      fireEvent(document, new Event('visibilitychange'));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(180_000);
      });
      expect(getIndicesSnapshot).toHaveBeenCalledTimes(4);

      visibility.mockReturnValue('visible');
      fireEvent(document, new Event('visibilitychange'));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(getIndicesSnapshot).toHaveBeenCalledTimes(6);
    } finally {
      visibility.mockRestore();
    }
  });

  it('opens the global search with the shortcut only when asked', async () => {
    renderShellAt('/portfolio');
    expect(screen.queryByRole('dialog', { name: '搜索股票' })).not.toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    expect(await screen.findByRole('dialog', { name: '搜索股票' })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '搜索股票' })).not.toBeInTheDocument());
  });

  it('starts as a 72px rail below 1680px and remembers the expanded choice', () => {
    vi.stubGlobal('innerWidth', 1440);
    try {
      const { unmount } = renderShellAt('/portfolio');
      expect(screen.getByRole('complementary')).toHaveClass('w-[72px]');

      fireEvent.click(screen.getByRole('button', { name: '展开侧边栏' }));
      expect(screen.getByRole('complementary')).toHaveClass('w-[172px]');
      unmount();

      renderShellAt('/portfolio');
      expect(screen.getByRole('complementary')).toHaveClass('w-[172px]');
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('starts expanded at 1680px but honours a stored collapse', () => {
    vi.stubGlobal('innerWidth', 1680);
    try {
      const { unmount } = renderShellAt('/portfolio');
      expect(screen.getByRole('complementary')).toHaveClass('w-[172px]');

      fireEvent.click(screen.getByRole('button', { name: '折叠侧边栏' }));
      unmount();

      renderShellAt('/portfolio');
      expect(screen.getByRole('complementary')).toHaveClass('w-[72px]');
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('renders ShellHeader only outside embed mode', () => {
    const header = (entry: string) => (
      <MemoryRouter initialEntries={[entry]}>
        <ThemeProvider>
          <ShellHeader />
        </ThemeProvider>
      </MemoryRouter>
    );

    const { unmount } = render(header('/portfolio'));
    expect(screen.getByRole('banner')).toBeInTheDocument();
    unmount();

    render(header('/portfolio?embed=ios'));
    expect(screen.queryByRole('banner')).not.toBeInTheDocument();
  });

  it('drops side padding and reserves the bottom safe area in embed mode', () => {
    renderShellAt('/alerts?embed=ios');
    const frame = screen.getByTestId('shell-embed-frame');
    expect(frame).toHaveClass('px-0', 'pt-2', 'pb-[calc(env(safe-area-inset-bottom)+1.5rem)]');
    expect(frame).not.toHaveClass('px-3');
  });

  it('sets document.title to the plain page name, in embed mode too', () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    document.title = 'stale';
    const renderEn = (entry: string) =>
      render(
        <MemoryRouter initialEntries={[entry]}>
          <UiLanguageProvider>
            <ThemeProvider>
              <Shell>
                <Link to="/usage">go to usage</Link>
              </Shell>
            </ThemeProvider>
          </UiLanguageProvider>
        </MemoryRouter>
      );

    const { unmount } = renderEn('/alerts');
    expect(document.title).toBe('Alerts');
    fireEvent.click(screen.getByRole('link', { name: 'go to usage' }));
    expect(document.title).toBe('AI usage');
    unmount();

    renderEn('/portfolio?embed=ios');
    expect(document.title).toBe('Assets');
  });

  it('lets a page put a detail title (e.g. a chat conversation) into document.title', () => {
    const ChatTitle = () => {
      useShellDocumentTitle('Q3 outlook');
      return null;
    };
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ThemeProvider>
          <Shell>
            <ChatTitle />
          </Shell>
        </ThemeProvider>
      </MemoryRouter>
    );
    expect(document.title).toBe('Q3 outlook');
  });

  it('uses the shell route name as document.title on /calendar', () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    document.title = 'stale';
    render(
      <MemoryRouter initialEntries={['/calendar']}>
        <UiLanguageProvider>
          <ThemeProvider>
            <Shell>
              <div>calendar page</div>
            </Shell>
          </ThemeProvider>
        </UiLanguageProvider>
      </MemoryRouter>
    );
    expect(document.title).toBe('Calendar');
    expect(document.title).not.toContain(' - DSA');
  });

  it('titles the mobile "more" drawer "More"', () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    viewport.mobile = true;
    render(
      <MemoryRouter initialEntries={['/portfolio']}>
        <UiLanguageProvider>
          <ThemeProvider>
            <Shell>
              <div>page content</div>
            </Shell>
          </ThemeProvider>
        </UiLanguageProvider>
      </MemoryRouter>
    );
    const tabs = screen.getByRole('navigation', { name: 'Bottom tabs' });
    fireEvent.click(within(tabs).getByRole('button', { name: 'More' }));
    const drawer = screen.getByRole('dialog', { name: 'More' });
    expect(within(drawer).getByRole('heading', { level: 2 })).toHaveTextContent('More');
    expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument();
  });

  it('portals page actions into the mobile shell header only', () => {
    const page = <ShellHeaderActions><button type="button">new rule</button></ShellHeaderActions>;
    viewport.mobile = true;
    const { unmount } = render(
      <MemoryRouter initialEntries={['/alerts']}>
        <ThemeProvider>
          <Shell>{page}</Shell>
        </ThemeProvider>
      </MemoryRouter>
    );
    expect(within(screen.getByRole('banner')).getByRole('button', { name: 'new rule' })).toBeInTheDocument();
    expect(screen.getByTestId('shell-header-title')).toHaveClass('text-base');
    unmount();

    viewport.mobile = false;
    render(
      <MemoryRouter initialEntries={['/alerts']}>
        <ThemeProvider>
          <Shell>{page}</Shell>
        </ThemeProvider>
      </MemoryRouter>
    );
    expect(screen.queryByRole('button', { name: 'new rule' })).not.toBeInTheDocument();
  });

  it('shows a confirmation dialog before logout', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ThemeProvider>
          <Shell>
            <div>page content</div>
          </Shell>
        </ThemeProvider>
      </MemoryRouter>
    );

    // Logout now lives in the rail's "more" popover (W15).
    fireEvent.click(within(screen.getByTestId('sidebar-toolbar')).getByRole('button', { name: '更多' }));
    fireEvent.click(screen.getByRole('button', { name: '退出' }));

    expect(await screen.findByRole('heading', { name: '退出登录' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认退出' }));
    expect(mockLogout).toHaveBeenCalled();
  });
});
