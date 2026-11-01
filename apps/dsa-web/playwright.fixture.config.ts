import { defineConfig, devices } from '@playwright/test';

// Deterministic browser fixtures intercept every API request; no backend or secrets.
// fork：自架 runner 用 host 網路，多個 web-gate 同時跑會搶同一個 port；CI 由 workflow 挑空 port 傳進來。
const port = Number(process.env.PLAYWRIGHT_FIXTURE_PORT || 4173);
const origin = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './e2e/fixtures',
  outputDir: './test-results/fixtures',
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  // CI 固定 2 個 worker（和 GitHub 託管的 4 vCPU 預設一樣）：自架 runner 的容器看得到主機全部執行緒，
  // 預設會開 6 個 Chromium 去搶 4 核，Vite dev server 首次編譯就逾時。
  workers: process.env.CI ? 2 : undefined,
  reporter: 'list',
  use: {
    baseURL: origin,
    locale: 'zh-CN',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: origin,
    reuseExistingServer: !process.env.CI,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
