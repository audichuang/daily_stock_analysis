import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ParsedApiError } from '../../../api/error';
import { ApiErrorAlert } from '../ApiErrorAlert';

const longText = `Upstream request failed: ${'x'.repeat(275)}`;

function makeError(overrides: Partial<ParsedApiError> = {}): ParsedApiError {
  return {
    title: 'Request failed',
    message: 'Short message',
    rawMessage: 'Short message',
    category: 'unknown',
    ...overrides,
  };
}

describe('ApiErrorAlert', () => {
  it('clamps a long message and puts the full text in the details even when it equals rawMessage', () => {
    expect(longText).toHaveLength(300);
    const { container } = render(<ApiErrorAlert error={makeError({ message: longText, rawMessage: longText })} />);

    const messageNode = screen.getByText(longText, { selector: 'p' });
    expect(messageNode).toHaveClass('line-clamp-3');
    expect(messageNode.className).toContain('[overflow-wrap:anywhere]');

    const details = container.querySelector('details');
    expect(details).not.toBeNull();
    expect(details?.querySelector('pre')?.textContent).toBe(longText);
  });

  it('keeps short messages identical to rawMessage without details', () => {
    const { container } = render(<ApiErrorAlert error={makeError()} />);

    expect(screen.getByText('Short message', { selector: 'p' })).not.toHaveClass('line-clamp-3');
    expect(container.querySelector('details')).toBeNull();
  });

  it('gives a short message with more than three lines its full text instead of silently clamping line 4', () => {
    // Shape of a validation_failed error: message === rawMessage, ~120 chars, one header plus three issues.
    const message = [
      '请修正以下配置后重试：',
      'LLM_MODELFLARE_API_KEY：请填写此渠道的 API Key。',
      'LITELLM_FALLBACK_MODELS：请选择当前启用渠道中的模型',
      'LITELLM_MODEL：请选择一个已启用的模型',
    ].join('\n');
    expect(message.length).toBeLessThan(200);
    const { container } = render(<ApiErrorAlert error={makeError({ title: '配置需要调整', message, rawMessage: message })} />);

    const details = container.querySelector('details');
    expect(details).not.toBeNull();
    expect(details?.querySelector('pre')?.textContent).toBe(message);
  });

  it('still shows rawMessage in the details when it differs from a short message', () => {
    const { container } = render(
      <ApiErrorAlert error={makeError({ message: 'Friendly message', rawMessage: 'raw upstream body' })} />,
    );

    const pres = Array.from(container.querySelectorAll('details pre')).map((node) => node.textContent);
    expect(pres).toEqual(['raw upstream body']);
  });
});
