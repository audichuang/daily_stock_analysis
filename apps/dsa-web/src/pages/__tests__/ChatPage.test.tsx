import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StrictMode, useState } from 'react';
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { createParsedApiError } from '../../api/error';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { historyApi } from '../../api/history';
import type { ActiveStockContext } from '../../api/agent';
import type { Message, ProgressStep } from '../../stores/agentChatStore';
import type { StockIndexItem } from '../../types/stockIndex';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import ChatPage from '../ChatPage';
import { extractStockCodeFromMessage, extractStockCodesFromMessage } from '../../utils/chatStockCode';

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const {
  mockGetSkills,
  mockGetStatus,
  mockDeleteChatSession,
  mockSendChat,
  mockGetSystemConfig,
  mockUpdateSystemConfig,
  mockGetWatchlist,
  mockAddToWatchlist,
  mockRemoveFromWatchlist,
  mockDownloadSession,
  mockFormatSessionAsMarkdown,
  mockStockIndex,
  mockStockIndexState,
  mockGetQuotes,
  mockGetSnapshot,
} = vi.hoisted(() => {
  const mockStockIndex = [
    { canonicalCode: '600519.SH', displayCode: '600519', nameZh: '贵州茅台', aliases: ['茅台'], market: 'CN', assetType: 'stock', active: true },
    { canonicalCode: '300750.SZ', displayCode: '300750', nameZh: '宁德时代', aliases: [], market: 'CN', assetType: 'stock', active: true },
    { canonicalCode: '000001.SZ', displayCode: '000001', nameZh: '平安银行', aliases: [], market: 'CN', assetType: 'stock', active: true },
    { canonicalCode: 'BABA', displayCode: 'BABA', nameZh: '阿里巴巴', aliases: [], market: 'US', assetType: 'stock', active: true },
    { canonicalCode: '09988.HK', displayCode: '09988', nameZh: '阿里巴巴', aliases: [], market: 'HK', assetType: 'stock', active: true },
    { canonicalCode: 'sh000001', displayCode: 'sh000001', nameZh: '上证指数', aliases: ['000001.SH'], market: 'CN', assetType: 'index', active: true },
    { canonicalCode: 'sh000016', displayCode: 'sh000016', nameZh: '上证50', aliases: ['000016.SH'], market: 'CN', assetType: 'index', active: true },
    { canonicalCode: 'sz399001', displayCode: 'sz399001', nameZh: '深证成指', aliases: ['399001.SZ'], market: 'CN', assetType: 'index', active: true },
    { canonicalCode: 'sh000300', displayCode: 'sh000300', nameZh: '沪深300', aliases: ['sz399300', '399300.SZ', '000300.SH', '000300.CSI'], market: 'CN', assetType: 'index', active: true },
    { canonicalCode: 'csi930955', displayCode: '930955.CSI', nameZh: '红利低波100', aliases: [], market: 'CN', assetType: 'index', active: true },
  ];
  return {
    mockGetSkills: vi.fn(),
    mockGetStatus: vi.fn(),
    mockDeleteChatSession: vi.fn(),
    mockSendChat: vi.fn(),
    mockGetSystemConfig: vi.fn(),
    mockUpdateSystemConfig: vi.fn(),
    mockGetWatchlist: vi.fn(),
    mockAddToWatchlist: vi.fn(),
    mockRemoveFromWatchlist: vi.fn(),
    mockDownloadSession: vi.fn(),
    mockFormatSessionAsMarkdown: vi.fn(),
    mockGetQuotes: vi.fn(),
    mockGetSnapshot: vi.fn(),
    mockStockIndex,
    // Mutable registry-load state for the async window shared by every backend.
    mockStockIndexState: {
      index: mockStockIndex,
      loading: false,
      error: null as Error | null,
      fallback: false,
      loaded: true,
    },
  };
});

const mockLoadSessions = vi.fn();
const mockLoadInitialSession = vi.fn();
const mockSwitchSession = vi.fn();
const mockStartStream = vi.fn();
const mockStopStream = vi.fn();
const mockRefreshSession = vi.fn();
const mockClearCompletionBadge = vi.fn();
const mockStartNewChat = vi.fn();

const mockStoreState = {
  messages: [] as Message[],
  selectedSkillIds: null as string[] | null,
  activeStockContext: null as ActiveStockContext | null,
  stateContract: 'unbound' as 'unbound' | 'authoritative' | 'legacy',
  loading: false,
  progressSteps: [] as ProgressStep[],
  sessionId: 'session-1',
  sessions: [
    {
      session_id: 'session-1',
      title: '请简要分析 600519',
      message_count: 2,
      created_at: '2026-03-15T09:00:00Z',
      last_active: '2026-03-15T09:05:00Z',
    },
  ],
  sessionsLoading: false,
  chatError: null as ReturnType<typeof createParsedApiError> | null,
  stopping: false,
  terminalStatus: null as 'cancelled' | 'timeout' | null,
  stopError: false,
  loadSessions: mockLoadSessions,
  loadInitialSession: mockLoadInitialSession,
  switchSession: mockSwitchSession,
  stopStream: mockStopStream,
  refreshSession: mockRefreshSession,
  startStream: mockStartStream,
  clearCompletionBadge: mockClearCompletionBadge,
};

vi.mock('../../api/agent', () => ({
  agentApi: {
    getSkills: mockGetSkills,
    getStatus: mockGetStatus,
    deleteChatSession: mockDeleteChatSession,
    sendChat: mockSendChat,
  },
}));

vi.mock('../../api/systemConfig', () => ({
  systemConfigApi: {
    getConfig: mockGetSystemConfig,
    update: mockUpdateSystemConfig,
    getWatchlist: mockGetWatchlist,
    addToWatchlist: mockAddToWatchlist,
    removeFromWatchlist: mockRemoveFromWatchlist,
  },
}));

vi.mock('../../utils/chatExport', () => ({
  downloadSession: mockDownloadSession,
  formatSessionAsMarkdown: mockFormatSessionAsMarkdown,
}));

vi.mock('../../api/history', () => ({
  historyApi: {
    getDetail: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock('../../api/stocks', () => ({
  stocksApi: { getQuotes: mockGetQuotes },
}));

vi.mock('../../api/portfolio', () => ({
  portfolioApi: { getSnapshot: mockGetSnapshot },
}));

vi.mock('../../hooks/useStockIndex', () => ({
  useStockIndex: () => ({
    index: mockStockIndexState.index,
    loading: mockStockIndexState.loading,
    error: mockStockIndexState.error,
    fallback: mockStockIndexState.fallback,
    loaded: mockStockIndexState.loaded,
  }),
}));

vi.mock('../../stores/agentChatStore', () => {
  type MockStore = typeof mockStoreState & {
    setSelectedSkillIds: (skillIds: string[]) => void;
  };
  const useAgentChatStore = (
    selector?: (state: MockStore) => unknown
  ) => {
    const [selectedSkillIds, setSelectedSkillIdsState] = useState(
      mockStoreState.selectedSkillIds,
    );
    const state: MockStore = {
      ...mockStoreState,
      selectedSkillIds,
      setSelectedSkillIds: (skillIds) => {
        setSelectedSkillIdsState(skillIds);
      },
    };
    return typeof selector === 'function' ? selector(state) : state;
  };

  useAgentChatStore.getState = () => ({
    startNewChat: mockStartNewChat,
  });

  return { useAgentChatStore };
});

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

  Object.defineProperty(window, 'requestAnimationFrame', {
    writable: true,
    value: (callback: FrameRequestCallback) => window.setTimeout(() => callback(0), 0),
  });

  Object.defineProperty(window, 'cancelAnimationFrame', {
    writable: true,
    value: (handle: number) => window.clearTimeout(handle),
  });

  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    writable: true,
    value: vi.fn(),
  });
});

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
  mockGetStatus.mockReset();
  mockStoreState.messages = [];
  mockStoreState.activeStockContext = null;
  mockStoreState.stateContract = 'unbound';
  mockStoreState.selectedSkillIds = null;
  mockStoreState.loading = false;
  mockStoreState.progressSteps = [];
  mockStoreState.chatError = null;
  mockStoreState.stopping = false;
  mockStoreState.terminalStatus = null;
  mockStoreState.stopError = false;
  mockStoreState.sessionsLoading = false;
  mockStoreState.sessionId = 'session-1';
  mockStoreState.sessions = [
    {
      session_id: 'session-1',
      title: '请简要分析 600519',
      message_count: 2,
      created_at: '2026-03-15T09:00:00Z',
      last_active: '2026-03-15T09:05:00Z',
    },
  ];
  mockGetSkills.mockResolvedValue({
    skills: [
      { id: 'bull_trend', name: '趋势分析', description: '测试技能' },
    ],
    default_skill_id: 'bull_trend',
  });
  mockGetStatus.mockResolvedValue({
    backend: 'litellm',
    available: true,
    experimental: false,
    errorCode: null,
    message: null,
  });
  mockStartStream.mockImplementation(async (_payload, meta) => {
    meta?.onAccepted?.({
      type: 'accepted',
      backend: 'litellm',
      request_id: 'request-test',
      session_id: 'session-1',
    });
  });
  mockDeleteChatSession.mockResolvedValue(undefined);
  mockSendChat.mockResolvedValue({ success: true });
  mockGetWatchlist.mockResolvedValue([]);
  mockGetQuotes.mockResolvedValue([]);
  mockGetSnapshot.mockResolvedValue({ accounts: [] });
  mockGetSystemConfig.mockResolvedValue({
    configVersion: 'cfg-v1',
    maskToken: 'mask-token',
    items: [
      {
        key: 'AGENT_CONTEXT_COMPRESSION_ENABLED',
        value: 'false',
        rawValueExists: true,
        isMasked: false,
      },
    ],
  });
  mockUpdateSystemConfig.mockResolvedValue({
    success: true,
    configVersion: 'cfg-v2',
    appliedCount: 1,
    skippedMaskedCount: 0,
    reloadTriggered: true,
    updatedKeys: ['AGENT_CONTEXT_COMPRESSION_ENABLED'],
    warnings: [],
  });
  mockDownloadSession.mockImplementation(() => {});
  mockFormatSessionAsMarkdown.mockReturnValue('# exported session');
  mockStockIndexState.index = mockStockIndex;
  mockStockIndexState.loading = false;
  mockStockIndexState.error = null;
  mockStockIndexState.fallback = false;
  mockStockIndexState.loaded = true;
});

