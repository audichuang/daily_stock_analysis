import type React from 'react';
import { useState } from 'react';
import { stocksApi, type DossierSummary, type DossierTone } from '../../api/stocks';
import { getParsedApiError } from '../../api/error';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { cn } from '../../utils/cn';
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

/** 表格內的精簡欄：最新結構方向＋最近支撐／壓力距離（用即時價算）。 */
export const BoardDossierCell: React.FC<{ summary?: DossierSummary | null; price?: number | null }> = ({ summary, price }) => {
  const { t } = useUiLanguage();
  if (!summary) return <span className="text-secondary-text">—</span>;
  const s = summary.structure;
  const ref = price ?? summary.close;
  const near = ref ? nearestLevels(summary.levels, ref) : null;
  return (
    <div className="whitespace-nowrap text-xs leading-5">
      {s ? (
        <span className={s.bias === 'bull' ? 'text-red-500' : 'text-emerald-600'}>
          {s.bias === 'bull' ? '▲' : '▼'} {s.kind}
        </span>
      ) : null}
      {near?.support ? (
        <div className="tabular-nums text-secondary-text">
          {t('board.dossier.support')} {fmtPct(near.support.distPct)}
        </div>
      ) : null}
      {near?.resistance ? (
        <div className="tabular-nums text-secondary-text">
          {t('board.dossier.resistance')} {fmtPct(near.resistance.distPct)}
        </div>
      ) : null}
    </div>
  );
};

/** 展開列：完整的結構、支撐壓力、近一日變化、已快取的解讀色調，以及開完整報告的按鈕。 */
export const BoardDossierPanel: React.FC<{
  code: string;
  name?: string | null;
  summary?: DossierSummary | null;
  price?: number | null;
  levelAlertsEnabled?: boolean;
}> = ({ code, name, summary, price, levelAlertsEnabled = false }) => {
  const { t } = useUiLanguage();
  const [open, setOpen] = useState(false);
  const [alertNote, setAlertNote] = useState<string | null>(null);
  const [creatingAlerts, setCreatingAlerts] = useState(false); // 送出中鎖住按鈕，避免連點重複建立
  if (!summary) return null;
  const s = summary.structure;
  const ref = price ?? summary.close;
  const near = ref ? nearestLevels(summary.levels, ref) : null;
  return (
    <div className="space-y-2 px-4 py-3 text-xs">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="font-medium text-foreground">{t('board.dossier.title')}</span>
        <span className="text-secondary-text">{t('board.dossier.asOf', { date: summary.asOf })}</span>
        {s ? (
          <span>
            {t('board.dossier.structure')}：
            <span className={s.bias === 'bull' ? 'text-red-500' : 'text-emerald-600'}>
              {s.date.slice(5)} {s.kind} {s.bias === 'bull' ? '▲' : '▼'}（{fmtPrice(s.level)}）
            </span>
          </span>
        ) : null}
        {near?.support ? (
          <span className="tabular-nums">
            {t('board.dossier.support')}：{near.support.level.label} {levelRange(near.support)}（{fmtPct(near.support.distPct)}）
          </span>
        ) : null}
        {near?.resistance ? (
          <span className="tabular-nums">
            {t('board.dossier.resistance')}：{near.resistance.level.label} {levelRange(near.resistance)}（{fmtPct(near.resistance.distPct)}）
          </span>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
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
        {levelAlertsEnabled && (near?.support || near?.resistance) ? (
          <button
            type="button"
            className="ml-auto rounded-md border border-border px-2 py-0.5 text-secondary-text hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
            disabled={creatingAlerts}
            onClick={() => {
              if (!window.confirm(t('board.dossier.alertConfirm'))) return;
              setCreatingAlerts(true);
              stocksApi
                .createLevelAlerts(code, { support: near?.support?.level, resistance: near?.resistance?.level })
                .then((n) => setAlertNote(t('board.dossier.alertCreated', { count: String(n) })))
                .catch((err) => setAlertNote(getParsedApiError(err).message))
                .finally(() => setCreatingAlerts(false));
            }}
          >
            {t('board.dossier.createAlerts')}
          </button>
        ) : null}
        <button
          type="button"
          className={cn(
            'rounded-md border border-[hsl(var(--primary))]/40 px-2 py-0.5 text-[hsl(var(--primary))] hover:bg-[hsl(var(--primary))]/10',
            levelAlertsEnabled && (near?.support || near?.resistance) ? '' : 'ml-auto',
          )}
          onClick={() => setOpen(true)}
        >
          {t('home.dossier')}
        </button>
      </div>
      {alertNote ? <p className="text-secondary-text" role="status">{alertNote}</p> : null}
      {open ? <StockDossierDrawer stockCode={code} stockName={name} onClose={() => setOpen(false)} /> : null}
    </div>
  );
};
