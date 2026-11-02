import { expect, test, type Page } from '@playwright/test';

// 完整分析報告抽屜：捲動容器有 p-6，固定標題列必須貼齊容器上緣（不能留一條縫讓捲上去的內容透出來），
// 剛打開時也不能蓋住報告的第一個標題。

const sections = Array.from({ length: 12 }, (_, i) => [
  `## 第 ${i + 1} 節`,
  '',
  '| 項目 | 數值 |',
  '| --- | --- |',
  ...Array.from({ length: 8 }, (_, j) => `| 指標 ${j + 1} | 趨勢強度: ${(i * 8 + j) % 100}/100 |`),
  '',
  '段落文字，用來把報告撐到需要捲動的長度。'.repeat(4),
  '',
].join('\n')).join('\n');
const markdown = sections;

async function openDrawer(page: Page, width: number, height: number) {
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path === '/api/v1/history/1/markdown') return route.fulfill({ json: { content: markdown } });
    return route.fulfill({ json: {} });
  });
  await page.route('**/src/main.tsx', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: `
      import React from '/node_modules/.vite/deps/react.js';
      import ReactDOMClient from '/node_modules/.vite/deps/react-dom_client.js';
      import '/src/index.css';
      import { ReportMarkdownDrawer } from '/src/components/report/ReportMarkdownDrawer.tsx';
      import { UiLanguageProvider } from '/src/contexts/UiLanguageContext.tsx';
      const h = React.createElement;
      ReactDOMClient.createRoot(document.getElementById('root')).render(h(UiLanguageProvider, null,
        h(ReportMarkdownDrawer, {
          recordId: 1, stockName: '上銀', stockCode: '2049.TW', reportLanguage: 'zh', onClose: () => {},
          summary: { analysisSummary: '觀望，等待回測支撐', operationAdvice: '觀望', trendPrediction: '震盪', sentimentScore: 40 },
        }),
      ));
    `,
  }));
  await page.setViewportSize({ width, height });
  await page.goto('/');
  const header = page.getByTestId('report-drawer-header');
  await expect(header).toBeVisible();
  await expect(page.getByRole('dialog').locator('h2', { hasText: '第 12 節' })).toBeAttached();
  return header;
}

function measure(page: Page) {
  return page.getByTestId('report-drawer-header').evaluate((header) => {
    const scroller = header.parentElement!;
    const firstH2 = scroller.querySelector('.home-markdown-prose h2')!;
    return {
      scrollerTop: scroller.getBoundingClientRect().top,
      headerTop: header.getBoundingClientRect().top,
      headerBottom: header.getBoundingClientRect().bottom,
      firstH2Top: firstH2.getBoundingClientRect().top,
    };
  });
}

for (const [label, width, height] of [['desktop', 1280, 900], ['mobile', 390, 844]] as const) {
  test(`report drawer header stays flush and clears the first heading (${label})`, async ({ page }) => {
    const header = await openDrawer(page, width, height);

    const initial = await measure(page);
    expect(Math.abs(initial.headerTop - initial.scrollerTop)).toBeLessThanOrEqual(1);
    expect(initial.firstH2Top).toBeGreaterThanOrEqual(initial.headerBottom);

    await header.evaluate((el) => { el.parentElement!.scrollTop = 1400; });
    await expect.poll(() => header.evaluate((el) => el.parentElement!.scrollTop)).toBeGreaterThan(1000);
    const scrolled = await measure(page);
    expect(Math.abs(scrolled.headerTop - scrolled.scrollerTop)).toBeLessThanOrEqual(1);
  });
}
