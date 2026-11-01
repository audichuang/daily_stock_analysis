import { AlertBellLink } from '../components/alerts/AlertBellLink';
import type React from 'react';
import { Fragment, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { UNSAFE_LocationContext, UNSAFE_NavigationContext } from 'react-router-dom';
import { AlertTriangle, Info, Layers3, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react';
import { decisionSignalsApi } from '../api/decisionSignals';
import { portfolioApi } from '../api/portfolio';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import {
  ApiErrorAlert,
  AppPage,
  Badge,
  Button,
  Card,
  Checkbox,
  Collapsible,
  ConfirmDialog,
  Drawer,
  EmptyState,
  IconButton,
  InlineAlert,
  Input,
  Metric,
  MetricGroup,
  PageHeader,
  Segmented,
  Select,
  Skeleton,
  StatusDot,
  Tooltip,
  useEmbedModeSafe,
} from '../components/common';
import type { DataTableColumn, DataTableRowGroup, SortState } from '../components/common';
import { DataTable } from '../components/common';
import { ActionMenu } from '../components/common/ActionMenu';
import { PortfolioSignalBadge } from '../components/decision-signals/DecisionSignalDisplay';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { formatUiText } from '../i18n/uiText';
import { PORTFOLIO_PAGE_TEXT, PORTFOLIO_TEXT } from '../locales/featureText';
import { PORTFOLIO_W09_TEXT, PORTFOLIO_W10_TEXT } from '../locales/portfolioText';
import { currencyUnitLabel, formatMoneyValue, formatNumber, formatPercent, NO_VALUE } from '../utils/format';
import type { FxRefreshFeedback, PendingEntry, PendingTone, PortfolioEntryParam } from '../utils/portfolioFormat';
import {
  buildFxRefreshFeedback,
  computeTradeAmount,
  formatBrokerOptionLabel,
  formatCashDirectionLabel,
  formatCorporateActionLabel,
  formatLossPct,
  formatMoney,
  formatPct,
  formatPendingGroupLabel,
  formatPositionMoney,
  formatPositionPrice,
  formatSideLabel,
  getCsvCommitVariant,
  getCsvParseVariant,
  getFxBadge,
  getFxRefreshFeedbackVariant,
  getPositionPriceLabel,
  getTodayIso,
  hasPositionPrice,
  mergePendingBySymbol,
  parsePortfolioEntryParam,
  removeSearchParam,
  shortAccountName,
  sortPendingBySeverity,
  splitPendingRows,
} from '../utils/portfolioFormat';
import type { HoldingGroup, HoldingRow, HoldingSortKey } from '../utils/portfolioHoldings';
import {
  buildHoldingRows,
  getCommonScales,
  getConsolidatedFactor,
  getSharedPriceDate,
  groupHoldingRows,
  sortHoldingRows,
} from '../utils/portfolioHoldings';
import type {
  DecisionSignalItem,
  DecisionSignalMarket,
} from '../types/decisionSignals';
import type {
  PortfolioAccountItem,
  PortfolioCashDirection,
  PortfolioCashLedgerListItem,
  PortfolioCorporateActionListItem,
  PortfolioCorporateActionType,
  PortfolioCostMethod,
  PortfolioImportBrokerItem,
  PortfolioImportCommitResponse,
  PortfolioImportParseResponse,
  PortfolioPositionItem,
  PortfolioRiskResponse,
  PortfolioSide,
  PortfolioSnapshotResponse,
  PortfolioTradeListItem,
} from '../types/portfolio';
import { areStockCodesEquivalent, normalizeStockCode } from '../utils/stockCode';
import { parseDecisionSignalDate } from '../utils/decisionSignalTime';
import { buildDecisionActionLabelMap, getDecisionActionLabel } from '../utils/decisionAction';
import { marketToneClass } from '../utils/marketTone';
import { cn } from '../utils/cn';

// 總資產與風險卡的顯示幣別；快照的 total* 仍是 CNY 彙總，換算值只讀 consolidated*。
const PORTFOLIO_DISPLAY_CURRENCY = 'TWD';
const UNCLASSIFIED_SECTOR = 'UNCLASSIFIED';
const DEFAULT_PAGE_SIZE = 20;
const PORTFOLIO_SIGNAL_LOOKUP_CONCURRENCY = 6;
const FALLBACK_BROKERS: PortfolioImportBrokerItem[] = [
  { broker: 'huatai', aliases: [], displayName: '華泰' },
  { broker: 'citic', aliases: ['zhongxin'], displayName: '中信' },
  { broker: 'cmb', aliases: ['cmbchina', 'zhaoshang'], displayName: '招商' },
];

type AccountOption = 'all' | number;
type EventType = 'trade' | 'cash' | 'corporate';
type EntryKind = EventType;

type PendingItem = {
  key: string;
  label: string;
  tone: PendingTone;
  rowKey?: string;
  /** Accounts behind this row; shown in small text when the view spans several accounts. */
  accountNames?: string[];
  action?: { label: string; onClick: () => void };
};

const PENDING_VISIBLE_LIMIT = 5;
/** Same breakpoint PageHeader uses for its compact layout. */
const PORTFOLIO_NARROW_QUERY = '(max-width: 767.98px)';
const PORTFOLIO_FILTER_CLASS =
  'input-surface input-focus-glow h-8 w-full rounded-[var(--radius-control)] border bg-transparent px-3 text-xs transition-all focus:outline-none';
const PORTFOLIO_FILTER_SELECT_CLASS = `${PORTFOLIO_FILTER_CLASS} appearance-none pr-8`;

type RouterNavigator = { replace: (to: { pathname: string; search: string; hash: string }) => void };

/** Current search string without requiring a Router (unit tests render the page bare). */
function readLocationSearch(locationContext: { location?: { search?: string } } | null): string {
  return locationContext?.location?.search ?? (typeof window !== 'undefined' ? window.location.search : '');
}

function buildSnapshotQuery(accountId: number | undefined, costMethod: PortfolioCostMethod) {
  return {
    accountId,
    costMethod,
    includeRealtime: false,
    displayCurrency: PORTFOLIO_DISPLAY_CURRENCY,
    // 基金在帳本外、不屬於單一帳戶，只有全部帳戶視圖才算進總資產。
    includeFunds: accountId === undefined,
  };
}

function buildRiskQuery(accountId: number | undefined, costMethod: PortfolioCostMethod) {
  return { accountId, costMethod, includeRealtime: false, displayCurrency: PORTFOLIO_DISPLAY_CURRENCY };
}

/** 金額帶正負號，損益與今日用。 */
function formatSignedMoney(value: number | null | undefined, currency?: string): string {
  if (value == null || !Number.isFinite(value)) return NO_VALUE;
  const sign = value > 0 ? '+' : '';
  return `${currency ? `${currency} ` : ''}${sign}${formatNumber(value, 2)}`;
}

type FlatPosition = PortfolioPositionItem & {
  accountId: number;
  accountName: string;
};

type PortfolioSignalLookup = {
  stockCode: string;
  market?: DecisionSignalMarket;
};

type PortfolioSignalLookupResult = {
  items: DecisionSignalItem[];
  error: string | null;
};

type PortfolioPageLanguage = 'zh' | 'en' | 'zh-TW';

const PORTFOLIO_LIMITATION_LABELS: Record<string, Record<PortfolioPageLanguage, string>> = {
  realtime_quote_best_effort: {
    zh: '实时行情为尽力获取',
    en: 'Realtime quotes are best-effort',
    'zh-TW': '即時行情為盡力取得',
  },
  fx_and_cost_basis_partial: {
    zh: '汇率与成本基础为部分口径',
    en: 'FX and cost basis are partial',
    'zh-TW': '匯率與成本基礎為部分口徑',
  },
  sector_and_risk_metrics_limited: {
    zh: '行业与风险指标覆盖有限',
    en: 'Sector and risk metrics are limited',
    'zh-TW': '產業與風險指標覆蓋有限',
  },
};

type PendingDelete =
  | { eventType: 'trade'; id: number; message: string }
  | { eventType: 'cash'; id: number; message: string }
  | { eventType: 'corporate'; id: number; message: string };

type PendingAccountDelete = {
  accountId: number;
  accountName: string;
};

type FxRefreshContext = {
  viewKey: string;
  requestId: number;
};

const PORTFOLIO_INPUT_CLASS =
  'input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-4 text-sm transition-all focus:outline-none disabled:cursor-not-allowed disabled:opacity-60';
const PORTFOLIO_SELECT_CLASS = `${PORTFOLIO_INPUT_CLASS} appearance-none pr-10`;
const PORTFOLIO_FILE_PICKER_CLASS =
  'input-surface input-focus-glow flex h-11 w-full cursor-pointer items-center justify-center rounded-xl border bg-transparent px-4 text-sm transition-all focus:outline-none disabled:cursor-not-allowed disabled:opacity-60';
const PORTFOLIO_RISK_DASHBOARD_TEXT = {
  zh: {
    title: '风险与暴露看板',
    riskFlags: '风险旗标',
    marketExposure: '市场暴露',
    currencyExposure: '币种暴露',
    noExposure: '暂无暴露数据',
    exposureUnavailable: '暴露不可用',
    concentration: '个股集中',
    sector: '行业集中',
    drawdown: '回撤',
    stopLoss: '止损',
    aiSignal: 'AI 信号',
    priceQuality: '价格质量',
    active: '需处理',
    stable: '正常',
    unavailable: '不可用',
    incomplete: '不完整',
    maxDrawdown: '最大回撤',
    topPosition: 'Top1',
    topSector: 'Top1',
    triggered: '已触发',
    near: '接近',
    missingPrice: '缺价',
    stalePrice: '过期价',
    positions: '持仓',
    snapshotUnavailable: '持仓快照不可用',
    snapshotUnavailableDescription: '无法确认持仓数量或估值，请刷新重试。',
  },
  en: {
    title: 'Risk and exposure dashboard',
    riskFlags: 'Risk flags',
    marketExposure: 'Market exposure',
    currencyExposure: 'Currency exposure',
    noExposure: 'No exposure data',
    exposureUnavailable: 'Exposure unavailable',
    concentration: 'Position concentration',
    sector: 'Sector concentration',
    drawdown: 'Drawdown',
    stopLoss: 'Stop loss',
    aiSignal: 'AI signals',
    priceQuality: 'Price quality',
    active: 'Needs action',
    stable: 'Normal',
    unavailable: 'Unavailable',
    incomplete: 'Incomplete',
    maxDrawdown: 'Max drawdown',
    topPosition: 'Top1',
    topSector: 'Top1',
    triggered: 'Triggered',
    near: 'Near',
    missingPrice: 'Missing price',
    stalePrice: 'Stale price',
    positions: 'Positions',
    snapshotUnavailable: 'Portfolio snapshot unavailable',
    snapshotUnavailableDescription: 'Holdings and valuation are unknown. Refresh to try again.',
  },
  'zh-TW': {
    title: '風險與曝險看板',
    riskFlags: '風險旗標',
    marketExposure: '市場曝險',
    currencyExposure: '幣別曝險',
    noExposure: '尚無曝險資料',
    exposureUnavailable: '曝險不可用',
    concentration: '個股集中',
    sector: '產業集中',
    drawdown: '回撤',
    stopLoss: '停損',
    aiSignal: 'AI 訊號',
    priceQuality: '價格品質',
    active: '需處理',
    stable: '正常',
    unavailable: '不可用',
    incomplete: '不完整',
    maxDrawdown: '最大回撤',
    topPosition: 'Top1',
    topSector: 'Top1',
    triggered: '已觸發',
    near: '接近',
    missingPrice: '缺價',
    stalePrice: '過期價',
    positions: '持股',
    snapshotUnavailable: '持股快照不可用',
    snapshotUnavailableDescription: '無法確認持股數量或估值，請重新整理再試。',
  },
} as const;

type RiskDashboardText = typeof PORTFOLIO_RISK_DASHBOARD_TEXT[PortfolioPageLanguage];
type PortfolioRiskFlagTone = 'success' | 'warning' | 'danger' | 'neutral';

type PortfolioRiskFlag = {
  key: string;
  label: string;
  value: string;
  detail: string;
  tone: PortfolioRiskFlagTone;
};

type PortfolioRiskAvailability = {
  concentration: boolean;
  sectorConcentration: boolean;
  drawdown: boolean;
  stopLoss: boolean;
  decisionSignalRisk: boolean;
};

type PortfolioExposureRow = {
  key: string;
  label: string;
  value: number;
  weightPct: number;
  count: number;
};

function getSignalTime(item: DecisionSignalItem): number {
  return parseDecisionSignalDate(item.createdAt)?.getTime()
    ?? parseDecisionSignalDate(item.updatedAt)?.getTime()
    ?? 0;
}

function isNewerSignal(left: DecisionSignalItem | undefined, right: DecisionSignalItem): boolean {
  if (!left) return true;
  return getSignalTime(right) > getSignalTime(left);
}

function formatPortfolioLimitation(limitation: string, language: PortfolioPageLanguage): string {
  return PORTFOLIO_LIMITATION_LABELS[limitation]?.[language] ?? limitation;
}

function sumPositionMarketValue(positions: PortfolioPositionItem[]): number {
  return positions.reduce((sum, position) => sum + Number(position.marketValueBase || 0), 0);
}

function hasRiskBlockField(value: unknown, field: string): value is Record<string, unknown> {
  return value != null && typeof value === 'object' && field in value;
}

function hasBooleanField(value: unknown, field: string): value is Record<string, boolean> {
  if (!hasRiskBlockField(value, field)) return false;
  return typeof value[field] === 'boolean';
}

function hasNumberField(value: unknown, field: string): value is Record<string, number> {
  if (!hasRiskBlockField(value, field)) return false;
  return typeof value[field] === 'number' && Number.isFinite(value[field]);
}

function hasFreshFxEvidence(snapshot: PortfolioSnapshotResponse | null): boolean {
  return snapshot !== null
    && snapshot.fxStale === false
    && Array.isArray(snapshot.accounts)
    && snapshot.accounts.every((account) => account.fxStale === false);
}

function hasUsablePositionQuote(position: PortfolioPositionItem): boolean {
  return position.priceAvailable === true
    && hasPositionPrice(position)
    && Number.isFinite(position.lastPrice)
    && position.lastPrice > 0;
}

function hasCompletePositionPriceCoverage(snapshot: PortfolioSnapshotResponse | null): boolean {
  return snapshot !== null
    && Array.isArray(snapshot.accounts)
    && snapshot.accounts.every((account) => (
      Array.isArray(account.positions)
        && account.positions.every(hasUsablePositionQuote)
    ));
}

function getValidTopPositionRows(risk: PortfolioRiskResponse | null) {
  const concentration = risk?.concentration;
  const rows = concentration?.topPositions;
  if (!Array.isArray(rows) || rows.length === 0) return [];
  // Keep the summary, Top1 label and chart on the same complete evidence.
  // Filtering malformed rows could silently promote a different holding to Top1.
  const valid = rows.every((item, index) => (
    typeof item?.symbol === 'string'
      && item.symbol.trim().length > 0
      && typeof item.weightPct === 'number'
      && Number.isFinite(item.weightPct)
      && item.weightPct >= 0
      && item.weightPct <= 100
      && (index === 0 || item.weightPct <= rows[index - 1].weightPct)
  ));
  return valid && rows[0].weightPct > 0 && rows[0].weightPct === concentration?.topWeightPct ? rows : [];
}

function getClassifiedSectorRows(risk: PortfolioRiskResponse | null) {
  const rows = risk?.sectorConcentration?.topSectors;
  if (!Array.isArray(rows) || rows.length === 0) return [];
  // Sector flags, Top1 and pie charts must obey the same ordering/summary
  // contract as position concentration, without silently filtering bad rows.
  const valid = rows.every((item, index) => (
    typeof item?.sector === 'string'
      && item.sector.trim().length > 0
      && item.sector.trim().toUpperCase() !== UNCLASSIFIED_SECTOR
      && typeof item.weightPct === 'number'
      && Number.isFinite(item.weightPct)
      && item.weightPct >= 0
      && item.weightPct <= 100
      && (index === 0 || item.weightPct <= rows[index - 1].weightPct)
  ));
  return valid && rows[0].weightPct > 0 && rows[0].weightPct === risk?.sectorConcentration?.topWeightPct ? rows : [];
}

function hasCompleteSectorCoverage(risk: PortfolioRiskResponse | null) {
  const sectorConcentration = risk?.sectorConcentration;
  if (!sectorConcentration) return false;
  if (!Array.isArray(sectorConcentration.topSectors)) return false;
  if (!Array.isArray(sectorConcentration.errors)) return false;
  const coverage = sectorConcentration.coverage || {};
  if (
    !hasNumberField(coverage, 'classifiedCount')
    || !hasNumberField(coverage, 'unclassifiedCount')
    || !hasNumberField(coverage, 'failedCount')
  ) return false;
  const hasUnclassifiedRows = (sectorConcentration.topSectors || []).some((item) => (
    typeof item?.sector === 'string'
      && item.sector.trim().toUpperCase() === UNCLASSIFIED_SECTOR
      && Number.isFinite(Number(item.weightPct))
      && Number(item.weightPct) > 0
  ));
  const hasInvalidRows = (sectorConcentration.topSectors || []).some((item) => (
    typeof item?.sector !== 'string'
      || item.sector.trim().length === 0
      || typeof item.weightPct !== 'number'
      || !Number.isFinite(item.weightPct)
      || item.weightPct < 0
  ));
  return !hasUnclassifiedRows
    && !hasInvalidRows
    && coverage.classifiedCount > 0
    && coverage.unclassifiedCount === 0
    && coverage.failedCount === 0
    && sectorConcentration.errors.length === 0;
}

function getPortfolioRiskAvailability(
  risk: PortfolioRiskResponse | null,
  snapshot: PortfolioSnapshotResponse | null,
): PortfolioRiskAvailability {
  const concentration = risk?.concentration;
  const sectorConcentration = risk?.sectorConcentration;
  const drawdown = risk?.drawdown;
  const stopLoss = risk?.stopLoss;
  const decisionSignalRisk = risk?.decisionSignalRisk;

  const fxQualityAvailable = hasFreshFxEvidence(snapshot);
  const priceCoverageAvailable = hasCompletePositionPriceCoverage(snapshot);

  return {
    concentration: fxQualityAvailable
      && priceCoverageAvailable
      && hasNumberField(concentration, 'topWeightPct')
      && hasBooleanField(concentration, 'alert')
      && getValidTopPositionRows(risk).length > 0,
    sectorConcentration: fxQualityAvailable
      && priceCoverageAvailable
      && hasNumberField(sectorConcentration, 'topWeightPct')
      && hasBooleanField(sectorConcentration, 'alert')
      && hasCompleteSectorCoverage(risk)
      && getClassifiedSectorRows(risk).length > 0,
    drawdown: hasNumberField(drawdown, 'currentDrawdownPct')
      && hasNumberField(drawdown, 'maxDrawdownPct')
      && hasNumberField(drawdown, 'seriesPoints')
      && drawdown.seriesPoints > 1
      && hasBooleanField(drawdown, 'fxStale')
      && drawdown.fxStale === false
      && drawdown.fxMissing !== true
      && hasBooleanField(drawdown, 'alert'),
    stopLoss: priceCoverageAvailable
      && hasNumberField(stopLoss, 'triggeredCount')
      && hasNumberField(stopLoss, 'nearCount')
      && hasBooleanField(stopLoss, 'nearAlert'),
    decisionSignalRisk: hasBooleanField(decisionSignalRisk, 'available')
      && decisionSignalRisk.available === true
      && hasNumberField(decisionSignalRisk, 'total'),
  };
}

function buildExposureRows(
  snapshot: PortfolioSnapshotResponse | null,
  groupBy: 'market' | 'currency',
): PortfolioExposureRow[] {
  if (!snapshot) return [];
  if (!hasFreshFxEvidence(snapshot)) return [];
  if (!hasCompletePositionPriceCoverage(snapshot)) return [];
  const accounts = snapshot.accounts || [];
  const totalMarketValue = Number(snapshot.totalMarketValue || 0);
  if (!Number.isFinite(totalMarketValue) || totalMarketValue <= 0) return [];
  const snapshotCurrency = String(snapshot.currency || 'CNY').toUpperCase();
  const rawPortfolioValue = accounts.reduce(
    (sum, account) => sum + sumPositionMarketValue(account.positions || []),
    0,
  );
  const valuationCurrencies = new Set<string>();
  for (const account of accounts) {
    for (const position of account.positions || []) {
      const rawValue = position.marketValueBase;
      if (typeof rawValue !== 'number' || !Number.isFinite(rawValue) || rawValue < 0) return [];
      if (rawValue === 0) continue;
      const valuationCurrency = String(position.valuationCurrency || account.baseCurrency || snapshotCurrency).toUpperCase();
      valuationCurrencies.add(valuationCurrency);
    }
  }
  const mixedValuationCurrencies = valuationCurrencies.size > 1;
  const [valuationCurrency = snapshotCurrency] = Array.from(valuationCurrencies);
  const scale = valuationCurrency === snapshotCurrency
    ? 1
    : rawPortfolioValue > 0
      ? totalMarketValue / rawPortfolioValue
      : 0;
  if (!Number.isFinite(scale)) return [];

  const groups = new Map<string, { value: number; symbols: Set<string> }>();
  for (const account of accounts) {
    let accountScale = scale;
    if (mixedValuationCurrencies) {
      const baseCurrency = String(account.baseCurrency).toUpperCase();
      const rawValue = sumPositionMarketValue(account.positions || []);
      if (rawValue === 0 && account.positions.length === 0) continue;
      if (account.positions.some((position) => (
        String(position.valuationCurrency || baseCurrency).toUpperCase() !== baseCurrency
      ))) return [];
      const convertedValue = baseCurrency === snapshotCurrency
        ? rawValue
        : account.totalMarketValueAggregate;
      if (typeof convertedValue !== 'number' || !Number.isFinite(convertedValue)
        || convertedValue < 0) return [];
      if (rawValue === 0 && convertedValue !== 0) return [];
      accountScale = rawValue > 0 ? convertedValue / rawValue : 0;
    }
    for (const position of account.positions || []) {
      const key = String(groupBy === 'market' ? position.market : position.currency || position.valuationCurrency || 'unknown').toUpperCase();
      const current = groups.get(key) ?? { value: 0, symbols: new Set<string>() };
      current.value += Number(position.marketValueBase || 0) * accountScale;
      current.symbols.add(position.symbol);
      groups.set(key, current);
    }
  }
  return Array.from(groups.entries())
    .map(([key, item]) => ({
      key,
      label: key,
      value: item.value,
      weightPct: totalMarketValue > 0 ? (item.value / totalMarketValue) * 100 : 0,
      count: item.symbols.size,
    }))
    .filter((item) => item.value > 0)
    .sort((a, b) => b.value - a.value);
}

/** 各帳戶佔總市值；與市場、幣別條同一組資料品質閘門。 */
function buildAccountExposureRows(snapshot: PortfolioSnapshotResponse | null): PortfolioExposureRow[] {
  if (!snapshot || !hasFreshFxEvidence(snapshot) || !hasCompletePositionPriceCoverage(snapshot)) return [];
  const total = Number(snapshot.totalMarketValue || 0);
  if (!Number.isFinite(total) || total <= 0) return [];
  const snapshotCurrency = String(snapshot.currency).toUpperCase();
  const rows: PortfolioExposureRow[] = [];
  for (const account of snapshot.accounts) {
    const value = String(account.baseCurrency).toUpperCase() === snapshotCurrency
      ? account.totalMarketValue
      : account.totalMarketValueAggregate;
    if (typeof value !== 'number' || !Number.isFinite(value)) return [];
    if (value > 0) {
      rows.push({
        key: String(account.accountId),
        label: account.accountName,
        value,
        weightPct: (value / total) * 100,
        count: new Set((account.positions ?? []).map((position) => position.symbol)).size,
      });
    }
  }
  return rows.sort((a, b) => b.value - a.value);
}

function buildPortfolioRiskFlags(
  risk: PortfolioRiskResponse | null,
  positions: FlatPosition[],
  snapshot: PortfolioSnapshotResponse | null,
  text: RiskDashboardText,
): PortfolioRiskFlag[] {
  const missingPriceCount = positions.filter((position) => !hasUsablePositionQuote(position)).length;
  const stalePriceCount = positions.filter((position) => hasUsablePositionQuote(position) && position.priceStale).length;
  const priceIssueCount = missingPriceCount + stalePriceCount;
  const concentration = risk?.concentration;
  const topPosition = getValidTopPositionRows(risk)[0];
  const sectorConcentration = risk?.sectorConcentration;
  const topClassifiedSector = getClassifiedSectorRows(risk)[0];
  const drawdown = risk?.drawdown;
  const availability = getPortfolioRiskAvailability(risk, snapshot);
  const snapshotAvailable = snapshot !== null;

  return [
    {
      key: 'concentration',
      label: text.concentration,
      value: availability.concentration ? formatPct(concentration?.topWeightPct) : NO_VALUE,
      detail: availability.concentration ? `${text.topPosition}: ${topPosition?.symbol}` : text.unavailable,
      tone: availability.concentration ? (concentration?.alert ? 'danger' : 'success') : 'neutral',
    },
    {
      key: 'sector',
      label: text.sector,
      value: availability.sectorConcentration ? formatPct(topClassifiedSector?.weightPct) : NO_VALUE,
      detail: availability.sectorConcentration ? `${text.topSector}: ${topClassifiedSector?.sector ?? NO_VALUE}` : text.unavailable,
      tone: availability.sectorConcentration ? (sectorConcentration?.alert ? 'danger' : 'success') : 'neutral',
    },
    {
      key: 'drawdown',
      label: text.drawdown,
      value: availability.drawdown ? formatPct(drawdown?.currentDrawdownPct) : NO_VALUE,
      detail: availability.drawdown ? `${text.maxDrawdown}: ${formatPct(drawdown?.maxDrawdownPct)}${drawdown?.dataQuality === 'partial' ? ` (${text.incomplete})` : ''}` : text.unavailable,
      tone: availability.drawdown ? (drawdown?.alert ? 'danger' : 'success') : 'neutral',
    },
    {
      key: 'price-quality',
      label: text.priceQuality,
      value: snapshotAvailable ? String(priceIssueCount) : NO_VALUE,
      detail: snapshotAvailable
        ? `${text.missingPrice}: ${missingPriceCount} · ${text.stalePrice}: ${stalePriceCount}`
        : text.unavailable,
      tone: snapshotAvailable
        ? missingPriceCount > 0 ? 'danger' : stalePriceCount > 0 ? 'warning' : 'success'
        : 'neutral',
    },
  ];
}

function riskFlagBadgeVariant(tone: PortfolioRiskFlagTone): 'success' | 'warning' | 'danger' | 'default' {
  if (tone === 'success') return 'success';
  if (tone === 'warning') return 'warning';
  if (tone === 'danger') return 'danger';
  return 'default';
}

// Available flags render as compact chips; data-flag-* lets tests and styles read the state.
const PortfolioRiskFlagChip: React.FC<{
  flag: PortfolioRiskFlag;
  text: RiskDashboardText;
}> = ({ flag, text }) => (
  <div
    data-flag-key={flag.key}
    data-flag-state={flag.tone}
    className="inline-flex min-w-0 max-w-full items-center gap-2 rounded-xl border border-border/70 bg-surface/55 px-3 py-1.5 text-xs"
  >
    <StatusDot tone={flag.tone} className="h-2 w-2 shrink-0" />
    <span className="shrink-0 font-semibold text-foreground">{flag.label}</span>
    <span className="shrink-0 tabular-nums text-foreground">{flag.value}</span>
    <span className="min-w-0 truncate text-secondary">{flag.detail}</span>
    {flag.tone === 'success' ? null : (
      <Badge variant={riskFlagBadgeVariant(flag.tone)} className="shrink-0">{text.active}</Badge>
    )}
  </div>
);

const PortfolioExposureList: React.FC<{
  title: string;
  rows: PortfolioExposureRow[];
  currency: string;
  emptyLabel: string;
  positionLabel: string;
}> = ({ title, rows, currency, emptyLabel, positionLabel }) => (
  <div className="rounded-xl border border-border/70 bg-surface/45 p-3">
    <h3 className="text-sm font-semibold text-foreground">{title}</h3>
    {rows.length === 0 ? (
      <p className="mt-2 text-xs text-muted-text">{emptyLabel}</p>
    ) : (
      <div className="mt-3 space-y-3">
        {rows.map((row) => (
          <div key={row.key}>
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="font-semibold text-foreground">{row.label}</span>
              <span className="text-secondary">{formatPct(row.weightPct)}</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-border/60">
              <div
                className="h-full rounded-full bg-cyan"
                style={{ width: `${Math.min(100, Math.max(0, row.weightPct))}%` }}
              />
            </div>
            <div className="mt-1 flex justify-between gap-2 text-[11px] text-muted-text">
              <span>{formatMoney(row.value, currency)}</span>
              <span>{positionLabel} {row.count}</span>
            </div>
          </div>
        ))}
      </div>
    )}
  </div>
);

const DECISION_SIGNAL_MARKETS = new Set<DecisionSignalMarket>(['cn', 'hk', 'us', 'jp', 'kr', 'tw']);
type PortfolioAccountMarket = 'cn' | 'hk' | 'us' | 'jp' | 'kr' | 'tw';

function toDecisionSignalMarket(value: string | null | undefined): DecisionSignalMarket | undefined {
  const normalized = String(value || '').toLowerCase();
  return DECISION_SIGNAL_MARKETS.has(normalized as DecisionSignalMarket)
    ? normalized as DecisionSignalMarket
    : undefined;
}

function toPositionSignalLookupKey(stockCode: string, market?: DecisionSignalMarket): string {
  return `${market || ''}:${normalizeStockCode(stockCode).toUpperCase()}`;
}

async function mapWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  mapper: (item: T) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let nextIndex = 0;
  const workerCount = Math.min(Math.max(1, concurrency), items.length);

  await Promise.all(Array.from({ length: workerCount }, async () => {
    while (nextIndex < items.length) {
      const currentIndex = nextIndex;
      nextIndex += 1;
      results[currentIndex] = await mapper(items[currentIndex]);
    }
  }));

  return results;
}

// Server cap for page_size on the decision-signals list endpoint.
const PORTFOLIO_SIGNAL_LIST_PAGE_SIZE = 100;

function signalMatchesLookup(signal: DecisionSignalItem, lookup: PortfolioSignalLookup): boolean {
  const signalMarket = String(signal.market || '').toLowerCase();
  if (lookup.market && signalMarket && lookup.market !== signalMarket) return false;
  return areStockCodesEquivalent(lookup.stockCode, signal.stockCode);
}

/**
 * One grouped list request covers every holding (latest active signal per stock);
 * only holdings it misses fall back to the per-stock latest endpoint. The server's
 * holding filter reads a cached positions table that can lag the snapshot, hence the fallback.
 */
async function fetchPortfolioSignals(
  lookups: PortfolioSignalLookup[],
  accountId: number | undefined,
): Promise<PortfolioSignalLookupResult[]> {
  let listed: DecisionSignalItem[] | null = null;
  try {
    const response = await decisionSignalsApi.list({
      holdingOnly: true,
      groupLatest: true,
      status: 'active',
      accountId,
      pageSize: PORTFOLIO_SIGNAL_LIST_PAGE_SIZE,
    });
    listed = response.items ?? [];
  } catch {
    // The per-stock fallback below reports its own errors.
    listed = null;
  }
  const hits: PortfolioSignalLookupResult[] = [];
  const misses: PortfolioSignalLookup[] = [];
  for (const lookup of lookups) {
    const matched = listed?.filter((signal) => signalMatchesLookup(signal, lookup)) ?? [];
    if (matched.length > 0) {
      hits.push({ items: matched, error: null });
    } else {
      misses.push(lookup);
    }
  }
  const fallback = misses.length > 0
    ? await mapWithConcurrency(misses, PORTFOLIO_SIGNAL_LOOKUP_CONCURRENCY, loadPortfolioSignalLookup)
    : [];
  return [...hits, ...fallback];
}

async function loadPortfolioSignalLookup(lookup: PortfolioSignalLookup): Promise<PortfolioSignalLookupResult> {
  try {
    const response = await decisionSignalsApi.getLatest(lookup.stockCode, {
      market: lookup.market,
      limit: 1,
    });
    return { items: response.items, error: null };
  } catch (err) {
    return { items: [], error: getParsedApiError(err).message };
  }
}

const PortfolioPage: React.FC = () => {
  const { language, t } = useUiLanguage();
  const text = PORTFOLIO_TEXT[language];
  const pageText = PORTFOLIO_PAGE_TEXT[language];
  const riskDashboardText = PORTFOLIO_RISK_DASHBOARD_TEXT[language];
  const w09Text = PORTFOLIO_W09_TEXT[language];
  const w10Text = PORTFOLIO_W10_TEXT[language];
  const embedded = useEmbedModeSafe();
  const narrow = useMediaQuery(PORTFOLIO_NARROW_QUERY);
  const locationContext = useContext(UNSAFE_LocationContext) as {
    location?: { pathname: string; search: string; hash: string };
  } | null;
  const navigationContext = useContext(UNSAFE_NavigationContext) as { navigator?: RouterNavigator } | null;
  // `?entry=` deep link (iOS I07): read once on mount; the matching drawer starts open.
  const [deepLinkEntry, setDeepLinkEntry] = useState<PortfolioEntryParam | null>(
    () => parsePortfolioEntryParam(readLocationSearch(locationContext)),
  );
  const decisionActionLabels = useMemo(() => buildDecisionActionLabelMap(t), [t]);

  // Set page title
  useEffect(() => {
    document.title = text.documentTitle;
  }, [text.documentTitle]);

  const [accounts, setAccounts] = useState<PortfolioAccountItem[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<AccountOption>('all');
  const [showCreateAccount, setShowCreateAccount] = useState(deepLinkEntry === 'account');
  const [accountCreating, setAccountCreating] = useState(false);
  const [accountCreateError, setAccountCreateError] = useState<string | null>(null);
  const [accountCreateSuccess, setAccountCreateSuccess] = useState<string | null>(null);
  const [accountForm, setAccountForm] = useState({
    name: '',
    broker: '',
    market: 'tw' as PortfolioAccountMarket,
    baseCurrency: 'TWD',
  });
  const [costMethod, setCostMethod] = useState<PortfolioCostMethod>('fifo');
  const [snapshot, setSnapshot] = useState<PortfolioSnapshotResponse | null>(null);
  const [risk, setRisk] = useState<PortfolioRiskResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [fxRefreshing, setFxRefreshing] = useState(false);
  const [fxRefreshFeedback, setFxRefreshFeedback] = useState<FxRefreshFeedback | null>(null);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [riskWarning, setRiskWarning] = useState<string | null>(null);
  const [writeWarning, setWriteWarning] = useState<string | null>(null);
  const [portfolioSignals, setPortfolioSignals] = useState<DecisionSignalItem[]>([]);
  const [portfolioSignalsLoading, setPortfolioSignalsLoading] = useState(false);
  const [portfolioSignalsWarning, setPortfolioSignalsWarning] = useState<string | null>(null);
  const [portfolioSignalsRefreshKey, setPortfolioSignalsRefreshKey] = useState(0);
  const portfolioSignalsRequestRef = useRef(0);
  const [positionAnalysisLoadingKey, setPositionAnalysisLoadingKey] = useState<string | null>(null);
  const [positionAnalysisMessage, setPositionAnalysisMessage] = useState<string | null>(null);

  const [entryOpen, setEntryOpen] = useState(deepLinkEntry === 'trade' || deepLinkEntry === 'cash');
  const [entryKind, setEntryKind] = useState<EntryKind>(deepLinkEntry === 'cash' ? 'cash' : 'trade');
  const [importOpen, setImportOpen] = useState(deepLinkEntry === 'import');
  const [entryAccountId, setEntryAccountId] = useState<number | null>(null);
  const [holdingSort, setHoldingSort] = useState<SortState>({ key: 'marketValue', direction: 'desc' });
  const [highlightedRowKey, setHighlightedRowKey] = useState<string | null>(null);
  const holdingsRef = useRef<HTMLDivElement>(null);

  const [brokers, setBrokers] = useState<PortfolioImportBrokerItem[]>([]);
  const [selectedBroker, setSelectedBroker] = useState('huatai');
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvDryRun, setCsvDryRun] = useState(true);
  const [csvParsing, setCsvParsing] = useState(false);
  const [csvCommitting, setCsvCommitting] = useState(false);
  const [csvParseResult, setCsvParseResult] = useState<PortfolioImportParseResponse | null>(null);
  const [csvCommitResult, setCsvCommitResult] = useState<PortfolioImportCommitResponse | null>(null);
  const [pasteText, setPasteText] = useState('');
  const [pasteTradeDate, setPasteTradeDate] = useState(getTodayIso());
  // Both import sections default to a dry run; writing is an explicit opt-in.
  const [pasteDryRun, setPasteDryRun] = useState(true);
  const [pasteParsing, setPasteParsing] = useState(false);
  const [pasteCommitting, setPasteCommitting] = useState(false);
  const [pasteParseResult, setPasteParseResult] = useState<PortfolioImportParseResponse | null>(null);
  const [pasteCommitResult, setPasteCommitResult] = useState<PortfolioImportCommitResponse | null>(null);
  const [brokerLoadWarning, setBrokerLoadWarning] = useState<string | null>(null);

  const [eventType, setEventType] = useState<EventType>('trade');
  const [eventDateFrom, setEventDateFrom] = useState('');
  const [eventDateTo, setEventDateTo] = useState('');
  const [eventSymbol, setEventSymbol] = useState('');
  const [eventSide, setEventSide] = useState<'' | PortfolioSide>('');
  const [eventDirection, setEventDirection] = useState<'' | PortfolioCashDirection>('');
  const [eventActionType, setEventActionType] = useState<'' | PortfolioCorporateActionType>('');
  const [eventPage, setEventPage] = useState(1);
  const [eventTotal, setEventTotal] = useState(0);
  const [eventLoading, setEventLoading] = useState(false);
  const [tradeEvents, setTradeEvents] = useState<PortfolioTradeListItem[]>([]);
  const [cashEvents, setCashEvents] = useState<PortfolioCashLedgerListItem[]>([]);
  const [corporateEvents, setCorporateEvents] = useState<PortfolioCorporateActionListItem[]>([]);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [pendingAccountDelete, setPendingAccountDelete] = useState<PendingAccountDelete | null>(null);
  const [accountDeleteLoading, setAccountDeleteLoading] = useState(false);

  const [tradeForm, setTradeForm] = useState({
    symbol: '',
    tradeDate: getTodayIso(),
    side: 'buy' as PortfolioSide,
    quantity: '',
    price: '',
    fee: '',
    tax: '',
    tradeUid: '',
    note: '',
  });
  const [cashForm, setCashForm] = useState({
    eventDate: getTodayIso(),
    direction: 'in' as PortfolioCashDirection,
    amount: '',
    currency: '',
    note: '',
  });
  const [corpForm, setCorpForm] = useState({
    symbol: '',
    effectiveDate: getTodayIso(),
    actionType: 'cash_dividend' as PortfolioCorporateActionType,
    cashDividendPerShare: '',
    splitRatio: '',
    note: '',
  });

  const queryAccountId = selectedAccount === 'all' ? undefined : selectedAccount;
  const refreshViewKey = `${selectedAccount === 'all' ? 'all' : `account:${selectedAccount}`}:cost:${costMethod}`;
  const refreshContextRef = useRef<FxRefreshContext>({ viewKey: refreshViewKey, requestId: 0 });
  const hasAccounts = accounts.length > 0;
  const selectedAccountItem = selectedAccount === 'all' ? undefined : accounts.find((item) => item.id === selectedAccount);
  const writeBlocked = !selectedAccountItem;
  // 記一筆與匯入在抽屜裡自己選帳戶；刪除紀錄仍只在單一帳戶視圖。
  const writableAccount = accounts.find((item) => item.id === entryAccountId) ?? selectedAccountItem ?? accounts[0];
  const writableAccountId = writableAccount?.id;
  // 後端 record_trade 未帶 currency 時依帳戶市場決定幣別（portfolio_service._default_currency_for_market），這裡照同一張表標價。
  const tradeCurrency = writableAccount
    ? ({ hk: 'HKD', us: 'USD', tw: 'TWD' } as Record<string, string>)[String(writableAccount.market).toLowerCase()] ?? 'CNY'
    : undefined;
  const canDeleteSelectedAccount = Boolean(selectedAccountItem) && !isLoading && !fxRefreshing && !accountDeleteLoading;
  const totalEventPages = Math.max(1, Math.ceil(eventTotal / DEFAULT_PAGE_SIZE));
  const currentEventCount = eventType === 'trade'
    ? tradeEvents.length
    : eventType === 'cash'
      ? cashEvents.length
      : corporateEvents.length;

  const isActiveRefreshContext = (requestedViewKey: string, requestedRequestId: number) => {
    return (
      refreshContextRef.current.viewKey === requestedViewKey
      && refreshContextRef.current.requestId === requestedRequestId
    );
  };

  const loadAccounts = useCallback(async () => {
    try {
      const response = await portfolioApi.getAccounts(false);
      const items = response.accounts || [];
      setAccounts(items);
      setSelectedAccount((prev) => {
        if (items.length === 0) return 'all';
        if (prev !== 'all' && !items.some((item) => item.id === prev)) return items[0].id;
        return prev;
      });
      if (items.length === 0) setShowCreateAccount(true);
    } catch (err) {
      setError(getParsedApiError(err));
    }
  }, []);

  const loadBrokers = useCallback(async () => {
    try {
      const response = await portfolioApi.listImportBrokers();
      const brokerItems = response.brokers || [];
      if (brokerItems.length === 0) {
        setBrokers(FALLBACK_BROKERS);
        setBrokerLoadWarning(pageText.brokerEmpty);
        if (!FALLBACK_BROKERS.some((item) => item.broker === selectedBroker)) {
          setSelectedBroker(FALLBACK_BROKERS[0].broker);
        }
        return;
      }
      setBrokers(brokerItems);
      setBrokerLoadWarning(null);
      if (!brokerItems.some((item) => item.broker === selectedBroker)) {
        setSelectedBroker(brokerItems[0].broker);
      }
    } catch {
      setBrokers(FALLBACK_BROKERS);
      setBrokerLoadWarning(pageText.brokerError);
      if (!FALLBACK_BROKERS.some((item) => item.broker === selectedBroker)) {
        setSelectedBroker(FALLBACK_BROKERS[0].broker);
      }
    }
  }, [pageText.brokerEmpty, pageText.brokerError, selectedBroker]);

  const loadSnapshotAndRisk = useCallback(async () => {
    setIsLoading(true);
    setRiskWarning(null);
    // Run sequentially: both GETs rewrite portfolio_positions server-side, so concurrent calls hit a unique-key violation.
    // Failures stay independent: a risk error only degrades the risk card.
    const snapshotResult = await Promise.allSettled([
      portfolioApi.getSnapshot(buildSnapshotQuery(queryAccountId, costMethod)),
    ]).then(([result]) => result);
    const riskResult = await Promise.allSettled([
      portfolioApi.getRisk(buildRiskQuery(queryAccountId, costMethod)),
    ]).then(([result]) => result);
    if (snapshotResult.status === 'fulfilled') {
      setSnapshot(snapshotResult.value);
      setError(null);
      if (riskResult.status === 'fulfilled') {
        setRisk(riskResult.value);
      } else {
        setRisk(null);
        const parsed = getParsedApiError(riskResult.reason);
        setRiskWarning(parsed.message || pageText.loadError);
      }
    } else {
      setSnapshot(null);
      setRisk(null);
      setError(getParsedApiError(snapshotResult.reason));
    }
    setIsLoading(false);
  }, [queryAccountId, costMethod, pageText.loadError]);

  const loadEventsPage = useCallback(async (page: number) => {
    setEventLoading(true);
    try {
      if (eventType === 'trade') {
        const response = await portfolioApi.listTrades({
          accountId: queryAccountId,
          dateFrom: eventDateFrom || undefined,
          dateTo: eventDateTo || undefined,
          symbol: eventSymbol || undefined,
          side: eventSide || undefined,
          page,
          pageSize: DEFAULT_PAGE_SIZE,
        });
        setTradeEvents(response.items || []);
        setEventTotal(response.total || 0);
      } else if (eventType === 'cash') {
        const response = await portfolioApi.listCashLedger({
          accountId: queryAccountId,
          dateFrom: eventDateFrom || undefined,
          dateTo: eventDateTo || undefined,
          direction: eventDirection || undefined,
          page,
          pageSize: DEFAULT_PAGE_SIZE,
        });
        setCashEvents(response.items || []);
        setEventTotal(response.total || 0);
      } else {
        const response = await portfolioApi.listCorporateActions({
          accountId: queryAccountId,
          dateFrom: eventDateFrom || undefined,
          dateTo: eventDateTo || undefined,
          symbol: eventSymbol || undefined,
          actionType: eventActionType || undefined,
          page,
          pageSize: DEFAULT_PAGE_SIZE,
        });
        setCorporateEvents(response.items || []);
        setEventTotal(response.total || 0);
      }
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setEventLoading(false);
    }
  }, [
    eventActionType,
    eventDateFrom,
    eventDateTo,
    eventDirection,
    eventSide,
    eventSymbol,
    eventType,
    queryAccountId,
  ]);

  const loadEvents = useCallback(async () => {
    await loadEventsPage(eventPage);
  }, [eventPage, loadEventsPage]);

  const refreshPortfolioData = useCallback(async (page = eventPage) => {
    await Promise.all([loadSnapshotAndRisk(), loadEventsPage(page)]);
  }, [eventPage, loadEventsPage, loadSnapshotAndRisk]);

  useEffect(() => {
    void loadAccounts();
    void loadBrokers();
  }, [loadAccounts, loadBrokers]);

  useEffect(() => {
    void loadSnapshotAndRisk();
  }, [loadSnapshotAndRisk]);

  useEffect(() => {
    void loadEvents();
  }, [loadEvents]);

  useEffect(() => {
    refreshContextRef.current = {
      viewKey: refreshViewKey,
      requestId: refreshContextRef.current.requestId + 1,
    };
    setFxRefreshing(false);
    setFxRefreshFeedback(null);
  }, [refreshViewKey]);

  useEffect(() => {
    setEventPage(1);
  }, [eventType, queryAccountId, eventDateFrom, eventDateTo, eventSymbol, eventSide, eventDirection, eventActionType]);

  useEffect(() => {
    if (!writeBlocked) {
      setWriteWarning(null);
    }
  }, [writeBlocked]);

  // Once the deep-linked drawer is closed, drop `entry` from the URL (replace, no history entry).
  useEffect(() => {
    if (!deepLinkEntry || entryOpen || importOpen || showCreateAccount) return;
    const routerLocation = locationContext?.location;
    const navigator = navigationContext?.navigator;
    if (routerLocation && navigator) {
      navigator.replace({
        pathname: routerLocation.pathname,
        search: removeSearchParam(routerLocation.search, 'entry'),
        hash: routerLocation.hash,
      });
    } else if (typeof window !== 'undefined') {
      const { pathname, search, hash } = window.location;
      window.history.replaceState(window.history.state, '', `${pathname}${removeSearchParam(search, 'entry')}${hash}`);
    }
    setDeepLinkEntry(null);
  }, [deepLinkEntry, entryOpen, importOpen, showCreateAccount, locationContext, navigationContext]);

  const positionRows: FlatPosition[] = useMemo(() => {
    if (!snapshot) return [];
    const rows: FlatPosition[] = [];
    for (const account of snapshot.accounts || []) {
      for (const position of account.positions || []) {
        rows.push({
          ...position,
          accountId: account.accountId,
          accountName: account.accountName,
        });
      }
    }
    rows.sort((a, b) => Number(b.marketValueBase || 0) - Number(a.marketValueBase || 0));
    return rows;
  }, [snapshot]);
  // A missing snapshot is unknown, not a successfully loaded empty portfolio.
  const positionCount = snapshot === null ? NO_VALUE : positionRows.length;
  // 只換曝險金額；比例不受幣別影響。缺換算值就維持快照幣別，不混用。
  const displayFactor = useMemo(() => getConsolidatedFactor(snapshot), [snapshot]);
  const exposureCurrency = displayFactor !== null ? (snapshot?.displayCurrency ?? undefined) : snapshot?.currency;
  const exposureTotal = displayFactor !== null ? snapshot?.consolidatedMarketValueBase : snapshot?.totalMarketValue;
  const marketLabel = useCallback((market: string): string => {
    const labels: Record<string, string> = {
      TW: pageText.marketTw, US: pageText.marketUs, CN: pageText.marketCn,
      HK: pageText.marketHk, JP: pageText.marketJp, KR: pageText.marketKr,
    };
    return labels[market.toUpperCase()] ?? market.toUpperCase();
  }, [pageText]);
  const toDisplayExposure = useCallback((rows: PortfolioExposureRow[]) => (
    displayFactor === null ? rows : rows.map((row) => ({ ...row, value: row.value * displayFactor }))
  ), [displayFactor]);
  const exposureEmptyLabel = snapshot !== null && positionRows.length === 0 && hasFreshFxEvidence(snapshot)
    ? riskDashboardText.noExposure
    : riskDashboardText.exposureUnavailable;
  const marketExposureRows = useMemo(
    () => toDisplayExposure(buildExposureRows(snapshot, 'market')).map((row) => ({ ...row, label: marketLabel(row.key) })),
    [marketLabel, snapshot, toDisplayExposure],
  );
  const currencyExposureRows = useMemo(
    () => toDisplayExposure(buildExposureRows(snapshot, 'currency')),
    [snapshot, toDisplayExposure],
  );
  const accountExposureRows = useMemo(
    () => ((snapshot?.accounts?.length ?? 0) > 1 ? toDisplayExposure(buildAccountExposureRows(snapshot)) : []),
    [snapshot, toDisplayExposure],
  );
  const holdingRows = useMemo(() => buildHoldingRows(snapshot), [snapshot]);
  const sortedHoldingRows = useMemo(() => {
    const key = (holdingSort.key === 'weight' ? 'marketValue' : holdingSort.key) as HoldingSortKey;
    return sortHoldingRows(holdingRows, key, holdingSort.direction);
  }, [holdingRows, holdingSort]);
  const holdingScales = useMemo(() => getCommonScales(snapshot), [snapshot]);
  const holdingGroups = useMemo(
    () => groupHoldingRows(sortedHoldingRows, holdingScales?.currency),
    [holdingScales, sortedHoldingRows],
  );
  const sharedPriceDate = useMemo(() => getSharedPriceDate(holdingRows), [holdingRows]);
  // Weights were computed with a stale cross-currency rate: still shown, but flagged in the header.
  const weightFxStale = holdingScales?.fxStale === true && holdingRows.some((row) => row.weightPct !== null);
  const portfolioRiskFlags = useMemo(
    () => buildPortfolioRiskFlags(risk, positionRows, snapshot, riskDashboardText),
    [positionRows, risk, riskDashboardText, snapshot],
  );
  const riskAvailability = useMemo(
    () => getPortfolioRiskAvailability(risk, snapshot),
    [risk, snapshot],
  );
  const topClassifiedSector = useMemo(() => getClassifiedSectorRows(risk)[0], [risk]);
  const concentrationTopWeight = riskAvailability.sectorConcentration
    ? topClassifiedSector?.weightPct
    : riskAvailability.concentration
      ? risk?.concentration?.topWeightPct
      : null;

  const snapshotMatchesAccountScope = useMemo(() => {
    if (!snapshot) return false;
    const snapshotAccountIds = new Set((snapshot.accounts || []).map((account) => account.accountId));
    if (queryAccountId !== undefined) {
      return snapshotAccountIds.size === 1 && snapshotAccountIds.has(queryAccountId);
    }
    return accounts.length === 0 || Number(snapshot.accountCount || 0) === accounts.length;
  }, [accounts.length, queryAccountId, snapshot]);

  const positionSignalLookups = useMemo(() => {
    const lookups = new Map<string, PortfolioSignalLookup>();
    for (const row of positionRows) {
      const stockCode = String(row.symbol || '').trim();
      if (!stockCode) continue;
      const market = toDecisionSignalMarket(row.market);
      const key = toPositionSignalLookupKey(stockCode, market);
      if (!lookups.has(key)) {
        lookups.set(key, { stockCode, market });
      }
    }
    return Array.from(lookups.values());
  }, [positionRows]);

  useEffect(() => {
    const requestId = portfolioSignalsRequestRef.current + 1;
    portfolioSignalsRequestRef.current = requestId;

    if (positionSignalLookups.length === 0 || !snapshotMatchesAccountScope) {
      setPortfolioSignals([]);
      setPortfolioSignalsWarning(null);
      setPortfolioSignalsLoading(false);
      return;
    }

    const isActiveRequest = () => portfolioSignalsRequestRef.current === requestId;

    const loadPortfolioSignals = async () => {
      setPortfolioSignalsLoading(true);
      setPortfolioSignalsWarning(null);
      const results = await fetchPortfolioSignals(positionSignalLookups, queryAccountId);
      if (!isActiveRequest()) return;
      const collected = results.flatMap((result) => result.items);
      const failures = results.flatMap((result) => (result.error ? [result.error] : []));
      setPortfolioSignals(collected);
      setPortfolioSignalsWarning(
        failures.length > 0
          ? (
              collected.length > 0
                ? formatUiText(t('decisionSignals.portfolioPartialWarning'), { message: failures[0] })
                : failures[0]
            )
          : null,
      );
      if (isActiveRequest()) {
        setPortfolioSignalsLoading(false);
      }
    };

    void loadPortfolioSignals();

    return () => {
      portfolioSignalsRequestRef.current += 1;
    };
  }, [portfolioSignalsRefreshKey, positionSignalLookups, queryAccountId, snapshotMatchesAccountScope, t]);

  const signalByRowKey = useMemo(() => {
    const mapped = new Map<string, DecisionSignalItem>();
    for (const row of holdingRows) {
      const rowMarket = String(row.market || '').toLowerCase();
      for (const signal of portfolioSignals) {
        const signalMarket = String(signal.market || '').toLowerCase();
        if (rowMarket && signalMarket && rowMarket !== signalMarket) {
          continue;
        }
        if (!areStockCodesEquivalent(row.symbol, signal.stockCode)) {
          continue;
        }
        if (isNewerSignal(mapped.get(row.key), signal)) {
          mapped.set(row.key, signal);
        }
      }
    }
    return mapped;
  }, [holdingRows, portfolioSignals]);

  const handleAnalyzePosition = async (row: HoldingRow, accountId: number) => {
    setPositionAnalysisLoadingKey(row.key);
    setPositionAnalysisMessage(null);
    setError(null);
    try {
      const task = await portfolioApi.analyzePosition(row.symbol, {
        accountId,
        analysisPhase: 'auto',
        force: false,
      });
      setPositionAnalysisMessage(formatUiText(pageText.analysisSubmitted, { symbol: row.symbol, taskId: task.taskId }));
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setPositionAnalysisLoadingKey(null);
    }
  };

  const openEntry = (kind: EntryKind, accountId?: number, symbol?: string) => {
    setError(null);
    setEntryKind(kind);
    setEntryAccountId(accountId ?? selectedAccountItem?.id ?? null);
    if (symbol) {
      setTradeForm((prev) => ({ ...prev, symbol }));
    }
    setEntryOpen(true);
  };

  const openImport = () => {
    setError(null);
    setEntryAccountId(selectedAccountItem?.id ?? null);
    setImportOpen(true);
  };

  const jumpToRow = (rowKey: string) => {
    setHighlightedRowKey(rowKey);
    const candidates = Array.from(holdingsRef.current?.querySelectorAll<HTMLElement>('[data-row-key]') ?? [])
      .filter((element) => element.getAttribute('data-row-key') === rowKey);
    // 桌機與手機版都在 DOM 裡，捲到看得見的那一個；jsdom 沒有 scrollIntoView。
    const target = candidates.find((element) => element.offsetParent !== null) ?? candidates[0];
    target?.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
  };

  useEffect(() => {
    if (!highlightedRowKey) return undefined;
    const timer = window.setTimeout(() => setHighlightedRowKey(null), 2500);
    return () => window.clearTimeout(timer);
  }, [highlightedRowKey]);

  // 集中度條只讀通過閘門的列，全部列出：Top 6 圓餅會把部分資料畫成 100%。
  const sectorBarRows = useMemo(() => {
    if (!riskAvailability.sectorConcentration) return [];
    return getClassifiedSectorRows(risk)
      .map((item) => ({ name: item.sector, value: Number(item.weightPct || 0) }))
      .filter((item) => item.value > 0);
  }, [risk, riskAvailability.sectorConcentration]);

  const positionBarRows = useMemo(() => {
    if (!riskAvailability.concentration) return [];
    return getValidTopPositionRows(risk)
      .map((item) => ({ name: item.symbol, value: Number(item.weightPct || 0) }))
      .filter((item) => item.value > 0);
  }, [risk, riskAvailability.concentration]);

  const concentrationBarRows = sectorBarRows.length > 0 ? sectorBarRows : positionBarRows;
  const concentrationMode = sectorBarRows.length > 0 ? 'sector' : 'position';

  const handleTradeSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!writableAccountId) {
      setWriteWarning(pageText.writeNeedsAccount);
      return;
    }
    try {
      setWriteWarning(null);
      await portfolioApi.createTrade({
        accountId: writableAccountId,
        symbol: tradeForm.symbol,
        tradeDate: tradeForm.tradeDate,
        side: tradeForm.side,
        quantity: Number(tradeForm.quantity),
        price: Number(tradeForm.price),
        fee: Number(tradeForm.fee || 0),
        tax: Number(tradeForm.tax || 0),
        tradeUid: tradeForm.tradeUid || undefined,
        note: tradeForm.note || undefined,
      });
      await refreshPortfolioData();
      setTradeForm((prev) => ({ ...prev, symbol: '', tradeUid: '', note: '' }));
      setEntryOpen(false);
    } catch (err) {
      setError(getParsedApiError(err));
    }
  };

  const handleCashSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!writableAccountId) {
      setWriteWarning(pageText.writeNeedsAccount);
      return;
    }
    try {
      setWriteWarning(null);
      await portfolioApi.createCashLedger({
        accountId: writableAccountId,
        eventDate: cashForm.eventDate,
        direction: cashForm.direction,
        amount: Number(cashForm.amount),
        currency: cashForm.currency || undefined,
        note: cashForm.note || undefined,
      });
      await refreshPortfolioData();
      setCashForm((prev) => ({ ...prev, note: '' }));
      setEntryOpen(false);
    } catch (err) {
      setError(getParsedApiError(err));
    }
  };

  const handleCorporateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!writableAccountId) {
      setWriteWarning(pageText.writeNeedsAccount);
      return;
    }
    try {
      setWriteWarning(null);
      await portfolioApi.createCorporateAction({
        accountId: writableAccountId,
        symbol: corpForm.symbol,
        effectiveDate: corpForm.effectiveDate,
        actionType: corpForm.actionType,
        cashDividendPerShare: corpForm.cashDividendPerShare ? Number(corpForm.cashDividendPerShare) : undefined,
        splitRatio: corpForm.splitRatio ? Number(corpForm.splitRatio) : undefined,
        note: corpForm.note || undefined,
      });
      await refreshPortfolioData();
      setCorpForm((prev) => ({ ...prev, symbol: '', note: '' }));
      setEntryOpen(false);
    } catch (err) {
      setError(getParsedApiError(err));
    }
  };

  const handleParseCsv = async () => {
    if (!csvFile) return;
    try {
      setCsvParsing(true);
      const parsed = await portfolioApi.parseCsvImport(selectedBroker, csvFile);
      setCsvParseResult(parsed);
      setCsvCommitResult(null);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setCsvParsing(false);
    }
  };

  const handleCommitCsv = async () => {
    if (!csvFile) return;
    if (!writableAccountId) {
      setWriteWarning(pageText.writeNeedsAccount);
      return;
    }
    try {
      setWriteWarning(null);
      setCsvCommitting(true);
      const committed = await portfolioApi.commitCsvImport(writableAccountId, selectedBroker, csvFile, csvDryRun);
      setCsvCommitResult(committed);
      if (!csvDryRun) {
        await refreshPortfolioData();
      }
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setCsvCommitting(false);
    }
  };

  const handleParsePaste = async () => {
    if (!pasteText.trim()) return;
    if (!writableAccountId) {
      setWriteWarning(pageText.writeNeedsAccount);
      return;
    }
    try {
      setWriteWarning(null);
      setPasteParsing(true);
      setPasteParseResult(await portfolioApi.parseTextImport(writableAccountId, pasteText, pasteTradeDate));
      setPasteCommitResult(null);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setPasteParsing(false);
    }
  };

  const handleCommitPaste = async () => {
    if (!pasteText.trim()) return;
    if (!writableAccountId) {
      setWriteWarning(pageText.writeNeedsAccount);
      return;
    }
    try {
      setWriteWarning(null);
      setPasteCommitting(true);
      const committed = await portfolioApi.commitTextImport(writableAccountId, pasteText, pasteTradeDate, pasteDryRun);
      setPasteCommitResult(committed);
      if (!pasteDryRun) {
        await refreshPortfolioData();
      }
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setPasteCommitting(false);
    }
  };

  // 券商库存表没有成本：把解析结果改写成「代号 股数 成本 日期」范本，缺成本的行留空待填。
  const handlePasteToTemplate = () => {
    if (!pasteParseResult) return;
    const ready = pasteParseResult.records.map((r) => `${r.symbol} ${r.quantity} ${r.price} ${r.tradeDate}`);
    const pending = (pasteParseResult.missingCost ?? []).map((r) => `${r.symbol} ${r.quantity} `);
    setPasteText([...ready, ...pending].join('\n'));
    setPasteParseResult(null);
  };

  const openDeleteDialog = (item: PendingDelete) => {
    if (writeBlocked) {
      setWriteWarning(pageText.deleteHintBlocked);
      return;
    }
    setPendingDelete(item);
  };

  const openAccountDeleteDialog = () => {
    if (!selectedAccountItem) {
      setWriteWarning(pageText.deleteHintBlocked);
      return;
    }
    setPendingAccountDelete({
      accountId: selectedAccountItem.id,
      accountName: selectedAccountItem.name,
    });
  };

  const handleConfirmAccountDelete = async () => {
    if (!pendingAccountDelete || accountDeleteLoading) return;

    try {
      setAccountDeleteLoading(true);
      setWriteWarning(null);
      await portfolioApi.deleteAccount(pendingAccountDelete.accountId);
      const nextAccount = accounts.find((item) => item.id !== pendingAccountDelete.accountId);
      setSelectedAccount(nextAccount?.id ?? 'all');
      setPendingAccountDelete(null);
      setShowCreateAccount(!nextAccount);
      await loadAccounts();
      setEventPage(1);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setAccountDeleteLoading(false);
    }
  };

  const handleConfirmDelete = async () => {
    if (!pendingDelete || deleteLoading) return;
    if (writeBlocked) {
      setWriteWarning(pageText.deleteHintBlocked);
      setPendingDelete(null);
      return;
    }

    const nextPage = currentEventCount === 1 && eventPage > 1 ? eventPage - 1 : eventPage;
    try {
      setDeleteLoading(true);
      setWriteWarning(null);
      if (pendingDelete.eventType === 'trade') {
        await portfolioApi.deleteTrade(pendingDelete.id);
      } else if (pendingDelete.eventType === 'cash') {
        await portfolioApi.deleteCashLedger(pendingDelete.id);
      } else {
        await portfolioApi.deleteCorporateAction(pendingDelete.id);
      }
      setPendingDelete(null);
      if (nextPage !== eventPage) {
        setEventPage(nextPage);
      }
      await refreshPortfolioData(nextPage);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setDeleteLoading(false);
    }
  };

  const handleCreateAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = accountForm.name.trim();
    if (!name) {
      setAccountCreateError(pageText.createNameEmpty);
      setAccountCreateSuccess(null);
      return;
    }
    try {
      setAccountCreating(true);
      setAccountCreateError(null);
      setAccountCreateSuccess(null);
      const created = await portfolioApi.createAccount({
        name,
        broker: accountForm.broker.trim() || undefined,
        market: accountForm.market,
        baseCurrency: accountForm.baseCurrency.trim() || PORTFOLIO_DISPLAY_CURRENCY,
      });
      await loadAccounts();
      setSelectedAccount(created.id);
      setShowCreateAccount(false);
      setWriteWarning(null);
      setAccountForm({
        name: '',
        broker: '',
        market: accountForm.market,
        baseCurrency: accountForm.baseCurrency,
      });
      setAccountCreateSuccess(pageText.createOkMessage);
    } catch (err) {
      const parsed = getParsedApiError(err);
      setAccountCreateError(parsed.message || pageText.createFailRetry);
      setAccountCreateSuccess(null);
    } finally {
      setAccountCreating(false);
    }
  };

  const handleRefresh = async () => {
    await Promise.all([loadAccounts(), loadSnapshotAndRisk(), loadEvents(), loadBrokers()]);
    setPortfolioSignalsRefreshKey((current) => current + 1);
  };

  const reloadSnapshotAndRiskForScope = useCallback(async (
    requestedViewKey: string,
    requestedRequestId: number,
    requestedAccountId: number | undefined,
    requestedCostMethod: PortfolioCostMethod,
  ): Promise<boolean> => {
    if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
      return false;
    }

    setRiskWarning(null);

    try {
      const snapshotData = await portfolioApi.getSnapshot(buildSnapshotQuery(requestedAccountId, requestedCostMethod));
      if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
        return false;
      }
      setSnapshot(snapshotData);
      setError(null);

      try {
        const riskData = await portfolioApi.getRisk(buildRiskQuery(requestedAccountId, requestedCostMethod));
        if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
          return false;
        }
        setRisk(riskData);
        setRiskWarning(null);
      } catch (riskErr) {
        if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
          return false;
        }
        setRisk(null);
        const parsed = getParsedApiError(riskErr);
        setRiskWarning(parsed.message || pageText.loadError);
      }
      return true;
    } catch (err) {
      if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
        return false;
      }
      setSnapshot(null);
      setRisk(null);
      setError(getParsedApiError(err));
      return false;
    }
  }, [pageText.loadError]);

  const handleRefreshFx = async () => {
    if (!hasAccounts || isLoading || fxRefreshing) {
      return;
    }

    const requestedViewKey = refreshViewKey;
    const requestedAccountId = queryAccountId;
    const requestedCostMethod = costMethod;
    const requestedRequestId = refreshContextRef.current.requestId + 1;
    refreshContextRef.current = {
      viewKey: requestedViewKey,
      requestId: requestedRequestId,
    };

    try {
      setFxRefreshing(true);
      setFxRefreshFeedback(null);
      const result = await portfolioApi.refreshFx({
        accountId: requestedAccountId,
      });
      if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
        return;
      }
      const reloaded = await reloadSnapshotAndRiskForScope(
        requestedViewKey,
        requestedRequestId,
        requestedAccountId,
        requestedCostMethod,
      );
      if (!reloaded || !isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
        return;
      }
      setFxRefreshFeedback(buildFxRefreshFeedback(result, language));
    } catch (err) {
      if (!isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
        return;
      }
      setError(getParsedApiError(err));
    } finally {
      if (isActiveRefreshContext(requestedViewKey, requestedRequestId)) {
        setFxRefreshing(false);
      }
    }
  };

  const formatDecisionSignalRiskAction = (signal: Partial<DecisionSignalItem>): string => (
    getDecisionActionLabel(
      signal.action,
      signal.actionLabel,
      null,
      text.alert,
      decisionActionLabels,
    ) ?? text.alert
  );

  const findRowKey = (symbol: string): string | undefined => (
    holdingRows.find((row) => areStockCodesEquivalent(row.symbol, symbol))?.key
  );

  // Pending lists anomalies only (hidden when empty): one row per holding, most severe first.
  const accountNameById = new Map((snapshot?.accounts ?? []).map((account) => [account.accountId, account.accountName]));
  const holdingNameOf = (symbol: string): string | null => (
    holdingRows.find((row) => areStockCodesEquivalent(row.symbol, symbol))?.name || null
  );
  const pendingEntries: PendingEntry[] = [];
  if (riskAvailability.stopLoss) {
    for (const item of risk?.stopLoss?.items ?? []) {
      pendingEntries.push({
        symbol: item.symbol,
        tone: item.isTriggered ? 'danger' : 'warning',
        text: formatUiText(item.isTriggered ? w10Text.pendingStopTriggered : w10Text.pendingStopNear, {
          pct: formatLossPct(item.lossPct),
        }),
        name: holdingNameOf(item.symbol),
        accountName: accountNameById.get(item.accountId) ?? null,
        rowKey: findRowKey(item.symbol),
      });
    }
  }
  if (riskAvailability.decisionSignalRisk) {
    for (const item of risk?.decisionSignalRisk?.items ?? []) {
      pendingEntries.push({
        symbol: item.symbol,
        tone: 'warning',
        text: formatUiText(w10Text.pendingAi, { action: formatDecisionSignalRiskAction(item.signal) }),
        name: holdingNameOf(item.symbol),
        accountName: item.accountId != null ? accountNameById.get(item.accountId) ?? null : null,
        rowKey: findRowKey(item.symbol),
      });
    }
  }
  for (const row of holdingRows) {
    if (!hasPositionPrice(row)) {
      pendingEntries.push({
        symbol: row.symbol,
        tone: 'warning',
        text: w10Text.pendingMissingPrice,
        name: row.name || null,
        rowKey: row.key,
      });
    }
  }
  const pendingItems: PendingItem[] = mergePendingBySymbol(pendingEntries).map((group) => ({
    key: group.key,
    label: formatPendingGroupLabel(group),
    tone: group.tone,
    rowKey: group.rowKey,
    accountNames: group.accountNames,
  }));
  // Every account with negative cash folds into one row; backfill opens the first one.
  const negativeCashAccounts = (snapshot?.accounts ?? []).filter((account) => account.totalCash < 0);
  if (negativeCashAccounts.length > 0) {
    pendingItems.push({
      key: 'negative-cash',
      label: formatUiText(w10Text.pendingNegativeCash, {
        accounts: negativeCashAccounts
          .map((account) => formatUiText(w10Text.pendingCashAccount, {
            account: account.accountName,
            amount: formatMoney(account.totalCash, account.baseCurrency),
          }))
          .join('、'),
      }),
      tone: 'warning',
      action: {
        label: pageText.pendingBackfill,
        onClick: () => {
          setCashForm((prev) => ({ ...prev, direction: 'in' }));
          openEntry('cash', negativeCashAccounts[0].accountId);
        },
      },
    });
  }
  const sortedPendingItems = sortPendingBySeverity(pendingItems);
  const { visible: visiblePendingItems, hidden: hiddenPendingItems } = splitPendingRows(sortedPendingItems, PENDING_VISIBLE_LIMIT);

  // 有幣別對查無匯率時，換算總額不能用。帶 displayCurrency 的快照只讀 consolidated*，不退回 CNY 彙總。
  const hasConsolidated = Boolean(snapshot?.displayCurrency);
  const fxMissing = snapshot?.fxMissing === true || snapshot?.consolidatedFxMissing === true;
  const fxMissingPairs = Array.from(new Set([
    ...(snapshot?.fxMissingPairs ?? []),
    ...(snapshot?.consolidatedFxMissingPairs ?? []),
  ]));
  const fxStale = hasConsolidated ? snapshot?.consolidatedFxStale : snapshot?.fxStale;
  const summaryCurrency = hasConsolidated ? (snapshot?.displayCurrency ?? undefined) : snapshot?.currency;
  const pickAmount = (consolidated: number | null | undefined, legacy: number | null | undefined): number | null => {
    if (hasConsolidated) return consolidated ?? null;
    return fxMissing ? null : legacy ?? null;
  };
  const equityAmount = pickAmount(snapshot?.consolidatedEquityBase, snapshot?.totalEquity);
  const marketValueAmount = pickAmount(snapshot?.consolidatedMarketValueBase, snapshot?.totalMarketValue);
  const cashAmount = pickAmount(snapshot?.consolidatedCashBase, snapshot?.totalCash);
  const unrealizedAmount = pickAmount(snapshot?.consolidatedUnrealizedPnlBase, snapshot?.unrealizedPnl);
  const realizedAmount = pickAmount(snapshot?.consolidatedRealizedPnlBase, snapshot?.realizedPnl);
  const stockDayAmount = pickAmount(snapshot?.consolidatedDayPnlBase, snapshot?.dayPnl);
  const fundValue = snapshot?.consolidatedFundValueBase ?? null;
  const fundDay = snapshot?.consolidatedFundDayPnlBase ?? null;
  const hasFunds = fundValue !== null && fundValue > 0;
  const fundsUnavailable = hasConsolidated && selectedAccount === 'all' && fundValue === null;
  // 總資產＝帳本權益＋基金；基金讀不到時只算帳本並明講，不把缺值當 0。
  const totalAssets = equityAmount !== null && fundValue !== null ? equityAmount + fundValue : equityAmount;
  // 基金有市值卻讀不到當日損益時整體未知，不能只顯示帳本那一半當作總損益。
  const dayAmount = hasFunds && fundDay === null
    ? null
    : (stockDayAmount !== null && fundDay !== null ? stockDayAmount + fundDay : stockDayAmount);
  // 單一帳戶且帳戶幣別不是顯示幣別（例如 USD 複委託）：主值用帳戶原幣，hint 附換算後的約當值。
  const singleAccount = selectedAccount !== 'all' && snapshot?.accounts?.length === 1 ? snapshot.accounts[0] : null;
  const accountCurrency = singleAccount ? String(singleAccount.baseCurrency).toUpperCase() : null;
  const useAccountCurrency = Boolean(
    singleAccount && hasConsolidated && accountCurrency && accountCurrency !== String(summaryCurrency ?? '').toUpperCase(),
  );
  const metricCurrency = useAccountCurrency ? (accountCurrency ?? undefined) : summaryCurrency;
  const metricUnit = currencyUnitLabel(metricCurrency) || undefined;
  /** Summary money without the currency prefix (Metric renders it as `unit`); TWD has no decimals. */
  const moneyDigits = (value: number, currency: string | undefined, signed = false): string => (
    `${signed && value > 0 ? '+' : ''}${formatMoneyValue(value, currency, {})}`
  );
  /** Full summary money with the unit prefix, for hints. */
  const moneyLabel = (value: number, currency: string | undefined, signed = false): string => {
    const unit = currencyUnitLabel(currency);
    return `${unit ? `${unit} ` : ''}${moneyDigits(value, currency, signed)}`;
  };
  const approxHint = (consolidated: number | null): string | undefined => (
    useAccountCurrency && consolidated !== null
      ? formatUiText(w09Text.approx, { amount: moneyLabel(consolidated, summaryCurrency) })
      : undefined
  );
  // 帳戶自己缺匯率時，原幣 total* 已含 1:1 冒充的數字，不能當真值顯示。
  const accountFxMissing = useAccountCurrency && singleAccount?.fxMissing === true;
  const pickMetric = (accountValue: number | null | undefined, consolidated: number | null): number | null => (
    useAccountCurrency
      ? (!accountFxMissing && typeof accountValue === 'number' && Number.isFinite(accountValue) ? accountValue : null)
      : consolidated
  );
  const showFxMissingText = fxMissing && (!useAccountCurrency || accountFxMissing);
  const amountText = (value: number | null): string => {
    if (value !== null) return moneyDigits(value, metricCurrency);
    return showFxMissingText ? text.fxMissingTotal : NO_VALUE;
  };
  const signedNode = (value: number | null): React.ReactNode => (
    value === null
      ? (showFxMissingText ? text.fxMissingTotal : NO_VALUE)
      : <span className={marketToneClass(value)}>{moneyDigits(value, metricCurrency, true)}</span>
  );
  const metricUnitFor = (value: number | null): string | undefined => (value === null ? undefined : metricUnit);
  const joinHints = (parts: Array<string | undefined | false | null>): string | undefined => {
    const kept = parts.filter((part): part is string => Boolean(part));
    return kept.length > 0 ? kept.join(' · ') : undefined;
  };

  const metricTotal = pickMetric(singleAccount?.totalEquity, totalAssets);
  const metricDayValue = pickMetric(singleAccount?.dayPnl, dayAmount);
  const metricUnrealizedValue = pickMetric(singleAccount?.unrealizedPnl, unrealizedAmount);
  const metricRealizedValue = pickMetric(singleAccount?.realizedPnl, realizedAmount);
  const metricMarketValue = pickMetric(singleAccount?.totalMarketValue, marketValueAmount);
  const metricCashValue = pickMetric(singleAccount?.totalCash, cashAmount);
  // 報價日不是今天（假日、盤前）就把「今日」改成報價日，避免把前一交易日損益當成今天的。
  const quoteDateIsToday = !sharedPriceDate || sharedPriceDate === getTodayIso();
  const dayLabel = quoteDateIsToday
    ? pageText.metricDay
    : formatUiText(w09Text.dayPnlOn, { date: (sharedPriceDate ?? '').slice(5).replace('-', '/') });
  const dayBreakdown = selectedAccount === 'all' && hasFunds && stockDayAmount !== null && fundDay !== null
    ? formatUiText(w09Text.dayBreakdown, {
        stock: moneyDigits(stockDayAmount, summaryCurrency, true),
        fund: moneyDigits(fundDay, summaryCurrency, true),
      })
    : undefined;
  const showFundCard = hasFunds || fundsUnavailable;

  const snapshotQualityMessage = snapshot?.dataQuality === 'partial' && snapshot.limitations?.length
    ? snapshot.limitations
      .map((limitation) => formatPortfolioLimitation(limitation, language))
      .join(language === 'en' ? '; ' : '；')
    : null;

  const snapshotFailed = !isLoading && snapshot === null;
  const riskFailed = Boolean(riskWarning);
  const riskLoading = isLoading && risk === null && !riskFailed;
  const showAccountNames = (snapshot?.accounts?.length ?? 0) > 1;

  // 小計依組內幣別：同幣就是原幣；只剩快照彙總幣別時才換到顯示幣別。
  const subtotalAmount = (value: number | null, currency: string | null): { value: number | null; currency?: string } => {
    if (value === null || currency === null) return { value: null };
    if (displayFactor !== null && currency === String(snapshot?.currency ?? '').toUpperCase()) {
      return { value: value * displayFactor, currency: snapshot?.displayCurrency ?? undefined };
    }
    return { value, currency };
  };

  const rowMenuItems = (row: HoldingRow) => [
    ...row.sources.map((source) => ({
      key: `analyze-${source.accountId}`,
      label: row.sources.length > 1
        ? formatUiText(pageText.analyzeInAccount, { account: source.accountName })
        : text.analyze,
      disabled: positionAnalysisLoadingKey === row.key,
      onSelect: () => void handleAnalyzePosition(row, source.accountId),
    })),
    {
      key: 'record',
      label: pageText.recordEntry,
      onSelect: () => openEntry('trade', row.sources[0]?.accountId, row.symbol),
    },
  ];

  const pnlNode = (row: HoldingRow) => {
    const priced = hasPositionPrice(row);
    return (
      <div data-testid="holding-pnl" className={priced ? marketToneClass(row.unrealizedPnlBase) : 'text-secondary'}>
        <div>{priced ? formatSignedMoney(row.unrealizedPnlBase, row.valuationCurrency) : NO_VALUE}</div>
        <div className="text-[11px]">{priced ? formatPercent(row.unrealizedPnlPct) : NO_VALUE}</div>
      </div>
    );
  };

  const holdingColumns: DataTableColumn<HoldingRow>[] = [
    {
      key: 'name',
      header: pageText.colName,
      sortable: true,
      minWidth: 180,
      render: (row) => (
        <div className="min-w-0">
          <div className="truncate text-foreground">{row.name || row.symbol}</div>
          <div className="flex items-center gap-1 text-[11px] text-secondary">
            {row.name ? <span className="font-mono">{row.symbol}</span> : null}
            {showAccountNames ? <span className="truncate">{row.sources.map((source) => source.accountName).join('、')}</span> : null}
            <AlertBellLink code={row.symbol} className="align-middle" />
          </div>
        </div>
      ),
    },
    {
      key: 'marketValue',
      header: pageText.colValue,
      numeric: true,
      sortable: true,
      render: (row) => formatPositionMoney(row.marketValueBase, row),
    },
    {
      key: 'weight',
      header: weightFxStale ? (
        <span className="inline-flex items-center gap-1">
          {pageText.colWeight}
          <Badge variant="warning">{w09Text.weightFxStale}</Badge>
        </span>
      ) : pageText.colWeight,
      numeric: true,
      sortable: true,
      render: (row) => (row.weightPct === null ? NO_VALUE : formatPct(row.weightPct)),
    },
    {
      key: 'price',
      header: sharedPriceDate ? formatUiText(pageText.colPriceOn, { date: sharedPriceDate }) : pageText.colPrice,
      numeric: true,
      render: (row) => (
        <div>
          <div>{formatPositionPrice(row)}</div>
          <div className="flex justify-end gap-1 text-[11px] text-secondary">
            <span>{pageText.costPrefix} {formatNumber(row.avgCost)}</span>
            {!hasPositionPrice(row) || row.priceStale ? (
              <span className="text-warning">{getPositionPriceLabel(row, language)}</span>
            ) : null}
          </div>
        </div>
      ),
    },
    { key: 'pnl', header: pageText.colPnl, numeric: true, sortable: true, render: pnlNode },
    {
      key: 'ai',
      header: pageText.colAi,
      align: 'right',
      render: (row) => <PortfolioSignalBadge item={signalByRowKey.get(row.key)} loading={portfolioSignalsLoading} />,
    },
    {
      key: 'menu',
      header: '',
      align: 'right',
      render: (row) => (
        <ActionMenu
          label={formatUiText(pageText.rowMenu, { symbol: row.symbol })}
          size="sm"
          items={rowMenuItems(row)}
        />
      ),
    },
  ];

  const holdingRowGroups: DataTableRowGroup<HoldingRow>[] = holdingGroups.map((group: HoldingGroup) => {
    const value = subtotalAmount(group.value, group.currency);
    const pnl = subtotalAmount(group.pnl, group.currency);
    const label = formatUiText(pageText.groupSummary, { label: marketLabel(group.market), count: group.rows.length });
    return {
      key: group.market,
      rows: group.rows,
      summaryCells: {
        name: label,
        marketValue: value.value === null ? NO_VALUE : formatMoney(value.value, value.currency),
        weight: group.weightPct === null ? NO_VALUE : formatPct(group.weightPct),
        pnl: (
          <div className={pnl.value === null ? 'text-secondary' : marketToneClass(pnl.value)}>
            <div>{formatSignedMoney(pnl.value, pnl.currency)}</div>
            <div className="text-[11px]">{formatPercent(group.pnlPct)}</div>
          </div>
        ),
      },
      mobileSummary: (
        <div className="flex items-center justify-between gap-3">
          <span>{label}</span>
          <span className="tabular-nums">{value.value === null ? NO_VALUE : formatMoney(value.value, value.currency)}</span>
        </div>
      ),
    };
  });

  const holdingMobileSort = (holdingSort.key === 'weight' ? 'marketValue' : holdingSort.key) as HoldingSortKey;

  // 手機兩行：名稱＋AI 標籤 …… 市值；代號 · 佔比 …… 損益 · ％。AI 標籤不跟名稱一起被截斷。
  const renderHoldingMobileCard = (row: HoldingRow) => (
    <div className="flex items-center gap-2 px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2 text-sm">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-foreground">{row.name || row.symbol}</span>
            <span className="shrink-0">
              <PortfolioSignalBadge item={signalByRowKey.get(row.key)} loading={portfolioSignalsLoading} showHint={false} />
            </span>
          </span>
          <span className="shrink-0 tabular-nums">{formatPositionMoney(row.marketValueBase, row)}</span>
        </div>
        <div className="mt-0.5 flex items-center justify-between gap-2 text-xs text-secondary">
          <span className="min-w-0 truncate">
            {row.name ? <span className="font-mono">{row.symbol}</span> : null}
            {row.name ? ' · ' : null}
            <span>{row.weightPct === null ? NO_VALUE : formatPct(row.weightPct)}</span>
          </span>
          <span className={cn('shrink-0 tabular-nums', hasPositionPrice(row) ? marketToneClass(row.unrealizedPnlBase) : 'text-secondary')}>
            {hasPositionPrice(row)
              ? `${formatSignedMoney(row.unrealizedPnlBase, row.valuationCurrency)} · ${formatPercent(row.unrealizedPnlPct)}`
              : getPositionPriceLabel(row, language)}
          </span>
        </div>
      </div>
      <ActionMenu label={formatUiText(pageText.rowMenu, { symbol: row.symbol })} size="sm" items={rowMenuItems(row)} />
    </div>
  );

  const deleteButton = (onClick: () => void) => (
    writeBlocked ? null : (
      <IconButton
        aria-label={pageText.removeRow}
        size="sm"
        icon={<Trash2 className="h-4 w-4" />}
        onClick={onClick}
      />
    )
  );

  // Desktop record cells: holding name over the code; the code stays its own node.
  const recordSymbolCell = (symbol: string) => {
    const name = holdingNameOf(symbol);
    return (
      <div className="min-w-0">
        {name ? <div className="truncate text-foreground">{name}</div> : null}
        <div className={cn('font-mono', name && 'text-[11px] text-secondary')}>{symbol}</div>
      </div>
    );
  };
  const sideBadge = (side: PortfolioSide) => (
    <Badge variant={side === 'buy' ? 'info' : 'default'}>{formatSideLabel(side, language)}</Badge>
  );

  const tradeColumns: DataTableColumn<PortfolioTradeListItem>[] = [
    { key: 'tradeDate', header: pageText.colDate, priority: 'primary' },
    { key: 'side', header: pageText.colSide, render: (item) => sideBadge(item.side) },
    { key: 'symbol', header: pageText.colSymbol, priority: 'primary', render: (item) => recordSymbolCell(item.symbol) },
    { key: 'quantity', header: pageText.colQuantity, numeric: true, priority: 'primary', render: (item) => formatNumber(item.quantity) },
    { key: 'price', header: pageText.colTradePrice, numeric: true, render: (item) => formatMoney(item.price, item.currency) },
    { key: 'fee', header: pageText.colFee, numeric: true, render: (item) => formatNumber(item.fee + item.tax) },
    {
      key: 'delete',
      header: '',
      align: 'right',
      render: (item) => deleteButton(() => openDeleteDialog({
        eventType: 'trade',
        id: item.id,
        message: formatUiText(pageText.deleteTradeMsg, {
          date: item.tradeDate,
          side: formatSideLabel(item.side, language),
          symbol: item.symbol,
          quantity: item.quantity,
          price: item.price,
        }),
      })),
    },
  ];

  const cashColumns: DataTableColumn<PortfolioCashLedgerListItem>[] = [
    { key: 'eventDate', header: pageText.colDate, priority: 'primary' },
    { key: 'direction', header: pageText.colDirection, priority: 'primary', render: (item) => formatCashDirectionLabel(item.direction, language) },
    { key: 'amount', header: pageText.colAmount, numeric: true, priority: 'primary', render: (item) => formatMoney(item.amount, item.currency) },
    {
      key: 'delete',
      header: '',
      align: 'right',
      render: (item) => deleteButton(() => openDeleteDialog({
        eventType: 'cash',
        id: item.id,
        message: formatUiText(pageText.deleteCashMsg, {
          date: item.eventDate,
          direction: formatCashDirectionLabel(item.direction, language),
          amount: item.amount,
          currency: item.currency,
        }),
      })),
    },
  ];

  const corporateColumns: DataTableColumn<PortfolioCorporateActionListItem>[] = [
    { key: 'effectiveDate', header: pageText.colDate, priority: 'primary' },
    { key: 'actionType', header: pageText.colAction, priority: 'primary', render: (item) => formatCorporateActionLabel(item.actionType, language) },
    { key: 'symbol', header: pageText.colSymbol, priority: 'primary', render: (item) => recordSymbolCell(item.symbol) },
    {
      key: 'detail',
      header: pageText.colDetail,
      numeric: true,
      render: (item) => formatNumber(item.actionType === 'cash_dividend' ? item.cashDividendPerShare : item.splitRatio),
    },
    {
      key: 'delete',
      header: '',
      align: 'right',
      render: (item) => deleteButton(() => openDeleteDialog({
        eventType: 'corporate',
        id: item.id,
        message: formatUiText(pageText.deleteCorporateMsg, {
          date: item.effectiveDate,
          action: formatCorporateActionLabel(item.actionType, language),
          symbol: item.symbol,
        }),
      })),
    },
  ];

  // Trade/corporate records carry no name; borrow it from the matching holding when there is one.
  const holdingNameFor = holdingNameOf;

  // 手機紀錄卡兩行：代號＋名稱 …… 金額；日期 · 類型 Badge …… 數量或幣別。
  const recordMobileCard = (
    title: React.ReactNode,
    amount: React.ReactNode,
    date: string,
    badge: React.ReactNode,
    detail: React.ReactNode,
    action: React.ReactNode,
  ) => (
    <div className="flex items-center gap-2 px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2 text-sm">
          <span className="min-w-0 truncate text-foreground">{title}</span>
          <span className="shrink-0 tabular-nums">{amount}</span>
        </div>
        <div className="mt-0.5 flex items-center justify-between gap-2 text-xs text-secondary">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="tabular-nums">{date}</span>
            <span aria-hidden="true">·</span>
            {badge}
          </span>
          <span className="shrink-0 tabular-nums">{detail}</span>
        </div>
      </div>
      {action}
    </div>
  );

  const symbolTitle = (symbol: string) => {
    const name = holdingNameFor(symbol);
    return (
      <>
        <span className="font-mono">{symbol}</span>
        {name ? <span className="ml-1.5">{name}</span> : null}
      </>
    );
  };

  const renderTradeMobileCard = (item: PortfolioTradeListItem) => recordMobileCard(
    symbolTitle(item.symbol),
    formatMoney(item.price, item.currency),
    item.tradeDate,
    sideBadge(item.side),
    formatUiText(w09Text.shares, { quantity: formatNumber(item.quantity) }),
    tradeColumns.find((column) => column.key === 'delete')?.render?.(item),
  );

  const renderCashMobileCard = (item: PortfolioCashLedgerListItem) => recordMobileCard(
    item.note || item.currency,
    formatMoney(item.amount, item.currency),
    item.eventDate,
    <Badge variant={item.direction === 'in' ? 'info' : 'default'}>{formatCashDirectionLabel(item.direction, language)}</Badge>,
    null,
    cashColumns.find((column) => column.key === 'delete')?.render?.(item),
  );

  const renderCorporateMobileCard = (item: PortfolioCorporateActionListItem) => recordMobileCard(
    symbolTitle(item.symbol),
    item.actionType === 'cash_dividend'
      ? formatUiText(w09Text.dividendPerShare, { amount: formatNumber(item.cashDividendPerShare) })
      : formatUiText(w09Text.splitRatio, { ratio: formatNumber(item.splitRatio) }),
    item.effectiveDate,
    <Badge variant="default">{formatCorporateActionLabel(item.actionType, language)}</Badge>,
    item.currency,
    corporateColumns.find((column) => column.key === 'delete')?.render?.(item),
  );

  const recordsEmpty = (
    <EmptyState
      title={pageText.noRecords}
      description={pageText.noRecordsHint}
      className="border-none bg-transparent px-3 py-6 shadow-none"
    />
  );

  const tradeAmount = computeTradeAmount(tradeForm.quantity, tradeForm.price);

  const entryAccountSelect = (
    <label className="block text-xs text-secondary">
      {pageText.entryAccount}
      <select
        className={`${PORTFOLIO_SELECT_CLASS} mt-1`}
        value={writableAccountId ?? ''}
        onChange={(e) => setEntryAccountId(Number(e.target.value))}
      >
        {accounts.map((account) => (
          <option key={account.id} value={account.id}>{account.name}</option>
        ))}
      </select>
    </label>
  );

  const accountFormNode = (
    <>
      {accountCreateError ? (
        <InlineAlert
          variant="danger"
          className="mt-2 rounded-lg px-2 py-1 text-xs shadow-none"
          title={pageText.createFail}
          message={accountCreateError}
        />
      ) : null}
      {accountCreateSuccess ? (
        <InlineAlert
          variant="success"
          className="mt-2 rounded-lg px-2 py-1 text-xs shadow-none"
          title={pageText.createOk}
          message={accountCreateSuccess}
        />
      ) : null}
      <form className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2" onSubmit={handleCreateAccount}>
        <input
          className={`${PORTFOLIO_INPUT_CLASS} md:col-span-2`}
          placeholder={pageText.accountNamePlaceholder}
          value={accountForm.name}
          onChange={(e) => setAccountForm((prev) => ({ ...prev, name: e.target.value }))}
        />
        <input
          className={PORTFOLIO_INPUT_CLASS}
          placeholder={pageText.brokerPlaceholder}
          value={accountForm.broker}
          onChange={(e) => setAccountForm((prev) => ({ ...prev, broker: e.target.value }))}
        />
        <input
          className={PORTFOLIO_INPUT_CLASS}
          placeholder={pageText.basePlaceholder}
          value={accountForm.baseCurrency}
          onChange={(e) => setAccountForm((prev) => ({ ...prev, baseCurrency: e.target.value.toUpperCase() }))}
        />
        <select
          className={PORTFOLIO_SELECT_CLASS}
          value={accountForm.market}
          onChange={(e) => setAccountForm((prev) => ({ ...prev, market: e.target.value as PortfolioAccountMarket }))}
        >
          <option value="tw">{pageText.marketOptionTw}</option>
          <option value="us">{pageText.marketOptionUs}</option>
          <option value="hk">{pageText.marketOptionHk}</option>
          <option value="cn">{pageText.marketOptionCn}</option>
          <option value="jp">{pageText.marketOptionJp}</option>
          <option value="kr">{pageText.marketOptionKr}</option>
        </select>
        <button type="submit" className="btn-secondary text-sm" disabled={accountCreating}>
          {accountCreating ? pageText.creating : pageText.createSubmit}
        </button>
      </form>
    </>
  );

  const costMethodMenuHeader = (
    <div>
      <p className="mb-1 text-xs text-secondary">{pageText.costMethodLabel}</p>
      <Segmented
        aria-label={pageText.costMethodLabel}
        size="sm"
        value={costMethod}
        onChange={setCostMethod}
        options={[
          { value: 'fifo', label: text.fifo },
          { value: 'avg', label: text.avg },
        ]}
      />
    </div>
  );
  const accountMenuItems = [
    {
      key: 'create',
      label: text.createAccount,
      onSelect: () => {
        setShowCreateAccount(true);
        setAccountCreateError(null);
        setAccountCreateSuccess(null);
      },
    },
    {
      key: 'delete',
      label: accountDeleteLoading ? text.deletingAccount : text.deleteAccount,
      disabled: !canDeleteSelectedAccount,
      danger: true,
      onSelect: openAccountDeleteDialog,
    },
  ];
  // Phones: record / import / refresh move into the ⋯ menu so the header stays one row.
  const narrowMenuItems = [
    { key: 'record', label: pageText.recordEntry, disabled: !hasAccounts, onSelect: () => openEntry('trade') },
    { key: 'import', label: pageText.importEntry, disabled: !hasAccounts, onSelect: openImport },
    {
      key: 'refresh',
      label: isLoading ? text.refreshing : text.refreshData,
      disabled: isLoading || fxRefreshing,
      onSelect: () => void handleRefresh(),
    },
    ...accountMenuItems,
  ];
  const accountSwitcher = hasAccounts ? (
    <Segmented
      aria-label={text.accountView}
      // Phones: full-width row with short names so all accounts fit without a scrollbar.
      className={narrow ? 'flex w-full [&>button]:flex-1 [&>button]:px-2' : 'overflow-x-auto'}
      value={String(selectedAccount)}
      onChange={(value) => setSelectedAccount(value === 'all' ? 'all' : Number(value))}
      options={[
        { value: 'all', label: narrow ? w10Text.allAccountsShort : text.allAccounts },
        ...accounts.map((account) => ({
          value: String(account.id),
          label: narrow ? shortAccountName(account.name) : account.name,
        })),
      ]}
    />
  ) : null;

  const fxBadge = getFxBadge(fxMissing, fxStale, language);
  const fxStatusLoading = isLoading && snapshot === null;
  const fxNotes = [
    fxMissing ? text.fxMissingHint.replace('{pairs}', fxMissingPairs.join(', ')) : null,
    snapshotQualityMessage ? `${text.snapshotPartialTitle}：${snapshotQualityMessage}` : null,
  ].filter((note): note is string => Boolean(note));

  // Embedded (iOS) and deep-linked into a drawer: the summary folds into one line.
  const compactSummary = embedded && deepLinkEntry !== null;

  const renderPendingRows = (items: PendingItem[]) => (
    <ul className="divide-y divide-border/40">
      {items.map((item) => (
        <li key={item.key} className="flex items-center justify-between gap-3 py-1.5 text-sm">
          <span className="flex min-w-0 items-center gap-2">
            <StatusDot tone={item.tone} className="h-2 w-2 shrink-0" />
            {item.rowKey ? (
              <button
                type="button"
                className="min-w-0 cursor-pointer text-left hover:underline"
                onClick={() => jumpToRow(item.rowKey as string)}
              >
                {item.label}
              </button>
            ) : (
              <span className="min-w-0">{item.label}</span>
            )}
            {showAccountNames && item.accountNames && item.accountNames.length > 0 ? (
              <span className="shrink-0 text-[11px] text-secondary">{item.accountNames.join('、')}</span>
            ) : null}
          </span>
          {item.action ? (
            <Button size="sm" variant="secondary" onClick={item.action.onClick}>{item.action.label}</Button>
          ) : null}
        </li>
      ))}
    </ul>
  );

  const pendingSection = sortedPendingItems.length > 0 ? (
    <section data-testid="portfolio-pending">
      <Card padding="md">
        <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
          <AlertTriangle className="h-4 w-4 text-warning" />
          {pageText.sectionPending}
        </h2>
        {renderPendingRows(visiblePendingItems)}
        {hiddenPendingItems.length > 0 ? (
          <Collapsible
            title={formatUiText(w10Text.pendingShowMore, { count: hiddenPendingItems.length })}
            className="mt-2 rounded-xl shadow-none"
          >
            {renderPendingRows(hiddenPendingItems)}
          </Collapsible>
        ) : null}
      </Card>
    </section>
  ) : null;

  const availableRiskFlags = portfolioRiskFlags.filter((flag) => flag.tone !== 'neutral');
  const unavailableRiskFlags = portfolioRiskFlags.filter((flag) => flag.tone === 'neutral');

  return (
    <AppPage className="portfolio-page">
      <PageHeader
        title={text.title}
        actions={narrow ? (
          <ActionMenu label={pageText.more} header={costMethodMenuHeader} items={narrowMenuItems} />
        ) : (
          <>
            {accountSwitcher}
            <Button onClick={() => openEntry('trade')} disabled={!hasAccounts}>{pageText.recordEntry}</Button>
            <Button variant="secondary" onClick={openImport} disabled={!hasAccounts}>{pageText.importEntry}</Button>
            <IconButton
              aria-label={isLoading ? text.refreshing : text.refreshData}
              icon={<RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />}
              onClick={() => void handleRefresh()}
              disabled={isLoading || fxRefreshing}
            />
            <ActionMenu label={pageText.more} header={costMethodMenuHeader} items={accountMenuItems} />
          </>
        )}
      />
      {narrow ? accountSwitcher : null}

      {error && !entryOpen && !importOpen ? <ApiErrorAlert error={error} onDismiss={() => setError(null)} /> : null}
      {writeWarning ? (
        <InlineAlert
          variant="warning"
          title={text.operationHint}
          message={writeWarning}
        />
      ) : null}
      {positionAnalysisMessage ? (
        <InlineAlert
          variant="success"
          title={text.analysisTask}
          message={positionAnalysisMessage}
        />
      ) : null}

      {!hasAccounts && !isLoading ? (
        <Card padding="md">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-foreground">{pageText.createTitle}</h2>
            <span className="text-xs text-secondary">{pageText.createAfter}</span>
          </div>
          <p className="mt-1 text-xs text-secondary">{text.noAccounts}</p>
          {accountFormNode}
        </Card>
      ) : null}

      {/* Phones: pending comes before the summary (U5.9). */}
      {narrow ? pendingSection : null}

      <section className="space-y-2" aria-label={pageText.metricTotalAssets}>
        {compactSummary ? (
          <p data-testid="portfolio-summary-compact" className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
            <span>
              <span className="text-secondary">{pageText.metricTotalAssets}</span>{' '}
              <span className="font-semibold tabular-nums text-foreground">
                {metricTotal === null ? amountText(metricTotal) : moneyLabel(metricTotal, metricCurrency)}
              </span>
            </span>
            <span>
              <span className="text-secondary">{dayLabel}</span>{' '}
              <span className={cn('tabular-nums', metricDayValue !== null && marketToneClass(metricDayValue))}>
                {metricDayValue === null ? amountText(metricDayValue) : moneyLabel(metricDayValue, metricCurrency, true)}
              </span>
            </span>
          </p>
        ) : (
          <MetricGroup columns={4}>
            <Metric
              hero
              label={pageText.metricTotalAssets}
              unit={metricUnitFor(metricTotal)}
              value={amountText(metricTotal)}
              hint={joinHints([
                hasFunds && fundValue !== null
                  ? formatUiText(pageText.includesFunds, { amount: moneyLabel(fundValue, summaryCurrency) })
                  : fundsUnavailable && equityAmount !== null ? pageText.excludesFunds : undefined,
                approxHint(totalAssets),
              ])}
            />
            <Metric
              label={dayLabel}
              unit={metricUnitFor(metricDayValue)}
              value={signedNode(metricDayValue)}
              hint={joinHints([
                quoteDateIsToday ? undefined : w09Text.marketClosed,
                dayBreakdown,
                fundsUnavailable && dayAmount !== null ? pageText.stocksOnly : undefined,
                approxHint(dayAmount),
              ])}
            />
            <Metric
              label={pageText.metricUnrealized}
              unit={metricUnitFor(metricUnrealizedValue)}
              value={signedNode(metricUnrealizedValue)}
              hint={approxHint(unrealizedAmount)}
            />
            <Metric
              label={pageText.metricRealized}
              unit={metricUnitFor(metricRealizedValue)}
              value={signedNode(metricRealizedValue)}
              hint={approxHint(realizedAmount)}
            />
            <Metric
              label={pageText.metricMarketValue}
              unit={metricUnitFor(metricMarketValue)}
              value={amountText(metricMarketValue)}
              hint={approxHint(marketValueAmount)}
            />
            <Metric
              label={pageText.metricCash}
              unit={metricUnitFor(metricCashValue)}
              value={amountText(metricCashValue)}
              hint={approxHint(cashAmount)}
              // Hero takes two slots, so without the funds card the last row has one gap: let cash fill it.
              className={showFundCard ? undefined : 'md:col-span-2'}
            />
            {showFundCard ? (
              <Metric
                label={pageText.metricFunds}
                unit={fundValue === null ? undefined : currencyUnitLabel(summaryCurrency) || undefined}
                value={fundValue === null ? NO_VALUE : moneyDigits(fundValue, summaryCurrency)}
                hint={fundDay === null ? undefined : (
                  <span className={marketToneClass(fundDay)}>{moneyLabel(fundDay, summaryCurrency, true)}</span>
                )}
              />
            ) : null}
          </MetricGroup>
        )}
        <div className="flex flex-wrap items-center gap-2 text-xs text-secondary">
          {fxStatusLoading ? (
            <Skeleton className="h-5 w-20 rounded-full" />
          ) : fxBadge ? (
            <Badge variant={fxBadge.variant}>{fxBadge.label}</Badge>
          ) : null}
          {fxNotes.length > 0 ? (
            <Tooltip
              focusable
              content={(
                <span className="block whitespace-normal">
                  {fxNotes.map((note) => <span key={note} className="block">{note}</span>)}
                </span>
              )}
            >
              <Info aria-label={w10Text.fxInfo} role="img" className="h-3.5 w-3.5 text-secondary" />
            </Tooltip>
          ) : null}
          <IconButton
            aria-label={fxRefreshing ? text.refreshing : text.refreshFx}
            size="sm"
            icon={<RefreshCw className={cn('h-3.5 w-3.5', fxRefreshing && 'animate-spin')} />}
            onClick={() => void handleRefreshFx()}
            disabled={!hasAccounts || isLoading || fxRefreshing}
          />
        </div>
        {fxRefreshFeedback ? (
          <InlineAlert
            variant={getFxRefreshFeedbackVariant(fxRefreshFeedback.tone)}
            title={text.fxRefreshResult}
            message={fxRefreshFeedback.text}
            className="rounded-xl px-3 py-2 text-xs shadow-none"
          />
        ) : null}
      </section>

      {narrow ? null : pendingSection}

      <section>
        <Card padding="md">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-foreground">{text.positionsTitle}</h2>
            <span className="text-xs text-secondary">{formatUiText(text.countItems, { count: positionCount })}</span>
          </div>
          {portfolioSignalsWarning ? (
            <InlineAlert
              variant="warning"
              title={t('decisionSignals.portfolioWarningTitle')}
              message={portfolioSignalsWarning}
              className="mb-3 rounded-xl px-3 py-2 text-xs shadow-none"
            />
          ) : null}
          {snapshot === null ? (
            <EmptyState
              title={isLoading ? text.refreshing : riskDashboardText.snapshotUnavailable}
              description={isLoading ? undefined : riskDashboardText.snapshotUnavailableDescription}
              className="border-none bg-transparent px-4 py-8 shadow-none"
            />
          ) : holdingRows.length === 0 ? (
            <EmptyState
              title={text.noPositionsTitle}
              description={text.noPositionsDescription}
              className="border-none bg-transparent px-4 py-8 shadow-none"
            />
          ) : (
            <div ref={holdingsRef} data-testid="portfolio-holdings">
              <div className="mb-2 md:hidden">
                <Segmented
                  aria-label={pageText.sortBy}
                  size="sm"
                  value={holdingMobileSort}
                  onChange={(key) => setHoldingSort({ key, direction: key === 'name' ? 'asc' : 'desc' })}
                  options={[
                    { value: 'marketValue', label: pageText.sortValue },
                    { value: 'pnl', label: pageText.sortPnl },
                    { value: 'returnPct', label: pageText.sortReturn },
                    { value: 'name', label: pageText.sortName },
                  ]}
                />
              </div>
              <DataTable
                aria-label={text.positionsTitle}
                density="regular"
                columns={holdingColumns}
                rows={sortedHoldingRows}
                rowGroups={holdingRowGroups}
                rowKey={(row) => row.key}
                sort={holdingSort}
                onSortChange={setHoldingSort}
                isRowHighlighted={(row) => row.key === highlightedRowKey}
                renderMobileCard={renderHoldingMobileCard}
              />
            </div>
          )}
        </Card>
      </section>

      {snapshotFailed || riskFailed || riskLoading || concentrationBarRows.length === 0 ? null : (
        <section>
          <Card padding="md">
            <h2 className="mb-3 text-sm font-semibold text-foreground">
              {concentrationMode === 'sector' ? text.sectorConcentration : text.positionConcentrationFallback}
            </h2>
            <ol className="space-y-2">
              {concentrationBarRows.map((row) => (
                <li key={row.name}>
                  <div className="flex items-center justify-between gap-3 text-xs">
                    <span className="truncate text-foreground">{row.name}</span>
                    <span className="tabular-nums text-secondary">{formatPct(row.value)}</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-border/60">
                    <div className="h-full rounded-full bg-cyan" style={{ width: `${Math.min(100, Math.max(0, row.value))}%` }} />
                  </div>
                </li>
              ))}
            </ol>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-secondary">
              <div>{text.displayScope}: {concentrationMode === 'sector' ? text.sectorDimension : text.positionDimensionFallback}</div>
              <div>{text.sectorAlert}: {riskAvailability.sectorConcentration ? (risk?.sectorConcentration?.alert ? text.yes : text.no) : riskDashboardText.unavailable}</div>
              <div>{text.topWeight}: {formatPct(concentrationTopWeight)}</div>
            </div>
          </Card>
        </section>
      )}

      <section data-testid="portfolio-risk">
        <Card padding="md">
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-cyan" />
              <h2 className="text-sm font-semibold text-foreground">{riskDashboardText.title}</h2>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-secondary">
              <span>{riskDashboardText.positions}: {positionCount}</span>
              <span>{text.totalMarketValue}: {formatMoney(exposureTotal, exposureCurrency)}</span>
            </div>
          </div>
          {snapshotFailed || riskFailed ? (
            <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border/70 px-3 py-2 text-sm">
              <span className="min-w-0">
                <span className="font-medium text-foreground">{snapshotFailed ? riskDashboardText.snapshotUnavailable : text.riskDegraded}</span>
                <span className="ml-2 text-xs text-secondary">{snapshotFailed ? riskDashboardText.snapshotUnavailableDescription : riskWarning}</span>
              </span>
              <Button size="sm" variant="secondary" onClick={() => void loadSnapshotAndRisk()}>{pageText.retry}</Button>
            </div>
          ) : riskLoading ? (
            <div data-testid="portfolio-risk-skeleton" className="flex flex-wrap gap-2" aria-hidden="true">
              {Array.from({ length: 4 }, (_, index) => (
                <div key={index} className="h-8 w-40 animate-pulse rounded-xl bg-border/40" />
              ))}
            </div>
          ) : (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,0.75fr)]">
              <div className="min-w-0">
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-secondary">
                  <AlertTriangle className="h-3.5 w-3.5 text-warning" />
                  {riskDashboardText.riskFlags}
                </div>
                {availableRiskFlags.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {availableRiskFlags.map((flag) => (
                      <PortfolioRiskFlagChip key={flag.key} flag={flag} text={riskDashboardText} />
                    ))}
                  </div>
                ) : null}
                {unavailableRiskFlags.length > 0 ? (
                  <p data-testid="portfolio-risk-unavailable" className="mt-2 text-xs text-muted-text">
                    {w10Text.riskUnavailable}
                    {unavailableRiskFlags.map((flag, index) => (
                      <Fragment key={flag.key}>
                        {index > 0 ? (language === 'en' ? ', ' : '、') : null}
                        <span data-flag-key={flag.key} data-flag-state="unavailable">{flag.label}</span>
                      </Fragment>
                    ))}
                  </p>
                ) : null}
              </div>
              <div className="grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-1">
                <div className="mb-[-0.25rem] hidden items-center gap-2 text-xs font-semibold text-secondary xl:flex">
                  <Layers3 className="h-3.5 w-3.5 text-cyan" />
                  {riskDashboardText.marketExposure} / {riskDashboardText.currencyExposure}
                </div>
                <PortfolioExposureList
                  title={riskDashboardText.marketExposure}
                  rows={marketExposureRows}
                  currency={exposureCurrency || 'CNY'}
                  emptyLabel={exposureEmptyLabel}
                  positionLabel={riskDashboardText.positions}
                />
                <PortfolioExposureList
                  title={riskDashboardText.currencyExposure}
                  rows={currencyExposureRows}
                  currency={exposureCurrency || 'CNY'}
                  emptyLabel={exposureEmptyLabel}
                  positionLabel={riskDashboardText.positions}
                />
                {accountExposureRows.length > 0 ? (
                  <PortfolioExposureList
                    title={pageText.accountExposure}
                    rows={accountExposureRows}
                    currency={exposureCurrency || 'CNY'}
                    emptyLabel={exposureEmptyLabel}
                    positionLabel={riskDashboardText.positions}
                  />
                ) : null}
              </div>
            </div>
          )}
        </Card>
      </section>

      <section data-testid="portfolio-records">
        <Card padding="md">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-foreground">{pageText.recordsTitle}</h2>
            <Segmented
              aria-label={pageText.recordsTitle}
              size="sm"
              value={eventType}
              onChange={setEventType}
              options={[
                { value: 'trade', label: pageText.typeTrade },
                { value: 'cash', label: pageText.typeCash },
                { value: 'corporate', label: pageText.typeCorporate },
              ]}
            />
          </div>
          <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
            <input aria-label={pageText.dateFrom} className={PORTFOLIO_FILTER_CLASS} type="date" value={eventDateFrom} onChange={(e) => setEventDateFrom(e.target.value)} />
            <input aria-label={pageText.dateTo} className={PORTFOLIO_FILTER_CLASS} type="date" value={eventDateTo} onChange={(e) => setEventDateTo(e.target.value)} />
            {eventType === 'trade' || eventType === 'corporate' ? (
              <input aria-label={pageText.filterSymbol} className={PORTFOLIO_FILTER_CLASS} placeholder={pageText.filterSymbol} value={eventSymbol}
                onChange={(e) => setEventSymbol(e.target.value)} />
            ) : null}
            {eventType === 'trade' ? (
              <select aria-label={pageText.sideAll} className={PORTFOLIO_FILTER_SELECT_CLASS} value={eventSide} onChange={(e) => setEventSide(e.target.value as '' | PortfolioSide)}>
                <option value="">{pageText.sideAll}</option>
                <option value="buy">{pageText.buy}</option>
                <option value="sell">{pageText.sell}</option>
              </select>
            ) : null}
            {eventType === 'cash' ? (
              <select aria-label={pageText.directionAll} className={PORTFOLIO_FILTER_SELECT_CLASS} value={eventDirection}
                onChange={(e) => setEventDirection(e.target.value as '' | PortfolioCashDirection)}>
                <option value="">{pageText.directionAll}</option>
                <option value="in">{pageText.cashIn}</option>
                <option value="out">{pageText.cashOut}</option>
              </select>
            ) : null}
            {eventType === 'corporate' ? (
              <select aria-label={pageText.actionAll} className={PORTFOLIO_FILTER_SELECT_CLASS} value={eventActionType}
                onChange={(e) => setEventActionType(e.target.value as '' | PortfolioCorporateActionType)}>
                <option value="">{pageText.actionAll}</option>
                <option value="cash_dividend">{pageText.actionCashDividend}</option>
                <option value="split_adjustment">{pageText.actionSplit}</option>
              </select>
            ) : null}
          </div>
          {writeBlocked ? <p className="mb-2 text-[11px] text-secondary">{pageText.deleteHintBlocked}</p> : null}
          {eventType === 'trade' ? (
            <DataTable columns={tradeColumns} renderMobileCard={renderTradeMobileCard} rows={tradeEvents} rowKey={(item) => `t-${item.id}`} density="compact" emptyState={eventLoading ? undefined : recordsEmpty} aria-label={pageText.typeTrade} />
          ) : eventType === 'cash' ? (
            <DataTable columns={cashColumns} renderMobileCard={renderCashMobileCard} rows={cashEvents} rowKey={(item) => `c-${item.id}`} density="compact" emptyState={eventLoading ? undefined : recordsEmpty} aria-label={pageText.typeCash} />
          ) : (
            <DataTable columns={corporateColumns} renderMobileCard={renderCorporateMobileCard} rows={corporateEvents} rowKey={(item) => `ca-${item.id}`} density="compact" emptyState={eventLoading ? undefined : recordsEmpty} aria-label={pageText.typeCorporate} />
          )}
          <div className="mt-3 flex items-center justify-between text-xs text-secondary">
            <span>{formatUiText(pageText.pageOf, { page: eventPage, total: totalEventPages })}</span>
            <div className="flex gap-2">
              <button type="button" className="btn-secondary text-xs px-3 py-1" disabled={eventPage <= 1}
                onClick={() => setEventPage((prev) => Math.max(1, prev - 1))}>
                {pageText.prevPage}
              </button>
              <button type="button" className="btn-secondary text-xs px-3 py-1" disabled={eventPage >= totalEventPages}
                onClick={() => setEventPage((prev) => Math.min(totalEventPages, prev + 1))}>
                {pageText.nextPage}
              </button>
            </div>
          </div>
        </Card>
      </section>

      <Drawer isOpen={entryOpen} onClose={() => setEntryOpen(false)} title={pageText.entryTitle} width="max-w-md">
        <div className="space-y-3">
          {error ? <ApiErrorAlert error={error} onDismiss={() => setError(null)} /> : null}
          {entryAccountSelect}
          <Segmented
            aria-label={pageText.entryTitle}
            value={entryKind}
            onChange={setEntryKind}
            options={[
              { value: 'trade', label: pageText.entryTrade },
              { value: 'cash', label: pageText.entryCash },
              { value: 'corporate', label: pageText.entryCorporate },
            ]}
          />
          {entryKind === 'trade' ? (
            <form className="space-y-3" onSubmit={handleTradeSubmit}>
              <Input
                label={w10Text.tradeSymbol}
                placeholder={w10Text.tradeSymbolExample}
                value={tradeForm.symbol}
                onChange={(e) => setTradeForm((prev) => ({ ...prev, symbol: e.target.value }))}
                required
              />
              <div className="grid grid-cols-2 gap-2">
                <Input
                  label={w10Text.tradeDate}
                  type="date"
                  value={tradeForm.tradeDate}
                  onChange={(e) => setTradeForm((prev) => ({ ...prev, tradeDate: e.target.value }))}
                  required
                />
                <Select
                  label={w10Text.tradeSide}
                  value={tradeForm.side}
                  onChange={(value) => setTradeForm((prev) => ({ ...prev, side: value as PortfolioSide }))}
                  options={[
                    { value: 'buy', label: pageText.buy },
                    { value: 'sell', label: pageText.sell },
                  ]}
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Input
                  label={w10Text.tradeQuantity}
                  type="number"
                  min="0"
                  step="0.0001"
                  value={tradeForm.quantity}
                  onChange={(e) => setTradeForm((prev) => ({ ...prev, quantity: e.target.value }))}
                  required
                />
                <Input
                  label={tradeCurrency
                    ? formatUiText(w10Text.tradePrice, { currency: tradeCurrency })
                    : w10Text.tradePriceBare}
                  type="number"
                  min="0"
                  step="0.0001"
                  value={tradeForm.price}
                  onChange={(e) => setTradeForm((prev) => ({ ...prev, price: e.target.value }))}
                  required
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Input
                  label={w10Text.tradeFee}
                  type="number"
                  min="0"
                  step="0.0001"
                  value={tradeForm.fee}
                  onChange={(e) => setTradeForm((prev) => ({ ...prev, fee: e.target.value }))}
                />
                <Input
                  label={w10Text.tradeTax}
                  type="number"
                  min="0"
                  step="0.0001"
                  value={tradeForm.tax}
                  onChange={(e) => setTradeForm((prev) => ({ ...prev, tax: e.target.value }))}
                />
              </div>
              <p className="text-xs text-secondary">{pageText.feeHint}</p>
              {tradeAmount !== null ? (
                <p data-testid="portfolio-trade-amount" className="text-sm font-medium tabular-nums text-foreground">
                  {formatUiText(w10Text.tradeAmount, { amount: formatMoney(tradeAmount, tradeCurrency) })}
                </p>
              ) : null}
              <Button type="submit" className="w-full" disabled={!writableAccountId}>{pageText.submitTrade}</Button>
            </form>
          ) : entryKind === 'cash' ? (
            <form className="space-y-2" onSubmit={handleCashSubmit}>
              <div className="grid grid-cols-2 gap-2">
                <input className={PORTFOLIO_INPUT_CLASS} type="date" value={cashForm.eventDate}
                  onChange={(e) => setCashForm((prev) => ({ ...prev, eventDate: e.target.value }))} required />
                <select className={PORTFOLIO_SELECT_CLASS} value={cashForm.direction}
                  onChange={(e) => setCashForm((prev) => ({ ...prev, direction: e.target.value as PortfolioCashDirection }))}>
                  <option value="in">{pageText.cashIn}</option>
                  <option value="out">{pageText.cashOut}</option>
                </select>
              </div>
              <input className={PORTFOLIO_INPUT_CLASS} type="number" min="0" step="0.0001" placeholder={pageText.amount}
                value={cashForm.amount} onChange={(e) => setCashForm((prev) => ({ ...prev, amount: e.target.value }))} required />
              <input
                className={PORTFOLIO_INPUT_CLASS}
                placeholder={formatUiText(pageText.currencyOptional, { currency: writableAccount?.baseCurrency || pageText.accountBase })}
                value={cashForm.currency}
                onChange={(e) => setCashForm((prev) => ({ ...prev, currency: e.target.value }))}
              />
              <Button type="submit" className="w-full" disabled={!writableAccountId}>{pageText.submitCash}</Button>
            </form>
          ) : (
            <form className="space-y-2" onSubmit={handleCorporateSubmit}>
              <input className={PORTFOLIO_INPUT_CLASS} placeholder={pageText.symbolPlaceholderShort} value={corpForm.symbol}
                onChange={(e) => setCorpForm((prev) => ({ ...prev, symbol: e.target.value }))} required />
              <div className="grid grid-cols-2 gap-2">
                <input className={PORTFOLIO_INPUT_CLASS} type="date" value={corpForm.effectiveDate}
                  onChange={(e) => setCorpForm((prev) => ({ ...prev, effectiveDate: e.target.value }))} required />
                <select className={PORTFOLIO_SELECT_CLASS} value={corpForm.actionType}
                  onChange={(e) => setCorpForm((prev) => ({ ...prev, actionType: e.target.value as PortfolioCorporateActionType }))}>
                  <option value="cash_dividend">{pageText.actionCashDividend}</option>
                  <option value="split_adjustment">{pageText.actionSplit}</option>
                </select>
              </div>
              {corpForm.actionType === 'cash_dividend' ? (
                <input className={PORTFOLIO_INPUT_CLASS} type="number" min="0" step="0.000001" placeholder={pageText.dividendPerShare}
                  value={corpForm.cashDividendPerShare}
                  onChange={(e) => setCorpForm((prev) => ({ ...prev, cashDividendPerShare: e.target.value, splitRatio: '' }))} required />
              ) : (
                <input className={PORTFOLIO_INPUT_CLASS} type="number" min="0" step="0.000001" placeholder={pageText.splitRatio}
                  value={corpForm.splitRatio}
                  onChange={(e) => setCorpForm((prev) => ({ ...prev, splitRatio: e.target.value, cashDividendPerShare: '' }))} required />
              )}
              <Button type="submit" className="w-full" disabled={!writableAccountId}>{pageText.submitCorporate}</Button>
            </form>
          )}
        </div>
      </Drawer>

      <Drawer isOpen={importOpen} onClose={() => setImportOpen(false)} title={pageText.importTitle}>
        <div className="space-y-3">
          {error ? <ApiErrorAlert error={error} onDismiss={() => setError(null)} /> : null}
          {entryAccountSelect}
          <h3 className="text-sm font-semibold text-foreground">{pageText.pasteTitle}</h3>
          <p className="text-xs text-secondary">{pageText.pasteHint}</p>
          <div className="space-y-2">
            <textarea
              className="input-surface input-focus-glow min-h-32 w-full rounded-xl border bg-transparent px-4 py-2 font-mono text-sm transition-all focus:outline-none"
              placeholder={'元大台灣50 300 98.5\n2303 450 52.1 2025-03-10\n00631L.TW 2000 21.3'}
              value={pasteText}
              onChange={(e) => setPasteText(e.target.value)}
              aria-label={pageText.pasteLabel}
            />
            <div className="grid grid-cols-2 items-end gap-2">
              <Input
                label={pageText.pasteDate}
                type="date"
                value={pasteTradeDate}
                onChange={(e) => setPasteTradeDate(e.target.value)}
              />
              <button type="button" className="btn-secondary h-9" disabled={!pasteParseResult?.missingCost?.length}
                onClick={handlePasteToTemplate}>
                {pageText.toTemplate}
              </button>
            </div>
            <Checkbox
              label={pageText.dryRun}
              checked={pasteDryRun}
              onChange={(e) => setPasteDryRun(e.target.checked)}
            />
            <div className="flex gap-2">
              <button type="button" className="btn-secondary flex-1" disabled={!pasteText.trim() || pasteParsing}
                onClick={() => void handleParsePaste()}>
                {pasteParsing ? pageText.parsing : pageText.parseContent}
              </button>
              <button type="button" className="btn-secondary flex-1"
                disabled={!pasteText.trim() || !writableAccountId || pasteCommitting} onClick={() => void handleCommitPaste()}>
                {pasteCommitting ? pageText.committing : pasteDryRun ? w10Text.commitDry : w10Text.commitWrite}
              </button>
            </div>
            {pasteParseResult ? (
              <InlineAlert
                variant={getCsvParseVariant(pasteParseResult)}
                title={pageText.pasteParseTitle}
                message={[
                  formatUiText(pageText.pasteParseSummary, {
                    records: pasteParseResult.recordCount,
                    missing: pasteParseResult.missingCost?.length ?? 0,
                    errors: pasteParseResult.errorCount,
                  }),
                  ...(pasteParseResult.missingCost ?? []).map((r) => formatUiText(pageText.missingCostLine, {
                    name: r.name ?? '',
                    symbol: r.symbol,
                    quantity: r.quantity,
                  })),
                  ...pasteParseResult.errors,
                ].join('\n')}
                className="whitespace-pre-line rounded-lg px-3 py-2 text-xs shadow-none"
              />
            ) : null}
            {pasteCommitResult ? (
              <InlineAlert
                variant={getCsvCommitVariant(pasteCommitResult, pasteDryRun)}
                title={pasteDryRun ? pageText.pasteDryTitle : pageText.pasteCommitTitle}
                message={formatUiText(pageText.commitSummary, {
                  prefix: pasteDryRun ? pageText.dryPrefix : pageText.commitPrefix,
                  inserted: pasteCommitResult.insertedCount,
                  duplicate: pasteCommitResult.duplicateCount,
                  failed: pasteCommitResult.failedCount,
                })}
                className="rounded-lg px-3 py-2 text-xs shadow-none"
              />
            ) : null}
          </div>

          <Collapsible title={w10Text.csvSection} className="rounded-xl shadow-none">
          <div className="space-y-2">
            {brokerLoadWarning ? (
              <InlineAlert
                variant="warning"
                className="rounded-lg px-2 py-1 text-xs shadow-none"
                message={brokerLoadWarning}
              />
            ) : null}
            <div className="grid grid-cols-2 gap-2">
              <select
                aria-label={pageText.csvTitle}
                className={PORTFOLIO_SELECT_CLASS}
                value={selectedBroker}
                onChange={(e) => setSelectedBroker(e.target.value)}
              >
                {brokers.map((item) => (
                  <option key={item.broker} value={item.broker}>
                    {formatBrokerOptionLabel(item.broker, item.displayName, language)}
                  </option>
                ))}
              </select>
              <label className={PORTFOLIO_FILE_PICKER_CLASS}>
                {pageText.csvPick}
                <input type="file" accept=".csv" className="hidden"
                  onChange={(e) => setCsvFile(e.target.files && e.target.files[0] ? e.target.files[0] : null)} />
              </label>
            </div>
            <Checkbox
              label={pageText.dryRun}
              checked={csvDryRun}
              onChange={(e) => setCsvDryRun(e.target.checked)}
            />
            <div className="flex gap-2">
              <button type="button" className="btn-secondary flex-1" disabled={!csvFile || csvParsing} onClick={() => void handleParseCsv()}>
                {csvParsing ? pageText.parsing : pageText.parseFile}
              </button>
              <button type="button" className="btn-secondary flex-1"
                disabled={!csvFile || !writableAccountId || csvCommitting} onClick={() => void handleCommitCsv()}>
                {csvCommitting ? pageText.committing : csvDryRun ? w10Text.commitDry : w10Text.commitWrite}
              </button>
            </div>
            {csvParseResult ? (
              <InlineAlert
                variant={getCsvParseVariant(csvParseResult)}
                title={pageText.csvParseTitle}
                message={formatUiText(pageText.parseSummary, {
                  records: csvParseResult.recordCount,
                  skipped: csvParseResult.skippedCount,
                  errors: csvParseResult.errorCount,
                })}
                className="rounded-lg px-3 py-2 text-xs shadow-none"
              />
            ) : null}
            {csvCommitResult ? (
              <InlineAlert
                variant={getCsvCommitVariant(csvCommitResult, csvDryRun)}
                title={csvDryRun ? pageText.csvDryTitle : pageText.csvCommitTitle}
                message={formatUiText(pageText.commitSummary, {
                  prefix: csvDryRun ? pageText.dryPrefix : pageText.commitPrefix,
                  inserted: csvCommitResult.insertedCount,
                  duplicate: csvCommitResult.duplicateCount,
                  failed: csvCommitResult.failedCount,
                })}
                className="rounded-lg px-3 py-2 text-xs shadow-none"
              />
            ) : null}
          </div>
          </Collapsible>
        </div>
      </Drawer>

      <Drawer isOpen={showCreateAccount && hasAccounts} onClose={() => setShowCreateAccount(false)} title={pageText.createTitle}>
        {accountFormNode}
      </Drawer>

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        title={pageText.deleteTitle}
        message={pendingDelete?.message || pageText.deleteConfirm}
        confirmText={deleteLoading ? pageText.deleting : pageText.confirmDelete}
        cancelText={pageText.cancel}
        isDanger
        onConfirm={() => void handleConfirmDelete()}
        onCancel={() => {
          if (!deleteLoading) {
            setPendingDelete(null);
          }
        }}
      />
      <ConfirmDialog
        isOpen={Boolean(pendingAccountDelete)}
        title={text.deleteAccountTitle}
        message={
          pendingAccountDelete
            ? formatUiText(text.deleteAccountMessage, {
              name: pendingAccountDelete.accountName,
              id: pendingAccountDelete.accountId,
            })
            : ''
        }
        confirmText={accountDeleteLoading ? text.deletingAccount : text.deleteAccountConfirm}
        isDanger
        onConfirm={() => void handleConfirmAccountDelete()}
        onCancel={() => {
          if (!accountDeleteLoading) {
            setPendingAccountDelete(null);
          }
        }}
      />
    </AppPage>
  );
};

export default PortfolioPage;
