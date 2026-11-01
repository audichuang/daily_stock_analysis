import { ChevronDown, Star } from 'lucide-react';
import type React from 'react';
import { useId, useState } from 'react';
import { AlertBellLink } from '../alerts/AlertBellLink';
import type {
  ReportDetails as ReportDetailsType,
  ReportMeta,
  ReportStrategy as ReportStrategyType,
  ReportSummary as ReportSummaryType,
} from '../../types/analysis';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { formatUiText } from '../../i18n/uiText';
import { getMarketReviewUiText } from '../../locales/marketReviewText';
import { cn } from '../../utils/cn';
import {
  buildDecisionActionLabelMap,
  getDecisionActionLabel,
  getDecisionActionTone,
} from '../../utils/decisionAction';
import { formatDateTime, formatPercent, formatPrice } from '../../utils/format';
import { getMarketPhaseShortLabel, getPartialBarLabel } from '../../utils/marketPhase';
import { marketToneClass } from '../../utils/marketTone';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Badge, Card, IconButton, ScoreBar, Tooltip } from '../common';
import { ShareImageButton } from './ShareImageButton';

interface ReportOverviewProps {
  meta: ReportMeta;
  summary: ReportSummaryType;
  details?: ReportDetailsType;
  /** Structured sniper prices feed the key-level strip; omitted means no strip. */
  strategy?: ReportStrategyType;
  isHistory?: boolean;
  /** 缺資料影響判斷時的提示，放在結論下面。 */
  notice?: string | null;
  watchlist?: {
    isInWatchlist: (code: string) => boolean;
    onToggle: (code: string) => void;
    isActioning: boolean;
    actionMessage: string | null;
  };
  headerActions?: React.ReactNode;
}

type BoardStatus = 'leading' | 'lagging';

type BoardSignal = {
  status: BoardStatus;
  changePct?: number;
};

type BoardSignalMaps = {
  sectors: Map<string, BoardSignal>;
  concepts: Map<string, BoardSignal>;
};

type PreparedBoard = {
  key: string;
  name: string;
  signal?: BoardSignal;
};

const ACTION_TONE_CLASS = {
  brand: 'text-cyan',
  neutral: 'text-secondary-text',
  caution: 'text-warning',
  default: 'text-foreground',
} as const;

// 盤中報價不是收盤價；其他階段的報價都是最近一場的收盤。
const INTRADAY_PHASES = new Set(['intraday', 'lunch_break', 'closing_auction']);

const normalizeBoardName = (value?: string): string =>
  (value || '').trim().replace(/\s+/g, ' ');

const normalizeBoardType = (value?: string): 'sector' | 'concept' | null => {
  const normalized = (value || '').trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  if (['行业', '行业板块', 'industry', 'sector'].includes(normalized)) {
    return 'sector';
  }
  if (['概念', '概念板块', '题材', 'concept', 'theme'].includes(normalized)) {
    return 'concept';
  }
  return null;
};

const coerceFiniteNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : undefined;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim().replace(/%$/, '');
    if (!trimmed) {
      return undefined;
    }
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
};

const buildRankingSignalMap = (rankings?: ReportDetailsType['sectorRankings']): Map<string, BoardSignal> => {
  const signalMap = new Map<string, BoardSignal>();
  const topBoards = Array.isArray(rankings?.top) ? rankings.top : [];
  const bottomBoards = Array.isArray(rankings?.bottom) ? rankings.bottom : [];

  topBoards.forEach((item) => {
    const normalizedName = normalizeBoardName(item?.name);
    const changePct = coerceFiniteNumber(item?.changePct);
    if (!normalizedName || changePct === undefined) {
      return;
    }
    signalMap.set(normalizedName, {
      status: 'leading',
      changePct,
    });
  });

  bottomBoards.forEach((item) => {
    const normalizedName = normalizeBoardName(item?.name);
    const changePct = coerceFiniteNumber(item?.changePct);
    if (!normalizedName || changePct === undefined) {
      return;
    }
    signalMap.set(normalizedName, {
      status: 'lagging',
      changePct,
    });
  });

  return signalMap;
};

