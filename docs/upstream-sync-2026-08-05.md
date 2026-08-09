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
第二個同樣重要的教訓在「Codex 審查後的修復」開頭：**修復本身也會製造回歸，而且會反覆犯同一種錯**。

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

**四輪審查，每一輪都審上一輪的產物。** 這個結構是刻意的，因為只審合併、不審修復，
下面那些「修復自己造成的回歸」會直接出貨。

| 輪次 | 審查標的 | 判定 | 其中「修復自己造成」的項數 |
| --- | --- | --- | --- |
| 1 | 合併 commit `a69d5da4` | DO NOT SHIP | — |
| 2 | 第一批修復 `e4fe78c8` | DO NOT SHIP | 2 |
| 3 | 第二批修復 `5ea16aa8` | DO NOT SHIP | 1 |
| 4 | 第三批修復 `0c7849f9` | DO NOT SHIP | 1 |

**四輪裡有三輪在上一輪的修復裡找到新回歸，而且三次都是同一種錯：把修法放在呼叫端，
而不是放在所有路徑匯流的那一點。** 這比任何單一 bug 都值得記住：

| 輪次 | 我修在哪 | 真正該修的地方 |
| --- | --- | --- |
| 2 | `has_stats` 加上 `institutional_net` | 信號該問「評分器有沒有可用維度」，不是問「有沒有任何資料」 |
| 3 | `_build_stats_block` 與 `market_review` 兩個消費端 | `build_market_review_payload` 會對 `None` 自己補建，`or` 抵銷呼叫端過濾 |
| 4 | 評分器的 `index_changes` 加 `isfinite` | `MarketIndex` / `MarketOverview` 的建構點——reasons、payload、`to_dict()` 是另外三個出口 |

下面逐輪記。

### 第一輪（審合併 commit）

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

### 第二輪（審第一批修復 `e4fe78c8`）

判定 DO NOT SHIP。**兩項是第一批修復自己造成的**：

- **（High，修復自造）憑空生出 50/100 的盤面判斷。** 把 `institutional_net` 併進
  `has_stats` 讓 `has_market_signal` 為真，但評分器（`_build_market_light_scores`）
  **不看** `institutional_net` 也不看 `total_amount`。於是台股在「只有三大法人」時
  三個維度全部 `available=False`，快照落在中性預設 **50 分**，報告卻印出
  「50/100 需觀察」加操作建議——而那個 50 還會被 `market_review` 當成歷史主市場分數。

  修法：新增 `_market_light_has_reading()`，在 `_build_stats_block` 與 `market_review`
  兩個消費端各過一次。**判準是「有沒有任何維度 available」，不是 `data_quality`**——
  後者只要 index 維度缺就標 `unavailable`，所以「只有漲跌停」（limit 維度真的評出
  10/100）也會被誤殺。

- **（High，修復自造）逐列判定退回單一布林又繞回原病。** 用一個 `has_breadth` 蓋住
  整組，導致「只有漲跌停家數」時印出 `0 / 0 / 0` 與 `0 亿`——正是 F4 要修的東西。
  改成 `has_advance_decline` / `has_limit` / `has_turnover` 逐列判定，en/zh 都改。

- **（High）共用 validation handler 的回應契約不安全。** 第一批只修了序列化，沒改契約：
  `input` 會回吐使用者送的原值（`/api/v1/auth/login` 的 `password` 送成非字串就在 422
  裡看到明文），且不設上限（100,000 字元的非法輸入 → 100KB 回應，零成本放大面）。
  改為投影成 `{type, loc, msg}` allowlist，錯誤筆數上限 20、訊息 500 字元。
  前端 `error.ts::extractValidationDetail` 只讀 `loc`/`msg`，不影響既有消費端。
  實測：100KB 輸入 → **176 bytes**，密碼不再出現。

