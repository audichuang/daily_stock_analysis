# 台股三大法人歷史趨勢注入 LLM prompt（Phase 3 設計）

> 日期：2026-07-11 · 分支：`phase3/tw-institutional-trend`（疊在 `merge/upstream-v3.25` 上）
> 上游合併三階段的第三階段——本次整合的獨家增值。
> v2（2026-07-11）：依 Codex spec 複查修正——趨勢改在 **prompt 組裝層** 計算（不入持久化 context / 不碰對外 schema）、日期正規化去重、NULL 與 streak 視窗語義明確化、沿用 `L(zh_tw, zh)` 兩語慣例。

## 背景

上游 v3.25 合併後，台股個股報告已具備「當日」三大法人買賣超（`TwInstitutionalFetcher`，走 TWSE T86 / TPEx OpenAPI 網路），透過 `get_fundamental_context` 的 `institution` block 進 `context`，再由 `analyzer._format_prompt` 的「三大法人動向」區塊（`src/analyzer.py` ~4035）寫進 LLM prompt。

上游做不到「歷史趨勢」（無歷史庫），本 fork 以前也做不到（無個股報告面）。本 fork 的 `market.institutional`（Postgres market schema）有約 14 年 per-stock 歷史（`stock_id, date, foreign_net, trust_net, dealer_net, total_net`，均 nullable，PK `(stock_id,date)`）。把兩者接起來 → 給 LLM「外資連 N 日買超、近 20 日累計、佔股本比」的籌碼趨勢語境。

## 目標與非目標

**目標**：把三大法人歷史趨勢指標注入台股個股分析的 LLM prompt，提升籌碼趨勢判讀。

**非目標（裁決紅線）**：
- 只限台股（`.TW` / `.TWO`）；其他市場不受影響。
- 嚴格 additive、fail-open：DB/psycopg 不可用、無歷史、無當日 block 時一律略過趨勢，當日 block 與主分析流程不變、絕不中斷。
- **只進 LLM prompt 字串**，不寫入 `context` / `fundamental_snapshot` / `context_snapshot` / API 報告 / Agent·AlphaSift compactor，不改 institution block 對外 schema、不動 Web/報告渲染、不新增 DecisionSignal / score / 評分權重。
- 不改上游當日抓取路徑（`TwInstitutionalFetcher`），不 mutate 其快取 record。

## 關鍵設計決策（v2，回應 Codex 複查）

**趨勢在 prompt 組裝層計算，不進持久化 context。** Codex 複查指出：`context["institution"]` 會被 `fundamental_snapshot` / `context_snapshot.enhanced_context` / API 報告 details / Agent·AlphaSift compactor 持久化與序列化，且既有測試斷言 institution data 為 raw-only。因此**不在 `base.py` 掛 trend 子欄**。改在 `analyzer._format_prompt` 的三大法人區塊，用當下已有的 `code` 與當日 `institution_data`，即時讀歷史、算趨勢、格式化成 prompt 行後即丟棄。趨勢**只存在於 prompt 字串**，永不進任何被持久化/序列化/工具消費的結構。連帶好處：不碰 `base.py` 的 stage-budget、不改對外契約、不動既有 raw-only 測試。

## 資料契約

- 歷史：`market.institutional`（DB，到前一交易日）——經新增的 `market_repo.institutional()` 讀取。
- 當日：沿用 `_format_prompt` 內已有的 `context["institution"]["data"]`（當日網路值：foreign/trust/dealer/total_net + date）——作為時間序列**最新且權威**的一點併入。
- 股本：`market.stock_info.shares_outstanding`（BigInt，可能 NULL）——僅有值且 >0 時算佔股本比。
- `stock_id` = 代碼去後綴（`2330.TW` → `2330`，複用 `market_db_fetcher._stock_id`）。

## 元件（4 個，邊界清晰）

### 1. `market_data/market_repo.py` — 歷史讀取
新增 `institutional(stock_id, start=None, end=None, engine=None) -> DataFrame`，欄位 `date, foreign_net, trust_net, dealer_net, total_net`，`ORDER BY date`。照既有 `price_history` / `valuation` 模式（`_q(sql, params, engine)`）。`stock_info(stock_id)` reader 已有，用來取 `shares_outstanding`。

