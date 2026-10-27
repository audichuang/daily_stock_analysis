# 上游同步紀錄 2026-10-21（v3.33.0 後第二輪）

## 基線

| | |
| --- | --- |
| 上一次同步基線 | `7a21cd76`（`docs/upstream-sync-2026-10-19.md` 收的最後一個 commit） |
| 本次上游 HEAD | `ec66bf46`（上游最新發版仍是 `v3.33.0`，不在本輪範圍內） |
| 吸收 commit 數 | 1（全部；3 檔，+29／−10） |
| 合併方式 | 分支 `chore/upstream-sync-2026-10-21`（自 `main` `3a332522`）`git merge upstream/main --no-ff`，不 rebase（§10） |
| 衝突檔 | 1：`src/notification_sender/telegram_sender.py`（import 行） |
| 新依賴 | 無 |
| 觸發 | 上游待同步只有 1 個 commit（低於 precheck 門檻 5），本輪由 `force-once` 強制執行 |

## 吸收的上游改動

| commit | 內容 | 對本 fork 的意義 |
| --- | --- | --- |
| `ec66bf46` #2419 | Telegram 推送改以 UTF-16 code unit 計算 4096 上限並據此分段（`utf16_len`／`_custom_unit_to_index`，兩者 fork 的 `src/formatters.py` 早已有），修復含大量 emoji 的報告超限發送失敗；補一個 emoji 分段測試 | 本 fork 通知走 Bark（custom webhook），不用 Telegram，實際行為不受影響；程式碼照收，避免日後再衝突 |

## 衝突裁決

| 檔案 | 裁決 |
| --- | --- |
| `src/notification_sender/telegram_sender.py` | import 塊：fork 側多了 `from src.notification_sender.base import OutboundMessage`（Sender protocol 重構），上游側把 `src.formatters` 的 import 擴成 `_custom_unit_to_index, strip_hidden_markdown_metadata, utf16_len`。**兩者都留**：用上游的 formatters import 行，再接 fork 的 `OutboundMessage` import。其餘程式碼自動合併 |
| `docs/CHANGELOG.md` | 自動合併：上游那條 `[修复] Telegram ...` 落在 fork `[Unreleased]` 段末，fork 既有條目全數不動 |

## 靜默降級排查

- 本輪沒有新增或改寫市場集合、語言集合常數；改動只在 Telegram 長度計算，與市場／語言無關
- 沒有新的台股代碼正則、`isdigit()` 判代碼、簡體字詞比對
- 沒有新頂層 package／資料夾，`docker/Dockerfile` 不需調整
- `.env.example` 未被改動；沒有新設定項
- 沒有新依賴；Web 無改動

## 驗證

| 項目 | 結果 |
| --- | --- |
| `ci_gate.sh syntax` / `flake8` | 綠 / 綠（0） |
| 受影響測試（`test_formatters.py`、`test_notification_report_fixtures.py`、`test_notification_sender.py`、`test_notification_sender_protocol.py`、`test_pipeline_notification_image_routing.py`、`test_system_config_service.py`） | 478 passed |
| 全量離線測試 `ci_gate.sh` | 排程未跑；合併前手動補跑：9550 passed、79 skipped、0 failed（4 分 38 秒） |
| 阻斷 CI | 未跑（fork 不開 PR，§6） |

## 回滾

`git revert -m 1 <merge commit>`。無 schema 變更。

## fork 刻意分歧（2026-10-27 補記）

本次修復基線：本地 HEAD 與 fetch 後的 `origin/develop` 皆為 `7093f4b7`，工作樹已在相同基線，無須更新。

- 上游 `e22cf8e1`（#1289）的建議意圖推測不再保留：`infer_decision_type_from_advice` 只保留 `_canonicalize_lookup_value` 的完整標籤查表，移除子字串／否定掃描與專用詞表。結構／三大法人校準及大盤脈絡護欄優先使用模型的結構化 `decision_type`，缺漏時投影 `action`，再試完整標籤；皆未知則沿用各自預設，不讀建議句子補判買賣。`hold` 配買入區分數的既有護欄仍保留。未來同步不得重新加入片語推測或以程式計算值代替模型判斷；契約見 [`decision-signals.md`](decision-signals.md#結構化動作與未知建議)，守門為 `test_report_language.py`、`test_decision_stability.py`、`test_daily_market_context_guardrail.py`。
