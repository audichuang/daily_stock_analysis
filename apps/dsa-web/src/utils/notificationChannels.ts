import type { NotificationTestChannel, SystemConfigItem } from '../types/systemConfig';
import type { UiTextKey } from '../i18n/uiText';

export interface NotificationChannelSpec {
  id: NotificationTestChannel;
  labelKey: UiTextKey;
  /** 任一有值就算這個管道已設定。 */
  credentialKeys: string[];
  /** 預設展開的欄位。 */
  primaryKeys: string[];
  /** 收在「進階」裡的欄位。 */
  advancedKeys: string[];
}

// 依使用頻率排序：Telegram 是本 fork 的主要通知管道，排第一。
export const NOTIFICATION_CHANNEL_SPECS: NotificationChannelSpec[] = [
  {
    id: 'telegram',
    labelKey: 'settings.channelTelegram',
    credentialKeys: ['TELEGRAM_BOT_TOKEN'],
    primaryKeys: ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'],
    advancedKeys: ['TELEGRAM_MESSAGE_THREAD_ID'],
  },
  {
    id: 'custom',
    labelKey: 'settings.channelCustom',
    credentialKeys: ['CUSTOM_WEBHOOK_URLS'],
    primaryKeys: ['CUSTOM_WEBHOOK_URLS'],
    advancedKeys: ['CUSTOM_WEBHOOK_BEARER_TOKEN', 'CUSTOM_WEBHOOK_BODY_TEMPLATE', 'WEBHOOK_VERIFY_SSL'],
  },
  {
    id: 'email',
    labelKey: 'settings.channelEmail',
    credentialKeys: ['EMAIL_SENDER'],
    primaryKeys: ['EMAIL_SENDER', 'EMAIL_PASSWORD', 'EMAIL_RECEIVERS'],
    advancedKeys: ['MERGE_EMAIL_NOTIFICATION'],
  },
  {
    id: 'discord',
    labelKey: 'settings.channelDiscord',
    credentialKeys: ['DISCORD_WEBHOOK_URL', 'DISCORD_BOT_TOKEN'],
    primaryKeys: ['DISCORD_WEBHOOK_URL'],
    advancedKeys: ['DISCORD_BOT_TOKEN', 'DISCORD_MAIN_CHANNEL_ID', 'DISCORD_INTERACTIONS_PUBLIC_KEY'],
  },
  {
    id: 'slack',
    labelKey: 'settings.channelSlack',
    credentialKeys: ['SLACK_WEBHOOK_URL', 'SLACK_BOT_TOKEN'],
    primaryKeys: ['SLACK_WEBHOOK_URL'],
    advancedKeys: ['SLACK_BOT_TOKEN', 'SLACK_CHANNEL_ID'],
  },
  {
    id: 'ntfy',
    labelKey: 'settings.channelNtfy',
    credentialKeys: ['NTFY_URL'],
    primaryKeys: ['NTFY_URL'],
    advancedKeys: ['NTFY_TOKEN'],
  },
  {
    id: 'gotify',
    labelKey: 'settings.channelGotify',
    credentialKeys: ['GOTIFY_URL'],
    primaryKeys: ['GOTIFY_URL', 'GOTIFY_TOKEN'],
    advancedKeys: [],
  },
  {
    id: 'pushover',
    labelKey: 'settings.channelPushover',
    credentialKeys: ['PUSHOVER_USER_KEY'],
    primaryKeys: ['PUSHOVER_USER_KEY', 'PUSHOVER_API_TOKEN'],
    advancedKeys: [],
  },
  {
    id: 'pushplus',
    labelKey: 'settings.channelPushplus',
    credentialKeys: ['PUSHPLUS_TOKEN'],
    primaryKeys: ['PUSHPLUS_TOKEN'],
    advancedKeys: ['PUSHPLUS_TOPIC'],
  },
  {
    id: 'serverchan3',
    labelKey: 'settings.channelServerchan3',
    credentialKeys: ['SERVERCHAN3_SENDKEY'],
    primaryKeys: ['SERVERCHAN3_SENDKEY'],
    advancedKeys: [],
  },
  {
    id: 'wechat',
    labelKey: 'settings.channelWechat',
    credentialKeys: ['WECHAT_WEBHOOK_URL'],
    primaryKeys: ['WECHAT_WEBHOOK_URL'],
    advancedKeys: [],
  },
  {
    id: 'feishu',
    labelKey: 'settings.channelFeishu',
    credentialKeys: ['FEISHU_WEBHOOK_URL', 'FEISHU_APP_ID'],
    primaryKeys: ['FEISHU_WEBHOOK_URL'],
    advancedKeys: [
      'FEISHU_WEBHOOK_SECRET',
      'FEISHU_WEBHOOK_KEYWORD',
      'FEISHU_APP_ID',
      'FEISHU_APP_SECRET',
      'FEISHU_STREAM_ENABLED',
      'FEISHU_CHAT_ID',
      'FEISHU_RECEIVE_ID_TYPE',
      'FEISHU_DOMAIN',
    ],
  },
  {
    id: 'dingtalk',
    labelKey: 'settings.channelDingtalk',
    credentialKeys: ['DINGTALK_WEBHOOK_URL', 'DINGTALK_APP_KEY'],
    primaryKeys: ['DINGTALK_WEBHOOK_URL'],
    advancedKeys: ['DINGTALK_SECRET', 'DINGTALK_APP_KEY', 'DINGTALK_APP_SECRET', 'DINGTALK_STREAM_ENABLED'],
  },
  {
    id: 'astrbot',
    labelKey: 'settings.channelAstrbot',
    credentialKeys: ['ASTRBOT_URL'],
    primaryKeys: ['ASTRBOT_URL', 'ASTRBOT_TOKEN'],
    advancedKeys: [],
  },
];

export interface NotificationChannelGroup {
  spec: NotificationChannelSpec;
  primaryItems: SystemConfigItem[];
  advancedItems: SystemConfigItem[];
  isConfigured: boolean;
}

export interface NotificationGrouping {
  channels: NotificationChannelGroup[];
  /** 不屬於特定管道的通知規則（路由、靜音、報告格式）與未來新增的欄位。 */
  generalItems: SystemConfigItem[];
}

function hasValue(item: SystemConfigItem | undefined): boolean {
  return String(item?.value ?? '').trim().length > 0;
}

/** 把通知分類的欄位分到各管道；沒有任何欄位的管道不列出，查無歸屬的欄位放通用區，不會消失。 */
export function groupNotificationItems(items: SystemConfigItem[]): NotificationGrouping {
  const byKey = new Map(items.map((item) => [item.key, item]));
  const assigned = new Set<string>();
  const pick = (keys: string[]) => keys.flatMap((key) => {
    const item = byKey.get(key);
    if (!item) return [];
    assigned.add(key);
    return [item];
  });

  const channels = NOTIFICATION_CHANNEL_SPECS.flatMap((spec) => {
    const primaryItems = pick(spec.primaryKeys);
    const advancedItems = pick(spec.advancedKeys);
    if (primaryItems.length === 0 && advancedItems.length === 0) return [];
    return [{
      spec,
      primaryItems,
      advancedItems,
      isConfigured: spec.credentialKeys.some((key) => hasValue(byKey.get(key))),
    }];
  });

  return { channels, generalItems: items.filter((item) => !assigned.has(item.key)) };
}

export function countConfiguredNotificationChannels(items: SystemConfigItem[]): number {
  return groupNotificationItems(items).channels.filter((channel) => channel.isConfigured).length;
}