### 2. `data_provider/tw_institutional_trend.py` — 純函式趨勢計算（新檔）
`compute_institutional_trend(history_rows, today_record, shares_outstanding) -> dict`（純函式、無 DB/網路/I-O）：
- **合併/去重/排序**：把 `history_rows`（DB）依 `date` 正規化為 `date`；先濾掉 `date >= today_record.date` 的列（DB 可能已含當日），再把 `today_record` 當作最新且權威的一點 append，最後依 date 升冪排序 → 單一時間序列。日期正規化涵蓋 DB `Date` 與當日 record 的 `YYYYMMDD` 字串差異。
- 對每個法人（`foreign` / `trust` / `dealer` / `total`）算：
  - `streak`：由最新往回，同號（買超>0 / 賣超<0）連續天數（含當日）。遇 `0`、**符號翻轉、或 NULL** 即中斷。若連續到達取樣視窗邊界，回傳 `streak` 並標 `capped=True`（顯示為「≥N」）。
  - `cum_5d` / `cum_20d`：近 5 / 20 個交易日淨額合計（含當日）。累計時 **NULL 視為缺值跳過**（不當 0）；實有天數不足即以實有天數計並標記。
  - `pct_of_shares`：`cum_20d(total) / shares_outstanding × 100`（僅 shares_outstanding 有值且 >0；否則 None）。**僅在「三大法人合計」那一行顯示**（用合計的 cum_20d），不逐法人重複；避免與各法人 cum 混淆。
- 邊角：空歷史 / 缺欄 / 缺當日 record / 全 NULL → 對應欄位回 None，不丟例外。

### 3. `src/analyzer.py` `_format_prompt` 三大法人區塊（~4035）— prompt 層 wiring + 兩語注入
在現有「三大法人動向」表格之後，當 `institution status==ok`、`market/code` 為台股時：
- 取 `code`（已在 `_format_prompt` scope，line 3811）與當日 `institution_data`。
- 呼叫一個 analyzer 內的私有 helper（例 `self._tw_institutional_trend_lines(code, institution_data, report_language)`）：
  1. `market_repo.institutional(_stock_id(code), start=近90天)` 讀歷史（涵蓋 ≥60 交易日以容納長 streak）；`market_repo.stock_info(...)` 取 shares_outstanding。**lazy import 於 helper 內、整段 try/except 包住**：DB/psycopg/import/查詢任何失敗 → log warning、回空字串（不加趨勢行，現有 block 位元組不變）。DB 連線用**真正的 statement/connect timeout**（透過 SQLAlchemy engine `connect_args` 的 `options='-c statement_timeout=...'` 或 psycopg `connect_timeout`，非僅靠 try/except 事後兜底），避免 DB 卡住拖慢 prompt 組裝。
  2. 用**當日 `institution_data` 的複本**（不 mutate 快取 record）組 today_record，呼叫 `compute_institutional_trend(...)`。
  3. 用 `L(zh_tw, zh)` 兩語（與該區塊一致；en/ko 沿用區塊既有的 output-language 指令，維持中文＋語言指令，不在此另做 en/ko 文案）格式化趨勢行，例：`外資：連 5 日買超；近 20 日累計 +X 股（佔股本 +Y%）`。
- 回傳字串 append 進 prompt；trend 全 None → 回空字串。

## 錯誤處理 / 降級

| 情況 | 行為 |
|---|---|
| 非 tw / 當日 block not_supported | 不算 trend（現況不變） |
| DB 不可用 / 缺 psycopg / import 失敗 / 查詢逾時 / 無歷史 | log warning，回空字串，現有 block 保留 |
| 某法人某日 net 為 NULL | streak 中斷、cum 跳過該日（不當 0） |
| shares_outstanding NULL / 0 | 算 streak / 累計，佔股本比欄 None |
| 歷史不足 20/5 日 | 以實有天數計並標記；streak 照算 |
| streak 到取樣視窗邊界 | 標 `capped`，顯示「≥N 日」 |

## 測試

- `tw_institutional_trend` 純函式單測：連買 / 連賣 / 翻轉中斷 / 0 中斷 / NULL 中斷 / 空歷史 / 缺當日 / 缺 shares / 不足視窗 / DB 已含當日（去重）/ 日期型別混用（Date vs YYYYMMDD）/ streak capped。
- `market_repo.institutional()` 讀取單測（有 DATABASE_URL 時；無則 skip，沿用 market_data conftest 慣例）。
- analyzer helper fail-open 單測：mock `market_repo` 丟例外 → helper 回空字串、不拋。
- 契約回歸：確認 `context["institution"]` 序列化/持久化**不含** trend（既有 raw-only 測試仍綠）。
- 整合實跑 2330.TW（`--force-run --no-notify`）：確認 prompt 出現趨勢行、當日 block / 持久化 context / 其他市場不受影響。

## 影響面

`market_data/market_repo.py`（+reader）、`data_provider/tw_institutional_trend.py`（新純函式）、`src/analyzer.py`（+prompt-層 helper 與趨勢行，兩語）。**零 `base.py` 變更、零 schema 變更、零持久化 context 變更、零 Web 變更、零對外契約變更。**

## 回滾

移除 `tw_institutional_trend.py`、`analyzer.py` 的趨勢 helper 與 prompt 行、`market_repo.institutional`；或 revert 本 PR。當日 institution block（上游功能）與持久化 context 不受影響。
