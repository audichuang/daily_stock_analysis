import type { BacktestPhaseFilter } from '../types/backtest';
import type { AlertTargetScope, AlertType, MarketLightStatus, MarketRegion, PortfolioStopLossMode } from '../types/alerts';
import type { PortfolioCashDirection, PortfolioCorporateActionType, PortfolioSide } from '../types/portfolio';
import type { UiLanguage } from '../i18n/uiText';

type Option<T extends string = string> = { value: T; label: string };
const alertTypes: AlertType[] = ['price_cross', 'price_change_percent', 'volume_spike', 'ma_price_cross', 'rsi_threshold', 'macd_cross', 'kdj_cross', 'cci_threshold', 'portfolio_stop_loss', 'portfolio_concentration', 'portfolio_drawdown', 'portfolio_price_stale', 'market_light_status', 'market_light_score_drop'];
const symbolAlertTypes = alertTypes.slice(0, 8);
const portfolioAlertTypes = alertTypes.slice(8, 12);
const marketAlertTypes = alertTypes.slice(12);

export const BACKTEST_TEXT = {
  zh: { documentTitle: '策略回测 - DSA', codePlaceholder: '按股票代码筛选（留空表示全部）', filter: '筛选', evalWindow: '评估窗口', phase: '阶段', startDate: '开始日期', startDateAria: '分析开始日期', endDate: '结束日期', endDateAria: '分析结束日期', oneDayValidation: '1 日验证', forceRerun: '强制重跑', running: '回测中...', runBacktest: '运行回测', oneDayModeDescription: '1 日验证模式会用下一个可进场交易日的开盘至收盘收益校验 AI 预测，不含隔夜跳空。', windowModeDescription: '将评估窗口设为 1，可比较 AI 预测与下一个可进场交易日的开盘至收盘收益，不含隔夜跳空。', overallPerformance: '整体表现', noMetricsTitle: '暂无指标', noMetricsDescription: '运行回测后会生成组合级表现指标。', loadingResults: '正在加载结果...', noResultsTitle: '暂无结果', noResultsDescription: '运行回测后可评估历史分析准确性。', nextDayValidation: '次日验证', resultSet: '结果集', allStocks: '全部股票', filteredStock: '筛选 {code}', dayWindow: '{days} 日窗口', fromDate: '自 {date}', toDate: '至 {date}', scrollHint: '小屏幕可横向滚动', stock: '股票', analysisDate: '分析日期', aiPrediction: 'AI 预测', actualPerformance: '实际表现', windowReturn: '窗口收益', accuracy: '准确性', directionMatch: '方向匹配', result: '结果', status: '状态', totalPage: '共 {total} 条结果 · 第 {page} / {pages} 页', directionAccuracy: '方向准确率', winRate: '胜率', avgSimulatedReturn: '平均模拟收益', avgStockReturn: '平均个股收益', stopLossTriggerRate: '止损触发率', takeProfitTriggerRate: '止盈触发率', avgDaysToFirstHit: '平均命中天数', evaluationCount: '评估数', outcomeSummary: '盈 / 亏 / 中', phaseDistribution: '阶段分布：{text}', processed: '已处理:', saved: '已保存:', completed: '已完成:', insufficient: '数据不足:', errors: '错误:', yes: '是', no: '否', unknown: '未知' },
  en: { documentTitle: 'Strategy Backtest - DSA', codePlaceholder: 'Filter by stock code (leave empty for all)', filter: 'Filter', evalWindow: 'Evaluation window', phase: 'Phase', startDate: 'Start date', startDateAria: 'Analysis start date', endDate: 'End date', endDateAria: 'Analysis end date', oneDayValidation: '1D validation', forceRerun: 'Force rerun', running: 'Backtesting...', runBacktest: 'Run backtest', oneDayModeDescription: '1D validation checks AI predictions against the open-to-close return of the next eligible trading day, excluding the overnight gap.', windowModeDescription: 'Set the evaluation window to 1 to compare AI predictions with the open-to-close return of the next eligible trading day, excluding the overnight gap.', overallPerformance: 'Overall performance', noMetricsTitle: 'No metrics', noMetricsDescription: 'Portfolio-level performance metrics appear after a backtest runs.', loadingResults: 'Loading results...', noResultsTitle: 'No results', noResultsDescription: 'Run a backtest to evaluate historical analysis accuracy.', nextDayValidation: 'Next-day validation', resultSet: 'Result set', allStocks: 'All stocks', filteredStock: 'Filtered {code}', dayWindow: '{days}-day window', fromDate: 'from {date}', toDate: 'to {date}', scrollHint: 'Scroll horizontally on small screens', stock: 'Stock', analysisDate: 'Analysis date', aiPrediction: 'AI prediction', actualPerformance: 'Actual performance', windowReturn: 'Window return', accuracy: 'Accuracy', directionMatch: 'Direction match', result: 'Result', status: 'Status', totalPage: '{total} results · Page {page} / {pages}', directionAccuracy: 'Direction accuracy', winRate: 'Win rate', avgSimulatedReturn: 'Avg simulated return', avgStockReturn: 'Avg stock return', stopLossTriggerRate: 'Stop-loss trigger rate', takeProfitTriggerRate: 'Take-profit trigger rate', avgDaysToFirstHit: 'Avg days to first hit', evaluationCount: 'Evaluations', outcomeSummary: 'Win / Loss / Neutral', phaseDistribution: 'Phase breakdown: {text}', processed: 'Processed:', saved: 'Saved:', completed: 'Completed:', insufficient: 'Insufficient:', errors: 'Errors:', yes: 'Yes', no: 'No', unknown: 'Unknown' },
  'zh-TW': { documentTitle: '策略回測 - DSA', codePlaceholder: '依股票代號篩選（留空表示全部）', filter: '篩選', evalWindow: '評估天數', phase: '階段', startDate: '開始日期', startDateAria: '分析開始日期', endDate: '結束日期', endDateAria: '分析結束日期', oneDayValidation: '1 日驗證', forceRerun: '強制重跑', running: '回測中...', runBacktest: '執行回測', oneDayModeDescription: '1 日驗證模式會用下一個可進場交易日的開盤至收盤報酬檢驗 AI 預測，不含隔夜跳空。', windowModeDescription: '將評估天數設為 1，可比較 AI 預測與下一個可進場交易日的開盤至收盤報酬，不含隔夜跳空。', overallPerformance: '整體表現', noMetricsTitle: '暫無指標', noMetricsDescription: '執行回測後會產生組合級表現指標。', loadingResults: '正在載入結果...', noResultsTitle: '暫無結果', noResultsDescription: '按「重新計算」評估歷史分析準不準。', nextDayValidation: '次日驗證', resultSet: '結果集', allStocks: '全部股票', filteredStock: '篩選 {code}', dayWindow: '{days} 日', fromDate: '自 {date}', toDate: '至 {date}', scrollHint: '小螢幕可橫向捲動', stock: '股票', analysisDate: '分析日期', aiPrediction: 'AI 預測', actualPerformance: '實際表現', windowReturn: '區間報酬', accuracy: '準確性', directionMatch: '方向對錯', result: '結果', status: '狀態', totalPage: '共 {total} 筆結果・第 {page} / {pages} 頁', directionAccuracy: '方向準確率', winRate: '勝率', avgSimulatedReturn: '平均模擬報酬', avgStockReturn: '同期個股平均', stopLossTriggerRate: '停損觸發率', takeProfitTriggerRate: '停利觸發率', avgDaysToFirstHit: '平均命中天數', evaluationCount: '評估數', outcomeSummary: '勝／負／平', phaseDistribution: '階段分布：{text}', processed: '已處理：', saved: '已儲存：', completed: '已完成：', insufficient: '資料不足：', errors: '錯誤：', yes: '是', no: '否', unknown: '未知' },
} as const;

export const BACKTEST_PHASE_FILTER_OPTIONS: Record<UiLanguage, Array<Option<BacktestPhaseFilter>>> = {
  zh: [{ value: 'all', label: '全部阶段' }, { value: 'premarket', label: '盘前' }, { value: 'intraday', label: '盘中' }, { value: 'postmarket', label: '盘后' }, { value: 'unknown', label: '未知' }],
  en: [{ value: 'all', label: 'All phases' }, { value: 'premarket', label: 'Pre-market' }, { value: 'intraday', label: 'Intraday' }, { value: 'postmarket', label: 'Post-market' }, { value: 'unknown', label: 'Unknown' }],
  'zh-TW': [{ value: 'all', label: '全部階段' }, { value: 'premarket', label: '盤前' }, { value: 'intraday', label: '盤中' }, { value: 'postmarket', label: '盤後' }, { value: 'unknown', label: '未知' }],
};
export const BACKTEST_PHASE_LABELS: Record<UiLanguage, Record<string, string>> = { zh: { premarket: '盘前', intraday: '盘中', postmarket: '盘后', unknown: '未知' }, en: { premarket: 'Pre-market', intraday: 'Intraday', postmarket: 'Post-market', unknown: 'Unknown' }, 'zh-TW': { premarket: '盤前', intraday: '盤中', postmarket: '盤後', unknown: '未知' } };
export const BACKTEST_OUTCOME_LABELS: Record<UiLanguage, Record<string, string>> = { zh: { win: '盈利', loss: '亏损', neutral: '中性' }, en: { win: 'Win', loss: 'Loss', neutral: 'Neutral' }, 'zh-TW': { win: '獲利', loss: '虧損', neutral: '中性' } };
export const BACKTEST_STATUS_LABELS: Record<UiLanguage, Record<string, string>> = { zh: { completed: '已完成', insufficient: '数据不足', insufficient_data: '数据不足', pending: '未到期', unable: '无法评估', error: '错误' }, en: { completed: 'Completed', insufficient: 'Insufficient data', insufficient_data: 'Insufficient data', pending: 'Not matured', unable: 'Unable', error: 'Error' }, 'zh-TW': { completed: '已完成', insufficient: '資料不足', insufficient_data: '資料不足', pending: '未到期', unable: '無法評估', error: '錯誤' } };
export const BACKTEST_MOVEMENT_LABELS: Record<UiLanguage, Record<string, string>> = { zh: { up: '上涨', down: '下跌', flat: '持平' }, en: { up: 'Up', down: 'Down', flat: 'Flat' }, 'zh-TW': { up: '上漲', down: '下跌', flat: '持平' } };
export const BACKTEST_DIRECTION_EXPECTED_LABELS: Record<UiLanguage, Record<string, string>> = { zh: { long: '做多', cash: '空仓', up: '看涨', down: '看跌', not_down: '不看跌', flat: '持平' }, en: { long: 'Long', cash: 'Cash', up: 'Bullish', down: 'Bearish', not_down: 'Not bearish', flat: 'Flat' }, 'zh-TW': { long: '做多', cash: '空手', up: '看漲', down: '看跌', not_down: '不看跌', flat: '持平' } };

