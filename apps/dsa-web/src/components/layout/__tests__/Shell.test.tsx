import { fireEvent, render, screen } from '@testing-library/react';
import { Link, MemoryRouter } from 'react-router-dom';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider } from '../../theme/ThemeProvider';
import { Shell } from '../Shell';
import { ShellHeader } from '../ShellHeader';

const mockLogout = vi.fn().mockResolvedValue(undefined);

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

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: query === '(prefers-color-scheme: dark)',
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

const OPEN_NAV_LABEL = /Open navigation|打开导航菜单|開啟導覽選單/;

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
  });

  afterEach(() => {
    delete (window as { dsaDesktop?: unknown }).dsaDesktop;
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

  it('hides the sidebar and top bar with ?embed=ios and keeps them hidden after in-app navigation', () => {
    renderShellAt('/portfolio?embed=ios');

    expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: OPEN_NAV_LABEL })).not.toBeInTheDocument();

    // 換頁後 query 已不在，只有 sessionStorage 的旗標能維持內嵌。
    fireEvent.click(screen.getByRole('link', { name: 'go to alerts' }));

    expect(screen.getByRole('link', { name: 'go to alerts' })).toBeInTheDocument();
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: OPEN_NAV_LABEL })).not.toBeInTheDocument();
  });

  it('keeps the normal frame without the parameter or with another value', () => {
    const { unmount } = renderShellAt('/portfolio');
    expect(screen.getByRole('complementary')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: OPEN_NAV_LABEL })).toBeInTheDocument();
    unmount();

    renderShellAt('/portfolio?embed=web');
    expect(screen.getByRole('complementary')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: OPEN_NAV_LABEL })).toBeInTheDocument();
  });

  it('renders ShellHeader only outside embed mode', () => {
    const header = (entry: string) => (
      <MemoryRouter initialEntries={[entry]}>
        <ThemeProvider>
          <ShellHeader collapsed={false} onToggleSidebar={vi.fn()} onOpenMobileNav={vi.fn()} />
        </ThemeProvider>
      </MemoryRouter>
    );

    const { unmount } = render(header('/portfolio'));
    expect(screen.getByRole('banner')).toBeInTheDocument();
    unmount();

    render(header('/portfolio?embed=ios'));
    expect(screen.queryByRole('banner')).not.toBeInTheDocument();
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

    fireEvent.click(screen.getByRole('button', { name: '退出' }));

    expect(await screen.findByRole('heading', { name: '退出登录' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认退出' }));
    expect(mockLogout).toHaveBeenCalled();
  });
});
