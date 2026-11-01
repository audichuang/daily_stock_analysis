import { useState } from 'react';
import type React from 'react';
import { ChevronDown } from 'lucide-react';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { ConfigValidationIssue, SystemConfigItem } from '../../types/systemConfig';
import { groupNotificationItems, type NotificationChannelGroup } from '../../utils/notificationChannels';
import { NotificationTestPanel } from './NotificationTestPanel';
import { SettingsField } from './SettingsField';

interface NotificationChannelListProps {
  items: SystemConfigItem[];
  maskToken: string;
  disabled?: boolean;
  issueByKey: Record<string, ConfigValidationIssue[]>;
  onChange: (key: string, value: string) => void;
}

function hasIssues(items: SystemConfigItem[], issueByKey: Record<string, ConfigValidationIssue[]>): boolean {
  return items.some((item) => (issueByKey[item.key] || []).length > 0);
}

const FieldRows: React.FC<{
  items: SystemConfigItem[];
  disabled: boolean;
  issueByKey: Record<string, ConfigValidationIssue[]>;
  onChange: (key: string, value: string) => void;
}> = ({ items, disabled, issueByKey, onChange }) => (
  <div className="divide-y divide-[var(--settings-border-soft)]">
    {items.map((item) => (
      <SettingsField
        key={item.key}
        item={item}
        value={item.value}
        disabled={disabled}
        onChange={onChange}
        issues={issueByKey[item.key] || []}
      />
    ))}
  </div>
);

const ChannelCard: React.FC<{
  channel: NotificationChannelGroup;
  allItems: SystemConfigItem[];
  maskToken: string;
  disabled: boolean;
  issueByKey: Record<string, ConfigValidationIssue[]>;
  onChange: (key: string, value: string) => void;
}> = ({ channel, allItems, maskToken, disabled, issueByKey, onChange }) => {
  const { t } = useUiLanguage();
  const { spec, primaryItems, advancedItems, isConfigured } = channel;
  // Telegram 與已設定的管道預設展開；有錯誤的欄位不能藏在收合裡。
  const [isOpen, setIsOpen] = useState(spec.id === 'telegram' || isConfigured);
  const hasAnyIssue = hasIssues([...primaryItems, ...advancedItems], issueByKey);
  const hasAdvancedIssue = hasIssues(advancedItems, issueByKey);

  return (
    <details
      open={isOpen || hasAnyIssue}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
      data-testid={`notification-channel-${spec.id}`}
      className="group/channel min-w-0 rounded-lg border settings-border bg-card/90 shadow-soft-card"
    >
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">{t(spec.labelKey)}</span>
        <span className="shrink-0 text-xs text-muted-text">
          {isConfigured ? t('settings.setupStatusConfigured') : t('settings.categoryStatusNotSet')}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-text transition-transform group-open/channel:rotate-180" aria-hidden="true" />
      </summary>
      <div className="border-t border-[var(--settings-border-soft)]">
        <FieldRows items={primaryItems} disabled={disabled} issueByKey={issueByKey} onChange={onChange} />
        {advancedItems.length ? (
          <details open={hasAdvancedIssue || undefined} className="border-t border-[var(--settings-border-soft)]">
            <summary className="cursor-pointer px-4 py-3 text-xs font-medium text-secondary-text">
              {t('settings.channelAdvanced')}
            </summary>
            <FieldRows items={advancedItems} disabled={disabled} issueByKey={issueByKey} onChange={onChange} />
          </details>
        ) : null}
        <div className="border-t border-[var(--settings-border-soft)] px-4 py-3">
          <NotificationTestPanel
            items={allItems.map((item) => ({ key: item.key, value: String(item.value ?? '') }))}
            maskToken={maskToken}
            disabled={disabled}
            fixedChannel={spec.id}
          />
        </div>
      </div>
    </details>
  );
};

/** 通知設定改以管道為單位：每張卡片放該管道的欄位與測試，通用規則收在最下方。 */
export const NotificationChannelList: React.FC<NotificationChannelListProps> = ({
  items,
  maskToken,
  disabled = false,
  issueByKey,
  onChange,
}) => {
  const { t } = useUiLanguage();
  const { channels, generalItems } = groupNotificationItems(items);

  return (
    <div className="space-y-3">
      {channels.map((channel) => (
        <ChannelCard
          key={channel.spec.id}
          channel={channel}
          allItems={items}
          maskToken={maskToken}
          disabled={disabled}
          issueByKey={issueByKey}
          onChange={onChange}
        />
      ))}
      {generalItems.length ? (
        <details
          open={hasIssues(generalItems, issueByKey) || undefined}
          data-testid="notification-general-settings"
          className="min-w-0 rounded-lg border settings-border bg-card/90 shadow-soft-card"
        >
          <summary className="flex min-h-11 cursor-pointer items-center px-4 py-3 text-sm font-semibold text-foreground">
            {t('settings.channelGeneral')}
          </summary>
          <div className="border-t border-[var(--settings-border-soft)]">
            <FieldRows items={generalItems} disabled={disabled} issueByKey={issueByKey} onChange={onChange} />
          </div>
        </details>
      ) : null}
    </div>
  );
};