export const ALERT_TYPE_LABELS: Record<UiLanguage, Record<AlertType, string>> = {
  zh: { price_cross: '价格突破', price_change_percent: '涨跌幅', volume_spike: '成交量放大', ma_price_cross: '价格均线穿越', rsi_threshold: 'RSI 阈值', macd_cross: 'MACD 金叉/死叉', kdj_cross: 'KDJ 金叉/死叉', cci_threshold: 'CCI 阈值', portfolio_stop_loss: '组合止损', portfolio_concentration: '组合集中度', portfolio_drawdown: '组合回撤', portfolio_price_stale: '组合价格状态', market_light_status: '大盘红绿灯状态', market_light_score_drop: '大盘红绿灯分数下降' },
  en: { price_cross: 'Price crossing', price_change_percent: 'Price change', volume_spike: 'Volume spike', ma_price_cross: 'Price/MA crossing', rsi_threshold: 'RSI threshold', macd_cross: 'MACD cross', kdj_cross: 'KDJ cross', cci_threshold: 'CCI threshold', portfolio_stop_loss: 'Portfolio stop loss', portfolio_concentration: 'Portfolio concentration', portfolio_drawdown: 'Portfolio drawdown', portfolio_price_stale: 'Portfolio price status', market_light_status: 'Market traffic light status', market_light_score_drop: 'Market traffic light score drop' },
  'zh-TW': { price_cross: '價格突破', price_change_percent: '漲跌幅', volume_spike: '成交量放大', ma_price_cross: '價格均線穿越', rsi_threshold: 'RSI 閾值', macd_cross: 'MACD 金叉／死叉', kdj_cross: 'KDJ 金叉／死叉', cci_threshold: 'CCI 閾值', portfolio_stop_loss: '組合停損', portfolio_concentration: '組合集中度', portfolio_drawdown: '組合回撤', portfolio_price_stale: '組合價格狀態', market_light_status: '大盤紅綠燈狀態', market_light_score_drop: '大盤紅綠燈分數下降' },
};
export const ALERT_SEVERITY_LABELS: Record<UiLanguage, Record<string, string>> = { zh: { info: '提示', warning: '警告', critical: '严重' }, en: { info: 'Info', warning: 'Warning', critical: 'Critical' }, 'zh-TW': { info: '提示', warning: '警告', critical: '嚴重' } };
export const ALERT_SCOPE_LABELS: Record<UiLanguage, Record<AlertTargetScope, string>> = { zh: { single_symbol: '单标的', watchlist: '自选股', portfolio_holdings: '持仓标的', portfolio_account: '持仓账户', market: '大盘市场' }, en: { single_symbol: 'Single symbol', watchlist: 'Watchlist', portfolio_holdings: 'Portfolio holdings', portfolio_account: 'Portfolio account', market: 'Market' }, 'zh-TW': { single_symbol: '單標的', watchlist: '自選股', portfolio_holdings: '持股標的', portfolio_account: '持股帳戶', market: '大盤市場' } };
export const ALERT_MARKET_REGION_LABELS: Record<UiLanguage, Record<MarketRegion, string>> = { zh: { cn: 'A 股', hk: '港股', us: '美股', tw: '台股' }, en: { cn: 'A-shares', hk: 'Hong Kong', us: 'US', tw: 'Taiwan' }, 'zh-TW': { cn: 'A 股', hk: '港股', us: '美股', tw: '台股' } };
export const ALERT_MARKET_LIGHT_STATUS_LABELS: Record<UiLanguage, Record<MarketLightStatus, string>> = { zh: { yellow: '黄灯', red: '红灯' }, en: { yellow: 'Yellow', red: 'Red' }, 'zh-TW': { yellow: '黃燈', red: '紅燈' } };
export const ALERT_DIRECTION_LABELS = {
  zh: { abovePrice: '上破', belowPrice: '下破', upChange: '上涨', downChange: '下跌', aboveThreshold: '上穿', belowThreshold: '下穿', bullishCross: '金叉', bearishCross: '死叉', stopLossNear: '接近止损', stopLossBreach: '已触发止损' },
  en: { abovePrice: 'above', belowPrice: 'below', upChange: 'up', downChange: 'down', aboveThreshold: 'above', belowThreshold: 'below', bullishCross: 'bullish cross', bearishCross: 'bearish cross', stopLossNear: 'Near stop loss', stopLossBreach: 'Stop loss breached' },
  'zh-TW': { abovePrice: '上破', belowPrice: '下破', upChange: '上漲', downChange: '下跌', aboveThreshold: '上穿', belowThreshold: '下穿', bullishCross: '金叉', bearishCross: '死叉', stopLossNear: '接近停損', stopLossBreach: '已觸發停損' },
} as const;
export const ALERT_LIST_TEXT = {
  zh: { title: '告警规则', subtitle: '{total} 条规则', enabledFilter: '启停状态', alertTypeFilter: '规则类型', loadingRules: '正在加载规则', emptyTitle: '暂无告警规则', emptyDescription: '创建规则后，后台评估任务会按轮询周期处理已启用的告警。', rule: '规则', target: '目标', type: '类型', parameters: '参数', status: '状态', cooldown: '冷却', updatedAt: '更新时间', action: '操作', source: '来源：{source}', allAccounts: '全部账户', accountTarget: '账户 {target}', enabled: '已启用', disabled: '已停用', coolingDown: '冷却中', notCoolingDown: '未冷却', childTargetCooldown: '子目标见触发历史', test: '测试', testing: '测试中', disabling: '停用中', enabling: '启用中', disable: '停用', enable: '启用', delete: '删除', cancel: '取消', scoreDropAtLeast: 'Score 下降 >= {value}', deleteAria: '删除 {name}', deleteTitle: '删除告警规则', deleteMessage: '确认删除「{name}」吗？该操作不会删除已有触发历史。' },
  en: { title: 'Alert rules', subtitle: '{total} rules', enabledFilter: 'Status', alertTypeFilter: 'Rule type', loadingRules: 'Loading rules', emptyTitle: 'No alert rules', emptyDescription: 'After rules are created, background evaluation processes enabled alerts on the polling schedule.', rule: 'Rule', target: 'Target', type: 'Type', parameters: 'Parameters', status: 'Status', cooldown: 'Cooldown', updatedAt: 'Updated', action: 'Actions', source: 'Source: {source}', allAccounts: 'All accounts', accountTarget: 'Account {target}', enabled: 'Enabled', disabled: 'Disabled', coolingDown: 'Cooling down', notCoolingDown: 'Not cooling down', childTargetCooldown: 'Per-target cooldowns are in trigger history', test: 'Test', testing: 'Testing', disabling: 'Disabling', enabling: 'Enabling', disable: 'Disable', enable: 'Enable', delete: 'Delete', cancel: 'Cancel', scoreDropAtLeast: 'Score drop >= {value}', deleteAria: 'Delete {name}', deleteTitle: 'Delete alert rule', deleteMessage: 'Delete "{name}"? Existing trigger history will be kept.' },
  'zh-TW': { title: '警報規則', subtitle: '{total} 條規則', enabledFilter: '啟停狀態', alertTypeFilter: '規則類型', loadingRules: '正在載入規則', emptyTitle: '暫無警報規則', emptyDescription: '建立規則後，後台評估任務會依輪詢週期處理已啟用的警報。', rule: '規則', target: '目標', type: '類型', parameters: '參數', status: '狀態', cooldown: '冷卻', updatedAt: '更新時間', action: '操作', source: '來源：{source}', allAccounts: '全部帳戶', accountTarget: '帳戶 {target}', enabled: '已啟用', disabled: '已停用', coolingDown: '冷卻中', notCoolingDown: '未冷卻', childTargetCooldown: '子目標請見觸發歷史', test: '測試', testing: '測試中', disabling: '停用中', enabling: '啟用中', disable: '停用', enable: '啟用', delete: '刪除', cancel: '取消', scoreDropAtLeast: 'Score 下降 >= {value}', deleteAria: '刪除 {name}', deleteTitle: '刪除警報規則', deleteMessage: '確認刪除「{name}」嗎？此操作不會刪除已有觸發歷史。' },
} as const;
export const ALERT_ENABLED_FILTER_OPTIONS: Record<UiLanguage, Array<Option<'all' | 'enabled' | 'disabled'>>> = { zh: [{ value: 'all', label: '全部状态' }, { value: 'enabled', label: '已启用' }, { value: 'disabled', label: '已停用' }], en: [{ value: 'all', label: 'All statuses' }, { value: 'enabled', label: 'Enabled' }, { value: 'disabled', label: 'Disabled' }], 'zh-TW': [{ value: 'all', label: '全部狀態' }, { value: 'enabled', label: '已啟用' }, { value: 'disabled', label: '已停用' }] };
export const ALERT_TYPE_FILTER_OPTIONS: Record<UiLanguage, Array<Option<'all' | AlertType>>> = { zh: [{ value: 'all', label: '全部类型' }, ...alertTypes.map((value) => ({ value, label: ALERT_TYPE_LABELS.zh[value] }))], en: [{ value: 'all', label: 'All types' }, ...alertTypes.map((value) => ({ value, label: ALERT_TYPE_LABELS.en[value] }))], 'zh-TW': [{ value: 'all', label: '全部類型' }, ...alertTypes.map((value) => ({ value, label: ALERT_TYPE_LABELS['zh-TW'][value] }))] };
export const ALERT_FORM_TEXT = {
  zh: { accountLoadFailed: '账户加载失败', allAccounts: '全部账户', cardTitle: '创建告警规则', cardSubtitle: 'Web 告警中心', ruleName: '规则名称', ruleNamePlaceholder: '可选，例如 茅台价格突破', targetScope: '目标范围', targetCode: '标的代码', target: '目标', marketRegion: '市场区域', account: '账户', ruleType: '规则类型', severity: '严重级别', direction: '方向', priceThreshold: '价格阈值', changePctThreshold: '涨跌幅阈值（%）', volumeMultiplier: '成交量放大倍数', crossDirection: '交叉方向', thresholdDirection: '阈值方向', maDirection: '穿越方向', maWindow: '均线周期', rsiPeriod: 'RSI 周期', rsiThreshold: 'RSI 阈值', fastPeriod: '快线周期', slowPeriod: '慢线周期', signalPeriod: '信号周期', kdjPeriod: 'KDJ 周期', kPeriod: 'K 平滑周期', dPeriod: 'D 平滑周期', cciPeriod: 'CCI 周期', cciThreshold: 'CCI 阈值', stopLossMode: '止损模式', triggerStatus: '触发状态', scoreDropThreshold: 'Score 下降阈值', enableAfterCreate: '创建后立即启用', creating: '创建中...', create: '创建规则', positiveNumber: '{label}必须是大于 0 的数字', integerRange: '{label}必须是 {min} 到 {max} 的整数', required: '{label}不能为空', finiteNumber: '{label}必须是有效数字', rsiRange: 'RSI 阈值必须在 0 到 100 之间', requiredBarsLimit: '{label} 周期组合需要 {requiredBars} 根日线，最多支持 {max} 根', fastLessThanSlow: '快线周期必须小于慢线周期', noMarketStatus: '至少选择一个红绿灯状态', invalidStockCode: '股票代码格式不正确' },
  en: { accountLoadFailed: 'Account loading failed', allAccounts: 'All accounts', cardTitle: 'Create alert rule', cardSubtitle: 'Web alert center', ruleName: 'Rule name', ruleNamePlaceholder: 'Optional, e.g. Moutai price crossing', targetScope: 'Target scope', targetCode: 'Symbol', target: 'Target', marketRegion: 'Market region', account: 'Account', ruleType: 'Rule type', severity: 'Severity', direction: 'Direction', priceThreshold: 'Price threshold', changePctThreshold: 'Change threshold (%)', volumeMultiplier: 'Volume multiplier', crossDirection: 'Cross direction', thresholdDirection: 'Threshold direction', maDirection: 'Cross direction', maWindow: 'MA window', rsiPeriod: 'RSI period', rsiThreshold: 'RSI threshold', fastPeriod: 'Fast period', slowPeriod: 'Slow period', signalPeriod: 'Signal period', kdjPeriod: 'KDJ period', kPeriod: 'K smoothing period', dPeriod: 'D smoothing period', cciPeriod: 'CCI period', cciThreshold: 'CCI threshold', stopLossMode: 'Stop-loss mode', triggerStatus: 'Trigger status', scoreDropThreshold: 'Score drop threshold', enableAfterCreate: 'Enable immediately', creating: 'Creating...', create: 'Create rule', positiveNumber: '{label} must be a number greater than 0', integerRange: '{label} must be an integer from {min} to {max}', required: '{label} is required', finiteNumber: '{label} must be a valid number', rsiRange: 'RSI threshold must be between 0 and 100', requiredBarsLimit: '{label} requires {requiredBars} daily bars, up to {max} are supported', fastLessThanSlow: 'Fast period must be less than slow period', noMarketStatus: 'Select at least one traffic light status', invalidStockCode: 'Invalid stock code format' },
  'zh-TW': { accountLoadFailed: '帳戶載入失敗', allAccounts: '全部帳戶', cardTitle: '建立警報規則', cardSubtitle: '警報中心', ruleName: '規則名稱', ruleNamePlaceholder: '選填，例如 台積電價格突破', targetScope: '目標範圍', targetCode: '標的代號', target: '目標', marketRegion: '市場區域', account: '帳戶', ruleType: '規則類型', severity: '嚴重級別', direction: '方向', priceThreshold: '價格閾值', changePctThreshold: '漲跌幅閾值（%）', volumeMultiplier: '成交量放大倍數', crossDirection: '交叉方向', thresholdDirection: '閾值方向', maDirection: '穿越方向', maWindow: '均線週期', rsiPeriod: 'RSI 週期', rsiThreshold: 'RSI 閾值', fastPeriod: '快線週期', slowPeriod: '慢線週期', signalPeriod: '訊號週期', kdjPeriod: 'KDJ 週期', kPeriod: 'K 平滑週期', dPeriod: 'D 平滑週期', cciPeriod: 'CCI 週期', cciThreshold: 'CCI 閾值', stopLossMode: '停損模式', triggerStatus: '觸發狀態', scoreDropThreshold: '大盤分數下降門檻', enableAfterCreate: '建立後立即啟用', creating: '建立中...', create: '建立規則', positiveNumber: '{label}必須是大於 0 的數字', integerRange: '{label}必須是 {min} 到 {max} 的整數', required: '{label}不能為空', finiteNumber: '{label}必須是有效數字', rsiRange: 'RSI 閾值必須在 0 到 100 之間', requiredBarsLimit: '{label} 週期組合需要 {requiredBars} 根日線，最多支援 {max} 根', fastLessThanSlow: '快線週期必須小於慢線週期', noMarketStatus: '至少選擇一個紅綠燈狀態', invalidStockCode: '股票代號格式不正確' },
} as const;
export const ALERT_SYMBOL_TYPE_OPTIONS: Record<UiLanguage, Array<Option<AlertType>>> = { zh: symbolAlertTypes.map((value) => ({ value, label: ALERT_TYPE_LABELS.zh[value] })), en: symbolAlertTypes.map((value) => ({ value, label: ALERT_TYPE_LABELS.en[value] })), 'zh-TW': symbolAlertTypes.map((value) => ({ value, label: ALERT_TYPE_LABELS['zh-TW'][value] })) };
export const ALERT_PORTFOLIO_TYPE_OPTIONS: Record<UiLanguage, Array<Option<AlertType>>> = { zh: portfolioAlertTypes.map((value) => ({ value, label: ALERT_TYPE_LABELS.zh[value] })), en: portfolioAlertTypes.map((value) => ({ value, label: ALERT_TYPE_LABELS.en[value] })), 'zh-TW': portfolioAlertTypes.map((value) => ({ value, label: ALERT_TYPE_LABELS['zh-TW'][value] })) };
export const ALERT_MARKET_TYPE_OPTIONS: Record<UiLanguage, Array<Option<AlertType>>> = { zh: marketAlertTypes.map((value) => ({ value, label: ALERT_TYPE_LABELS.zh[value] })), en: marketAlertTypes.map((value) => ({ value, label: ALERT_TYPE_LABELS.en[value] })), 'zh-TW': marketAlertTypes.map((value) => ({ value, label: ALERT_TYPE_LABELS['zh-TW'][value] })) };
export const ALERT_TARGET_SCOPE_OPTIONS: Record<UiLanguage, Array<Option<AlertTargetScope>>> = { zh: Object.entries(ALERT_SCOPE_LABELS.zh).map(([value, label]) => ({ value: value as AlertTargetScope, label })), en: Object.entries(ALERT_SCOPE_LABELS.en).map(([value, label]) => ({ value: value as AlertTargetScope, label })), 'zh-TW': Object.entries(ALERT_SCOPE_LABELS['zh-TW']).map(([value, label]) => ({ value: value as AlertTargetScope, label })) };
export const ALERT_SEVERITY_OPTIONS: Record<UiLanguage, Array<Option<'info' | 'warning' | 'critical'>>> = { zh: Object.entries(ALERT_SEVERITY_LABELS.zh).map(([value, label]) => ({ value: value as 'info' | 'warning' | 'critical', label })), en: Object.entries(ALERT_SEVERITY_LABELS.en).map(([value, label]) => ({ value: value as 'info' | 'warning' | 'critical', label })), 'zh-TW': Object.entries(ALERT_SEVERITY_LABELS['zh-TW']).map(([value, label]) => ({ value: value as 'info' | 'warning' | 'critical', label })) };
export const ALERT_PRICE_DIRECTION_OPTIONS: Record<UiLanguage, Array<Option<'above' | 'below'>>> = { zh: [{ value: 'above', label: '上破' }, { value: 'below', label: '下破' }], en: [{ value: 'above', label: 'Crosses above' }, { value: 'below', label: 'Crosses below' }], 'zh-TW': [{ value: 'above', label: '上破' }, { value: 'below', label: '下破' }] };
export const ALERT_CHANGE_DIRECTION_OPTIONS: Record<UiLanguage, Array<Option<'up' | 'down'>>> = { zh: [{ value: 'up', label: '上涨达到' }, { value: 'down', label: '下跌达到' }], en: [{ value: 'up', label: 'Rises by' }, { value: 'down', label: 'Falls by' }], 'zh-TW': [{ value: 'up', label: '上漲達到' }, { value: 'down', label: '下跌達到' }] };
export const ALERT_THRESHOLD_DIRECTION_OPTIONS: Record<UiLanguage, Array<Option<'above' | 'below'>>> = { zh: [{ value: 'above', label: '上穿' }, { value: 'below', label: '下穿' }], en: [{ value: 'above', label: 'Crosses above' }, { value: 'below', label: 'Crosses below' }], 'zh-TW': [{ value: 'above', label: '上穿' }, { value: 'below', label: '下穿' }] };
export const ALERT_CROSS_DIRECTION_OPTIONS: Record<UiLanguage, Array<Option<'bullish_cross' | 'bearish_cross'>>> = { zh: [{ value: 'bullish_cross', label: '金叉' }, { value: 'bearish_cross', label: '死叉' }], en: [{ value: 'bullish_cross', label: 'Bullish cross' }, { value: 'bearish_cross', label: 'Bearish cross' }], 'zh-TW': [{ value: 'bullish_cross', label: '金叉' }, { value: 'bearish_cross', label: '死叉' }] };
export const ALERT_STOP_LOSS_MODE_OPTIONS: Record<UiLanguage, Array<Option<PortfolioStopLossMode>>> = { zh: [{ value: 'near', label: '接近止损' }, { value: 'breach', label: '已触发止损' }], en: [{ value: 'near', label: 'Near stop loss' }, { value: 'breach', label: 'Stop loss breached' }], 'zh-TW': [{ value: 'near', label: '接近停損' }, { value: 'breach', label: '已觸發停損' }] };
export const ALERT_MARKET_REGION_OPTIONS: Record<UiLanguage, Array<Option<MarketRegion>>> = { zh: [{ value: 'tw', label: '台股' }, { value: 'cn', label: 'A 股' }, { value: 'hk', label: '港股' }, { value: 'us', label: '美股' }], en: [{ value: 'tw', label: 'Taiwan' }, { value: 'cn', label: 'A-shares' }, { value: 'hk', label: 'Hong Kong' }, { value: 'us', label: 'US' }], 'zh-TW': [{ value: 'tw', label: '台股' }, { value: 'cn', label: 'A 股' }, { value: 'hk', label: '港股' }, { value: 'us', label: '美股' }] };
export const ALERT_MARKET_LIGHT_STATUS_OPTIONS: Record<UiLanguage, Array<Option<MarketLightStatus>>> = { zh: [{ value: 'red', label: '红灯' }, { value: 'yellow', label: '黄灯' }], en: [{ value: 'red', label: 'Red' }, { value: 'yellow', label: 'Yellow' }], 'zh-TW': [{ value: 'red', label: '紅燈' }, { value: 'yellow', label: '黃燈' }] };

