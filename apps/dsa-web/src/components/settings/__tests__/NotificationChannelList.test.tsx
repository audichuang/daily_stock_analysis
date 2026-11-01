import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SystemConfigItem } from '../../../types/systemConfig';
import { groupNotificationItems } from '../../../utils/notificationChannels';
import { NotificationChannelList } from '../NotificationChannelList';

const testNotificationChannel = vi.hoisted(() => vi.fn());

vi.mock('../../../api/systemConfig', () => ({
  systemConfigApi: { testNotificationChannel },
}));

const item = (key: string, value = ''): SystemConfigItem => ({
  key,
  value,
  rawValueExists: Boolean(value),
  isMasked: false,
  schema: {
    key,
    title: key,
    category: 'notification',
    dataType: 'string',
    uiControl: 'text',
    isSensitive: false,
    isRequired: false,
    isEditable: true,
    options: [],
    validation: {},
    displayOrder: 1,
  },
});

const allItems = [
  item('WECHAT_WEBHOOK_URL', 'https://wechat.example/hook'),
  item('NOTIFICATION_QUIET_HOURS'),
  item('TELEGRAM_MESSAGE_THREAD_ID'),
  item('TELEGRAM_BOT_TOKEN'),
  item('TELEGRAM_CHAT_ID'),
  item('FUTURE_NEW_FIELD'),
];

const renderList = () => render(
  <NotificationChannelList
    items={allItems}
    maskToken="******"
    issueByKey={{}}
    onChange={vi.fn()}
  />,
);

describe('groupNotificationItems', () => {
  it('puts Telegram first regardless of item order', () => {
    expect(groupNotificationItems(allItems).channels[0].spec.id).toBe('telegram');
  });

  it('separates primary and advanced fields', () => {
    const telegram = groupNotificationItems(allItems).channels[0];
    expect(telegram.primaryItems.map((entry) => entry.key)).toEqual(['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']);
    expect(telegram.advancedItems.map((entry) => entry.key)).toEqual(['TELEGRAM_MESSAGE_THREAD_ID']);
  });

  it('marks a channel configured only when its credential has a value', () => {
    const { channels } = groupNotificationItems(allItems);
    expect(channels.find((c) => c.spec.id === 'telegram')?.isConfigured).toBe(false);
    expect(channels.find((c) => c.spec.id === 'wechat')?.isConfigured).toBe(true);
  });

  it('never drops a field: unknown keys go to the general group', () => {
    const { channels, generalItems } = groupNotificationItems(allItems);
    const grouped = channels.flatMap((c) => [...c.primaryItems, ...c.advancedItems]).map((entry) => entry.key);
    expect([...grouped, ...generalItems.map((entry) => entry.key)].sort()).toEqual(allItems.map((entry) => entry.key).sort());
    expect(generalItems.map((entry) => entry.key)).toEqual(['NOTIFICATION_QUIET_HOURS', 'FUTURE_NEW_FIELD']);
  });

  it('omits channels without any field', () => {
    expect(groupNotificationItems(allItems).channels.map((c) => c.spec.id)).not.toContain('slack');
  });
});

describe('NotificationChannelList', () => {
  beforeEach(() => {
    testNotificationChannel.mockReset();
    testNotificationChannel.mockResolvedValue({
      success: true,
      message: 'ok',
      errorCode: null,
      stage: 'notification_send',
      retryable: false,
      latencyMs: 5,
      attempts: [],
    });
  });

  it('renders Telegram as the first card', () => {
    const { container } = renderList();
    const firstCard = container.querySelector('[data-testid^="notification-channel-"]');
    expect(firstCard).toHaveAttribute('data-testid', 'notification-channel-telegram');
  });

  it('opens Telegram and configured channels by default', () => {
    renderList();
    expect(screen.getByTestId('notification-channel-telegram')).toHaveAttribute('open');
    expect(screen.getByTestId('notification-channel-wechat')).toHaveAttribute('open');
  });

  it('forces a channel open when one of its fields has an issue', () => {
    render(
      <NotificationChannelList
        items={[item('TELEGRAM_BOT_TOKEN'), item('SLACK_WEBHOOK_URL')]}
        maskToken="******"
        issueByKey={{ SLACK_WEBHOOK_URL: [{ key: 'SLACK_WEBHOOK_URL', code: 'invalid', message: 'bad', severity: 'error' }] }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('notification-channel-slack')).toHaveAttribute('open');
  });

  it('tests the card\'s own channel with all draft items and no channel picker', async () => {
    renderList();
    const card = screen.getByTestId('notification-channel-telegram');
    expect(within(card).queryByLabelText('渠道')).not.toBeInTheDocument();

    fireEvent.click(within(card).getByRole('button', { name: /发送测试/ }));

    await waitFor(() => expect(testNotificationChannel).toHaveBeenCalledTimes(1));
    const payload = testNotificationChannel.mock.calls[0][0] as { channel: string; items: Array<{ key: string }> };
    expect(payload.channel).toBe('telegram');
    expect(payload.items.map((entry) => entry.key)).toContain('WECHAT_WEBHOOK_URL');
  });
});