const buildBoardSignalMaps = (details?: ReportDetailsType): BoardSignalMaps => ({
  sectors: buildRankingSignalMap(details?.sectorRankings),
  concepts: buildRankingSignalMap(details?.conceptRankings),
});

const resolveBoardSignal = (
  board: { name?: string; type?: string },
  signalMaps: BoardSignalMaps,
): BoardSignal | undefined => {
  const boardName = normalizeBoardName(board.name);
  if (!boardName) {
    return undefined;
  }
  const boardType = normalizeBoardType(board.type);
  if (boardType === 'sector') {
    return signalMaps.sectors.get(boardName);
  }
  if (boardType === 'concept') {
    return signalMaps.concepts.get(boardName);
  }
  const sectorSignal = signalMaps.sectors.get(boardName);
  const conceptSignal = signalMaps.concepts.get(boardName);
  if (sectorSignal && !conceptSignal) {
    return sectorSignal;
  }
  if (conceptSignal && !sectorSignal) {
    return conceptSignal;
  }
  return undefined;
};

const buildPreparedRelatedBoards = (
  boards: ReportDetailsType['belongBoards'],
  signalMaps: BoardSignalMaps,
): PreparedBoard[] => {
  if (!Array.isArray(boards)) {
    return [];
  }

  return boards.reduce<PreparedBoard[]>((preparedBoards, board, index) => {
    const boardName = normalizeBoardName(board?.name);
    if (!boardName) {
      return preparedBoards;
    }
    preparedBoards.push({
      key: `${boardName}-${board?.code || index}`,
      name: boardName,
      signal: resolveBoardSignal(board, signalMaps),
    });
    return preparedBoards;
  }, []);
};

/** 2026-10-30 → 10/30；不是日期字串回 null，不猜。 */
const shortDate = (value?: string | null): string | null => {
  const matched = /^\d{4}-(\d{2})-(\d{2})/.exec(value ?? '');
  return matched ? `${matched[1]}/${matched[2]}` : null;
};

type KeyLevelCell = { key: string; label: string; price: number };

// Which sniper prices the strip shows depends on the (post-guardrail) action.
const KEY_LEVEL_LAYOUT: Partial<Record<NonNullable<ReportSummaryType['action']>, Array<'entry' | 'stop' | 'rebound'>>> = {
  buy: ['entry', 'stop'],
  add: ['entry', 'stop'],
  reduce: ['stop', 'rebound'],
  watch: ['stop', 'rebound'],
};

const finiteOrNull = (value?: number | null): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

/**
 * 報告首屏：股名與價格、結論列、分持股建議。單欄全寬，動作一律依枚舉查詞彙表，不用存檔的標籤。
 */
