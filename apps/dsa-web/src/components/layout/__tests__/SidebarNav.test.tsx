import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { SidebarNav } from '../SidebarNav';

const mockLogout = vi.fn().mockResolvedValue(undefined);
const mockThemeToggle = vi.fn(({ collapsed }: { collapsed?: boolean }) => (
  <button type="button">{collapsed ? '切换主题(折叠)' : '切换主题'}</button>
));

const completionBadgeState = { value: true };

vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({
    authEnabled: true,
    logout: mockLogout,
  }),
}));

vi.mock('../../../stores/agentChatStore', () => ({
  useAgentChatStore: (selector: (state: { completionBadge: boolean }) => unknown) =>
    selector({ completionBadge: completionBadgeState.value }),
}));

vi.mock('../../theme/ThemeToggle', () => ({
  ThemeToggle: (props: { collapsed?: boolean }) => mockThemeToggle(props),
}));

describe('SidebarNav', () => {
  it('groups navigation into watch, research and system with the board first', () => {
    render(<MemoryRouter initialEntries={['/']}><SidebarNav /></MemoryRouter>);

    const hrefsIn = (name: string) =>
      within(screen.getByRole('group', { name })).getAllByRole('link').map((link) => link.getAttribute('href'));
    expect(hrefsIn('看盘')).toEqual(['/board', '/', '/portfolio', '/funds', '/calendar', '/alerts']);
    expect(hrefsIn('研究')).toEqual(['/chat', '/screening', '/decision-signals', '/backtest']);
    expect(hrefsIn('系统')).toEqual(['/data', '/usage', '/settings']);
    expect(screen.getAllByRole('link')[0]).toHaveAttribute('href', '/board');
  });

  it('shows a short label under the icon only in the collapsed rail', () => {
    const { unmount } = render(
      <MemoryRouter><SidebarNav variant="rail" collapsed onToggleCollapsed={vi.fn()} /></MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'AI 建议' })).toHaveTextContent('建议');
    expect(screen.getByRole('link', { name: 'AI 建议' })).not.toHaveTextContent('AI 建议');
    expect(screen.getByRole('button', { name: '展开侧边栏' })).toBeInTheDocument();
    unmount();

    render(<MemoryRouter><SidebarNav variant="rail" onToggleCollapsed={vi.fn()} /></MemoryRouter>);
    expect(screen.getByRole('link', { name: 'AI 建议' })).toHaveTextContent('AI 建议');
    expect(screen.getByRole('button', { name: '折叠侧边栏' })).toBeInTheDocument();
  });

  it('keeps the language control out of the active style until its menu opens', () => {
    render(<MemoryRouter><SidebarNav variant="rail" /></MemoryRouter>);

    const language = screen.getByRole('button', { name: '切换界面语言' });
    expect(language).not.toHaveClass('font-medium');
    fireEvent.click(language);
    expect(language).toHaveClass('font-medium');
    expect(screen.getByRole('menu', { name: '界面语言' })).toBeInTheDocument();
  });

  it('collects theme, language and logout into the rail toolbar', () => {
    render(<MemoryRouter><SidebarNav variant="rail" /></MemoryRouter>);

    const toolbar = within(screen.getByTestId('sidebar-toolbar'));
    expect(toolbar.getByRole('button', { name: /切换主题/ })).toBeInTheDocument();
    expect(toolbar.getByRole('button', { name: '切换界面语言' })).toBeInTheDocument();
    expect(toolbar.getByRole('button', { name: '退出' })).toBeInTheDocument();
  });

  it('shows the shared completion badge only when chat completion is pending', () => {
    completionBadgeState.value = true;

    const { rerender } = render(
      <MemoryRouter initialEntries={['/chat']}>
        <SidebarNav />
      </MemoryRouter>,
    );

    expect(screen.getByTestId('chat-completion-badge')).toBeInTheDocument();
    expect(screen.getByLabelText('问股有新消息')).toBeInTheDocument();

    completionBadgeState.value = false;
    rerender(
      <MemoryRouter initialEntries={['/chat']}>
        <SidebarNav />
      </MemoryRouter>,
    );

    expect(screen.queryByTestId('chat-completion-badge')).not.toBeInTheDocument();
  });

  it('renders the collapsed theme toggle variant when the sidebar is collapsed', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <SidebarNav collapsed />
      </MemoryRouter>,
    );

    expect(mockThemeToggle).toHaveBeenCalledWith(
      expect.objectContaining({ variant: 'nav', collapsed: true }),
    );
    expect(screen.getByRole('button', { name: '切换主题(折叠)' })).toBeInTheDocument();
  });

  it('renders the alerts navigation item and marks it active', () => {
    render(
      <MemoryRouter initialEntries={['/alerts']}>
        <SidebarNav />
      </MemoryRouter>,
    );

    const alertsLink = screen.getByRole('link', { name: '告警' });
    expect(alertsLink).toHaveAttribute('href', '/alerts');
    expect(alertsLink).toHaveClass('font-medium');
  });

  it('renders the AI signals navigation item and marks it active', () => {
    render(
      <MemoryRouter initialEntries={['/decision-signals']}>
        <SidebarNav />
      </MemoryRouter>,
    );

    const signalsLink = screen.getByRole('link', { name: 'AI 建议' });
    expect(signalsLink).toHaveAttribute('href', '/decision-signals');
    expect(signalsLink).toHaveClass('font-medium');
  });

  it('renders the data center navigation item and marks it active', () => {
    render(
      <MemoryRouter initialEntries={['/data']}>
        <SidebarNav />
      </MemoryRouter>,
    );

    const link = screen.getByRole('link', { name: '数据中心' });
    expect(link).toHaveAttribute('href', '/data');
    expect(link).toHaveClass('font-medium');
  });

  it('renders the calendar navigation item and marks it active', () => {
    render(<MemoryRouter initialEntries={['/calendar']}><SidebarNav /></MemoryRouter>);
    const link = screen.getByRole('link', { name: '事件日历' });
    expect(link).toHaveAttribute('href', '/calendar');
    expect(link).toHaveClass('font-medium');
  });

  it('keeps rail controls outside the scrollable navigation links', () => {
    render(<MemoryRouter><SidebarNav variant="rail" /></MemoryRouter>);

    const nav = screen.getByRole('navigation', { name: '主导航' });
    expect(nav).toHaveClass('min-h-0', 'overflow-y-auto');
    expect(nav).not.toContainElement(screen.getByRole('button', { name: '退出' }));
    expect(nav).not.toContainElement(screen.getByRole('button', { name: /切换主题/ }));
    expect(screen.getByRole('link', { name: '设置' })).toHaveClass('shrink-0');
  });

  it.each(['/settings?category=system', '/settings/'])(
    'explicitly confirms settings draft loss before logout at %s', async (path) => {
      mockLogout.mockClear();
      render(<MemoryRouter initialEntries={[path]}><SidebarNav /></MemoryRouter>);
      fireEvent.click(screen.getByRole('button', { name: '退出' }));
      expect(await screen.findByText(/退出会丢弃本页未保存的设置/)).toBeInTheDocument();
      expect(screen.getByText(/已发出的保存请求不会因退出而撤销/)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: '取消' }));
      expect(mockLogout).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole('button', { name: '退出' }));
      fireEvent.click(screen.getByRole('button', { name: '确认退出' }));
      expect(mockLogout).toHaveBeenCalledTimes(1);
    },
  );

  it('opens the logout confirmation and confirms logout', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <SidebarNav />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: '退出' }));

    expect(await screen.findByRole('heading', { name: '退出登录' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认退出' }));
    expect(mockLogout).toHaveBeenCalled();
  });
});
