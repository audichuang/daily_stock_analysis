import { describe, expect, it } from 'vitest';
import { formatUiText, UI_TEXT, type UiTextKey, type UiTextParams } from '../../i18n/uiText';
import type { SetupStatusCheck } from '../../types/systemConfig';
import { getSetupCheckMessage, getSetupCheckTitle } from '../setupCheckText';

const tZhTw = (key: UiTextKey, params?: UiTextParams) => formatUiText(UI_TEXT['zh-TW'][key], params);

const baseCheck: SetupStatusCheck = {
  key: 'storage',
  title: '数据库 / 本地存储',
  category: 'system',
  required: true,
  status: 'needs_action',
  message: '后端原文',
  nextStep: null,
};

describe('getSetupCheckMessage', () => {
  it('composes the sentence from the code and camelCased params', () => {
    const message = getSetupCheckMessage(
      { ...baseCheck, messageCode: 'storage.app_db.unreachable', messageParams: { errorType: 'OperationalError' } },
      tZhTw,
    );
    expect(message).toBe('應用資料庫連線失敗（OperationalError）');
    expect(message).not.toContain('{');
  });

  it('never surfaces the backend message when the code is known', () => {
    const message = getSetupCheckMessage(
      {
        ...baseCheck,
        message: 'postgresql://user:secret@host/db',
        messageCode: 'storage.app_db.connected',
        messageParams: { backend: 'PostgreSQL' },
      },
      tZhTw,
    );
    expect(message).toBe('應用資料庫連線正常（PostgreSQL）');
  });

  it('falls back to the backend message for an unknown or missing code', () => {
    expect(getSetupCheckMessage({ ...baseCheck, messageCode: 'storage.future' }, tZhTw)).toBe('后端原文');
    expect(getSetupCheckMessage(baseCheck, tZhTw)).toBe('后端原文');
    expect(getSetupCheckMessage({ ...baseCheck, messageCode: null }, tZhTw)).toBe('后端原文');
  });
});

describe('getSetupCheckTitle', () => {
  it('maps known keys only in the zh-TW UI', () => {
    expect(getSetupCheckTitle(baseCheck, 'zh-TW')).toBe('資料庫與本機儲存');
    expect(getSetupCheckTitle(baseCheck, 'zh')).toBe('数据库 / 本地存储');
    expect(getSetupCheckTitle({ ...baseCheck, key: 'future_check', title: '后端标题' }, 'zh-TW')).toBe('后端标题');
  });
});
