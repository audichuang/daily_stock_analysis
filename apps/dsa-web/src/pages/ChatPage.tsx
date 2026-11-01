import React, { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate, useSearchParams } from 'react-router-dom';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ArrowDown, ChevronDown, History, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Plus, SlidersHorizontal, X } from 'lucide-react';
import { cn } from '../utils/cn';
import { agentApi } from '../api/agent';
import { portfolioApi } from '../api/portfolio';
import { stocksApi, type StockQuote } from '../api/stocks';
import { systemConfigApi } from '../api/systemConfig';
import { ApiErrorAlert, Badge, Button, ConfirmDialog, EmptyState, IconButton, InlineAlert, ScrollArea, ToastViewport } from '../components/common';
import { ShellHeaderActions, useShellHeaderActionsAvailable } from '../components/layout/ShellHeaderActions';
import { ChatStockSummaryCard } from '../components/chat/ChatStockSummaryCard';
import { createParsedApiError, getParsedApiError } from '../api/error';
import type { AgentStatusResponse, SkillInfo } from '../api/agent';
import { DashboardStateBlock } from '../components/dashboard';
import {
  useAgentChatStore,
  type Message,
  type ProgressStep,
} from '../stores/agentChatStore';
import { downloadSession, formatSessionAsMarkdown } from '../utils/chatExport';
import type { ChatFollowUpContext } from '../utils/chatFollowUp';
import {
  buildFollowUpPrompt,
  parseFollowUpRecordId,
  resolveChatFollowUpContext,
  sanitizeFollowUpStockCode,
  sanitizeFollowUpStockName,
} from '../utils/chatFollowUp';
import { isNearBottom } from '../utils/chatScroll';
import { filterSessions, groupSessionsByRecency, isFromEarlierDay } from '../utils/chatSessions';
import { searchStocks } from '../utils/searchStocks';
import { getReportText } from '../utils/reportLanguage';
import { getIntlLocale } from '../i18n/intlLocale';
import {
  findMatchingStockCode,
  includesStockCode,
  resolveRegisteredIndexCanonical,
} from '../utils/stockCode';
import { useStockIndex } from '../hooks/useStockIndex';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { CHAT_TEXT } from '../locales/chatText';
import { useEmbedMode } from '../utils/embedMode';
import type { UiLanguage, UiTextKey, UiTextParams } from '../i18n/uiText';

type Translate = (key: UiTextKey, params?: UiTextParams) => string;

// 空狀態的快捷問題：按下只填入輸入框，由使用者確認後才送出
const MARKET_PROMPT_KEYS: UiTextKey[] = ['chat.empty.market1', 'chat.empty.market2', 'chat.empty.market3'];
// 空狀態每組捷徑最多幾顆，手機一屏放得下。
const MAX_EMPTY_STOCKS = 4;
const MAX_INPUT_SUGGESTIONS = 6;
const MIN_SUGGESTION_QUERY_LENGTH = 2;

interface EmptyStockShortcut {
  code: string;
  name: string | null;
}

// 繁中介面用策略的繁中名；其他語系與未標註的策略用後端原名。
const getSkillDisplayName = (skill: SkillInfo, language: UiLanguage): string =>
  (language === 'zh-TW' ? skill.display_name_zh_tw : null) || skill.name;

const formatDayLabel = (value: string, locale: string): string =>
  new Date(value).toLocaleDateString(locale, { month: 'short', day: 'numeric', weekday: 'short' });

const formatTimeLabel = (value: string, locale: string): string =>
  new Date(value).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', hour12: false });

const isValidTimestamp = (value: string | null | undefined): value is string =>
  Boolean(value) && !Number.isNaN(new Date(value as string).getTime());

const MAX_SELECTED_SKILLS = 3;
const getMessageSkillNames = (msg: Message): string[] => {
  if (msg.skillNames?.length) return msg.skillNames;
  if (msg.skillName) return [msg.skillName];
  if (msg.skills?.length) return msg.skills;
  if (msg.skill) return [msg.skill];
  return [];
};

const getMessageSkillLabel = (msg: Message): string => getMessageSkillNames(msg).join('、');

const isStageDoneSuccessful = (status?: string): boolean => {
  if (!status) return true;
  const normalized = status.trim().toLowerCase();
  return ['completed', 'success', 'succeeded', 'done'].includes(normalized);
};

const getStageName = (step: ProgressStep, t: Translate): string => step.stage || t('chat.stage.genericName');

const getStageDoneLabel = (step: ProgressStep, t: Translate): string => {
  if (step.message) return step.message;
  const params = { stage: getStageName(step, t) };
  return t(isStageDoneSuccessful(step.status) ? 'chat.stage.completed' : 'chat.stage.notCompleted', params);
};

const getPipelineBudgetSkippedLabel = (step: ProgressStep, t: Translate): string =>
  step.message || t('chat.stage.budgetSkipped', { stage: getStageName(step, t) });

const getPipelineTimeoutLabel = (step: ProgressStep, t: Translate): string =>
  step.message || t('chat.stage.timedOut', { stage: getStageName(step, t) });