export const PORTFOLIO_TEXT = {
  zh: { documentTitle: '持仓分析 - DSA', title: '持仓管理', description: '组合快照、手工录入、CSV 导入与风险分析（支持全组合 / 单账户切换）', accountView: '账户视图', allAccounts: '全部账户', costMethod: '成本口径', fifo: '先进先出（FIFO）', avg: '均价成本（AVG）', collapseCreate: '收起新建', createAccount: '新建账户', deleteAccount: '删除账户', deletingAccount: '删除中...', deleteAccountTitle: '删除持仓账户', deleteAccountConfirm: '确认删除', deleteAccountMessage: '确认删除账户 {name}（#{id}）吗？删除后该账户会从默认列表、快照、风险和录入入口隐藏；历史流水不会物理删除。', refreshing: '刷新中...', refreshData: '刷新数据', noAccounts: '还没有可用账户，请先创建账户后再录入交易或导入 CSV。', riskDegraded: '风险模块降级', operationHint: '操作提示', analysisTask: '分析任务', snapshotPartialTitle: '组合估值限制', totalEquity: '总权益', totalMarketValue: '总市值', totalCash: '总现金', fxStatus: '汇率状态', refreshFx: '刷新汇率', stale: '过期', latest: '最新', fxRefreshResult: '汇率刷新结果', positionsTitle: '持仓明细', countItems: '共 {count} 项', noPositionsTitle: '当前无持仓数据', noPositionsDescription: '录入交易或导入 CSV 后，这里会展示按账户汇总的持仓明细。', account: '账户', code: '代码', quantity: '数量', avgCost: '均价', lastPrice: '现价', marketValue: '市值', unrealizedPnl: '未实现盈亏', returnPct: '收益率', action: '操作', submitting: '提交中', analyze: '分析', sectorConcentration: '行业集中度分布', positionConcentrationFallback: '行业数据暂不可用，当前展示个股集中度', noConcentrationTitle: '暂无集中度数据', noConcentrationDescription: '风险模块完成计算后，这里会展示行业或个股维度的集中度分布。', displayScope: '展示口径', sectorDimension: '行业维度', positionDimensionFallback: '个股维度（降级显示）', sectorAlert: '板块集中度告警', topWeight: 'Top1 权重', yes: '是', no: '否', writeBlocked: '当前处于“全部账户”视图。为避免误写，请先选择一个具体账户后再进行手工录入或 CSV 提交。', drawdownMonitor: '回撤监控', maxDrawdown: '最大回撤', currentDrawdown: '当前回撤', alert: '告警', stopLossWarning: '止损接近预警', triggeredCount: '触发数', nearCount: '接近数', scope: '口径', accountCount: '账户数', currency: '计价币种', costMethodShort: '成本法', aiRiskSignals: 'AI 风险信号', aiRiskUnavailable: '信号风险暂不可用', aiRiskTotal: '风险信号', sellSignals: '卖出', reduceSignals: '减仓', alertSignals: '预警', noAiRiskSignals: '暂无防御型信号', fxMissing: '缺汇率', fxMissingTotal: '不可用', fxMissingHint: '缺少 {pairs} 汇率，跨币别总额无法换算；请按「刷新汇率」。' },
  en: { documentTitle: 'Portfolio Analysis - DSA', title: 'Portfolio management', description: 'Portfolio snapshots, manual entries, CSV import, and risk analysis with full-portfolio or single-account views', accountView: 'Account view', allAccounts: 'All accounts', costMethod: 'Cost method', fifo: 'FIFO', avg: 'Average cost', collapseCreate: 'Collapse', createAccount: 'New account', deleteAccount: 'Delete account', deletingAccount: 'Deleting...', deleteAccountTitle: 'Delete portfolio account', deleteAccountConfirm: 'Delete account', deleteAccountMessage: 'Delete account {name} (#{id})? It will be hidden from default lists, snapshots, risk views, and entry forms; historical ledger rows are not physically deleted.', refreshing: 'Refreshing...', refreshData: 'Refresh data', noAccounts: 'No accounts are available. Create an account before entering trades or importing CSV files.', riskDegraded: 'Risk module degraded', operationHint: 'Operation hint', analysisTask: 'Analysis task', snapshotPartialTitle: 'Portfolio valuation limitations', totalEquity: 'Total equity', totalMarketValue: 'Total market value', totalCash: 'Total cash', fxStatus: 'FX status', refreshFx: 'Refresh FX', stale: 'Stale', latest: 'Current', fxRefreshResult: 'FX refresh result', positionsTitle: 'Positions', countItems: '{count} items', noPositionsTitle: 'No positions', noPositionsDescription: 'After you enter trades or import CSV data, account-level positions appear here.', account: 'Account', code: 'Code', quantity: 'Quantity', avgCost: 'Avg cost', lastPrice: 'Last price', marketValue: 'Market value', unrealizedPnl: 'Unrealized P/L', returnPct: 'Return', action: 'Action', submitting: 'Submitting', analyze: 'Analyze', sectorConcentration: 'Sector concentration', positionConcentrationFallback: 'Sector data unavailable; showing position concentration', noConcentrationTitle: 'No concentration data', noConcentrationDescription: 'Sector or position concentration appears after the risk module finishes.', displayScope: 'Display scope', sectorDimension: 'Sector', positionDimensionFallback: 'Position fallback', sectorAlert: 'Sector concentration alert', topWeight: 'Top1 weight', yes: 'Yes', no: 'No', writeBlocked: 'You are viewing all accounts. Select a specific account before manual entry or CSV submission to avoid writing to the wrong scope.', drawdownMonitor: 'Drawdown monitor', maxDrawdown: 'Max drawdown', currentDrawdown: 'Current drawdown', alert: 'Alert', stopLossWarning: 'Stop-loss proximity warning', triggeredCount: 'Triggered', nearCount: 'Near', scope: 'Scope', accountCount: 'Accounts', currency: 'Quote currency', costMethodShort: 'Cost method', aiRiskSignals: 'AI risk signals', aiRiskUnavailable: 'Signal risk unavailable', aiRiskTotal: 'Risk signals', sellSignals: 'Sell', reduceSignals: 'Reduce', alertSignals: 'Alert', noAiRiskSignals: 'No defensive signals', fxMissing: 'Missing FX', fxMissingTotal: 'Unavailable', fxMissingHint: 'Missing {pairs} FX rate, so cross-currency totals cannot be converted. Use Refresh FX.' },
  'zh-TW': { documentTitle: '持股分析 - DSA', title: '持股', description: '', accountView: '帳戶視圖', allAccounts: '全部帳戶', costMethod: '成本計算', fifo: '先進先出（FIFO）', avg: '均價成本（AVG）', collapseCreate: '收起新建', createAccount: '新建帳戶', deleteAccount: '刪除帳戶', deletingAccount: '刪除中...', deleteAccountTitle: '刪除持股帳戶', deleteAccountConfirm: '確認刪除', deleteAccountMessage: '確認刪除帳戶 {name}（#{id}）嗎？刪除後該帳戶會從預設列表、快照、風險和錄入入口隱藏；歷史紀錄不會實體刪除。', refreshing: '重新整理中...', refreshData: '重新整理資料', noAccounts: '還沒有可用帳戶，請先建立帳戶後再錄入交易或匯入 CSV。', riskDegraded: '風險模組降級', operationHint: '操作提示', analysisTask: '分析任務', snapshotPartialTitle: '組合估值限制', totalEquity: '總權益', totalMarketValue: '總市值', totalCash: '總現金', fxStatus: '匯率狀態', refreshFx: '重新整理匯率', stale: '過期', latest: '最新', fxRefreshResult: '匯率重新整理結果', positionsTitle: '持股明細', countItems: '共 {count} 項', noPositionsTitle: '目前無持股資料', noPositionsDescription: '錄入交易或匯入 CSV 後，這裡會顯示依帳戶彙總的持股明細。', account: '帳戶', code: '代號', quantity: '數量', avgCost: '均價', lastPrice: '現價', marketValue: '市值', unrealizedPnl: '未實現損益', returnPct: '報酬率', action: '操作', submitting: '提交中', analyze: '分析', sectorConcentration: '產業集中度分布', positionConcentrationFallback: '產業資料暫不可用，目前顯示個股集中度', noConcentrationTitle: '暫無集中度資料', noConcentrationDescription: '風險模組完成計算後，這裡會顯示產業或個股維度的集中度分布。', displayScope: '顯示口徑', sectorDimension: '產業維度', positionDimensionFallback: '個股維度（降級顯示）', sectorAlert: '產業集中度警報', topWeight: 'Top1 權重', yes: '是', no: '否', writeBlocked: '目前處於「全部帳戶」視圖。為避免誤寫，請先選擇一個具體帳戶後再進行手工錄入或 CSV 提交。', drawdownMonitor: '回撤監控', maxDrawdown: '最大回撤', currentDrawdown: '當前回撤', alert: '警報', stopLossWarning: '停損接近預警', triggeredCount: '觸發數', nearCount: '接近數', scope: '口徑', accountCount: '帳戶數', currency: '計價幣種', costMethodShort: '成本法', aiRiskSignals: 'AI 風險訊號', aiRiskUnavailable: '訊號風險暫不可用', aiRiskTotal: '風險訊號', sellSignals: '賣出', reduceSignals: '減碼', alertSignals: '預警', noAiRiskSignals: '暫無防禦型訊號', fxMissing: '缺匯率', fxMissingTotal: '不可用', fxMissingHint: '缺少 {pairs} 匯率，跨幣別總額無法換算；請按「重新整理匯率」。' },
} as const;
export const PORTFOLIO_SIDE_LABELS: Record<UiLanguage, Record<PortfolioSide, string>> = { zh: { buy: '买入', sell: '卖出' }, en: { buy: 'Buy', sell: 'Sell' }, 'zh-TW': { buy: '買進', sell: '賣出' } };
export const PORTFOLIO_CASH_DIRECTION_LABELS: Record<UiLanguage, Record<PortfolioCashDirection, string>> = { zh: { in: '流入', out: '流出' }, en: { in: 'Inflow', out: 'Outflow' }, 'zh-TW': { in: '流入', out: '流出' } };
export const PORTFOLIO_CORPORATE_ACTION_LABELS: Record<UiLanguage, Record<PortfolioCorporateActionType, string>> = { zh: { cash_dividend: '现金分红', split_adjustment: '拆并股调整' }, en: { cash_dividend: 'Cash dividend', split_adjustment: 'Split adjustment' }, 'zh-TW': { cash_dividend: '現金股利', split_adjustment: '股票分拆調整' } };

