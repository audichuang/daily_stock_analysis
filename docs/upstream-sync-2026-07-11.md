# 上游同步記錄：v3.24 → v3.25（2026-07-11）

> 本 fork（`audichuang/daily_stock_analysis`）週期性吸收上游 `ZhuLinsen/daily_stock_analysis` 的整合記錄。
> 供下次同步參考：基線、裁決原則、保留的 fork 增量、採納的上游功能、刻意 defer/skip 的項目。
> 詳細逐 commit 處置分析在 `.claude/reviews/upstream-sync-analysis-2026-07-11.md`（本地產物）；本檔是可入庫的精簡正本。

## 範圍

- 分岔點（merge-base）：`db5e3230`（2026-06-27）。
- 本次同步上游至 `093057a1`（v3.25.0+，「统一报告动作展示口径 #1982」）。
- 上游落後區間 62 commits；本 fork 領先 34 commits。
- 實際 merge 衝突：50 檔（`git merge upstream/main`）。
- 執行分三階段：Phase 1 快贏 cherry-pick → Phase 2 全量 merge → Phase 3 獨家增值。
- 合入方式：三階段線性疊層，最終 fast-forward 進 `main`（merge commit `0916f57a`）。

## 裁決原則

以**上游為 base**（decision-signal / report / market 家族改動大且成體系），再把 fork 的**台股(tw)與 zh-TW 繁體增量**重放上去。語言統一為 `{zh, zh-TW, en, ko}`（zh↔zh-TW 鍵數對齊）；大盤複盤市場統一為 `cn/hk/us/tw/jp/kr`（逗號子集保留使用者輸入順序，如 `tw,us` = 台股在前）。

## 保留的 fork 增量（裁決紅線）

- `apps/dsa-web/public/stocks.index.json` 台股全量種子（並入上游 30 支日股 `.T` 種子，union）。
- `TwseFetcher` 大盤複盤台股統計路由（`market_review:<region>`，`_STATS_MARKET_FETCHER_SUPPORT`）。
- `MarketDBFetcher` priority=1（台股日線優先本地 Postgres `market` schema）。
- 台股收盤集合競價 `_CLOSING_AUCTION_WINDOW_MINUTES["tw"]=5`；`compute_effective_region` 支援 tw + 逗號輸入順序。
- `split_stock_list` 自選股分隔符解析。
- zh-TW 繁體報告/UI 語言（report_language、analyzer prompt、web i18n、config_registry enum）。

## 採納的上游功能

- 台股三大法人 fetcher（`TwInstitutionalFetcher`，TWSE T86 / TPEx）+ institution block wiring（fork 以此為基礎做 Phase 3 歷史趨勢增值）。
- decision-signal 家族：評分收斂、信號歸因、單股信號時間線、決策信號 profiles、多 Agent 分歧摘要、reassess 預覽。
- jp/kr 大盤複盤 + 市場支持；`ko` 韓文報告語言。
- 生成後端：`claude_code_cli` / `opencode_cli` local CLI backend、Hermes 本地 HTTP 渠道、Provider Cache Capability Registry、GenerationBackend 狀態診斷。
- 通知：釘釘（dingtalk）、飛書檔案上傳；Discord 長報告分片。
- 資料源：TickFlow A 股日 K/實時/清單擴展；AlphaSift 穩定性加固。
- 其他：概念板塊展示、內部 DSA Tool Surface、子 Agent 獨立超時、WebUI bind 一致性、桌面端 port/host 同步、yfinance 1.2.x 分紅解析修復。

## 關鍵衝突裁決

| 衝突區 | 裁決 |
|---|---|
| `requirements.txt` longbridge | 採上游 platform-conditional pin（Docker py3.11 → `0.2.74`；dev py3.12+ → `4.x`）。我方 `0.2.75` 在 py3.12 無 wheel。保留 `shioaji`、採上游 `tickflow>=0.1.24`。 |
| 語言分支（report_language.py / analyzer / web） | union `{zh, zh-TW, en, ko}`；保留 zh-TW 繁體、採上游 ko。 |
| `trading_calendar.compute_effective_region` / `config._parse_market_review_region` | 採上游 comma 邏輯 base，但保留 fork 的**輸入順序**語義（非 canonical 排序）。 |
| Web alert `MarketRegion` | 收斂為 `cn/hk/us`，對齊 merge 進來的後端 `MARKET_LIGHT_ALERT_REGIONS={cn,hk,us}`（告警範圍窄於快照）。 |
| `stocks.index.json` | 台股種子 ∪ 上游日股種子（union，非二選一）。 |

## 驗證

- `ci_gate` 離線全套 4462 passed（12 個歷史失敗全歸類為非本次回歸：真 `.env` 汙染 / main 上既有 / 已修的 merge-integration 測試）。
- web `tsc`/`eslint`/`build` 綠；market_data 離線測試全過。
- 台股實跑 2330.TW（`--no-notify --force-run`）：MarketDBFetcher DB 路徑、TwseFetcher 大盤統計、三大法人繁體 block 全正常。
- Codex 終審 5 輪收斂 SHIP。

## 回滾

merge commit `0916f57a` 為單點；`git revert -m 1 0916f57a` 可回滾整個上游合併（Phase 3 增值在其後、可另 revert）。

## 後續增量同步（2026-07-12）：`093057a1` → `01ebf70a`

上游在本次整併後又推 1 個 commit，已跟進：
- **`01ebf70a` #1984 `feat: add reliable home watchlist workspace`** —— 首頁自選股工作區（HomePage 重構 + `HomeStockWorkspace`、`stockPoolStore`、`useDashboardLifecycle`、批次分析提交、`history_service`/`/history` 端點小改）。
- 合併方式：`git merge upstream/main` 進 main（自動合併無文字衝突）。
- **fork 增量補齊**：#1984 給 `uiText.ts` 新增 38 個 `watchlist.*` 鍵（zh/en），fork 的 `zh-TW` 字典補上對應 38 個繁體鍵（自選/批次/送出/重新整理/載入/覆蓋 等台灣用語），維持 `zh↔zh-TW` 鍵數對齊、web `tsc` 綠。
- 驗證：`tsc` 0 error、web build 綠、3 個受影響 vitest 檔隔離跑 147 passed（全套偶發 5s timeout 為機器負載 flaky，非回歸）、後端 `test_analysis_history`/`history_comparison`/`report_language` 93 passed。

## 下次同步備忘

> **已完成後續同步**：`01ebf70a` → `e8a9ca77`（v3.26.1）見 **`docs/upstream-sync-2026-07-13.md`**。下列備忘保留作 v3.25 當下快照，新基線以 2026-07-13 文件為準。

- 起點基線 = 本次同步後的 `01ebf70a`（上游）；下次 `git fetch upstream` 後從此向後看新 commits。
- `.env` 的 `STOCK_INDEX_REMOTE_UPDATE_ENABLED` 必須保持 `false`（防上游索引更新覆蓋台股/美股增量）。
- 合併後務必 `uv pip install -r requirements.txt` 刷新 venv（longbridge/alphasift pin 會變）。
- **上游新增 UI 文案時，`uiText.ts` 的 `zh-TW` 字典要同步補繁體鍵**（`Record<UiTextKey, string>` 少一鍵即 `tsc` 失敗；#1984 踩過）。
