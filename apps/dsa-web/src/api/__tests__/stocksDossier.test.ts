import { beforeEach, describe, expect, it, vi } from 'vitest';
import { attachParsedApiError, getParsedApiError } from '../error';
import { stocksApi } from '../stocks';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../index', () => ({ default: { get } }));

// 模擬 axios 攔截器：responseType 'text' 時錯誤 body 是字串，攔截器先用字串解析過一次
const httpError = (status: number, data: string) => {
  const err = Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, statusText: '', data },
  });
  attachParsedApiError(err);
  return err;
};

describe('stocksApi.getDossierHtml errors', () => {
  beforeEach(() => get.mockReset());

  it('parses a JSON error body so the message is the detail, not raw braces', async () => {
    get.mockRejectedValueOnce(httpError(404, '{"detail":"查無 9999.TW 的資料"}'));
    const err = await stocksApi.getDossierHtml('9999.TW').catch((e: unknown) => e);
    const message = getParsedApiError(err).message;
    expect(message).toContain('查無 9999.TW 的資料');
    expect(message).not.toContain('{');
  });

  it('keeps a non-JSON error body as-is', async () => {
    get.mockRejectedValueOnce(httpError(502, '<html>Bad Gateway</html>'));
    const err = await stocksApi.getDossierHtml('2330.TW').catch((e: unknown) => e);
    expect((err as { response: { data: unknown } }).response.data).toBe('<html>Bad Gateway</html>');
  });
});