// 警報頁改版的文案；句子模板的 {target}、{value} 由元件帶入。
export const ALERT_PAGE_TEXT = {
  'zh-TW': {
    title: '價格警報', newRule: '新增規則', editRule: '編輯規則',
    monitorRunning: '監控中', monitorEvery: '每 {minutes} 分鐘檢查', monitorLastRun: '上次執行 {time}', monitorNotYet: '尚未執行',
    monitorChannels: '通知：{channels}', monitorNoChannel: '尚未設定通知管道，觸發後不會送出',
    monitorDownTitle: '監控未啟動，規則不會被檢查', monitorUnknown: '無法取得監控狀態',
    reasonDisabled: '服務沒有開啟警報監控（AGENT_EVENT_MONITOR_ENABLED）。', reasonThread: '監控執行緒沒有在跑，請重啟服務。', reasonSchedule: '服務沒有開啟排程，也沒有開啟只跑監控（AGENT_EVENT_MONITOR_WITHOUT_SCHEDULE）。',
    monitorError: '上一輪失敗：{error}',
    statRules: '啟用規則', statTriggered: '已觸發', statIssues: '異常', statSkipped: '略過',
    search: '搜尋股票', searchPlaceholder: '輸入代號，例如 2330.TW', group: '群組', allGroups: '全部群組', status: '狀態', type: '類型',
    tabRules: '規則', tabActivity: '動態', tabDiagnostics: '通知診斷',
    guideTitle: '還沒有警報規則', guideBody: '選一個範本開始，條件達成時會推播通知。',
    tplPrice: '股價站上或跌破某個價位', tplChange: '單日跌幅達 3%', tplMarket: '台股大盤轉紅燈',
    noMatch: '沒有符合篩選條件的規則', loadMore: '載入更多',
    whenPrefix: '當', remind: '時提醒',
    above: '站上', below: '跌破', up: '單日漲幅達', down: '單日跌幅達', volume: '成交量達均量', times: '倍',
    closeAboveMa: '收盤站上', closeBelowMa: '收盤跌破', crossUp: '向上突破', crossDown: '向下跌破',
    bullish: '黃金交叉', bearish: '死亡交叉',
    stopNear: '持股接近停損', stopBreach: '持股跌破停損', concentration: '持股集中度超過上限', drawdown: '帳戶回撤超過上限', stale: '持股價格過期或缺價',
    marketStatus: '大盤信號轉為', scoreDrop: '大盤分數下降達 {value} 分',
    watchlist: '自選股任一檔', holdings: '持股任一檔', allAccounts: '全部帳戶', account: '帳戶 {target}',
    current: '現價 {price}', distance: '距離 {pct}', noQuote: '暫無報價',
    lastTriggered: '上次觸發 {time}', neverTriggered: '尚未觸發', cooling: '提醒冷卻到 {time}', childCooldown: '各檔冷卻見動態',
    daily: '每天最多一次', hourly: '每小時最多一次', everyCustom: '每 {minutes} 分鐘最多一次', levelSource: '盯盤看板建立',
    switchOn: '啟用 {name}', menu: '{name} 的更多操作', edit: '編輯', dryRun: '試算目前條件', dryRunning: '試算中', delete: '刪除',
    dryRunNote: '只試算，不會送出通知', dryRunHit: '目前條件已達成', dryRunMiss: '目前條件未達成', dryRunError: '無法試算', dryRunUnable: '無法評估目前條件', dryRunPartial: '部分標的無法評估', dryRunUnableCount: '{count} 檔無法評估', dryRunObserved: '目前數值 {value}', dryRunSummary: '檢查 {evaluated} 檔，達成 {triggered} 檔', dryRunClose: '收起',
    activityTitle: '動態', tabTriggered: '已觸發', tabIssues: '異常', noTriggered: '還沒有觸發紀錄', noIssues: '沒有異常紀錄',
    observed: '當時 {value}', threshold: '條件 {value}', source: '來源 {source}',
    sourceShioaji: '永豐即時', sourceYfinance: 'yfinance（可能延遲）', sourceFallback: '備援來源（可能延遲）',
    statusSkipped: '略過', statusDegraded: '資料不完整', statusFailed: '失敗', statusTriggered: '已觸發',
    deleteTitle: '刪除警報規則', deleteMessage: '確定刪除「{name}」？已有的觸發紀錄會保留。', cancel: '取消',
    created: '已建立規則「{name}」', updated: '已更新規則「{name}」', close: '關閉',
    legacyTitle: '另有環境變數規則', legacyMessage: '環境變數設定了 {configured} 條有效規則，依目前啟用的頁面規則去重後有 {effective} 條可供背景輪詢。這個數字不受頁面篩選影響，也不代表背景輪詢已啟動。頁面只管理資料庫規則；刪除或停用頁面規則不會停用環境規則。要停用請在部署設定修改 AGENT_EVENT_ALERT_RULES_JSON 並重新載入設定。',
    diagnostics: '通知診斷', diagnosticsHint: '最近的通知嘗試紀錄', noNotifications: '還沒有通知紀錄', viewDiagnostics: '查看診斷', channelCooldown: '提醒冷卻', channelCooldownFail: '冷卻讀取失敗', channelNoise: '通知降噪', channelNone: '沒有可用管道', channelDispatch: '通知派送', channelContext: '對話管道',
    resultOk: '成功', resultCooldown: '冷卻中略過', resultNoise: '降噪略過', resultNoChannel: '沒有管道', resultFail: '失敗',
    stepWho: '監控誰', stepWhen: '何時提醒', stepHow: '怎麼提醒', frequency: '提醒頻率', levelLocked: '這條由盯盤看板建立，價位要回看板重建，不能在這裡改。', currentPrice: '現價 {price}，距離條件 {pct}', save: '儲存', stockPlaceholder: '輸入代號或名稱，例如 台積電',
    bell: '設定 {code} 的價格警報',
  },
  zh: {
    title: '价格警报', newRule: '新增规则', editRule: '编辑规则',
    monitorRunning: '监控中', monitorEvery: '每 {minutes} 分钟检查', monitorLastRun: '上次执行 {time}', monitorNotYet: '尚未执行',
    monitorChannels: '通知：{channels}', monitorNoChannel: '尚未设置通知渠道，触发后不会发送',
    monitorDownTitle: '监控未启动，规则不会被检查', monitorUnknown: '无法获取监控状态',
    reasonDisabled: '服务没有开启警报监控（AGENT_EVENT_MONITOR_ENABLED）。', reasonThread: '监控线程没有在运行，请重启服务。', reasonSchedule: '服务没有开启调度，也没有开启仅运行监控（AGENT_EVENT_MONITOR_WITHOUT_SCHEDULE）。',
    monitorError: '上一轮失败：{error}',
    statRules: '启用规则', statTriggered: '已触发', statIssues: '异常', statSkipped: '跳过',
    search: '搜索股票', searchPlaceholder: '输入代码，例如 2330.TW', group: '分组', allGroups: '全部分组', status: '状态', type: '类型',
    tabRules: '规则', tabActivity: '动态', tabDiagnostics: '通知诊断',
    guideTitle: '还没有警报规则', guideBody: '选一个模板开始，条件达成时会推送通知。',
    tplPrice: '股价站上或跌破某个价位', tplChange: '单日跌幅达 3%', tplMarket: '台股大盘转红灯',
    noMatch: '没有符合筛选条件的规则', loadMore: '加载更多',
    whenPrefix: '当', remind: '时提醒',
    above: '站上', below: '跌破', up: '单日涨幅达', down: '单日跌幅达', volume: '成交量达均量', times: '倍',
    closeAboveMa: '收盘站上', closeBelowMa: '收盘跌破', crossUp: '向上突破', crossDown: '向下跌破',
    bullish: '金叉', bearish: '死叉',
    stopNear: '持仓接近止损', stopBreach: '持仓跌破止损', concentration: '持仓集中度超过上限', drawdown: '账户回撤超过上限', stale: '持仓价格过期或缺价',
    marketStatus: '大盘信号转为', scoreDrop: '大盘分数下降达 {value} 分',
    watchlist: '自选股任一只', holdings: '持仓任一只', allAccounts: '全部账户', account: '账户 {target}',
    current: '现价 {price}', distance: '距离 {pct}', noQuote: '暂无报价',
    lastTriggered: '上次触发 {time}', neverTriggered: '尚未触发', cooling: '提醒冷却到 {time}', childCooldown: '各只冷却见动态',
    daily: '每天最多一次', hourly: '每小时最多一次', everyCustom: '每 {minutes} 分钟最多一次', levelSource: '盯盘看板创建',
    switchOn: '启用 {name}', menu: '{name} 的更多操作', edit: '编辑', dryRun: '试算当前条件', dryRunning: '试算中', delete: '删除',
    dryRunNote: '只试算，不会发送通知', dryRunHit: '当前条件已达成', dryRunMiss: '当前条件未达成', dryRunError: '无法试算', dryRunUnable: '无法评估当前条件', dryRunPartial: '部分标的无法评估', dryRunUnableCount: '{count} 只无法评估', dryRunObserved: '当前数值 {value}', dryRunSummary: '检查 {evaluated} 只，达成 {triggered} 只', dryRunClose: '收起',
    activityTitle: '动态', tabTriggered: '已触发', tabIssues: '异常', noTriggered: '还没有触发记录', noIssues: '没有异常记录',
    observed: '当时 {value}', threshold: '条件 {value}', source: '来源 {source}',
    sourceShioaji: '永丰实时', sourceYfinance: 'yfinance（可能延迟）', sourceFallback: '备用来源（可能延迟）',
    statusSkipped: '跳过', statusDegraded: '数据不完整', statusFailed: '失败', statusTriggered: '已触发',
    deleteTitle: '删除警报规则', deleteMessage: '确定删除「{name}」？已有的触发记录会保留。', cancel: '取消',
    created: '已创建规则「{name}」', updated: '已更新规则「{name}」', close: '关闭',
    legacyTitle: '存在环境变量告警规则', legacyMessage: '环境变量配置了 {configured} 条有效规则，按当前启用的页面规则去重后有 {effective} 条可供后台轮询。此数量不受页面筛选影响，也不表示后台轮询已启动。页面仅管理数据库规则；删除或禁用页面规则不会停用环境规则。若需停用，请在部署配置中修改 AGENT_EVENT_ALERT_RULES_JSON 并重新加载配置。',
    diagnostics: '通知诊断', diagnosticsHint: '最近的通知尝试记录', noNotifications: '还没有通知记录', viewDiagnostics: '查看诊断', channelCooldown: '提醒冷却', channelCooldownFail: '冷却读取失败', channelNoise: '通知降噪', channelNone: '没有可用渠道', channelDispatch: '通知发送', channelContext: '会话渠道',
    resultOk: '成功', resultCooldown: '冷却中跳过', resultNoise: '降噪跳过', resultNoChannel: '没有渠道', resultFail: '失败',
    stepWho: '监控谁', stepWhen: '何时提醒', stepHow: '怎么提醒', frequency: '提醒频率', levelLocked: '这条由盯盘看板创建，价位要回看板重建，不能在这里改。', currentPrice: '现价 {price}，距离条件 {pct}', save: '保存', stockPlaceholder: '输入代码或名称，例如 台积电',
    bell: '设置 {code} 的价格警报',
  },
  en: {
    title: 'Price alerts', newRule: 'New rule', editRule: 'Edit rule',
    monitorRunning: 'Monitoring', monitorEvery: 'checks every {minutes} min', monitorLastRun: 'last run {time}', monitorNotYet: 'not run yet',
    monitorChannels: 'Channels: {channels}', monitorNoChannel: 'No notification channel; triggers will not be sent',
    monitorDownTitle: 'Monitor is not running; rules are not being checked', monitorUnknown: 'Monitor status unavailable',
    reasonDisabled: 'Alert monitoring is off (AGENT_EVENT_MONITOR_ENABLED).', reasonThread: 'The monitor thread is not running; restart the service.', reasonSchedule: 'Neither the schedule nor monitor-only mode (AGENT_EVENT_MONITOR_WITHOUT_SCHEDULE) is on.',
    monitorError: 'Last cycle failed: {error}',
    statRules: 'Active rules', statTriggered: 'Triggered', statIssues: 'Issues', statSkipped: 'Skipped',
    search: 'Search stock', searchPlaceholder: 'Enter a code, e.g. 2330.TW', group: 'Group', allGroups: 'All groups', status: 'Status', type: 'Type',
    tabRules: 'Rules', tabActivity: 'Activity', tabDiagnostics: 'Diagnostics',
    guideTitle: 'No alert rules yet', guideBody: 'Start from a template; you get a notification when the condition is met.',
    tplPrice: 'Price rises above or falls below a level', tplChange: 'Daily drop reaches 3%', tplMarket: 'Taiwan market light turns red',
    noMatch: 'No rules match these filters', loadMore: 'Load more',
    whenPrefix: 'When', remind: '',
    above: 'rises above', below: 'falls below', up: 'daily gain reaches', down: 'daily drop reaches', volume: 'volume reaches average x', times: '',
    closeAboveMa: 'closes above', closeBelowMa: 'closes below', crossUp: 'crosses above', crossDown: 'crosses below',
    bullish: 'bullish cross', bearish: 'bearish cross',
    stopNear: 'holding nears stop loss', stopBreach: 'holding breaches stop loss', concentration: 'concentration exceeds the limit', drawdown: 'drawdown exceeds the limit', stale: 'holding price is stale or missing',
    marketStatus: 'market light turns', scoreDrop: 'market score drops by {value}',
    watchlist: 'any watchlist stock', holdings: 'any holding', allAccounts: 'all accounts', account: 'account {target}',
    current: 'Price {price}', distance: '{pct} away', noQuote: 'No quote',
    lastTriggered: 'Last triggered {time}', neverTriggered: 'Never triggered', cooling: 'Cooling down until {time}', childCooldown: 'Per-stock cooldowns are in activity',
    daily: 'At most once a day', hourly: 'At most once an hour', everyCustom: 'At most every {minutes} min', levelSource: 'Created from the board',
    switchOn: 'Enable {name}', menu: 'More actions for {name}', edit: 'Edit', dryRun: 'Evaluate now', dryRunning: 'Evaluating', delete: 'Delete',
    dryRunNote: 'Evaluation only; no notification is sent', dryRunHit: 'Condition is met now', dryRunMiss: 'Condition is not met now', dryRunError: 'Could not evaluate', dryRunUnable: 'Condition could not be evaluated', dryRunPartial: 'Some targets could not be evaluated', dryRunUnableCount: '{count} could not be evaluated', dryRunObserved: 'Current value {value}', dryRunSummary: 'Checked {evaluated}, met {triggered}', dryRunClose: 'Dismiss',
    activityTitle: 'Activity', tabTriggered: 'Triggered', tabIssues: 'Issues', noTriggered: 'No triggers yet', noIssues: 'No issues',
    observed: 'Value {value}', threshold: 'Condition {value}', source: 'Source {source}',
    sourceShioaji: 'Sinopac realtime', sourceYfinance: 'yfinance (may be delayed)', sourceFallback: 'Fallback (may be delayed)',
    statusSkipped: 'Skipped', statusDegraded: 'Incomplete data', statusFailed: 'Failed', statusTriggered: 'Triggered',
    deleteTitle: 'Delete alert rule', deleteMessage: 'Delete "{name}"? Existing trigger history is kept.', cancel: 'Cancel',
    created: 'Created "{name}"', updated: 'Updated "{name}"', close: 'Dismiss',
    legacyTitle: 'Environment rules exist', legacyMessage: '{configured} valid rules come from environment config; {effective} remain for background polling after deduplicating against enabled page rules. This count ignores page filters and does not mean polling is running. This page only manages database rules, so deleting or disabling them does not stop environment rules. To stop those, change AGENT_EVENT_ALERT_RULES_JSON in the deployment config and reload it.',
    diagnostics: 'Diagnostics', diagnosticsHint: 'Recent notification attempts', noNotifications: 'No notification attempts yet', viewDiagnostics: 'View diagnostics', channelCooldown: 'Cooldown', channelCooldownFail: 'Cooldown read failed', channelNoise: 'Noise control', channelNone: 'No channel', channelDispatch: 'Dispatch', channelContext: 'Chat channel',
    resultOk: 'Sent', resultCooldown: 'Skipped by cooldown', resultNoise: 'Skipped by noise control', resultNoChannel: 'No channel', resultFail: 'Failed',
    stepWho: 'What to watch', stepWhen: 'When to alert', stepHow: 'How to alert', frequency: 'Frequency', levelLocked: 'Created from the board; rebuild it there to change the level.', currentPrice: 'Price {price}, {pct} from the condition', save: 'Save', stockPlaceholder: 'Enter a code or name',
    bell: 'Set a price alert for {code}',
  },
} as const;

