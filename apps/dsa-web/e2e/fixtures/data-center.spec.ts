import { expect, test } from '@playwright/test';

const overview = {
  as_of: '2026-10-01T09:30:00+08:00',
  providers: [{
    name: 'akshare', label: 'AkShare', enabled: true, configured: true,
    status: 'partial', priority: 0, markets: ['CN'],
    datasets: ['financial.snapshot'], dataset_markets: { 'financial.snapshot': ['CN'] },
    warnings: ['runtime_probe_unknown'], last_error: null, cooldown: false,
  }],
  datasets: [{
    dataset: 'financial.snapshot', status: 'partial', source: 'akshare', stale: null,
    last_success: null, last_error: null, fallback_from: [],
    coverage: { markets: {
      cn: { status: 'ok', source: 'akshare' },
      hk: { status: 'unavailable', source: null },
      us: { status: 'unavailable', source: null },
    } },
    warnings: ['hk/us financial data unavailable'],
  }, {
    dataset: 'quote.realtime', status: 'ok', source: null, stale: false,
    last_success: '2026-10-01T09:29:00+08:00', last_error: null, fallback_from: [],
    coverage: { markets: {
      cn: { status: 'ok', source: 'tencent' },
      us: { status: 'ok', source: 'yfinance' },
    } }, warnings: [],
  }, {
    dataset: 'screening.snapshot', status: 'unknown', source: 'em_datacenter', stale: null,
    last_success: null, last_error: null, fallback_from: [], coverage: null,
    warnings: ['screening_health_unknown'],
  }],
  priorities: [{ scenario: 'cn.quote', providers: ['tencent', 'akshare'], source: 'runtime', warnings: [] }],
  warnings: ['screening_health_unknown'],
};

for (const state of ['partial', 'empty', 'error'] as const) {
  test(`data center: ${state}`, async ({ page }, testInfo) => {
    let failed = state === 'error';
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (!path.startsWith('/api/')) return route.continue();
      if (path.endsWith('/auth/status')) {
        return route.fulfill({ json: { authEnabled: false, loggedIn: true, setupState: 'no_password' } });
      }
      if (path.endsWith('/data/overview')) {
        if (failed) return route.fulfill({ status: 503, json: { detail: 'Fixture overview unavailable' } });
        return route.fulfill({ json: state === 'partial' ? overview : {
          as_of: overview.as_of, providers: [], datasets: [], priorities: [], warnings: [],
        } });
      }
      return route.fulfill({ json: { items: [], total: 0 } });
    });
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.goto('/data');
    await expect(page.getByRole('heading', { name: '数据中心', exact: true })).toBeVisible();
    if (state === 'partial') {
      // 改版後來源清單與技術細節收在折疊區，先展開才看得到。
      await page.locator('details').evaluateAll((items) => items.forEach((item) => { (item as HTMLDetailsElement).open = true; }));
      await expect(page.getByText('AkShare', { exact: true })).toBeVisible();
      const row = page.getByRole('row').filter({ hasText: 'A 股 财务数据' });
      await expect(row.getByRole('cell', { name: 'akshare', exact: true })).toBeVisible();
      await expect(page.getByRole('row').filter({ hasText: 'screening.snapshot' })).toContainText('尚未检查');
      await expect(page.getByText('→ akshare', { exact: true })).toBeVisible();
    } else if (state === 'empty') {
      await expect(page.getByText('暂无能力数据', { exact: true })).toBeVisible();
    } else {
      await expect(page.getByText('数据概览加载失败', { exact: true })).toBeVisible();
    }
    const desktop = testInfo.outputPath(`data-center-${state}-1440.png`);
    await page.screenshot({ path: desktop, fullPage: true, animations: 'disabled' });
    await testInfo.attach(`${state}-desktop`, { path: desktop, contentType: 'image/png' });
    if (state === 'error') {
      failed = false;
      await page.getByRole('button', { name: '重试', exact: true }).click();
      await expect(page.getByText('暂无能力数据', { exact: true })).toBeVisible();
      await expect(page.getByText('数据概览加载失败', { exact: true })).toHaveCount(0);
    }
    if (state === 'partial') {
      await page.setViewportSize({ width: 390, height: 844 });
      // 手機版改成卡片列，不靠表格橫向捲動；只要整頁不溢出。
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      const mobile = testInfo.outputPath('data-center-partial-390.png');
      await page.screenshot({ path: mobile, fullPage: true, animations: 'disabled' });
      await testInfo.attach('partial-mobile', { path: mobile, contentType: 'image/png' });
    }
  });
}


test('short desktop rail keeps settings and controls reachable', async ({ page }, testInfo) => {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    if (path.endsWith('/auth/status')) return route.fulfill({ json: {
      authEnabled: true, loggedIn: true, setupState: 'enabled', passwordSet: true,
    } });
    if (path.endsWith('/screening/status')) return route.fulfill({ json: { enabled: true, available: true } });
    if (path.endsWith('/data/overview')) return route.fulfill({ json: overview });
    return route.fulfill({ json: { items: [], total: 0 } });
  });
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto('/data');
  const rail = page.getByRole('complementary', { name: '桌面侧边导航' });
  await expect(rail.getByRole('link', { name: '选股', exact: true })).toBeVisible();
  const nav = rail.getByRole('navigation', { name: '主导航' });
  await expect.poll(() => nav.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  const pageScroll = await page.evaluate(() => window.scrollY);
  await nav.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  const settings = rail.getByRole('link', { name: '设置', exact: true });
  await expect(settings).toBeInViewport();
  await expect(rail.getByRole('button', { name: '退出', exact: true })).toBeInViewport();
  await rail.getByRole('button', { name: '切换主题', exact: true }).click();
  const themeMenu = rail.getByRole('menu', { name: '主题模式' });
  await expect(themeMenu).toBeInViewport();
  await themeMenu.getByRole('menuitemradio', { name: '深色', exact: true }).click();
  await rail.getByRole('button', { name: '退出', exact: true }).click();
  await expect(page.getByRole('heading', { name: '退出登录', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await expect(page.getByRole('heading', { name: '退出登录', exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => window.scrollY)).toBe(pageScroll);
  const screenshot = testInfo.outputPath('data-center-short-desktop-1280x720.png');
  await page.screenshot({ path: screenshot, animations: 'disabled' });
  await testInfo.attach('short-desktop-controls', { path: screenshot, contentType: 'image/png' });
});
