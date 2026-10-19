# 上游同步紀錄 2026-10-19（v3.33.0 後第一輪）

## 基線

| | |
| --- | --- |
| 上一次同步基線 | `6cb86d6e`（`docs/upstream-sync-2026-10-14.md` 收的最後一個 commit） |
| 本次上游 HEAD | `7a21cd76`（上游已發 `v3.33.0`，2026-10-15） |
| 吸收 commit 數 | 6（全部；淨 7 檔，+210／−125） |
| 合併方式 | 分支 `chore/upstream-sync-2026-10-19`（自 `main` `2059a9b0`）`git merge upstream/main --no-ff`，不 rebase（§10） |
| 衝突檔 | 2：`docs/README_CHT.md`、`docs/README_EN.md`（`git merge-tree` 乾跑與實際合併一致） |
| 新依賴 | 無 |

## 吸收的上游改動

| commit | 內容 | 對本 fork 的意義 |
| --- | --- | --- |
| `85f8aa11` #2406 | 問股把通過驗證的完整註冊名稱視為一個標的：名稱內部的短別名或類代碼片段不再另立討論對象（`长电科技(600584.SH)` 不再因「长电」觸發澄清）；`chat_object_decision.object_mentions` 新增 `full_name_spans` 過濾，`docs/agent-stream-events.md` 補說明 | 自動合併進 fork 版函式（fork 的繁轉簡謂語比對在其後，不衝突）。用真實索引抽查 `台積電(2330.TW)`、`元大台灣50(0050.TW)`、`富邦金和國泰金比較`、`長榮航(2618.TW)`、`2330.TW 跟 2454.TW`，對象判定皆正確 |
| `bba8bf51` #2412 | 上游 v3.33.0 發版整理 CHANGELOG | 自動合併：上游 Unreleased 條目移入新的 `[3.33.0]` 段，fork 的 `[Unreleased]` 條目全數留在原段，結構正確 |
| `6abf3fef` #2408 | 三語 README 移除 TickFlow 推廣 | 僅文件 |
| `9ff1eab2` #2395、`5457ac81` #2396、`7a21cd76` #2418 | API Route、Opper 渠道預設先合入後被上游整批 revert | 淨零改動 |

## 衝突裁決

| 檔案 | 裁決 |
| --- | --- |
| `docs/README_CHT.md`、`docs/README_EN.md` | 唯一衝突塊是「行情數據／新聞搜尋」兩列：上游移除 TickFlow 推廣、改 Anspire 連結。本 fork 無立場，**衝突塊取上游**，非衝突處 fork 文字不動 |

## 靜默降級排查

- 本輪上游沒有新增市場集合或語言集合常數；#2406 的過濾只依名稱 span 包含關係，與市場／語言無關
- Web 無改動
- `.env.example` 未被改動，`STOCK_INDEX_REMOTE_UPDATE_ENABLED` 等 fork 約定不受影響

## 驗證

| 項目 | 結果 |
| --- | --- |
| `ci_gate.sh syntax` / `flake8` | 綠 / 綠（0） |
| 受影響測試 `tests/test_agent_active_stock_integration.py` | 277 passed |
| 台股／繁體問股對象抽查（真實索引） | 見上表，正確 |
| 全量離線測試 `ci_gate.sh` | 見合併 commit 後的交付說明 |

## 回滾

`git revert -m 1 <merge commit>`。無 schema 變更。