- **（Medium）第一批的新測試沒有牙齒。** `_render()` 把 `_supports_market_light` 與
  `build_market_light_snapshot` 都 patch 掉，`tw` 被拿掉也不會紅——**正是本文件自己
  在「下次同步備忘」寫下的原則**。改成只設 `region` 與 `profile`，跑真實判定。

- **（Low）告警市場的文檔漂移。** `full-guide{,_EN}.md` 與 `decision-signals.md` 稱
  Market Light 告警支援 `jp/kr`，後端 `MARKET_LIGHT_ALERT_REGIONS` 只收 `cn/hk/us`，
  照文檔建立告警會被拒。三份已更正。

- **（Standards）兩個同名 `MARKET_LIGHT_REGIONS` 契約不同**——`schemas` 那個是「評得出
  分數」的窄集合，`services` 那個是「查得到快照」的全集合。**兩者都是上游命名**，改名
  會在每次合併付代價，所以不改名；改成把 service 側從 `MARKET_REVIEW_REGION_ORDER`
  推導（新增市場時不可能再落後），兩處各自註明差異。

### 第三輪（審第二批修復 `5ea16aa8`）

判定 DO NOT SHIP。**一項是第二批修復自己造成的**：

- **（High，修復自造）無讀數快照仍進 structured payload。** 第二批只在
  `_build_stats_block` 與 `market_review` 的 primary score 加閘門，漏掉第三條——
  `build_market_review_payload` 對 `None` 會**自己補建**
  （`market_light_snapshot or self.build_market_light_snapshot(...)`），那個 `or`
  把呼叫端的過濾直接抵銷。於是預設 50 分仍流進 `payload["market_light"]`、
  `market_review_payload` API、歷史紀錄，並被 `daily_market_context` 讀成
  「conservative / 等待確認」。修法：閘門移到快照進入結構化契約的**唯一入口**。
- **（High）`loc` 未設上限。** 只截 `msg` 不截 `loc`，等於把回吐與放大的路徑從值搬到鍵——
  mapping 欄位的非法 key 會被 pydantic 原樣放進 `loc`，100KB key → 100KB 回應。
  `loc` 限 16 段 × 128 字元（實測 request body 最大 loc 深度為 4，無遞迴 schema）。
- **（Medium）`NaN`/`±inf` 通過 available 檢查**，分數被釘在 100 或 0
  （`NaN` 因比較恆假而落在 `min()` 上界）。
- **（Medium）`HTTPException` 回吐 `stock_code`。** 修在輸入邊界
  （`WatchlistRequest.stock_code` 補 `max_length=32`，與 `decision_signals` 既有約定一致），
  而不是截斷所有 HTTPException detail——根因是輸入沒設上限。
- **（Low）「20 筆上限」測試只造了 3 筆錯誤**，拿掉實作上限也照樣綠。改用 60 欄位模型。

### 第四輪（審第三批修復 `0c7849f9`）

判定 DO NOT SHIP。**一項是第三批修復自己造成的**：

- **（High，修復自造）`isfinite` 放錯層。** 第三批只在評分器的 `index_changes` 過濾，
  但 reason 文案、structured payload、`to_dict()` 是另外三個出口：實測有效 breadth 加
  `change_pct=NaN` 得到 reason `+nan%`、payload 含 `nan`，而 `JSONResponse` 直接拋
  `Out of range float values are not JSON compliant`——**整個 API 回應 500，不是顯示瑕疵**。
  修法：`MarketIndex.__post_init__` 與 `MarketOverview.__post_init__` 在**建構點**清洗，
  每條 provider 路徑都會經過。壓成 `None` 而不是 0.0，因為 0 是有意義的讀數（平盤）。
  三大法人任一格非有限則整組作廢——只印部分欄位會讓「外資 -104 / 投信 +0」看起來像
  投信真的沒動作。
