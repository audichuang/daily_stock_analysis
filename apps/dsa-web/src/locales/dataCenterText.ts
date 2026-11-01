import type { UiLanguage } from '../i18n/uiText';

// 資料中心的文案獨立成檔：狀態、資料集、警告碼都是後端的穩定碼，三語集中對照。
const zhTW = {
  status: { ok: '正常', degraded: '走備援', partial: '部分可用', stale: '資料過期', unavailable: '無法使用', unconfigured: '未設定', unknown: '尚未檢查', cooldown: '冷卻中', unsupported: '不支援' } as Record<string, string>,
  datasets: { 'quote.realtime': '即時報價', 'kline.daily': '日 K', 'index.daily': '指數日線', 'market.overview': '大盤概況', 'financial.snapshot': '財務資料', 'news.events': '新聞事件', 'strategy.screening': '選股', 'alert.monitor': '警報監控', 'portfolio.account': '持股帳本' } as Record<string, string>,
  markets: { tw: '台股', us: '美股', hk: '港股', cn: 'A 股', jp: '日股', kr: '韓股', 'us.index': '美股指數', 'cn.index.exchange': 'A 股指數（交易所）', 'cn.index.csi': 'A 股指數（中證）', 'cn.exchange': 'A 股指數（交易所）', 'cn.csi': 'A 股指數（中證）' } as Record<string, string>,
  scenarios: { 'tw.realtime': '台股即時報價', 'us.realtime': '美股即時報價', 'hk.realtime': '港股即時報價', 'cn.realtime': 'A 股即時報價', 'daily.generic': '日 K', 'cn.index.daily': 'A 股指數日線', 'market.overview': '大盤概況', 'screening.snapshot': '選股快照', 'news.events': '新聞事件' } as Record<string, string>,
  reasons: { realtime_quote_disabled: '服務沒有開啟即時報價', fundamental_pipeline_disabled: '服務沒有開啟財務資料', screening_disabled: '服務沒有開啟選股', screening_engine_unavailable: '選股引擎無法使用', agent_event_monitor_disabled: '服務沒有開啟警報監控', agent_event_monitor_not_running: '警報監控沒有在跑' } as Record<string, string>,
  warnings: { runtime_probe_not_performed: '尚未實際探測來源', provider_not_initialized: '來源沒有初始化', provider_marked_unavailable: '來源標記為無法使用', priority_empty: '沒有設定來源順序', request_available_priority_empty: '目前沒有可用來源', tickflow_configured_but_not_in_realtime_priority: 'TickFlow 已設定，但不在即時報價順序內' } as Record<string, string>,
  bannerOk: '台股、美股資料正常', bannerDown: '台股或美股有資料無法使用', bannerStale: '台股或美股資料沒有更新', bannerAttention: '台股或美股需要留意', bannerUnchecked: '台股或美股尚有資料未檢查', bannerEmpty: '沒有台股、美股的資料狀態',
  bannerDataDate: '{label} 資料到 {date}', bannerChecked: '檢查時間 {time}', stoppedAt: '{label} 停在 {date}，最新應為 {expected}', isDown: '{label} 無法使用', isOff: '{label} 未啟用', isUnchecked: '{label} 尚未檢查', viaFallback: '{label} 走備援',
  countOk: '正常', countUnchecked: '尚未檢查', countOff: '未啟用', countIssue: '異常', countNote: '共 {total} 項（台股、美股與系統）', uncheckedNote: '{count} 項尚未被呼叫過，休市或首次啟動時屬正常', andMore: '等 {count} 項',
  tableTitle: '市場資料狀態', colData: '資料', colStatus: '狀態', colSource: '來源', colDate: '資料日期', colNote: '備援與說明', otherMarkets: '其他市場（{count}）', systemTitle: '其他資料',
  dateBehind: '{date}（應為 {expected}）', realtimeSuccess: '即時來源最近成功 {time}', skipped: '已跳過 {sources}，目前走 {source}', skippedNoSource: '已跳過 {sources}，沒有可用來源',
  providersTitle: '來源明細（{count}）', providerUsable: '可用', providerUnconfigured: '未設定', providerAttention: '需留意', providerMarkets: '市場：{markets}', providerDatasets: '資料：{datasets}',
  prioritiesTitle: '備援順序', priorityTw: '台股', priorityUs: '美股', priorityOther: '其他',
  hintsTitle: '有 {count} 則提示', hintUnknown: '另有 {count} 則未分類提示，見技術細節', technicalTitle: '技術細節', technicalEmpty: '沒有警告碼或錯誤',
  warnSourceStatus: '來源 {source}：{status}', warnUnknownSource: '順序內有不認得的來源 {source}',
};

