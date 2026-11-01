import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Bookmark,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Clock3,
  Play,
  RefreshCw,
  Search,
  Star,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { analysisApi } from '../api/analysis';
import {
  screeningApi,
  type ScreeningCandidate,
  type ScreeningCondition,
  type ScreeningExplanationItem,
  type ScreeningHotspotDetail,
  type ScreeningHotspot,
  type ScreeningHotspotsResponse,
  type ScreeningRunSummary,
  type ScreeningScreenResponse,
  type ScreeningScreenTaskStatus,
  type ScreeningStrategy,
} from '../api/screening';
import { formatParsedApiError, getParsedApiError, toApiErrorMessage, type ParsedApiError } from '../api/error';
import { systemConfigApi } from '../api/systemConfig';
import {
  AppPage,
  Button,
  Change,
  DataTable,
  Drawer,
  IconButton,
  InlineAlert,
  Num,
  PageHeader,
  Segmented,
  Select,
  type DataTableColumn,
  type SortState,
} from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { getIntlLocale } from '../i18n/intlLocale';
import type { UiLanguage, UiTextKey, UiTextParams } from '../i18n/uiText';
import { buildDecisionActionLabelMap } from '../utils/decisionAction';
import { NO_VALUE, formatNumber as formatGroupedNumber } from '../utils/format';
import { formatSignalText } from '../utils/signalText';
import { findMatchingStockCode } from '../utils/stockCode';

type Translate = (key: UiTextKey, params?: UiTextParams) => string;
type FormMarket = 'tw' | 'us';

const FORM_MARKETS: FormMarket[] = ['tw', 'us'];
const DEFAULT_MARKET: FormMarket = 'tw';
const DEFAULT_STRATEGY = 'momentum_quality';
const MAX_RESULT_OPTIONS = [3, 5, 10, 20] as const;
const MARKET_CURRENCY: Record<string, string> = { tw: 'TWD', us: 'USD' };
const SCREEN_TASK_STORAGE_KEY = 'dsa.screening.activeScreenTask.v1';
const SCREEN_TASK_POLL_INTERVAL_MS = 2000;

const isFormMarket = (value: string | undefined | null): value is FormMarket =>
  value === 'tw' || value === 'us';

const STRATEGY_CATEGORY_KEYS: Record<string, UiTextKey> = {
  framework: 'screeningPage.category.framework',
  income: 'screeningPage.category.income',
  momentum: 'screeningPage.category.momentum',
  quality: 'screeningPage.category.quality',
  reversal: 'screeningPage.category.reversal',
  trend: 'screeningPage.category.trend',
  value: 'screeningPage.category.value',
};

const formatStrategyCategory = (value: string | undefined, t: Translate) => {
  const normalized = value?.trim();
  if (!normalized) {
    return '';
  }
  const key = STRATEGY_CATEGORY_KEYS[normalized.toLowerCase()];
  return key ? t(key) : normalized;
};

const getStrategyName = (item: ScreeningStrategy, language: UiLanguage) =>
  (language === 'zh-TW' ? item.nameZhTw : '') || item.name || item.title || item.id;

const getStrategyDescription = (item: ScreeningStrategy, language: UiLanguage) =>
  (language === 'zh-TW' ? item.descriptionZhTw : '') || item.description || '';

const supportsMarket = (item: ScreeningStrategy, market: string) =>
  !item.marketScope?.length || item.marketScope.includes(market);

const getStrategyConditions = (item: ScreeningStrategy, market: string): ScreeningCondition[] =>
  item.marketConditions?.[market] ?? item.conditions ?? [];

const formatConditionValue = (condition: ScreeningCondition, t: Translate): string => {
  const { value, unit } = condition;
  if (value === true) {
    return '';
  }
  const text = Array.isArray(value)
    ? value.map(String).join(t('screeningPage.listSeparator'))
    : typeof value === 'number'
      ? formatGroupedNumber(value)
      : String(value ?? '');
  return unit ? `${text} ${unit}` : text;
};

type PersistedScreenTask = {
  taskId: string;
  runId?: string;
  market: string;
  strategy: string;
  maxResults: number;
};

type ResultContext = {
  market: string;
  strategy: string;
  maxResults?: number;
};

