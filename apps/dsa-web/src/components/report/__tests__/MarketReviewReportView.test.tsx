import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { historyApi } from '../../../api/history';
import type { AnalysisReport, MarketReviewPayload } from '../../../types/analysis';
import { MarketReviewReportView } from '../MarketReviewReportView';

vi.mock('../../../api/history', () => ({
  historyApi: {
    getMarkdown: vi.fn(),
  },
}));

const twUsPayload: MarketReviewPayload = {
  version: 1,
  kind: 'market_review',
  region: 'tw,us',
  language: 'zh-TW',
  rootTitle: '大盤複盤',
  markets: {
    us: {
      title: '美股',
      date: '2026-10-29',
      indices: [{ code: 'VIX', name: 'VIX', current: 18.2, changePct: 5.1 }, { code: 'SPX', name: 'S&P', current: 7000, changePct: -0.5 }],
    },
    tw: {
      title: '台股',
      date: '2026-10-30',
      indices: [{ code: 'TAIEX', name: '加權指數', current: 23456.78, changePct: 1.2 }],
      // toCamelCase 後鍵變小寫
      indexTrends: { taiex: { series: [{ date: '2026-10-29', close: 23000 }, { date: '2026-10-30', close: 23456 }] } },
      breadth: {
        upCount: 600,
        downCount: 300,
        flatCount: 100,
        turnoverUnit: '新台幣億元',
        institutionalNet: { foreignNet: 120.5, trustNet: -30.25, dealerNet: 10, totalNet: 100.25 },
      },
      marketLight: {
        status: 'red',
        score: 30,
        label: '偏空',
        dimensions: { breadth: { score: 40, available: true }, index: { score: 0, available: false } },
      },
      nextDayPlan: { stance: 'defensive', summary: '減碼為主', focus: ['半導體'], risks: ['匯率'], keyLevels: [{ label: '支撐', price: 23000 }] },
      sectorRank: { items: [{ name: '半導體業', changePct: 2.5 }] },
      sections: [
        { key: 'market_summary', title: '盤面總覽', markdown: '長文內容' },
      ],
    },
  },
};

const englishMarketReviewReport: AnalysisReport = {
  meta: {
    queryId: 'market-review-q-1',
    stockCode: 'MARKET',
    stockName: 'Market Review',
    reportType: 'market_review',
    reportLanguage: 'en',
    createdAt: '2026-03-18T08:00:00Z',
  },
  summary: {
    analysisSummary: '',
    operationAdvice: '',
    trendPrediction: '',
    sentimentScore: undefined as unknown as number,
  },
};

const combinedMarketReviewPayload: MarketReviewPayload = {
  version: 1,
  kind: 'market_review',
  region: 'cn,hk',
  language: 'zh',
  rootTitle: '大盘复盘',
  markets: {
    cn: {
      title: 'A股市场',
      breadth: {
        upCount: 3120,
        downCount: 1420,
        limitUpCount: 72,
        limitDownCount: 4,
        totalAmount: 9600,
        turnoverUnit: '亿元',
      },
      indices: [{
        code: '000300',
        name: '沪深300',
        current: 3920.2,
        changePct: 1.2,
        high: 3940.5,
        low: 3860.1,
      }],
      sectors: {
        top: [{ name: '半导体', changePct: 2.35 }],
        bottom: [{ name: '煤炭', changePct: -1.1 }],
      },
      concepts: {
        top: [{ name: '机器人概念', changePct: 4.2 }],
        bottom: [{ name: '转基因', changePct: -2.05 }],
      },
    },
    hk: {
      title: '港股市场',
      breadth: {
        upCount: 680,
        downCount: 410,
        limitUpCount: 0,
        limitDownCount: 0,
        totalAmount: 1180,
        turnoverUnit: '亿港元',
      },
      indices: [{
        code: 'HSI',
        name: '恒生指数',
        current: 18920.4,
        changePct: -0.5,
        high: 19050.2,
        low: 18780.3,
      }],
    },
  },
};

