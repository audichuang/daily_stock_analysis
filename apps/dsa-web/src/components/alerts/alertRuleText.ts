import { formatUiText, type UiLanguage } from '../../i18n/uiText';
import { ALERT_MARKET_LIGHT_STATUS_LABELS, ALERT_PAGE_TEXT } from '../../locales/featureText';
import type { AlertRuleItem } from '../../types/alerts';

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