const formatRunCreatedAt = (value: string | null | undefined, locale: string, t: Translate) => {
  if (!value) {
    return t('screeningPage.timeUnknown');
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString(locale, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
};

const formatMarketLabel = (marketId: string | null | undefined, t: Translate): string => {
  if (marketId === 'tw') return t('screeningPage.market.tw');
  if (marketId === 'us') return t('screeningPage.market.us');
  if (marketId === 'cn') return t('screeningPage.market.cn');
  return marketId || NO_VALUE;
};

const readPersistedScreenTask = (): PersistedScreenTask | null => {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    const raw = window.sessionStorage.getItem(SCREEN_TASK_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<PersistedScreenTask>;
    if (typeof parsed.taskId !== 'string' || !parsed.taskId.trim()) {
      return null;
    }
    const restoredMaxResults = Number(parsed.maxResults);
    return {
      taskId: parsed.taskId,
      runId: typeof parsed.runId === 'string' && parsed.runId.trim() ? parsed.runId : undefined,
      market: typeof parsed.market === 'string' && parsed.market.trim() ? parsed.market : DEFAULT_MARKET,
      strategy: typeof parsed.strategy === 'string' && parsed.strategy.trim() ? parsed.strategy : DEFAULT_STRATEGY,
      maxResults: Number.isFinite(restoredMaxResults) ? Math.min(100, Math.max(1, restoredMaxResults)) : 3,
    };
  } catch {
    return null;
  }
};

const persistScreenTask = (task: PersistedScreenTask) => {
  try {
    window.sessionStorage.setItem(SCREEN_TASK_STORAGE_KEY, JSON.stringify(task));
  } catch {
    // Session storage is best-effort; polling still works while the page stays mounted.
  }
};

const clearPersistedScreenTask = () => {
  try {
    window.sessionStorage.removeItem(SCREEN_TASK_STORAGE_KEY);
  } catch {
    // Ignore storage cleanup failures.
  }
};

const isUnrecoverableScreenTaskError = (error: ParsedApiError) =>
  // 這個標題是 api/error.ts 產生的分類結果，不是畫面文案。
  error.title === '选股任务不可恢复';

const formatRecoverableScreenTaskPollingError = (error: ParsedApiError, t: Translate) => {
  if (error.category === 'upstream_timeout') {
    return t('screeningPage.poll.timeout');
  }
  if (error.category === 'upstream_network' || error.category === 'local_connection_failed') {
    return t('screeningPage.poll.network');
  }
  return formatParsedApiError(error) || t('screeningPage.poll.unknown');
};

const toFiniteNumber = (value: unknown): number | null => {
  if (value == null || value === '' || Number.isNaN(Number(value))) {
    return null;
  }
  return Number(value);
};

const formatNumber = (value: unknown, digits = 2) => {
  const parsed = toFiniteNumber(value);
  return parsed === null ? NO_VALUE : parsed.toFixed(digits);
};

const formatAmount = (value: unknown, t: Translate) => {
  const amount = toFiniteNumber(value);
  if (amount === null) {
    return NO_VALUE;
  }
  if (Math.abs(amount) >= 100_000_000) {
    return `${(amount / 100_000_000).toFixed(2)} ${t('screeningPage.unit.yi')}`;
  }
  if (Math.abs(amount) >= 10_000) {
    return `${(amount / 10_000).toFixed(2)} ${t('screeningPage.unit.wan')}`;
  }
  return amount.toFixed(2);
};

const formatRatioPercent = (value: unknown) => {
  const parsed = toFiniteNumber(value);
  return parsed === null ? NO_VALUE : `${(parsed * 100).toFixed(0)}%`;
};

const FACTOR_KEYS: Record<string, UiTextKey> = {
  value: 'screeningPage.factor.value',
  liquidity: 'screeningPage.factor.liquidity',
  momentum: 'screeningPage.factor.momentum',
  reversal: 'screeningPage.factor.reversal',
  activity: 'screeningPage.factor.activity',
  stability: 'screeningPage.factor.stability',
  size: 'screeningPage.factor.size',
  theme_heat: 'screeningPage.factor.themeHeat',
  topic_alignment: 'screeningPage.factor.topicAlignment',
};

const HOTSPOT_QUALITY_KEYS: Record<string, UiTextKey> = {
  available: 'screeningPage.hotspot.quality.available',
  failed: 'screeningPage.hotspot.quality.failed',
  partial: 'screeningPage.hotspot.quality.partial',
  stale: 'screeningPage.hotspot.quality.stale',
};

const HOTSPOT_STAGE_KEYS: Record<string, UiTextKey> = {
  accelerating: 'screeningPage.hotspot.stage.accelerating',
  cooling: 'screeningPage.hotspot.stage.cooling',
  diverging: 'screeningPage.hotspot.stage.diverging',
  initial: 'screeningPage.hotspot.stage.initial',
  persistent_hot: 'screeningPage.hotspot.stage.spreading',
  warming: 'screeningPage.hotspot.stage.spreading',
  weakening: 'screeningPage.hotspot.stage.cooling',
};

const HOTSPOT_ROLE_KEYS: Record<string, UiTextKey> = {
  core_leader: 'screeningPage.hotspot.role.leader',
  follower: 'screeningPage.hotspot.role.follower',
  laggard: 'screeningPage.hotspot.role.laggard',
  leader: 'screeningPage.hotspot.role.leader',
  secondary: 'screeningPage.hotspot.role.secondary',
};

const HOTSPOT_MISSING_FIELD_KEYS: Record<string, UiTextKey> = {
  canonical_topic: 'screeningPage.hotspot.missing.canonicalTopic',
  hotspot_constituents: 'screeningPage.hotspot.missing.stocks',
  leader_stocks: 'screeningPage.hotspot.missing.leaderStocks',
  live_stocks: 'screeningPage.hotspot.missing.liveStocks',
  route: 'screeningPage.hotspot.missing.route',
  source: 'screeningPage.hotspot.missing.source',
  stocks: 'screeningPage.hotspot.missing.stocks',
  timeline: 'screeningPage.hotspot.missing.timeline',
};

const EXPLANATION_SOURCE_KEYS: Record<string, UiTextKey> = {
  screening: 'screeningPage.source.screening',
  llm: 'screeningPage.source.llm',
  realtime_quote: 'screeningPage.source.realtimeQuote',
  legacy_result: 'screeningPage.source.legacy',
  unknown: 'screeningPage.quality.unknown',
};

const EXPLANATION_QUALITY_KEYS: Record<string, UiTextKey> = {
  observed: 'screeningPage.quality.observed',
  inferred: 'screeningPage.quality.inferred',
  unknown: 'screeningPage.quality.unknown',
  ok: 'screeningPage.quality.ok',
  partial: 'screeningPage.quality.partial',
};

const UNIVERSE_SOURCE_KEYS: Record<string, UiTextKey> = {
  sp500: 'screeningPage.universe.sp500',
  env: 'screeningPage.universe.env',
  default: 'screeningPage.universe.default',
};

const lookupLabel = (map: Record<string, UiTextKey>, value: unknown, t: Translate): string | null => {
  const key = map[String(value ?? '').trim().toLowerCase()];
  return key ? t(key) : null;
};

const getHotspotStageLabel = (value: unknown, t: Translate) => {
  const text = String(value || '').trim();
  if (!text) {
    return '';
  }
  return lookupLabel(HOTSPOT_STAGE_KEYS, text, t) || text;
};

const getHotspotRoleLabel = (value: unknown, t: Translate) => {
  const text = String(value || '').trim();
  if (!text) {
    return t('screeningPage.hotspot.role.default');
  }
  return lookupLabel(HOTSPOT_ROLE_KEYS, text, t) || text;
};

const getHotspotQualityLabel = (value: unknown, t: Translate) =>
  lookupLabel(HOTSPOT_QUALITY_KEYS, value, t) || t('screeningPage.hotspot.quality.pending');

const getCandidateReason = (item: ScreeningCandidate, t: Translate) => {
  if (item.llmThesis || item.llmScore != null) {
    return item.reason || item.llmThesis || t('screeningPage.detail.llmRanked');
  }
  if (item.reason) {
    return item.reason;
  }
  const summaries = item.postAnalysisSummaries || {};
  const summary = Object.values(summaries).find((value) => typeof value === 'string' && value.trim());
  if (typeof summary === 'string') {
    return summary;
  }
  return t('screeningPage.detail.noSummary');
};

// 引擎沒給動作就不顯示，不用「觀察」假裝有訊號；動作依枚舉查詞彙表。
const getSignal = (item: ScreeningCandidate, t: Translate): string | null => {
  const rawSignal = item.raw?.action ?? item.raw?.signal ?? item.raw?.recommendation;
  if (typeof rawSignal !== 'string' || !rawSignal.trim()) {
    return null;
  }
  const labels: Record<string, string> = buildDecisionActionLabelMap(t);
  return labels[rawSignal.trim().toLowerCase()] ?? rawSignal;
};

const getFactorEntries = (item: ScreeningCandidate) =>
  Object.entries(item.factorScores || {})
    .filter(([, value]) => typeof value === 'number')
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 6);

const getSelectionExplanations = (item: ScreeningCandidate, t: Translate): ScreeningExplanationItem[] => {
  if (item.whySelected?.length) return item.whySelected;
  // Legacy runs lack provenance. Retain every stored summary as unknown rather
  // than re-scoring historical factors or asserting it was observed.
  const summaries = Array.from(new Set(
    [item.reason, item.llmThesis, ...Object.values(item.postAnalysisSummaries || {})]
      .filter((value): value is string => typeof value === 'string' && Boolean(value.trim()))
      .map((value) => value.trim()),
  ));
  return summaries.map((summary) => ({
    code: 'legacy_summary',
    text: t('screeningPage.detail.legacySummary', { summary }),
    source: 'legacy_result',
    quality: 'unknown',
  }));
};

const ExplanationItems = ({ items, emptyText, t }: { items?: ScreeningExplanationItem[]; emptyText: string; t: Translate }) => (
  items?.length ? (
    <ul className="mt-2 space-y-2">
      {items.map((item, index) => (
        <li key={`${item.code}-${item.source}-${index}`} className="rounded-lg border border-border/50 bg-background/30 p-2">
          <p className="text-sm leading-6 text-foreground">{item.text}</p>
          <p className="mt-1 text-xs text-secondary-text">
            {t('screeningPage.detail.provenance', {
              source: lookupLabel(EXPLANATION_SOURCE_KEYS, item.source, t) || item.source || t('screeningPage.quality.unknown'),
              quality: lookupLabel(EXPLANATION_QUALITY_KEYS, item.quality, t) || item.quality || t('screeningPage.quality.unknown'),
            })}
          </p>
        </li>
      ))}
    </ul>
  ) : <p className="mt-1 text-sm leading-6 text-foreground">{emptyText}</p>
);

const toMessageList = (values: string[] | undefined) =>
  Array.isArray(values) ? values.map((value) => String(value).trim()).filter(Boolean) : [];

const KNOWN_SNAPSHOT_SOURCES = new Set(['tushare', 'sina', 'efinance', 'akshare_em', 'em_datacenter', 'baostock']);
const MAX_MESSAGE_DETAIL_LENGTH = 96;

const truncateMessageDetail = (value: string, maxLength = MAX_MESSAGE_DETAIL_LENGTH) => {
  const text = value.replace(/\s+/g, ' ').trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength - 1)}…`;
};

const summarizeScreeningDiagnostic = (detail: string, t: Translate) => {
  if (/no_json_found|invalid_response|coverage below threshold/i.test(detail)) {
    return t('screeningPage.diag.noStructured');
  }
  if (/call_failed/i.test(detail)) {
    return t('screeningPage.diag.callFailed');
  }
  if (/trade_cal returned no open trading days/i.test(detail)) {
    return t('screeningPage.diag.noTradingDay');
  }
  if (/too many requests|rate limit|http\s*429/i.test(detail)) {
    return t('screeningPage.diag.rateLimited');
  }
  if (/403 forbidden|forbidden|access denied/i.test(detail)) {
    return t('screeningPage.diag.forbidden');
  }
  if (/timeout|timed out/i.test(detail)) {
    return t('screeningPage.diag.timeout');
  }
  if (/RemoteDisconnected|Connection aborted|ProtocolError|ConnectionPool|Max retries exceeded|ProxyError|NameResolutionError/i.test(detail)) {
    return t('screeningPage.diag.network');
  }
  if (/missing .*api key|GEMINI_API_KEY|GOOGLE_API_KEY|gemini_api_key/i.test(detail)) {
    return t('screeningPage.diag.noApiKey');
  }
  if (/returned no data|empty/i.test(detail)) {
    return t('screeningPage.diag.noData');
  }

  const withoutUrl = detail
    .replace(/https?:\/\/\S+/gi, 'URL')
    .replace(/\bwith url:\s*\S+/gi, 'with url: URL')
    .replace(/\burl:\s*\S+/gi, 'url: URL');
  return truncateMessageDetail(withoutUrl);
};

const parseSourceDiagnostic = (value: string) => {
  const match = value.match(/^([a-zA-Z0-9_-]+)\s*[:：]\s*(.+)$/);
  if (!match) {
    return null;
  }
  return {
    source: match[1],
    detail: match[2],
  };
};

const normalizeScreenMessageKey = (value: string, t: Translate) => {
  const formatted = formatScreenMessage(value, t);
  return formatted ? formatted.trim().toLowerCase() : value.trim().toLowerCase();
};

const formatEnrichmentSummary = (value: string, t: Translate) =>
  value
    .replace(/DSA行情\s*[:：]\s*/gi, t('screeningPage.enrich.quote'))
    .replace(/DSA新闻\s*[:：]\s*/gi, t('screeningPage.enrich.news'))
    .replace(/DSA事件\s*[:：]\s*/gi, t('screeningPage.enrich.events'));

const formatScreenMessage = (value: string, t: Translate) => {
  if (/^DSA provider context applied \d+ of \d+ candidates/i.test(value)) {
    return '';
  }
  const universeFallback = value.match(/^US universe fallback:\s*(.*)$/i);
  if (universeFallback) {
    return t('screeningPage.universe.fallback', {
      source: lookupLabel(UNIVERSE_SOURCE_KEYS, universeFallback[1], t) || t('screeningPage.quality.unknown'),
    });
  }
  if (/^LLM ranking skipped:\s*no LLM config/i.test(value)) {
    return t('screeningPage.msg.noLlmConfig');
  }
  if (/^LLM ranking failed/i.test(value) || /no_json_found|invalid_response|coverage below threshold|call_failed/i.test(value)) {
    return t('screeningPage.msg.llmFailed', { reason: summarizeScreeningDiagnostic(value, t) });
  }
  if (/^(?:LLM ranking prompt|LLM context) truncated:/i.test(value)) {
    return '';
  }
  if (/^(?:Remote post-analysis cap|Risk veto excluded|Snapshot hard-filter waterfall|Daily hard-filter waterfall|Daily hard-filter rejections|Candidate context collected rows=)/i.test(value)) {
    return '';
  }
  if (/^Daily K-line (?:enrichment attempted|sources|quality flags|source ordering|source health):?/i.test(value)) {
    return '';
  }
  if (/^Daily K-line enrichment row errors:/i.test(value)) {
    return t('screeningPage.msg.dailyRowErrors');
  }
  if (/^Daily K-line enrichment skipped:/i.test(value)) {
    return t('screeningPage.msg.dailySkipped');
  }
  if (/^Candidate context row errors:/i.test(value)) {
    return t('screeningPage.msg.contextErrors');
  }
  if (/^Industry\/concepts enrichment:/i.test(value)) {
    return t('screeningPage.msg.industryErrors');
  }
  if (/^DSA deep analysis failed for /i.test(value)) {
    return t('screeningPage.msg.deepFailed');
  }

  const snapshotFallback = value.match(/^Snapshot source fallback:\s*(.+)$/i);
  if (snapshotFallback) {
    const parsed = parseSourceDiagnostic(snapshotFallback[1]);
    if (parsed) {
      return t('screeningPage.msg.sourceFallback', { source: parsed.source, reason: summarizeScreeningDiagnostic(parsed.detail, t) });
    }
    return t('screeningPage.msg.sourceFallbackPlain', { reason: summarizeScreeningDiagnostic(snapshotFallback[1], t) });
  }

  const parsed = parseSourceDiagnostic(value);
  if (parsed && KNOWN_SNAPSHOT_SOURCES.has(parsed.source.toLowerCase())) {
    return t('screeningPage.msg.sourceFallback', { source: parsed.source, reason: summarizeScreeningDiagnostic(parsed.detail, t) });
  }
  return truncateMessageDetail(value);
};

const getScreenMessages = (meta: ScreeningScreenResponse | null, t: Translate) => {
  if (!meta) {
    return [];
  }
  const messages: string[] = [];
  const seen = new Set<string>();
  [...toMessageList(meta.warnings), ...toMessageList(meta.sourceErrors), ...toMessageList(meta.llmParseErrors)].forEach(
    (value) => {
      const key = normalizeScreenMessageKey(value, t);
      if (seen.has(key)) {
        return;
      }
      const message = formatScreenMessage(value, t);
      if (!message) {
        return;
      }
      seen.add(key);
      messages.push(message);
    },
  );
  return messages;
};

const isRunningScreenTask = (status: string | undefined | null) => status === 'pending' || status === 'processing';

const formatScreenTaskFailure = (value: string | null | undefined, t: Translate) => {
  const text = String(value || '').trim();
  if (!text) {
    return t('screeningPage.taskFailed');
  }
  return t('screeningPage.taskFailedWith', { reason: summarizeScreeningDiagnostic(text, t) });
};

const SCREENING_HOTSPOT_NO_CACHE_HINT = 'No cached Screening hotspot snapshot. Click refresh to fetch live hotspots.';
const SCREENING_HOTSPOT_UNAVAILABLE_CODE = 'eastmoney_hotspot_unavailable';

const formatHotspotEmptyMessage = (result: ScreeningHotspotsResponse, market: string, t: Translate) => {
  const message = String(result.message || '').trim();
  const sourceErrors = result.sourceErrors || [];
  if (message === SCREENING_HOTSPOT_NO_CACHE_HINT) {
    return t('screeningPage.hotspot.noCache');
  }
  // 台股、美股沒有熱點來源，後端會回固定說明，直接照實顯示。
  if (message && (market !== 'cn' || sourceErrors.includes(SCREENING_HOTSPOT_UNAVAILABLE_CODE))) {
    return message;
  }
  const sourceError = sourceErrors[0];
  if (sourceError) {
    return t('screeningPage.hotspot.noDataWith', { reason: summarizeScreeningDiagnostic(sourceError, t) });
  }
  return t('screeningPage.hotspot.noData');
};

const ScreenAlertMessage: React.FC<{ messages: string[] }> = ({ messages }) => {
  if (messages.length <= 1) {
    return <span>{messages[0]}</span>;
  }
  return (
    <ul className="list-disc space-y-1 pl-4">
      {messages.map((message) => (
        <li key={message}>{message}</li>
      ))}
    </ul>
  );
};

const hasLlmInsight = (item: ScreeningCandidate) =>
  Boolean(
    item.llmThesis ||
      item.llmSector ||
      item.llmTheme ||
      item.llmConfidence != null ||
      item.llmWatchItems?.length ||
      item.llmCatalysts?.length,
  );

const getRiskClassName = (riskLevel: string | undefined) => {
  if (riskLevel === 'high') {
    return 'bg-danger/10 text-danger';
  }
  if (riskLevel === 'medium') {
    return 'bg-warning/10 text-warning';
  }
  return 'bg-surface text-secondary-text';
};

const getRiskLabel = (riskLevel: string | undefined, t: Translate) => {
  if (riskLevel === 'high') return t('screeningPage.risk.high');
  if (riskLevel === 'medium') return t('screeningPage.risk.medium');
  if (riskLevel === 'low') return t('screeningPage.risk.low');
  return t('screeningPage.risk.pending');
};

const getRouteTimeLabel = (item: ScreeningHotspotDetail['route'][number], locale: string, t: Translate) => {
  const rawTime = item.publishedAt || item.date || item.time || '';
  if (!rawTime) {
    return t('screeningPage.hotspot.timePending');
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(rawTime)) {
    return rawTime;
  }
  const parsed = new Date(rawTime);
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleString(locale, {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  }
  return rawTime;
};

const formatHotspotRouteTitle = (value: string, t: Translate) => {
  const text = String(value || '').trim();
  const normalized = text.toLowerCase();
  if (normalized === 'current fermentation') {
    return t('screeningPage.hotspot.currentFermentation');
  }
  if (normalized === 'news catalyst') {
    return t('screeningPage.hotspot.newsCatalyst');
  }
  return text || t('screeningPage.hotspot.change');
};

const formatHotspotRouteDescription = (value: string, t: Translate) => {
  const text = String(value || '').trim();
  if (!text) {
    return t('screeningPage.hotspot.noMoreInfo');
  }
  const parts = text.split(/\s*;\s*/).map((part) => part.trim()).filter(Boolean);
  if (parts.some((part) => /\b(?:heat|stage|leaders?)\b/i.test(part))) {
    const listSeparator = t('screeningPage.listSeparator');
    const localized = parts.map((part) => {
      const heat = part.match(/^(.*?)\s+heat\s+(-?\d+(?:\.\d+)?)$/i);
      if (heat) {
        return t('screeningPage.hotspot.topicHeat', { topic: heat[1], value: formatNumber(heat[2], 1) });
      }
      const stage = part.match(/^stage\s+(.+)$/i);
      if (stage) {
        return t('screeningPage.hotspot.stageIs', { stage: getHotspotStageLabel(stage[1], t) });
      }
      const leaders = part.match(/^leaders?\s+(.+)$/i);
      if (leaders) {
        return t('screeningPage.hotspot.leadersAre', { leaders: leaders[1].split(/\s*,\s*/).filter(Boolean).join(listSeparator) });
      }
      return part;
    });
    return t('screeningPage.hotspot.sentence', { parts: localized.join(t('screeningPage.clauseSeparator')) });
  }
  if (/Dsa[A-Z]|Provider\b|stock_board_|concept_constituents|leader_stocks|last_good_cache/i.test(text)) {
    return t('screeningPage.hotspot.dataChanged');
  }
  return text;
};

const getHotspotMissingFieldLabels = (values: string[] | undefined, t: Translate) => {
  const labels = (values || []).map((value) => lookupLabel(HOTSPOT_MISSING_FIELD_KEYS, value, t) || t('screeningPage.hotspot.missing.partial'));
  return [...new Set(labels)];
};

const formatHotspotDiagnostic = (value: string, t: Translate) => {
  const text = String(value || '').trim();
  const timeoutSeconds = text.match(/timed out after\s*(\d+(?:\.\d+)?)s/i);
  if (timeoutSeconds) {
    return t('screeningPage.hotspot.diag.timeoutSeconds', { seconds: timeoutSeconds[1] });
  }
  if (/timeout|timed out/i.test(text)) {
    return t('screeningPage.hotspot.diag.timeout');
  }
  if (/RemoteDisconnected|Connection aborted|ProtocolError|ConnectionPool|Max retries exceeded|ProxyError|NameResolutionError/i.test(text)) {
    return t('screeningPage.hotspot.diag.network');
  }
  if (/eastmoney_hotspot_unavailable|returned no data|no live hotspot rows|\bempty\b/i.test(text)) {
    return t('screeningPage.hotspot.diag.noData');
  }
  if (/rate limit|too many requests|http\s*429/i.test(text)) {
    return t('screeningPage.hotspot.diag.rateLimited');
  }
  if (/Dsa[A-Z]|Provider\b|stock_board_|concept_constituents|leader_stocks|last_good_cache|^[a-z0-9_.:-]+$/i.test(text)) {
    return t('screeningPage.hotspot.diag.partial');
  }
  if (/[\u0080-￿]/.test(text)) {
    return truncateMessageDetail(text);
  }
  return t('screeningPage.hotspot.diag.partial');
};

const getHotspotDiagnosticMessages = (values: string[] | undefined, t: Translate) =>
  [...new Set((values || []).map((value) => formatHotspotDiagnostic(value, t)).filter(Boolean))].slice(0, 4);

const hasHotspotDetailDegradation = (detail: ScreeningHotspotDetail) => {
  if ((detail.missingFields || []).length > 0) {
    return true;
  }
  const qualityStatus = String(detail.qualityStatus || '').trim().toLowerCase();
  if (qualityStatus) {
    return qualityStatus !== 'available';
  }
  return (detail.sourceErrors || []).length > 0;
};

const getHotspotFallbackLabel = (detail: ScreeningHotspotDetail, t: Translate) => {
  if (detail.stale || detail.cacheUsed) {
    return detail.staleAgeHours != null
      ? t('screeningPage.hotspot.cacheFallbackAge', { hours: formatNumber(detail.staleAgeHours, 1) })
      : t('screeningPage.hotspot.cacheFallback');
  }
  return t('screeningPage.hotspot.backupSource');
};

const getHotspotSummaryText = (detail: ScreeningHotspotDetail, hotspot: ScreeningHotspot | undefined, t: Translate) => {
  const summaryDetail = detail.summaryDetail || {};
  const heatScore = summaryDetail.heatScore ?? summaryDetail.heat_score ?? hotspot?.heatScore;
  const stage = summaryDetail.stage ?? hotspot?.stage ?? hotspot?.state;
  const rawLeaders = summaryDetail.leaders ?? hotspot?.leaders;
  const leaders = Array.isArray(rawLeaders)
    ? rawLeaders.map((value) => String(value).trim()).filter(Boolean).slice(0, 3)
    : [];
  const parts: string[] = [];
  if (heatScore != null && !Number.isNaN(Number(heatScore))) {
    parts.push(t('screeningPage.hotspot.heatIs', { value: formatNumber(heatScore, 1) }));
  }
  if (stage) {
    parts.push(t('screeningPage.hotspot.stageIs', { stage: getHotspotStageLabel(stage, t) }));
  }
  if (leaders.length > 0) {
    parts.push(t('screeningPage.hotspot.leadersAre', { leaders: leaders.join(t('screeningPage.listSeparator')) }));
  }
  if (parts.length > 0) {
    return t('screeningPage.hotspot.summary', {
      topic: detail.name || detail.canonicalTopic || detail.topic,
      parts: parts.join(t('screeningPage.clauseSeparator')),
    });
  }
  const summary = String(detail.summary || '').trim();
  if (summary && !/\b(?:heat|stage|leaders?|quality status|available|partial|stale|failed)\b|Dsa[A-Z]|Provider\b|stock_board_/i.test(summary)) {
    return summary;
  }
  return t('screeningPage.hotspot.detailLoaded');
};

const buildHotspotPreviewDetail = (hotspot: ScreeningHotspot, t: Translate): ScreeningHotspotDetail => {
  const leaders = (hotspot.leaders || []).map((value) => String(value).trim()).filter(Boolean);
  const stage = getHotspotStageLabel(hotspot.stage || hotspot.state, t);
  const descriptionParts = [t('screeningPage.hotspot.topicHeat', { topic: hotspot.name || hotspot.topic, value: formatNumber(hotspot.heatScore, 1) })];
  if (stage) {
    descriptionParts.push(t('screeningPage.hotspot.stageIs', { stage }));
  }
  if (leaders.length > 0) {
    descriptionParts.push(t('screeningPage.hotspot.leadersAre', { leaders: leaders.slice(0, 3).join(t('screeningPage.listSeparator')) }));
  }
  const stocks = (hotspot.leaderStocks || []).slice(0, 10);
  return {
    enabled: true,
    provider: 'akshare',
    topic: hotspot.topic,
    name: hotspot.name || hotspot.topic,
    canonicalTopic: hotspot.topic,
    summaryDetail: {
      heatScore: hotspot.heatScore,
      stage: hotspot.stage || hotspot.state,
      leaders,
    },
    route: [{
      title: t('screeningPage.hotspot.currentFermentation'),
      description: t('screeningPage.hotspot.sentence', { parts: descriptionParts.join(t('screeningPage.clauseSeparator')) }),
    }],
    stocks,
    stockCount: hotspot.sampleStockCount ?? stocks.length,
    sourceErrors: hotspot.sourceErrors,
    qualityStatus: hotspot.qualityStatus,
    missingFields: hotspot.missingFields,
    fallbackUsed: hotspot.fallbackUsed,
    stale: hotspot.stale,
    staleAgeHours: hotspot.staleAgeHours,
    cacheUsed: hotspot.cacheUsed,
    cachedAt: hotspot.cachedAt,
  };
};

const stripHotspotSearchAugmentation = (detail: ScreeningHotspotDetail): ScreeningHotspotDetail => {
  const baseDetail: ScreeningHotspotDetail = {
    ...detail,
    route: (detail.route || []).filter((item) => !item.searchResult),
    ...(detail.timeline
      ? { timeline: detail.timeline.filter((item) => !item.searchResult) }
      : {}),
  };
  delete baseDetail.newsSearchRequested;
  delete baseDetail.newsSearchStatus;
  return baseDetail;
};

const stripHotspotSearchAugmentationByTopic = (
  details: Record<string, ScreeningHotspotDetail>,
) => Object.fromEntries(
  Object.entries(details).map(([topic, detail]) => [topic, stripHotspotSearchAugmentation(detail)]),
) as Record<string, ScreeningHotspotDetail>;

const getHotspotRouteItems = (detail: ScreeningHotspotDetail) => {
  const route = detail.route || [];
  if (route.length > 0) {
    return route;
  }
  return detail.timeline || [];
};

const getHotspotLeadersText = (item: ScreeningHotspot, t: Translate) => {
  const leaders = (item.leaders || []).map((value) => String(value).trim()).filter(Boolean);
  return leaders.length > 0 ? leaders.slice(0, 2).join(t('screeningPage.listSeparator')) : NO_VALUE;
};

const formatHotspotUpdatedAt = (value: string | null, locale: string, t: Translate) => {
  if (!value) {
    return t('screeningPage.hotspot.pendingRefresh');
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
};

// 結果表的客戶端排序；缺值一律排最後，不當成 0。
const SORT_VALUE: Record<string, (item: ScreeningCandidate) => number | null> = {
  rank: (item) => toFiniteNumber(item.rank),
  price: (item) => toFiniteNumber(item.price),
  changePct: (item) => toFiniteNumber(item.changePct),
  score: (item) => toFiniteNumber(item.score),
  amount: (item) => toFiniteNumber(item.amount),
};

const sortCandidates = (items: ScreeningCandidate[], sort: SortState): ScreeningCandidate[] => {
  const read = SORT_VALUE[sort.key] ?? SORT_VALUE.rank;
  const sign = sort.direction === 'asc' ? 1 : -1;
  return [...items].sort((a, b) => {
    const left = read(a);
    const right = read(b);
    if (left === null && right === null) return 0;
    if (left === null) return 1;
    if (right === null) return -1;
    return (left - right) * sign;
  });
};

const DetailBlock: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div>
    <p className="text-xs font-semibold text-secondary-text">{title}</p>
    {children}
  </div>
);

const StockScreeningPage: React.FC = () => {
  const { language, t } = useUiLanguage();
  const navigate = useNavigate();
  const intlLocale = getIntlLocale(language);
  const [restoredTask] = useState<PersistedScreenTask | null>(() => readPersistedScreenTask());
  const restoredFormMarket = isFormMarket(restoredTask?.market);
  const [statusState, setStatusState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [statusError, setStatusError] = useState('');
  const [statusAttempt, setStatusAttempt] = useState(0);
  const [enabled, setEnabled] = useState(false);
  const [available, setAvailable] = useState(false);
  // 表單只開台股與美股；還原到舊的 A 股結果時，結果區另外標，表單仍回預設。
  const [market, setMarket] = useState<FormMarket>(restoredFormMarket ? (restoredTask?.market as FormMarket) : DEFAULT_MARKET);
  const [strategy, setStrategy] = useState(restoredFormMarket ? (restoredTask?.strategy || DEFAULT_STRATEGY) : DEFAULT_STRATEGY);
  const [strategies, setStrategies] = useState<ScreeningStrategy[]>([]);
  const [maxResults, setMaxResults] = useState(restoredTask?.maxResults || 3);
  const [resultContext, setResultContext] = useState<ResultContext | null>(() => (restoredTask
    ? { market: restoredTask.market, strategy: restoredTask.strategy, maxResults: restoredTask.maxResults }
    : null));
  const [candidates, setCandidates] = useState<ScreeningCandidate[]>([]);
  const [sort, setSort] = useState<SortState>({ key: 'rank', direction: 'asc' });
  const [detailCode, setDetailCode] = useState<string | null>(null);
  const [selectedCodes, setSelectedCodes] = useState<string[]>([]);
  const [watchlistCodes, setWatchlistCodes] = useState<string[]>([]);
  const [batchMessage, setBatchMessage] = useState<{ variant: 'success' | 'danger'; text: string } | null>(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const [hotspots, setHotspots] = useState<ScreeningHotspot[]>([]);
  const [hotspotsUpdatedAt, setHotspotsUpdatedAt] = useState<string | null>(null);
  const [hotspotsExpanded, setHotspotsExpanded] = useState(false);
  const [selectedHotspotTopic, setSelectedHotspotTopic] = useState<string | null>(null);
  const selectedHotspotTopicRef = useRef<string | null>(null);
  const hotspotDetailRequestIdRef = useRef(0);
  const hotspotDetailsByTopicRef = useRef<Record<string, ScreeningHotspotDetail>>({});
  const historyRunRequestIdRef = useRef(0);
  const [hotspotDetail, setHotspotDetail] = useState<ScreeningHotspotDetail | null>(null);
  const [loadingHotspotDetail, setLoadingHotspotDetail] = useState(false);
  const [searchingHotspotNews, setSearchingHotspotNews] = useState(false);
  const [hotspotDetailError, setHotspotDetailError] = useState('');
  const [loadingHotspots, setLoadingHotspots] = useState(false);
  const [hotspotError, setHotspotError] = useState('');
  const [screenMeta, setScreenMeta] = useState<ScreeningScreenResponse | null>(null);
  const [loading, setLoading] = useState(Boolean(restoredTask?.taskId));
  const [enabling, setEnabling] = useState(false);
  const [historyRuns, setHistoryRuns] = useState<ScreeningRunSummary[]>([]);
  const [selectedHistoryRunId, setSelectedHistoryRunId] = useState('');
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [restoreResolved, setRestoreResolved] = useState(() => !restoredTask?.runId);
  // 标记当前 strategy 是否来自历史 run（刷新自动恢复或手动历史选择）的上下文同步。
  // 为 true 时 loadStrategies 跳过“不在列表则回退第一项”的归一化，
  // 防止迟到的 /strategies 响应把历史上下文改写回默认策略。
  const historyContextStrategyRef = useRef(false);
  const [loadingStrategies, setLoadingStrategies] = useState(false);
  const [error, setError] = useState('');
  const [strategyLoadError, setStrategyLoadError] = useState('');
  const [activeTaskId, setActiveTaskId] = useState<string | null>(restoredTask?.taskId ?? null);
  const [taskProgress, setTaskProgress] = useState(restoredTask?.taskId ? 10 : 0);
  const [taskMessage, setTaskMessage] = useState(restoredTask?.taskId ? t('screeningPage.task.restoring') : '');
  // 自動還原只該跑一次，切語言不能重跑把使用者手上的結果蓋掉，所以文案經 ref 讀。
  const translateRef = useRef(t);

  useEffect(() => {
    translateRef.current = t;
  }, [t]);

  const marketStrategies = useMemo(
    () => strategies.filter((item) => supportsMarket(item, market)),
    [market, strategies],
  );
  const selectedStrategy = useMemo(() => marketStrategies.find((item) => item.id === strategy), [marketStrategies, strategy]);
  const resultStrategyId = resultContext?.strategy ?? strategy;
  const resultMarket = resultContext?.market ?? market;
  const resultStrategy = useMemo(() => strategies.find((item) => item.id === resultStrategyId), [resultStrategyId, strategies]);
  const displayedStrategy = resultStrategy
    ? getStrategyName(resultStrategy, language)
    : t('screeningPage.customStrategy', { id: resultStrategyId });
  const screenMessages = useMemo(() => getScreenMessages(screenMeta, t), [screenMeta, t]);
  const sortedCandidates = useMemo(() => sortCandidates(candidates, sort), [candidates, sort]);
  const detailCandidate = useMemo(
    () => candidates.find((item) => item.code === detailCode) ?? null,
    [candidates, detailCode],
  );
  const selectedHotspot = useMemo(
    () => hotspots.find((item) => item.topic === selectedHotspotTopic),
    [hotspots, selectedHotspotTopic],
  );
  const factorRanking = Boolean(screenMeta && (screenMeta.rankingMode === 'factor' || screenMeta.llmRanked === false));
  const llmFailed = Boolean(factorRanking && screenMeta?.llmFailureReason);
  const alertMessages = llmFailed
    ? screenMessages.length > 0
      ? screenMessages
      : [t('screeningPage.llmFallback')]
    : screenMessages;
  const isScreeningEnabled = statusState === 'ready' && enabled && available;
  const conditionsChanged = Boolean(screenMeta && resultContext && (
    resultContext.market !== market
    || resultContext.strategy !== strategy
    || (resultContext.maxResults !== undefined && resultContext.maxResults !== maxResults)
  ));
  const statusText = statusState === 'loading'
    ? t('screeningPage.status.loading')
    : statusState === 'error'
      ? t('screeningPage.status.error')
      : !enabled
        ? t('screeningPage.status.disabled')
        : available ? t('screeningPage.status.enabled') : t('screeningPage.status.unavailable');

  const applyScreenResult = useCallback((result: ScreeningScreenResponse) => {
    setScreenMeta(result);
    setCandidates(result.candidates || []);
    setDetailCode(null);
    setSelectedCodes([]);
    setBatchMessage(null);
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError('');
    try {
      const result = await screeningApi.getHistory({ limit: 10 });
      setHistoryRuns(result.runs || []);
    } catch (err) {
      setHistoryError(toApiErrorMessage(err, t('screeningPage.history.loadFailed')));
    } finally {
      setHistoryLoading(false);
    }
  }, [t]);

  const handleHistoryRunSelect = useCallback(async (runId: string) => {
    // 竞态防护：快速切换历史条目时，只应用最新一次请求的响应
    const requestId = historyRunRequestIdRef.current + 1;
    historyRunRequestIdRef.current = requestId;
    const isCurrentRequest = () => historyRunRequestIdRef.current === requestId;
    // 与运行中的选股任务互斥：手动选择历史记录后，暂停/取消后台任务轮询，
    // 避免任务完成后把当前任务的候选结果回写到历史上下文中。
    setActiveTaskId(null);
    setHistoryError('');
    setLoading(true);
    try {
      const detail = await screeningApi.getRun(runId);
      if (!isCurrentRequest()) {
        return;
      }
      if (detail?.result) {
        applyScreenResult(detail.result);
        historyContextStrategyRef.current = true;
        // 同步持久化恢复指针：刷新后应恢复用户刚选中的历史 run，
        // 而不是停留在更早的 task/run。历史详情不携带 taskId，以 runId
        // 作为占位——正常路径刷新走 getRun(runId) 恢复、不会触发轮询；
        // 若该 run 恢复失败，占位轮询会命中不可恢复错误并清理过期指针。
        persistScreenTask({
          taskId: runId,
          runId,
          market: detail.market || market,
          strategy: detail.strategy || strategy,
          maxResults,
        });
        // 结果区用该 run 的策略与市场；表单只同步开放的市场，舊的 A 股紀錄不改表單。
        setResultContext({ market: detail.market || market, strategy: detail.strategy || strategy });
        if (isFormMarket(detail.market)) {
          setMarket(detail.market);
          if (detail.strategy) {
            setStrategy(detail.strategy);
          }
        }
        setError('');
        setTaskProgress(100);
        setTaskMessage(t('screeningPage.task.historyLoaded'));
      } else {
        setError(t('screeningPage.history.noResult'));
      }
    } catch (err) {
      if (!isCurrentRequest()) {
        return;
      }
      setError(toApiErrorMessage(err, t('screeningPage.history.resultFailed')));
    } finally {
      if (isCurrentRequest()) {
        setLoading(false);
      }
    }
  }, [applyScreenResult, market, maxResults, strategy, t]);

  const loadHotspotDetail = useCallback(async (
    topic: string,
    options: { refresh?: boolean; includeSearch?: boolean } = {},
  ) => {
    if (!topic) {
      return;
    }
    const cachedDetail = !options.refresh && !options.includeSearch
      ? hotspotDetailsByTopicRef.current[topic]
      : null;
    if (cachedDetail) {
      setHotspotDetail(cachedDetail);
      setHotspotDetailError('');
      setLoadingHotspotDetail(false);
      return;
    }
    const requestId = hotspotDetailRequestIdRef.current + 1;
    hotspotDetailRequestIdRef.current = requestId;
    const isCurrentRequest = () => hotspotDetailRequestIdRef.current === requestId;
    const canApplyRequest = () => isCurrentRequest() && selectedHotspotTopicRef.current === topic;
    setLoadingHotspotDetail(!options.includeSearch);
    setSearchingHotspotNews(Boolean(options.includeSearch));
    setHotspotDetail((currentDetail) => (currentDetail?.topic === topic ? currentDetail : null));
    setHotspotDetailError('');
    try {
      const detail = await screeningApi.getHotspotDetail({
        topic,
        provider: 'akshare',
        refresh: options.refresh ?? false,
        ...(options.includeSearch ? { includeSearch: true } : {}),
      });
      if (!canApplyRequest()) {
        return;
      }
      const cacheableDetail = options.includeSearch
        ? hotspotDetailsByTopicRef.current[topic] || stripHotspotSearchAugmentation(detail)
        : stripHotspotSearchAugmentation(detail);
      hotspotDetailsByTopicRef.current = {
        ...hotspotDetailsByTopicRef.current,
        [topic]: cacheableDetail,
      };
      setHotspotDetail(options.includeSearch ? detail : cacheableDetail);
      if (options.includeSearch && detail.newsSearchStatus === 'no_results') {
        setHotspotDetailError(t('screeningPage.hotspot.newsNoResults'));
      } else if (options.includeSearch && detail.newsSearchStatus !== 'available') {
        setHotspotDetailError(t('screeningPage.hotspot.newsFailed'));
      }
    } catch (err) {
      if (!canApplyRequest()) {
        return;
      }
      if (!options.includeSearch) {
        setHotspotDetail(null);
      }
      setHotspotDetailError(toApiErrorMessage(
        err,
        options.includeSearch ? t('screeningPage.hotspot.newsFailed') : t('screeningPage.hotspot.detailFailed'),
      ));
    } finally {
      if (isCurrentRequest()) {
        setLoadingHotspotDetail(false);
        setSearchingHotspotNews(false);
      }
    }
  }, [t]);

  const loadStrategies = useCallback(async () => {
    setLoadingStrategies(true);
    try {
      setStrategyLoadError('');
      // 一次取全部策略再依市場過濾：切市場不用重打 API，歷史紀錄也查得到其他市場的策略名稱。
      const result = await screeningApi.getStrategies();
      const loadedStrategies = result.strategies || [];
      setStrategies(loadedStrategies);
    } catch (err) {
      setStrategies([]);
      setStrategyLoadError(err instanceof Error ? err.message : t('screeningPage.strategyLoadFailed'));
    } finally {
      setLoadingStrategies(false);
    }
  }, [t]);

  const loadHotspots = useCallback(async (refresh: boolean, hotspotMarket: string) => {
    setLoadingHotspots(true);
    setHotspotError('');
    try {
      const result = await screeningApi.getHotspots({ provider: 'akshare', top: 12, refresh, market: hotspotMarket });
      const nextHotspots = result.hotspots || [];
      const nextDetails = stripHotspotSearchAugmentationByTopic(result.details || {});
      hotspotDetailsByTopicRef.current = {
        ...hotspotDetailsByTopicRef.current,
        ...nextDetails,
      };
      const currentTopic = selectedHotspotTopicRef.current;
      const retainedTopic = Boolean(currentTopic && nextHotspots.some((item) => item.topic === currentTopic));
      const nextTopic = retainedTopic ? currentTopic : null;
      setHotspots(nextHotspots);
      setHotspotsUpdatedAt(result.cachedAt || (nextHotspots.length > 0 ? new Date().toISOString() : null));
      setSelectedHotspotTopic(nextTopic);
      selectedHotspotTopicRef.current = nextTopic;
      setHotspotDetailError('');
      if (nextTopic && nextDetails[nextTopic]) {
        setHotspotDetail(nextDetails[nextTopic]);
        setLoadingHotspotDetail(false);
      } else if (!retainedTopic) {
        setHotspotDetail(null);
      } else if (refresh && nextTopic) {
        // A refreshed list and a retained detail must describe the same source
        // snapshot. The list endpoint intentionally omits details by default,
        // so explicitly bypass the detail cache for the retained topic.
        await loadHotspotDetail(nextTopic, { refresh: true });
      }
      if (nextHotspots.length === 0) {
        setHotspotError(formatHotspotEmptyMessage(result, hotspotMarket, t));
      }
    } catch (err) {
      setHotspotError(toApiErrorMessage(err, t('screeningPage.hotspot.loadFailed')));
    } finally {
      setLoadingHotspots(false);
    }
  }, [loadHotspotDetail, t]);

  const handleHotspotSelect = useCallback((topic: string) => {
    selectedHotspotTopicRef.current = topic;
    setSelectedHotspotTopic(topic);
    const cachedDetail = hotspotDetailsByTopicRef.current[topic];
    if (cachedDetail) {
      setHotspotDetail(cachedDetail);
      setHotspotDetailError('');
      setLoadingHotspotDetail(false);
    } else {
      const preview = hotspots.find((item) => item.topic === topic);
      setHotspotDetail((currentDetail) => (
        currentDetail?.topic === topic ? currentDetail : preview ? buildHotspotPreviewDetail(preview, t) : null
      ));
    }
  }, [hotspots, t]);

  const toggleHotspotsExpanded = useCallback(() => {
    setHotspotsExpanded((expanded) => {
      const nextExpanded = !expanded;
      if (!nextExpanded) {
        selectedHotspotTopicRef.current = null;
        setSelectedHotspotTopic(null);
        setHotspotDetail(null);
        setHotspotDetailError('');
      }
      return nextExpanded;
    });
  }, []);

  const handleAnalyzeHotspotStock = useCallback((stock: ScreeningHotspotDetail['stocks'][number]) => {
    const stockCode = String(stock.code || '').trim();
    if (!stockCode) {
      return;
    }
    const stockName = String(stock.name || stockCode).trim();
    navigate('/', {
      state: {
        stockCode,
        stockName,
        autoAnalyze: true,
        selectionSource: 'screening_hotspot',
        skills: ['hot_theme'],
      },
    });
  }, [navigate]);

  const handleAnalyzeCandidate = useCallback((candidate: ScreeningCandidate) => {
    const stockCode = String(candidate.code || '').trim();
    if (!stockCode) {
      return;
    }
    const stockName = String(candidate.name || stockCode).trim();
    const analysisSkills = (resultStrategy?.analysisSkills || []).filter(Boolean);
    navigate('/', {
      state: {
        stockCode,
        stockName,
        autoAnalyze: true,
        selectionSource: 'screening_result',
        ...(analysisSkills.length > 0 ? { skills: analysisSkills } : {}),
      },
    });
  }, [navigate, resultStrategy]);

  const handleToggleWatch = useCallback(async (code: string) => {
    try {
      const existing = findMatchingStockCode(watchlistCodes, code);
      const next = existing
        ? await systemConfigApi.removeFromWatchlist(existing)
        : await systemConfigApi.addToWatchlist(code);
      setWatchlistCodes(next);
    } catch (err) {
      setBatchMessage({ variant: 'danger', text: toApiErrorMessage(err, t('screeningPage.batch.watchFailed')) });
    }
  }, [t, watchlistCodes]);

  const toggleSelectedCode = useCallback((code: string) => {
    setSelectedCodes((current) => (current.includes(code) ? current.filter((item) => item !== code) : [...current, code]));
  }, []);

  const handleBatchWatch = async () => {
    setBatchBusy(true);
    setBatchMessage(null);
    try {
      let next = watchlistCodes;
      for (const code of selectedCodes) {
        if (!findMatchingStockCode(next, code)) {
          next = await systemConfigApi.addToWatchlist(code);
        }
      }
      setWatchlistCodes(next);
      setBatchMessage({ variant: 'success', text: t('screeningPage.batch.watchAdded', { count: selectedCodes.length }) });
      setSelectedCodes([]);
    } catch (err) {
      setBatchMessage({ variant: 'danger', text: toApiErrorMessage(err, t('screeningPage.batch.watchFailed')) });
    } finally {
      setBatchBusy(false);
    }
  };

  const handleBatchAnalyze = async () => {
    setBatchBusy(true);
    setBatchMessage(null);
    try {
      const analysisSkills = (resultStrategy?.analysisSkills || []).filter(Boolean);
      await analysisApi.analyzeAsync({
        stockCodes: selectedCodes,
        ...(analysisSkills.length > 0 ? { skills: analysisSkills } : {}),
      });
      setBatchMessage({ variant: 'success', text: t('screeningPage.batch.analyzeSent', { count: selectedCodes.length }) });
      setSelectedCodes([]);
    } catch (err) {
      setBatchMessage({ variant: 'danger', text: toApiErrorMessage(err, t('screeningPage.batch.analyzeFailed')) });
    } finally {
      setBatchBusy(false);
    }
  };

  useEffect(() => {
    selectedHotspotTopicRef.current = selectedHotspotTopic;
  }, [selectedHotspotTopic]);

  useEffect(() => {
    if (!selectedHotspotTopic) {
      return;
    }
    void loadHotspotDetail(selectedHotspotTopic);
  }, [loadHotspotDetail, selectedHotspotTopic]);

  const loadEnabledData = useCallback((hotspotMarket: string) => {
    void loadStrategies();
    void loadHotspots(false, hotspotMarket);
    void loadHistory();
    void systemConfigApi.getWatchlist()
      .then(setWatchlistCodes)
      .catch(() => {
        // 讀不到自選只影響星號的初始狀態，不擋選股。
      });
  }, [loadHistory, loadHotspots, loadStrategies]);

  // 初次載入用當下市場；之後切市場由 handleMarketChange 明確重抓，這裡不追 market。
  const initialMarketRef = useRef(market);

  useEffect(() => {
    let active = true;
    screeningApi
      .getStatus()
      .then((status) => {
        if (!active) {
          return;
        }
        setEnabled(status.enabled);
        setAvailable(status.available);
        setStatusState('ready');
        if (status.enabled && status.available) {
          loadEnabledData(initialMarketRef.current);
        }
      })
      .catch((err) => {
        if (active) {
          setStatusError(toApiErrorMessage(err, t('screeningPage.statusReadFailed')));
          setStatusState('error');
        }
      });
    return () => {
      active = false;
    };
  }, [loadEnabledData, statusAttempt, t]);

  // 刷新后优先从 history API 按 run_id 恢复结果；恢复失败再回退到 task 轮询
  useEffect(() => {
    const runId = restoredTask?.runId;
    if (!runId) {
      setRestoreResolved(true);
      return undefined;
    }
    let active = true;
    setLoading(true);
    // 记录自动恢复的请求基准：若在自动恢复返回前用户手动点开了历史记录
    // （historyRunRequestIdRef 被 handleHistoryRunSelect 递增），则放弃本次自动恢复响应，
    // 避免较晚返回的自动恢复把页面切回旧 run，覆盖用户最新一次的历史选择。
    const restoreRequestBase = historyRunRequestIdRef.current;
    screeningApi
      .getRun(runId)
      .then((detail) => {
        if (!active || historyRunRequestIdRef.current !== restoreRequestBase) {
          return;
        }
        if (detail?.result) {
          applyScreenResult(detail.result);
          historyContextStrategyRef.current = true;
          // 同步恢复该历史 run 的上下文（与 handleHistoryRunSelect 一致）
          setResultContext({
            market: detail.market || restoredTask.market,
            strategy: detail.strategy || restoredTask.strategy,
          });
          if (isFormMarket(detail.market)) {
            setMarket(detail.market);
            if (detail.strategy) {
              setStrategy(detail.strategy);
            }
          }
          setError('');
          setTaskProgress(100);
          setTaskMessage(translateRef.current('screeningPage.task.restored'));
          setActiveTaskId(null);
        }
      })
      .catch(() => {
        // 历史记录恢复失败（run 不存在或服务重启），回退到 task 轮询；
        // 若用户已手动选择了历史记录，则不再回退，保持用户的选择。
        if (active && historyRunRequestIdRef.current === restoreRequestBase) {
          setActiveTaskId(restoredTask?.taskId ?? null);
        }
      })
      .finally(() => {
        // 无论结果是否过期都要解除自动恢复门闩，否则新任务的轮询会被阻塞到旧请求超时。
        if (active) {
          setRestoreResolved(true);
        }
        // 过期的自动恢复不得触碰共享 loading：用户手动选择的历史详情请求可能仍在飞行，
        // 提前清掉会重新放开“运行选股”入口，随后迟到的历史响应会覆盖新任务状态。
        if (active && historyRunRequestIdRef.current === restoreRequestBase) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [applyScreenResult, restoredTask]);

  useEffect(() => {
    if (!activeTaskId || !restoreResolved) {
      return undefined;
    }

    const pollingTaskId = activeTaskId;
    let active = true;
    let timer: ReturnType<typeof window.setTimeout> | undefined;

    function finishTask() {
      setActiveTaskId(null);
      setLoading(false);
    }

    function applyTaskStatus(task: ScreeningScreenTaskStatus) {
      const nextProgress = Number(task.progress ?? 0);
      setTaskProgress(Number.isFinite(nextProgress) ? nextProgress : 0);
      setTaskMessage(task.message || '');

      if (task.status === 'completed') {
        if (task.result) {
          applyScreenResult(task.result);
          setError('');
          // 持久化 runId：刷新后优先从 history API 恢复结果，而非依赖内存 task
          const completedRunId = task.result.runId || screenMeta?.runId;
          if (completedRunId) {
            persistScreenTask({
              taskId: pollingTaskId,
              runId: completedRunId,
              market,
              strategy,
              maxResults,
            });
          }
        } else {
          setError(t('screeningPage.task.noResult'));
          setCandidates([]);
          setScreenMeta(null);
        }
        finishTask();
        return;
      }

      if (task.status === 'failed') {
        setCandidates([]);
        setScreenMeta(null);
        setDetailCode(null);
        setError(formatScreenTaskFailure(task.error || task.message, t));
        clearPersistedScreenTask();
        finishTask();
        return;
      }

      if (isRunningScreenTask(task.status)) {
        setLoading(true);
        timer = window.setTimeout(pollTask, SCREEN_TASK_POLL_INTERVAL_MS);
        return;
      }

      setError(t('screeningPage.task.unknownStatus', { status: task.status || t('screeningPage.quality.unknown') }));
      clearPersistedScreenTask();
      finishTask();
    }

    async function pollTask() {
      try {
        const task = await screeningApi.getScreenTask(pollingTaskId);
        if (!active) {
          return;
        }
        applyTaskStatus(task);
      } catch (err) {
        if (!active) {
          return;
        }
        const parsedError = getParsedApiError(err);
        if (isUnrecoverableScreenTaskError(parsedError)) {
          setError(formatParsedApiError(parsedError) || t('screeningPage.task.unrecoverable'));
          setCandidates([]);
          setScreenMeta(null);
          clearPersistedScreenTask();
          finishTask();
          return;
        }
        setError(formatRecoverableScreenTaskPollingError(parsedError, t));
        setLoading(true);
        timer = window.setTimeout(pollTask, SCREEN_TASK_POLL_INTERVAL_MS);
      }
    }

    void pollTask();

    return () => {
      active = false;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
    // 輪詢只跟任務走；表單在執行中是停用的，market/strategy 不會變。
  }, [activeTaskId, applyScreenResult, restoreResolved]);

  // 目前策略不在此市場開放時回退第一項。
  // 历史 run 的自定义/下线策略不在当前列表属预期行为，不做归一化，
  // 否则迟到的策略列表会把刚恢复好的上下文改写回默认策略。
  useEffect(() => {
    if (historyContextStrategyRef.current || marketStrategies.length === 0) {
      return;
    }
    if (!marketStrategies.some((item) => item.id === strategy)) {
      setStrategy(marketStrategies[0].id);
    }
  }, [marketStrategies, strategy]);

  const handleEnable = async () => {
    setEnabling(true);
    setError('');
    try {
      await screeningApi.enable();
      setEnabled(true);
      setAvailable(true);
      loadEnabledData(market);
    } catch (err) {
      try {
        const status = await screeningApi.getStatus();
        setEnabled(status.enabled);
        setAvailable(status.available);
        setStatusState('ready');
      } catch (statusErr) {
        setStatusError(toApiErrorMessage(statusErr, t('screeningPage.statusReadFailed')));
        setStatusState('error');
      }
      setError(err instanceof Error ? err.message : t('screeningPage.enableFailed'));
    } finally {
      setEnabling(false);
    }
  };

  // 改條件不清空結果：舊結果留著比對，靠提示告知要重新執行才會更新。
  const handleMarketChange = (nextMarket: FormMarket) => {
    if (nextMarket === market) {
      return;
    }
    historyContextStrategyRef.current = false;
    setMarket(nextMarket);
    void loadHotspots(false, nextMarket);
  };

  const handleSubmit = async () => {
    // 新任务提交即代表用户放弃当前历史/恢复上下文：
    // 递增请求代号作废飞行中的历史详情与自动恢复响应；
    // 解除自动恢复门闩，保证刚提交的任务轮询立即可启动。
    historyRunRequestIdRef.current += 1;
    setRestoreResolved(true);
    setLoading(true);
    setError('');
    setScreenMeta(null);
    setDetailCode(null);
    setSelectedHistoryRunId('');
    setResultContext({ market, strategy, maxResults });
    setTaskProgress(0);
    setTaskMessage(t('screeningPage.task.submitting'));
    try {
      const task = await screeningApi.startScreen({ market, strategy, maxResults });
      persistScreenTask({
        taskId: task.taskId,
        market,
        strategy,
        maxResults,
      });
      setActiveTaskId(task.taskId);
      setTaskProgress(0);
      setTaskMessage(task.message || t('screeningPage.task.submitted'));
    } catch (err) {
      setCandidates([]);
      setLoading(false);
      setError(toApiErrorMessage(err, t('screeningPage.task.submitFailed')));
    }
  };

  const currency = MARKET_CURRENCY[resultMarket];
  const universeLabel = screenMeta?.universeSource
    ? lookupLabel(UNIVERSE_SOURCE_KEYS, screenMeta.universeSource, t) || screenMeta.universeSource
    : '';

  const renderRowActions = (item: ScreeningCandidate) => {
    const watched = Boolean(findMatchingStockCode(watchlistCodes, item.code));
    return (
      <span className="inline-flex items-center justify-end gap-1">
        <Button
          size="xsm"
          variant="secondary"
          onClick={(event: React.MouseEvent) => {
            event.stopPropagation();
            handleAnalyzeCandidate(item);
          }}
          aria-label={t('screeningPage.table.analyzeNamed', { name: item.name || item.code })}
        >
          {t('screeningPage.table.analyze')}
        </Button>
        <IconButton
          size="sm"
          aria-label={t(watched ? 'screeningPage.table.unwatch' : 'screeningPage.table.watch', { name: item.name || item.code })}
          aria-pressed={watched}
          icon={<Star className={watched ? 'h-4 w-4 fill-current text-warning' : 'h-4 w-4'} aria-hidden="true" />}
          onClick={(event: React.MouseEvent) => {
            event.stopPropagation();
            void handleToggleWatch(item.code);
          }}
        />
      </span>
    );
  };

  const renderRowCheckbox = (item: ScreeningCandidate) => (
    <input
      type="checkbox"
      aria-label={t('screeningPage.table.select', { name: item.name || item.code })}
      checked={selectedCodes.includes(item.code)}
      onClick={(event) => event.stopPropagation()}
      onChange={() => toggleSelectedCode(item.code)}
    />
  );

  const columns: DataTableColumn<ScreeningCandidate>[] = [
    { key: 'select', header: t('screeningPage.table.selectHeader'), render: renderRowCheckbox, priority: 'primary' },
    { key: 'rank', header: '#', numeric: true, sortable: true, render: (item) => item.rank },
    {
      key: 'name',
      header: t('screeningPage.table.name'),
      priority: 'primary',
      minWidth: 140,
      render: (item) => (
        <span className="block min-w-0">
          <span className="block truncate font-semibold text-foreground">{item.name || NO_VALUE}</span>
          <span className="block truncate text-xs text-secondary-text">{item.code}</span>
        </span>
      ),
    },
    { key: 'industry', header: t('screeningPage.table.industry'), render: (item) => item.industry || NO_VALUE },
    {
      key: 'price',
      header: t('screeningPage.table.price'),
      numeric: true,
      sortable: true,
      render: (item) => <Num kind="price" value={item.price} currency={currency} />,
    },
    {
      key: 'changePct',
      header: t('screeningPage.table.change'),
      numeric: true,
      sortable: true,
      priority: 'primary',
      render: (item) => <Change value={item.changePct}><Num kind="percent" value={item.changePct} /></Change>,
    },
    {
      key: 'score',
      header: t('screeningPage.table.score'),
      numeric: true,
      sortable: true,
      render: (item) => <Num value={item.score} digits={2} />,
    },
    {
      key: 'ranking',
      header: t('screeningPage.table.ranking'),
      render: (item) => (factorRanking ? t('screeningPage.table.factorRanking') : formatNumber(item.llmScore)),
    },
    {
      key: 'risk',
      header: t('screeningPage.table.risk'),
      render: (item) => (
        <span className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${getRiskClassName(item.riskLevel)}`}>
          {getRiskLabel(item.riskLevel, t)}
        </span>
      ),
    },
    { key: 'actions', header: t('screeningPage.table.actions'), align: 'right', render: renderRowActions },
  ];

  const renderMobileCard = (item: ScreeningCandidate) => (
    <div className="flex flex-col gap-2 px-3 py-3" data-testid="screening-mobile-card">
      <div className="flex items-start justify-between gap-3">
        <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setDetailCode(item.code)}>
          <span className="block truncate text-sm font-semibold text-foreground">{item.name || NO_VALUE}</span>
          <span className="block truncate text-xs text-secondary-text">{item.code}</span>
        </button>
        <span className="shrink-0 text-right">
          <span className="block text-sm font-semibold text-foreground"><Num kind="price" value={item.price} currency={currency} /></span>
          <span className="block text-xs"><Change value={item.changePct}><Num kind="percent" value={item.changePct} /></Change></span>
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <label className="inline-flex items-center gap-2 text-xs text-secondary-text">
          {renderRowCheckbox(item)}
          {t('screeningPage.table.score')} <Num value={item.score} digits={2} />
        </label>
        {renderRowActions(item)}
      </div>
    </div>
  );

  const renderCandidateDetail = (item: ScreeningCandidate) => {
    const factors = getFactorEntries(item);
    const selectionExplanations = getSelectionExplanations(item, t);
    const selectionQuality = item.whySelected?.length
      ? item.explanationQuality?.whySelected || 'unknown'
      : 'unknown';
    const dsaWarnings = [...new Set((item.dsaContext?.warnings || []).map((value) => (
      // 後端的機器碼不直接給人看
      /^[a-z0-9_]+$/.test(value) ? t('screeningPage.detail.partialData') : value
    )))];
    const dsaNews = item.dsaNews || [];
    const dsaEvents = item.dsaEvents || [];
    const signal = getSignal(item, t);
    const reason = getCandidateReason(item, t);
    // 分三層去重：摘要已出現在入選理由就不重複，智慧判斷同摘要也不重複。
    const reasonRepeated = (item.whySelected || []).some((entry) => entry.text.trim() === reason.trim());
    const thesis = item.llmThesis && item.llmThesis.trim() !== reason.trim() ? item.llmThesis : '';
    const risks = [...new Set([...(item.riskFlags || []), ...(item.llmRisks || [])])];
    const riskSummary = formatSignalText(item.riskSummary);

    return (
      <div className="space-y-5" data-testid="screening-candidate-detail">
        {/* 第一層：結論與動作 */}
        <section className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-lg font-semibold text-foreground"><Num kind="price" value={item.price} currency={currency} /></span>
            <Change value={item.changePct}><Num kind="percent" value={item.changePct} /></Change>
            <span className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${getRiskClassName(item.riskLevel)}`}>
              {t('screeningPage.detail.riskIs', { level: getRiskLabel(item.riskLevel, t) })}
            </span>
          </div>
          {reasonRepeated ? null : (
            <DetailBlock title={t('screeningPage.detail.summary')}>
              <p className="mt-1 text-sm leading-6 text-foreground">{reason}</p>
            </DetailBlock>
          )}
          {signal ? (
            <DetailBlock title={t('screeningPage.detail.signal')}>
              <p className="mt-1 text-sm text-foreground">{signal}</p>
            </DetailBlock>
          ) : null}
          <button
            className="rounded-lg border border-cyan/40 px-3 py-1.5 text-xs font-semibold text-cyan transition-colors hover:bg-cyan/10"
            type="button"
            onClick={() => handleAnalyzeCandidate(item)}
          >
            {t('screeningPage.detail.deepAnalyze')}
          </button>
        </section>

        {/* 第二層：為什麼選它 */}
        <section className="space-y-3 border-t border-border/60 pt-4">
          <div data-testid="screening-why-selected" className="rounded-xl border border-border/60 bg-surface/40 px-3 py-2.5">
            <p className="text-xs font-semibold text-foreground">{t('screeningPage.detail.whySelected')}</p>
            <ExplanationItems items={selectionExplanations} emptyText={t('screeningPage.detail.noWhySelected')} t={t} />
            {selectionExplanations.length > 0 ? (
              <p className="mt-2 text-xs text-secondary-text">
                {t('screeningPage.detail.overallQuality', { quality: lookupLabel(EXPLANATION_QUALITY_KEYS, selectionQuality, t) || selectionQuality })}
              </p>
            ) : null}
          </div>
          <div className="rounded-xl border border-border/60 bg-surface/40 px-3 py-2.5">
            <p className="text-xs font-semibold text-foreground">{t('screeningPage.detail.whyNow')}</p>
            <ExplanationItems items={item.whyNow} emptyText={t('screeningPage.detail.noWhyNow')} t={t} />
            {item.whyNow?.length ? (
              <p className="mt-2 text-xs text-secondary-text">
                {t('screeningPage.detail.overallQuality', {
                  quality: lookupLabel(EXPLANATION_QUALITY_KEYS, item.explanationQuality?.whyNow || 'unknown', t) || String(item.explanationQuality?.whyNow),
                })}
              </p>
            ) : null}
          </div>
          {hasLlmInsight(item) ? (
            <DetailBlock title={t('screeningPage.detail.llmInsight')}>
              {thesis ? <p className="mt-1 text-sm leading-6 text-foreground">{thesis}</p> : null}
              <p className="mt-1 text-xs text-secondary-text">
                {t('screeningPage.detail.llmMeta', {
                  sector: item.llmSector || NO_VALUE,
                  theme: item.llmTheme || NO_VALUE,
                  confidence: formatRatioPercent(item.llmConfidence),
                })}
              </p>
            </DetailBlock>
          ) : null}
          <DetailBlock title={t('screeningPage.detail.factors')}>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {factors.length > 0 ? (
                factors.map(([key, value]) => (
                  <div key={key} className="rounded-lg border border-border bg-card px-3 py-2">
                    <span className="block text-xs text-secondary-text">{lookupLabel(FACTOR_KEYS, key, t) || key}</span>
                    <span className="text-sm font-semibold tabular-nums text-foreground">{formatNumber(value)}</span>
                  </div>
                ))
              ) : (
                <span className="text-sm text-secondary-text">{t('screeningPage.detail.noFactors')}</span>
              )}
            </div>
          </DetailBlock>
          <DetailBlock title={t('screeningPage.detail.amount')}>
            <p className="mt-1 text-sm tabular-nums text-foreground">{formatAmount(item.amount, t)}</p>
          </DetailBlock>
        </section>

        {/* 第三層：風險與原始證據 */}
        <section className="space-y-3 border-t border-border/60 pt-4">
          <DetailBlock title={t('screeningPage.detail.riskTags')}>
            <p className="mt-1 text-sm text-foreground">
              {risks.length ? risks.join(t('screeningPage.clauseSeparator')) : t('screeningPage.detail.none')}
            </p>
          </DetailBlock>
          {/* 空陣列 `[]` 格式化後是 null，不顯示空的風險摘要區塊 */}
          {riskSummary ? (
            <DetailBlock title={t('screeningPage.detail.riskSummary')}>
              <p className="mt-1 text-sm text-foreground">{riskSummary}</p>
            </DetailBlock>
          ) : null}
          {item.dsaAnalysisSummary ? (
            <DetailBlock title={t('screeningPage.detail.enrichSummary')}>
              <p className="mt-1 text-sm leading-6 text-foreground">{formatEnrichmentSummary(item.dsaAnalysisSummary, t)}</p>
            </DetailBlock>
          ) : null}
          {item.llmWatchItems?.length ? (
            <DetailBlock title={t('screeningPage.detail.watchItems')}>
              <p className="mt-1 text-sm text-foreground">{item.llmWatchItems.join(t('screeningPage.clauseSeparator'))}</p>
            </DetailBlock>
          ) : null}
          {item.llmCatalysts?.length ? (
            <DetailBlock title={t('screeningPage.detail.catalysts')}>
              <p className="mt-1 text-sm text-foreground">{item.llmCatalysts.join(t('screeningPage.clauseSeparator'))}</p>
            </DetailBlock>
          ) : null}
          <DetailBlock title={t('screeningPage.detail.news')}>
            {dsaNews.length > 0 ? (
              <ul className="mt-1 space-y-1 text-sm text-foreground">
                {dsaNews.slice(0, 3).map((newsItem, newsIndex) => (
                  <li key={`${item.code}-dsa-news-${newsIndex}`}>{newsItem.title || newsItem.snippet || NO_VALUE}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-secondary-text">{t('screeningPage.detail.none')}</p>
            )}
          </DetailBlock>
          <DetailBlock title={t('screeningPage.detail.events')}>
            {dsaEvents.length > 0 ? (
              <ul className="mt-1 space-y-1 text-sm text-foreground">
                {dsaEvents.slice(0, 3).map((eventItem, eventIndex) => (
                  <li key={`${item.code}-dsa-event-${eventIndex}`}>{eventItem.title || eventItem.snippet || NO_VALUE}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-secondary-text">{t('screeningPage.detail.none')}</p>
            )}
          </DetailBlock>
          {dsaWarnings.length > 0 ? (
            <DetailBlock title={t('screeningPage.detail.dataWarnings')}>
              <p className="mt-1 text-sm text-secondary-text">{dsaWarnings.join(t('screeningPage.clauseSeparator'))}</p>
            </DetailBlock>
          ) : null}
        </section>
      </div>
    );
  };

  return (
    <AppPage className="max-w-6xl space-y-6 pb-12 pt-6">
      <PageHeader
        title={t('screeningPage.title')}
        actions={(
          <>
            {isScreeningEnabled ? (
              <Segmented<FormMarket>
                aria-label={t('screeningPage.market')}
                value={market}
                onChange={handleMarketChange}
                options={FORM_MARKETS.map((value) => ({
                  value,
                  label: formatMarketLabel(value, t),
                  disabled: loading,
                }))}
              />
            ) : null}
            <span className="inline-flex w-fit items-center gap-2 rounded-2xl border border-border/70 bg-card/80 px-3 py-1.5 text-sm">
              <span className={`h-2.5 w-2.5 rounded-full ${isScreeningEnabled ? 'bg-success' : 'bg-warning'}`} />
              <span className="font-medium text-secondary-text">{statusText}</span>
            </span>
          </>
        )}
      />

      {statusState === 'loading' ? (
        <InlineAlert variant="info" message={t('screeningPage.statusLoadingMessage')} />
      ) : null}

      {statusState === 'error' ? (
        <InlineAlert
          variant="warning"
          title={t('screeningPage.statusFailedTitle')}
          message={statusError}
          action={
            <Button size="sm" onClick={() => {
              setStatusState('loading');
              setStatusError('');
              setStatusAttempt((attempt) => attempt + 1);
            }}>
              {t('screeningPage.retry')}
            </Button>
          }
        />
      ) : null}

      {statusState === 'ready' && !enabled ? (
        <section data-testid="screening-guide-card" className="rounded-2xl border border-border/80 bg-card/95 p-6 text-center shadow-soft-card">
          <h2 className="text-base font-semibold text-foreground">{t('screeningPage.status.disabled')}</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-secondary-text">{t('screeningPage.enableHint')}</p>
          <Button className="mt-4" isLoading={enabling} loadingText={t('screeningPage.enabling')} onClick={() => void handleEnable()}>
            {t('screeningPage.enable')}
          </Button>
        </section>
      ) : null}

      {statusState === 'ready' && enabled && !available ? (
        <InlineAlert
          variant="warning"
          title={t('screeningPage.status.unavailable')}
          message={t('screeningPage.unavailableHint')}
        />
      ) : null}

      {error ? <InlineAlert variant="danger" title={t('screeningPage.errorTitle')} message={error} /> : null}

      {isScreeningEnabled ? (
        <>
          {/* 條件 */}
          <section className="rounded-2xl border border-border/80 bg-card/95 p-4 shadow-soft-card">
            <h2 className="mb-3 text-sm font-semibold text-foreground">{t('screeningPage.strategy')}</h2>
            {strategyLoadError ? (
              <p className="mb-3 text-xs text-warning">{strategyLoadError}</p>
            ) : null}
            <div role="radiogroup" aria-label={t('screeningPage.strategy')} className="grid gap-3 md:grid-cols-2">
              {marketStrategies.map((item) => {
                const selected = item.id === strategy;
                const conditions = getStrategyConditions(item, market);
                const category = formatStrategyCategory(item.category || item.tag || item.tags?.[0], t);
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    disabled={loading}
                    onClick={() => {
                      historyContextStrategyRef.current = false;
                      setStrategy(item.id);
                    }}
                    className={`rounded-xl border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                      selected ? 'border-cyan bg-cyan/5' : 'border-border/70 hover:bg-hover/50'
                    }`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-semibold text-foreground">{getStrategyName(item, language)}</span>
                      {category ? <span className="shrink-0 text-xs text-secondary-text">{category}</span> : null}
                    </span>
                    <span className="mt-1 block text-xs leading-5 text-secondary-text">{getStrategyDescription(item, language)}</span>
                    {conditions.length > 0 ? (
                      <span data-testid="screening-condition-chips" className="mt-2 flex flex-wrap gap-1.5">
                        {conditions.map((condition) => {
                          const valueText = formatConditionValue(condition, t);
                          return (
                            <span key={condition.key} className="rounded-full border border-border/60 px-2 py-0.5 text-[11px] text-secondary-text">
                              {condition.label}{valueText ? ` ${valueText}` : ''}
                            </span>
                          );
                        })}
                      </span>
                    ) : null}
                  </button>
                );
              })}
              {!selectedStrategy && !loadingStrategies && strategy ? (
                <div className="rounded-xl border border-cyan bg-cyan/5 p-3 text-sm font-semibold text-foreground">
                  {t('screeningPage.customStrategy', { id: strategy })}
                </div>
              ) : null}
            </div>

            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs font-medium text-secondary-text">
                <span>{t('screeningPage.maxResults')}</span>
                <Segmented<string>
                  size="sm"
                  aria-label={t('screeningPage.maxResults')}
                  value={String(maxResults)}
                  onChange={(value) => setMaxResults(Number(value))}
                  options={MAX_RESULT_OPTIONS.map((value) => ({ value: String(value), label: String(value), disabled: loading }))}
                />
              </div>
              <Button
                className="min-w-40"
                isLoading={loading}
                loadingText={t('screeningPage.running')}
                disabled={loading || !strategy.trim()}
                onClick={() => void handleSubmit()}
              >
                <Play className="h-4 w-4" />
                {t('screeningPage.run')}
              </Button>
            </div>
          </section>

          {/* 執行狀態 */}
          {loading || screenMeta ? (
            <section className="rounded-2xl border border-border bg-card/95 p-4 shadow-soft-card">
              <div className="flex items-center gap-3">
                <span className={`grid h-7 w-7 place-items-center rounded-full ${loading ? 'text-cyan' : 'text-success'}`}>
                  {loading ? <CircleAlert className="h-5 w-5" /> : <CheckCircle2 className="h-5 w-5" />}
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold text-foreground">
                    {loading ? t('screeningPage.runningTitle') : t('screeningPage.doneTitle')}
                  </h2>
                  <p className="mt-1 text-xs text-secondary-text">
                    {loading
                      ? `${taskMessage || t('screeningPage.runningFallback')} · ${taskProgress}%`
                      : `${displayedStrategy} · ${formatMarketLabel(resultMarket, t)}`}
                  </p>
                </div>
              </div>
              {loading ? (
                <div
                  role="progressbar"
                  aria-label={t('screeningPage.runningTitle')}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={taskProgress}
                  className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface"
                >
                  <div className="h-full rounded-full bg-cyan transition-all" style={{ width: `${Math.min(100, Math.max(0, taskProgress))}%` }} />
                </div>
              ) : null}

              <details className="mt-3 border-t border-border/70 pt-3 text-xs text-secondary-text">
                <summary className="w-fit cursor-pointer font-medium text-secondary-text">{t('screeningPage.runDetails')}</summary>
                <div className="mt-2 grid gap-1">
                  <span>{t('screeningPage.runDetails.task', { id: activeTaskId ? activeTaskId.slice(0, 12) : NO_VALUE })}</span>
                  <span>{t('screeningPage.runDetails.run', { id: screenMeta?.runId || NO_VALUE })}</span>
                  <span>
                    {t('screeningPage.runDetails.counts', {
                      snapshot: screenMeta?.snapshotCount ?? NO_VALUE,
                      filtered: screenMeta?.afterFilterCount ?? NO_VALUE,
                      candidates: screenMeta?.candidateCount ?? candidates.length,
                    })}
                  </span>
                  <span>
                    {t('screeningPage.runDetails.ranking', {
                      mode: screenMeta?.llmRanked
                        ? t('screeningPage.ranking.llm')
                        : screenMeta ? t('screeningPage.ranking.factor') : NO_VALUE,
                    })}
                    {screenMeta?.llmModelUsed ? ` · ${screenMeta.llmModelUsed}` : ''}
                    {screenMeta?.llmCoverage != null ? ` · ${t('screeningPage.runDetails.coverage', { value: formatRatioPercent(screenMeta.llmCoverage) })}` : ''}
                  </span>
                  {screenMeta?.resultVariantPoolSize ? (
                    <span>
                      {t('screeningPage.runDetails.variant', { pool: screenMeta.resultVariantPoolSize })}
                      {' · '}
                      {screenMeta.resultVariantApplied
                        ? t('screeningPage.runDetails.variantApplied', { slots: screenMeta.resultVariantRotatedSlots ?? 0 })
                        : t('screeningPage.runDetails.variantBase')}
                    </span>
                  ) : null}
                  <span>
                    {t('screeningPage.runDetails.enrich', {
                      done: screenMeta?.dsaEnrichment?.enrichedCount ?? NO_VALUE,
                      total: screenMeta?.dsaEnrichment?.requestedCount ?? NO_VALUE,
                    })}
                  </span>
                </div>
              </details>
            </section>
          ) : null}

          {screenMeta && alertMessages.length > 0 ? (
            <InlineAlert
              variant={llmFailed ? 'warning' : 'info'}
              title={llmFailed ? t('screeningPage.factorAlertTitle') : t('screeningPage.alertTitle')}
              message={<ScreenAlertMessage messages={alertMessages} />}
            />
          ) : null}

          {/* 結果 */}
          {screenMeta ? (
            <section className="rounded-2xl border border-border bg-card/95 p-4 shadow-soft-card">
              <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <h2 className="text-base font-semibold text-foreground">{t('screeningPage.results')}</h2>
                <div className="flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-secondary-text">
                  <Search className="h-4 w-4 text-cyan" />
                  {t('screeningPage.candidateCount', { count: candidates.length })}
                </div>
              </div>

              {universeLabel || screenMeta.snapshotDate || screenMeta.funnel?.length ? (
                <div data-testid="screening-provenance" className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-secondary-text">
                  {universeLabel ? (
                    <span>
                      {t('screeningPage.universe.label', { source: universeLabel })}
                      {screenMeta.universeSize != null ? ` (${formatGroupedNumber(screenMeta.universeSize)})` : ''}
                    </span>
                  ) : null}
                  {screenMeta.snapshotDate ? <span>{t('screeningPage.snapshotDate', { date: screenMeta.snapshotDate })}</span> : null}
                  {screenMeta.funnel?.length ? (
                    <span>{screenMeta.funnel.map((stage) => `${stage.label} ${formatGroupedNumber(stage.count)}`).join(' → ')}</span>
                  ) : null}
                </div>
              ) : null}

              {conditionsChanged ? (
                <p data-testid="screening-conditions-changed" className="mb-3 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
                  {t('screeningPage.conditionsChanged')}
                </p>
              ) : null}

              {batchMessage ? (
                <InlineAlert className="mb-3" variant={batchMessage.variant} message={batchMessage.text} />
              ) : null}

              {selectedCodes.length > 0 ? (
                <div data-testid="screening-batch-bar" className="mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-border/70 bg-surface/60 px-3 py-2 text-xs text-secondary-text">
                  <span>{t('screeningPage.batch.selected', { count: selectedCodes.length })}</span>
                  <Button size="xsm" variant="secondary" disabled={batchBusy} onClick={() => void handleBatchAnalyze()}>
                    {t('screeningPage.batch.analyze')}
                  </Button>
                  <Button size="xsm" variant="secondary" disabled={batchBusy} onClick={() => void handleBatchWatch()}>
                    {t('screeningPage.batch.watch')}
                  </Button>
                  <Button size="xsm" variant="ghost" disabled={batchBusy} onClick={() => setSelectedCodes([])}>
                    {t('screeningPage.batch.clear')}
                  </Button>
                </div>
              ) : null}

              <DataTable<ScreeningCandidate>
                aria-label={t('screeningPage.results')}
                columns={columns}
                rows={sortedCandidates}
                rowKey={(item) => `${item.rank}-${item.code}`}
                sort={sort}
                onSortChange={setSort}
                onRowClick={(item) => setDetailCode(item.code)}
                renderMobileCard={renderMobileCard}
                emptyState={(
                  <div className="rounded-xl border border-dashed border-border bg-surface/70 px-5 py-10 text-center">
                    <p className="text-sm font-medium text-foreground">{t('screeningPage.noCandidates')}</p>
                  </div>
                )}
              />
            </section>
          ) : null}

          <Drawer
            isOpen={Boolean(detailCandidate)}
            onClose={() => setDetailCode(null)}
            title={detailCandidate ? `${detailCandidate.name || detailCandidate.code} ${detailCandidate.code}` : ''}
            width="max-w-xl"
          >
            {detailCandidate ? renderCandidateDetail(detailCandidate) : null}
          </Drawer>

          {/* 熱點 */}
          <section className="rounded-2xl border border-border/80 bg-card/95 p-4 shadow-soft-card">
            <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <h2 className="text-sm font-semibold text-foreground">{t('screeningPage.hotspots')}</h2>
              <div className="flex flex-col items-start gap-2 lg:items-end">
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="secondary" onClick={toggleHotspotsExpanded}>
                    <Bookmark className="h-4 w-4" />
                    {hotspotsExpanded
                      ? t('screeningPage.hotspot.collapse')
                      : t('screeningPage.hotspot.expand', { count: hotspots.length ? ` (${hotspots.length})` : '' })}
                    <ChevronDown className={`h-4 w-4 transition-transform ${hotspotsExpanded ? 'rotate-180' : ''}`} />
                  </Button>
                  {hotspotsExpanded ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      isLoading={loadingHotspots}
                      loadingText={t('screeningPage.hotspot.refreshing')}
                      disabled={loadingHotspots}
                      onClick={() => void loadHotspots(true, market)}
                    >
                      <RefreshCw className="h-4 w-4" />
                      {t('screeningPage.hotspot.refresh')}
                    </Button>
                  ) : null}
                </div>
                {hotspotsUpdatedAt ? (
                  <p className="text-xs text-secondary-text">
                    {t('screeningPage.hotspot.updatedAt', { time: formatHotspotUpdatedAt(hotspotsUpdatedAt, intlLocale, t) })}
                  </p>
                ) : null}
              </div>
            </div>

            {hotspotsExpanded && hotspotError ? (
              <p className="mb-3 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
                {hotspotError}
              </p>
            ) : null}

            {!hotspotsExpanded ? null : hotspots.length === 0 ? (
              hotspotError ? null : (
                <div className="rounded-xl border border-dashed border-border bg-surface/70 px-4 py-6 text-sm text-secondary-text">
                  {t('screeningPage.hotspot.empty')}
                </div>
              )
            ) : (
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                {hotspots.map((item) => {
                  const selected = selectedHotspotTopic === item.topic;
                  const stage = getHotspotStageLabel(item.stage || item.state, t);
                  return (
                    <button
                      key={`${item.topic}-${item.rank ?? ''}`}
                      className={`rounded-xl border px-3 py-3 text-left transition-colors ${
                        selected ? 'border-cyan bg-cyan/5' : 'border-border/80 bg-card hover:bg-hover/50'
                      }`}
                      type="button"
                      onClick={() => handleHotspotSelect(item.topic)}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-foreground">{item.name || item.topic}</p>
                          {stage ? <p className="mt-1 text-[11px] text-secondary-text">{stage}</p> : null}
                        </div>
                        <span className="shrink-0 text-xl font-semibold tabular-nums text-foreground">
                          {formatNumber(item.heatScore, 0)}
                        </span>
                      </div>
                      <div className="mt-3 grid gap-1 text-[11px] text-secondary-text">
                        <span>
                          {t('screeningPage.hotspot.change')}{' '}
                          <Change value={item.changePct}><Num kind="percent" value={item.changePct} /></Change>
                        </span>
                        <span>
                          {t('screeningPage.hotspot.trendPersistence', {
                            trend: formatNumber(item.trendScore, 1),
                            persistence: formatNumber(item.persistenceScore, 1),
                          })}
                        </span>
                        <span>
                          {item.sampleStockCount != null
                            ? `${t('screeningPage.hotspot.coverage', { count: item.sampleStockCount })} · `
                            : ''}
                          {t('screeningPage.hotspot.leaders', { leaders: getHotspotLeadersText(item, t) })}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}

            {hotspotsExpanded && selectedHotspotTopic ? (
              <div className="mt-4 rounded-xl border border-border/80 bg-surface/80 p-4">
                <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">
                      {hotspotDetail?.name || selectedHotspotTopic}
                    </h3>
                    <p className="mt-1 text-xs leading-5 text-secondary-text">
                      {hotspotDetail
                        ? getHotspotSummaryText(hotspotDetail, selectedHotspot, t)
                        : loadingHotspotDetail
                          ? t('screeningPage.hotspot.loadingDetail')
                          : t('screeningPage.hotspot.clickToView')}
                    </p>
                    {hotspotDetail?.canonicalTopic && hotspotDetail.canonicalTopic !== selectedHotspotTopic ? (
                      <p className="mt-1 text-[11px] text-secondary-text">
                        {t('screeningPage.hotspot.canonicalTopic', { topic: hotspotDetail.canonicalTopic })}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      isLoading={searchingHotspotNews}
                      loadingText={t('screeningPage.hotspot.searching')}
                      disabled={loadingHotspotDetail || searchingHotspotNews}
                      onClick={() => void loadHotspotDetail(selectedHotspotTopic, { includeSearch: true })}
                    >
                      <Search className="h-3.5 w-3.5" />
                      {t('screeningPage.hotspot.searchNews')}
                    </Button>
                    {loadingHotspotDetail ? (
                      <span className="w-fit rounded-full bg-cyan/10 px-3 py-1 text-xs font-semibold text-cyan">
                        {t('screeningPage.hotspot.enriching')}
                      </span>
                    ) : null}
                    {hotspotDetail?.qualityStatus ? (
                      <span className="w-fit rounded-full bg-warning/10 px-3 py-1 text-xs font-semibold text-warning">
                        {t('screeningPage.hotspot.qualityIs', { quality: getHotspotQualityLabel(hotspotDetail.qualityStatus, t) })}
                      </span>
                    ) : null}
                    {hotspotDetail?.fallbackUsed || hotspotDetail?.stale ? (
                      <span className="w-fit rounded-full bg-warning/10 px-3 py-1 text-xs font-semibold text-warning">
                        {getHotspotFallbackLabel(hotspotDetail, t)}
                      </span>
                    ) : null}
                    {hotspotDetail?.stockCount != null ? (
                      <span className="w-fit rounded-full bg-surface px-3 py-1 text-xs font-semibold text-secondary-text">
                        {t('screeningPage.hotspot.stockCount', { count: hotspotDetail.stockCount })}
                      </span>
                    ) : null}
                  </div>
                </div>

                {hotspotDetailError ? (
                  <p className="mb-3 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
                    {hotspotDetailError}
                  </p>
                ) : null}

                {hotspotDetail && hasHotspotDetailDegradation(hotspotDetail) ? (
                  <details className="mb-3 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
                    <summary className="cursor-pointer font-semibold">{t('screeningPage.hotspot.degraded')}</summary>
                    <div className="mt-2 space-y-1 leading-5">
                      {(hotspotDetail.missingFields || []).length > 0 ? (
                        <p>{t('screeningPage.hotspot.missingList', { fields: getHotspotMissingFieldLabels(hotspotDetail.missingFields, t).join(t('screeningPage.listSeparator')) })}</p>
                      ) : null}
                      {getHotspotDiagnosticMessages(hotspotDetail.sourceErrors, t).map((message, index) => (
                        <p key={`${message}-${index}`}>{message}</p>
                      ))}
                    </div>
                  </details>
                ) : null}

                {hotspotDetail ? (
                  <div className="grid gap-4 lg:grid-cols-[1fr_1.3fr]">
                    <div>
                      <p className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-secondary-text">
                        <Clock3 className="h-3.5 w-3.5" />
                        {t('screeningPage.hotspot.timeline')}
                      </p>
                      <div className="relative space-y-0 pl-4 before:absolute before:bottom-3 before:left-[5px] before:top-2 before:w-px before:bg-border">
                        {getHotspotRouteItems(hotspotDetail).map((item, index) => (
                          <div key={`${item.title}-${index}`} className="relative pb-4 last:pb-0">
                            <span className="absolute -left-4 top-1 h-2.5 w-2.5 rounded-full border border-border bg-card" />
                            <div className="rounded-lg border border-border/70 bg-card/80 p-3">
                              <p className="text-[11px] font-semibold text-secondary-text">{getRouteTimeLabel(item, intlLocale, t)}</p>
                              <p className="mt-1 text-xs font-semibold text-foreground">{formatHotspotRouteTitle(item.title, t)}</p>
                              <p className="mt-1 text-xs leading-5 text-secondary-text">{formatHotspotRouteDescription(item.description, t)}</p>
                              {item.url ? (
                                <a
                                  className="mt-2 inline-flex text-[11px] font-semibold text-cyan hover:text-foreground"
                                  href={item.url}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  {t('screeningPage.hotspot.viewNews')}
                                </a>
                              ) : null}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <p className="mb-2 text-xs font-semibold text-secondary-text">{t('screeningPage.hotspot.stocks')}</p>
                      <div className="grid gap-2 sm:grid-cols-2">
                        {(hotspotDetail.stocks || []).slice(0, 10).map((stock) => (
                          <div key={`${stock.code || stock.name}`} className="rounded-lg border border-border/70 bg-card/80 p-3">
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0">
                                <p className="truncate text-xs font-semibold text-foreground">{stock.name || stock.code || NO_VALUE}</p>
                                <p className="mt-1 text-[11px] text-secondary-text">{stock.code || NO_VALUE}</p>
                              </div>
                              <div className="flex shrink-0 items-center gap-1">
                                <span className="rounded-full bg-cyan/10 px-2 py-1 text-[11px] font-semibold text-cyan">
                                  {getHotspotRoleLabel(stock.role, t)}
                                </span>
                                {stock.code ? (
                                  <button
                                    type="button"
                                    aria-label={t('screeningPage.table.analyzeNamed', { name: stock.name || stock.code })}
                                    className="inline-flex h-7 items-center gap-1 rounded-full border border-cyan/30 bg-cyan/10 px-2 text-[11px] font-semibold text-cyan transition-colors hover:border-cyan hover:bg-cyan/15 hover:text-foreground"
                                    onClick={() => handleAnalyzeHotspotStock(stock)}
                                  >
                                    <Play className="h-3 w-3" />
                                    {t('screeningPage.table.analyze')}
                                  </button>
                                ) : null}
                              </div>
                            </div>
                            <p className="mt-2 text-[11px] text-secondary-text">
                              {t('screeningPage.hotspot.stockMeta', {
                                change: toFiniteNumber(stock.changePct) === null
                                  ? t('screeningPage.hotspot.noQuote')
                                  : `${formatNumber(stock.changePct)}%`,
                                heat: formatNumber(stock.hotStockScore, 0),
                              })}
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
          </section>

          {/* 最近結果 */}
          <section className="rounded-2xl border border-border/80 bg-card/95 p-4 shadow-soft-card">
            {historyError ? (
              <p className="mb-3 text-xs text-danger">{historyError}</p>
            ) : null}
            {historyRuns.length === 0 ? (
              <p className="py-1 text-xs text-secondary-text">
                {historyLoading ? t('screeningPage.historyLoading') : t('screeningPage.historyEmpty')}
              </p>
            ) : (
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                <Select
                  id="screening-recent-results"
                  className="min-w-0 flex-1"
                  label={t('screeningPage.history')}
                  value={selectedHistoryRunId}
                  placeholder={t('screeningPage.historyPlaceholder')}
                  options={historyRuns.map((run) => {
                    const runStrategy = strategies.find((item) => item.id === run.strategy);
                    const parts = [
                      runStrategy ? getStrategyName(runStrategy, language) : run.strategy,
                      formatMarketLabel(run.market, t),
                      t('screeningPage.historyCount', { count: run.candidateCount ?? 0 }),
                      ...(run.snapshotCount != null ? [t('screeningPage.historySnapshot', { count: run.snapshotCount })] : []),
                      ...(run.llmRanked ? [t('screeningPage.ranking.llm')] : []),
                      formatRunCreatedAt(run.createdAt, intlLocale, t),
                    ];
                    return { value: run.runId, label: parts.join(' · ') };
                  })}
                  onChange={(value) => {
                    setSelectedHistoryRunId(value);
                    if (value) {
                      void handleHistoryRunSelect(value);
                    }
                  }}
                />
                <Button size="sm" variant="ghost" disabled={historyLoading} onClick={() => void loadHistory()}>
                  {historyLoading ? t('screeningPage.history.refreshing') : t('screeningPage.history.refresh')}
                </Button>
              </div>
            )}
          </section>
        </>
      ) : null}
    </AppPage>
  );
};

export default StockScreeningPage;
