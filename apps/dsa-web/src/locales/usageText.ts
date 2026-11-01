import type { UiLanguage } from '../i18n/uiText';

// 用量頁改版後新增的文案；舊的 usage.* 鍵仍在 uiText，這裡只放新版面用到的。
const zhTW = {
  input: '輸入', output: '輸出', total: '合計', calls: '呼叫', peak: '單次峰值', cost: '估算費用', model: '模型', time: '時間', type: '用途', stock: '股票',
  totalLabel: '總用量（tokens）', costLabel: '估算費用', changeToday: '較昨日同時段', changeMonth: '較上月同期', noPrevious: '上期沒有資料',
  costSubscription: '走訂閱，不計費', costUnpriced: '未設定單價', costPartial: '部分模型未定價', subscriptionNote: '另有 {tokens} tokens 走訂閱，不計費',
  conclusion: '{period}共 {calls} 次呼叫，最多用在{top}（{share}）。', conclusionPlain: '{period}共 {calls} 次呼叫。',
  metricCalls: '呼叫次數', metricInOut: '輸入／輸出', metricCache: '快取命中',
  dailyTitle: '每日用量', dailyHint: '點長條只看當天明細', dayBar: '{date} 合計 {total}，輸入 {input}，輸出 {output}',
  shareTitle: '用途佔比', shareDetail: '{calls} 次 · {tokens} tokens', modelTitle: '模型',
  recordsTitle: '呼叫明細', recordsCount: '共 {count} 筆', noRecords: '沒有符合條件的呼叫', loadMore: '載入更多',
  filterType: '用途', filterAll: '全部用途', filterSort: '排序', sortNewest: '最新優先', sortOldest: '最舊優先', sortTokens: '用量最大',
  dayChip: '只看 {date}', clearDay: '看全部日期', rounds: '{count} 輪', expandRounds: '展開 {count} 輪', collapseRounds: '收起 {count} 輪',
  callTypes: { agent_analysis: 'Agent 分析', financial_commentary: '財報短評' } as Record<string, string>,
  callTypeOther: '其他（{type}）', callTypeOtherBare: '其他', claudeModel: 'Claude Sonnet 5.5',
  daySummary: '{date}：輸入 {input}／輸出 {output}', cacheUnreported: '模型供應商沒有回報快取用量', loading: '載入用量中…',
};

export type UsageText = typeof zhTW;

export const USAGE_TEXT: Record<UiLanguage, UsageText> = {
  'zh-TW': zhTW,
  zh: {
    input: '输入', output: '输出', total: '合计', calls: '调用', peak: '单次峰值', cost: '估算费用', model: '模型', time: '时间', type: '用途', stock: '股票',
    totalLabel: '总用量（tokens）', costLabel: '估算费用', changeToday: '较昨日同时段', changeMonth: '较上月同期', noPrevious: '上期没有数据',
    costSubscription: '走订阅，不计费', costUnpriced: '未设置单价', costPartial: '部分模型未定价', subscriptionNote: '另有 {tokens} tokens 走订阅，不计费',
    conclusion: '{period}共 {calls} 次调用，最多用在{top}（{share}）。', conclusionPlain: '{period}共 {calls} 次调用。',
    metricCalls: '调用次数', metricInOut: '输入／输出', metricCache: '缓存命中',
    dailyTitle: '每日用量', dailyHint: '点长条只看当天明细', dayBar: '{date} 合计 {total}，输入 {input}，输出 {output}',
    shareTitle: '用途占比', shareDetail: '{calls} 次 · {tokens} tokens', modelTitle: '模型',
    recordsTitle: '调用明细', recordsCount: '共 {count} 条', noRecords: '没有符合条件的调用', loadMore: '加载更多',
    filterType: '用途', filterAll: '全部用途', filterSort: '排序', sortNewest: '最新优先', sortOldest: '最旧优先', sortTokens: '用量最大',
    dayChip: '只看 {date}', clearDay: '看全部日期', rounds: '{count} 轮', expandRounds: '展开 {count} 轮', collapseRounds: '收起 {count} 轮',
    callTypes: { agent_analysis: 'Agent 分析', financial_commentary: '财报短评' },
    callTypeOther: '其他（{type}）', callTypeOtherBare: '其他', claudeModel: 'Claude Sonnet 5.5',
    daySummary: '{date}：输入 {input}／输出 {output}', cacheUnreported: '模型供应商没有回报缓存用量', loading: '加载用量中…',
  },
  en: {
    input: 'Input', output: 'Output', total: 'Total', calls: 'Calls', peak: 'Peak call', cost: 'Est. cost', model: 'Model', time: 'Time', type: 'Purpose', stock: 'Stock',
    totalLabel: 'Total usage (tokens)', costLabel: 'Est. cost', changeToday: 'vs. same time yesterday', changeMonth: 'vs. same point last month', noPrevious: 'No data last period',
    costSubscription: 'Subscription, not billed', costUnpriced: 'No price set', costPartial: 'Some models unpriced', subscriptionNote: '{tokens} more tokens on subscription, not billed',
    conclusion: '{period}: {calls} calls, mostly {top} ({share}).', conclusionPlain: '{period}: {calls} calls.',
    metricCalls: 'Calls', metricInOut: 'Input / output', metricCache: 'Cache hit',
    dailyTitle: 'Daily usage', dailyHint: 'Click a bar to see that day', dayBar: '{date} total {total}, input {input}, output {output}',
    shareTitle: 'By purpose', shareDetail: '{calls} calls · {tokens} tokens', modelTitle: 'Models',
    recordsTitle: 'Call records', recordsCount: '{count} records', noRecords: 'No matching calls', loadMore: 'Load more',
    filterType: 'Purpose', filterAll: 'All purposes', filterSort: 'Sort', sortNewest: 'Newest first', sortOldest: 'Oldest first', sortTokens: 'Largest first',
    dayChip: 'Only {date}', clearDay: 'All dates', rounds: '{count} rounds', expandRounds: 'Expand {count} rounds', collapseRounds: 'Collapse {count} rounds',
    callTypes: { agent_analysis: 'Agent analysis', financial_commentary: 'Financial commentary' },
    callTypeOther: 'Other ({type})', callTypeOtherBare: 'Other', claudeModel: 'Claude Sonnet 5.5',
    daySummary: '{date}: input {input} / output {output}', cacheUnreported: 'The model provider did not report cache usage', loading: 'Loading usage…',
  },
};