// 回測頁改版後的文案；欄位多，獨立一張表，不和上面的舊文案混。
export const BACKTEST_OVERVIEW_TEXT = {
  zh: {
    pageTitle: '回测',
    recalculate: '重新计算',
    recalculateDescription: '依下方条件重新评估历史分析。强制重跑会连同未满最小天龄的记录一起算。',
    appliedLabel: '已套用：',
    clearFilters: '清除条件',
    conclusion: '已完成 {count} 笔：胜率 {winRate}（{win} 胜 {loss} 负），平均模拟收益 {simulated}，同期个股平均 {stock}。',
    conclusionInsufficient: '样本不足：只有 {count} 笔已完成（少于 {min} 笔），以下数字仅供观察，不下结论。',
    tabCompleted: '已完成',
    tabPending: '未到期',
    tabAll: '全部',
    maturesBy: '{date} 前到期',
    adviceTitle: '依建议拆解',
    adviceColumn: '建议',
    countColumn: '笔数',
    adviceUnclassified: '未分类',
    emptyFilteredTitle: '没有符合条件的结果',
    emptyFilteredDescription: '换个条件，或清除条件看全部。',
    emptyPendingTitle: '没有未到期的回测',
    emptyPendingDescription: '评估窗口还没走完的分析会列在这里。',
    entryDate: '进场日',
    entryPrice: '进场价',
    exitPrice: '出场价',
    exitReason: '出场原因',
    simulatedReturn: '模拟收益',
    stopLoss: '停损价',
    takeProfit: '停利价',
    firstHit: '先触及',
    chartTitle: '逐笔累计（非资金曲线）',
    chartSimulated: '累计模拟收益',
    chartStock: '同期个股累计',
    monthlyWinRate: '月胜率',
    updatedAt: '资料更新：{time}',
    chartTruncated: '笔数超过上限，只含最新的部分，累计值不含更早的回测。',
    chartPhaseIgnored: '趋势图不受阶段条件影响。',
  },
  en: {
    pageTitle: 'Backtest',
    recalculate: 'Recalculate',
    recalculateDescription: 'Re-evaluate past analyses with the conditions below. Force rerun also includes records younger than the minimum age.',
    appliedLabel: 'Applied: ',
    clearFilters: 'Clear filters',
    conclusion: '{count} completed: win rate {winRate} ({win}W {loss}L), avg simulated return {simulated}, same-period stock avg {stock}.',
    conclusionInsufficient: 'Not enough samples: only {count} completed (under {min}). These numbers are for observation only.',
    tabCompleted: 'Completed',
    tabPending: 'Not matured',
    tabAll: 'All',
    maturesBy: 'matures by {date}',
    adviceTitle: 'By advice',
    adviceColumn: 'Advice',
    countColumn: 'Count',
    adviceUnclassified: 'Unclassified',
    emptyFilteredTitle: 'No matching results',
    emptyFilteredDescription: 'Try other conditions, or clear them to see everything.',
    emptyPendingTitle: 'Nothing waiting to mature',
    emptyPendingDescription: 'Analyses whose evaluation window has not finished appear here.',
    entryDate: 'Entry date',
    entryPrice: 'Entry price',
    exitPrice: 'Exit price',
    exitReason: 'Exit reason',
    simulatedReturn: 'Simulated return',
    stopLoss: 'Stop loss',
    takeProfit: 'Take profit',
    firstHit: 'Hit first',
    chartTitle: 'Per-trade cumulative (not an equity curve)',
    chartSimulated: 'Cumulative simulated return',
    chartStock: 'Same-period stock cumulative',
    monthlyWinRate: 'Monthly win rate',
    updatedAt: 'Data updated: {time}',
    chartTruncated: 'Over the row limit: only the newest rows are included, so the cumulative excludes older backtests.',
    chartPhaseIgnored: 'The phase condition does not apply to these charts.',
  },
  'zh-TW': {
    pageTitle: '回測',
    recalculate: '重新計算',
    recalculateDescription: '依下方條件重新評估歷史分析。強制重跑會連同未滿最小天數的紀錄一起算。',
    appliedLabel: '已套用：',
    clearFilters: '清除條件',
    conclusion: '已完成 {count} 筆：勝率 {winRate}（{win} 勝 {loss} 負），平均模擬報酬 {simulated}，同期個股平均 {stock}。',
    conclusionInsufficient: '樣本不足：只有 {count} 筆已完成（少於 {min} 筆），以下數字僅供觀察，不下結論。',
    tabCompleted: '已完成',
    tabPending: '未到期',
    tabAll: '全部',
    maturesBy: '{date} 前到期',
    adviceTitle: '依建議拆解',
    adviceColumn: '建議',
    countColumn: '筆數',
    adviceUnclassified: '未分類',
    emptyFilteredTitle: '沒有符合條件的結果',
    emptyFilteredDescription: '換個條件，或清除條件看全部。',
    emptyPendingTitle: '沒有未到期的回測',
    emptyPendingDescription: '評估天數還沒走完的分析會列在這裡。',
    entryDate: '進場日',
    entryPrice: '進場價',
    exitPrice: '出場價',
    exitReason: '出場原因',
    simulatedReturn: '模擬報酬',
    stopLoss: '停損價',
    takeProfit: '停利價',
    firstHit: '先觸及',
    chartTitle: '逐筆累計（非資金曲線）',
    chartSimulated: '累計模擬報酬',
    chartStock: '同期個股累計',
    monthlyWinRate: '月勝率',
    updatedAt: '資料更新：{time}',
    chartTruncated: '筆數超過上限，只含最新的部分，累計值不含更早的回測。',
    chartPhaseIgnored: '趨勢圖不受階段條件影響。',
  },
} as const;

