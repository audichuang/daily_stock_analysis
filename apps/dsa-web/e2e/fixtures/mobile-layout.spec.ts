import { expect, test, type Page } from '@playwright/test';

// 390px 手機寬的版面回歸：首頁報告標題不能被按鈕列擠成一字一行、
// 盯盤看板展開列的內容不能被 colSpan 撐成整張表寬（要橫滑才找得到按鈕）。

async function lineCount(page: Page, testId: string) {
  return page.getByTestId(testId).locator('h2').first().evaluate((el) => {
    const lh = parseFloat(getComputedStyle(el).lineHeight);
    return Math.round(el.getBoundingClientRect().height / lh);
  });
}

test('report hero titles stay on one line at 390px', async ({ page }) => {
  await page.route('**/api/**', (route) => (new URL(route.request().url()).pathname.startsWith('/api/')
    ? route.fulfill({ json: {} })
    : route.continue()));
  await page.route('**/src/main.tsx', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: `
      import React from '/node_modules/.vite/deps/react.js';
      import ReactDOMClient from '/node_modules/.vite/deps/react-dom_client.js';
      import '/src/index.css';
      import { MarketReviewReportView } from '/src/components/report/MarketReviewReportView.tsx';
      import { ReportOverview } from '/src/components/report/ReportOverview.tsx';
      import { UiLanguageProvider } from '/src/contexts/UiLanguageContext.tsx';
      const h = React.createElement;
      ReactDOMClient.createRoot(document.getElementById('root')).render(h(UiLanguageProvider, null,
        // 模擬 App 殼在手機寬時左側約 48px 的導覽列與首頁 px-3 內距（正式站量到的可用寬度）
        h('main', { className: 'ml-12 min-h-screen bg-background px-3 py-4 text-foreground space-y-4' },
          h(MarketReviewReportView, {
            recordId: 1102,
            report: { meta: { id: 1102, stockName: '🎯 大盤複盤', stockCode: 'MARKET', createdAt: '2026-10-22T10:26:44Z' }, summary: {} },
            content: '# 🎯 大盤複盤\\n\\n## 台股\\n\\n內容',
            reportLanguage: 'zh',
            onOpenRunFlow: () => {},
          }),
          h(ReportOverview, {
            meta: { id: 1, queryId: 'q', stockCode: '2049.TW', stockName: '上銀', reportType: 'detailed',
              reportLanguage: 'zh', createdAt: '2026-10-22T10:26:44Z', currentPrice: 299, changePct: -2.92 },
            summary: { analysisSummary: '觀望', operationAdvice: '觀望', trendPrediction: '震盪', sentimentScore: 40 },
          }),
        ),
      ));
    `,
  }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByTestId('market-review-hero-header')).toBeVisible();
  await expect(page.getByTestId('report-hero-header')).toBeVisible();
  expect(await lineCount(page, 'market-review-hero-header')).toBe(1);
  expect(await lineCount(page, 'report-hero-header')).toBe(1);
  // 按鈕列不能被藏掉或擠出畫面：換行後仍完整在可視寬度內
  for (const id of ['market-review-hero-header', 'report-hero-header']) {
    const buttons = page.getByTestId(id).getByRole('button');
    expect(await buttons.count()).toBeGreaterThan(0);
    for (const b of await buttons.all()) {
      await expect(b).toBeVisible();
      const r = await b.boundingBox();
      expect(r!.x + r!.width).toBeLessThanOrEqual(390);
    }
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('board expanded row fits the visible table box at 390px', async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem('dsa.uiLanguage', 'en'));
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (!path.startsWith('/api/')) return route.continue();
    const codes = (url.searchParams.get('codes') ?? '').split(',').filter(Boolean);
    const json =
      path === '/api/v1/auth/status' ? { authEnabled: false, loggedIn: true, setupState: 'no_password' }
      : path === '/api/v1/stocks/watchlist' ? { stock_codes: ['2887.TW'] }
      : path === '/api/v1/portfolio/snapshot' ? { accounts: [] }
      : path === '/api/v1/funds/holdings' ? { items: [], totals: [], nav_error: null }
      : path === '/api/v1/stocks/indices' ? { items: [] }
      : path === '/api/v1/stocks/quotes' ? { items: codes.map((c) => ({ stock_code: c, quote: {
          stock_code: c, stock_name: '台新新光金', current_price: 42.1, change: 0.15, change_percent: 0.35,
          source: 'shioaji', is_stale: false, volume: 123456, average_price: 42.0, limit_up: 46.1, limit_down: 37.8,
        } })) }
      : path === '/api/v1/stocks/dossier-summary' ? { level_alerts_enabled: true, items: codes.map((c) => ({ stock_code: c, summary: {
          as_of: '2026-10-22', close: 41.95, structure: { kind: 'BOS', bias: 'bull', date: '2026-08-31', level: 37.8 },
          levels: [{ label: '多頭 OB', low: 40.1, high: 41.2, kind: 'ob', bias: 'bull' }, { label: '空頭 OB', low: 43.5, high: 44.2, kind: 'ob', bias: 'bear' }],
          changes: [{ kind: 'foreign', tone: 'pos', text: '外資 5 日轉買 +12,345 張（20 日 -3,840）' }],
          verdicts: { fundamental: { badge: '獲利升、營收年減', tone: 'neu' }, chips: { badge: '法人回補', tone: 'pos' } },
        } })) }
      : path.endsWith('/trend') ? { points: [] }
      : path.endsWith('/financials') ? { stock_code: '2887.TW', status: 'unsupported', template: 'general', periods: [], metrics: [], not_applicable: [], monthly_revenue: [], limitations: [], is_stale: false }
      : { items: [], total: 0 };
    await route.fulfill({ json });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/board');
  // 手機改成卡片列，不再是表格 row。
  await page.getByRole('button', { name: /2887\.TW/ }).first().click();
  const expanded = page.getByTestId('board-expanded');
  await expect(expanded).toBeVisible();
  // 手機卡片不橫向捲動，展開內容與「四維度分析」要直接落在視窗內。
  const box = await expanded.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390 + 1);
  const button = expanded.getByRole('button', { name: /Four-pillar|四維度|四维度/ }).last();
  const b = await button.boundingBox();
  expect(b).not.toBeNull();
  expect(b!.x + b!.width).toBeLessThanOrEqual(390 + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
