import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { ReportOverview } from '../ReportOverview';

const baseMeta = {
  queryId: 'q-1',
  stockCode: '600519',
  stockName: '贵州茅台',
  reportType: 'detailed' as const,
  reportLanguage: 'zh' as const,
  createdAt: '2026-03-21T08:00:00Z',
};

const baseSummary = {
  analysisSummary: '趋势维持强势',
  operationAdvice: '继续观察买点',
  trendPrediction: '短线震荡偏强',
  sentimentScore: 78,
};

describe('ReportOverview', () => {
  it('renders final market phase and partial-bar labels from report metadata', () => {
    render(
      <ReportOverview
        meta={{
          ...baseMeta,
          marketPhaseSummary: {
            market: 'cn',
            phase: 'intraday',
            marketLocalTime: '2026-03-21T10:30:00+08:00',
            sessionDate: '2026-03-21',
            effectiveDailyBarDate: '2026-03-20',
            isTradingDay: true,
            isMarketOpenNow: true,
            isPartialBar: true,
            minutesToOpen: null,
            minutesToClose: 150,
            triggerSource: 'api',
            analysisIntent: 'auto',
            warnings: [],
          },
        }}
        summary={baseSummary}
      />,
    );

    expect(screen.getByLabelText('CN · 盘中')).toBeInTheDocument();
    expect(screen.getByText('CN · 盘中')).toBeVisible();
    expect(screen.getByLabelText('日线未完成')).toBeInTheDocument();
  });

  it('renders English final market phase and partial-bar labels', () => {
    render(
      <ReportOverview
        meta={{
          ...baseMeta,
          reportLanguage: 'en',
          marketPhaseSummary: {
            market: 'us',
            phase: 'postmarket',
            marketLocalTime: '2026-03-21T16:30:00-04:00',
            sessionDate: '2026-03-21',
            effectiveDailyBarDate: '2026-03-21',
            isTradingDay: true,
            isMarketOpenNow: false,
            isPartialBar: true,
            minutesToOpen: null,
            minutesToClose: null,
            triggerSource: 'api',
            analysisIntent: 'auto',
            warnings: [],
          },
        }}
        summary={baseSummary}
      />,
    );

    expect(screen.getByLabelText('US · Post-market')).toBeInTheDocument();
    expect(screen.getByLabelText('Partial bar')).toBeInTheDocument();
  });

  it('renders unknown final phase without partial-bar label', () => {
    render(
      <ReportOverview
        meta={{
          ...baseMeta,
          marketPhaseSummary: {
            market: null,
            phase: 'unknown',
            marketLocalTime: null,
            sessionDate: null,
            effectiveDailyBarDate: null,
            isTradingDay: null,
            isMarketOpenNow: null,
            isPartialBar: false,
            minutesToOpen: null,
            minutesToClose: null,
            triggerSource: 'api',
            analysisIntent: 'auto',
            warnings: ['calendar_unavailable'],
          },
        }}
        summary={baseSummary}
      />,
    );

    expect(screen.getByText('阶段未知')).toBeVisible();
    expect(screen.queryByText('日线未完成')).not.toBeInTheDocument();
  });

  it('does not render a market phase placeholder for legacy reports', () => {
    render(<ReportOverview meta={baseMeta} summary={baseSummary} />);

    expect(screen.queryByText(/阶段/)).not.toBeInTheDocument();
    expect(screen.queryByText('日线未完成')).not.toBeInTheDocument();
  });

  it('renders related boards with leading and lagging markers', () => {
    render(
      <ReportOverview
        meta={baseMeta}
        summary={baseSummary}
        details={{
          belongBoards: [
            { name: ' 白酒 ', type: '行业' },
            { name: '消费', type: '概念' },
            { name: '新能源' },
          ],
          sectorRankings: {
            top: [{ name: '白酒', changePct: 2.31 }],
            bottom: [{ name: '新能源', changePct: -1.2 }],
          },
          conceptRankings: {
            top: [{ name: '消费', changePct: 4.56 }],
            bottom: [],
          },
        }}
      />,
    );

    expect(screen.getByText('关联板块')).toBeInTheDocument();
    expect(screen.getByText('白酒')).toBeInTheDocument();
    expect(screen.getAllByText('领涨')).toHaveLength(2);
    expect(screen.getByText('+2.31%')).toBeInTheDocument();
    expect(screen.getByText('+4.56%')).toBeInTheDocument();
    expect(screen.getByText('领跌')).toBeInTheDocument();
    expect(screen.getByText('\u22121.20%')).toBeInTheDocument();
    expect(screen.queryByText('中性')).not.toBeInTheDocument();
  });

  it('does not apply industry ranking to a concept board with the same name', () => {
    render(
      <ReportOverview
        meta={baseMeta}
        summary={baseSummary}
        details={{
          belongBoards: [{ name: '白酒', type: '概念' }],
          sectorRankings: {
            top: [{ name: '白酒', changePct: 2.31 }],
            bottom: [],
          },
          conceptRankings: {
            top: [],
            bottom: [{ name: '白酒', changePct: -3.2 }],
          },
        }}
      />,
    );

    expect(screen.getByText('白酒')).toBeInTheDocument();
    expect(screen.getByText('关联板块')).toBeInTheDocument();
    expect(screen.getByText('领跌')).toBeInTheDocument();
    expect(screen.getByText('\u22123.20%')).toBeInTheDocument();
    expect(screen.queryByText('+2.31%')).not.toBeInTheDocument();
  });

  it('renders untyped boards in a single related-board row with ranking matches', () => {
    const conceptRankingBoard = '榜单样例甲';
    const fallbackConceptBoard = '未标注板块';
    const sectorRankingBoard = '榜单样例乙';

    render(
      <ReportOverview
        meta={baseMeta}
        summary={baseSummary}
        details={{
          belongBoards: [
            { name: conceptRankingBoard },
            { name: fallbackConceptBoard },
            { name: sectorRankingBoard },
          ],
          sectorRankings: {
            top: [{ name: sectorRankingBoard, changePct: 1.11 }],
            bottom: [],
          },
          conceptRankings: {
            top: [{ name: conceptRankingBoard, changePct: 3.21 }],
            bottom: [],
          },
        }}
      />,
    );

    const relatedBoardsRegion = screen.getByRole('region', { name: '关联板块' });

    expect(within(relatedBoardsRegion).getByText(sectorRankingBoard)).toBeInTheDocument();
    expect(within(relatedBoardsRegion).getByText(conceptRankingBoard)).toBeInTheDocument();
    expect(within(relatedBoardsRegion).getByText(fallbackConceptBoard)).toBeInTheDocument();
    expect(within(relatedBoardsRegion).getByText('+3.21%')).toBeInTheDocument();
  });

  it('places related boards below action advice in one horizontal row', () => {
    const { container } = render(
      <ReportOverview
        meta={baseMeta}
        summary={baseSummary}
        details={{
          belongBoards: [
            { name: '白酒', type: '行业' },
            { name: '消费', type: '概念' },
            { name: '高端制造' },
            { name: '沪股通' },
          ],
        }}
      />,
    );

    const actionAdviceTitle = screen.getByText('操作建议');
    const relatedBoardsRegion = screen.getByRole('region', { name: '关联板块' });
    const boardLists = container.querySelectorAll('.home-related-board-list');

    expect(actionAdviceTitle.compareDocumentPosition(relatedBoardsRegion) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText('关联板块')).toBeInTheDocument();
    expect(screen.getByText('沪股通')).toBeInTheDocument();
    expect(boardLists[0]).toHaveClass(
      'flex-nowrap',
      'overflow-x-auto',
      'w-full',
      'min-w-0',
      'max-w-full',
      'touch-pan-x',
    );
  });

  it('shows board list when rankings are unavailable', () => {
    render(
      <ReportOverview
        meta={baseMeta}
        summary={baseSummary}
        details={{
          belongBoards: [{ name: '半导体', type: '行业' }],
        }}
      />,
    );

    expect(screen.getByText('关联板块')).toBeInTheDocument();
    expect(screen.getByText('半导体')).toBeInTheDocument();
    expect(screen.queryByText('中性')).not.toBeInTheDocument();
    expect(screen.queryByText('领涨')).not.toBeInTheDocument();
    expect(screen.queryByText('领跌')).not.toBeInTheDocument();
  });

  it('shows only the board when a matching ranking has no change percent', () => {
    render(
      <ReportOverview
        meta={baseMeta}
        summary={baseSummary}
        details={{
          belongBoards: [{ name: '白酒', type: '行业' }],
          sectorRankings: {
            top: [{ name: '白酒' }],
            bottom: [],
          },
        }}
      />,
    );

    expect(screen.getByText('关联板块')).toBeInTheDocument();
    expect(screen.getByText('白酒')).toBeInTheDocument();
    expect(screen.queryByText('行业')).not.toBeInTheDocument();
    expect(screen.queryByText('领涨')).not.toBeInTheDocument();
    expect(screen.queryByText('领跌')).not.toBeInTheDocument();
  });

  it('hides related boards section when no boards are available', () => {
    render(<ReportOverview meta={baseMeta} summary={baseSummary} details={{ belongBoards: [] }} />);

    expect(screen.queryByText('板块联动')).not.toBeInTheDocument();
  });

  it('renders the persisted empty-news disclosure beside the core conclusion', () => {
    render(
      <ReportOverview
        meta={baseMeta}
        summary={baseSummary}
        details={{
          emptyNewsDisclosure: '⚠️ 未配置搜索渠道，本次分析未纳入新闻面证据。',
        }}
      />,
    );

    expect(screen.getByRole('note')).toHaveTextContent('未配置搜索渠道');
    expect(screen.getByRole('note')).toHaveTextContent('未纳入新闻面证据');
  });

  it('fails open on malformed ranking payloads', () => {
    render(
      <ReportOverview
        meta={baseMeta}
        summary={baseSummary}
        details={{
          belongBoards: [{ name: ' 白酒 ' }],
          sectorRankings: {
            top: {} as unknown as never[],
            bottom: [{ name: '白酒', changePct: '-2.5%' as unknown as number }],
          },
        }}
      />,
    );

    expect(screen.getByText('关联板块')).toBeInTheDocument();
    expect(screen.getByText('白酒')).toBeInTheDocument();
    expect(screen.getByText('领跌')).toBeInTheDocument();
    expect(screen.getByText('\u22122.50%')).toBeInTheDocument();
  });

  it('hides the stock-only watchlist card for index reports', () => {
    render(
      <ReportOverview
        meta={{ ...baseMeta, stockCode: 'sh000016', assetType: 'index' }}
        summary={baseSummary}
        watchlist={{
          isInWatchlist: () => false,
          onToggle: () => {},
          isActioning: false,
          actionMessage: null,
        }}
      />,
    );

    expect(screen.queryByRole('button', { name: /自选/ })).not.toBeInTheDocument();
  });

  it('keeps the stock-only watchlist card for stock reports', () => {
    render(
      <ReportOverview
        meta={{ ...baseMeta, stockCode: '600519', assetType: 'stock' }}
        summary={baseSummary}
        watchlist={{
          isInWatchlist: () => false,
          onToggle: () => {},
          isActioning: false,
          actionMessage: null,
        }}
      />,
    );

    expect(screen.getByRole('button', { name: '加入自选' })).toBeInTheDocument();
  });

  it('keeps the stock-only watchlist card when assetType is absent (legacy)', () => {
    render(
      <ReportOverview
        meta={{ ...baseMeta, stockCode: '600519' }}
        summary={baseSummary}
        watchlist={{
          isInWatchlist: () => false,
          onToggle: () => {},
          isActioning: false,
          actionMessage: null,
        }}
      />,
    );

    expect(screen.getByRole('button', { name: '加入自选' })).toBeInTheDocument();
  });
});