- **（High）既有歷史 payload 是這個缺陷的最後一個出口。** 寫入端擋住新資料，但舊紀錄
  已存在「全維度 unavailable、預設 50、yellow」的 payload，`daily_market_context`
  照樣讀成 `conservative cautious wait for confirmation`。已在讀取端
  （`_extract_market_light_signal_text`）加同判準的守門。

  **守門的範圍是「`dimensions` 存在且全部 unavailable」，不含「缺 `dimensions`」。**
  第一版把缺 `dimensions` 也當成無讀數，紅了兩個既有測試——那是另一個方向的錯：
  `MarketLightSnapshot.dimensions` 是必填，缺它的只有更舊的格式，無從證明「沒有讀數」。
  把「無法證明有讀數」當成「證明沒讀數」會靜默丟掉合法的歷史上下文，而且同樣不報錯。
- **（Low）斷言太弱。** `score != 50` 任何評分改動都能蒙過，改為斷言精確值 29。

### 第四輪指出但刻意未修（附理由）

- **報告與告警對「有讀數」的定義不同。** 報告用「任一維度 available」，告警用
  `data_quality != unavailable`（而 `data_quality` 只要 index 維度缺就標 unavailable）。
  CN 僅 breadth 可用時，報告發布 score 60，告警回 `skipped`。
  **不改**：要讓兩者一致就得放寬告警，那會在「只有漲跌家數」的降級情境下**開出一個新的
  告警面**——沒人要求、且風險不對稱（假告警的代價高於少一次告警）。告警比報告嚴格是
  合理的分層，Codex 也確認它不會造成假告警。已在此記錄，避免下次被當成 bug「順手統一」。
- **watchlist 的 `stock_code` validator 拒絕合法的台股 ETF 與日韓碼**
  （實測 `00878.TW`／`006208.TW`／`009806.TWO`／`7203.T`／`005930.KS`／`035720.KQ` 全被拒），
  與 `data_provider/base.py` 的 normalizer 及 `docs/market-support.md` 矛盾。
  **這是既有 bug，非本次合併引入**，但正踩在 fork 主場（5~6 位台股 ETF）。
  放寬一個輸入 validator 等於改變「哪些代碼算自選標的」，屬產品決定，另開處理。
- **quote path 未設長度上限且把輸入原樣放進 404**（`stocks.py:511`）。同上，既有問題。

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

每一組都做過 mutation 檢查——**把修法改回舊寫法，測試必須立刻紅**。沒過這關的測試
不算守門，只算裝飾。

- `tests/test_market_analyzer_generate_text.py::TestBuildStatsBlockRegionAndDataSplit`（13 項）
  —— 台股市場集合、逐列資料可用性、「評不出來就不給分」，含 en/zh 兩語與空 overview。
  **刻意不 patch `_supports_market_light` 與 `build_market_light_snapshot`**。
  三個變異各自被抓到：拿掉 `tw` → 3 紅、拿掉 reading gate → 1 紅、逐列退回單一布林 → 2 紅。
- `tests/test_market_light_service.py::test_normalize_market_region_accepts_tw`。
- `tests/test_screening_api.py::OutboundGuardPropagationTestCase`（2 項）—— 守門例外必須
  穿透；放寬回 `except BaseException` 立刻紅。
- `tests/test_error_handler_validation.py`（8 項）—— 422 而非 500、不回吐 `input`、
  不隨輸入放大、只暴露 allowlist 欄位、筆數上限（用 60 欄位模型真的造出 60 筆）、
  `loc` 的每段長度與段數都有上限。
- `tests/test_market_analyzer_generate_text.py::TestMarketLightReachesEveryConsumer`（6 項）
  —— 無讀數快照不得進 result 或 structured payload、非有限值在建構點就清掉、
  三大法人整組作廢、payload 必須能過 `JSONResponse`（舊版在此拋 ValueError）。
- `tests/test_daily_market_context.py::TestHistoricalMarketLightWithoutReading`（4 項）
  —— 既有歷史紀錄裡「`dimensions` 全部 unavailable」的預設 50 快照不得被讀成風險訊號；
  **缺 `dimensions` 的更舊 payload 視為有讀數**（見上方理由）；真讀數仍照常產出。