export const ReportOverview: React.FC<ReportOverviewProps> = ({
  meta,
  summary,
  details,
  strategy,
  notice,
  watchlist,
  headerActions,
}) => {
  const { t } = useUiLanguage();
  const reportLanguage = normalizeReportLanguage(meta.reportLanguage);
  const text = getReportText(reportLanguage);
  const uiText = getMarketReviewUiText(reportLanguage);
  const guardrailDetailId = useId();
  const [guardrailOpen, setGuardrailOpen] = useState(false);
  const marketPhaseLabel = getMarketPhaseShortLabel(meta.marketPhaseSummary, reportLanguage);
  const partialBarLabel = meta.marketPhaseSummary?.isPartialBar === true
    ? getPartialBarLabel(reportLanguage)
    : null;
  const relatedBoards = (Array.isArray(details?.belongBoards) ? details.belongBoards : [])
    .filter((board) => normalizeBoardName(board?.name).length > 0);
  const preparedRelatedBoards = buildPreparedRelatedBoards(relatedBoards, buildBoardSignalMaps(details));

  const actionLabels = buildDecisionActionLabelMap(t);
  const actionLabel = getDecisionActionLabel(
    summary.action,
    summary.actionLabel,
    summary.operationAdvice,
    text.noAdvice,
    actionLabels,
  );
  const actionToneClass = ACTION_TONE_CLASS[getDecisionActionTone(summary.action, summary.actionLabel, summary.operationAdvice)];
  const oneSentence = summary.oneSentence?.trim() || null;
  const analysisSummary = summary.analysisSummary?.trim() || null;
  const guardrailSentence = oneSentence || analysisSummary || text.noAnalysisSummary;

  // Guardrail presentation only; the action label above always stays post-guardrail.
  const guardrailApplied = summary.guardrailApplied === true;
  const guardrailKind = summary.guardrailKind ?? null;
  const guardrailReason = summary.guardrailReason?.trim() || null;
  const modelSentence = summary.modelOneSentence?.trim() || null;
  // Rule 1: data was missing, so lead with what the model meant and tuck the guardrail into a tag.
  const showModelIntent = guardrailApplied && guardrailKind === 'data_unavailable' && modelSentence !== null;
  const sentence = showModelIntent
    ? formatUiText(uiText.modelIntent, { sentence: modelSentence ?? '' })
    : guardrailSentence;
  const extraSummary = oneSentence && analysisSummary && analysisSummary !== oneSentence ? analysisSummary : null;
  const score = typeof summary.sentimentScore === 'number' && Number.isFinite(summary.sentimentScore)
    ? summary.sentimentScore
    : null;

  const currency = meta.currency ?? undefined;
  // Only the change amount and percent carry the market tone; the price itself stays neutral.
  const priceToneClass = marketToneClass(meta.changePct, 'text-foreground');
  const priceDateText = shortDate(meta.priceDate);
  const pricePhaseText = INTRADAY_PHASES.has(meta.marketPhaseSummary?.phase ?? '') ? text.priceIntraday : text.priceAtClose;
  const changeAmount = typeof meta.changeAmount === 'number' ? meta.changeAmount : null;

  const adviceSource = showModelIntent && summary.modelPositionAdvice ? summary.modelPositionAdvice : summary.positionAdvice;
  const noPositionAdvice = adviceSource?.noPosition?.trim() || null;
  const hasPositionAdvice = adviceSource?.hasPosition?.trim() || null;
  type AdviceColumn = { key: string; title: string; body: string; pinned: boolean };
  const adviceColumns = ([
    noPositionAdvice ? { key: 'no-position', title: text.ifNoPosition, body: noPositionAdvice, pinned: false } : null,
    hasPositionAdvice ? { key: 'has-position', title: text.ifHasPosition, body: hasPositionAdvice, pinned: meta.held === true } : null,
  ] as Array<AdviceColumn | null>).filter((column): column is AdviceColumn => column !== null);
  // held 為 null 是無法判定，維持原順序、不標記；只有確定持有才把「手上有」置頂。
  adviceColumns.sort((a, b) => Number(b.pinned) - Number(a.pinned));

  // Only model-given numbers count; legacy prices parsed from prose are never shown here.
  const structuredSniper = strategy?.sniperPricesSource === 'structured' ? strategy.sniperPrices ?? null : null;
  const currentStop = finiteOrNull(structuredSniper?.stopLoss);
  const currentPrice = finiteOrNull(meta.currentPrice);
  const keyLevelCells: KeyLevelCell[] = structuredSniper && summary.action
    ? (KEY_LEVEL_LAYOUT[summary.action] ?? []).flatMap((slot) => {
        const cell = slot === 'entry'
          ? { key: slot, label: uiText.levelEntry, price: finiteOrNull(structuredSniper.idealBuy) }
          : slot === 'stop'
            ? { key: slot, label: uiText.levelStop, price: currentStop }
            : { key: slot, label: uiText.levelRebound, price: finiteOrNull(structuredSniper.takeProfit) };
        return cell.price === null ? [] : [{ ...cell, price: cell.price }];
      })
    : [];
  const formatKeyLevel = ({ label, price }: KeyLevelCell): string => {
    const distance = currentPrice ? formatPercent(((price - currentPrice) / currentPrice) * 100, 1) : null;
    return `${label} ${formatPrice(price, currency)}${distance ? `（${distance}）` : ''}`;
  };

  const previous = meta.previousReport;
  const previousDate = shortDate(previous?.createdAt);
  const previousStop = finiteOrNull(previous?.stopLoss);
  const comparisonParts = previous ? [
    previous.action ? `${actionLabels[previous.action]} → ${actionLabel}` : null,
    typeof previous.score === 'number' && score !== null ? `${text.modelScore} ${previous.score} → ${score}` : null,
    previousStop !== null
      ? currentStop !== null
        ? formatUiText(uiText.stopChange, { from: formatPrice(previousStop, currency), to: formatPrice(currentStop, currency) })
        : formatUiText(uiText.previousStop, { value: formatPrice(previousStop, currency) })
      : null,
  ].filter((part): part is string => part !== null) : [];

  const boardNames = reportLanguage === 'zh' || reportLanguage === 'zh-TW' ? uiText.boardNames : {};
  const guardrailTag = !guardrailApplied
    ? null
    : showModelIntent
      ? { label: formatUiText(uiText.guardrailDataTag, { action: actionLabel ?? '' }), className: 'border-subtle bg-subtle text-secondary-text' }
      : guardrailKind === 'market_logic'
        ? { label: uiText.guardrailMarketTag, className: 'border-warning/30 bg-warning/10 text-warning' }
        : null;
  const guardrailDetail = showModelIntent
    ? [guardrailReason, formatUiText(uiText.guardrailVersion, { sentence: guardrailSentence })]
    : guardrailKind === 'market_logic'
      ? [guardrailReason, modelSentence ? formatUiText(uiText.modelOriginal, { sentence: modelSentence }) : null]
      : [guardrailReason];
  const guardrailDetailLines = guardrailDetail.filter((line): line is string => Boolean(line));

  const canToggleWatchlist = Boolean(watchlist) && meta.reportType !== 'market_review' && meta.assetType !== 'index';
  const inWatchlist = watchlist?.isInWatchlist(meta.stockCode) ?? false;
  const trendPrediction = summary.trendPrediction?.trim() || null;
  const confidenceText = (
    <>
      {text.confidenceLabel} <span className="font-semibold text-foreground">{summary.confidenceLevel?.trim()}</span>
    </>
  );

  return (
    <div className="space-y-4">
      <Card variant="highlight" padding="md" className="home-report-hero">
        {/* 手機寬時分享鈕換行，不壓縮股名（中文股名會被擠成一字一行） */}
        <div className="flex flex-wrap items-start justify-between gap-3" data-testid="report-hero-header">
          <div className="min-w-[12rem] flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[28px] font-bold leading-tight text-foreground">
                {meta.stockName || meta.stockCode}
              </h2>
              <span className="inline-flex shrink-0 items-center gap-1">
                <span className="home-accent-chip px-2 py-0.5 font-mono text-xs">{meta.stockCode}</span>
                {canToggleWatchlist && watchlist ? (
                  <IconButton
                    size="sm"
                    aria-label={inWatchlist ? t('report.removeFromWatchlist') : t('report.addToWatchlist')}
                    aria-pressed={inWatchlist}
                    disabled={watchlist.isActioning}
                    onClick={() => watchlist.onToggle(meta.stockCode)}
                    icon={<Star className={cn('h-4 w-4', inWatchlist && 'fill-current text-warning')} aria-hidden="true" />}
                  />
                ) : null}
                <AlertBellLink code={meta.stockCode} />
              </span>
            </div>
            {watchlist?.actionMessage && canToggleWatchlist ? (
              <p className="mt-1 text-[11px] text-secondary-text">{watchlist.actionMessage}</p>
            ) : null}
            {typeof meta.currentPrice === 'number' ? (
              <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1" data-testid="report-price">
                <span className="text-3xl font-bold tabular-nums text-foreground">
                  {formatPrice(meta.currentPrice, currency)}
                </span>
                <span className={cn('text-base font-semibold tabular-nums', priceToneClass)}>
                  {changeAmount !== null ? `${changeAmount > 0 ? '+' : ''}${formatPrice(Math.round(changeAmount * 100) / 100, currency)} ` : ''}
                  {formatPercent(meta.changePct)}
                </span>
                {priceDateText ? (
                  <span className="text-xs text-muted-text">{priceDateText} {pricePhaseText}</span>
                ) : null}
              </div>
            ) : null}
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              {marketPhaseLabel ? (
                <Badge variant="info" className="shrink-0 gap-1.5 shadow-none" aria-label={marketPhaseLabel}>
                  {marketPhaseLabel}
                </Badge>
              ) : null}
              {partialBarLabel ? (
                <Badge variant="warning" className="shrink-0 shadow-none" aria-label={partialBarLabel}>
                  {partialBarLabel}
                </Badge>
              ) : null}
              <span className="text-xs text-muted-text">{formatDateTime(meta.createdAt)}</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            {headerActions}
            <ShareImageButton
              recordId={meta.id}
              reportTitle={`${meta.stockName || meta.stockCode}-${meta.stockCode}`}
              reportLanguage={reportLanguage}
              iconOnlyBelowMd
            />
          </div>
        </div>

        <div className="home-divider mt-3 border-t pt-3" data-testid="report-conclusion">
          <div className="flex flex-col gap-x-4 gap-y-1 md:flex-row md:items-baseline">
            <span data-testid="report-action" className={cn('shrink-0 text-3xl font-bold leading-tight', actionToneClass)}>
              {actionLabel}
            </span>
            <p data-testid="report-sentence" className="min-w-0 flex-1 whitespace-pre-wrap text-left text-lg font-semibold leading-7 text-foreground">
              {sentence}
            </p>
          </div>
          {keyLevelCells.length > 0 ? (
            <p
              data-testid="report-key-levels"
              aria-label={uiText.keyLevels}
              className="mt-2 text-left text-sm tabular-nums text-secondary-text"
            >
              {keyLevelCells.map(formatKeyLevel).join('｜')}
            </p>
          ) : null}
          <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-secondary-text">
            {summary.timeSensitivity?.trim() ? <span data-testid="report-time-sensitivity">{summary.timeSensitivity.trim()}</span> : null}
            {summary.confidenceLevel?.trim() ? (
              summary.confidenceReason?.trim() ? (
                <Tooltip content={summary.confidenceReason.trim()}>
                  <span>{confidenceText}</span>
                </Tooltip>
              ) : <span>{confidenceText}</span>
            ) : null}
            {score !== null ? <ScoreBar score={score} label={text.modelScore} className="w-56 max-w-full" /> : null}
            {comparisonParts.length > 0 ? (
              <span data-testid="report-comparison">
                {text.previousReport}{previousDate ? ` ${previousDate}` : ''}：{comparisonParts.join('，')}
              </span>
            ) : null}
            {guardrailApplied ? (
              <span
                className={cn('inline-flex flex-wrap items-center gap-1.5', guardrailOpen && 'w-full')}
                data-testid="report-guardrail"
                data-guardrail-kind={guardrailTag ? (showModelIntent ? 'data_unavailable' : 'market_logic') : 'legacy'}
              >
                {guardrailDetailLines.length > 0 ? (
                  <button
                    type="button"
                    aria-expanded={guardrailOpen}
                    aria-controls={guardrailDetailId}
                    onClick={() => setGuardrailOpen((open) => !open)}
                    className={cn(
                      'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
                      guardrailTag ? guardrailTag.className : 'border-warning/30 bg-warning/10 text-warning',
                    )}
                  >
                    {guardrailTag ? guardrailTag.label : text.guardrailAdjusted}
                    <ChevronDown className={cn('h-3 w-3 transition-transform', guardrailOpen && 'rotate-180')} aria-hidden="true" />
                  </button>
                ) : guardrailTag ? (
                  <span className={cn('inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium', guardrailTag.className)}>
                    {guardrailTag.label}
                  </span>
                ) : (
                  <Badge variant="warning" className="shadow-none">{text.guardrailAdjusted}</Badge>
                )}
                {guardrailOpen && guardrailDetailLines.length > 0 ? (
                  <span id={guardrailDetailId} data-testid="report-guardrail-detail" className="block w-full space-y-0.5 text-left leading-5">
                    {guardrailDetailLines.map((line) => <span key={line} className="block">{line}</span>)}
                  </span>
                ) : null}
              </span>
            ) : null}
          </div>
          {notice ? (
            <p role="note" data-testid="report-gap-notice" className="mt-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-left text-sm leading-6 text-foreground">
              {notice}
            </p>
          ) : null}
          {details?.emptyNewsDisclosure ? (
            <p role="note" className="mt-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-left text-sm leading-6 text-foreground">
              {details.emptyNewsDisclosure}
            </p>
          ) : null}
          {extraSummary ? (
            <details className="mt-2 text-left text-sm">
              <summary className="cursor-pointer text-xs text-secondary-text">{text.analysisDetail}</summary>
              <p className="mt-1 max-w-[72ch] whitespace-pre-wrap leading-6 text-foreground">{extraSummary}</p>
            </details>
          ) : null}
        </div>
      </Card>

      {adviceColumns.length > 0 ? (
        <div className={cn('grid grid-cols-1 gap-3', adviceColumns.length > 1 && 'md:grid-cols-2')} data-testid="report-position-advice">
          {adviceColumns.map((column) => (
            <Card key={column.key} variant="surface" padding="sm" className="home-panel-card text-left">
              <div data-testid={`advice-${column.key}`} data-pinned={column.pinned}>
                <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  {column.title}
                  {column.pinned ? <Badge variant="info" className="shadow-none">{text.heldMarker}</Badge> : null}
                </h3>
                <p className="mt-1 text-sm leading-6 text-secondary-text">{column.body}</p>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Card variant="surface" padding="sm" className="home-panel-card text-left">
          <h3 className="text-sm font-semibold text-foreground">{text.actionAdvice}</h3>
          <p className="mt-1 text-sm leading-6 text-secondary-text">{summary.operationAdvice || text.noAdvice}</p>
        </Card>
      )}

      {trendPrediction || preparedRelatedBoards.length > 0 ? (
        <div className="min-w-0 max-w-full space-y-2 px-1 text-left">
          {trendPrediction ? (
            <p className="text-xs leading-5 text-secondary-text">
              <span className="text-muted-text">{text.trendPrediction}：</span>{trendPrediction}
            </p>
          ) : null}
          {preparedRelatedBoards.length > 0 ? (
            <section aria-label={text.relatedBoards} className="flex min-w-0 max-w-full items-center gap-2">
              <span className="shrink-0 text-xs text-muted-text">{text.relatedBoards}</span>
              <div className="home-related-board-list flex min-h-6 w-full min-w-0 max-w-full flex-nowrap items-center gap-2 overflow-x-auto overscroll-x-contain touch-pan-x pb-1">
                {preparedRelatedBoards.map((board) => (
                  <div key={board.key} className="inline-flex shrink-0 items-center gap-1.5 text-xs">
                    <span className="home-accent-chip px-2 py-0.5 font-medium">{boardNames[board.name] ?? board.name}</span>
                    {board.signal ? (
                      <span className="text-secondary-text">
                        {board.signal.status === 'leading' ? text.leadingBoard : text.laggingBoard}
                      </span>
                    ) : null}
                    {board.signal?.changePct !== undefined ? (
                      <span className={cn('tabular-nums', marketToneClass(board.signal.changePct))}>
                        {formatPercent(board.signal.changePct)}
                      </span>
                    ) : null}
                  </div>
                ))}
              </div>
            </section>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};
