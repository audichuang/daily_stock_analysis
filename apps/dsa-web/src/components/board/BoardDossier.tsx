import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { stocksApi, type DossierSummary, type DossierTone } from '../../api/stocks';
import { getParsedApiError } from '../../api/error';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { cn } from '../../utils/cn';
import { ConfirmDialog } from '../common/ConfirmDialog';
import { Button } from '../common/Button';
import { Tooltip as HintTooltip } from '../common/Tooltip';
import { BOARD_TEXT } from '../../locales/boardText';
import { nearestLevels, type NearLevel } from '../../utils/dossierLevels';
import { StockDossierDrawer } from '../report/StockDossierDrawer';

// 台股慣例：紅漲綠跌（與四維度報告一致）
const TONE_CLASS: Record<DossierTone, string> = {
  pos: 'border-red-500/30 bg-red-500/10 text-red-500',
  neg: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600',
  neu: 'border-amber-500/30 bg-amber-500/10 text-amber-600',
  watch: 'border-border bg-hover text-secondary-text',
};
const VERDICT_KEYS = ['fundamental', 'chips', 'technical', 'valuation'] as const;

const fmtPrice = (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 2 });
const fmtPct = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;

function levelRange(near: NearLevel): string {
  const { low, high } = near.level;
  return low === high ? fmtPrice(low) : `${fmtPrice(low)}~${fmtPrice(high)}`;
}

/**
 * 最近支撐／壓力（用即時價量距離）。資料基準日之後有除權息／減資時價位是舊基準（前復權到 as_of），
 * 即時價已是新基準，量出來會偏掉整個調整幅度，所以不算，等盤後資料更新。
 */
function nearFor(summary: DossierSummary, price?: number | null) {
  if (summary.adjustedAfter) return null;
  const ref = price ?? summary.close;
  return ref ? nearestLevels(summary.levels, ref) : null;
}

/** Short structure-kind label for the one-line cell; unknown kinds keep the raw text. */
function useStructureKindShort() {
  const { language } = useUiLanguage();
  const bt = BOARD_TEXT[language] ?? BOARD_TEXT.zh;
  return (kind: string): string => {
    const normalized = kind.toUpperCase();
    if (normalized === 'BOS') return bt.kindShortBos;
    if (normalized === 'CHOCH') return bt.kindShortChoch;
    return kind;
  };
}

/** Full structure-kind label for the expanded panel; unknown kinds keep the raw text. */
function useStructureKindLabel() {
  const { t } = useUiLanguage();
  return (kind: string): string => {
    const normalized = kind.toUpperCase();
    if (normalized === 'BOS') return t('board.dossier.kind.bos');
    if (normalized === 'CHOCH') return t('board.dossier.kind.choch');
    return kind;
  };
}

/** SMC jargon (SSL / FVG / OB …) → plain words by level.kind; the raw label goes into the tooltip. */
const LevelName: React.FC<{ near: NearLevel }> = ({ near }) => {
  const { language } = useUiLanguage();
  const bt = BOARD_TEXT[language] ?? BOARD_TEXT.zh;
  const { kind, bias, label } = near.level;
  const plain = bt.levelKind[kind];
  if (!plain) return <>{label}</>;
  const prefix = bias === 'bull' ? bt.biasBull : bias === 'bear' ? bt.biasBear : '';
  const sep = language === 'en' ? ' ' : '';
  return (
    <HintTooltip content={label}>
      <span>{prefix ? `${prefix}${sep}${plain}` : plain}</span>
    </HintTooltip>
  );
};

/** 表格內的精簡欄：一行顯示結構方向＋最近支撐／壓力距離（用即時價算）。 */
export const BoardDossierCell: React.FC<{ summary?: DossierSummary | null; price?: number | null }> = ({ summary, price }) => {
  const { t } = useUiLanguage();
  const kindShort = useStructureKindShort();
  if (!summary) return <span className="text-secondary-text">—</span>;
  const s = summary.structure;
  const near = nearFor(summary, price);
  const parts: React.ReactNode[] = [];
  if (s) {
    parts.push(
      <span key="s" className={s.bias === 'bull' ? 'text-red-500' : 'text-emerald-600'}>
        {s.bias === 'bull' ? '▲' : '▼'}{kindShort(s.kind)}
      </span>,
    );
  }
  if (near?.support) parts.push(<span key="sup">{t('board.dossier.support')} {fmtPct(near.support.distPct)}</span>);
  if (near?.resistance) parts.push(<span key="res">{t('board.dossier.resistance')} {fmtPct(near.resistance.distPct)}</span>);
  if (summary.adjustedAfter) parts.push(<span key="adj" className="text-warning">{t('board.dossier.adjustedShort')}</span>);
  return (
    <div className="whitespace-nowrap text-xs leading-5 tabular-nums text-secondary-text" data-testid="board-dossier-cell">
      {parts.map((part, i) => (
        <span key={i}>
          {i > 0 ? ' · ' : null}
          {part}
        </span>
      ))}
    </div>
  );
};