export const BACKTEST_EXIT_REASON_LABELS: Record<UiLanguage, Record<string, string>> = {
  zh: { stop_loss: '触及停损', take_profit: '触及停利', ambiguous: '同日触及', ambiguous_stop_loss: '同日触及（按停损算）', window_end: '窗口结束', cash: '未进场', neither: '都未触及', none: '都未触及' },
  en: { stop_loss: 'Stop loss', take_profit: 'Take profit', ambiguous: 'Both on one day', ambiguous_stop_loss: 'Both on one day (as stop loss)', window_end: 'Window end', cash: 'No entry', neither: 'Neither', none: 'Neither' },
  'zh-TW': { stop_loss: '觸及停損', take_profit: '觸及停利', ambiguous: '同日觸及', ambiguous_stop_loss: '同日觸及（按停損算）', window_end: '期滿', cash: '未進場', neither: '都未觸及', none: '都未觸及' },
};

export const PORTFOLIO_FORMAT_TEXT: Record<UiLanguage, {
  priceMissing: string; priceRealtime: string; priceClose: string; priceUnknown: string;
  fxDisabled: string; fxNoPairs: string; fxUpdated: string; fxSummary: string; fxStillStale: string; fxPartial: string;
}> = {
  zh: {
    priceMissing: '缺价', priceRealtime: '实时价', priceClose: '收盘价', priceUnknown: '未知来源',
    fxDisabled: '汇率在线刷新已被禁用。', fxNoPairs: '当前范围无可刷新的汇率对。', fxUpdated: '汇率已刷新，共更新 {count} 对。',
    fxSummary: '更新 {updated} 对，仍过期 {stale} 对，失败 {errors} 对。', fxStillStale: '已尝试刷新，但仍有部分货币对使用 stale/fallback 汇率。', fxPartial: '在线刷新未完全成功。',
  },
  en: {
    priceMissing: 'No price', priceRealtime: 'Live', priceClose: 'Close', priceUnknown: 'Unknown source',
    fxDisabled: 'Online FX refresh is disabled.', fxNoPairs: 'No FX pairs to refresh in this scope.', fxUpdated: 'FX refreshed; {count} pairs updated.',
    fxSummary: '{updated} updated, {stale} still stale, {errors} failed.', fxStillStale: 'Refresh attempted, but some pairs still use stale rates. ', fxPartial: 'Online refresh did not fully succeed. ',
  },
  'zh-TW': {
    priceMissing: '缺價', priceRealtime: '即時價', priceClose: '收盤價', priceUnknown: '未知來源',
    fxDisabled: '匯率線上更新已停用。', fxNoPairs: '目前範圍沒有可更新的匯率對。', fxUpdated: '匯率已更新，共 {count} 對。',
    fxSummary: '更新 {updated} 對，仍過期 {stale} 對，失敗 {errors} 對。', fxStillStale: '已嘗試更新，但仍有部分幣別對使用過期匯率。', fxPartial: '線上更新未完全成功。',
  },
};