- `tests/test_market_analyzer_generate_text.py::TestNonFiniteValuesOnTheRealProviderPath`（5 項）
  —— **刻意複製 provider 的「先建空物件、再逐欄賦值」形狀**，因為第一版的清洗放在
  `__post_init__`，用 kwargs 建構的測試全綠而真實路徑完全沒保護。涵蓋 payload 可過
  `JSONResponse`、四個報告出口都不印 `nan`/`inf`、指數表格不因缺失值崩潰、
  缺失成交額不偽裝成 0、正常值不受影響。五個變異各自會紅。

## 驗證

各 commit 的驗證涵蓋範圍不同，分開記，不要合併成一句「都綠」：

| 驗證 | `e4fe78c8`（第一批修復） | `5ea16aa8`（第二批修復） |
| --- | --- | --- |
| `ci_gate.sh syntax` + `flake8` | 綠 | 綠 |
| 全量離線 `pytest -m "not network"` | **6021 passed / 0 failed**（49 分 13 秒；合併前 baseline 5202） | 見「待補」 |
| 受影響後端子集 | 16 檔 1152 passed | 17 檔 **1191 passed** |
| Web `lint` + `build` + `vitest` | 1062 passed | 未重跑（本批未動前端） |

- Import smoke：`server` / `main` / 六個核心模組乾淨。
- 端到端（真實服務 `uvicorn` on 8099，未注入 Doppler 故不推播）：
  - `POST /market-review {"region":"tw"}` → 202、canonical region 正確、LLM 產出 zh-TW 報告、
    三大法人數字確實進了 prompt
  - `region=us,tw` → canonical `us,tw`，兩市場複盤都完成
  - 非法 `region`（`eu` / `tw,,us` / `both,tw`）→ 422（修復前 500）
  - 100,000 字元非法 `region` → 回應 **176 bytes**、不含輸入（修復前 100KB 全文回吐）
  - `/auth/login` 的 `password` 送成非字串 → 422 且**回應不含明文**
  - `build_current_snapshot("tw")` → score=41、三維度全可用、`data_quality=ok`
    （真讀數，不是評分器的預設 50）

### 待補

- `5ea16aa8` 的全量離線測試。此前兩次背景執行都被 session 任務管理中止（非測試失敗；
  中止時分別跑到 6% 與 9%，0 failures）。改用 `setsid nohup` 完全脫離後重跑。
- `docker-build`、桌面端打包未驗。
- CI 的四個阻斷 job 一次都沒跑過——`ci.yml` 只在對 main 開 PR 時觸發，要驗滿得開一個
  base=main 的臨時 PR（做法見上次同步記錄）。
- Bark 推播未實測（e2e 刻意不注入 Doppler，避免誤發通知）。

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
- **驗證時不要 patch 掉你要驗的那個判定。** F1 第一輪沒抓到，就是因為驗
  `_build_stats_block` 時把 `_supports_market_light` patch 成固定值，正好遮住它。
  更糟的是**第一批修復附的測試又犯同一個錯**（第二輪審查抓到）——寫進文件不等於做得到，
  所以現在的規矩是：新測試一律做 mutation 檢查，把修法改回舊寫法，紅了才算數。
- **審查要審到修復本身，不是只審合併。** 前兩輪各有兩項發現是「修復自己引入的新回歸」
  （憑空 50/100、逐列判定退回單一布林）。只審合併就會把它們直接出貨。每改一批就再送一輪。
- **「補上缺的判定」與「別把缺資料當成零」是兩個相反方向的錯，很容易在修一個時犯另一個。**
  本次在 `_build_stats_block` 上來回踩了三次：先漏判 → 補成單一布林（把缺的印成 0）→
  拆開後又讓不相干欄位觸發評分（憑空 50 分）。判定的粒度要對齊**資料來源的粒度**，
  而不是對齊「這段程式碼有幾個 if」。
