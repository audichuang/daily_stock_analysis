import { describe, expect, it } from 'vitest';
import { prettyModelName } from '../usageSummary';

describe('prettyModelName', () => {
  it('turns current claude ids into product names', () => {
    expect(prettyModelName('claude-sonnet-5-5')).toBe('Claude Sonnet 5.5');
    expect(prettyModelName('claude-opus-4-7-20260101')).toBe('Claude Opus 4.7');
    expect(prettyModelName('CLAUDE-HAIKU-4-5')).toBe('Claude Haiku 4.5');
  });

  it('does not read a release date as a minor version', () => {
    expect(prettyModelName('claude-sonnet-4-20250514')).toBe('Claude Sonnet 4');
  });

  it('handles the legacy version-first naming', () => {
    expect(prettyModelName('claude-3-5-sonnet-20241022')).toBe('Claude Sonnet 3.5');
    expect(prettyModelName('claude-3-opus-20240229')).toBe('Claude Opus 3');
  });

  it('returns anything else unchanged', () => {
    expect(prettyModelName('gpt-4o')).toBe('gpt-4o');
    expect(prettyModelName('claude_code_cli')).toBe('claude_code_cli');
    expect(prettyModelName('claude-sonnet-5-5-preview')).toBe('claude-sonnet-5-5-preview');
    expect(prettyModelName('anthropic/claude-sonnet-5-5')).toBe('anthropic/claude-sonnet-5-5');
  });
});