/**
 * 展開列：撐壓與結構摘要、近一日變化、已快取的解讀色調。
 * 傳 onOpenReport 時改成「動作列模式」：頂端右側一排「看報告／四維度／建立警報」，沒有摘要的股票也照樣顯示動作。
 */
export const BoardDossierPanel: React.FC<{
  code: string;
  name?: string | null;
  summary?: DossierSummary | null;
  price?: number | null;
  levelAlertsEnabled?: boolean;
  onOpenReport?: () => void;
  onCreateAlert?: () => void;
}> = ({ code, name, summary, price, levelAlertsEnabled = false, onOpenReport, onCreateAlert }) => {
  const { t, language } = useUiLanguage();
  const bt = BOARD_TEXT[language] ?? BOARD_TEXT.zh;
  const [open, setOpen] = useState(false);
  const [alertNote, setAlertNote] = useState<string | null>(null);
  const [creatingAlerts, setCreatingAlerts] = useState(false); // 送出中鎖住按鈕，避免連點重複建立
  const [confirmingAlerts, setConfirmingAlerts] = useState(false);
  const [alertMenuOpen, setAlertMenuOpen] = useState(false);
  const alertMenuRef = useRef<HTMLDivElement>(null);
  const kindLabel = useStructureKindLabel();

  useEffect(() => {
    if (!alertMenuOpen) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!alertMenuRef.current?.contains(event.target as Node)) setAlertMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAlertMenuOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [alertMenuOpen]);

  const actionMode = Boolean(onOpenReport);
  if (!summary && !actionMode) return null;
  const s = summary?.structure ?? null;
  const near = summary ? nearFor(summary, price) : null;
  const canLevelAlert = Boolean(summary && levelAlertsEnabled && (near?.support || near?.resistance));

  const confirmDialog = (
    <ConfirmDialog
      isOpen={confirmingAlerts}
      title={t('board.dossier.createAlerts')}
      message={t('board.dossier.alertConfirm')}
      onCancel={() => setConfirmingAlerts(false)}
      onConfirm={() => {
        setConfirmingAlerts(false);
        setCreatingAlerts(true);
        stocksApi
          .createLevelAlerts(code, { support: near?.support?.level, resistance: near?.resistance?.level })
          .then((n) => setAlertNote(t('board.dossier.alertCreated', { count: String(n) })))
          .catch((err) => setAlertNote(getParsedApiError(err).message))
          .finally(() => setCreatingAlerts(false));
      }}
    />
  );

  // Two lines: support/resistance numbers (text-sm), then structure and data date (text-xs, muted).
  const summaryLines = summary ? (
    <div className="min-w-0 space-y-0.5" data-testid="board-dossier-summary">
      {near?.support || near?.resistance ? (
        <div className="flex flex-wrap gap-x-3 text-sm tabular-nums text-foreground">
          {near?.support ? (
            <span>
              {t('board.dossier.support')}：<LevelName near={near.support} /> {levelRange(near.support)}（{fmtPct(near.support.distPct)}）
            </span>
          ) : null}
          {near?.resistance ? (
            <span>
              {t('board.dossier.resistance')}：<LevelName near={near.resistance} /> {levelRange(near.resistance)}（{fmtPct(near.resistance.distPct)}）
            </span>
          ) : null}
        </div>
      ) : null}
      <div className="flex flex-wrap gap-x-3 text-xs text-secondary-text">
        {s ? (
          <span>
            {t('board.dossier.structure')}：
            <span className={s.bias === 'bull' ? 'text-red-500' : 'text-emerald-600'}>
              {s.date.slice(5)} {kindLabel(s.kind)} {s.bias === 'bull' ? '▲' : '▼'}（{fmtPrice(s.level)}）
            </span>
          </span>
        ) : null}
        <span>{t('board.dossier.asOf', { date: summary.asOf })}</span>
      </div>
    </div>
  ) : null;

  const chips = summary ? (
    <>
      {summary.verdicts
        ? VERDICT_KEYS.map((k) => {
            const v = summary.verdicts?.[k];
            return v?.badge ? (
              <span key={k} className={cn('rounded-md border px-1.5 py-0.5', TONE_CLASS[v.tone ?? 'watch'])}>
                {t(`board.dossier.verdict.${k}`)}・{v.badge}
              </span>
            ) : null;
          })
        : null}
      {summary.changes.map((c) => (
        <span key={c.kind + c.text} className={cn('rounded-md border px-1.5 py-0.5', TONE_CLASS[c.tone])}>
          {c.text}
        </span>
      ))}
      {!summary.verdicts && summary.changes.length === 0 ? (
        <span className="text-secondary-text">{t('board.dossier.noChanges')}</span>
      ) : null}
    </>
  ) : null;

  const adjustedNote = summary?.adjustedAfter ? (
    <p className="text-xs text-warning" role="note">
      {t('board.dossier.adjusted')}
    </p>
  ) : null;

  if (actionMode) {
    const alertOptions = [
      onCreateAlert ? { key: 'custom', label: bt.customAlert, run: onCreateAlert } : null,
      canLevelAlert ? { key: 'level', label: t('board.dossier.createAlerts'), run: () => setConfirmingAlerts(true) } : null,
    ].filter((o): o is { key: string; label: string; run: () => void } => o !== null);
    const stop = (fn: () => void) => (e: React.MouseEvent) => {
      e.stopPropagation();
      fn();
    };
    let alertControl: React.ReactNode = null;
    if (alertOptions.length === 1) {
      const only = alertOptions[0];
      alertControl = (
        <Button variant="secondary" size="sm" disabled={only.key === 'level' && creatingAlerts} onClick={stop(only.run)}>
          {only.key === 'custom' ? t('board.action.createAlert') : only.label}
        </Button>
      );
    } else if (alertOptions.length > 1) {
      alertControl = (
        <div ref={alertMenuRef} className="relative">
          <Button
            variant="secondary"
            size="sm"
            aria-haspopup="menu"
            aria-expanded={alertMenuOpen}
            onClick={stop(() => setAlertMenuOpen((v) => !v))}
          >
            {t('board.action.createAlert')}
            <ChevronDown aria-hidden="true" className="ml-1 h-3.5 w-3.5" />
          </Button>
          {alertMenuOpen ? (
            <div
              role="menu"
              aria-label={bt.alertMenu}
              className="absolute right-0 top-full z-30 mt-1 min-w-40 rounded-[var(--radius-control)] border border-border/70 bg-card p-1 text-left shadow-soft-card"
            >
              {alertOptions.map((o) => (
                <button
                  key={o.key}
                  type="button"
                  role="menuitem"
                  disabled={o.key === 'level' && creatingAlerts}
                  onClick={stop(() => {
                    setAlertMenuOpen(false);
                    o.run();
                  })}
                  className="flex w-full items-center rounded-[6px] px-2.5 py-2 text-left text-sm text-foreground hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {o.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      );
    }
    return (
      <div className="space-y-2 px-3 py-3 text-xs">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          {summaryLines ?? <div />}
          <div className="ml-auto flex flex-wrap items-center gap-2" data-testid="board-expanded-actions">
            <Button variant="primary" size="sm" onClick={stop(() => onOpenReport?.())}>
              {bt.openReport}
            </Button>
            {summary ? (
              <Button variant="secondary" size="sm" onClick={stop(() => setOpen(true))}>
                {bt.dossierShort}
              </Button>
            ) : null}
            {alertControl}
          </div>
        </div>
        {adjustedNote}
        {chips ? <div className="flex flex-wrap items-center gap-1.5">{chips}</div> : null}
        {alertNote ? <p className="text-secondary-text" role="status">{alertNote}</p> : null}
        {confirmDialog}
        {open ? <StockDossierDrawer stockCode={code} stockName={name} onClose={() => setOpen(false)} /> : null}
      </div>
    );
  }

  return (
    <div className="space-y-2 px-4 py-3 text-xs">
      {summaryLines}
      {adjustedNote}
      <div className="flex flex-wrap items-center gap-1.5">
        {chips}
        {canLevelAlert ? (
          <button
            type="button"
            className="ml-auto rounded-md border border-border px-2 py-0.5 text-secondary-text hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
            disabled={creatingAlerts}
            onClick={() => setConfirmingAlerts(true)}
          >
            {t('board.dossier.createAlerts')}
          </button>
        ) : null}
        <button
          type="button"
          className={cn(
            'rounded-md border border-[hsl(var(--primary))]/40 px-2 py-0.5 text-[hsl(var(--primary))] hover:bg-[hsl(var(--primary))]/10',
            canLevelAlert ? '' : 'ml-auto',
          )}
          onClick={() => setOpen(true)}
        >
          {t('home.dossier')}
        </button>
      </div>
      {alertNote ? <p className="text-secondary-text" role="status">{alertNote}</p> : null}
      {confirmDialog}
      {open ? <StockDossierDrawer stockCode={code} stockName={name} onClose={() => setOpen(false)} /> : null}
    </div>
  );
};
