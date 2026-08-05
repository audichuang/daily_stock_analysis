# 上游同步記錄：v3.27 → v3.29（2026-08-05）

## 範圍

- 基線：`aa68d45d`（2026-07-23，上次同步終點）→ `a8f084bf`（2026-08-04）
- 28 個上游 commit，含 v3.28.0 與 v3.29.0；233 檔，+40,780 / −4,508
- 合併 commit：`a69d5da4`（`git merge upstream/main`，31 檔文字衝突）
- 修復 commit：見本文「Codex 審查後的修復」段

## 裁決原則

以上游為 base，重放 fork 的台股（`tw`）／`zh-TW` 增量。**這類合併的主要風險不是編譯錯誤，
而是靜默降級**——fork 增量被上游版本悄悄蓋掉，程式照跑、測試照綠，只有台股那條路不再運作。
本次實際踩到三次（見下），所以下次同步請把「找靜默降級」當成主要工作，而不是把衝突解完就算。

## 保留的 fork 增量（裁決紅線）

| 增量 | 上游狀態 | 裁決 |
| --- | --- | --- |
| `MARKET_REVIEW_REGION_ORDER` 含 `tw` | 上游新的共用常數只有 `cn,hk,us,jp,kr` | 加 `tw`；auto-merge 已把 `src/core/market_review.py` 接到上游常數，照收即廢掉台股複盤 |
| `MARKET_LIGHT_REGIONS` 含 `tw` | 上游無 `tw` | 加 `tw`（詳見下方 F1） |
| Bark 按 UTF-8 位元組截斷 2800 | 上游是字元截 `[:4000]` | 保留 fork 版，改套在上游的 `sanitized_content` 上 |
| 大盤複盤的三大法人區塊 | 上游無 | 重新注入上游重構後的 `_build_stats_block`，en/zh 兩條路徑都補 |
| `REPORT_LANGUAGE` 含 `zh-TW` | 上游是 `zh/en/ko` | 保留；「合法值」日誌改由 `SUPPORTED_REPORT_LANGUAGES` 推導，不再手寫字面 |
| `tests/test_screening_api.py` 的連外守門 | 上游改名後的 `FakeProvider` 繼承真 provider（會連外） | 保留 `_no_outbound_network` + `_OfflineHotspotProvider`，並收窄上游的 `except BaseException` |

## 採納的上游功能

- `bcb7ae4e` AlphaSift 選股內化為 `src/services/screening/`（`alphasift_service` → `screening_service`，`test_alphasift_api.py` → `test_screening_api.py`）
- `68fc575f` Web/API 按市場觸發大盤複盤（新增請求級 `region` 欄位與共用 normalizer）
- `91988da1` / `3c849dec` / `b61ebf9f` 報告分享圖與 Web 一鍵分享
- `8d8fa56b` offline pytest `--timeout=120` + faulthandler watchdog
- `7fa29c7e` longbridge `history_candlesticks_by_offset` 位置參數順序（`volume_ratio` 靜默失效）
- `02717771` yfinance 4~5 位裸港股碼誤路由 `.SZ`
- `90f62349` 騰訊日 K 保持為最終兜底
- `a8f084bf` `stock_list_parser` 顯式交易所後綴（含 `.TW` / `.TWO`）

## 刻意的分歧

- **不恢復 `src/agent/strategies/*` legacy shim。** 上游新增 `TestStrategyRouter` /
  `TestStrategyAggregator` 測它，但該 shim 已被 fork 的 `26b373c2` 當死代碼刪除，合併後全樹
  （含動態 import、字串 module path、entry point、`strategies/*.yaml`）仍無生產端引用。
  已刪除那兩個測試類並在原處留註記。生產端用的是仍存在的 `src.agent.skills.*`。
- **熱點路由卡片不再印 `来源 {item.source}`。** 上游新測試正確斷言 provider 內部名
  （`DsaEastMoneyHotspotProvider`）不得對使用者可見。

## region 順序語義（容易搞混，寫清楚）

兩條路徑**刻意不同**：

- **持久化設定 `MARKET_REVIEW_REGION`**（`normalize_market_review_region_lenient`）：
  **保留輸入順序**。`tw,us` = 台股先複盤。維運者打一次、意思明確，順序有語義
  （決定 `_persist_market_review_history` 的 primary snapshot）。
- **請求級 `region` 欄位**（`normalize_market_review_region_strict`）：
  **按 `cn,hk,us,tw,jp,kr` 排序**，不保留呼叫方輸入順序。請求沒有「作者」——Web 選擇器送出的是
  checkbox 狀態，與點擊順序無關，硬要尊重「輸入順序」只會捏造一個呼叫方從未做過的主市場選擇。

合併當下曾把 strict 也改成保留順序（想求一致），結果打破上游 3 個測試，而且 Web serializer
（`marketReviewRegion.ts`）本來就 canonical，等於前端點「台股→美股」送出的仍是 `us,tw`，
方向剛好相反。已還原並在 docstring 寫明理由。

## Codex 審查後的修復

合併後交由 Codex（gpt-5.6-sol / xhigh）獨立審查，判定 DO NOT SHIP。逐項驗證後修復：

- **F1（High，合併引入的回歸）台股失去盤面信號。**
  `MARKET_LIGHT_REGIONS = {cn,hk,us}` 本身是既有的，但上游 v3.29 把 `_build_stats_block`
  的盤面信號改成由 `_supports_market_light()` 閘住——合併前是**無條件**呼叫
  `build_market_light_snapshot`。於是台股複盤整組失去「盤面信號／信號依據／操作建議」，
  且 `tw,us` 組合會誤取美股分數當 primary。修法：`tw` 加進
  `src/schemas/market_light.py` 與 `src/services/market_light_service.py` 的兩個集合。
  `MARKET_LIGHT_ALERT_REGIONS` 維持 `cn/hk/us`（告警範圍另有文檔約定）。
