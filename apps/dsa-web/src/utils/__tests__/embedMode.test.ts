import { beforeEach, describe, expect, it } from 'vitest';
import { EMBED_MODE_STORAGE_KEY, resolveEmbedMode } from '../embedMode';

describe('resolveEmbedMode', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it('is off without the parameter or a stored flag', () => {
    expect(resolveEmbedMode('', window.sessionStorage)).toBe(false);
    expect(window.sessionStorage.getItem(EMBED_MODE_STORAGE_KEY)).toBeNull();
  });

  it('persists the flag so a later navigation without the query stays embedded', () => {
    expect(resolveEmbedMode('?embed=ios', window.sessionStorage)).toBe(true);
    expect(resolveEmbedMode('', window.sessionStorage)).toBe(true);
  });

  it('does not treat other values as embedded and does not store them', () => {
    expect(resolveEmbedMode('?embed=web', window.sessionStorage)).toBe(false);
    expect(resolveEmbedMode('', window.sessionStorage)).toBe(false);
  });

  it('still honours the parameter when storage throws', () => {
    const broken = {
      getItem: () => {
        throw new Error('denied');
      },
      setItem: () => {
        throw new Error('denied');
      },
    } as unknown as Storage;
    expect(resolveEmbedMode('?embed=ios', broken)).toBe(true);
    expect(resolveEmbedMode('', broken)).toBe(false);
    expect(resolveEmbedMode('?embed=ios', null)).toBe(true);
  });
});
