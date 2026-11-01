import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { historyApi } from '../../../api/history';
import { ReportMarkdown } from '../ReportMarkdown';

vi.mock('../../../api/history', () => ({
  historyApi: {
    getMarkdown: vi.fn(),
  },
}));

describe('ReportMarkdown', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('uses localized copy labels for English reports', async () => {
    vi.mocked(historyApi.getMarkdown).mockResolvedValue('# Full report');

    render(
      <ReportMarkdown
        recordId={1}
        stockName="Apple"
        stockCode="AAPL"
        reportLanguage="en"
        onClose={() => {}}
      />
    );

    // 複製鈕在內容載入前是 disabled，先等報告出來。
    await screen.findByRole('heading', { name: 'Full report' });
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
    expect(screen.getByRole('menuitem', { name: 'Copy Markdown Source' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Copy Plain Text' })).toBeInTheDocument();
  });

  it('retries after a load failure', async () => {
    vi.mocked(historyApi.getMarkdown)
      .mockRejectedValueOnce(new Error('load failed'))
      .mockResolvedValueOnce('# Recovered');

    render(<ReportMarkdown recordId={1} stockName="Apple" stockCode="AAPL" reportLanguage="en" onClose={() => {}} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('load failed');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('heading', { name: 'Recovered' })).toBeInTheDocument();
  });

  it('drops the trailing generated-at line, wraps tables and has no bottom close', async () => {
    vi.mocked(historyApi.getMarkdown).mockResolvedValue(
      '## 📊 Section\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n## Other\n\n*Generated At: 2026-10-30 12:00:00*\n',
    );

    render(<ReportMarkdown recordId={1} stockName="Apple" stockCode="AAPL" reportLanguage="en" onClose={() => {}} />);

    expect(await screen.findByRole('heading', { name: 'Section' })).toBeInTheDocument();
    expect(screen.queryByText(/Generated At/)).not.toBeInTheDocument();
    expect(screen.getByTestId('report-table-scroll').querySelector('table')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
    // 錨點指向實際標題。
    const nav = screen.getByRole('navigation', { name: 'Contents' });
    expect(nav).toHaveTextContent('Section');
    expect(document.getElementById('report-section-1')).toHaveTextContent('Section');
  });
});
