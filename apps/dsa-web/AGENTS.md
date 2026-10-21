# dsa-web — 面板 Web 前端

> 本檔只寫本模組增量。

## 模組定位

面板的 Web 前端:React 19 + Vite + TypeScript + Tailwind 4 + zustand。打後端 FastAPI(repo 根 `api/`),認證走 cookie session(axios `withCredentials`)。Electron 桌面端(`apps/dsa-desktop/`)包的就是這份建置產物。

## 頁面業務地圖(`src/pages/`)

- `/` HomePage:**最複雜的一頁**——發起分析任務、任務進度(run-flow/tasks 面板)、歷史報告與大盤複盤檢視都在這
- `/board` RealtimeBoardPage:台股即時看板(Shioaji 行情+大盤指數條);**資料語意正本在 `docs/realtime-board.md`**(fallback、時區、kbars 30 天上限),別在這裡重查
- `/funds` FundsPage:境內基金查詢(淨值走勢、報酬、前十大持股)與帳本外的基金持倉;資料語意見 `docs/tw-funds.md`
- `/chat` agent 對話、`/portfolio` 投組、`/decision-signals` 決策信號、`/screening` 選股、`/backtest` 回測、`/alerts` 警報、`/usage` LLM token 用量、`/data` 資料中心(唯讀資料源能力；後端 `data_capability_service.py` 不認得 fork 的台股 fetcher，台股只列 yfinance)、`/settings` 設定——顧名思義
- `/login` 登入頁(已登入時自動導回 `/`)

## 進來改要遵守

- API 呼叫一律走 `src/api/*`(共用 `api/index.ts` 的 axios 實例,自帶 `attachParsedApiError` 統一錯誤解析);**不要在元件裡直接 fetch/axios**。
- 全域狀態:zustand(`src/stores/`);auth 與 UI 語言用 context(`src/contexts/`)。
- UI 文案是 TS 常數表(`src/locales/*.ts`、`src/i18n/`),**每組文案 zh / en / zh-TW 三語都要補**。`i18n/uiText.ts`(`UI_TEXT: Record<UiLanguage, Record<UiTextKey, string>>`,`UiTextKey = keyof typeof zh`)與 `locales/*.ts` 多為嚴格 `Record` 型別——**漏一語會 tsc build 失敗**(合併上游最常踩:上游只加 zh/en,zh-TW 缺鍵即編譯錯,本 repo 已多次實踩);少數鬆散表才只是畫面缺字。
- 型別集中在 `src/types/`,與後端 schema 對齊;改後端 API 欄位時記得同步這裡。

## 驗證

- 單元測試:`npm run test`(vitest)。測試環境預設 UI 語言是英文,斷言文字照 `en` 寫
- 截圖(UI 改動的交付證據):本機 Playwright 沒下載瀏覽器(裝要先問),用 `chromium.launch({ channel: 'chrome' })` 走系統 Chrome;要指定語言就在 `addInitScript` 寫 localStorage `dsa.uiLanguage`

## 踩雷

- 看板行情異常(延遲、漲跌停欄位變空)通常不是前端問題——是後端缺 Shioaji 金鑰時**靜默降級 yfinance**,先查後端再動前端。判別看回應的 `source` 是不是 `shioaji`;名稱不會因此變英文,別拿名稱語言判斷。
- **時間相關的測試用相對日期**(`Date.now() - 1 day`)。寫死日曆日的 fixture 會在超出頁面的時間視窗後開始必紅,與程式碼改動無關(踩過:90 天時間軸)。