async function confirmSendToNotify() {
  fireEvent.click(await screen.findByRole('button', { name: '更多操作' }));
  fireEvent.click(await screen.findByRole('menuitem', { name: '发送到已配置的通知机器人/邮箱' }));
  fireEvent.click(await screen.findByRole('button', { name: '推送' }));
}

describe('ChatPage', () => {
  it('lets the user stop an active Codex analysis from the existing Chat composer', async () => {
    mockGetStatus.mockResolvedValueOnce({
      backend: 'codex_app_server',
      available: true,
      experimental: true,
      errorCode: null,
      message: null,
    });
    mockStoreState.loading = true;

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: '停止分析' }));

    expect(mockStopStream).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: '发送' })).not.toBeInTheDocument();
  });

  it('keeps the existing waiting state for LiteLLM without offering a false stop', async () => {
    mockStoreState.loading = true;

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('button', { name: '处理中...' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '停止分析' })).not.toBeInTheDocument();
    expect(mockStopStream).not.toHaveBeenCalled();
  });

  it('labels the stop action in English when the UI language is English', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    mockGetStatus.mockResolvedValueOnce({
      backend: 'codex_app_server',
      available: true,
      experimental: true,
      errorCode: null,
      message: null,
    });
    mockStoreState.loading = true;

    render(
      <UiLanguageProvider>
        <MemoryRouter initialEntries={['/chat']}>
          <ChatPage />
        </MemoryRouter>
      </UiLanguageProvider>,
    );

    expect(await screen.findByRole('button', { name: 'Stop analysis' })).toBeInTheDocument();
  });

  it('shows a disabled stopping state until Codex confirms cleanup', async () => {
    mockGetStatus.mockResolvedValueOnce({
      backend: 'codex_app_server',
      available: true,
      experimental: true,
      errorCode: null,
      message: null,
    });
    mockStoreState.loading = true;
    mockStoreState.stopping = true;

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>,
    );

    const button = await screen.findByRole('button', { name: '正在停止…' });
    expect(button).toBeDisabled();
  });

  it('shows a plain-language terminal status after cancellation', async () => {
    mockStoreState.terminalStatus = 'cancelled';

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('status')).toHaveTextContent('本次分析已停止，后台任务也已结束。');
  });

  it('shows the current backend in the existing Chat header', async () => {
    mockGetStatus.mockResolvedValueOnce({
      backend: 'codex_app_server',
      available: true,
      experimental: true,
      errorCode: null,
      message: null,
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('Codex Agent · 实验')).toBeInTheDocument();
    expect(screen.getByText('Codex 当前可用范围')).toBeInTheDocument();
    expect(screen.getByText(/实时行情、新闻、市场热点/)).toBeInTheDocument();
    expect(screen.getByText('使用已保存的分析上下文和回测汇总，向 Codex 询问个股。')).toBeInTheDocument();
    expect(screen.getByText(/Codex 将基于已保存的分析上下文和回测汇总回答/)).toBeInTheDocument();
    expect(screen.queryByText(/AI 将调用实时数据工具/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '切换问股方式' })).toBeInTheDocument();
    expect(mockGetStatus).toHaveBeenCalledTimes(1);
    expect(screen.getByPlaceholderText(/例如/)).toBeEnabled();
  });

  it('finishes the compatibility check when React Strict Mode remounts effects', async () => {
    render(
      <StrictMode>
        <MemoryRouter initialEntries={['/chat']}>
          <ChatPage />
        </MemoryRouter>
      </StrictMode>,
    );

    expect(await screen.findByPlaceholderText(/例如/)).toBeEnabled();
    expect(screen.queryByText('正在确认问股运行环境')).not.toBeInTheDocument();
  });

  it('preserves the draft and disables sending while the compatibility check is pending', async () => {
    const status = createDeferred<{
      backend: string;
      available: boolean;
      experimental: boolean;
      errorCode: null;
      message: null;
    }>();
    mockGetStatus.mockReturnValueOnce(status.promise);

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('正在确认问股运行环境')).toBeInTheDocument();
    const input = screen.getByPlaceholderText(/例如/);
    expect(input).toBeDisabled();
    expect(screen.getByText(/不会调用模型或读取股票数据/)).toBeInTheDocument();
    status.resolve({
      backend: 'codex_app_server',
      available: true,
      experimental: true,
      errorCode: null,
      message: null,
    });

    await waitFor(() => expect(input).toBeEnabled());
    expect(mockGetStatus).toHaveBeenCalledTimes(1);
  });

  it('blocks sending only when backend status confirms unavailability and links to Agent settings', async () => {
    mockGetStatus.mockResolvedValueOnce({
      backend: 'codex_app_server',
      available: false,
      experimental: true,
      errorCode: 'command_not_found',
      message: 'Codex was not found',
    });
    const router = createMemoryRouter(
      [
        { path: '/chat', element: <ChatPage /> },
        { path: '/settings', element: <div>Agent settings destination</div> },
      ],
      { initialEntries: ['/chat'] },
    );
    render(<RouterProvider router={router} />);

    const input = await screen.findByPlaceholderText(/例如/);
    expect(input).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '前往 Agent 设置' }));
    expect(await screen.findByText('Agent settings destination')).toBeInTheDocument();
    // React Router v7 applies navigations asynchronously; waitFor keeps the
    // assertion in an act-wrapped retry loop instead of reading a stale router state.
    await waitFor(() => {
      expect(router.state.location.search).toBe('?category=agent');
    });
  });

  it('keeps sending disabled when backend status cannot be established', async () => {
    mockGetStatus.mockRejectedValueOnce(new Error('temporary status failure'));
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('暂时无法读取问股运行状态')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/例如/)).toBeDisabled();
    expect(mockGetStatus).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: '重新检查' }));
    await waitFor(() => expect(screen.getByPlaceholderText(/例如/)).toBeEnabled());
    expect(mockGetStatus).toHaveBeenCalledTimes(2);
  });

  it('keeps the draft until the server accepts the turn', async () => {
    const stream = createDeferred<void>();
    let onAccepted: ((event: {
      type: 'accepted';
      backend: 'litellm' | 'codex_app_server';
      request_id: string;
      session_id: string;
    }) => void) | undefined;
    mockStartStream.mockImplementationOnce(async (_payload, meta) => {
      onAccepted = meta?.onAccepted;
      await stream.promise;
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>,
    );

    const input = await screen.findByPlaceholderText(/例如/);
    fireEvent.change(input, { target: { value: '分析 AAPL' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(mockStartStream).toHaveBeenCalledTimes(1));

    expect(input).toHaveValue('分析 AAPL');
    expect(onAccepted).toBeTypeOf('function');
    act(() => {
      onAccepted?.({
        type: 'accepted',
        backend: 'codex_app_server',
        request_id: 'request-accepted',
        session_id: 'session-1',
      });
    });
    expect(input).toHaveValue('');

    stream.resolve();
    await act(async () => {
      await stream.promise;
    });
  });

  it.each(['litellm', 'codex_app_server'] as const)(
    'delegates code and name resolution to the server under %s, without waiting for a client registry',
    async (backend) => {
      mockGetStatus.mockResolvedValueOnce({ backend, available: true, experimental: false, errorCode: null, message: null });
      mockStockIndexState.index = [];
      mockStockIndexState.loading = true;
      render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);
      const input = await screen.findByPlaceholderText(/例如/);
      for (const message of ['分析上证指数', '分析 005930.KS', '换成 000001', '比较 sh000001 和 000001']) {
        fireEvent.change(input, { target: { value: message } });
        fireEvent.click(screen.getByRole('button', { name: '发送' }));
        await waitFor(() => expect(mockStartStream).toHaveBeenLastCalledWith(
          expect.objectContaining({ message, context: undefined }), expect.anything()));
      }
      expect(screen.getByLabelText('当前讨论对象')).toHaveTextContent('未确认');
    },
  );

  it.each([
    ['sh000001', 'index', '上证指数'],
    ['000001', 'stock', '平安银行'],
    ['005930.KS', 'stock', '三星电子'],
  ] as const)('shows the accepted server identity %s and uses its type for watchlist eligibility', async (code, type, name) => {
    mockStoreState.stateContract = 'authoritative';
    mockStoreState.activeStockContext = {
      stock_code: code, canonical_id: code, stock_name: name, asset_type: type,
    };
    mockStockIndexState.index = [];
    mockStockIndexState.loading = true;
    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);
    expect(await screen.findByLabelText('当前讨论对象')).toHaveTextContent(name);
    if (type === 'index') expect(screen.queryByText('加入自选')).not.toBeInTheDocument();
    else expect(await screen.findByText('加入自选')).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText(/例如/), { target: { value: '风险呢' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(mockStartStream).toHaveBeenLastCalledWith(
      expect.objectContaining({ message: '风险呢', context: undefined }), expect.anything()));
  });

  it('keeps input and explicit Skill draft on an acceptance conflict and provides manual refresh, not auto resend', async () => {
    mockStoreState.chatError = createParsedApiError({
      title: '会话已更新', message: '请刷新会话后重试', code: 'session_state_conflict', category: 'http_error',
    });
    mockStartStream.mockImplementationOnce(async () => undefined);
    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);
    const input = await screen.findByPlaceholderText(/例如/);
    fireEvent.change(input, { target: { value: '风险呢' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(mockStartStream).toHaveBeenCalledTimes(1));
    expect(input).toHaveValue('风险呢');
    fireEvent.click(screen.getByRole('button', { name: /刷新会话/ }));
    expect(mockRefreshSession).toHaveBeenCalledTimes(1);
    expect(input).toHaveValue('风险呢');
    expect(mockStartStream).toHaveBeenCalledTimes(1);
  });

  it('renders authoritative object and manual conflict refresh in English', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    mockStoreState.activeStockContext = { stock_code: '005930.KS', canonical_id: '005930.KS',
      stock_name: 'Samsung', asset_type: 'stock' };
    mockStoreState.chatError = createParsedApiError({ title: 'Session changed', message: 'Refresh',
      code: 'session_state_conflict', category: 'http_error' });
    render(<UiLanguageProvider><MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter></UiLanguageProvider>);
    expect(await screen.findByLabelText('Current discussion object')).toHaveTextContent('Discussing: Samsung · 005930.KS');
    expect(screen.getByRole('button', { name: 'Refresh session (keep your draft and retry)' })).toBeInTheDocument();
  });

  it('renders the new Codex status copy in English when the UI language is English', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    mockGetStatus.mockResolvedValueOnce({
      backend: 'codex_app_server',
      available: false,
      experimental: true,
      errorCode: 'command_not_found',
      message: 'Codex was not found',
    });

    render(
      <UiLanguageProvider>
        <MemoryRouter initialEntries={['/chat']}>
          <ChatPage />
        </MemoryRouter>
      </UiLanguageProvider>,
    );

    expect(await screen.findByText('Codex Agent · Experimental')).toBeInTheDocument();
    expect(screen.getByText('This device does not currently meet the basic Codex ask-stock requirements. Open Agent settings to check installation and Single Agent mode.')).toBeInTheDocument();
    expect(screen.queryByText(/当前不可用|前往 Agent 设置检查/)).not.toBeInTheDocument();
  });

  it('renders status-read failure copy in English', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    mockGetStatus.mockRejectedValueOnce(new Error('temporary status failure'));

    render(
      <UiLanguageProvider>
        <MemoryRouter initialEntries={['/chat']}>
          <ChatPage />
        </MemoryRouter>
      </UiLanguageProvider>,
    );

    expect(await screen.findByText('Ask-stock status is temporarily unavailable')).toBeInTheDocument();
    expect(screen.getByText('The ask-stock runtime cannot be confirmed, so sending is paused. You can check again manually; your question will be preserved.')).toBeInTheDocument();
    expect(screen.queryByText('暂时无法读取问股运行状态')).not.toBeInTheDocument();
  });

  it('renders the chat chrome in Traditional Chinese and keeps backend data untranslated', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh-TW');

    render(
      <UiLanguageProvider>
        <MemoryRouter initialEntries={['/chat']}>
          <ChatPage />
        </MemoryRouter>
      </UiLanguageProvider>,
    );

    expect(await screen.findByRole('checkbox', { name: '不指定' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '開啟新對話' })).toBeInTheDocument();
    // 會話標題與技能名稱是後端資料，不能被翻譯
    expect(screen.getByRole('button', { name: '切換到對話 请简要分析 600519' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: '趋势分析' })).toBeInTheDocument();
    expect(screen.getByText('2 則對話')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刪除對話 请简要分析 600519' })).toBeInTheDocument();
    expect(screen.getByText('開始問股')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('問個股，例如 2330.TW')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '傳送' })).toBeInTheDocument();
    expect(document.title).toBe('問股 - DSA');

    const bodyText = document.body.textContent ?? '';
    for (const simplified of ['历史对话', '开始问股', '条对话', '发送']) {
      expect(bodyText).not.toContain(simplified);
    }
  });

  it('renders the chat chrome in English', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');

    render(
      <UiLanguageProvider>
        <MemoryRouter initialEntries={['/chat']}>
          <ChatPage />
        </MemoryRouter>
      </UiLanguageProvider>,
    );

    expect(await screen.findByRole('checkbox', { name: 'Not specified' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start a new chat' })).toBeInTheDocument();
    expect(screen.getByText('2 messages')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/^Ask about a stock/)).toBeInTheDocument();
  });

  it('no longer offers context compression in the chat page', async () => {
    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    await screen.findByTestId('chat-composer');
    expect(screen.queryByRole('checkbox', { name: /上下文压缩/ })).not.toBeInTheDocument();
    expect(mockGetSystemConfig).not.toHaveBeenCalled();
  });

  it('renders a fixed workspace shell with independent session and message viewports', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByTestId('chat-workspace')).toBeInTheDocument();
    expect(screen.getByTestId('chat-session-list-scroll')).toBeInTheDocument();
    expect(screen.getByTestId('chat-message-scroll')).toBeInTheDocument();
    expect(mockLoadInitialSession).toHaveBeenCalled();
    expect(mockClearCompletionBadge).toHaveBeenCalled();
  });

  it('does not switch when clicking the current session card', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const sessionCard = await screen.findByRole('button', {
      name: /切换到对话 请简要分析 600519/,
    });

    fireEvent.click(sessionCard);
    expect(mockSwitchSession).not.toHaveBeenCalled();
    expect(sessionCard).toHaveAttribute('aria-current', 'page');
  });

  it('renders a separate delete button for each session and opens confirmation without switching', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const deleteButton = await screen.findByRole('button', {
      name: /删除对话 请简要分析 600519/,
    });

    fireEvent.click(deleteButton);

    expect(mockSwitchSession).not.toHaveBeenCalled();
    expect(await screen.findByText('删除后，该对话将不可恢复，确认删除吗？')).toBeInTheDocument();
  });

  it('hides header actions when there are no messages', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByRole('heading', { name: '问股' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '导出会话' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '发送到已配置的通知机器人/邮箱' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '历史对话' })).toBeInTheDocument();
  });

  it('exports the current session from the header action', async () => {
    mockStoreState.messages = [
      { id: 'user-1', role: 'user', content: '请分析 600519' },
      { id: 'assistant-1', role: 'assistant', content: '趋势偏强', skillName: '趋势分析' },
    ];

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: '更多操作' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '导出会话为 Markdown 文件' }));

    // 本 fork 的导出带 locale 第二参（getIntlLocale(language)，供繁体/英文本地化导出）
    expect(mockDownloadSession).toHaveBeenCalledWith(mockStoreState.messages, expect.anything());
    expect(mockFormatSessionAsMarkdown).not.toHaveBeenCalled();
  });

  it('renders assistant skill labels with shared badge semantics', async () => {
    mockStoreState.messages = [
      { id: 'assistant-1', role: 'assistant', content: '趋势偏强', skillName: '趋势分析' },
    ];

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const skillBadge = await screen.findByLabelText('技能 趋势分析');
    expect(skillBadge).toBeInTheDocument();
    expect(skillBadge).toHaveTextContent('趋势分析');
  });

  it('renders assistant multi-skill labels with shared badge semantics', async () => {
    mockStoreState.messages = [
      {
        id: 'assistant-1',
        role: 'assistant',
        content: '趋势偏强',
        skills: ['bull_trend', 'ma_golden_cross'],
        skillNames: ['趋势分析', '均线金叉'],
      },
    ];

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const skillBadge = await screen.findByLabelText('技能 趋势分析、均线金叉');
    expect(skillBadge).toBeInTheDocument();
    expect(skillBadge).toHaveTextContent('趋势分析、均线金叉');
  });

  it('renders failed stage_done progress as a non-success state', async () => {
    mockStoreState.loading = true;
    mockStoreState.progressSteps = [
      { type: 'stage_done', stage: 'risk', status: 'failed' },
    ];
    mockStoreState.messages = [
      {
        id: 'assistant-1',
        role: 'assistant',
        content: 'Partial answer',
        thinkingSteps: [
          { type: 'stage_done', stage: 'risk', status: 'failed' },
        ],
      },
    ];

    const { container } = render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findAllByText('risk 未完成')).toHaveLength(1);

    const thinkingToggle = container.querySelector('button[class*="mb-2"][class*="w-full"]') as HTMLButtonElement;
    fireEvent.click(thinkingToggle);

    const failedStage = screen.getAllByText('risk 未完成').find((node) =>
      node.closest('.chat-progress-item'),
    );
    expect(failedStage).toBeDefined();
    expect(failedStage?.closest('.chat-progress-item')).toHaveClass('chat-progress-item-danger');
    expect(failedStage?.closest('.chat-progress-item')).not.toHaveClass('chat-progress-item-success');
  });

  it('renders pipeline budget skip progress without timeout severity', async () => {
    mockStoreState.loading = true;
    mockStoreState.progressSteps = [
      { type: 'pipeline_budget_skipped', stage: 'decision' },
    ];
    mockStoreState.messages = [
      {
        id: 'assistant-1',
        role: 'assistant',
        content: 'Partial answer',
        thinkingSteps: [
          { type: 'pipeline_budget_skipped', stage: 'decision' },
        ],
      },
    ];

    const { container } = render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findAllByText('decision 已跳过：预算不足')).toHaveLength(1);
    expect(screen.queryByText('decision 已超时')).not.toBeInTheDocument();

    const thinkingToggle = container.querySelector('button[class*="mb-2"][class*="w-full"]') as HTMLButtonElement;
    fireEvent.click(thinkingToggle);

    const budgetSkipped = screen.getAllByText('decision 已跳过：预算不足').find((node) =>
      node.closest('.chat-progress-item'),
    );
    expect(budgetSkipped).toBeDefined();
    expect(budgetSkipped?.closest('.chat-progress-item')).toHaveClass('chat-progress-item-muted');
    expect(budgetSkipped?.closest('.chat-progress-item')).not.toHaveClass('chat-progress-item-danger');
  });

  it('selects the default skill after loading skills', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByRole('checkbox', { name: '趋势分析' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: '不指定' })).not.toBeChecked();
  });

  it('keeps the restored session skills when the Skill catalog finishes loading', async () => {
    mockStoreState.selectedSkillIds = ['ma_golden_cross'];
    mockGetSkills.mockResolvedValue({
      skills: [
        { id: 'bull_trend', name: '趋势分析', description: '默认趋势' },
        { id: 'ma_golden_cross', name: '均线金叉', description: '均线交叉' },
      ],
      default_skill_id: 'bull_trend',
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByRole('checkbox', { name: '均线金叉' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: '趋势分析' })).not.toBeChecked();

    fireEvent.change(screen.getByPlaceholderText(/例如/), {
      target: { value: '继续分析' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({ skills: ['ma_golden_cross'] }),
        expect.any(Object),
      );
    });
  });

  it('omits skills for an untouched new session so the server resolves its default', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByRole('checkbox', { name: '趋势分析' })).toBeChecked();
    fireEvent.change(screen.getByPlaceholderText(/例如/), {
      target: { value: '分析 AAPL' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(mockStartStream).toHaveBeenCalled());
    expect(mockStartStream.mock.calls.at(-1)?.[0]).not.toHaveProperty('skills');
  });

  it('omits skills when continuing a legacy session without persisted Skill state', async () => {
    mockStoreState.messages = [
      { id: 'legacy-user', role: 'user', content: '分析 AAPL' },
      { id: 'legacy-assistant', role: 'assistant', content: '历史分析结果' },
    ];
    mockStoreState.selectedSkillIds = null;

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByRole('checkbox', { name: '趋势分析' })).toBeChecked();
    fireEvent.change(screen.getByPlaceholderText(/例如/), {
      target: { value: '继续分析' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(mockStartStream).toHaveBeenCalled());
    expect(mockStartStream.mock.calls.at(-1)?.[0]).toEqual(
      expect.objectContaining({
        message: '继续分析',
        session_id: 'session-1',
      }),
    );
    expect(mockStartStream.mock.calls.at(-1)?.[0]).not.toHaveProperty('skills');
  });

  it('sends multiple selected skills in order', async () => {
    mockGetSkills.mockResolvedValue({
      skills: [
        { id: 'bull_trend', name: '趋势分析', description: '默认趋势' },
        { id: 'ma_golden_cross', name: '均线金叉', description: '均线交叉' },
      ],
      default_skill_id: 'bull_trend',
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('checkbox', { name: '均线金叉' }));
    fireEvent.change(screen.getByPlaceholderText(/例如/), {
      target: { value: '分析 600519' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '分析 600519',
          skills: ['bull_trend', 'ma_golden_cross'],
        }),
        expect.objectContaining({
          skillNames: ['趋势分析', '均线金叉'],
          skillName: '趋势分析、均线金叉',
        }),
      );
    });
  });

  it('fills an empty-state stock shortcut with its context and does not send until the user does', async () => {
    mockGetSnapshot.mockResolvedValue({
      accounts: [{ positions: [{ symbol: '2330.TW', name: '台积电' }] }],
    });
    mockGetWatchlist.mockResolvedValue(['AAPL']);

    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole('button', { name: '台积电' }));

    const input = screen.getByPlaceholderText(/例如/);
    expect(input).toHaveValue('分析 台积电 2330.TW');
    expect(mockStartStream).not.toHaveBeenCalled();
    expect(await screen.findByRole('button', { name: 'AAPL' })).toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole('button', { name: '发送' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '分析 台积电 2330.TW',
          context: { stock_code: '2330.TW', stock_name: '台积电' },
        }),
        expect.any(Object),
      );
    });
  });

  it('fills a market prompt without a stock context and without sending', async () => {
    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole('button', { name: '今天台股大盘怎么看' }));

    expect(screen.getByPlaceholderText(/例如/)).toHaveValue('今天台股大盘怎么看');
    expect(mockStartStream).not.toHaveBeenCalled();
  });

  it('shows no empty-state holdings group when the portfolio cannot be read', async () => {
    mockGetSnapshot.mockRejectedValue(new Error('portfolio down'));

    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    await screen.findByTestId('chat-empty-shortcuts');
    expect(screen.queryByText('持股')).not.toBeInTheDocument();
    expect(screen.getByText('大盘')).toBeInTheDocument();
  });

  it('suggests stocks from the index while typing and binds the picked one', async () => {
    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    const input = await screen.findByPlaceholderText(/例如/);
    await waitFor(() => expect(input).toBeEnabled());
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: '宁德' } });

    const option = await screen.findByRole('option', { name: /宁德时代/ });
    fireEvent.mouseDown(option.querySelector('button') as HTMLButtonElement);

    expect(input).toHaveValue('宁德时代 300750.SZ ');
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({ context: { stock_code: '300750.SZ', stock_name: '宁德时代' } }),
        expect.any(Object),
      );
    });
  });

  it('treats Enter as a newline on touch devices and as send elsewhere', async () => {
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query === '(pointer: coarse)',
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    })) as unknown as typeof window.matchMedia;
    try {
      render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);
      const input = await screen.findByPlaceholderText(/例如/);
      await waitFor(() => expect(input).toBeEnabled());
      fireEvent.change(input, { target: { value: '分析 2330.TW' } });
      fireEvent.keyDown(input, { key: 'Enter' });
      expect(mockStartStream).not.toHaveBeenCalled();
    } finally {
      window.matchMedia = originalMatchMedia;
    }
  });

  it('does not send when Enter only confirms an input method composition', async () => {
    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);
    const input = await screen.findByPlaceholderText(/例如/);
    await waitFor(() => expect(input).toBeEnabled());
    fireEvent.change(input, { target: { value: '台积电' } });
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
    expect(mockStartStream).not.toHaveBeenCalled();
  });

  it('shows the time, a day separator and the follow-ups of the latest answer', async () => {
    const now = new Date();
    const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    mockStoreState.messages = [
      { id: 'u-1', role: 'user', content: '昨天的问题', createdAt: yesterday.toISOString() },
      { id: 'u-2', role: 'user', content: '今天的问题', createdAt: now.toISOString() },
      { id: 'a-2', role: 'assistant', content: '今天的回答', createdAt: now.toISOString(),
        structured: { follow_ups: ['压力怎么看'] } },
    ];

    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    expect(await screen.findAllByTestId('chat-day-separator')).toHaveLength(2);
    fireEvent.click(within(screen.getByTestId('chat-follow-ups')).getByRole('button', { name: '压力怎么看' }));
    expect(screen.getByPlaceholderText(/例如/)).toHaveValue('压力怎么看');
    expect(mockStartStream).not.toHaveBeenCalled();
  });

  it('flags an answer from an earlier day and re-asks the last question on request', async () => {
    const earlier = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString();
    mockStoreState.messages = [
      { id: 'u-1', role: 'user', content: '分析 2330.TW', createdAt: earlier },
      { id: 'a-1', role: 'assistant', content: '当时偏多', createdAt: earlier },
    ];

    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    const rerun = await screen.findByRole('button', { name: '以最新资料重新分析' });
    await waitFor(() => expect(rerun).toBeEnabled());
    fireEvent.click(rerun);
    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({ message: '分析 2330.TW' }),
        expect.any(Object),
      );
    });
  });

  it('does not flag an answer from today as stale', async () => {
    const now = new Date().toISOString();
    mockStoreState.messages = [
      { id: 'u-1', role: 'user', content: '分析 2330.TW', createdAt: now },
      { id: 'a-1', role: 'assistant', content: '偏多', createdAt: now },
    ];

    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    await screen.findByText('偏多');
    expect(screen.queryByRole('button', { name: '以最新资料重新分析' })).not.toBeInTheDocument();
  });

  it('renders the stock summary only above the latest answer from quote and structured values', async () => {
    mockStoreState.activeStockContext = { stock_code: '2330.TW', canonical_id: '2330.TW', stock_name: '台积电', asset_type: 'stock' };
    mockStoreState.messages = [
      { id: 'a-1', role: 'assistant', content: '较早的回答' },
      { id: 'a-2', role: 'assistant', content: '最新的回答',
        structured: { conclusion: '逢回分批', resistance: 1100, support: 980, invalidation: '跌破季线', follow_ups: [] } },
    ];
    mockGetQuotes.mockResolvedValue([{ stockCode: '2330.TW', quote: { stockCode: '2330.TW', currentPrice: 1050, changePercent: 1.5 } }]);

    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    const cards = await screen.findAllByTestId('chat-stock-summary');
    expect(cards).toHaveLength(1);
    expect(cards[0]).toHaveTextContent('逢回分批');
    expect(cards[0]).toHaveTextContent('跌破季线');
    expect(cards[0]).toHaveTextContent('1,100');
    expect(cards[0]).toHaveTextContent('980');
    await waitFor(() => expect(cards[0]).toHaveTextContent('1,050'));
    expect(mockGetQuotes).toHaveBeenCalledWith(['2330.TW']);
  });

  it('does not show the previous stock quote after switching stock', async () => {
    mockStoreState.activeStockContext = { stock_code: '2330.TW', canonical_id: '2330.TW', stock_name: '台积电', asset_type: 'stock' } as ActiveStockContext;
    mockStoreState.messages = [{ id: 'a-1', role: 'assistant', content: '回答' }];
    mockGetQuotes.mockResolvedValueOnce([{ stockCode: '2330.TW', quote: { stockCode: '2330.TW', currentPrice: 1050, changePercent: 1 } }]);

    const view = render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId('chat-stock-summary')).toHaveTextContent('1,050'));

    mockStoreState.activeStockContext = { stock_code: 'AAPL', canonical_id: 'AAPL', stock_name: 'Apple', asset_type: 'stock' } as ActiveStockContext;
    mockGetQuotes.mockReturnValueOnce(new Promise(() => undefined));
    view.rerender(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    await waitFor(() => expect(screen.getByTestId('chat-stock-summary')).toHaveTextContent('AAPL'));
    expect(screen.getByTestId('chat-stock-summary')).not.toHaveTextContent('1,050');
  });

  it('does not attach the previous stock answer to a newly active stock', async () => {
    mockStoreState.activeStockContext = { stock_code: 'AAPL', canonical_id: 'AAPL', stock_name: 'Apple', asset_type: 'stock' } as ActiveStockContext;
    mockStoreState.messages = [
      { id: 'a-1', role: 'assistant', content: '台积电的回答', stockCode: '2330.TW',
        structured: { conclusion: '逢回分批', resistance: 1100, support: 980, invalidation: '跌破季线', follow_ups: [] } },
    ];
    mockGetQuotes.mockResolvedValue([]);

    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    await screen.findByText('台积电的回答');
    expect(screen.queryByTestId('chat-stock-summary')).not.toBeInTheDocument();
  });

  it('keeps the summary card when the answer is about the active stock', async () => {
    mockStoreState.activeStockContext = { stock_code: 'AAPL', canonical_id: 'AAPL', stock_name: 'Apple', asset_type: 'stock' } as ActiveStockContext;
    mockStoreState.messages = [{ id: 'a-1', role: 'assistant', content: '苹果的回答', stockCode: 'AAPL' }];
    mockGetQuotes.mockResolvedValue([]);

    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    expect(await screen.findByTestId('chat-stock-summary')).toBeInTheDocument();
  });

  it('keeps the summary card and shows no-value marks when the quote fails', async () => {
    mockStoreState.activeStockContext = { stock_code: '2330.TW', canonical_id: '2330.TW', stock_name: '台积电', asset_type: 'stock' };
    mockStoreState.messages = [{ id: 'a-1', role: 'assistant', content: '回答' }];
    mockGetQuotes.mockRejectedValue(new Error('quote down'));

    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    expect(await screen.findByTestId('chat-stock-summary')).toHaveTextContent('—');
    expect(screen.getByTestId('chat-stock-summary')).not.toHaveTextContent('0.00');
  });

  it('groups and filters the session list and shows the stock pill', async () => {
    mockStoreState.sessions = [
      { session_id: 'session-1', title: '今天的对话', message_count: 2, created_at: '',
        last_active: new Date().toISOString(), stock_code: '2330.TW', stock_name: '台积电' },
      { session_id: 'session-2', title: '很久以前', message_count: 2, created_at: '',
        last_active: new Date(Date.now() - 60 * 24 * 60 * 60 * 1000).toISOString() },
    ] as typeof mockStoreState.sessions;

    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    expect(await screen.findByText('台积电 · 2330.TW')).toBeInTheDocument();
    expect(screen.getByText('今天')).toBeInTheDocument();
    expect(screen.getByText('更早')).toBeInTheDocument();

    fireEvent.change(screen.getByRole('searchbox', { name: '搜索对话或股票' }), { target: { value: '2330' } });
    expect(screen.queryByText('很久以前')).not.toBeInTheDocument();
    expect(screen.getByText('今天的对话')).toBeInTheDocument();
  });

  it('collapses the desktop history list and brings it back', async () => {
    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole('button', { name: '收起历史对话' }));
    expect(screen.queryByTestId('chat-session-list-scroll')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '展开历史对话' }));
    expect(screen.getByTestId('chat-session-list-scroll')).toBeInTheDocument();
  });

  it('does not show the constant default-model badge', async () => {
    mockStoreState.messages = [{ id: 'a-1', role: 'assistant', content: '回答', backend: 'litellm' }];

    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    await screen.findByText('回答');
    expect(screen.queryByText('默认模型')).not.toBeInTheDocument();
  });

  it('groups strategies and uses the Traditional Chinese name only in zh-TW', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh-TW');
    mockGetSkills.mockResolvedValue({
      skills: [{ id: 'chan_theory', name: '缠论', description: '结构', display_name_zh_tw: '纏論', group: 'theory', group_name_zh_tw: '理論框架' }],
      default_skill_id: '',
    });

    render(
      <UiLanguageProvider>
        <MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>
      </UiLanguageProvider>,
    );

    expect(await screen.findByRole('checkbox', { name: '纏論' })).toBeInTheDocument();
    expect(screen.getByText('理論框架')).toBeInTheDocument();
  });

  it('collapses the mobile skill picker by default and keeps selected skills when sending', async () => {
    mockGetSkills.mockResolvedValue({
      skills: [
        { id: 'bull_trend', name: '趋势分析', description: '默认趋势' },
        { id: 'ma_golden_cross', name: '均线金叉', description: '均线交叉' },
      ],
      default_skill_id: 'bull_trend',
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const mobileToggle = await screen.findByRole('button', { name: '展开策略选择' });
    const skillPanel = screen.getByTestId('chat-skill-picker-panel');
    expect(mobileToggle).toHaveAttribute('aria-expanded', 'false');
    expect(skillPanel).toHaveClass('hidden');

    fireEvent.click(mobileToggle);

    expect(screen.getByRole('button', { name: '收起策略选择' })).toHaveAttribute('aria-expanded', 'true');
    expect(skillPanel).not.toHaveClass('hidden');
    expect(skillPanel).toHaveClass('flex');

    fireEvent.click(screen.getByRole('checkbox', { name: '均线金叉' }));
    fireEvent.change(screen.getByPlaceholderText(/例如/), {
      target: { value: '分析 600519' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '分析 600519',
          skills: ['bull_trend', 'ma_golden_cross'],
        }),
        expect.objectContaining({
          skillName: '趋势分析、均线金叉',
        }),
      );
    });

    expect(screen.getByRole('button', { name: '展开策略选择' })).toHaveAttribute('aria-expanded', 'false');
    expect(skillPanel).toHaveClass('hidden');
  });

  it('sends an explicit empty skills list when all concrete skills are cleared', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('checkbox', { name: '趋势分析' }));
    expect(screen.getByRole('checkbox', { name: '不指定' })).toBeChecked();

    fireEvent.change(screen.getByPlaceholderText(/例如/), {
      target: { value: '分析 AAPL' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalled();
    });
    const lastCall = mockStartStream.mock.calls[mockStartStream.mock.calls.length - 1];
    expect(lastCall[0]).toEqual(expect.objectContaining({
      message: '分析 AAPL',
      skills: [],
    }));
    expect(lastCall[1]).toEqual(expect.objectContaining({
      skillNames: ['通用'],
      skillName: '通用',
    }));
  });

  it('caps concrete skill selection at three and re-enables choices after unselecting', async () => {
    mockGetSkills.mockResolvedValue({
      skills: [
        { id: 'bull_trend', name: '趋势分析', description: '默认趋势' },
        { id: 'ma_golden_cross', name: '均线金叉', description: '均线交叉' },
        { id: 'chan_theory', name: '缠论', description: '结构分析' },
        { id: 'wave_theory', name: '波浪理论', description: '波浪分析' },
      ],
      default_skill_id: 'bull_trend',
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('checkbox', { name: '均线金叉' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '缠论' }));

    const wave = screen.getByRole('checkbox', { name: '波浪理论' });
    expect(wave).toBeDisabled();

    fireEvent.click(screen.getByRole('checkbox', { name: '均线金叉' }));
    expect(wave).not.toBeDisabled();
  });

  it('does not send a client-selected identity for a name-only question', async () => {
    mockGetStatus.mockResolvedValueOnce({ backend: 'codex_app_server', available: true, experimental: true, errorCode: null, message: null });
    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);
    const input = await screen.findByPlaceholderText(/例如/);
    fireEvent.change(input, { target: { value: '分析茅台' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(mockStartStream).toHaveBeenCalledWith(
      expect.objectContaining({ message: '分析茅台', context: undefined }), expect.anything()));
  });

  it('does not guess when one stock name maps to multiple markets', async () => {
    mockGetStatus.mockResolvedValueOnce({
      backend: 'codex_app_server',
      available: true,
      experimental: true,
      errorCode: null,
      message: null,
    });
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    fireEvent.change(await screen.findByPlaceholderText(/例如/), {
      target: { value: '分析阿里巴巴' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({ context: undefined }),
        expect.any(Object),
      );
    });
  });

  it('keeps assistant message actions directly activatable in the DOM', async () => {
    mockStoreState.messages = [
      { id: 'assistant-1', role: 'assistant', content: '趋势偏强', skillName: '趋势分析' },
    ];

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const exportButton = await screen.findByRole('button', { name: '导出此条消息为 Markdown' });
    const actionGroup = exportButton.parentElement;

    expect(actionGroup).toHaveClass('chat-message-actions');
    expect(actionGroup?.className).not.toMatch(/pointer-events-none|opacity-0/);
  });

  it('sends exported markdown to notification channel and shows success feedback', async () => {
    mockStoreState.messages = [
      { id: 'user-1', role: 'user', content: '请分析 600519' },
      { id: 'assistant-1', role: 'assistant', content: '趋势偏强', skillName: '趋势分析' },
    ];
    mockGetStatus.mockResolvedValueOnce({
      backend: 'codex_app_server',
      available: false,
      experimental: true,
      errorCode: 'command_not_found',
      message: 'Codex was not found',
    });
    mockFormatSessionAsMarkdown.mockReturnValue('# exported markdown');

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    await confirmSendToNotify();

    await waitFor(() => {
      expect(mockFormatSessionAsMarkdown).toHaveBeenCalledWith(mockStoreState.messages, expect.anything());
      expect(mockSendChat).toHaveBeenCalledWith('# exported markdown');
    });

    expect(await screen.findByText('已发送到通知渠道')).toBeInTheDocument();
  });

  it('shows parsed error feedback when notification delivery fails', async () => {
    mockStoreState.messages = [
      { id: 'user-1', role: 'user', content: '请分析 AAPL' },
      { id: 'assistant-1', role: 'assistant', content: '短线震荡', skillName: '趋势分析' },
    ];
    mockSendChat.mockRejectedValue(
      createParsedApiError({
        title: '发送失败',
        message: '通知渠道不可用',
        category: 'unknown',
      }),
    );

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    await confirmSendToNotify();

    expect(await screen.findByText('通知渠道不可用')).toBeInTheDocument();
  });

  it('prevents duplicate notification sends while the request is in flight', async () => {
    mockStoreState.messages = [
      { id: 'user-1', role: 'user', content: '请分析 TSLA' },
      { id: 'assistant-1', role: 'assistant', content: '波动较大', skillName: '趋势分析' },
    ];
    const deferred = createDeferred<{ success: boolean }>();
    mockSendChat.mockImplementation(() => deferred.promise);

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    await confirmSendToNotify();
    await waitFor(() => expect(mockSendChat).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    expect(screen.getByRole('menuitem', { name: '发送到已配置的通知机器人/邮箱' })).toBeDisabled();

    await act(async () => {
      deferred.resolve({ success: true });
    });
    expect(screen.getByRole('menuitem', { name: '发送到已配置的通知机器人/邮箱' })).not.toBeDisabled();
  });

  it('does not push to the notification channel until the user confirms', async () => {
    mockStoreState.messages = [{ id: 'assistant-1', role: 'assistant', content: '回答' }];

    render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole('button', { name: '更多操作' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '发送到已配置的通知机器人/邮箱' }));
    expect(mockSendChat).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole('button', { name: '取消' }));
    expect(mockSendChat).not.toHaveBeenCalled();
  });

  it('allows sending with base follow-up context before report hydration completes', async () => {
    const deferred = createDeferred<Awaited<ReturnType<typeof historyApi.getDetail>>>();

    vi.mocked(historyApi.getDetail).mockImplementation(() => deferred.promise);

    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0&recordId=1']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();

    const sendButton = screen.getByRole('button', { name: /发送|处理中\.\.\./ });
    expect(sendButton).not.toBeDisabled();
    expect(screen.getByText('正在加载历史分析上下文；现在可直接发送追问。')).toBeInTheDocument();

    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '请深入分析 贵州茅台(600519)',
          context: {
            stock_code: '600519',
            stock_name: '贵州茅台',
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });

    deferred.resolve({
      meta: {
        id: 1,
        queryId: 'q-1',
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'detailed',
        createdAt: '2026-03-18T08:00:00Z',
        currentPrice: 1523.6,
        changePct: 1.8,
      },
      summary: {
        analysisSummary: '趋势延续',
        operationAdvice: '继续观察',
        trendPrediction: '高位震荡',
        sentimentScore: 78,
      },
      strategy: {
        stopLoss: '1450',
      },
    });

    await waitFor(() => {
      expect(screen.queryByText('正在加载历史分析上下文；现在可直接发送追问。')).not.toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText(/例如/), {
      target: { value: '继续分析成交量' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '继续分析成交量',
          context: undefined,
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });

    fireEvent.change(screen.getByPlaceholderText(/例如/), {
      target: { value: '如果不考虑 TTM 呢' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '如果不考虑 TTM 呢',
          context: undefined,
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('uses hydrated report context when it finishes before sending', async () => {
    vi.mocked(historyApi.getDetail).mockResolvedValue({
      meta: {
        id: 1,
        queryId: 'q-1',
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'detailed',
        createdAt: '2026-03-18T08:00:00Z',
        currentPrice: 1523.6,
        changePct: 1.8,
      },
      summary: {
        analysisSummary: '趋势延续',
        operationAdvice: '继续观察',
        trendPrediction: '高位震荡',
        sentimentScore: 78,
      },
      strategy: {
        stopLoss: '1450',
      },
    });

    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0&recordId=1']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.queryByText('正在加载历史分析上下文；现在可直接发送追问。')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '请深入分析 贵州茅台(600519)',
          context: expect.objectContaining({
            stock_code: '600519',
            stock_name: '贵州茅台',
            previous_price: 1523.6,
            previous_change_pct: 1.8,
            previous_strategy: expect.objectContaining({
              stopLoss: '1450',
            }),
          }),
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('falls back to base stock context when recordId is missing', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=AAPL']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 AAPL')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '请深入分析 AAPL',
          context: {
            stock_code: 'AAPL',
            stock_name: null,
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
    expect(historyApi.getDetail).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText(/例如/), {
      target: { value: '继续看估值' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '继续看估值',
          context: undefined,
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('never replays history or a prior report hint as authority after the first acceptance', async () => {
    mockStoreState.messages = [
      { id: '1', role: 'user', content: '分析600519' },
      { id: '2', role: 'user', content: '改看宁德时代' },
      { id: '3', role: 'assistant', content: '模型猜测正在讨论300750' },
    ];
    mockStoreState.stateContract = 'authoritative';
    render(<MemoryRouter initialEntries={['/chat?stock=AAPL&name=Apple']}><ChatPage /></MemoryRouter>);
    const input = await screen.findByDisplayValue('请深入分析 Apple(AAPL)');
    expect(screen.getByLabelText('当前讨论对象')).toHaveTextContent('未确认');
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(mockStartStream).toHaveBeenCalledTimes(1));
    expect(mockStartStream.mock.calls[0][0].context).toEqual({ stock_code: 'AAPL', stock_name: 'Apple' });
    fireEvent.change(input, { target: { value: '风险呢' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(mockStartStream).toHaveBeenCalledTimes(2));
    expect(mockStartStream.mock.calls[1][0].context).toBeUndefined();
    expect(screen.getByLabelText('当前讨论对象')).toHaveTextContent('未确认');
  });

  it.each(['风险呢', '改看300750', '比较600519和AAPL', 'AAPL与600519哪个更好'])(
    'does not overwrite or retransmit server state when submitting %s', async (message) => {
      mockStoreState.activeStockContext = { stock_code: '600519', canonical_id: 'sh600519',
        stock_name: '贵州茅台', asset_type: 'stock' };
      mockStoreState.stateContract = 'authoritative';
      render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);
      const input = await screen.findByPlaceholderText(/例如/);
      fireEvent.change(input, { target: { value: message } });
      fireEvent.click(screen.getByRole('button', { name: '发送' }));
      await waitFor(() => expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({ message, context: undefined }), expect.anything()));
      expect(screen.getByLabelText('当前讨论对象')).toHaveTextContent('贵州茅台');
    },
  );

  it('ignores malformed follow-up query params', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=%3Cscript%3E&name=Bad%0AName&recordId=abc']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByRole('heading', { name: '问股' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/例如/)).toHaveValue('');
    expect(historyApi.getDetail).not.toHaveBeenCalled();
  });

  it('reprocesses follow-up query params when navigating to the same chat route again', async () => {
    const firstDeferred = createDeferred<Awaited<ReturnType<typeof historyApi.getDetail>>>();
    const secondDeferred = createDeferred<Awaited<ReturnType<typeof historyApi.getDetail>>>();

    vi.mocked(historyApi.getDetail)
      .mockImplementationOnce(() => firstDeferred.promise)
      .mockImplementationOnce(() => secondDeferred.promise);

    const router = createMemoryRouter(
      [{ path: '/chat', element: <ChatPage /> }],
      {
        initialEntries: ['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0&recordId=1'],
      },
    );

    render(<RouterProvider router={router} />);

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();
    expect(screen.getByText('正在加载历史分析上下文；现在可直接发送追问。')).toBeInTheDocument();

    await act(async () => {
      await router.navigate('/chat?stock=AAPL&name=Apple&recordId=2');
    });

    expect(await screen.findByDisplayValue('请深入分析 Apple(AAPL)')).toBeInTheDocument();

    firstDeferred.resolve({
      meta: {
        id: 1,
        queryId: 'q-1',
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'detailed',
        createdAt: '2026-03-18T08:00:00Z',
        currentPrice: 1523.6,
        changePct: 1.8,
      },
      summary: {
        analysisSummary: '趋势延续',
        operationAdvice: '继续观察',
        trendPrediction: '高位震荡',
        sentimentScore: 78,
      },
      strategy: {
        stopLoss: '1450',
      },
    });

    secondDeferred.resolve({
      meta: {
        id: 2,
        queryId: 'q-2',
        stockCode: 'AAPL',
        stockName: 'Apple',
        reportType: 'detailed',
        createdAt: '2026-03-18T09:00:00Z',
        currentPrice: 211.5,
        changePct: 2.4,
      },
      summary: {
        analysisSummary: '趋势走强',
        operationAdvice: '继续持有',
        trendPrediction: '短线偏强',
        sentimentScore: 81,
      },
      strategy: {
        stopLoss: '205',
      },
    });

    await waitFor(() => {
      expect(screen.queryByText('正在加载历史分析上下文；现在可直接发送追问。')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '请深入分析 Apple(AAPL)',
          context: expect.objectContaining({
            stock_code: 'AAPL',
            stock_name: 'Apple',
            previous_price: 211.5,
            previous_change_pct: 2.4,
            previous_strategy: expect.objectContaining({
              stopLoss: '205',
            }),
          }),
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it.each([
    ['sh000016', 'sh000016'],
    ['csi930955', 'csi930955'],
    ['000016.SH', 'sh000016'],
  ] as const)('restores the %s follow-up URL to the registry canonical and hides the stock-only watchlist action', async (stockParam, expectedCanonical) => {
    render(
      <MemoryRouter initialEntries={[`/chat?stock=${stockParam}`]}>
        <ChatPage />
      </MemoryRouter>,
    );

    const expectedPrompt = `请深入分析 ${expectedCanonical}`;
    expect(await screen.findByDisplayValue(expectedPrompt)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: expectedPrompt,
          context: {
            stock_code: expectedCanonical,
            stock_name: null,
          },
        }),
        expect.any(Object),
      );
    });

    // The index canonical hides the stock-only watchlist action immediately.
    expect(screen.queryByText('加入自选')).not.toBeInTheDocument();
    expect(screen.queryByText('从自选删除')).not.toBeInTheDocument();
  });

  it('defers a default-backend index follow-up until the registry settles', async () => {
    mockStockIndexState.index = [];
    mockStockIndexState.loading = true;
    mockStockIndexState.loaded = false;

    const { rerender } = render(
      <MemoryRouter initialEntries={['/chat?stock=sh000016']}>
        <ChatPage />
      </MemoryRouter>,
    );
    expect(screen.queryByDisplayValue(/请深入分析/)).not.toBeInTheDocument();

    mockStockIndexState.index = mockStockIndex;
    mockStockIndexState.loading = false;
    mockStockIndexState.loaded = true;
    rerender(
      <MemoryRouter initialEntries={['/chat?stock=sh000016']}>
        <ChatPage />
      </MemoryRouter>,
    );

    expect(await screen.findByDisplayValue('请深入分析 sh000016')).toBeInTheDocument();
  });

  type RegistrySettleRow = [
    string,
    { index: typeof mockStockIndexState.index; error: Error | null; fallback: boolean },
    string,
  ];

  it.each<RegistrySettleRow>([
    [
      'success settle with index data',
      { index: mockStockIndex, error: null, fallback: false },
      '请深入分析 sh000016',
    ],
    [
      'explicit load failure fail-open',
      { index: [], error: new Error('registry unavailable'), fallback: true },
      '请深入分析 SH000016',
    ],
    [
      'successful-empty registry fail-open',
      { index: [], error: null, fallback: false },
      '请深入分析 SH000016',
    ],
  ])(
    'releases the default-backend index follow-up after the shared registry settles: %s',
    async (_scenario, finalRegistry, expectedPrompt) => {
      mockStockIndexState.index = [];
      mockStockIndexState.loading = true;
      mockStockIndexState.error = null;
      mockStockIndexState.fallback = false;
      mockStockIndexState.loaded = false;

      const { rerender } = render(
        <MemoryRouter initialEntries={['/chat?stock=sh000016']}>
          <ChatPage />
        </MemoryRouter>,
      );

      await waitFor(() => {
        expect(screen.queryByDisplayValue(/请深入分析 (SH000016|sh000016)/)).not.toBeInTheDocument();
      });

      // Settle regardless of outcome: success consumes the registry canonical;
      // failure and an empty registry fail open to the stock path.
      mockStockIndexState.index = finalRegistry.index;
      mockStockIndexState.loading = false;
      mockStockIndexState.error = finalRegistry.error;
      mockStockIndexState.fallback = finalRegistry.fallback;
      mockStockIndexState.loaded = true;
      rerender(
        <MemoryRouter initialEntries={['/chat?stock=sh000016']}>
          <ChatPage />
        </MemoryRouter>,
      );

      expect(await screen.findByDisplayValue(expectedPrompt)).toBeInTheDocument();
    },
  );

  it.each(['authoritative', 'legacy'] as const)(
    'does not restore a guessed stock from %s history when the store explicitly has no object', async (contract) => {
      mockStoreState.stateContract = contract;
      mockStoreState.messages = [{ id: 'm-1', role: 'user', content: '分析 sh000016' }];
      render(<MemoryRouter initialEntries={['/chat']}><ChatPage /></MemoryRouter>);
      const input = await screen.findByPlaceholderText(/例如/);
      expect(screen.getByLabelText('当前讨论对象')).toHaveTextContent('未确认');
      expect(screen.queryByText('加入自选')).not.toBeInTheDocument();
      fireEvent.change(input, { target: { value: '继续看支撑位' } });
      fireEvent.click(screen.getByRole('button', { name: '发送' }));
      await waitFor(() => expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({ context: undefined }), expect.anything()));
    },
  );

  it('shows a jump-to-latest action when new content arrives while the user is away from bottom', async () => {
    mockStoreState.messages = [
      { id: 'user-1', role: 'user', content: '请分析 600519' },
      { id: 'assistant-1', role: 'assistant', content: '趋势偏强', skillName: '趋势分析' },
    ];

    const { rerender } = render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const viewport = await screen.findByTestId('chat-message-scroll');
    Object.defineProperty(viewport, 'scrollTop', { configurable: true, value: 0 });
    Object.defineProperty(viewport, 'clientHeight', { configurable: true, value: 400 });
    Object.defineProperty(viewport, 'scrollHeight', { configurable: true, value: 1200 });

    fireEvent.scroll(viewport);

    mockStoreState.messages = [
      ...mockStoreState.messages,
      { id: 'assistant-2', role: 'assistant', content: '新的补充分析', skillName: '趋势分析' },
    ];

    rerender(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const jumpButton = await screen.findByRole('button', { name: '查看最新消息' });
    expect(jumpButton).toBeInTheDocument();

    fireEvent.click(jumpButton);

    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled();
  });
});

describe('extractStockCodeFromMessage', () => {
  it('returns 6-digit A-share code', () => {
    expect(extractStockCodeFromMessage('分析 600519 趋势')).toBe('600519');
    expect(extractStockCodeFromMessage('002460')).toBe('002460');
  });

  it('returns HK prefixed code (normalized)', () => {
    expect(extractStockCodeFromMessage('分析 hk00700')).toBe('HK00700');
  });

  it('returns .HK suffix code (normalized to canonical)', () => {
    expect(extractStockCodeFromMessage('00700.HK')).toBe('HK00700');
    expect(extractStockCodeFromMessage('1810.HK')).toBe('HK01810');
  });

  it('returns code with .SH/.SZ suffix (normalized)', () => {
    expect(extractStockCodeFromMessage('看 600519.SH')).toBe('600519');
    expect(extractStockCodeFromMessage('000001.SZ')).toBe('000001');
  });

  it('returns US ticker like AAPL', () => {
    expect(extractStockCodeFromMessage('分析 AAPL 走势')).toBe('AAPL');
    expect(extractStockCodeFromMessage('TSLA')).toBe('TSLA');
    expect(extractStockCodeFromMessage('分析 BRK.B')).toBe('BRK.B');
  });

  it('does NOT return finance abbreviations as tickers', () => {
    expect(extractStockCodeFromMessage('如果不考虑 TTM 呢')).toBeNull();
    expect(extractStockCodeFromMessage('市盈率 TTM 怎么看')).toBeNull();
    expect(extractStockCodeFromMessage('PE 怎么看')).toBeNull();
    expect(extractStockCodeFromMessage('MACD 还没金叉吗')).toBeNull();
    expect(extractStockCodeFromMessage('RSI 怎么看')).toBeNull();
    expect(extractStockCodeFromMessage('WHAT IS PE')).toBeNull();
    expect(extractStockCodeFromMessage('PE IS HIGH')).toBeNull();
    expect(extractStockCodeFromMessage('WHAT IS TTM')).toBeNull();
  });

  it('does NOT return contextual moving-average MA as a ticker', () => {
    expect(extractStockCodeFromMessage('分析 MA 均线')).toBeNull();
    expect(extractStockCodeFromMessage('看看 MA 怎么排列')).toBeNull();
    expect(extractStockCodesFromMessage('MA 和 RSI 的指标怎么看')).toEqual([]);
    expect(extractStockCodeFromMessage('分析 KDJ 指标')).toBeNull();
    expect(extractStockCodeFromMessage('KDJ 怎么看')).toBeNull();
  });

  it('skips finance abbreviations before a real ticker', () => {
    expect(extractStockCodeFromMessage('PE AAPL 怎么看')).toBe('AAPL');
    expect(extractStockCodeFromMessage('TTM AAPL 怎么看')).toBe('AAPL');
    expect(extractStockCodeFromMessage('MACD AAPL 怎么看')).toBe('AAPL');
    expect(extractStockCodeFromMessage('WHAT IS PE AAPL')).toBe('AAPL');
  });

  it('does NOT return exchange prefixes as tickers', () => {
    expect(extractStockCodeFromMessage('分析 SH 走势')).toBeNull();
    expect(extractStockCodeFromMessage('看看 BJ')).toBeNull();
    expect(extractStockCodeFromMessage('HK')).toBeNull();
    expect(extractStockCodeFromMessage('买入 SZ')).toBeNull();
    expect(extractStockCodeFromMessage('US 市场')).toBeNull();
    expect(extractStockCodeFromMessage('SS')).toBeNull();
  });

  it('returns null for messages without stock codes', () => {
    expect(extractStockCodeFromMessage('茅台现在适合买入吗')).toBeNull();
    expect(extractStockCodeFromMessage('大盘走势如何')).toBeNull();
  });

  it('matches prefixed code like SH600519 (normalized)', () => {
    expect(extractStockCodeFromMessage('分析 SH600519')).toBe('600519');
  });

  it('returns SZ-prefixed code when standalone (normalized)', () => {
    expect(extractStockCodeFromMessage('SZ000001')).toBe('000001');
  });

  it('returns all stock codes in message order', () => {
    expect(extractStockCodesFromMessage('分析 600519 和 AAPL 的差异')).toEqual(['600519', 'AAPL']);
    expect(extractStockCodesFromMessage('分析 AAPL 和 600519 的差异')).toEqual(['AAPL', '600519']);
    expect(extractStockCodesFromMessage('AAPL 和 TSLA 哪个更值得买')).toEqual(['AAPL', 'TSLA']);
    expect(extractStockCodesFromMessage('比较 BRK.B 和 AAPL')).toEqual(['BRK.B', 'AAPL']);
  });

  it('extracts lowercase tickers only with explicit stock intent hints', () => {
    expect(extractStockCodesFromMessage('分析tsla')).toEqual(['TSLA']);
    expect(extractStockCodesFromMessage('看看 tsla')).toEqual(['TSLA']);
    expect(extractStockCodesFromMessage('aapl 和 tsla 哪个更值得买')).toEqual(['AAPL', 'TSLA']);
    expect(extractStockCodesFromMessage('hello tsla')).toEqual([]);
  });

  it('returns all HK and A-share variants without exchange affix tokens', () => {
    expect(extractStockCodesFromMessage('比较 01810 和 AAPL')).toEqual(['HK01810', 'AAPL']);
    expect(extractStockCodesFromMessage('比较 1810.HK 和 AAPL')).toEqual(['HK01810', 'AAPL']);
    expect(extractStockCodesFromMessage('比较 600519.SH 和 AAPL')).toEqual(['600519', 'AAPL']);
    expect(extractStockCodesFromMessage('比较 000001.SZ 和 SS')).toEqual(['000001']);
    expect(extractStockCodesFromMessage('比较 SH600519 和 AAPL')).toEqual(['600519', 'AAPL']);
    expect(extractStockCodesFromMessage('比较 SZ000001 和 AAPL')).toEqual(['000001', 'AAPL']);
    expect(extractStockCodesFromMessage('比较 BJ920748 和 AAPL')).toEqual(['920748', 'AAPL']);
    expect(extractStockCodesFromMessage('比较 HK01810 和 AAPL')).toEqual(['HK01810', 'AAPL']);
  });

  it('does not return denied abbreviations in multi-code extraction', () => {
    expect(extractStockCodesFromMessage('如果不考虑 TTM 和 PE')).toEqual([]);
    expect(extractStockCodesFromMessage('MACD AAPL 和 RSI')).toEqual(['AAPL']);
    expect(extractStockCodesFromMessage('KDJ AAPL 怎么看')).toEqual(['AAPL']);
  });
});

describe('extractStockCodesFromMessage with index registry', () => {
  // The hoisted mock widens market/assetType to plain strings; the extraction
  // parameter is StockIndexItem[], so a structural cast keeps the registry rows.
  const registeredIndex = mockStockIndex as unknown as StockIndexItem[];

  it('resolves explicit SH-prefixed index tokens to the registry canonical only', () => {
    expect(extractStockCodesFromMessage('分析 sh000016', registeredIndex)).toEqual(['sh000016']);
    expect(extractStockCodesFromMessage('分析 SH000016', registeredIndex)).toEqual(['sh000016']);
  });

  it('resolves dotted SH index aliases without leaking the inner bare digits', () => {
    expect(extractStockCodesFromMessage('分析 000016.SH', registeredIndex)).toEqual(['sh000016']);
    expect(extractStockCodesFromMessage('分析 000016.sh', registeredIndex)).toEqual(['sh000016']);
  });

  it('resolves CSI display and prefix forms to the single csi canonical', () => {
    expect(extractStockCodesFromMessage('分析 930955.CSI', registeredIndex)).toEqual(['csi930955']);
    expect(extractStockCodesFromMessage('分析 CSI930955', registeredIndex)).toEqual(['csi930955']);
    expect(extractStockCodesFromMessage('分析 csi930955', registeredIndex)).toEqual(['csi930955']);
  });

  it('resolves a registered SZ index code via its registry canonical', () => {
    expect(extractStockCodesFromMessage('分析 sz399001', registeredIndex)).toEqual(['sz399001']);
  });

  it('extracts Taiwan codes carrying their trailing letter as one token', () => {
    // 尾字母是载荷不是杂讯（槓桿 00631L / 反向 00632R / 债券 ETF 00679B / 特别股 2887A）。
    // 少了 `[A-Z]?` 就**整个抽不到**（实测 mutation 回 `[]`）：後面较宽松的
    // `\b(\d{5,6})\b` 也救不了，尾随的 `L` 是 word char，`\b` 在那里不成立。
    // 症状是使用者在对话里打了代码却完全没有被识别成个股。
    expect(extractStockCodesFromMessage('分析 00631L.TW', registeredIndex)).toEqual(['00631L.TW']);
    expect(extractStockCodesFromMessage('分析 00632R.TW', registeredIndex)).toEqual(['00632R.TW']);
    expect(extractStockCodesFromMessage('分析 00679B.TWO', registeredIndex)).toEqual(['00679B.TWO']);
    expect(extractStockCodesFromMessage('分析 2887A.TW', registeredIndex)).toEqual(['2887A.TW']);
  });

  it('keeps plain Taiwan codes unchanged by the letter widening', () => {
    expect(extractStockCodesFromMessage('分析 2330.TW', registeredIndex)).toEqual(['2330.TW']);
    expect(extractStockCodesFromMessage('分析 00878.TW', registeredIndex)).toEqual(['00878.TW']);
  });

  it('keeps the bare same-code stock distinct from a registered index', () => {
    expect(extractStockCodesFromMessage('分析 000016', registeredIndex)).toEqual(['000016']);
    expect(extractStockCodesFromMessage('SH000016 和 000016', registeredIndex)).toEqual(['sh000016', '000016']);
    expect(extractStockCodesFromMessage('000016 和 sh000016', registeredIndex)).toEqual(['000016', 'sh000016']);
  });

  it('keeps stock semantics for unregistered explicit forms when the registry is loaded', () => {
    expect(extractStockCodesFromMessage('分析 sh600519', registeredIndex)).toEqual(['600519']);
    expect(extractStockCodesFromMessage('分析 SZ000001', registeredIndex)).toEqual(['000001']);
  });

  it('fails open to the stock path when no registry is passed', () => {
    expect(extractStockCodesFromMessage('分析 sh000016')).toEqual(['000016']);
  });

  it('keeps the legacy no-registry baseline for dotted index forms without leaking the suffix token', () => {
    // Without a registry, `930955.CSI` must behave EXACTLY as before this
    // change: the dotted form is NOT a registered index hit, so only the bare
    // digits surface (the `.CSI` suffix never leaks as a separate token).
    expect(extractStockCodesFromMessage('分析 930955.CSI')).toEqual(['930955']);
  });

  it('keeps the legacy baseline for csi-prefixed forms without a registry (no output)', () => {
    expect(extractStockCodesFromMessage('CSI930955')).toEqual([]);
    expect(extractStockCodesFromMessage('csi930955')).toEqual([]);
  });

  it('keeps SH/SZ stock alias normalization unchanged when the registry miss falls through', () => {
    expect(extractStockCodesFromMessage('分析 000016.SH')).toEqual(['000016']);
    expect(extractStockCodesFromMessage('分析 SH600519')).toEqual(['600519']);
  });

  it('does NOT surface the whole dotted form for an UNREGISTERED index even when the registry is loaded', () => {
    // The shared mock registry DOES contain the `930955.CSI` alias (csi930955),
    // so build a registry WITHOUT it to exercise the genuinely unregistered
    // case: it must fall through to the legacy bare-digit behavior, not emit
    // the whole token nor suppress the legacy patterns.
    const registryWithoutCsi = mockStockIndex.filter(
      (item) => item.canonicalCode !== 'csi930955',
    ) as StockIndexItem[];
    expect(extractStockCodesFromMessage('分析 930955.CSI', registryWithoutCsi)).toEqual(['930955']);
  });
});

describe('watchlist button with code variants', () => {
  it('shows "从自选删除" when canonical code is in watchlist and user inputs variant', async () => {
    mockStoreState.activeStockContext = { stock_code: '600519', canonical_id: 'sh600519', stock_name: null, asset_type: 'stock' };
    mockGetWatchlist.mockResolvedValue(['600519', 'HK01810']);

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>,
    );

    const textarea = await screen.findByPlaceholderText(/例如/);
    fireEvent.change(textarea, { target: { value: '分析 600519.SH' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    expect(await screen.findByText('从自选删除')).toBeInTheDocument();
  });

  it('shows "从自选删除" for HK variant codes', async () => {
    mockStoreState.activeStockContext = { stock_code: 'HK01810', canonical_id: 'hk01810', stock_name: null, asset_type: 'stock' };
    mockGetWatchlist.mockResolvedValue(['HK01810']);

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>,
    );

    const textarea = await screen.findByPlaceholderText(/例如/);
    fireEvent.change(textarea, { target: { value: '分析 1810.HK' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    expect(await screen.findByText('从自选删除')).toBeInTheDocument();
  });

  it('matches raw HK watchlist entries before rendering the watchlist action', async () => {
    mockStoreState.activeStockContext = { stock_code: 'HK01810', canonical_id: 'hk01810', stock_name: null, asset_type: 'stock' };
    mockGetWatchlist.mockResolvedValue(['01810']);

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>,
    );

    const textarea = await screen.findByPlaceholderText(/例如/);
    fireEvent.change(textarea, { target: { value: '分析 1810.HK' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    expect(await screen.findByText('从自选删除')).toBeInTheDocument();
  });

  it('removes the matched raw HK watchlist entry instead of adding a duplicate variant', async () => {
    mockStoreState.activeStockContext = { stock_code: 'HK00700', canonical_id: 'hk00700', stock_name: null, asset_type: 'stock' };
    mockGetWatchlist.mockResolvedValue(['00700']);
    mockRemoveFromWatchlist.mockResolvedValue([]);

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>,
    );

    const textarea = await screen.findByPlaceholderText(/例如/);
    fireEvent.change(textarea, { target: { value: '分析 00700.HK' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });
    fireEvent.click(await screen.findByText('从自选删除'));

    await waitFor(() => {
      expect(mockRemoveFromWatchlist).toHaveBeenCalledWith('00700');
    });
    expect(mockAddToWatchlist).not.toHaveBeenCalled();
  });
});