- `uiText.ts` 的 `zh-TW` 是嚴格 `Record<UiTextKey, string>`，上游只加 zh/en 就會 `tsc` 失敗；
  用腳本對三張表的 key 集合做差集比逐個看 tsc 錯誤快。
- `.env` 的 `STOCK_INDEX_REMOTE_UPDATE_ENABLED` 必須保持 `false`。
- 合併後 `uv pip install -r requirements.txt` 刷新 venv。

---

# 追加同步：v3.29 → `ed848da6`（2026-08-09）

## 範圍

`a8f084bf..ed848da6`，5 個 commit：

| commit | 內容 |
| --- | --- |
| `8052d1a0` | ci: 選擇性測試門檻（`changes` job 決定 backend 要不要跑） |
| `4dda5d71` | feat: LLM channel 顯式 Responses API 路由（`src/config.py` +315 行） |
| `03dd26ac` | ci: backend 測試分成 3 個 shard 平行跑（新增 `scripts/ci_test_shard.py` 與時長基準表） |
| `ae19329d` | fix: watchlist 明細與 workspace 狀態（純前端） |
| `ed848da6` | feat: Agent Chat 的 skill 選擇按 session 持久化 |

## 衝突與裁決（2 處）

- **`.github/workflows/ci.yml`** —— 上游把 `backend-tests` 改成 `matrix.shard [1,2,3]` 並掛上
  `needs: [changes]` 閘門；本 fork 在同一個 job 上掛了 ephemeral Postgres service 與
  `alembic upgrade head`（`market_data` 的 DB 測試要它）。**兩邊都要**：採上游的分片結構，
  把 Postgres service、`DATABASE_URL` env 與 migrate step 疊回去。migrate step **不加**
  `if: matrix.shard == 1`——DB 測試散在三個 shard 裡。
- **`tests/test_intelligence_service.py::test_fetch_enabled_sources_is_fail_open`** ——
  上游改成 patch `_validate_url` + `requests.get`；本 fork 早先改成 patch
  `_fetch_feed_entries`（完全不碰 HTTP/DNS）。**取 fork 版**：上游自己的註解說目的是避免
  耦合到 process-global 的 DNS patching，patch `_fetch_feed_entries` 把這件事做得更徹底。

## 合併後修掉的兩個靜默降級

兩個都不會報錯、不會變紅，只會少跑東西——正是上次備忘寫的那個形狀。

- **`setup.cfg` 的 `testpaths` 從 `.` 被改成 `tests`**（隨上游分片 PR 進來），
  會把 `market_data/tests/` 的 **13 個檔案**整組排除在離線套件外。改成
  `testpaths = tests market_data/tests`。
- **`scripts/ci_test_shard.py::discover_test_files` 把 `tests` 寫死**，同一個洞。
  抽成 `TEST_ROOTS` 常數，並新增
  `tests/test_ci_test_shard.py::test_shard_roots_match_the_pytest_testpaths_contract`
  ——直接讀 `setup.cfg` 的 `testpaths` 做差集，下次上游再動就會紅。
- `.github/ci-test-durations.json` 列了 `tests/test_discord_platform.py`，本 fork 在
  `26b373c2` 連同 `bot/platforms/discord.py`（不在 `ALL_PLATFORMS` 的死代碼）一起刪了。
  移除該筆；`src/notification_sender/discord_sender.py`（通知渠道）不受影響。

## 下次同步備忘（追加）

- **上游的 CI 重構會動到「要跑哪些測試」的定義**，而少跑測試看起來跟全綠一模一樣。
  合併後固定檢查三處：`setup.cfg` 的 `testpaths`、分片腳本的 root 列表、
  `ci.yml` 裡任何新的 `if:` 閘門有沒有把 fork 專屬的 step 一起關掉。
