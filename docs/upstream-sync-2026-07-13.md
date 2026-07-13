# 上游同步記錄：v3.25 → v3.26.1（2026-07-13）

> 本 fork（`audichuang/daily_stock_analysis`）週期性吸收上游 `ZhuLinsen/daily_stock_analysis` 的整合記錄。
> 供下次同步參考：基線、裁決原則、保留的 fork 增量、採納的上游功能、刻意 defer/skip 的項目。

## 範圍

- 分岔點（merge-base）：`01ebf70a`（#1984 home watchlist workspace；見 `docs/upstream-sync-2026-07-11.md` 後續增量段）。
- 本次同步上游至 `e8a9ca77`（tag `v3.26.1`，`fix: harden release packages and report market context #1994`）。
- 上游落後區間 **7 commits**（v3.26.0 發版 + 6 個 follow-up fix/feat）。
- 實際 merge：`git merge upstream/main` 進分支 `merge/upstream-v3.26`。
- 合入方式：merge commit `655f9cdc` 後 fast-forward 進 `main`。

### 上游 commits（`01ebf70a..e8a9ca77`）

| SHA | 說明 |
|---|---|
| `6da1360a` | feat: 重建市场结构上下文 (#1981) |
| `85c02edc` | fix: reuse empty concept rankings within pipeline run (#1988) |
| `6fda28b4` | fix: bundle AkShare calendar data in desktop builds (#1990) |
| `44371c29` | fix: delete all history records by stock code (#1987) |
| `5a0552f1` | fix: 修复通知理由字段被截断 (#1989) |
| `49f46954` | docs: release v3.26.0 |
| `e8a9ca77` | fix: harden release packages and report market context (#1994) |

## 裁決原則

延續 v3.25 同步：

1. **以上游為 base** 接功能與契約變更。
2. **重放 / 保留 fork 增量**：台股(tw)、zh-TW、Sender protocol、LLMClient 拆分、Bark 位元組截斷、pipeline `finalize_and_persist`、MarketDB / TwseFetcher / Shioaji 等。
3. 語言維持 `{zh, zh-TW, en, ko}`；大盤複盤市場維持 `cn/hk/us/tw/jp/kr`。

## 保留的 fork 增量（本輪驗證仍在）

| 增量 | 驗證方式 |
|---|---|
| Sender protocol + `_senders` 組合 | `src/notification.py` 仍以 composition 註冊；mixin 未回流 |
| `src/llm/client.py::LLMClient` | `GeminiAnalyzer` 仍繼承 `LLMClient` |
| Bark UTF-8 位元組截斷（APNs 上限） | `custom_webhook_sender` 仍用 `slice_at_max_bytes` |
| pipeline `_finalize_and_persist_result` | 雙路徑仍共用；並接上 `market_structure_context` |
| 台股三大法人歷史趨勢 prompt | `analyzer._tw_institutional_trend_lines` 仍在 |
| MarketDBFetcher / TwseFetcher / Shioaji / zh-TW | 本輪未衝突覆蓋 |

## 採納的上游功能

- **A 股市場結構上下文**（#1981）：`MarketStructureService` / `MarketHotspotService`、prompt 注入、DecisionSignal 抽取、API/歷史 `details.market_structure`、Web 型別與 chat follow-up 上下文；個股報告 UI **刻意不**再展示「题材主线与个股位置」卡片（資料仍進 prompt / 決策鏈）。
- **概念排行負結果本輪複用**（#1988）：空排行不再每票重打資料源。
- **歷史依代碼批次刪除**（#1987）：超過 10000 筆可清完；空白代碼 400。
- **DecisionSignal 理由不再固定 120 字截斷**（#1989）；Telegram 按轉義後 payload 長度安全分片。
- **桌面/Docker 發行加固**：`orjson` 顯式依賴；AkShare `calendar.json` 打包校驗（#1990 / #1994）。
- **TickFlow** 申萬一級行業池排行 fallback；基本面/市場結構單能力預設超時 3s → 8s。
- **通知 / Markdown / 微信報告** 不再重複附加 AI 決策信號摘要（存儲、告警、Web AI 建議頁不變）。

## 關鍵衝突 / 合併後修正

| 項目 | 處置 |
|---|---|
| `src/core/pipeline.py` | 採上游 market structure + concept cache；接到 fork 的 `_finalize_and_persist_result`（從 `snapshot_context` 回填 `result.market_structure_context`）。 |
| `src/notification.py` / report templates | 採上游移除 decision signal excerpt；保留 Sender protocol 組合。 |
| `src/analyzer.py` | 採上游 market structure prompt 注入；保留 TW institutional trend / LLMClient。 |
| `docs/CHANGELOG.md` | 合併後約 **35 條** fork Unreleased 扁平條目錯位到 `## [3.26.0]` 後方 → 已搬回 `[Unreleased]`，並補 chore 條目。 |
| `market_data/crawler.py` | 修 flake8 `F824`（未使用的 `global _session`），避免 `ci_gate` flake8 擋關。 |
| `apps/dsa-web/package-lock.json` | `registry.npmmirror.com` → `registry.npmjs.org`（本機 `npm ci` 禁 remote mirror tarball）。 |
| 離線測試環境污染 | `system_config` setUp 隔離 ambient `LITELLM_*` / `LLM_*` 等；`report_schema` 依 runtime language 斷言 action_label；intelligence fail-open 測試避免在 fetch path 內丟 AssertionError。 |

## 市場結構對台股的影響

- `MarketStructureService` **僅支援 `cn`**；非 A 股回 unsupported / fail-open，不阻斷主流程。
- 台股分析仍走既有 TW 路徑（MarketDB / 三大法人趨勢 prompt 等），不受 A 股题材主线影響。

## 驗證

| 檢查 | 結果 |
|---|---|
| syntax + flake8 critical | 通過（含 crawler F824 修復） |
| deterministic（code / yfinance） | 通過 |
| 合併相關後端子集 | 719 passed |
| 全量離線 `pytest -m "not network"` | 4586+ passed；原 7 個失敗歸類為 `.env` 污染 / flaky，已用測試隔離修復後重跑受影響模組 **234 passed** |
| 前端 lint / vitest / build | 977 passed（2 skipped）、build 綠 |

## 回滾

- merge commit：`655f9cdc`
- 回滾整次上游合併：`git revert -m 1 655f9cdc`（若已 fast-forward 進 main，在 main 上對該 merge commit 操作）。

## 下次同步備忘

- 起點基線 = 上游 `e8a9ca77`（tag `v3.26.1`）；下次 `git fetch upstream` 後從此向後看。
- `.env` 的 `STOCK_INDEX_REMOTE_UPDATE_ENABLED` 必須保持 `false`。
- 開發者 `.env` 的 `LITELLM_MODEL` / `REPORT_LANGUAGE` 會經 `load_dotenv` 進 `os.environ`；system_config 測試已隔離，其他新測試勿假設乾淨 process env。
- 上游新增 UI 文案時，`uiText.ts` 的 `zh-TW` 字典要同步補繁體鍵。
- 合併 CHANGELOG 時注意：上游正式版段（`## [x.y.z]`）插入 Unreleased 中間會把 fork 扁平條目擠到錯誤位置，合併後要檢查結構。
- 合併後建議 `uv pip install -r requirements.txt`（本輪新增 `orjson`）。
