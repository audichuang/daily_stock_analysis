import { formatUiText, type UiLanguage } from '../../i18n/uiText';
import { ALERT_MARKET_LIGHT_STATUS_LABELS, ALERT_PAGE_TEXT } from '../../locales/featureText';
import type { AlertRuleItem, AlertRuleTargetResult, AlertRuleTestResponse } from '../../types/alerts';

export type AlertPageText = (typeof ALERT_PAGE_TEXT)[UiLanguage];

export function ruleCondition(rule: Pick<AlertRuleItem, 'alertType' | 'parameters' | 'name'>, language: UiLanguage, text: AlertPageText): string {
  const p = rule.parameters;
  switch (rule.alertType) {
    case 'price_cross':
      return `${p.direction === 'below' ? text.below : text.above} ${p.price?.toLocaleString() ?? '--'}`;
    case 'price_change_percent':
      return `${p.direction === 'down' ? text.down : text.up} ${p.changePct ?? '--'}%`;
    case 'volume_spike':
      return `${text.volume} ${p.multiplier ?? '--'} ${text.times}`.trim();
    case 'ma_price_cross':
      return `${p.direction === 'below' ? text.closeBelowMa : text.closeAboveMa} MA${p.window ?? '--'}`;
    case 'rsi_threshold':
      return `RSI${p.period ?? '--'} ${p.direction === 'below' ? text.crossDown : text.crossUp} ${p.threshold ?? '--'}`;
    case 'cci_threshold':
      return `CCI${p.period ?? '--'} ${p.direction === 'below' ? text.crossDown : text.crossUp} ${p.threshold ?? '--'}`;
    case 'macd_cross':
      return `MACD ${p.direction === 'bearish_cross' ? text.bearish : text.bullish}`;
    case 'kdj_cross':
      return `KDJ ${p.direction === 'bearish_cross' ? text.bearish : text.bullish}`;
    case 'portfolio_stop_loss':
      return p.mode === 'breach' ? text.stopBreach : text.stopNear;
    case 'portfolio_concentration':
      return text.concentration;
    case 'portfolio_drawdown':
      return text.drawdown;
    case 'portfolio_price_stale':
      return text.stale;
    case 'market_light_status':
      return `${text.marketStatus} ${(p.statuses ?? []).map((status) => ALERT_MARKET_LIGHT_STATUS_LABELS[language][status] ?? status).join(' / ')}`;
    case 'market_light_score_drop':
      return formatUiText(text.scoreDrop, { value: p.minDrop ?? '--' });
    default:
      return rule.name;
  }
}

export type DryRunOutcome = 'hit' | 'miss' | 'unable' | 'partial' | 'error';

export interface DryRunSummary {
  outcome: DryRunOutcome;
  unableCount: number;
  unableTargets: AlertRuleTargetResult[];
}

function isUnableTarget(item: AlertRuleTargetResult): boolean {
  return item.status === 'evaluation_error'
    || item.recordStatus === 'skipped'
    || item.recordStatus === 'degraded'
    || item.recordStatus === 'failed';
}

/** status=not_triggered 也可能是沒報價：略過與降級的標的沒有被評估，不能說成條件未達成。 */
export function summarizeDryRun(result: AlertRuleTestResponse): DryRunSummary {
  const unableTargets = (result.targetResults ?? []).filter(isUnableTarget);
  // targetResults 有筆數上限，計數欄位才是全量；failed 沒有獨立計數，只能從明細數。
  const unableCount = Math.max(unableTargets.length, (result.skippedCount ?? 0) + (result.degradedCount ?? 0));
  if (result.status === 'evaluation_error') return { outcome: 'error', unableCount, unableTargets };
  if (result.triggered) return { outcome: 'hit', unableCount, unableTargets };
  if (unableCount === 0) return { outcome: 'miss', unableCount, unableTargets };
  const allUnable = unableCount >= Math.max(result.evaluatedCount ?? 1, 1);
  return { outcome: allUnable ? 'unable' : 'partial', unableCount, unableTargets };
}