describe('ReportOverview conclusion', () => {
  afterEach(() => {
    window.localStorage.removeItem('dsa.uiLanguage');
  });

  const positionAdvice = { noPosition: '空手先等', hasPosition: '持股守停損' };

  it('shows the glossary word for an old report stored as 減倉, not the stored label', () => {
    window.localStorage.setItem('dsa.uiLanguage', 'zh-TW');
    render(
      <UiLanguageProvider>
        <ReportOverview meta={baseMeta} summary={{ ...baseSummary, action: 'reduce', actionLabel: '減倉' }} />
      </UiLanguageProvider>,
    );

    expect(screen.getByTestId('report-action')).toHaveTextContent('減碼');
    expect(screen.queryByText('減倉')).not.toBeInTheDocument();
  });

  it('maps a stored label when the enum is absent', () => {
    window.localStorage.setItem('dsa.uiLanguage', 'zh-TW');
    render(
      <UiLanguageProvider>
        <ReportOverview meta={baseMeta} summary={{ ...baseSummary, action: null, actionLabel: '減倉' }} />
      </UiLanguageProvider>,
    );

    expect(screen.getByTestId('report-action')).toHaveTextContent('減碼');
  });

  it('prefers the one-sentence conclusion and keeps the longer summary collapsed', () => {
    render(<ReportOverview meta={baseMeta} summary={{ ...baseSummary, oneSentence: '一句話結論' }} />);

    expect(screen.getByText('一句話結論')).toBeVisible();
    expect(screen.getByText('趋势维持强势')).not.toBeVisible();
  });

  it('shows time sensitivity, confidence, score and comparison with the previous report', () => {
    render(
      <ReportOverview
        meta={{ ...baseMeta, reportLanguage: 'zh-TW', previousReport: { action: 'hold', score: 60, createdAt: '2026-10-28T08:00:00', stopLoss: 90 } }}
        summary={{ ...baseSummary, action: 'watch', sentimentScore: 45, timeSensitivity: '今日有效', confidenceLevel: '中' }}
      />,
    );

    expect(screen.getByTestId('report-time-sensitivity')).toHaveTextContent('今日有效');
    expect(screen.getByText('中')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '模型評分 45' })).toBeInTheDocument();
    const comparison = screen.getByTestId('report-comparison');
    expect(comparison).toHaveTextContent('10/28');
    expect(comparison).toHaveTextContent('模型評分 60 → 45');
  });

  it('clamps the score marker but prints the raw score', () => {
    render(<ReportOverview meta={baseMeta} summary={{ ...baseSummary, sentimentScore: 130 }} />);

    expect(screen.getByTestId('score-bar-marker')).toHaveStyle({ left: '100%' });
    expect(screen.getByTestId('score-bar')).toHaveTextContent('130');
  });

  it('no longer renders the fear and greed gauge', () => {
    render(<ReportOverview meta={baseMeta} summary={baseSummary} />);

    expect(screen.queryByText('市场情绪')).not.toBeInTheDocument();
    expect(screen.queryByText('恐惧贪婪指数')).not.toBeInTheDocument();
  });

  it('rounds the change amount to at most two decimals', () => {
    render(
      <ReportOverview
        meta={{ ...baseMeta, reportLanguage: 'zh-TW', currentPrice: 2370, changePct: -1.86, changeAmount: -44.9175 }}
        summary={baseSummary}
      />,
    );

    const price = screen.getByTestId('report-price');
    expect(price).toHaveTextContent('\u221244.92');
    expect(price).not.toHaveTextContent('44.9175');
  });

  it('labels the price with its session date and close or intraday', () => {
    const { rerender } = render(
      <ReportOverview
        meta={{ ...baseMeta, reportLanguage: 'zh-TW', currentPrice: 100, changePct: -1.5, changeAmount: -1.52, priceDate: '2026-10-30' }}
        summary={baseSummary}
      />,
    );

    const price = screen.getByTestId('report-price');
    expect(price).toHaveTextContent('10/30 收盤');
    expect(price).toHaveTextContent('\u22121.52');
    expect(price).toHaveTextContent('\u22121.50%');

    rerender(
      <ReportOverview
        meta={{
          ...baseMeta,
          reportLanguage: 'zh-TW',
          currentPrice: 100,
          priceDate: '2026-10-30',
          marketPhaseSummary: { phase: 'intraday', warnings: [] },
        }}
        summary={baseSummary}
      />,
    );
    expect(screen.getByTestId('report-price')).toHaveTextContent('10/30 盤中');
  });

  it('pins the holding column only when held is true', () => {
    render(<ReportOverview meta={{ ...baseMeta, held: true }} summary={{ ...baseSummary, positionAdvice }} />);

    const hasPosition = screen.getByTestId('advice-has-position');
    const noPosition = screen.getByTestId('advice-no-position');
    expect(hasPosition).toHaveAttribute('data-pinned', 'true');
    expect(hasPosition.compareDocumentPosition(noPosition) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it.each([null, false, undefined])('does not pin either column when held is %s', (held) => {
    render(<ReportOverview meta={{ ...baseMeta, held }} summary={{ ...baseSummary, positionAdvice }} />);

    const hasPosition = screen.getByTestId('advice-has-position');
    const noPosition = screen.getByTestId('advice-no-position');
    expect(hasPosition).toHaveAttribute('data-pinned', 'false');
    expect(noPosition).toHaveAttribute('data-pinned', 'false');
    expect(noPosition.compareDocumentPosition(hasPosition) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('flags guardrail reports with their reason', () => {
    render(
      <ReportOverview
        meta={{ ...baseMeta, reportLanguage: 'zh-TW' }}
        summary={{ ...baseSummary, guardrailApplied: true, guardrailReason: '重大波動沒有新聞' }}
      />,
    );

    const guardrail = screen.getByTestId('report-guardrail');
    expect(guardrail).toHaveTextContent('系統護欄調整');
    // Legacy reports (no guardrailKind) keep the badge but fold the reason behind it.
    expect(guardrail).not.toHaveTextContent('重大波動沒有新聞');
    const toggle = within(guardrail).getByRole('button', { name: /系統護欄調整/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(guardrail).toHaveTextContent('重大波動沒有新聞');
  });

  it('leads with the model intent when the guardrail fired for missing data', () => {
    window.localStorage.setItem('dsa.uiLanguage', 'zh-TW');
    render(
      <UiLanguageProvider>
        <ReportOverview
          meta={{ ...baseMeta, reportLanguage: 'zh-TW' }}
          summary={{
            ...baseSummary,
            action: 'watch',
            oneSentence: '資金流資料缺，先觀望',
            positionAdvice: { noPosition: '護欄版空手', hasPosition: '護欄版持股' },
            guardrailApplied: true,
            guardrailKind: 'data_unavailable',
            guardrailReason: '法人資金流抓不到',
            modelOneSentence: '突破前高，可小量試單',
            modelPositionAdvice: { noPosition: '模型版空手', hasPosition: '模型版持股' },
          }}
        />
      </UiLanguageProvider>,
    );

    expect(screen.getByTestId('report-sentence')).toHaveTextContent('模型原意：突破前高，可小量試單');
    expect(screen.getByTestId('report-action')).toHaveTextContent('觀望');
    expect(screen.getByTestId('advice-no-position')).toHaveTextContent('模型版空手');
    expect(screen.getByTestId('advice-has-position')).toHaveTextContent('模型版持股');

    const guardrail = screen.getByTestId('report-guardrail');
    const toggle = within(guardrail).getByRole('button', { name: /護欄：資料缺，動作降為觀望/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(guardrail).not.toHaveTextContent('法人資金流抓不到');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(guardrail).toHaveTextContent('法人資金流抓不到');
    expect(guardrail).toHaveTextContent('資金流資料缺，先觀望');
  });

  it('keeps the guardrailed sentence for market-logic adjustments', () => {
    render(
      <ReportOverview
        meta={{ ...baseMeta, reportLanguage: 'zh-TW' }}
        summary={{
          ...baseSummary,
          action: 'watch',
          oneSentence: '大盤轉弱，先觀望',
          guardrailApplied: true,
          guardrailKind: 'market_logic',
          guardrailReason: '大盤紅燈',
          modelOneSentence: '突破前高，可小量試單',
        }}
      />,
    );

    expect(screen.getByTestId('report-sentence')).toHaveTextContent('大盤轉弱，先觀望');
    expect(screen.getByTestId('report-sentence')).not.toHaveTextContent('模型原意');
    const guardrail = screen.getByTestId('report-guardrail');
    fireEvent.click(within(guardrail).getByRole('button', { name: /護欄已調整/ }));
    expect(guardrail).toHaveTextContent('大盤紅燈');
    expect(guardrail).toHaveTextContent('模型原本建議：突破前高，可小量試單');
  });

  it('shows the structured key-level strip by action and compares the stop with the previous report', () => {
    render(
      <ReportOverview
        meta={{
          ...baseMeta,
          reportLanguage: 'zh-TW',
          currentPrice: 100,
          previousReport: { stopLoss: 106.5 },
        }}
        summary={{ ...baseSummary, action: 'reduce' }}
        strategy={{ sniperPricesSource: 'structured', sniperPrices: { idealBuy: 95, stopLoss: 94.2, takeProfit: 108.2 } }}
      />,
    );

    const strip = screen.getByTestId('report-key-levels');
    expect(strip).toHaveTextContent(/停損 94\.2\d*（−5\.8%）｜反彈減碼 108\.2\d*（\+8\.2%）/);
    expect(strip).not.toHaveTextContent('進場');
    expect(screen.getByTestId('report-comparison')).toHaveTextContent(/停損 106\.5\d* → 94\.2/);
  });

  it('does not render the key-level strip for legacy sniper prices', () => {
    render(
      <ReportOverview
        meta={{ ...baseMeta, reportLanguage: 'zh-TW', currentPrice: 100, previousReport: { stopLoss: 106.5 } }}
        summary={{ ...baseSummary, action: 'buy' }}
        strategy={{ sniperPricesSource: 'legacy', sniperPrices: { idealBuy: 95, stopLoss: 90 } }}
      />,
    );

    expect(screen.queryByTestId('report-key-levels')).not.toBeInTheDocument();
    expect(screen.getByTestId('report-comparison')).toHaveTextContent(/前份停損 106\.5/);
  });

  it('keeps the price neutral and tones only the change', () => {
    render(
      <ReportOverview
        meta={{ ...baseMeta, reportLanguage: 'zh-TW', currentPrice: 100, changePct: 2, changeAmount: 2 }}
        summary={baseSummary}
      />,
    );

    const price = screen.getByTestId('report-price');
    const [current, change] = Array.from(price.children);
    expect(current).toHaveClass('text-foreground', 'text-3xl');
    expect(current).not.toHaveClass('text-market-up');
    expect(change).toHaveClass('text-market-up');
  });

  it('does not flag when the guardrail was not applied', () => {
    render(<ReportOverview meta={baseMeta} summary={{ ...baseSummary, guardrailApplied: false }} />);
    expect(screen.queryByTestId('report-guardrail')).not.toBeInTheDocument();
  });

  it('shows the data gap notice under the conclusion', () => {
    render(<ReportOverview meta={baseMeta} summary={baseSummary} notice="部分資料缺漏" />);
    expect(within(screen.getByTestId('report-conclusion')).getByTestId('report-gap-notice')).toHaveTextContent('部分資料缺漏');
  });

  it('toggles the watchlist from the star in the title row', () => {
    const onToggle = vi.fn();
    render(
      <ReportOverview
        meta={baseMeta}
        summary={baseSummary}
        watchlist={{ isInWatchlist: () => false, onToggle, isActioning: false, actionMessage: null }}
      />,
    );

    fireEvent.click(within(screen.getByTestId('report-hero-header')).getByRole('button', { name: '加入自选' }));
    expect(onToggle).toHaveBeenCalledWith('600519');
  });
});
