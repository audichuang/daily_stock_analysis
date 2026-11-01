import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ReportMarkdownBody } from '../ReportMarkdownBody';

const whitespaceTextNodes = (element: Element) =>
  Array.from(element.childNodes).filter((node) => node.nodeType === Node.TEXT_NODE && node.textContent?.trim() === '');

describe('ReportMarkdownBody', () => {
  it('keeps a soft line break inside a tight list item as a visible break', () => {
    const { container } = render(<ReportMarkdownBody content={'- 項目一\n- 項目二\n  續行'} />);
    const second = container.querySelectorAll('li')[1];
    expect(second.querySelectorAll(':scope > br')).toHaveLength(1);
    expect(second.textContent).toBe('項目二續行');
  });

  it.each([
    ['two trailing spaces', '- one  \n  two'],
    ['a trailing backslash', '- one\\\n  two'],
  ])('keeps a hard line break written with %s as a single break', (_label, content) => {
    const { container } = render(<ReportMarkdownBody content={content} />);
    const item = container.querySelector('li') as HTMLLIElement;
    expect(item.querySelectorAll('br')).toHaveLength(1);
    expect(item.textContent).toBe('onetwo');
  });

  it('passes the GFM footnote id through to the list item', () => {
    const { container } = render(<ReportMarkdownBody content={'正文[^1]\n\n[^1]: 註腳內容'} />);
    expect(container.querySelector('li[id]')?.id).toMatch(/fn-1$/);
  });

  it('does not turn the newlines around nested lists or loose-item paragraphs into breaks', () => {
    const { container } = render(<ReportMarkdownBody content={'- 有巢狀\n  - 子一\n  - 子二\n\n段落\n\n- 鬆散一\n\n  第二段\n- 鬆散二'} />);
    const [nested, , , loose] = Array.from(container.querySelectorAll('li'));
    expect(nested.querySelector('br')).toBeNull();
    expect(whitespaceTextNodes(nested)).toHaveLength(0);
    expect(nested.firstChild?.textContent).toBe('有巢狀');
    expect(loose.querySelector('br')).toBeNull();
    expect(Array.from(loose.childNodes).map((node) => node.nodeName)).toEqual(['P', 'P']);
  });
});
