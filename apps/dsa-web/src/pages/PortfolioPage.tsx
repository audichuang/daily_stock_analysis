import { AlertBellLink } from '../components/alerts/AlertBellLink';
import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Layers3, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react';
import { decisionSignalsApi } from '../api/decisionSignals';
import { portfolioApi } from '../api/portfolio';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import {
  ApiErrorAlert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Drawer,
  EmptyState,
  IconButton,
  InlineAlert,
  Metric,
  MetricGroup,
  PageHeader,
  Segmented,
  StatusDot,
} from '../components/common';
import type { DataTableColumn, DataTableRowGroup, SortState } from '../components/common';
import { DataTable } from '../components/common';
import { ActionMenu } from '../components/common/ActionMenu';
import { PortfolioSignalBadge } from '../components/decision-signals/DecisionSignalDisplay';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { formatUiText } from '../i18n/uiText';
import { PORTFOLIO_PAGE_TEXT, PORTFOLIO_TEXT } from '../locales/featureText';
import { formatNumber, formatPercent, NO_VALUE } from '../utils/format';
import type { FxRefreshFeedback } from '../utils/portfolioFormat';
import {
  buildFxRefreshFeedback,
  formatBrokerLabel,
  formatCashDirectionLabel,
  formatCorporateActionLabel,
  formatMoney,
  formatPct,
  formatPositionMoney,
  formatPositionPrice,
  formatSideLabel,
  getCsvCommitVariant,
  getCsvParseVariant,
  getFxRefreshFeedbackVariant,
  getPositionPriceLabel,
  getTodayIso,
  hasPositionPrice,
} from '../utils/portfolioFormat';
import type { HoldingGroup, HoldingRow, HoldingSortKey } from '../utils/portfolioHoldings';
import {
  buildHoldingRows,
  getCommonScales,
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
  tone: 'danger' | 'warning';
  rowKey?: string;
  action?: { label: string; onClick: () => void };
};

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
    triggered: '触发',
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
    triggered: '觸發',
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
  const stopLoss = risk?.stopLoss;
  const decisionSignalRisk = risk?.decisionSignalRisk;
  const availability = getPortfolioRiskAvailability(risk, snapshot);
  const snapshotAvailable = snapshot !== null;
  const defensiveSignalCount = availability.decisionSignalRisk ? (decisionSignalRisk?.total ?? 0) : 0;

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
      key: 'stop-loss',
      label: text.stopLoss,
      value: availability.stopLoss ? String(stopLoss?.triggeredCount ?? 0) : NO_VALUE,
      detail: availability.stopLoss ? `${text.triggered}: ${stopLoss?.triggeredCount ?? 0} · ${text.near}: ${stopLoss?.nearCount ?? 0}` : text.unavailable,
      tone: availability.stopLoss ? (stopLoss?.nearAlert ? 'danger' : 'success') : 'neutral',
    },
    {
      key: 'ai-signal',
      label: text.aiSignal,
      value: availability.decisionSignalRisk ? String(defensiveSignalCount) : NO_VALUE,
      detail: availability.decisionSignalRisk ? `${text.active}: ${defensiveSignalCount}` : text.unavailable,
      tone: availability.decisionSignalRisk ? (defensiveSignalCount > 0 ? 'warning' : 'success') : 'neutral',
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

const PortfolioRiskFlagCard: React.FC<{
  flag: PortfolioRiskFlag;
  text: RiskDashboardText;
}> = ({ flag, text }) => (
  <div className="rounded-xl border border-border/70 bg-surface/55 px-3 py-2.5">
    <div className="flex min-w-0 items-center justify-between gap-2">
      <div className="flex min-w-0 items-center gap-2">
        <StatusDot tone={flag.tone} className="h-2 w-2" />
        <span className="truncate text-sm font-semibold text-foreground">{flag.label}</span>
      </div>
      <Badge variant={riskFlagBadgeVariant(flag.tone)}>
        {flag.tone === 'success' ? text.stable : flag.tone === 'neutral' ? text.unavailable : text.active}
      </Badge>
    </div>
    <div className="mt-2 text-lg font-semibold text-foreground">{flag.value}</div>
    <div className="mt-1 truncate text-xs text-secondary">{flag.detail}</div>
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
      <div className="mt-3 rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-secondary">
        {emptyLabel}
      </div>
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
  const decisionActionLabels = useMemo(() => buildDecisionActionLabelMap(t), [t]);

  // Set page title
  useEffect(() => {
    document.title = text.documentTitle;
  }, [text.documentTitle]);

  const [accounts, setAccounts] = useState<PortfolioAccountItem[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<AccountOption>('all');
  const [showCreateAccount, setShowCreateAccount] = useState(false);
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

  const [entryOpen, setEntryOpen] = useState(false);
  const [entryKind, setEntryKind] = useState<EntryKind>('trade');
  const [importOpen, setImportOpen] = useState(false);
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
  const [pasteDryRun, setPasteDryRun] = useState(false);
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
    try {
      const snapshotData = await portfolioApi.getSnapshot(buildSnapshotQuery(queryAccountId, costMethod));
      setSnapshot(snapshotData);
      setError(null);

      try {
        const riskData = await portfolioApi.getRisk(buildRiskQuery(queryAccountId, costMethod));
        setRisk(riskData);
      } catch (riskErr) {
        setRisk(null);
        const parsed = getParsedApiError(riskErr);
        setRiskWarning(parsed.message || pageText.loadError);
      }
    } catch (err) {
      setSnapshot(null);
      setRisk(null);
      setError(getParsedApiError(err));
    } finally {
      setIsLoading(false);
    }
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
  const displayFactor = useMemo(() => {
    const consolidated = snapshot?.consolidatedMarketValueBase;
    const total = snapshot?.totalMarketValue;
    if (!snapshot?.displayCurrency || snapshot.consolidatedFxMissing) return null;
    if (typeof consolidated !== 'number' || !Number.isFinite(consolidated)) return null;
    return typeof total === 'number' && total > 0 ? consolidated / total : null;
  }, [snapshot]);
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
  const holdingGroups = useMemo(() => groupHoldingRows(sortedHoldingRows), [sortedHoldingRows]);
  const sharedPriceDate = useMemo(() => getSharedPriceDate(holdingRows), [holdingRows]);
  const holdingCurrency = useMemo(() => getCommonScales(snapshot)?.currency, [snapshot]);
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
      const results = await mapWithConcurrency(
        positionSignalLookups,
        PORTFOLIO_SIGNAL_LOOKUP_CONCURRENCY,
        loadPortfolioSignalLookup,
      );
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
  }, [portfolioSignalsRefreshKey, positionSignalLookups, snapshotMatchesAccountScope, t]);

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

  // 待處理只列異常；沒有就整區不顯示。
  const pendingItems: PendingItem[] = [];
  if (riskAvailability.stopLoss) {
    for (const item of risk?.stopLoss?.items ?? []) {
      pendingItems.push({
        key: `stop-${item.accountId}-${item.symbol}`,
        label: formatUiText(item.isTriggered ? pageText.pendingStopTriggered : pageText.pendingStopNear, {
          symbol: item.symbol,
          pct: formatPct(item.lossPct),
        }),
        tone: item.isTriggered ? 'danger' : 'warning',
        rowKey: findRowKey(item.symbol),
      });
    }
  }
  if (riskAvailability.decisionSignalRisk) {
    for (const item of risk?.decisionSignalRisk?.items ?? []) {
      pendingItems.push({
        key: `signal-${item.accountId ?? 'all'}-${item.market}-${item.symbol}-${item.signal.id ?? item.signal.action}`,
        label: `${item.symbol} · ${formatDecisionSignalRiskAction(item.signal)}`,
        tone: 'warning',
        rowKey: findRowKey(item.symbol),
      });
    }
  }
  for (const row of holdingRows) {
    if (!hasPositionPrice(row)) {
      pendingItems.push({
        key: `price-${row.key}`,
        label: formatUiText(pageText.pendingMissingPrice, { symbol: row.symbol }),
        tone: 'warning',
        rowKey: row.key,
      });
    }
  }
  for (const account of snapshot?.accounts ?? []) {
    if (account.totalCash < 0) {
      pendingItems.push({
        key: `cash-${account.accountId}`,
        label: formatUiText(pageText.pendingNegativeCash, {
          account: account.accountName,
          amount: formatMoney(account.totalCash, account.baseCurrency),
        }),
        tone: 'warning',
        action: {
          label: pageText.pendingBackfill,
          onClick: () => {
            setCashForm((prev) => ({ ...prev, direction: 'in' }));
            openEntry('cash', account.accountId);
          },
        },
      });
    }
  }

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
  const dayAmount = stockDayAmount !== null && fundDay !== null ? stockDayAmount + fundDay : stockDayAmount;
  const amountText = (value: number | null): string => {
    if (value !== null) return formatMoney(value, summaryCurrency);
    return fxMissing ? text.fxMissingTotal : NO_VALUE;
  };
  const signedNode = (value: number | null): React.ReactNode => (
    value === null
      ? (fxMissing ? text.fxMissingTotal : NO_VALUE)
      : <span className={marketToneClass(value)}>{formatSignedMoney(value, summaryCurrency)}</span>
  );

  const snapshotQualityMessage = snapshot?.dataQuality === 'partial' && snapshot.limitations?.length
    ? snapshot.limitations
      .map((limitation) => formatPortfolioLimitation(limitation, language))
      .join(language === 'en' ? '; ' : '；')
    : null;

  const snapshotFailed = !isLoading && snapshot === null;
  const riskFailed = Boolean(riskWarning);
  const riskLoading = isLoading && risk === null && !riskFailed;
  const showAccountNames = (snapshot?.accounts?.length ?? 0) > 1;

  // 小計是跨帳戶加總：同幣就是原幣，跨幣別要換到顯示幣別才可讀。
  const subtotalAmount = (value: number | null): { value: number | null; currency?: string } => {
    if (value === null) return { value: null };
    if (displayFactor !== null && holdingCurrency === snapshot?.currency) {
      return { value: value * displayFactor, currency: snapshot?.displayCurrency ?? undefined };
    }
    return { value, currency: holdingCurrency };
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
      header: pageText.colWeight,
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
    const value = subtotalAmount(group.value);
    const pnl = subtotalAmount(group.pnl);
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

  const renderHoldingMobileCard = (row: HoldingRow) => (
    <div className="flex items-center gap-2 px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2 text-sm">
          <span className="truncate text-foreground">{row.name || row.symbol}</span>
          <span className="shrink-0 tabular-nums">{formatPositionMoney(row.marketValueBase, row)}</span>
        </div>
        <div className="mt-0.5 flex items-center justify-between gap-2 text-xs text-secondary">
          <span className="flex min-w-0 items-center gap-1.5 truncate">
            {row.name ? <span className="font-mono">{row.symbol}</span> : null}
            <span>{row.weightPct === null ? NO_VALUE : formatPct(row.weightPct)}</span>
            <PortfolioSignalBadge item={signalByRowKey.get(row.key)} loading={portfolioSignalsLoading} showHint={false} />
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

  const tradeColumns: DataTableColumn<PortfolioTradeListItem>[] = [
    { key: 'tradeDate', header: pageText.colDate, priority: 'primary' },
    { key: 'side', header: pageText.colSide, render: (item) => formatSideLabel(item.side, language) },
    { key: 'symbol', header: pageText.colSymbol, priority: 'primary', render: (item) => <span className="font-mono">{item.symbol}</span> },
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
    { key: 'symbol', header: pageText.colSymbol, priority: 'primary', render: (item) => <span className="font-mono">{item.symbol}</span> },
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

  const recordsEmpty = (
    <EmptyState
      title={pageText.noRecords}
      description={pageText.noRecordsHint}
      className="border-none bg-transparent px-3 py-6 shadow-none"
    />
  );

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

  return (
    <div className="portfolio-page min-h-screen space-y-4 p-4 md:p-6">
      <PageHeader
        title={text.title}
        actions={(
          <>
            {hasAccounts ? (
              <Segmented
                aria-label={text.accountView}
                className="overflow-x-auto"
                value={String(selectedAccount)}
                onChange={(value) => setSelectedAccount(value === 'all' ? 'all' : Number(value))}
                options={[
                  { value: 'all', label: text.allAccounts },
                  ...accounts.map((account) => ({ value: String(account.id), label: account.name })),
                ]}
              />
            ) : null}
            <Button onClick={() => openEntry('trade')} disabled={!hasAccounts}>{pageText.recordEntry}</Button>
            <Button variant="secondary" onClick={openImport} disabled={!hasAccounts}>{pageText.importEntry}</Button>
            <IconButton
              aria-label={isLoading ? text.refreshing : text.refreshData}
              icon={<RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />}
              onClick={() => void handleRefresh()}
              disabled={isLoading || fxRefreshing}
            />
            <ActionMenu
              label={pageText.more}
              header={(
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
              )}
              items={[
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
              ]}
            />
          </>
        )}
      />

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

      <section className="space-y-2" aria-label={pageText.metricTotalAssets}>
        <MetricGroup columns={4}>
          <Metric
            hero
            label={pageText.metricTotalAssets}
            value={amountText(totalAssets)}
            hint={hasFunds
              ? formatUiText(pageText.includesFunds, { amount: formatMoney(fundValue, summaryCurrency) })
              : fundsUnavailable && equityAmount !== null ? pageText.excludesFunds : undefined}
          />
          <Metric
            label={pageText.metricDay}
            value={signedNode(dayAmount)}
            hint={fundsUnavailable && dayAmount !== null ? pageText.stocksOnly : undefined}
          />
          <Metric label={pageText.metricUnrealized} value={signedNode(unrealizedAmount)} />
          <Metric label={pageText.metricRealized} value={signedNode(realizedAmount)} />
          <Metric label={pageText.metricMarketValue} value={amountText(marketValueAmount)} />
          <Metric label={pageText.metricCash} value={amountText(cashAmount)} />
          {hasFunds || fundsUnavailable ? (
            <Metric
              label={pageText.metricFunds}
              value={fundValue === null ? NO_VALUE : formatMoney(fundValue, summaryCurrency)}
              hint={fundDay === null ? undefined : (
                <span className={marketToneClass(fundDay)}>{formatSignedMoney(fundDay, summaryCurrency)}</span>
              )}
            />
          ) : null}
        </MetricGroup>
        <div className="flex flex-wrap items-center gap-2 text-xs text-secondary">
          <span>{text.fxStatus}</span>
          {fxMissing
            ? <Badge variant="warning">{text.fxMissing}</Badge>
            : fxStale === true
              ? <Badge variant="warning">{text.stale}</Badge>
              : fxStale === false
                ? <Badge variant="success">{text.latest}</Badge>
                : <Badge variant="default">{riskDashboardText.unavailable}</Badge>}
          <button
            type="button"
            className="btn-secondary !px-3 !py-1 !text-xs shrink-0"
            onClick={() => void handleRefreshFx()}
            disabled={!hasAccounts || isLoading || fxRefreshing}
          >
            {fxRefreshing ? text.refreshing : text.refreshFx}
          </button>
          {fxMissing ? <span>{text.fxMissingHint.replace('{pairs}', fxMissingPairs.join(', '))}</span> : null}
          {snapshotQualityMessage ? (
            <span>
              <span className="font-medium">{text.snapshotPartialTitle}</span>
              {'：'}
              <span>{snapshotQualityMessage}</span>
            </span>
          ) : null}
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

      {pendingItems.length > 0 ? (
        <section data-testid="portfolio-pending">
          <Card padding="md">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
              <AlertTriangle className="h-4 w-4 text-warning" />
              {pageText.sectionPending}
            </h2>
            <ul className="divide-y divide-border/40">
              {pendingItems.map((item) => (
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
                  </span>
                  {item.action ? (
                    <Button size="sm" variant="secondary" onClick={item.action.onClick}>{item.action.label}</Button>
                  ) : null}
                </li>
              ))}
            </ul>
          </Card>
        </section>
      ) : null}

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

      {snapshotFailed || riskFailed || riskLoading ? null : (
        <section>
          <Card padding="md">
            <h2 className="mb-3 text-sm font-semibold text-foreground">
              {concentrationMode === 'sector' ? text.sectorConcentration : text.positionConcentrationFallback}
            </h2>
            {concentrationBarRows.length > 0 ? (
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
            ) : (
              <EmptyState
                title={text.noConcentrationTitle}
                description={text.noConcentrationDescription}
                className="border-none bg-transparent px-4 py-10 shadow-none"
              />
            )}
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
            <div data-testid="portfolio-risk-skeleton" className="grid gap-2 md:grid-cols-2 xl:grid-cols-3" aria-hidden="true">
              {Array.from({ length: 6 }, (_, index) => (
                <div key={index} className="h-[5.5rem] animate-pulse rounded-xl bg-border/40" />
              ))}
            </div>
          ) : (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,0.75fr)]">
              <div className="min-w-0">
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-secondary">
                  <AlertTriangle className="h-3.5 w-3.5 text-warning" />
                  {riskDashboardText.riskFlags}
                </div>
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                  {portfolioRiskFlags.map((flag) => (
                    <PortfolioRiskFlagCard key={flag.key} flag={flag} text={riskDashboardText} />
                  ))}
                </div>
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
            <input aria-label={pageText.dateFrom} className={PORTFOLIO_INPUT_CLASS} type="date" value={eventDateFrom} onChange={(e) => setEventDateFrom(e.target.value)} />
            <input aria-label={pageText.dateTo} className={PORTFOLIO_INPUT_CLASS} type="date" value={eventDateTo} onChange={(e) => setEventDateTo(e.target.value)} />
            {eventType === 'trade' || eventType === 'corporate' ? (
              <input className={PORTFOLIO_INPUT_CLASS} placeholder={pageText.filterSymbol} value={eventSymbol}
                onChange={(e) => setEventSymbol(e.target.value)} />
            ) : null}
            {eventType === 'trade' ? (
              <select aria-label={pageText.sideAll} className={PORTFOLIO_SELECT_CLASS} value={eventSide} onChange={(e) => setEventSide(e.target.value as '' | PortfolioSide)}>
                <option value="">{pageText.sideAll}</option>
                <option value="buy">{pageText.buy}</option>
                <option value="sell">{pageText.sell}</option>
              </select>
            ) : null}
            {eventType === 'cash' ? (
              <select aria-label={pageText.directionAll} className={PORTFOLIO_SELECT_CLASS} value={eventDirection}
                onChange={(e) => setEventDirection(e.target.value as '' | PortfolioCashDirection)}>
                <option value="">{pageText.directionAll}</option>
                <option value="in">{pageText.cashIn}</option>
                <option value="out">{pageText.cashOut}</option>
              </select>
            ) : null}
            {eventType === 'corporate' ? (
              <select aria-label={pageText.actionAll} className={PORTFOLIO_SELECT_CLASS} value={eventActionType}
                onChange={(e) => setEventActionType(e.target.value as '' | PortfolioCorporateActionType)}>
                <option value="">{pageText.actionAll}</option>
                <option value="cash_dividend">{pageText.actionCashDividend}</option>
                <option value="split_adjustment">{pageText.actionSplit}</option>
              </select>
            ) : null}
          </div>
          {writeBlocked ? <p className="mb-2 text-[11px] text-secondary">{pageText.deleteHintBlocked}</p> : null}
          {eventType === 'trade' ? (
            <DataTable columns={tradeColumns} rows={tradeEvents} rowKey={(item) => `t-${item.id}`} density="compact" emptyState={eventLoading ? undefined : recordsEmpty} aria-label={pageText.typeTrade} />
          ) : eventType === 'cash' ? (
            <DataTable columns={cashColumns} rows={cashEvents} rowKey={(item) => `c-${item.id}`} density="compact" emptyState={eventLoading ? undefined : recordsEmpty} aria-label={pageText.typeCash} />
          ) : (
            <DataTable columns={corporateColumns} rows={corporateEvents} rowKey={(item) => `ca-${item.id}`} density="compact" emptyState={eventLoading ? undefined : recordsEmpty} aria-label={pageText.typeCorporate} />
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

      <Drawer isOpen={entryOpen} onClose={() => setEntryOpen(false)} title={pageText.entryTitle}>
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
            <form className="space-y-2" onSubmit={handleTradeSubmit}>
              <input className={PORTFOLIO_INPUT_CLASS} placeholder={pageText.symbolPlaceholder} value={tradeForm.symbol}
                onChange={(e) => setTradeForm((prev) => ({ ...prev, symbol: e.target.value }))} required />
              <div className="grid grid-cols-2 gap-2">
                <input className={PORTFOLIO_INPUT_CLASS} type="date" value={tradeForm.tradeDate}
                  onChange={(e) => setTradeForm((prev) => ({ ...prev, tradeDate: e.target.value }))} required />
                <select className={PORTFOLIO_SELECT_CLASS} value={tradeForm.side}
                  onChange={(e) => setTradeForm((prev) => ({ ...prev, side: e.target.value as PortfolioSide }))}>
                  <option value="buy">{pageText.buy}</option>
                  <option value="sell">{pageText.sell}</option>
                </select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <input className={PORTFOLIO_INPUT_CLASS} type="number" min="0" step="0.0001" placeholder={pageText.quantityRequired} value={tradeForm.quantity}
                  onChange={(e) => setTradeForm((prev) => ({ ...prev, quantity: e.target.value }))} required />
                <input className={PORTFOLIO_INPUT_CLASS} type="number" min="0" step="0.0001" placeholder={pageText.priceRequired} value={tradeForm.price}
                  onChange={(e) => setTradeForm((prev) => ({ ...prev, price: e.target.value }))} required />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <input className={PORTFOLIO_INPUT_CLASS} type="number" min="0" step="0.0001" placeholder={pageText.feeOptional} value={tradeForm.fee}
                  onChange={(e) => setTradeForm((prev) => ({ ...prev, fee: e.target.value }))} />
                <input className={PORTFOLIO_INPUT_CLASS} type="number" min="0" step="0.0001" placeholder={pageText.taxOptional} value={tradeForm.tax}
                  onChange={(e) => setTradeForm((prev) => ({ ...prev, tax: e.target.value }))} />
              </div>
              <p className="text-xs text-secondary">{pageText.feeHint}</p>
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
            <div className="grid grid-cols-2 gap-2">
              <input type="date" className={PORTFOLIO_INPUT_CLASS} value={pasteTradeDate}
                onChange={(e) => setPasteTradeDate(e.target.value)} aria-label={pageText.pasteDate} />
              <button type="button" className="btn-secondary" disabled={!pasteParseResult?.missingCost?.length}
                onClick={handlePasteToTemplate}>
                {pageText.toTemplate}
              </button>
            </div>
            <div className="flex items-center gap-2 text-xs text-secondary">
              <input id="paste-dry-run" type="checkbox" checked={pasteDryRun} onChange={(e) => setPasteDryRun(e.target.checked)} />
              <label htmlFor="paste-dry-run">{pageText.dryRun}</label>
            </div>
            <div className="flex gap-2">
              <button type="button" className="btn-secondary flex-1" disabled={!pasteText.trim() || pasteParsing}
                onClick={() => void handleParsePaste()}>
                {pasteParsing ? pageText.parsing : pageText.parseContent}
              </button>
              <button type="button" className="btn-secondary flex-1"
                disabled={!pasteText.trim() || !writableAccountId || pasteCommitting} onClick={() => void handleCommitPaste()}>
                {pasteCommitting ? pageText.committing : pageText.commitImport}
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

          <h3 className="pt-2 text-sm font-semibold text-foreground">{pageText.csvTitle}</h3>
          <div className="space-y-2">
            {brokerLoadWarning ? (
              <InlineAlert
                variant="warning"
                className="rounded-lg px-2 py-1 text-xs shadow-none"
                message={brokerLoadWarning}
              />
            ) : null}
            <div className="grid grid-cols-2 gap-2">
              <select className={PORTFOLIO_SELECT_CLASS} value={selectedBroker} onChange={(e) => setSelectedBroker(e.target.value)}>
                {brokers.map((item) => <option key={item.broker} value={item.broker}>{formatBrokerLabel(item.broker, item.displayName)}</option>)}
              </select>
              <label className={PORTFOLIO_FILE_PICKER_CLASS}>
                {pageText.csvPick}
                <input type="file" accept=".csv" className="hidden"
                  onChange={(e) => setCsvFile(e.target.files && e.target.files[0] ? e.target.files[0] : null)} />
              </label>
            </div>
            <div className="flex items-center gap-2 text-xs text-secondary">
              <input id="csv-dry-run" type="checkbox" checked={csvDryRun} onChange={(e) => setCsvDryRun(e.target.checked)} />
              <label htmlFor="csv-dry-run">{pageText.dryRun}</label>
            </div>
            <div className="flex gap-2">
              <button type="button" className="btn-secondary flex-1" disabled={!csvFile || csvParsing} onClick={() => void handleParseCsv()}>
                {csvParsing ? pageText.parsing : pageText.parseFile}
              </button>
              <button type="button" className="btn-secondary flex-1"
                disabled={!csvFile || !writableAccountId || csvCommitting} onClick={() => void handleCommitCsv()}>
                {csvCommitting ? pageText.committing : pageText.commitImport}
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
    </div>
  );
};

export default PortfolioPage;
