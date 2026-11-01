import type { UiLanguage } from '../i18n/uiText';

export type StatusTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

interface StatusEntry {
  tone: StatusTone;
  zh: string;
  en: string;
  'zh-TW': string;
}

// 後端狀態碼集中在這裡轉文案與 tone，繁中對應 iOS 的 PresentationText，改一邊要同步另一邊。
const STATUS: Record<string, StatusEntry> = {
  // 資料品質
  good: { tone: 'success', zh: '良好', en: 'Good', 'zh-TW': '良好' },
  usable: { tone: 'info', zh: '可用', en: 'Usable', 'zh-TW': '可用' },
  limited: { tone: 'warning', zh: '有限', en: 'Limited', 'zh-TW': '有限' },
  poor: { tone: 'danger', zh: '不足', en: 'Poor', 'zh-TW': '不足' },
  complete: { tone: 'success', zh: '完整', en: 'Complete', 'zh-TW': '完整' },
  partial: { tone: 'warning', zh: '部分数据', en: 'Partial', 'zh-TW': '部分資料' },
  insufficient: { tone: 'warning', zh: '数据不足', en: 'Insufficient', 'zh-TW': '資料不足' },
  unknown: { tone: 'neutral', zh: '未确认', en: 'Unknown', 'zh-TW': '未確認' },
  // 資料區塊
  stale: { tone: 'warning', zh: '已过期', en: 'Stale', 'zh-TW': '已過期' },
  missing: { tone: 'warning', zh: '缺漏', en: 'Missing', 'zh-TW': '缺漏' },
  fetch_failed: { tone: 'danger', zh: '获取失败', en: 'Fetch failed', 'zh-TW': '取得失敗' },
  not_supported: { tone: 'neutral', zh: '暂不支持', en: 'Not supported', 'zh-TW': '目前不支援' },
  fallback: { tone: 'warning', zh: '使用备援来源', en: 'Fallback source', 'zh-TW': '使用備援來源' },
  estimated: { tone: 'warning', zh: '包含估计值', en: 'Estimated', 'zh-TW': '包含估計值' },
  // 任務
  pending: { tone: 'neutral', zh: '等待中', en: 'Pending', 'zh-TW': '等待中' },
  running: { tone: 'info', zh: '进行中', en: 'Running', 'zh-TW': '進行中' },
  completed: { tone: 'success', zh: '已完成', en: 'Completed', 'zh-TW': '已完成' },
  failed: { tone: 'danger', zh: '失败', en: 'Failed', 'zh-TW': '失敗' },
  cancelled: { tone: 'neutral', zh: '已取消', en: 'Cancelled', 'zh-TW': '已取消' },
  // 系統狀態
  ok: { tone: 'success', zh: '正常', en: 'OK', 'zh-TW': '正常' },
  degraded: { tone: 'warning', zh: '降级', en: 'Degraded', 'zh-TW': '降級' },
  disabled: { tone: 'neutral', zh: '已停用', en: 'Disabled', 'zh-TW': '已停用' },
  enabled: { tone: 'success', zh: '已启用', en: 'Enabled', 'zh-TW': '已啟用' },
  configured: { tone: 'success', zh: '已设置', en: 'Configured', 'zh-TW': '已設定' },
  needs_action: { tone: 'warning', zh: '需处理', en: 'Needs action', 'zh-TW': '需處理' },
};

export interface StatusPresentation {
  label: string;
  tone: StatusTone;
}

/** 未知碼保留原文並用中性灰，不要猜語意；空值回 null 由呼叫端決定要不要顯示。 */
export const getStatusPresentation = (code?: string | null, language: UiLanguage = 'zh-TW'): StatusPresentation | null => {
  const key = code?.trim();
  if (!key) return null;
  const entry = Object.prototype.hasOwnProperty.call(STATUS, key.toLowerCase()) ? STATUS[key.toLowerCase()] : undefined;
  return entry ? { label: entry[language], tone: entry.tone } : { label: key, tone: 'neutral' };
};