export type DataCenterText = typeof zhTW;

export const DATA_CENTER_TEXT: Record<UiLanguage, DataCenterText> = {
  'zh-TW': zhTW,
  zh: {
    status: { ok: '正常', degraded: '走备援', partial: '部分可用', stale: '数据过期', unavailable: '无法使用', unconfigured: '未设置', unknown: '尚未检查', cooldown: '冷却中', unsupported: '不支持' },
    datasets: { 'quote.realtime': '实时行情', 'kline.daily': '日 K', 'index.daily': '指数日线', 'market.overview': '大盘概况', 'financial.snapshot': '财务数据', 'news.events': '新闻事件', 'strategy.screening': '选股', 'alert.monitor': '警报监控', 'portfolio.account': '持仓账本' },
    markets: { tw: '台股', us: '美股', hk: '港股', cn: 'A 股', jp: '日股', kr: '韩股', 'us.index': '美股指数', 'cn.index.exchange': 'A 股指数（交易所）', 'cn.index.csi': 'A 股指数（中证）', 'cn.exchange': 'A 股指数（交易所）', 'cn.csi': 'A 股指数（中证）' },
    scenarios: { 'tw.realtime': '台股实时行情', 'us.realtime': '美股实时行情', 'hk.realtime': '港股实时行情', 'cn.realtime': 'A 股实时行情', 'daily.generic': '日 K', 'cn.index.daily': 'A 股指数日线', 'market.overview': '大盘概况', 'screening.snapshot': '选股快照', 'news.events': '新闻事件' },
    reasons: { realtime_quote_disabled: '服务没有开启实时行情', fundamental_pipeline_disabled: '服务没有开启财务数据', screening_disabled: '服务没有开启选股', screening_engine_unavailable: '选股引擎无法使用', agent_event_monitor_disabled: '服务没有开启警报监控', agent_event_monitor_not_running: '警报监控没有在运行' },
    warnings: { runtime_probe_not_performed: '尚未实际探测来源', provider_not_initialized: '来源没有初始化', provider_marked_unavailable: '来源标记为无法使用', priority_empty: '没有设置来源顺序', request_available_priority_empty: '目前没有可用来源', tickflow_configured_but_not_in_realtime_priority: 'TickFlow 已设置，但不在实时行情顺序内' },
    bannerOk: '台股、美股数据正常', bannerDown: '台股或美股有数据无法使用', bannerStale: '台股或美股数据没有更新', bannerAttention: '台股或美股需要留意', bannerUnchecked: '台股或美股尚有数据未检查', bannerEmpty: '没有台股、美股的数据状态',
    bannerDataDate: '{label} 数据到 {date}', bannerChecked: '检查时间 {time}', stoppedAt: '{label} 停在 {date}，最新应为 {expected}', isDown: '{label} 无法使用', isOff: '{label} 未启用', isUnchecked: '{label} 尚未检查', viaFallback: '{label} 走备援',
    countOk: '正常', countUnchecked: '尚未检查', countOff: '未启用', countIssue: '异常', countNote: '共 {total} 项（台股、美股与系统）', uncheckedNote: '{count} 项尚未被调用过，休市或首次启动时属正常', andMore: '等 {count} 项',
    tableTitle: '市场数据状态', colData: '数据', colStatus: '状态', colSource: '来源', colDate: '数据日期', colNote: '备援与说明', otherMarkets: '其他市场（{count}）', systemTitle: '其他数据',
    dateBehind: '{date}（应为 {expected}）', realtimeSuccess: '实时来源最近成功 {time}', skipped: '已跳过 {sources}，目前走 {source}', skippedNoSource: '已跳过 {sources}，没有可用来源',
    providersTitle: '来源明细（{count}）', providerUsable: '可用', providerUnconfigured: '未设置', providerAttention: '需留意', providerMarkets: '市场：{markets}', providerDatasets: '数据：{datasets}',
    prioritiesTitle: '备援顺序', priorityTw: '台股', priorityUs: '美股', priorityOther: '其他',
    hintsTitle: '有 {count} 条提示', hintUnknown: '另有 {count} 条未分类提示，见技术细节', technicalTitle: '技术细节', technicalEmpty: '没有警告码或错误',
    warnSourceStatus: '来源 {source}：{status}', warnUnknownSource: '顺序内有不认识的来源 {source}',
  },
  en: {
    status: { ok: 'OK', degraded: 'On fallback', partial: 'Partial', stale: 'Stale', unavailable: 'Unavailable', unconfigured: 'Not configured', unknown: 'Not checked', cooldown: 'Cooling down', unsupported: 'Unsupported' },
    datasets: { 'quote.realtime': 'Realtime quotes', 'kline.daily': 'Daily bars', 'index.daily': 'Index daily', 'market.overview': 'Market overview', 'financial.snapshot': 'Financials', 'news.events': 'News events', 'strategy.screening': 'Screening', 'alert.monitor': 'Alert monitor', 'portfolio.account': 'Portfolio ledger' },
    markets: { tw: 'Taiwan', us: 'US', hk: 'Hong Kong', cn: 'A-shares', jp: 'Japan', kr: 'Korea', 'us.index': 'US indices', 'cn.index.exchange': 'A-share indices (exchange)', 'cn.index.csi': 'A-share indices (CSI)', 'cn.exchange': 'A-share indices (exchange)', 'cn.csi': 'A-share indices (CSI)' },
    scenarios: { 'tw.realtime': 'Taiwan realtime', 'us.realtime': 'US realtime', 'hk.realtime': 'Hong Kong realtime', 'cn.realtime': 'A-share realtime', 'daily.generic': 'Daily bars', 'cn.index.daily': 'A-share index daily', 'market.overview': 'Market overview', 'screening.snapshot': 'Screening snapshot', 'news.events': 'News events' },
    reasons: { realtime_quote_disabled: 'Realtime quotes are turned off', fundamental_pipeline_disabled: 'Financials are turned off', screening_disabled: 'Screening is turned off', screening_engine_unavailable: 'Screening engine is unavailable', agent_event_monitor_disabled: 'Alert monitor is turned off', agent_event_monitor_not_running: 'Alert monitor is not running' },
    warnings: { runtime_probe_not_performed: 'Source has not been probed', provider_not_initialized: 'Source was not initialized', provider_marked_unavailable: 'Source is marked unavailable', priority_empty: 'No source order configured', request_available_priority_empty: 'No source is available', tickflow_configured_but_not_in_realtime_priority: 'TickFlow is configured but not in the realtime order' },
    bannerOk: 'Taiwan and US data are healthy', bannerDown: 'Some Taiwan or US data is unavailable', bannerStale: 'Some Taiwan or US data is out of date', bannerAttention: 'Taiwan or US data needs attention', bannerUnchecked: 'Some Taiwan or US data is not checked yet', bannerEmpty: 'No Taiwan or US data status',
    bannerDataDate: '{label} through {date}', bannerChecked: 'Checked {time}', stoppedAt: '{label} stopped at {date}, expected {expected}', isDown: '{label} unavailable', isOff: '{label} turned off', isUnchecked: '{label} not checked', viaFallback: '{label} on fallback',
    countOk: 'OK', countUnchecked: 'Not checked', countOff: 'Off', countIssue: 'Issues', countNote: '{total} items (Taiwan, US and system)', uncheckedNote: '{count} items have not been called yet; normal on market holidays or right after startup', andMore: 'and {count} in total',
    tableTitle: 'Market data status', colData: 'Data', colStatus: 'Status', colSource: 'Source', colDate: 'Data date', colNote: 'Fallback and notes', otherMarkets: 'Other markets ({count})', systemTitle: 'Other data',
    dateBehind: '{date} (expected {expected})', realtimeSuccess: 'Realtime source last succeeded {time}', skipped: 'Skipped {sources}, using {source}', skippedNoSource: 'Skipped {sources}, no source available',
    providersTitle: 'Sources ({count})', providerUsable: 'Usable', providerUnconfigured: 'Not configured', providerAttention: 'Needs attention', providerMarkets: 'Markets: {markets}', providerDatasets: 'Data: {datasets}',
    prioritiesTitle: 'Fallback order', priorityTw: 'Taiwan', priorityUs: 'US', priorityOther: 'Other',
    hintsTitle: '{count} notes', hintUnknown: '{count} more unclassified notes in technical details', technicalTitle: 'Technical details', technicalEmpty: 'No warning codes or errors',
    warnSourceStatus: 'Source {source}: {status}', warnUnknownSource: 'Unknown source in the order: {source}',
  },
};
