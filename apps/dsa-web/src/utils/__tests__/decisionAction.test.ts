import { describe, expect, it } from 'vitest';
import {
  type DecisionActionLabelMap,
  getDecisionActionLabel,
  getLegacyDecisionAction,
  getDecisionActionTone,
  getLegacyDecisionActionLabel,
  normalizeDecisionActionAlias,
} from '../decisionAction';

const englishLabels: DecisionActionLabelMap = {
  buy: 'Buy',
  add: 'Add',
  hold: 'Hold',
  reduce: 'Reduce',
  sell: 'Sell',
  watch: 'Watch',
  avoid: 'Avoid',
  alert: 'Alert',
};

describe('decisionAction helpers', () => {
  it('uses structured action taxonomy before server label and legacy advice text', () => {
    expect(getDecisionActionLabel('avoid', '回避', '买入', '建议')).toBe('回避');
    expect(getDecisionActionLabel('sell', '买入', null, 'Advice', englishLabels)).toBe('Sell');
    expect(getDecisionActionTone('sell', '买入', null)).toBe('caution');
    // 存檔的已知動作詞視同枚舉，英文介面也不會露出中文標籤。
    expect(getDecisionActionLabel(null, '买入', null, 'Advice', englishLabels)).toBe('Buy');
    // 未知標籤才保留原文。
    expect(getDecisionActionLabel(null, '分批布局', null, 'Advice', englishLabels)).toBe('分批布局');
  });

  it('falls back to the action taxonomy label when actionLabel is absent', () => {
    expect(getDecisionActionLabel('add', null, '持有', '建议')).toBe('加仓');
    expect(getDecisionActionLabel('watch', null, '持有', 'Advice', englishLabels)).toBe('Watch');
  });

  it('keeps legacy fallback compatible with negated buy advice', () => {
    expect(getLegacyDecisionActionLabel('不建议买入，等待确认')).toBe('回避');
    expect(getDecisionActionLabel(null, null, '避免买入', '建议')).toBe('回避');
    expect(getLegacyDecisionActionLabel('暂不买入，等待确认')).toBe('回避');
    expect(getLegacyDecisionActionLabel('先不建仓，等待放量')).toBe('回避');
    expect(getLegacyDecisionActionLabel('无需买入，等待确认')).toBe('回避');
    expect(getLegacyDecisionActionLabel('无须建仓，继续观察')).toBe('回避');
    expect(getLegacyDecisionActionLabel('无需布局，等待突破')).toBe('回避');
    expect(getLegacyDecisionActionLabel('no buy until breakout')).toBe('回避');
    expect(getLegacyDecisionActionLabel('no need to buy before confirmation')).toBe('回避');
    expect(getLegacyDecisionActionLabel('cannot buy before confirmation')).toBe('回避');
    expect(getLegacyDecisionActionLabel("can't buy before confirmation")).toBe('回避');
    expect(getLegacyDecisionActionLabel('not a buy yet')).toBe('回避');
    expect(getLegacyDecisionActionLabel('not a buy yet', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('not to buy', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('avoid buying', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('avoid buying into weakness', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('waiting to buy')).toBeNull();
  });

  it('keeps legacy fallback compatible with negated sell and add advice', () => {
    expect(getLegacyDecisionActionLabel('不建议卖出，继续观察')).toBe('持有');
    expect(getLegacyDecisionActionLabel('洗盘观察')).toBe('持有');
    expect(getLegacyDecisionActionLabel('洗盘观察', englishLabels)).toBe('Hold');
    expect(getLegacyDecisionActionLabel('无需减仓，维持仓位')).toBe('持有');
    expect(getLegacyDecisionActionLabel('无须减仓，维持仓位')).toBe('持有');
    expect(getLegacyDecisionActionLabel('不建议加仓，等待回踩')).toBe('持有');
    expect(getLegacyDecisionActionLabel('无须加仓，等待回踩')).toBe('持有');
    expect(getLegacyDecisionActionLabel('no add before confirmation')).toBe('持有');
    expect(getLegacyDecisionActionLabel('cannot add before confirmation')).toBe('持有');
    expect(getLegacyDecisionActionLabel('no need to accumulate here')).toBe('持有');
    expect(getLegacyDecisionActionLabel("can't accumulate here")).toBe('持有');
    expect(getLegacyDecisionActionLabel('no sell before earnings')).toBe('持有');
    expect(getLegacyDecisionActionLabel('cannot sell before earnings')).toBe('持有');
    expect(getLegacyDecisionActionLabel('no need to reduce exposure')).toBe('持有');
    expect(getLegacyDecisionActionLabel("can't reduce exposure")).toBe('持有');
    expect(getLegacyDecisionActionLabel('no trim while trend holds')).toBe('持有');
    expect(getLegacyDecisionActionLabel('cannot trim while trend holds')).toBe('持有');
    expect(getLegacyDecisionActionLabel('not a sell yet')).toBe('持有');
    expect(getLegacyDecisionActionLabel('not a trim yet')).toBe('持有');
    expect(getLegacyDecisionActionLabel('not to sell')).toBe('持有');
    expect(getLegacyDecisionActionLabel('not to trim')).toBe('持有');
    expect(getLegacyDecisionActionLabel('not a trim yet', englishLabels)).toBe('Hold');
    expect(getLegacyDecisionActionLabel('avoid selling into weakness', englishLabels)).toBe('Hold');
    expect(getLegacyDecisionActionLabel('avoid trimming before earnings', englishLabels)).toBe('Hold');
    expect(getLegacyDecisionActionLabel('avoid reducing exposure before earnings', englishLabels)).toBe('Hold');
    expect(getDecisionActionTone(null, null, '不建议卖出，继续观察')).toBe('neutral');
  });

  it('does not turn ambiguous English advice into a badge action', () => {
    expect(getLegacyDecisionActionLabel('buy or sell')).toBeNull();
    expect(getDecisionActionLabel(null, null, 'buy or sell', 'Advice', englishLabels)).toBe('Advice');
  });

  it('does not match financial compound words as legacy actions', () => {
    expect(getLegacyDecisionActionLabel('no buyback announced', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('cannot buyback shares now', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('share buy-back announced', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('share buy back announced', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('no selloff risk', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('not selloff yet', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('sell-off risk remains low', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('sell off risk remains low', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('no sell-off pressure', englishLabels)).toBeNull();
    expect(getDecisionActionLabel(null, null, 'no buyback announced', 'Advice', englishLabels)).toBe('Advice');
    expect(getDecisionActionLabel(null, null, 'no selloff risk', 'Advice', englishLabels)).toBe('Advice');
    expect(getLegacyDecisionActionLabel('no buy until breakout', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('cannot buy before confirmation', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('no sell before earnings', englishLabels)).toBe('Hold');
  });

  it('keeps separate action terms next to financial compounds', () => {
    expect(getLegacyDecisionAction('buy after sell-off')).toBe('buy');
    expect(getLegacyDecisionActionLabel('buy after sell-off', englishLabels)).toBe('Buy');
    expect(getLegacyDecisionAction('sell after buy-back rumor')).toBe('sell');
    expect(getLegacyDecisionActionLabel('sell after buy-back rumor', englishLabels)).toBe('Sell');
  });

  it('does not match Chinese financial context words as legacy actions', () => {
    expect(getLegacyDecisionActionLabel('买盘增强，继续观察')).toBeNull();
    expect(getLegacyDecisionActionLabel('卖压缓解，继续观察')).toBeNull();
    expect(getLegacyDecisionActionLabel('卖方评级分歧')).toBeNull();
    expect(getDecisionActionLabel(null, null, '买盘增强，继续观察', '建议')).toBe('建议');
    expect(getDecisionActionLabel(null, null, '卖压缓解，继续观察', '建议')).toBe('建议');
  });

  it('keeps multi-guard legacy advice empty instead of prioritizing avoid or alert', () => {
    expect(getLegacyDecisionActionLabel('risk alert, avoid buying')).toBeNull();
    expect(getLegacyDecisionActionLabel('风险预警，避免买入')).toBeNull();
    expect(getDecisionActionLabel(null, null, 'risk alert, avoid buying', 'Advice', englishLabels)).toBe('Advice');
    expect(getLegacyDecisionActionLabel('avoid buying', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('risk alert', englishLabels)).toBe('Alert');
  });

  it('maps action tone without reading legacy text when action is present', () => {
    expect(getDecisionActionTone('buy', null, '卖出')).toBe('brand');
    expect(getDecisionActionTone('reduce', null, '买入')).toBe('caution');
    expect(getDecisionActionTone('alert', null, '买入')).toBe('caution');
    expect(getDecisionActionTone(null, '观望', '买入')).toBe('neutral');
    expect(getDecisionActionTone(null, 'Sell', '买入')).toBe('caution');
    expect(getDecisionActionTone(null, null, 'avoid buying')).toBe('caution');
  });

  it('認得詞彙表新詞與舊標籤，顯示一律走詞彙表', () => {
    const labels = { reduce: '減碼', buy: '買進', hold: '續抱' };
    // 舊報告存「減倉」、沒有枚舉：畫面仍要顯示「減碼」。
    expect(getDecisionActionLabel(null, '減倉', null, null, labels)).toBe('減碼');
    expect(getDecisionActionLabel(null, '减仓', null, null, labels)).toBe('減碼');
    expect(getDecisionActionLabel('reduce', '減倉', null, null, labels)).toBe('減碼');
    expect(getDecisionActionLabel(null, '買入', null, null, labels)).toBe('買進');
    // 第 2 批 B04 開始存新詞。
    expect(getDecisionActionTone(null, '減碼', null)).toBe('caution');
    expect(getDecisionActionTone(null, '買進', null)).toBe('brand');
    expect(getDecisionActionTone(null, '續抱', null)).toBe('neutral');
    expect(getLegacyDecisionAction('減碼')).toBe('reduce');
    expect(getLegacyDecisionAction('買進')).toBe('buy');
  });

  it('別名只比對整個標籤，不把否定句當成動作', () => {
    expect(getLegacyDecisionAction('不建議買進')).toBeNull();
    expect(getDecisionActionLabel(null, '暫不減碼', null, null, { reduce: '減碼' })).toBe('暫不減碼');
  });
});

describe('normalizeDecisionActionAlias', () => {
  it('把各時期存檔的動作標籤正規化成枚舉', () => {
    expect(['觀望', '观望', '減倉'].map((label) => normalizeDecisionActionAlias(label))).toEqual(['watch', 'watch', 'reduce']);
    expect(normalizeDecisionActionAlias(' 減碼 ')).toBe('reduce');
    expect(normalizeDecisionActionAlias('减仓')).toBe('reduce');
    expect(normalizeDecisionActionAlias('watch')).toBe('watch');
    expect(normalizeDecisionActionAlias('Watch')).toBe('watch');
  });

  it('對不上的原文回 null，不做子字串猜測', () => {
    expect(normalizeDecisionActionAlias('不建議買進')).toBeNull();
    expect(normalizeDecisionActionAlias('逢低买入')).toBeNull();
    expect(normalizeDecisionActionAlias('watching')).toBeNull();
    expect(normalizeDecisionActionAlias('')).toBeNull();
    expect(normalizeDecisionActionAlias(null)).toBeNull();
  });
});