const PORTFOLIO_PAGE_TEXT_ZH = {
  recordEntry: '记一笔', importEntry: '导入', more: '更多操作', rowMenu: '{symbol} 的更多操作', costMethodLabel: '成本计算', loadError: '载入失败', retry: '重试',
  sectionPending: '待处理', pendingStopTriggered: '{symbol} 已触发停损，亏损 {pct}', pendingStopNear: '{symbol} 接近停损，亏损 {pct}', pendingMissingPrice: '{symbol} 缺报价',
  pendingNegativeCash: '{account} 现金为负（{amount}），可能漏记入金', pendingBackfill: '补记',
  metricTotalAssets: '总资产', metricDay: '今日', metricUnrealized: '未实现', metricRealized: '已实现', metricMarketValue: '市值', metricCash: '现金', metricFunds: '基金',
  includesFunds: '含基金 {amount}', excludesFunds: '不含基金（基金资料暂时无法取得）', stocksOnly: '只计股票',
  colName: '名称', colValue: '市值', colWeight: '占比', colPrice: '现价／成本', colPriceOn: '现价（{date}）／成本', colPnl: '损益', colAi: 'AI', costPrefix: '成本',
  sortBy: '持股排序', sortValue: '市值', sortPnl: '损益', sortReturn: '报酬', sortName: '名称', groupSummary: '{label}（{count} 档）', viewAlert: '设定警报',
  analyzeInAccount: '分析（{account}）', analysisSubmitted: '已提交 {symbol} 分析任务：{taskId}',
  marketTw: '台股', marketUs: '美股', marketCn: 'A 股', marketHk: '港股', marketJp: '日股', marketKr: '韩股', accountExposure: '帐户占比',
  entryTitle: '记一笔', importTitle: '导入持股', entryAccount: '帐户', entryTrade: '交易', entryCash: '资金', entryCorporate: '公司行动', writeNeedsAccount: '请先建立帐户。',
  symbolPlaceholder: '股票代号（例如 2330.TW）', symbolPlaceholderShort: '股票代号', buy: '买入', sell: '卖出', quantityRequired: '数量（必填）', priceRequired: '成交价（必填）', feeOptional: '手续费（可选）', taxOptional: '税费（可选）', feeHint: '手续费和税费可留空，系统将按 0 处理。', submitTrade: '提交交易',
  cashIn: '流入', cashOut: '流出', amount: '金额', currencyOptional: '币别（可选，默认 {currency}）', accountBase: '帐户基准币', submitCash: '提交资金流水',
  actionCashDividend: '现金分红', actionSplit: '拆并股调整', dividendPerShare: '每股分红', splitRatio: '拆并股比例', submitCorporate: '提交公司行动',
  createTitle: '新建账户', createAfter: '创建后自动切换到该账户', createFail: '创建账户失败', createOk: '创建账户成功', createOkMessage: '账户创建成功，已自动切换到该账户。', createNameEmpty: '账户名称不能为空。', createFailRetry: '创建账户失败，请稍后重试。',
  accountNamePlaceholder: '账户名称（必填）', brokerPlaceholder: '券商（可选，如 国泰）', basePlaceholder: '基准币（如 TWD/USD）', creating: '创建中...', createSubmit: '创建账户',
  marketOptionTw: '市场：台股（tw）', marketOptionUs: '市场：美股（us）', marketOptionCn: '市场：A 股（cn）', marketOptionHk: '市场：港股（hk）', marketOptionJp: '市场：日股（jp）', marketOptionKr: '市场：韩股（kr）',
  brokerEmpty: '券商列表接口返回为空，已回退为内置券商列表（华泰/中信/招商）。', brokerError: '券商列表接口不可用，已回退为内置券商列表（华泰/中信/招商）。',
  csvTitle: '券商 CSV 导入', csvPick: '选择 CSV', dryRun: '仅预演（不写入）', parsing: '解析中...', parseFile: '解析文件', committing: '提交中...', commitImport: '提交导入',
  csvParseTitle: 'CSV 解析结果', parseSummary: '有效 {records} 条，跳过 {skipped} 条，错误 {errors} 条。', csvDryTitle: 'CSV 预演结果', csvCommitTitle: 'CSV 提交结果', dryPrefix: '预演检查', commitPrefix: '实际写入', commitSummary: '{prefix}：写入 {inserted} 条，重复 {duplicate} 条，失败 {failed} 条。',
  pasteTitle: '粘贴持仓导入', pasteHint: '每行「名称或代号 股数 平均成本 [日期]」，空格或 Tab 分隔；也可直接粘贴券商库存表，再用「转成待填范本」补成本。平均成本请填券商的成本均价（已含买进手续费）。重复粘贴同一份内容会去重，持股变动后请改用交易录入。', pasteLabel: '粘贴持仓', pasteDate: '默认建仓日期', toTemplate: '转成待填范本', parseContent: '解析内容', pasteParseTitle: '粘贴解析结果', pasteParseSummary: '有效 {records} 条，缺成本 {missing} 条，错误 {errors} 条。', missingCostLine: '缺成本：{name} {symbol} × {quantity}', pasteDryTitle: '粘贴预演结果', pasteCommitTitle: '粘贴提交结果',
  recordsTitle: '交易纪录', typeTrade: '交易', typeCash: '资金', typeCorporate: '公司行动', refreshRecords: '刷新纪录', loadingRecords: '加载中...', dateFrom: '起始日期', dateTo: '结束日期', filterSymbol: '按股票代号筛选', sideAll: '全部买卖方向', directionAll: '全部资金方向', actionAll: '全部公司行动', deleteHintBlocked: '删除修正仅在单账户视图可用，请先切到具体账户。',
  colDate: '日期', colSide: '方向', colSymbol: '代号', colQuantity: '数量', colTradePrice: '价格', colFee: '费用', colDirection: '方向', colAmount: '金额', colAction: '类型', colDetail: '内容', remove: '删除', removeRow: '删除这笔', noRecords: '暂无纪录', noRecordsHint: '调整筛选条件或先记一笔。', pageOf: '第 {page} / {total} 页', prevPage: '上一页', nextPage: '下一页',
  deleteTradeMsg: '确认删除 {date} 的{side}流水 {symbol}（数量 {quantity}，价格 {price}）吗？', deleteCashMsg: '确认删除 {date} 的资金流水（{direction} {amount} {currency}）吗？', deleteCorporateMsg: '确认删除 {date} 的公司行动 {action}（{symbol}）吗？', deleteTitle: '删除错误流水', deleteConfirm: '确认删除这条流水吗？', deleting: '删除中...', confirmDelete: '确认删除', cancel: '取消',
  concentrationBars: '持股占比排行',
};