const noBreadthMarketReviewPayload: MarketReviewPayload = {
  version: 1,
  kind: 'market_review',
  region: 'us',
  language: 'en',
  title: 'Market Review',
  rootTitle: 'Market Review',
  indices: [{
    code: 'SPX',
    name: 'S&P 500',
    current: 5200,
    changePct: 0.68,
    high: 5235.2,
    low: 5170.4,
  }],
  sectors: {
    top: [{ name: 'Technology', changePct: 1.9 }],
    bottom: [{ name: 'Energy', changePct: -0.8 }],
  },
  news: [],
  sections: [],
};

describe('MarketReviewReportView', () => {
  it('shows one market at a time, labelled with its session date and defaulting to Taiwan', () => {
    render(<MarketReviewReportView payload={twUsPayload} content="# 大盤複盤" reportLanguage="zh-TW" />);

    expect(screen.getByRole('radio', { name: '台股 10/30' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: '美股 10/29' })).toBeInTheDocument();
    expect(screen.getByText('加權指數')).toBeInTheDocument();
    expect(screen.queryByText('標普500指數')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('radio', { name: '美股 10/29' }));
    expect(screen.getByText('標普500指數')).toBeInTheDocument();
    expect(screen.queryByText('加權指數')).not.toBeInTheDocument();
  });

  it('formats index cards with thousands separators, sparkline, and a neutral VIX', () => {
    render(<MarketReviewReportView payload={twUsPayload} content="# 大盤複盤" reportLanguage="zh-TW" />);

    const cards = within(screen.getByTestId('market-index-cards'));
    expect(cards.getByText('23,456.78')).toBeInTheDocument();
    expect(cards.getByText('+1.20%')).toHaveClass('text-market-up');
    // 鍵被 toCamelCase 改成小寫時仍要對到 TAIEX
    expect(cards.getByTestId('index-sparkline')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('radio', { name: '美股 10/29' }));
    const usCards = within(screen.getByTestId('market-index-cards'));
    expect(usCards.getByText('+5.10%')).not.toHaveClass('text-market-up');
    expect(usCards.getByText(/0\.50%/)).toHaveClass('text-market-down');
  });

  it('shows the four institutional cells exactly as the API numbers', () => {
    render(<MarketReviewReportView payload={twUsPayload} content="# 大盤複盤" reportLanguage="zh-TW" />);

    const cells = within(screen.getByTestId('institutional-net'));
    expect(cells.getByText('外資').nextElementSibling).toHaveTextContent('+120.50');
    expect(cells.getByText('投信').nextElementSibling).toHaveTextContent('−30.25');
    expect(cells.getByText('自營商').nextElementSibling).toHaveTextContent('+10.00');
    expect(cells.getByText('合計').nextElementSibling).toHaveTextContent('+100.25');
  });

  it('labels the light in words with amber/grey tones and hides unavailable dimensions', () => {
    render(<MarketReviewReportView payload={twUsPayload} content="# 大盤複盤" reportLanguage="zh-TW" />);

    const light = screen.getByTestId('market-light');
    const badge = within(light).getByTestId('market-light-badge');
    // Badge shows the word only; the score is not repeated next to it.
    expect(badge).toHaveTextContent(/^警戒$/);
    expect(badge).toHaveClass('text-warning');
    expect(badge).not.toHaveClass('bg-danger/10');
    // Dimension scores move into the badge tooltip instead of inline spans.
    expect(light).not.toHaveTextContent('廣度');
    fireEvent.mouseEnter(badge);
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip).toHaveTextContent(/^廣度 40$/);
    // An unavailable dimension would only show a dash, so it is left out.
    expect(tooltip).not.toHaveTextContent('指數');
    expect(light).not.toHaveTextContent('—');
  });

  it('strips the leading emoji from the hero title', () => {
    render(
      <MarketReviewReportView
        payload={{ ...noBreadthMarketReviewPayload, title: '🎯 Market Review', rootTitle: undefined }}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    const heading = screen.getByRole('heading', { level: 2 });
    expect(heading).toHaveTextContent('Market Review');
    expect(heading.textContent).not.toContain('🎯');
  });

  it('shows the light score once: word-only badge plus a stance · sentiment line', () => {
    const payload: MarketReviewPayload = {
      ...noBreadthMarketReviewPayload,
      marketLight: {
        status: 'red',
        score: 26,
        label: 'Defensive',
        dimensions: { index: { available: true, score: 26 } },
      },
    };
    render(
      <MarketReviewReportView
        report={{
          ...englishMarketReviewReport,
          summary: { analysisSummary: 'Choppy session', operationAdvice: '', trendPrediction: '', sentimentScore: 26 },
        }}
        payload={payload}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    const conclusion = screen.getByTestId('market-review-conclusion');
    expect(conclusion.textContent?.match(/26/g)).toHaveLength(1);
    expect(screen.getByTestId('market-light-badge')).toHaveTextContent(/^Caution$/);
    // No plan stance here, so the light's own label stands in for it.
    expect(screen.getByTestId('market-review-headline')).toHaveTextContent('Defensive · Sentiment 26/100');
  });

  it('puts stance and sentiment in one headline and drops empty fields', () => {
    render(
      <MarketReviewReportView
        report={{
          ...englishMarketReviewReport,
          meta: { ...englishMarketReviewReport.meta, reportLanguage: 'zh-TW' },
          summary: { analysisSummary: '偏空整理', operationAdvice: '', trendPrediction: '留意匯率', sentimentScore: 26 },
        }}
        payload={twUsPayload}
        content="# 大盤複盤"
        reportLanguage="zh-TW"
      />,
    );

    expect(screen.getByTestId('market-review-headline')).toHaveTextContent('偏防守 · 情緒 26/100');
    const conclusion = screen.getByTestId('market-review-conclusion');
    expect(conclusion).toHaveTextContent('留意匯率');
    expect(conclusion).not.toHaveTextContent('輪動與資金');
    expect(conclusion).not.toHaveTextContent('暫無');
  });

  it('collapses long text when structured data exists but opens it for markdown-only reports', () => {
    const { rerender } = render(<MarketReviewReportView payload={twUsPayload} content="# 大盤複盤" reportLanguage="zh-TW" />);
    expect(screen.getByText('長文內容').closest('details')).not.toHaveAttribute('open');

    rerender(<MarketReviewReportView content={'## 段落\n\n只有文字'} reportLanguage="zh-TW" />);
    expect(screen.getByText('只有文字').closest('details')).toHaveAttribute('open');
  });

  it('renders the legacy 四_明日交易計畫 section as an open plan card right below the conclusion', () => {
    render(
      <MarketReviewReportView
        report={{ ...englishMarketReviewReport, summary: { ...englishMarketReviewReport.summary, analysisSummary: '結論' } }}
        payload={{
          kind: 'market_review',
          region: 'tw',
          indices: [{ code: 'TAIEX', name: '加權指數', current: 1 }],
          sections: [
            { key: 'market_summary', title: '總覽', markdown: '總覽內容' },
            // Title deliberately avoids the plan regex so only the key list can match it.
            { key: '四_明日交易計畫', title: '第四節', markdown: '計畫內容' },
          ],
        }}
        content="# x"
        reportLanguage="zh-TW"
      />,
    );

    const planCard = screen.getByTestId('next-day-plan-card');
    expect(planCard).toHaveAttribute('open');
    expect(within(planCard).getByText('明日計畫')).toBeInTheDocument();
    expect(within(screen.getByTestId('next-day-plan')).getByText('計畫內容')).toBeInTheDocument();
    expect(within(screen.getByTestId('market-review-report')).queryByText('計畫內容')).not.toBeInTheDocument();
    const conclusion = screen.getByTestId('market-review-conclusion');
    expect(conclusion.compareDocumentPosition(planCard) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(planCard.compareDocumentPosition(screen.getByTestId('market-index-cards')) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  });

  it('falls back to the plan title when no legacy key matches, stripping the emoji', () => {
    render(
      <MarketReviewReportView
        payload={{
          kind: 'market_review',
          region: 'tw',
          indices: [{ code: 'TAIEX', name: '加權指數', current: 1 }],
          sections: [
            { key: 'overview', title: 'Overview', markdown: '總覽內容' },
            { key: 'other', title: '🎯 明日操作', markdown: '計畫內容' },
          ],
        }}
        content="# x"
        reportLanguage="zh-TW"
      />,
    );

    expect(within(screen.getByTestId('next-day-plan')).getByText('計畫內容')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '摘要' })).toBeInTheDocument();
    expect(screen.queryByText(/🎯/)).not.toBeInTheDocument();
  });

  it('promotes the structured plan, and falls back to the legacy section by key', () => {
    const { rerender } = render(<MarketReviewReportView payload={twUsPayload} content="# 大盤複盤" reportLanguage="zh-TW" />);
    const plan = within(screen.getByTestId('next-day-plan'));
    expect(plan.getByText('減碼為主')).toBeInTheDocument();
    expect(plan.getByText('偏防守')).toBeInTheDocument();
    expect(plan.getByText('23,000.00')).toBeInTheDocument();

    rerender(
      <MarketReviewReportView
        payload={{
          kind: 'market_review',
          region: 'tw',
          indices: [{ code: 'TAIEX', name: '加權指數', current: 1 }],
          sections: [
            { key: 'market_summary', title: '總覽', markdown: '總覽內容' },
            { key: 'news_catalysts', title: '後市展望', markdown: '展望內容' },
          ],
        }}
        content="# x"
        reportLanguage="zh-TW"
      />,
    );
    expect(within(screen.getByTestId('next-day-plan')).getByText('展望內容')).toBeInTheDocument();
    expect(within(screen.getByTestId('market-review-report')).queryByText('展望內容')).not.toBeInTheDocument();
  });

  it('skips the sector and breadth cards entirely when the session has no such data', () => {
    render(
      <MarketReviewReportView
        payload={{ kind: 'market_review', region: 'tw', indices: [{ code: 'TAIEX', name: '加權指數', current: 1 }] }}
        content="# x"
        reportLanguage="zh-TW"
      />,
    );
    expect(screen.queryByText('這個場次沒有類股資料')).not.toBeInTheDocument();
    expect(screen.queryByTestId('sector-rank')).not.toBeInTheDocument();
    expect(screen.queryByText('暫無資料')).not.toBeInTheDocument();
    expect(screen.queryByTestId('institutional-net')).not.toBeInTheDocument();
  });

  it('hides the MARKET code and offers a retry when the report fails to load', async () => {
    vi.mocked(historyApi.getMarkdown).mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce('## 段落\n\n救回來了');

    render(<MarketReviewReportView report={englishMarketReviewReport} recordId={9} reportLanguage="en" />);

    expect(screen.getByTestId('market-review-skeleton')).toBeInTheDocument();
    expect(await screen.findByText('boom')).toBeInTheDocument();
    expect(screen.queryByText('MARKET')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByText('救回來了')).toBeInTheDocument());
  });

  it('merges the insight cards into one conclusion card with localized fallbacks', () => {
    render(
      <MarketReviewReportView
        report={englishMarketReviewReport}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText("Today's Takeaway")).toBeInTheDocument();
    expect(screen.getByText('No review summary yet')).toBeInTheDocument();
    // Empty fields are hidden instead of printing placeholders.
    expect(screen.queryByText('Rotation & Funds')).not.toBeInTheDocument();
    expect(screen.queryByText('Risks & Watchlist')).not.toBeInTheDocument();
    expect(screen.queryByText('No score yet')).not.toBeInTheDocument();
    expect(screen.queryByText('暂无摘要')).not.toBeInTheDocument();
  });

  it('renders legacy rankings when the session has no sector rank', () => {
    render(
      <MarketReviewReportView
        payload={combinedMarketReviewPayload}
        content="# 大盘复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getAllByText('行业板块').length).toBeGreaterThan(0);
    expect(screen.getByText('半导体')).toBeInTheDocument();
    expect(screen.getByText('+4.20%')).toBeInTheDocument();
    expect(screen.getByText('−2.05%')).toBeInTheDocument();
  });

  it('omits the breadth card when breadth is not available for a market review payload', () => {
    render(
      <MarketReviewReportView
        payload={noBreadthMarketReviewPayload}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.queryByText('No data')).not.toBeInTheDocument();
    expect(screen.getByText('S&P 500')).toBeInTheDocument();
    expect(screen.getByText('Technology')).toBeInTheDocument();
    expect(screen.queryByText('Advancers')).not.toBeInTheDocument();
  });

  it('shows traditional Chinese US index names for zh-TW reports only', () => {
    const payload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'us',
      language: 'zh-TW',
      title: '大盤複盤',
      rootTitle: '大盤複盤',
      indices: [
        { code: 'SPX', name: '标普500指数', current: 7712.57, changePct: 0.3 },
        { code: '^IXIC', name: '纳斯达克综合指数', current: 26424.82, changePct: 0.5 },
        { code: 'TWII', name: '加權指數', current: 23000, changePct: 0.1 },
      ],
    };

    const { rerender } = render(
      <MarketReviewReportView payload={payload} content="# 大盤複盤" reportLanguage="zh-TW" />,
    );

    expect(screen.getByText('標普500指數')).toBeInTheDocument();
    expect(screen.getByText('那斯達克綜合指數')).toBeInTheDocument();
    expect(screen.getByText('加權指數')).toBeInTheDocument();
    expect(screen.queryByText('标普500指数')).not.toBeInTheDocument();

    rerender(<MarketReviewReportView payload={payload} content="# 大盘复盘" reportLanguage="zh" />);

    expect(screen.getByText('标普500指数')).toBeInTheDocument();
    expect(screen.queryByText('標普500指數')).not.toBeInTheDocument();
  });

  it('coerces string-backed numbers and never prints unrounded values', () => {
    const payload = {
      version: 1,
      kind: 'market_review',
      region: 'cn',
      language: 'en',
      title: 'Market Review',
      rootTitle: 'Market Review',
      breadth: {
        upCount: '4,327',
        downCount: '1,145',
        limitUpCount: '0',
        limitDownCount: '12',
        totalAmount: '36,822.49698199988',
        turnoverUnit: 'bn',
      },
      indices: [{
        code: '000001',
        name: 'Shanghai Composite',
        current: '4,112.446',
        changePct: '0.44079750937683315%',
      }],
    } as unknown as MarketReviewPayload;

    render(
      <MarketReviewReportView
        payload={payload}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('4,327')).toBeInTheDocument();
    expect(screen.getByText('36,822.50 bn')).toBeInTheDocument();
    expect(screen.getByText('4,112.45')).toBeInTheDocument();
    expect(screen.getByText('+0.44%')).toBeInTheDocument();
    expect(screen.queryByText(/0\.440797/)).not.toBeInTheDocument();
  });

  it('keeps actions in the more menu and opens run flow from it', () => {
    const onOpenRunFlow = vi.fn();

    render(
      <MarketReviewReportView
        payload={combinedMarketReviewPayload}
        content="# 大盘复盘"
        recordId={7}
        reportLanguage="zh"
        onOpenRunFlow={onOpenRunFlow}
      />,
    );

    expect(screen.queryByRole('menuitem', { name: '查看历史记录 7 运行流' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '查看历史记录 7 运行流' }));

    expect(onOpenRunFlow).toHaveBeenCalledWith(7);
  });

  it('adds a full-report button and merges page actions into the single more menu', () => {
    const onOpenFullReport = vi.fn();
    const onHistory = vi.fn();

    render(
      <MarketReviewReportView
        payload={combinedMarketReviewPayload}
        content="# 大盘复盘"
        recordId={7}
        reportLanguage="zh"
        onOpenFullReport={onOpenFullReport}
        extraActionItems={[{ key: 'history', label: '历次分析', onSelect: onHistory }]}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /完整报告/ }));
    expect(onOpenFullReport).toHaveBeenCalled();
    expect(screen.getAllByRole('button', { name: '更多操作' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    expect(screen.getByRole('menuitem', { name: '复制 Markdown 源码' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('menuitem', { name: '历次分析' }));
    expect(onHistory).toHaveBeenCalled();
  });
});