- **F3（High，合併中自造）** region 順序只遷移一半——見上一節。
- **F4（Medium，合併中自造）缺資料被渲染成 0。**
  把 `institutional_net` 併進 `has_stats` 後，只有三大法人而無漲跌家數時會印出
  `0 / 0 / 0` 與成交額 `0 亿`。修法：拆成 `has_breadth` / `has_institutional`，
  表頭在任一表格列存在時輸出。
- **F5（Medium，上游削弱 fork 護欄）** `screening_service._fetch_constituent_sources`
  在 `future.result()` 外圍捕 `BaseException`，會吞掉離線測試刻意繼承 `BaseException`
  的連外守門 → 未來漏一格 mock 仍然全綠。已收窄為 `except Exception`。
- **既有 bug，但被本次合併變成可觸發：`RequestValidationError` 回 500。**
  `api/middlewares/error_handler.py` 把 `exc.errors()` 直接塞進 `JSONResponse`，
  而 `value_error` 類型的項帶著**原始 `ValueError` 物件**（不是字串），序列化失敗後被
  general handler 接成 500。上游新的 `region` 是這條鏈上第一個會拋 `ValueError` 的
  `field_validator`，所以文件明寫的 4xx 實際回 500。修法在共用 handler 一處
  （`jsonable_encoder`，與 FastAPI 自帶 handler 同一套），涵蓋所有現有與未來的 validator。

### 已知未做（另開）

- **F2（High）分享圖不認台股與繁體。** 上游新分享圖只辨識簡體「大盤複盤／市場複盤」標題、
  市場集合漏 `tw`、且把 `zh-*` 一律壓成 `zh-CN`。實測 `zh-TW` + `region=tw,us` 的真實報告
  會被當成一般 dashboard，兩個市場的結構化摘要全部消失。這是上游**新功能沒覆蓋 fork 主場**，
  不是回歸（fork 以前沒有分享圖），但落地即壞。需要動 `src/share_image.py` 多處
  （:29 標題辨識、:32/:127/:840/:1920 市場集合、:315 語言壓平）加測試。
- **F6（Low）設定頁仍展示上游五市場契約。** `settingsHelp.ts` 說 `both = cn,hk,us,jp,kr`
  且 `zh-TW` 直接回退簡中表；`systemConfigI18n.ts` 的 region label map 漏 `tw`。
  繁中使用者看到簡體說明、被告知 `both` 不含台股，但存檔後實際會跑台股。
- `_build_stats_block` 的 zh 分支對 `zh-TW` 仍輸出簡體標籤（盘面信号／指标／外资…）。
  **這是既有問題，非本次引入**——合併前就是同一套字串。

## 新增的回歸守門

- `tests/test_market_analyzer_generate_text.py::TestBuildStatsBlockRegionAndDataSplit`（7 項）
  —— 盯 F1 的市場集合與 F4 的資料分組，含 en/zh 兩語與空 overview。
- `tests/test_market_light_service.py::test_normalize_market_region_accepts_tw` —— 盯 F1。
- `tests/test_screening_api.py::OutboundGuardPropagationTestCase`（2 項）—— 盯 F5，
  已用 mutation 檢查確認「放寬回 `BaseException` 立刻紅」。
- `tests/test_error_handler_validation.py`（2 項）—— 盯 500→422，同樣過 mutation 檢查。

## 驗證

- `ci_gate.sh syntax` + `flake8`：綠
- 受影響後端子集 16 檔：**1152 passed**
- Web `lint` + `build` + `vitest`：**1062 passed**
- Import smoke：`server` / `main` / 六個核心模組乾淨
- 端到端（真實服務，未注入 Doppler 故不推播）：
  - `POST /market-review {"region":"tw"}` → 202、canonical region 正確、LLM 產出 zh-TW 報告、
    三大法人數字確實進了 prompt
  - 非法 `region`（`eu` / `tw,,us` / `both,tw`）→ 422（修復前為 500）
  - `region=us,tw` → canonical `us,tw`，兩市場複盤完成
- 全量離線 `pytest -m "not network"`：見下方「待補」

## 回滾

- 合併前的 main：`backup/pre-upstream-v3.29`（`e8998de0`）
- 分支：`merge/upstream-v3.29`；main 未動，回滾即不合併該分支

## 下次同步備忘

- 起點基線 = `a8f084bf`（上游）。
- **先跑 `git merge-tree --write-tree --name-only main upstream/main` 乾跑**，可在不動工作區的
  情況下拿到準確衝突清單，比逐檔猜快得多。
- **重點不是解衝突，是找靜默降級。** 具體做法：把上游新增的每個共用常數／helper 抓出來，
  逐個問「它的集合涵蓋 `tw` 嗎？涵蓋 `zh-TW` 嗎？」——本次三次踩雷全是這個形狀
  （`MARKET_REVIEW_REGION_ORDER`、`MARKET_LIGHT_REGIONS`、分享圖的市場集合）。
- **驗證時不要 patch 掉你要驗的那個判定。** F1 之所以第一輪沒抓到，就是因為驗
  `_build_stats_block` 時把 `_supports_market_light` patch 成固定值，正好遮住它。
- `uiText.ts` 的 `zh-TW` 是嚴格 `Record<UiTextKey, string>`，上游只加 zh/en 就會 `tsc` 失敗；
  用腳本對三張表的 key 集合做差集比逐個看 tsc 錯誤快。
- `.env` 的 `STOCK_INDEX_REMOTE_UPDATE_ENABLED` 必須保持 `false`。
- 合併後 `uv pip install -r requirements.txt` 刷新 venv。
