import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LoginPage from '../LoginPage';

const { navigate, useSearchParamsMock, useAuthMock } = vi.hoisted(() => ({
  navigate: vi.fn(),
  useSearchParamsMock: vi.fn(),
  useAuthMock: vi.fn(),
}));

vi.mock('../../hooks', () => ({
  useAuth: () => useAuthMock(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigate,
    useSearchParams: () => useSearchParamsMock(),
  };
});

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.documentElement.className = 'light';
    useSearchParamsMock.mockReturnValue([new URLSearchParams('redirect=%2Fsettings')]);
  });

  it('blocks first-time setup when confirmation does not match', async () => {
    const login = vi.fn();
    useAuthMock.mockReturnValue({
      login,
      passwordSet: false,
      setupState: 'no_password',
    });

    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText('设置密码'), { target: { value: 'passwd6' } });
    fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'passwd7' } });
    fireEvent.click(screen.getByRole('button', { name: '设置并登录' }));

    expect(await screen.findByText('两次输入的密码不一致')).toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
    expect(screen.getByLabelText('设置密码')).toHaveAttribute('data-appearance', 'login');
    expect(screen.getByLabelText('确认密码')).toHaveAttribute('data-appearance', 'login');
  });

  it('navigates to redirect after a successful login', async () => {
    useAuthMock.mockReturnValue({
      login: vi.fn().mockResolvedValue({ success: true }),
      passwordSet: true,
      setupState: 'enabled',
    });

    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText('登录密码'), { target: { value: 'passwd6' } });
    fireEvent.click(screen.getByRole('button', { name: '登录' }));

    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/settings', { replace: true }));
    expect(screen.getByLabelText('登录密码')).toHaveAttribute('data-appearance', 'login');
  });

  it('does not override login theme tokens inline so light mode can take effect', () => {
    useAuthMock.mockReturnValue({
      login: vi.fn(),
      passwordSet: true,
      setupState: 'enabled',
    });

    const { container } = render(<LoginPage />);
    const pageRoot = container.firstElementChild as HTMLElement | null;

    expect(pageRoot).not.toBeNull();
    expect(pageRoot?.getAttribute('style') ?? '').not.toContain('--login-bg-main');
  });

  const failLogin = async (error: Record<string, unknown>) => {
    useAuthMock.mockReturnValue({
      login: vi.fn().mockResolvedValue({
        success: false,
        error: { title: 't', message: '后端原文', rawMessage: 'raw', category: 'http_error', ...error },
      }),
      passwordSet: true,
      setupState: 'enabled',
    });
    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText('登录密码'), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: '登录' }));
  };

  it('tells a wrong password apart from a connection failure', async () => {
    await failLogin({ status: 401 });
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('密码错误，请重新输入。'));
    expect(screen.getByRole('alert')).not.toHaveTextContent('无法连接');
  });

  it.each([
    [{ category: 'local_connection_failed' }],
    [{ status: 502 }],
    [{ category: 'upstream_timeout', status: 200 }],
  ])('reports %j as a connection problem, not a wrong password', async (error) => {
    await failLogin(error);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('无法连接服务'));
    expect(screen.getByRole('alert')).not.toHaveTextContent('密码错误');
  });

  it('keeps backend wording for other validation errors', async () => {
    await failLogin({ status: 400 });
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('后端原文'));
  });

  it('reserves the error slot before any error and disables submit while empty', () => {
    useAuthMock.mockReturnValue({ login: vi.fn(), passwordSet: true, setupState: 'enabled' });
    render(<LoginPage />);

    expect(screen.getByRole('alert')).toBeEmptyDOMElement();
    expect(screen.getByRole('alert')).toHaveClass('min-h-[2.5rem]');
    const submit = screen.getByRole('button', { name: '登录' });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText('登录密码'), { target: { value: 'x' } });
    expect(submit).toBeEnabled();
  });

  it('requires the confirmation and shows the password rule during first-time setup', () => {
    useAuthMock.mockReturnValue({ login: vi.fn(), passwordSet: false, setupState: 'no_password' });
    render(<LoginPage />);

    expect(screen.getByText('密码至少 6 位')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('设置密码'), { target: { value: 'passwd6' } });
    expect(screen.getByRole('button', { name: '设置并登录' })).toBeDisabled();
  });

  it('drops the marketing copy and renders a single card capped at 400px', () => {
    useAuthMock.mockReturnValue({ login: vi.fn(), passwordSet: true, setupState: 'enabled' });
    const { container } = render(<LoginPage />);

    expect(screen.getByTestId('login-card')).toHaveClass('max-w-[400px]');
    expect(container.textContent).not.toMatch(/V3\.X|Analysis Engine|DSA-V3-TLS/i);
    expect(container.querySelector('canvas')).toBeNull();
  });
});