const ChatPage: React.FC = () => {
  const { language, t } = useUiLanguage();
  const chatText = CHAT_TEXT[language];
  const embedded = useEmbedMode();
  const shellActionsAvailable = useShellHeaderActionsAvailable();
  // 手機殼層有標題列、或 iOS 內嵌時，頁首只留 icon 列，h1 交給殼層。
  const compactHeader = shellActionsAvailable || embedded;
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [input, setInput] = useState('');
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [defaultSkillIds, setDefaultSkillIds] = useState<string[]>([]);
  const [showSkillDesc, setShowSkillDesc] = useState<string | null>(null);
  const [skillPickerOpen, setSkillPickerOpen] = useState(false);
  // Desktop popover anchor (viewport px), captured from the trigger when the picker opens.
  const [skillAnchor, setSkillAnchor] = useState<{ left: number; bottom: number } | null>(null);
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const [sendConfirmOpen, setSendConfirmOpen] = useState(false);
  const [historyCollapsed, setHistoryCollapsed] = useState(false);
  const [historyKeyword, setHistoryKeyword] = useState('');
  const [inputFocused, setInputFocused] = useState(false);
  const [holdings, setHoldings] = useState<EmptyStockShortcut[]>([]);
  const [quoteState, setQuoteState] = useState<{ code: string; quote: StockQuote | null } | null>(null);
  const [expandedThinking, setExpandedThinking] = useState<Set<string>>(new Set());
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [isFollowUpContextLoading, setIsFollowUpContextLoading] = useState(false);
  const [sendToast, setSendToast] = useState<{
    type: 'success' | 'error';
    message: string;
  } | null>(null);
  const [copiedMessages, setCopiedMessages] = useState<Set<string>>(new Set());
  const [showJumpToBottom, setShowJumpToBottom] = useState(false);
  const [watchlistCodes, setWatchlistCodes] = useState<string[]>([]);
  const [isWatchlistActioning, setIsWatchlistActioning] = useState(false);
  // undoCode: the exact watchlist entry just removed, so 復原 can add it back unchanged.
  const [watchlistMessage, setWatchlistMessage] = useState<{ key: UiTextKey; params?: UiTextParams; undoCode?: string } | null>(null);
  const [agentStatus, setAgentStatus] = useState<AgentStatusResponse | null>(null);
  const [agentStatusError, setAgentStatusError] = useState<string | null>(null);
  const [agentStatusChecking, setAgentStatusChecking] = useState(true);
  // The registry is used only to validate report hints, never to confirm Chat state.
  const { index: stockIndex, loading: stockIndexLoading } = useStockIndex();

  const watchlistMessageTimerRef = useRef<number | null>(null);
  const copyResetTimerRef = useRef<Partial<Record<string, number>>>({});
  const messagesViewportRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const skillTriggerRef = useRef<HTMLButtonElement>(null);
  const isMountedRef = useRef(true);
  const sendToastTimerRef = useRef<number | null>(null);
  const followUpHydrationTokenRef = useRef(0);
  const followUpContextRef = useRef<ChatFollowUpContext | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const pendingScrollBehaviorRef = useRef<ScrollBehavior>('auto');
  const agentStatusRequestIdRef = useRef(0);

  // Get localized text (default to Chinese)
  const text = getReportText(language);

  // Cleanup timers on unmount
  useEffect(() => {
    const timers = copyResetTimerRef.current;
    return () => {
      if (sendToastTimerRef.current !== null) {
        window.clearTimeout(sendToastTimerRef.current);
      }
      Object.values(timers).forEach((timerId) => {
        if (timerId !== undefined) {
          window.clearTimeout(timerId);
        }
      });
    };
  }, []);

  // Set page title
  useEffect(() => {
    document.title = `${t('layout.route.chat.title')} - DSA`;
  }, [t]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const loadWatchlist = useCallback(async () => {
    try {
      const codes = await systemConfigApi.getWatchlist();
      if (isMountedRef.current) {
        setWatchlistCodes(codes);
      }
    } catch {
      // ignore error silently
    }
  }, []);

  useEffect(() => {
    void loadWatchlist();
  }, [loadWatchlist]);

  const stockInWatchlist = useCallback(
    (stockCode: string) => includesStockCode(watchlistCodes, stockCode),
    [watchlistCodes],
  );

  const showWatchlistMessage = useCallback((message: { key: UiTextKey; params?: UiTextParams; undoCode?: string }) => {
    setWatchlistMessage(message);
    if (watchlistMessageTimerRef.current !== null) {
      window.clearTimeout(watchlistMessageTimerRef.current);
    }
    watchlistMessageTimerRef.current = window.setTimeout(() => {
      if (isMountedRef.current) {
        setWatchlistMessage(null);
      }
    }, message.undoCode ? 6000 : 3000);
  }, []);

  useEffect(() => () => {
    if (watchlistMessageTimerRef.current !== null) {
      window.clearTimeout(watchlistMessageTimerRef.current);
    }
  }, []);

  const handleToggleWatchlist = useCallback(
    async (stockCode: string) => {
      if (!stockCode || isWatchlistActioning) return;
      setIsWatchlistActioning(true);
      setWatchlistMessage(null);
      try {
        const existingStockCode = findMatchingStockCode(watchlistCodes, stockCode);
        if (existingStockCode) {
          const codes = await systemConfigApi.removeFromWatchlist(existingStockCode);
          if (isMountedRef.current) {
            setWatchlistCodes(codes);
            showWatchlistMessage({ key: 'chat.watchlistRemoved', params: { code: stockCode }, undoCode: existingStockCode });
          }
        } else {
          const codes = await systemConfigApi.addToWatchlist(stockCode);
          if (isMountedRef.current) {
            setWatchlistCodes(codes);
            showWatchlistMessage({ key: 'chat.watchlistAdded', params: { code: stockCode } });
          }
        }
      } catch {
        if (isMountedRef.current) {
          showWatchlistMessage({ key: 'chat.watchlistFailed' });
        }
      } finally {
        if (isMountedRef.current) {
          setIsWatchlistActioning(false);
        }
      }
    },
    [isWatchlistActioning, showWatchlistMessage, watchlistCodes],
  );

  // 移出自選的復原：把剛移掉的那筆原樣加回去。
  const handleUndoWatchlistRemoval = useCallback(async (code: string) => {
    if (isWatchlistActioning) return;
    setIsWatchlistActioning(true);
    setWatchlistMessage(null);
    try {
      const codes = await systemConfigApi.addToWatchlist(code);
      if (isMountedRef.current) {
        setWatchlistCodes(codes);
        showWatchlistMessage({ key: 'chat.watchlistAdded', params: { code } });
      }
    } catch {
      if (isMountedRef.current) {
        showWatchlistMessage({ key: 'chat.watchlistFailed' });
      }
    } finally {
      if (isMountedRef.current) {
        setIsWatchlistActioning(false);
      }
    }
  }, [isWatchlistActioning, showWatchlistMessage]);

  const {
    messages,
    selectedSkillIds: sessionSelectedSkillIds,
    activeStockContext,
    stateContract,
    loading,
    progressSteps,
    sessionId,
    sessions,
    sessionsLoading,
    chatError,
    stopping,
    terminalStatus,
    stopError,
    setSelectedSkillIds,
    loadSessions,
    loadInitialSession,
    switchSession,
    refreshSession,
    stopStream,
    startStream,
    clearCompletionBadge,
  } = useAgentChatStore();
  const selectedSkillIds = sessionSelectedSkillIds ?? defaultSkillIds;

  const activeStockCode = activeStockContext?.stock_code ?? null;

  const syncScrollState = useCallback(() => {
    const viewport = messagesViewportRef.current;
    if (!viewport) return;
    const nearBottom = isNearBottom({
      scrollTop: viewport.scrollTop,
      clientHeight: viewport.clientHeight,
      scrollHeight: viewport.scrollHeight,
    });
    shouldStickToBottomRef.current = nearBottom;
    setShowJumpToBottom((prev) => (nearBottom ? false : prev));
  }, []);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    messagesEndRef.current?.scrollIntoView({ behavior });
  }, []);

  const requestScrollToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    shouldStickToBottomRef.current = true;
    pendingScrollBehaviorRef.current = behavior;
    setShowJumpToBottom(false);
  }, []);

  const handleMessagesScroll = useCallback(() => {
    syncScrollState();
  }, [syncScrollState]);

  useEffect(() => {
    syncScrollState();
  }, [syncScrollState, sessionId]);

  useEffect(() => {
    const behavior = pendingScrollBehaviorRef.current;
    const shouldAutoScroll = shouldStickToBottomRef.current;
    if (!shouldAutoScroll) {
      if (messages.length > 0 || progressSteps.length > 0 || loading) {
        setShowJumpToBottom(true);
      }
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      scrollToBottom(behavior);
      pendingScrollBehaviorRef.current = loading ? 'auto' : 'smooth';
    });

    return () => window.cancelAnimationFrame(frame);
  }, [messages, progressSteps, loading, sessionId, scrollToBottom]);

  useEffect(() => {
    if (!loading) {
      pendingScrollBehaviorRef.current = 'smooth';
    }
  }, [loading]);

  useEffect(() => {
    clearCompletionBadge();
  }, [clearCompletionBadge]);

  useEffect(() => {
    loadInitialSession();
  }, [loadInitialSession]);

  useEffect(() => {
    agentApi.getSkills()
      .then((res) => {
        setSkills(res.skills);
        const defaultId =
          res.default_skill_id ||
          res.skills[0]?.id ||
          '';
        setDefaultSkillIds(defaultId ? [defaultId] : []);
      })
      .catch((error) => {
        console.error('Failed to load chat skills:', error);
      });
  }, []);

  const loadAgentStatus = useCallback(async () => {
    const requestId = agentStatusRequestIdRef.current + 1;
    agentStatusRequestIdRef.current = requestId;
    setAgentStatusChecking(true);
    try {
      const status = await agentApi.getStatus();
      if (!isMountedRef.current || agentStatusRequestIdRef.current !== requestId) return;
      setAgentStatus(status);
      setAgentStatusError(null);
    } catch (error: unknown) {
      if (!isMountedRef.current || agentStatusRequestIdRef.current !== requestId) return;
      setAgentStatus(null);
      setAgentStatusError(getParsedApiError(error).message);
    } finally {
      if (isMountedRef.current && agentStatusRequestIdRef.current === requestId) {
        setAgentStatusChecking(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadAgentStatus();
  }, [loadAgentStatus]);

  // 空狀態的「持股」捷徑；讀不到就不顯示這組，不影響問股。
  useEffect(() => {
    let active = true;
    void portfolioApi.getSnapshot()
      .then((snapshot) => {
        if (!active) return;
        const seen = new Set<string>();
        const shortcuts: EmptyStockShortcut[] = [];
        for (const account of snapshot.accounts ?? []) {
          for (const position of account.positions ?? []) {
            if (seen.has(position.symbol)) continue;
            seen.add(position.symbol);
            shortcuts.push({ code: position.symbol, name: position.name ?? null });
          }
        }
        setHoldings(shortcuts);
      })
      .catch(() => {
        // 空狀態捷徑是輔助資訊，失敗時只少一組按鈕
      });
    return () => {
      active = false;
    };
  }, []);

  // 摘要卡的現價與漲跌：換標的或回答結束時更新。
  useEffect(() => {
    if (!activeStockCode || loading) return undefined;
    let active = true;
    void stocksApi.getQuotes([activeStockCode])
      .then((items) => {
        if (active) setQuoteState({ code: activeStockCode, quote: items[0]?.quote ?? null });
      })
      .catch(() => {
        if (active) setQuoteState({ code: activeStockCode, quote: null });
      });
    return () => {
      active = false;
    };
  }, [activeStockCode, loading]);

  // 報價跟著代碼走：換標的後、新報價回來前不能顯示上一檔的價格。
  const activeQuote = quoteState?.code === activeStockCode ? quoteState.quote : null;

  // 持股與自選重複的代號只留在持股那組；每組最多 MAX_EMPTY_STOCKS 顆。
  const holdingCodes = holdings.map((holding) => holding.code);
  const holdingShortcuts = holdings.slice(0, MAX_EMPTY_STOCKS);
  const watchlistShortcuts: EmptyStockShortcut[] = watchlistCodes
    .filter((code) => !includesStockCode(holdingCodes, code))
    .slice(0, MAX_EMPTY_STOCKS)
    .map((code) => {
      const matched = stockIndex.find((item) => item.canonicalCode === code || item.displayCode === code);
      return { code, name: matched?.nameZh ?? null };
    });
  const selectedSkillIdSet = new Set(selectedSkillIds);
  const skillLimitReached = selectedSkillIds.length >= MAX_SELECTED_SKILLS;
  const skillGroups: Array<{ id: string; name: string | null; items: SkillInfo[] }> = [];
  for (const skill of skills) {
    const groupId = skill.group || '';
    const existingGroup = skillGroups.find((group) => group.id === groupId);
    if (existingGroup) existingGroup.items.push(skill);
    else skillGroups.push({ id: groupId, name: skill.group_name_zh_tw || null, items: [skill] });
  }
  const agentConfirmedUnavailable = Boolean(agentStatus && !agentStatus.available);
  const agentAvailable = Boolean(agentStatus?.available) && !agentStatusChecking;
  const agentUnavailableMessage = agentStatus?.errorCode === 'agent_mode_disabled'
    ? t('chat.agentModeDisabled')
    : agentStatus?.errorCode === 'platform_unsupported'
      ? t('chat.agentPlatformUnsupported')
      : agentStatus?.backend === 'codex_app_server'
        ? t('chat.codexUnavailableMessage')
        : t('chat.defaultUnavailableMessage');
  const agentUnavailableError = agentConfirmedUnavailable
    ? createParsedApiError({
        title: t('chat.agentBackendUnavailableTitle'),
        message: agentUnavailableMessage,
        rawMessage: `${agentStatus?.errorCode || 'capability_unsupported'}: ${agentStatus?.message || ''}`,
        category: 'upstream_network',
      })
    : null;

  const getSkillNames = useCallback(
    (skillIds: string[]) => skillIds.map((id) => {
      const skill = skills.find((s) => s.id === id);
      return skill ? getSkillDisplayName(skill, language) : id;
    }),
    [language, skills],
  );

  const normalizeSelectedSkillIds = useCallback((skillIds: string[]) => {
    const normalized: string[] = [];
    for (const skillId of skillIds) {
      const cleaned = skillId.trim();
      if (cleaned && !normalized.includes(cleaned)) {
        normalized.push(cleaned);
      }
    }
    return normalized.slice(0, MAX_SELECTED_SKILLS);
  }, []);

  const toggleSkillSelection = useCallback((skillId: string) => {
    if (selectedSkillIds.includes(skillId)) {
      setSelectedSkillIds(selectedSkillIds.filter((id) => id !== skillId));
      return;
    }
    if (selectedSkillIds.length < MAX_SELECTED_SKILLS) {
      setSelectedSkillIds([...selectedSkillIds, skillId]);
    }
  }, [selectedSkillIds, setSelectedSkillIds]);

  const closeSkillPicker = useCallback(() => {
    setSkillPickerOpen(false);
    skillTriggerRef.current?.focus();
  }, []);

  // 策略面板開著時 Esc 關閉，焦點還給觸發鈕。
  useEffect(() => {
    if (!skillPickerOpen) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      closeSkillPicker();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [skillPickerOpen, closeSkillPicker]);

  const toggleSkillPicker = () => {
    if (skillPickerOpen) {
      setSkillPickerOpen(false);
      return;
    }
    // The panel is portaled to body, so the desktop popover is positioned from the trigger rect.
    const rect = skillTriggerRef.current?.getBoundingClientRect();
    setSkillAnchor(rect ? { left: rect.left, bottom: window.innerHeight - rect.top + 8 } : null);
    setSkillPickerOpen(true);
  };

  const handleStartNewChat = useCallback(() => {
    followUpContextRef.current = null;
    requestScrollToBottom('auto');
    useAgentChatStore.getState().startNewChat();
    setSidebarOpen(false);
  }, [requestScrollToBottom]);

  const handleSwitchSession = useCallback((targetSessionId: string) => {
    if (targetSessionId === sessionId) {
      setSidebarOpen(false);
      return;
    }
    followUpContextRef.current = null;
    requestScrollToBottom('auto');
    switchSession(targetSessionId);
    setSidebarOpen(false);
  }, [requestScrollToBottom, sessionId, switchSession]);

  const confirmDelete = useCallback(() => {
    if (!deleteConfirmId) return;
    agentApi.deleteChatSession(deleteConfirmId)
      .then(() => {
        loadSessions();
        if (deleteConfirmId === sessionId) {
          handleStartNewChat();
        }
      })
      .catch((error) => {
        console.error('Failed to delete chat session:', error);
      });
    setDeleteConfirmId(null);
  }, [deleteConfirmId, sessionId, loadSessions, handleStartNewChat]);

  // Handle follow-up from report page: ?stock=600519&name=贵州茅台&recordId=xxx
  useEffect(() => {
    const rawStockCode = searchParams.get('stock');
    if (!rawStockCode) {
      // Nothing to follow up — only clear when there actually ARE stale query
      // params. Skipping the empty case avoids redundant `replace: true`
      // navigations on every effect re-run (the gate below legitimately re-runs
      // as status/registry state settles), which would otherwise clobber
      // subsequent RouterProvider navigation state asserted by other tests.
      if (searchParams.size === 0) {
        return;
      }
      setSearchParams({}, { replace: true });
      return;
    }

    if (stockIndexLoading) {
      return;
    }
    if (agentStatusChecking) {
      return;
    }

    // Registry canonical first for explicit index follow-ups (sh000016 /
    // 000016.SH / 930955.CSI / csi930955) so the report-follow-up canonical is
    // preserved end-to-end; the sanitize contract is untouched and remains the
    // stock fail-open when the registry is unavailable or the code unregistered.
    const registryCanonical = resolveRegisteredIndexCanonical(stockIndex, rawStockCode);
    const stock = registryCanonical ?? sanitizeFollowUpStockCode(rawStockCode);
    const name = sanitizeFollowUpStockName(searchParams.get('name'));
    const recordId = parseFollowUpRecordId(searchParams.get('recordId'));

    if (!stock) {
      setSearchParams({}, { replace: true });
      return;
    }

    const hydrationToken = ++followUpHydrationTokenRef.current;
    setInput(buildFollowUpPrompt(stock, name));
    followUpContextRef.current = {
      stock_code: stock,
      stock_name: name,
    };
    if (recordId !== undefined) {
      setIsFollowUpContextLoading(true);
    }
    void resolveChatFollowUpContext({
      stockCode: stock,
      stockName: name,
      recordId,
      index: stockIndex,
    }).then((context) => {
      if (!isMountedRef.current || followUpHydrationTokenRef.current !== hydrationToken) {
        return;
      }
      followUpContextRef.current = context;
    }).finally(() => {
      if (isMountedRef.current && followUpHydrationTokenRef.current === hydrationToken) {
        setIsFollowUpContextLoading(false);
      }
    });
    setSearchParams({}, { replace: true });
  }, [searchParams, setSearchParams, stockIndex, stockIndexLoading, agentStatusChecking]);

  const handleSend = useCallback(
    async (overrideMessage?: string) => {
      const msgText = (overrideMessage ?? input).trim();
      if (!msgText || loading || !agentAvailable || !agentStatus) return;
      if (overrideMessage !== undefined) {
        setInput(msgText);
      }
      const requestedSkillIds = sessionSelectedSkillIds;
      const usedSkillIds = normalizeSelectedSkillIds(
        requestedSkillIds ?? selectedSkillIds,
      );
      const usedSkillNames = usedSkillIds.length > 0 ? getSkillNames(usedSkillIds) : [t('chat.skillGeneral')];
      // Only report/shortcut hints accompany this request. Ordinary follow-ups
      // rely on the server's accepted state, not a replay or a client-selected fact.
      const contextForSend = followUpContextRef.current ?? undefined;

      const payload = {
        message: msgText,
        session_id: sessionId,
        ...(requestedSkillIds !== null
          ? { skills: normalizeSelectedSkillIds(requestedSkillIds) }
          : {}),
        context: contextForSend ?? undefined,
      };
      await startStream(payload, {
        skillNames: usedSkillNames,
        skillName: usedSkillNames.join('、'),
        onAccepted: () => {
          followUpHydrationTokenRef.current += 1;
          followUpContextRef.current = null;
          setIsFollowUpContextLoading(false);
          setInput('');
          setSkillPickerOpen(false);
          requestScrollToBottom('smooth');
        },
      });
    },
    [agentAvailable, agentStatus, getSkillNames, input, loading, normalizeSelectedSkillIds, requestScrollToBottom, selectedSkillIds, sessionId, sessionSelectedSkillIds, startStream, t],
  );

  const suggestionQuery = input.match(/\S+$/)?.[0] ?? '';
  const inputSuggestions = inputFocused && !loading && suggestionQuery.length >= MIN_SUGGESTION_QUERY_LENGTH
    ? searchStocks(suggestionQuery, stockIndex, { limit: MAX_INPUT_SUGGESTIONS })
    : [];

  const fillInput = useCallback((value: string, context: ChatFollowUpContext | null) => {
    followUpHydrationTokenRef.current += 1;
    followUpContextRef.current = context;
    setIsFollowUpContextLoading(false);
    setInput(value);
    inputRef.current?.focus();
  }, []);

  const handleSelectSuggestion = (code: string, name: string) => {
    const prefix = input.slice(0, input.length - suggestionQuery.length);
    fillInput(`${prefix}${name} ${code} `, { stock_code: code, stock_name: name });
  };

  const fillStockShortcut = (shortcut: EmptyStockShortcut) => {
    fillInput(
      t('chat.empty.analyzePrompt', { stock: shortcut.name ? `${shortcut.name} ${shortcut.code}` : shortcut.code }),
      { stock_code: shortcut.code, stock_name: shortcut.name },
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 中文輸入法選字的 Enter 不是送出。
    if (e.nativeEvent.isComposing) return;
    if (e.key === 'Enter' && !e.shiftKey) {
      // 手機鍵盤的 Enter 只換行，靠傳送鈕送出；桌機維持 Enter 傳送、Shift+Enter 換行。
      if (window.matchMedia('(pointer: coarse)').matches) return;
      e.preventDefault();
      handleSend();
    }
  };

  const showSendFeedback = useCallback((nextToast: { type: 'success' | 'error'; message: string }, durationMs: number) => {
    if (sendToastTimerRef.current !== null) {
      window.clearTimeout(sendToastTimerRef.current);
    }
    setSendToast(nextToast);
    sendToastTimerRef.current = window.setTimeout(() => {
      setSendToast(null);
      sendToastTimerRef.current = null;
    }, durationMs);
  }, []);

  const toggleThinking = (msgId: string) => {
    setExpandedThinking((prev) => {
      const next = new Set(prev);
      if (next.has(msgId)) next.delete(msgId);
      else next.add(msgId);
      return next;
    });
  };

  const copyMessageToClipboard = async (msgId: string, content: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedMessages((prev) => new Set(prev).add(msgId));
      const existingTimer = copyResetTimerRef.current[msgId];
      if (existingTimer !== undefined) {
        window.clearTimeout(existingTimer);
      }
      copyResetTimerRef.current[msgId] = window.setTimeout(() => {
        setCopiedMessages((prev) => {
          const next = new Set(prev);
          next.delete(msgId);
          return next;
        });
        delete copyResetTimerRef.current[msgId];
      }, 2000);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  };

  const downloadMessageAsMarkdown = useCallback((msg: Message) => {
    const skillLabel = getMessageSkillLabel(msg);
    const heading = msg.role === 'user' ? `# ${t('chat.export.userHeading')}` : `# ${t('chat.export.aiHeading')}${skillLabel ? ` · ${skillLabel}` : ''}`;
    const content = [heading, '', msg.content].join('\n');
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${msg.role === 'user' ? 'user' : 'assistant'}-message-${msg.id}.md`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }, [t]);

  const handleConfirmSendToNotify = async () => {
    setSendConfirmOpen(false);
    if (sending) return;
    setSending(true);
    setSendToast(null);
    try {
      const content = formatSessionAsMarkdown(messages, getIntlLocale(language));
      await agentApi.sendChat(content);
      showSendFeedback({ type: 'success', message: t('chat.sendSuccessMessage') }, 3000);
    } catch (err) {
      const parsed = getParsedApiError(err);
      showSendFeedback({ type: 'error', message: parsed.message || t('chat.sendFailed') }, 5000);
    } finally {
      setSending(false);
    }
  };

  const getCurrentStage = (steps: ProgressStep[]): string => {
    if (steps.length === 0) return t('chat.stage.connecting');
    const last = steps[steps.length - 1];
    if (last.type === 'thinking') return last.message || t('chat.stage.thinking');
    if (last.type === 'tool_start')
      return `${last.display_name || last.tool}...`;
    if (last.type === 'tool_done')
      return t('chat.stage.toolDone', { tool: last.display_name || last.tool || '' });
    if (last.type === 'stage_start')
      return last.message || t('chat.stage.starting', { stage: getStageName(last, t) });
    if (last.type === 'stage_done')
      return getStageDoneLabel(last, t);
    if (last.type === 'pipeline_timeout')
      return getPipelineTimeoutLabel(last, t);
    if (last.type === 'pipeline_budget_skipped')
      return getPipelineBudgetSkippedLabel(last, t);
    if (last.type === 'generating')
      return last.message || t('chat.stage.generating');
    return t('chat.stage.processing');
  };

  const renderThinkingBlock = (msg: Message) => {
    if (!msg.thinkingSteps || msg.thinkingSteps.length === 0) return null;
    const isExpanded = expandedThinking.has(msg.id);
    const toolSteps = msg.thinkingSteps.filter((s) => s.type === 'tool_done');
    const totalDuration = toolSteps.reduce(
      (sum, s) => sum + (s.duration || 0),
      0,
    );
    const summary = t('chat.thinking.summary', { count: toolSteps.length, seconds: totalDuration.toFixed(1) });

    return (
      <button
        onClick={() => toggleThinking(msg.id)}
        className="flex items-center gap-2 text-xs text-muted-text hover:text-secondary-text transition-colors mb-2 w-full text-left"
      >
        <svg
          className={`w-3 h-3 transition-transform flex-shrink-0 ${isExpanded ? 'rotate-90' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 5l7 7-7 7"
          />
        </svg>
        <span className="flex items-center gap-1.5">
          <span className="text-secondary-text">{t('chat.thinking.title')}</span>
          <span className="text-muted-text">·</span>
          <span className="text-secondary-text">{summary}</span>
        </span>
      </button>
    );
  };

  const renderThinkingDetails = (steps: ProgressStep[]) => (
    <div className="mb-3 pl-5 border-l border-border/40 space-y-1.5 animate-fade-in">
      {steps.map((step, idx) => {
        let statusClass = 'chat-progress-item-muted';
        let iconClass = 'chat-progress-dot-muted';
        let text = '';
        if (step.type === 'thinking') {
          text = step.message || t('chat.thinking.step', { step: step.step ?? '' });
          statusClass = 'chat-progress-item-thinking';
          iconClass = 'chat-progress-dot-thinking';
        } else if (step.type === 'tool_start') {
          text = `${step.display_name || step.tool}...`;
          statusClass = 'chat-progress-item-tool';
          iconClass = 'chat-progress-dot-tool';
        } else if (step.type === 'tool_done') {
          text = `${step.display_name || step.tool} (${step.duration}s)`;
          statusClass = step.success ? 'chat-progress-item-success' : 'chat-progress-item-danger';
          iconClass = step.success ? 'chat-progress-dot-success' : 'chat-progress-dot-danger';
        } else if (step.type === 'stage_start') {
          text = step.message || t('chat.stage.starting', { stage: getStageName(step, t) });
          statusClass = 'chat-progress-item-thinking';
          iconClass = 'chat-progress-dot-thinking';
        } else if (step.type === 'stage_done') {
          const isSuccess = isStageDoneSuccessful(step.status);
          text = getStageDoneLabel(step, t);
          statusClass = isSuccess ? 'chat-progress-item-success' : 'chat-progress-item-danger';
          iconClass = isSuccess ? 'chat-progress-dot-success' : 'chat-progress-dot-danger';
        } else if (step.type === 'pipeline_timeout') {
          text = getPipelineTimeoutLabel(step, t);
          statusClass = 'chat-progress-item-danger';
          iconClass = 'chat-progress-dot-danger';
        } else if (step.type === 'pipeline_budget_skipped') {
          text = getPipelineBudgetSkippedLabel(step, t);
          statusClass = 'chat-progress-item-muted';
          iconClass = 'chat-progress-dot-muted';
        } else if (step.type === 'generating') {
          text = step.message || t('chat.thinking.generating');
          statusClass = 'chat-progress-item-generating';
          iconClass = 'chat-progress-dot-generating';
        } else {
          text = step.message || t('chat.stage.processing');
        }
        return (
          <div
            key={idx}
            className={cn('chat-progress-item', statusClass)}
          >
            <span className={cn('chat-progress-dot', iconClass)} />
            <span className="leading-relaxed">{text}</span>
          </div>
        );
      })}
    </div>
  );

  const visibleSessions = filterSessions(sessions, historyKeyword);
  const sessionGroups = groupSessionsByRecency(visibleSessions);
  const intlLocale = getIntlLocale(language);

  const sidebarContent = (
    <>
      <div className="space-y-2 border-b border-border/50 p-3">
        <div className="flex items-center justify-between gap-2">
          <Button
            size="sm"
            className="flex-1"
            onClick={handleStartNewChat}
            aria-label={t('chat.history.newChat')}
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            {t('chat.newChat')}
          </Button>
          <IconButton
            className="hidden md:inline-flex"
            aria-label={t('chat.history.collapse')}
            icon={<PanelLeftClose className="h-4 w-4" aria-hidden="true" />}
            onClick={() => setHistoryCollapsed(true)}
          />
        </div>
        <input
          type="search"
          value={historyKeyword}
          onChange={(event) => setHistoryKeyword(event.target.value)}
          placeholder={t('chat.history.searchPlaceholder')}
          aria-label={t('chat.history.searchPlaceholder')}
          className="input-surface h-9 w-full rounded-lg border bg-transparent px-3 text-base focus:outline-none md:text-sm"
        />
      </div>
      <ScrollArea testId="chat-session-list-scroll" viewportClassName="p-3">
        {sessionsLoading ? (
          <DashboardStateBlock
            loading
            compact
            title={t('chat.history.loading')}
            className="rounded-2xl border border-dashed border-border/50 bg-surface/30"
          />
        ) : sessions.length === 0 ? (
          <DashboardStateBlock
            compact
            title={t('chat.history.emptyTitle')}
            description={t('chat.history.emptyDescription')}
            className="rounded-2xl border border-dashed border-border/50 bg-surface/30"
          />
        ) : visibleSessions.length === 0 ? (
          <p className="py-4 text-center text-xs text-secondary-text">{t('chat.history.noMatch')}</p>
        ) : (
          <div className="space-y-4">
            {sessionGroups.map((group) => (
              <div key={group.id} className="space-y-2">
                <h3 className="text-xs font-medium text-muted-text">{t(`chat.history.group.${group.id}`)}</h3>
                {group.sessions.map((s) => (
                  <div key={s.session_id} className="session-item-row">
                    <button
                      type="button"
                      onClick={() => handleSwitchSession(s.session_id)}
                      className={`session-item ${s.session_id === sessionId ? 'active' : ''}`}
                      aria-label={t('chat.history.switchTo', { title: s.title })}
                      aria-current={s.session_id === sessionId ? 'page' : undefined}
                    >
                      <div className="indicator" />
                      <div className="content">
                        <span className="title">{s.title}</span>
                        {s.stock_code ? (
                          <span className="mt-1 inline-flex w-fit max-w-full truncate rounded-full border border-border/60 px-2 py-0.5 text-[11px] text-secondary-text">
                            {s.stock_name ? `${s.stock_name} · ` : ''}{s.stock_code}
                          </span>
                        ) : null}
                        <div className="mt-0.5 flex items-center gap-2">
                          <span className="meta">
                            {t('chat.history.messageCount', { count: s.message_count })}
                          </span>
                          {s.last_active && (
                            <>
                              <span className="separator" />
                              <span className="meta">
                                {new Date(s.last_active).toLocaleDateString(intlLocale, { month: 'short', day: 'numeric' })}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                    </button>
                    <button
                      type="button"
                      className="delete-btn"
                      onClick={() => {
                        setDeleteConfirmId(s.session_id);
                      }}
                      aria-label={t('chat.history.delete', { title: s.title })}
                    >
                      <svg
                        className="w-3.5 h-3.5"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                        />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
    </>
  );

  const selectedSkillSummary = selectedSkillIds.length > 0
    ? getSkillNames(selectedSkillIds).join('、')
    : t('chat.skillPicker.none');

  const lastMessage = messages[messages.length - 1];
  const lastAssistantId = [...messages].reverse().find((msg) => msg.role === 'assistant')?.id;
  const lastUserMessage = [...messages].reverse().find((msg) => msg.role === 'user');
  const staleSince = !loading && isValidTimestamp(lastMessage?.createdAt) && isFromEarlierDay(lastMessage.createdAt)
    ? lastMessage.createdAt
    : null;

  const renderEmptyGroup = (title: string, children: React.ReactNode) => (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-muted-text">{title}</h3>
      <div className="flex flex-wrap justify-center gap-2">{children}</div>
    </div>
  );

  const renderStockShortcut = (shortcut: EmptyStockShortcut) => (
    <button
      key={shortcut.code}
      type="button"
      onClick={() => fillStockShortcut(shortcut)}
      className="quick-question-btn"
    >
      <span className="text-secondary-text">{shortcut.code}</span>
      {shortcut.name ? ` ${shortcut.name}` : null}
    </button>
  );

  // 歷史、＋、⋯：手機殼層放進標題列，內嵌時單獨一列，桌機放在 h1 右側（歷史與＋只在窄螢幕出現）。
  const narrowOnlyClass = compactHeader ? '' : 'md:hidden';
  const headerIconRow = (
    <div data-testid="chat-header-actions" className="relative flex flex-shrink-0 items-center gap-1">
      <IconButton
        className={narrowOnlyClass}
        aria-label={t('chat.history.title')}
        icon={<History className="h-4 w-4" aria-hidden="true" />}
        onClick={() => setSidebarOpen(true)}
      />
      <IconButton
        className={narrowOnlyClass}
        aria-label={t('chat.newChat')}
        icon={<Plus className="h-4 w-4" aria-hidden="true" />}
        onClick={handleStartNewChat}
      />
      {messages.length > 0 ? (
        <>
          <IconButton
            aria-label={t('chat.moreActions')}
            aria-expanded={moreMenuOpen}
            aria-haspopup="menu"
            icon={<MoreHorizontal className="h-4 w-4" aria-hidden="true" />}
            onClick={() => setMoreMenuOpen((open) => !open)}
          />
          {moreMenuOpen ? (
            <div
              role="menu"
              className="absolute right-0 top-full z-30 mt-1 min-w-64 whitespace-nowrap rounded-xl border border-border/70 bg-card p-1 shadow-soft-card"
            >
              <button
                type="button"
                role="menuitem"
                className="block w-full rounded-lg px-3 py-2 text-left text-sm text-foreground hover:bg-hover"
                onClick={() => {
                  setMoreMenuOpen(false);
                  downloadSession(messages, intlLocale);
                }}
              >
                {chatText.exportMarkdown}
              </button>
              <button
                type="button"
                role="menuitem"
                disabled={sending}
                className="block w-full rounded-lg px-3 py-2 text-left text-sm text-foreground hover:bg-hover disabled:cursor-not-allowed disabled:opacity-60"
                onClick={() => {
                  setMoreMenuOpen(false);
                  setSendConfirmOpen(true);
                }}
              >
                {chatText.pushToNotify}
              </button>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );

  return (
    <div
      data-testid="chat-workspace"
      className="flex h-[calc(100dvh-var(--shell-page-offset,2rem))] w-full min-w-0 gap-4 overflow-hidden"
    >
      {/* Desktop sidebar */}
      {historyCollapsed ? null : (
        <div className="hidden h-full w-64 flex-shrink-0 flex-col overflow-hidden rounded-[1.25rem] border border-white/8 bg-card/82 shadow-soft-card md:flex">
          {sidebarContent}
        </div>
      )}

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div
          className={cn('fixed inset-0 z-40', compactHeader ? '' : 'md:hidden')}
          onClick={() => setSidebarOpen(false)}
        >
          <div className="page-drawer-overlay absolute inset-0" />
          <div
            data-testid="chat-history-drawer"
            role="dialog"
            aria-modal="true"
            aria-labelledby="chat-history-drawer-title"
            className="absolute bottom-0 left-0 top-0 flex w-[85vw] max-w-80 flex-col overflow-hidden border-r border-border/70 bg-card pt-[env(safe-area-inset-top,0px)] shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex h-12 flex-shrink-0 items-center justify-between gap-2 border-b border-border/50 px-3">
              <h2 id="chat-history-drawer-title" className="text-base font-semibold text-foreground">
                {t('chat.history.title')}
              </h2>
              <IconButton
                aria-label={chatText.historyClose}
                icon={<X className="h-4 w-4" aria-hidden="true" />}
                onClick={() => setSidebarOpen(false)}
              />
            </div>
            {sidebarContent}
          </div>
        </div>
      )}

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        isOpen={Boolean(deleteConfirmId)}
        title={t('chat.deleteDialog.title')}
        message={t('chat.deleteDialog.message')}
        confirmText={t('chat.deleteDialog.confirm')}
        cancelText={t('chat.deleteDialog.cancel')}
        isDanger
        onConfirm={confirmDelete}
        onCancel={() => setDeleteConfirmId(null)}
      />

      {/* 推送會傳到外部通知管道，先確認 */}
      <ConfirmDialog
        isOpen={sendConfirmOpen}
        title={t('chat.sendConfirm.title')}
        message={t('chat.sendConfirm.message')}
        confirmText={t('chat.sendConfirm.confirm')}
        cancelText={t('chat.deleteDialog.cancel')}
        onConfirm={() => void handleConfirmSendToNotify()}
        onCancel={() => setSendConfirmOpen(false)}
      />

      {watchlistMessage ? (
        <ToastViewport>
          <div
            role="status"
            data-testid="chat-watchlist-toast"
            className="pointer-events-auto flex items-center justify-between gap-3 rounded-xl border border-border/70 bg-card px-4 py-3 text-sm text-foreground shadow-soft-card"
          >
            <span className="min-w-0">{t(watchlistMessage.key, watchlistMessage.params)}</span>
            {watchlistMessage.undoCode ? (
              <button
                type="button"
                className="flex-shrink-0 rounded-lg px-2 py-1 text-sm font-medium text-cyan hover:bg-hover"
                disabled={isWatchlistActioning}
                onClick={() => void handleUndoWatchlistRemoval(watchlistMessage.undoCode as string)}
              >
                {chatText.undo}
              </button>
            ) : null}
          </div>
        </ToastViewport>
      ) : null}

      {/* Main chat area */}
      <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
        {shellActionsAvailable ? <ShellHeaderActions>{headerIconRow}</ShellHeaderActions> : null}
        {shellActionsAvailable ? null : embedded ? (
          <header className="mb-2 flex flex-shrink-0 items-center justify-end border-b border-border/50 pb-2">
            {headerIconRow}
          </header>
        ) : (
          <header className="mb-2 flex-shrink-0 space-y-1 border-b border-border/50 pb-2 md:mb-3 md:pb-3">
            <div className="flex items-center justify-between gap-2">
              <h1 className="flex min-w-0 items-center gap-2 text-lg font-bold text-foreground md:text-2xl">
                {historyCollapsed ? (
                  <IconButton
                    className="hidden md:inline-flex"
                    aria-label={t('chat.history.expand')}
                    icon={<PanelLeftOpen className="h-4 w-4" aria-hidden="true" />}
                    onClick={() => setHistoryCollapsed(false)}
                  />
                ) : null}
                <span className="truncate">{t('layout.route.chat.title')}</span>
                {agentStatus?.backend === 'codex_app_server' ? (
                  <Badge variant="warning" size="sm">{t('chat.codexBackendBadge')}</Badge>
                ) : null}
              </h1>
              {headerIconRow}
            </div>
            <p className="hidden text-sm text-secondary-text md:block">
              {t(agentStatus?.backend === 'codex_app_server' ? 'chat.introCodex' : 'chat.introDefault')}
            </p>
          </header>
        )}

        {/* 狀態提示集中在訊息區上方，輸入卡只放輸入相關的東西 */}
        <div data-testid="chat-status-region" className="mb-2 flex-shrink-0 space-y-2 empty:hidden">
          {agentStatus?.backend === 'codex_app_server' ? (
            <InlineAlert
              variant="warning"
              title={t('chat.codexLimitedTitle')}
              message={t('chat.codexLimitedMessage')}
              action={(
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => navigate('/settings?category=agent')}
                >
                  {t('chat.codexChangeBackend')}
                </Button>
              )}
              className="rounded-xl px-3 py-2 text-xs shadow-none"
            />
          ) : null}
          {sendToast ? (
            <InlineAlert
              variant={sendToast.type === 'success' ? 'success' : 'danger'}
              title={sendToast.type === 'success' ? t('chat.sendSuccessTitle') : t('chat.sendFailed')}
              message={sendToast.message}
              className="max-w-md rounded-xl px-3 py-2 text-xs shadow-none"
            />
          ) : null}
          {staleSince && lastUserMessage ? (
            <InlineAlert
              variant="info"
              message={t('chat.stale.message', { date: formatDayLabel(staleSince, intlLocale) })}
              action={(
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!agentAvailable}
                  onClick={() => void handleSend(lastUserMessage.content)}
                >
                  {t('chat.stale.rerun')}
                </Button>
              )}
              className="rounded-xl px-3 py-2 text-xs shadow-none"
            />
          ) : null}
          {chatError ? <ApiErrorAlert error={chatError} /> : null}
          {chatError?.code === 'session_state_conflict' && (
            <Button variant="secondary" size="sm" onClick={() => void refreshSession()}>
              {t('chat.refreshSession')}
            </Button>
          )}
          {terminalStatus === 'cancelled' ? (
            <div role="status" className="rounded-xl border border-slate-500/20 bg-slate-500/5 px-4 py-3 text-sm">
              {t('chat.analysisStopped')}
            </div>
          ) : null}
          {terminalStatus === 'timeout' ? (
            <div role="status" className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm">
              {t('chat.analysisTimedOut')}
            </div>
          ) : null}
          {stopError ? (
            <div role="alert" className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm">
              {t('chat.stopRequestFailed')}
            </div>
          ) : null}
          {agentUnavailableError ? (
            <div className="space-y-2">
              <ApiErrorAlert
                error={agentUnavailableError}
                actionLabel={t('chat.openAgentSettings')}
                onAction={() => navigate('/settings?category=agent')}
              />
              <Button variant="secondary" size="sm" onClick={() => void loadAgentStatus()}>
                {t('chat.recheckAgentStatus')}
              </Button>
            </div>
          ) : null}
          {agentStatusError ? (
            <InlineAlert
              variant="warning"
              title={t('chat.statusUnavailableTitle')}
              message={t('chat.statusUnavailableMessage')}
              action={(
                <Button variant="secondary" size="sm" onClick={() => void loadAgentStatus()}>
                  {t('chat.recheckAgentStatus')}
                </Button>
              )}
              className="rounded-xl px-3 py-2 text-xs shadow-none"
            />
          ) : null}
          {agentStatusChecking ? (
            <InlineAlert
              variant="info"
              title={t('chat.statusCheckingTitle')}
              message={t('chat.statusCheckingMessage')}
              className="rounded-xl px-3 py-2 text-xs shadow-none"
            />
          ) : null}
          {isFollowUpContextLoading ? (
            <InlineAlert
              variant="info"
              title={t('chat.followUpLoadingTitle')}
              message={t('chat.followUpLoadingMessage')}
              className="rounded-xl px-3 py-2 text-xs shadow-none"
            />
          ) : null}
        </div>

        <div className="relative z-10 flex min-h-0 flex-1 flex-col overflow-hidden">
          {/* Messages */}
          <div className="relative flex min-h-0 flex-1 flex-col">
            <ScrollArea
              className="relative z-10 flex-1 [mask-image:linear-gradient(to_bottom,transparent_0,black_1rem)]"
              viewportRef={messagesViewportRef}
              onScroll={handleMessagesScroll}
              viewportClassName="px-1 py-3 md:px-4"
              testId="chat-message-scroll"
            >
              <div data-testid="chat-message-column" className="mx-auto w-full max-w-[760px] space-y-5">
                {messages.length === 0 && !loading ? (
                  <div className="flex h-full items-center justify-center">
                    <EmptyState
                      title={t('chat.emptyTitle')}
                      description={t(
                        agentStatus?.backend === 'codex_app_server'
                          ? 'chat.emptyDescriptionCodex'
                          : 'chat.emptyDescriptionDefault',
                      )}
                      className="max-w-2xl border-dashed bg-card/55"
                      action={(
                        <div data-testid="chat-empty-shortcuts" className="max-w-lg space-y-3 text-center">
                          {holdingShortcuts.length > 0
                            ? renderEmptyGroup(t('chat.empty.holdings'), holdingShortcuts.map(renderStockShortcut))
                            : null}
                          {watchlistShortcuts.length > 0
                            ? renderEmptyGroup(t('chat.empty.watchlist'), watchlistShortcuts.map(renderStockShortcut))
                            : null}
                          {renderEmptyGroup(t('chat.empty.market'), MARKET_PROMPT_KEYS.map((key) => (
                            <button
                              key={key}
                              type="button"
                              onClick={() => fillInput(t(key), null)}
                              className="quick-question-btn"
                            >
                              {t(key)}
                            </button>
                          )))}
                        </div>
                      )}
                    />
                  </div>
                ) : (
                  messages.map((msg, index) => {
                    const skillLabel = getMessageSkillLabel(msg);
                    const previous = messages[index - 1];
                    const hasTime = isValidTimestamp(msg.createdAt);
                    const showDaySeparator = hasTime && (
                      !isValidTimestamp(previous?.createdAt)
                      || new Date(previous.createdAt as string).toDateString() !== new Date(msg.createdAt as string).toDateString()
                    );
                    const isLastAssistant = msg.id === lastAssistantId;
                    const followUps = isLastAssistant && !loading ? msg.structured?.follow_ups ?? [] : [];
                    return (
                      <React.Fragment key={msg.id}>
                        {showDaySeparator ? (
                          <div data-testid="chat-day-separator" className="flex items-center gap-3 text-xs text-muted-text">
                            <span className="h-px flex-1 bg-border/50" />
                            {formatDayLabel(msg.createdAt as string, intlLocale)}
                            <span className="h-px flex-1 bg-border/50" />
                          </div>
                        ) : null}
                        {msg.role === 'user' ? (
                          <div className="flex flex-col items-end gap-1">
                            <div className="chat-bubble-user min-w-0 max-w-[85%] overflow-hidden px-4 py-2.5">
                              {msg.content.split('\n').map((line, i) => (
                                <p key={i} className="mb-1 last:mb-0 leading-relaxed">
                                  {line || ' '}
                                </p>
                              ))}
                            </div>
                            {hasTime ? (
                              <time className="text-[11px] text-muted-text">{formatTimeLabel(msg.createdAt as string, intlLocale)}</time>
                            ) : null}
                          </div>
                        ) : (
                          <div data-testid="chat-assistant-message" className="group/message w-full min-w-0">
                            {(skillLabel || msg.backend === 'codex_app_server') && (
                              <div className="mb-2 flex flex-wrap gap-2">
                                {skillLabel ? (
                                  <Badge variant="info" className="chat-skill-badge shadow-none" aria-label={t('chat.skillBadge', { skill: skillLabel })}>
                                    {skillLabel}
                                  </Badge>
                                ) : null}
                                {msg.backend === 'codex_app_server' ? (
                                  <Badge variant="warning" size="sm">{t('chat.codexBackendBadge')}</Badge>
                                ) : null}
                              </div>
                            )}
                            {/* 新問題失敗時，最後一則回答還是上一檔的；不能掛到目前標的上。 */}
                            {isLastAssistant && activeStockContext && (!msg.stockCode || msg.stockCode === activeStockContext.stock_code) ? (
                              <ChatStockSummaryCard
                                stock={activeStockContext}
                                quote={activeQuote}
                                structured={msg.structured}
                                {...(activeStockContext.asset_type === 'stock'
                                  ? {
                                      inWatchlist: stockInWatchlist(activeStockContext.stock_code),
                                      watchlistPending: isWatchlistActioning,
                                      onToggleWatchlist: () => void handleToggleWatchlist(activeStockContext.stock_code),
                                    }
                                  : {})}
                              />
                            ) : null}
                            {renderThinkingBlock(msg)}
                            {expandedThinking.has(msg.id) && msg.thinkingSteps && renderThinkingDetails(msg.thinkingSteps)}
                            <div className="chat-prose">
                              <Markdown remarkPlugins={[remarkGfm]}>
                                {msg.content}
                              </Markdown>
                            </div>
                            <div className="mt-2 flex flex-wrap items-center gap-2">
                              <div className="chat-message-actions">
                                <button
                                  type="button"
                                  onClick={() => copyMessageToClipboard(msg.id, msg.content)}
                                  className="chat-copy-btn"
                                  aria-label={copiedMessages.has(msg.id) ? text.copied : text.copy}
                                >
                                  {copiedMessages.has(msg.id) ? text.copied : text.copy}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => downloadMessageAsMarkdown(msg)}
                                  className="chat-copy-btn"
                                  aria-label={t('chat.exportMessageHint')}
                                >
                                  {t('chat.exportMessage')}
                                </button>
                              </div>
                              {hasTime ? (
                                <time className="text-[11px] text-muted-text">{formatTimeLabel(msg.createdAt as string, intlLocale)}</time>
                              ) : null}
                            </div>
                            {followUps.length > 0 ? (
                              <div data-testid="chat-follow-ups" className="mt-3 flex flex-wrap gap-2">
                                {followUps.map((question) => (
                                  <button
                                    key={question}
                                    type="button"
                                    className="quick-question-btn"
                                    onClick={() => fillInput(question, null)}
                                  >
                                    {question}
                                  </button>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        )}
                      </React.Fragment>
                    );
                  })
                )}

                {loading && (
                  <div data-testid="chat-loading-steps" className="w-full">
                    <div className="flex items-center gap-2.5 text-sm text-secondary-text">
                      <div className="relative w-4 h-4 flex-shrink-0">
                        <div className="absolute inset-0 rounded-full border-2 border-cyan/20" />
                        <div className="absolute inset-0 rounded-full border-2 border-cyan border-t-transparent animate-spin" />
                      </div>
                      <span className="text-secondary-text">
                        {getCurrentStage(progressSteps)}
                      </span>
                    </div>
                    {progressSteps.length > 1 ? (
                      <div className="mt-2">{renderThinkingDetails(progressSteps.slice(0, -1))}</div>
                    ) : null}
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            </ScrollArea>

            {showJumpToBottom && (
              <div className="pointer-events-none absolute bottom-3 left-1/2 z-20 -translate-x-1/2">
                <button
                  type="button"
                  className="pointer-events-auto chat-copy-btn rounded-full shadow-soft-card"
                  onClick={() => {
                    requestScrollToBottom('smooth');
                    scrollToBottom('smooth');
                  }}
                  aria-label={t('chat.jumpToLatestHint')}
                >
                  <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
                  {t('chat.newMessages')}
                </button>
              </div>
            )}
          </div>

          {/* Input card */}
          <div className="relative z-20 flex-shrink-0 pb-[env(safe-area-inset-bottom)] pt-2">
            <div
              data-testid="chat-composer"
              className="relative mx-auto w-full max-w-[760px] rounded-2xl border border-border/70 bg-card p-3 shadow-soft-card"
            >
              {/* 有標的才顯示「名稱 代號」；有對話但沒標的才提示未確認，空白頁不顯示。 */}
              {activeStockContext || messages.length > 0 ? (
                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-text">
                  <span
                    aria-label={t('chat.currentObjectLabel')}
                    className="inline-flex max-w-full truncate rounded-full border border-border/60 px-2.5 py-1"
                  >
                    {activeStockContext
                      ? `${activeStockContext.stock_name ? `${activeStockContext.stock_name} ` : ''}${activeStockContext.stock_code}`
                      : t(stateContract === 'legacy' ? 'chat.objectUnconfirmedLegacy' : 'chat.objectUnconfirmed')}
                  </span>
                </div>
              ) : null}

              {inputSuggestions.length > 0 ? (
                <ul
                  role="listbox"
                  aria-label={t('chat.suggestions.label')}
                  className="absolute bottom-full left-0 right-0 z-30 mb-1 max-h-60 overflow-auto rounded-xl border border-border/70 bg-card p-1 shadow-soft-card"
                >
                  {inputSuggestions.map((suggestion) => (
                    <li key={suggestion.canonicalCode} role="option" aria-selected={false}>
                      <button
                        type="button"
                        className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-hover"
                        // 用 mouseDown 搶在 textarea blur 之前選取，否則清單會先收掉。
                        onMouseDown={(event) => {
                          event.preventDefault();
                          handleSelectSuggestion(suggestion.canonicalCode, suggestion.nameZh);
                        }}
                      >
                        <span className="truncate text-foreground">{suggestion.nameZh}</span>
                        <span className="flex-shrink-0 text-xs text-secondary-text">{suggestion.displayCode}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}

              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                onFocus={() => setInputFocused(true)}
                onBlur={() => setInputFocused(false)}
                placeholder={t('chat.inputPlaceholder')}
                aria-label={t('chat.inputPlaceholder')}
                disabled={loading || !agentAvailable}
                rows={1}
                className="block max-h-[200px] min-h-[44px] w-full resize-none border-0 bg-transparent px-1 py-2 text-base focus:outline-none disabled:cursor-not-allowed disabled:opacity-60 md:text-sm"
                style={{ height: 'auto' }}
                onInput={(e) => {
                  const target = e.target as HTMLTextAreaElement;
                  target.style.height = 'auto';
                  target.style.height = `${Math.min(target.scrollHeight, 200)}px`;
                }}
              />

              <div className="mt-2 flex items-center justify-between gap-3">
                {skills.length > 0 ? (
                  <button
                    ref={skillTriggerRef}
                    type="button"
                    className="inline-flex h-9 min-w-0 items-center gap-2 rounded-full border border-border/70 px-3 text-sm text-foreground hover:bg-hover"
                    aria-label={skillPickerOpen ? t('chat.skillPicker.collapse') : t('chat.skillPicker.expand')}
                    aria-expanded={skillPickerOpen}
                    aria-controls="chat-skill-picker-panel"
                    onClick={toggleSkillPicker}
                  >
                    <SlidersHorizontal className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
                    <span className="truncate text-xs">{selectedSkillSummary}</span>
                    <ChevronDown
                      className={cn('h-4 w-4 flex-shrink-0 text-muted-text transition-transform', skillPickerOpen ? 'rotate-180' : '')}
                      aria-hidden="true"
                    />
                  </button>
                ) : <span />}
                {loading && agentStatus?.backend === 'codex_app_server' ? (
                  <Button
                    variant="danger"
                    onClick={stopStream}
                    disabled={stopping}
                    className="flex-shrink-0"
                  >
                    {stopping ? t('chat.stoppingAnalysis') : t('chat.stopAnalysis')}
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    onClick={() => handleSend()}
                    disabled={!input.trim() || loading || !agentAvailable}
                    isLoading={loading}
                    className="btn-primary flex-shrink-0"
                  >
                    {t('chat.send')}
                  </Button>
                )}
              </div>

              {skills.length > 0 ? createPortal(
                <>
                  {skillPickerOpen ? (
                    <div
                      data-testid="chat-skill-picker-backdrop"
                      className="page-drawer-overlay fixed inset-0 z-[60] md:bg-transparent"
                      onClick={() => setSkillPickerOpen(false)}
                    />
                  ) : null}
                  {/* 掛在 body 上避免被底部分頁列蓋住：手機是底部抽屜，桌機是觸發鈕上方的 popover。 */}
                  <div
                    id="chat-skill-picker-panel"
                    data-testid="chat-skill-picker-panel"
                    role="dialog"
                    aria-labelledby="chat-skill-picker-title"
                    style={skillAnchor ? ({
                      '--chat-skill-left': `${skillAnchor.left}px`,
                      '--chat-skill-bottom': `${skillAnchor.bottom}px`,
                    } as React.CSSProperties) : undefined}
                    className={cn(
                      skillPickerOpen ? 'flex' : 'hidden',
                      'fixed inset-x-0 bottom-0 z-[60] max-h-[80dvh] flex-col rounded-t-2xl border border-border/70 bg-card shadow-soft-card',
                      'md:inset-x-auto md:bottom-[var(--chat-skill-bottom,6rem)] md:left-[var(--chat-skill-left,1rem)] md:max-h-96 md:w-96 md:rounded-2xl',
                    )}
                  >
                    <div className="flex-shrink-0 px-4 pt-2 md:px-3 md:pt-3">
                      <div aria-hidden="true" className="mx-auto mb-2 h-1 w-10 rounded-full bg-border md:hidden" />
                      <div className="flex items-center justify-between gap-2">
                        <h2 id="chat-skill-picker-title" className="text-sm font-semibold text-foreground">
                          {chatText.skillSheetTitle}
                        </h2>
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            className="rounded-lg px-2 py-1 text-xs text-secondary-text hover:bg-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                            disabled={selectedSkillIds.length === 0}
                            onClick={() => setSelectedSkillIds([])}
                          >
                            {chatText.skillClear}
                          </button>
                          <Button variant="primary" size="sm" onClick={closeSkillPicker}>
                            {chatText.skillDone}
                          </Button>
                        </div>
                      </div>
                    </div>
                    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 pb-[calc(1rem+56px+env(safe-area-inset-bottom))] pt-3 md:px-3 md:pb-3">
                      {skillGroups.map((group) => (
                        <div key={group.id} className="space-y-1.5">
                          {group.name ? <p className="text-xs text-muted-text">{group.name}</p> : null}
                          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                            {group.items.map((s) => {
                              const checked = selectedSkillIdSet.has(s.id);
                              const disabled = !checked && skillLimitReached;
                              const displayName = getSkillDisplayName(s, language);
                              return (
                                <label
                                  key={s.id}
                                  className={`group relative flex cursor-pointer items-center gap-1.5 ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}
                                  onMouseEnter={() => setShowSkillDesc(s.id)}
                                  onMouseLeave={() => setShowSkillDesc(null)}
                                >
                                  <input
                                    type="checkbox"
                                    name="skills"
                                    value={s.id}
                                    checked={checked}
                                    disabled={disabled}
                                    onChange={() => toggleSkillSelection(s.id)}
                                    className="chat-skill-checkbox"
                                  />
                                  <span className={`text-sm transition-colors ${checked ? 'font-medium text-foreground' : 'text-secondary-text group-hover:text-foreground'}`}>
                                    {displayName}
                                  </span>
                                  {showSkillDesc === s.id && s.description && (
                                    <div className="skill-desc-tooltip">
                                      <p className="skill-title">{displayName}</p>
                                      <p>{s.description}</p>
                                    </div>
                                  )}
                                </label>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </>,
                document.body,
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ChatPage;