export const PORTFOLIO_PAGE_TEXT: Record<UiLanguage, Record<keyof typeof PORTFOLIO_PAGE_TEXT_ZH, string>> = {
  zh: PORTFOLIO_PAGE_TEXT_ZH,
  en: {
    recordEntry: 'Add entry', importEntry: 'Import', more: 'More actions', rowMenu: 'More actions for {symbol}', costMethodLabel: 'Cost method', loadError: 'Failed to load', retry: 'Retry',
    sectionPending: 'Needs attention', pendingStopTriggered: '{symbol} hit stop loss, down {pct}', pendingStopNear: '{symbol} near stop loss, down {pct}', pendingMissingPrice: '{symbol} has no quote',
    pendingNegativeCash: '{account} cash is negative ({amount}); a deposit may be missing', pendingBackfill: 'Record',
    metricTotalAssets: 'Total assets', metricDay: 'Today', metricUnrealized: 'Unrealized', metricRealized: 'Realized', metricMarketValue: 'Market value', metricCash: 'Cash', metricFunds: 'Funds',
    includesFunds: 'Includes funds {amount}', excludesFunds: 'Excludes funds (fund data unavailable)', stocksOnly: 'Stocks only',
    colName: 'Name', colValue: 'Value', colWeight: 'Weight', colPrice: 'Price / cost', colPriceOn: 'Price ({date}) / cost', colPnl: 'P/L', colAi: 'AI', costPrefix: 'Cost',
    sortBy: 'Sort holdings', sortValue: 'Value', sortPnl: 'P/L', sortReturn: 'Return', sortName: 'Name', groupSummary: '{label} ({count})', viewAlert: 'Set alert',
    analyzeInAccount: 'Analyze ({account})', analysisSubmitted: 'Submitted analysis for {symbol}: {taskId}',
    marketTw: 'Taiwan', marketUs: 'US', marketCn: 'A-shares', marketHk: 'Hong Kong', marketJp: 'Japan', marketKr: 'Korea', accountExposure: 'Account share',
    entryTitle: 'Add entry', importTitle: 'Import holdings', entryAccount: 'Account', entryTrade: 'Trade', entryCash: 'Cash', entryCorporate: 'Corporate action', writeNeedsAccount: 'Create an account first.',
    symbolPlaceholder: 'Stock code (e.g. 2330.TW)', symbolPlaceholderShort: 'Stock code', buy: 'Buy', sell: 'Sell', quantityRequired: 'Quantity (required)', priceRequired: 'Price (required)', feeOptional: 'Fee (optional)', taxOptional: 'Tax (optional)', feeHint: 'Blank fee and tax count as 0.', submitTrade: 'Submit trade',
    cashIn: 'Inflow', cashOut: 'Outflow', amount: 'Amount', currencyOptional: 'Currency (optional, defaults to {currency})', accountBase: 'account base', submitCash: 'Submit cash entry',
    actionCashDividend: 'Cash dividend', actionSplit: 'Split adjustment', dividendPerShare: 'Dividend per share', splitRatio: 'Split ratio', submitCorporate: 'Submit corporate action',
    createTitle: 'New account', createAfter: 'Switches to the account once created', createFail: 'Could not create account', createOk: 'Account created', createOkMessage: 'Account created and selected.', createNameEmpty: 'Account name is required.', createFailRetry: 'Could not create the account. Try again later.',
    accountNamePlaceholder: 'Account name (required)', brokerPlaceholder: 'Broker (optional)', basePlaceholder: 'Base currency (e.g. TWD/USD)', creating: 'Creating...', createSubmit: 'Create account',
    marketOptionTw: 'Market: Taiwan (tw)', marketOptionUs: 'Market: US (us)', marketOptionCn: 'Market: A-shares (cn)', marketOptionHk: 'Market: Hong Kong (hk)', marketOptionJp: 'Market: Japan (jp)', marketOptionKr: 'Market: Korea (kr)',
    brokerEmpty: 'The broker list was empty; using the built-in list.', brokerError: 'The broker list is unavailable; using the built-in list.',
    csvTitle: 'Broker CSV import', csvPick: 'Choose CSV', dryRun: 'Dry run (no write)', parsing: 'Parsing...', parseFile: 'Parse file', committing: 'Submitting...', commitImport: 'Submit import',
    csvParseTitle: 'CSV parse result', parseSummary: '{records} valid, {skipped} skipped, {errors} errors.', csvDryTitle: 'CSV dry run', csvCommitTitle: 'CSV import result', dryPrefix: 'Dry run', commitPrefix: 'Written', commitSummary: '{prefix}: {inserted} inserted, {duplicate} duplicates, {failed} failed.',
    pasteTitle: 'Paste holdings', pasteHint: 'One line per holding: "name or code, shares, average cost, [date]", separated by spaces or tabs. You can paste a broker inventory table and use "Make template" to fill in costs. Use the broker average cost, which includes buy fees. Pasting the same content twice is de-duplicated; after holdings change, record trades instead.', pasteLabel: 'Paste holdings', pasteDate: 'Default open date', toTemplate: 'Make template', parseContent: 'Parse content', pasteParseTitle: 'Paste parse result', pasteParseSummary: '{records} valid, {missing} missing cost, {errors} errors.', missingCostLine: 'Missing cost: {name} {symbol} x {quantity}', pasteDryTitle: 'Paste dry run', pasteCommitTitle: 'Paste import result',
    recordsTitle: 'Transactions', typeTrade: 'Trades', typeCash: 'Cash', typeCorporate: 'Corporate actions', refreshRecords: 'Refresh', loadingRecords: 'Loading...', dateFrom: 'From date', dateTo: 'To date', filterSymbol: 'Filter by stock code', sideAll: 'All sides', directionAll: 'All directions', actionAll: 'All actions', deleteHintBlocked: 'Deleting is only available in a single-account view.',
    colDate: 'Date', colSide: 'Side', colSymbol: 'Code', colQuantity: 'Qty', colTradePrice: 'Price', colFee: 'Fees', colDirection: 'Direction', colAmount: 'Amount', colAction: 'Type', colDetail: 'Detail', remove: 'Delete', removeRow: 'Delete entry', noRecords: 'No records', noRecordsHint: 'Adjust the filters or add an entry.', pageOf: 'Page {page} / {total}', prevPage: 'Previous', nextPage: 'Next',
    deleteTradeMsg: 'Delete the {side} of {symbol} on {date} (qty {quantity}, price {price})?', deleteCashMsg: 'Delete the cash entry on {date} ({direction} {amount} {currency})?', deleteCorporateMsg: 'Delete the corporate action {action} ({symbol}) on {date}?', deleteTitle: 'Delete entry', deleteConfirm: 'Delete this entry?', deleting: 'Deleting...', confirmDelete: 'Delete', cancel: 'Cancel',
    concentrationBars: 'Holdings by weight',
  },
  'zh-TW': {
    recordEntry: '記一筆', importEntry: '匯入', more: '更多操作', rowMenu: '{symbol} 的更多操作', costMethodLabel: '成本計算', loadError: '載入失敗', retry: '重試',
    sectionPending: '待處理', pendingStopTriggered: '{symbol} 已觸發停損，虧損 {pct}', pendingStopNear: '{symbol} 接近停損，虧損 {pct}', pendingMissingPrice: '{symbol} 缺報價',
    pendingNegativeCash: '{account} 現金為負（{amount}），可能漏記入金', pendingBackfill: '補記',
    metricTotalAssets: '總資產', metricDay: '今日', metricUnrealized: '未實現', metricRealized: '已實現', metricMarketValue: '市值', metricCash: '現金', metricFunds: '基金',
    includesFunds: '含基金 {amount}', excludesFunds: '不含基金（基金資料暫時無法取得）', stocksOnly: '只計股票',
    colName: '名稱', colValue: '市值', colWeight: '佔比', colPrice: '現價／成本', colPriceOn: '現價（{date}）／成本', colPnl: '損益', colAi: 'AI', costPrefix: '成本',
    sortBy: '持股排序', sortValue: '市值', sortPnl: '損益', sortReturn: '報酬', sortName: '名稱', groupSummary: '{label}（{count} 檔）', viewAlert: '設定警報',
    analyzeInAccount: '分析（{account}）', analysisSubmitted: '已送出 {symbol} 分析任務：{taskId}',
    marketTw: '台股', marketUs: '美股', marketCn: 'A 股', marketHk: '港股', marketJp: '日股', marketKr: '韓股', accountExposure: '帳戶佔比',
    entryTitle: '記一筆', importTitle: '匯入持股', entryAccount: '帳戶', entryTrade: '交易', entryCash: '資金', entryCorporate: '公司行動', writeNeedsAccount: '請先建立帳戶。',
    symbolPlaceholder: '股票代號（例如 2330.TW）', symbolPlaceholderShort: '股票代號', buy: '買進', sell: '賣出', quantityRequired: '數量（必填）', priceRequired: '成交價（必填）', feeOptional: '手續費（選填）', taxOptional: '交易稅（選填）', feeHint: '手續費和交易稅可留空，會以 0 計算。', submitTrade: '送出交易',
    cashIn: '流入', cashOut: '流出', amount: '金額', currencyOptional: '幣別（選填，預設 {currency}）', accountBase: '帳戶基準幣', submitCash: '送出資金紀錄',
    actionCashDividend: '現金股利', actionSplit: '股票分割調整', dividendPerShare: '每股股利', splitRatio: '分割比例', submitCorporate: '送出公司行動',
    createTitle: '新建帳戶', createAfter: '建立後自動切換到該帳戶', createFail: '建立帳戶失敗', createOk: '建立帳戶成功', createOkMessage: '帳戶建立成功，已自動切換到該帳戶。', createNameEmpty: '帳戶名稱不能為空。', createFailRetry: '建立帳戶失敗，請稍後再試。',
    accountNamePlaceholder: '帳戶名稱（必填）', brokerPlaceholder: '券商（選填，例如 國泰）', basePlaceholder: '基準幣（例如 TWD/USD）', creating: '建立中...', createSubmit: '建立帳戶',
    marketOptionTw: '市場：台股（tw）', marketOptionUs: '市場：美股（us）', marketOptionCn: '市場：A 股（cn）', marketOptionHk: '市場：港股（hk）', marketOptionJp: '市場：日股（jp）', marketOptionKr: '市場：韓股（kr）',
    brokerEmpty: '券商清單回傳空白，改用內建清單。', brokerError: '券商清單無法取得，改用內建清單。',
    csvTitle: '券商 CSV 匯入', csvPick: '選擇 CSV', dryRun: '僅試算（不寫入）', parsing: '解析中...', parseFile: '解析檔案', committing: '送出中...', commitImport: '送出匯入',
    csvParseTitle: 'CSV 解析結果', parseSummary: '有效 {records} 筆，略過 {skipped} 筆，錯誤 {errors} 筆。', csvDryTitle: 'CSV 試算結果', csvCommitTitle: 'CSV 送出結果', dryPrefix: '試算檢查', commitPrefix: '實際寫入', commitSummary: '{prefix}：寫入 {inserted} 筆，重複 {duplicate} 筆，失敗 {failed} 筆。',
    pasteTitle: '貼上持股匯入', pasteHint: '每行「名稱或代號 股數 平均成本 [日期]」，以空白或 Tab 分隔；也可直接貼券商庫存表，再用「轉成待填範本」補成本。平均成本請填券商的成本均價（已含買進手續費）。重複貼上同一份內容會去重，持股變動後請改記交易。', pasteLabel: '貼上持股', pasteDate: '預設建倉日期', toTemplate: '轉成待填範本', parseContent: '解析內容', pasteParseTitle: '貼上解析結果', pasteParseSummary: '有效 {records} 筆，缺成本 {missing} 筆，錯誤 {errors} 筆。', missingCostLine: '缺成本：{name} {symbol} × {quantity}', pasteDryTitle: '貼上試算結果', pasteCommitTitle: '貼上送出結果',
    recordsTitle: '交易紀錄', typeTrade: '交易', typeCash: '資金', typeCorporate: '公司行動', refreshRecords: '重新整理紀錄', loadingRecords: '載入中...', dateFrom: '起始日期', dateTo: '結束日期', filterSymbol: '依股票代號篩選', sideAll: '全部買賣方向', directionAll: '全部資金方向', actionAll: '全部公司行動', deleteHintBlocked: '刪除只在單一帳戶檢視可用，請先切到該帳戶。',
    colDate: '日期', colSide: '方向', colSymbol: '代號', colQuantity: '數量', colTradePrice: '價格', colFee: '費用', colDirection: '方向', colAmount: '金額', colAction: '類型', colDetail: '內容', remove: '刪除', removeRow: '刪除這筆', noRecords: '尚無紀錄', noRecordsHint: '調整篩選條件或先記一筆。', pageOf: '第 {page} / {total} 頁', prevPage: '上一頁', nextPage: '下一頁',
    deleteTradeMsg: '確認刪除 {date} 的{side}紀錄 {symbol}（數量 {quantity}，價格 {price}）嗎？', deleteCashMsg: '確認刪除 {date} 的資金紀錄（{direction} {amount} {currency}）嗎？', deleteCorporateMsg: '確認刪除 {date} 的公司行動 {action}（{symbol}）嗎？', deleteTitle: '刪除錯誤紀錄', deleteConfirm: '確認刪除這筆紀錄嗎？', deleting: '刪除中...', confirmDelete: '確認刪除', cancel: '取消',
    concentrationBars: '持股佔比排行',
  },
};

export const SETTINGS_PANEL_ERROR_TEXT: Record<UiLanguage, {
  loadFailedSuffix: string;
  runtimeErrorMessage: string;
  defaultDiagnosticHint: string;
  errorSummaryPrefix: string;
}> = {
  zh: {
    loadFailedSuffix: '加载失败',
    runtimeErrorMessage: '该设置区域发生前端运行时异常，页面其他设置仍可继续使用。',
    defaultDiagnosticHint: '请补充 release 版本、运行环境和触发入口，便于定位问题。',
    errorSummaryPrefix: '错误摘要：',
  },
  en: {
    loadFailedSuffix: ' failed to load',
    runtimeErrorMessage: 'This settings area hit a frontend runtime error. Other settings remain usable.',
    defaultDiagnosticHint: 'Provide the release version, runtime environment, and trigger path to help diagnose the issue.',
    errorSummaryPrefix: 'Error summary: ',
  },
  'zh-TW': {
    loadFailedSuffix: '載入失敗',
    runtimeErrorMessage: '這個設定區塊發生前端執行錯誤，頁面其他設定仍可繼續使用。',
    defaultDiagnosticHint: '請補充 release 版本、執行環境與觸發入口，方便定位問題。',
    errorSummaryPrefix: '錯誤摘要：',
  },
};
