# 上游同步紀錄 2026-10-26（v3.33.0 後第三輪）

## 基線

| | |
| --- | --- |
| 上一次同步基線 | `ec66bf46`（`docs/upstream-sync-2026-10-21.md` 收的最後一個 commit） |
| 本次上游 HEAD | `4e622643`（上游最新發版仍是 `v3.33.0`，不在本輪範圍內） |
| 吸收 commit 數 | 5（全部；75 檔，+4129／−6217，大半是移除 Codex App Server 後端） |
| 合併方式 | 分支 `chore/upstream-sync-2026-10-26`（自 `develop` `88f75a48`）`git merge upstream/main --no-ff`，不 rebase（§10） |
| 衝突檔 | 4：`.github/ci-test-durations.json`、`apps/dsa-web/src/pages/ChatPage.tsx`、`main.py`、`tests/test_stock_watchlist_api.py` |
| 新依賴 | **`fastapi-guard>=8.1.1`**（`requirements.txt`；排程未安裝，見下） |
| 觸發 | precheck：上游待同步 5 個 commit（達門檻 5） |

## 吸收的上游改動

| commit | 內容 | 對本 fork 的意義 |
| --- | --- | --- |
| `a952f784` #2424 | 新建 MiniMax 文字渠道預設 `MiniMax-M3.1-Flash`／`MiniMax-M3`，過濾舊推薦、保留已存／自訂模型，更新 fallback 計價 | fork 生成走本機 Claude Code CLI，不用 MiniMax；只影響 Web 設定頁的渠道範本，照收 |
| `b19d4b99` #2416 | 可選的 fastapi-guard 安全中介層（`GUARD_ENABLED=true` 才啟用，預設關閉）：按 IP 限流、白／黑名單、請求特徵攔截、掃描器自動封鎖；新增 `api/middlewares/security_guard.py`，`server.py`／`webui.py` 依 `TRUST_X_FORWARDED_FOR` 設 Uvicorn 代理頭 | `guard` 套件只在啟用時才 import，預設關閉時缺套件也不影響啟動。NAS 映像下次重建會照 `requirements.txt` 裝上；本機 venv 未裝，`tests/test_api_security_guard.py` 會紅（見驗證）。NAS 在反向代理後，日後要開 guard 須先設 `TRUST_X_FORWARDED_FOR=true` 與 `GUARD_TRUSTED_PROXIES` |
| `24685389` #2402 | `python main.py --schedule` 啟動立即執行的當日去重（`SCHEDULE_STARTUP_DEDUP`，預設開）：標記檔 `data/analysis_run_state.json`（`DATABASE_PATH` 所在目錄），當天已有成功且覆蓋應分析清單的全量分析就跳過啟動補跑；新增 `src/core/analysis_run_marker.py` | fork 每日報告走 launchd 腳本、NAS 走 Web 內排程，不常用 `--schedule`；但閘門的「預期清單」原本沒併入 fork 的持股帳本（`ANALYZE_PORTFOLIO_HOLDINGS`），本輪補上（見靜默降級排查） |
| `88ec4bae` #2422 | 移除實驗性 Codex App Server 問股後端（`src/agent/codex_*.py`、`scripts/codex_app_server_gate_a.py` 與對應測試），`SUPPORTED_AGENT_BACKENDS` 收斂為 `auto`／`litellm`，舊值 `codex_app_server` 在設定驗證與儲存時被拒、Web 顯示「已移除」；問股的「停止分析」按鈕（Codex 專屬）一併移除 | 本機 `.env` 沒設 `AGENT_BACKEND`（預設 `auto`），不受影響。**NAS 正式站若設了 `AGENT_BACKEND=codex_app_server`，問股會被擋**——排程無法確認 NAS 設定，部署前請看一眼。fork Python 端沒有引用被刪的模組 |
| `4e622643` #2423 | 自選股儲存不再被無關的 LLM 設定錯誤阻擋（模型相關修改仍完整驗證）；僅更新自選時保留執行期單例與容器環境覆蓋 | 對 NAS 有利（容器 env 覆蓋 `STOCK_LIST` 時新增／刪除自選不會被吃掉）；fork 的 asset-aware 自選比對（`_watchlist_match_key`）與台股帶字母代碼的測試全數保留並通過 |

## 衝突裁決

| 檔案 | 裁決 |
| --- | --- |
| `.github/ci-test-durations.json` | 取 fork 版（10-23 自 fork CI 重新擷取，含 `market_data/tests` 等 fork 測試）。上游新增測試檔沒有時長紀錄，分片時用預設值，不影響正確性；已刪除的兩個 codex 測試條目也還留著（分片器會忽略不存在的檔）。下次重擷取時一併更新 |
| `apps/dsa-web/src/pages/ChatPage.tsx` | 空狀態：fork 的 `title={t('chat.emptyTitle')}`（三語文案）＋上游的 `description={t('chat.emptyDescriptionDefault')}`（Codex 分支已移除）。標題列的 Badge 與送出按鈕自動合併為「上游邏輯＋fork 的 `t()` 文案」 |
| `main.py` | 兩個新函式都留：fork 的 `_merge_portfolio_holdings` 與上游的 `_resolve_gate_expected_stock_codes`，並另開 commit 讓後者也併入持股（見下） |
| `tests/test_stock_watchlist_api.py` | 兩邊都留：import 取聯集（fork 需要 `_watchlist_match_key`，上游需要 `os`／`patch`／`Config` 等）；fork 的 ASCII 閘門、台股帶字母代碼、指數與同碼個股共存測試接在前，上游三個「保留容器環境覆蓋」測試接在後 |
| `docs/CHANGELOG.md` | 自動合併：上游 7 條落在 fork `[Unreleased]` 段末（與前幾輪相同位置），fork 既有條目全數不動 |

## 靜默降級排查

- **市場／語言集合**：上游新增的集合只有 `SUPPORTED_AGENT_BACKENDS = {"auto", "litellm"}`（後端名，與市場／語言無關）；測試裡的 `market_review_region: "cn"` 只是固定值。沒有新的 `cn`／`hk`／`us` 並列、`zh-CN` 判斷或 `*_MARKETS`／`*_LANGUAGES`
- **簡體字詞比對、預設 A 股**：無
- **台股代碼正則／`isdigit()`**：無新增；自選 API 的台股帶字母代碼測試（`00631L.TW`、`2887A.TW`）合併後照綠
- **新頂層 package／資料夾**：無（新檔都在既有的 `api/middlewares/`、`src/core/`），`docker/Dockerfile` 不需調整
- **`.env.example`**：上游只改 `AGENT_BACKEND` 註解、新增 `SCHEDULE_STARTUP_DEDUP=true` 與一段註解掉的 `GUARD_*`；`STOCK_INDEX_REMOTE_UPDATE_ENABLED` 等 fork 約定未被動到
- **新依賴**：`fastapi-guard>=8.1.1`，未安裝
- **Web zh-TW 字典**：上游刪了 22 鍵（Codex 專屬文案與「停止分析」）、新增 3 鍵（`settings.agentBackendRemoved`、`settings.agentBackendRemovedLabel`、`chat.historicalCodexBackendBadge`），另改寫 2 鍵的說明。zh-TW 是 `Record<UiTextKey, string>`，少鍵多鍵都會讓 `tsc` 失敗。**已修**（commit `7a28c412`）：刪 22 鍵、補 3 鍵繁體、2 鍵說明改成新語意
- **啟動去重閘門漏看持股**：上游 `_resolve_gate_expected_stock_codes` 宣稱與 `run_full_analysis` 的目標解析鏈一致，但 fork 的 `run_full_analysis` 對設定清單還會併入持股帳本。閘門少併這一步，當天新增的持股會被判成「當日全量已覆蓋」而跳過啟動補跑。**已修**（commit `e29e9d25`）：設定清單路徑（`stock_codes is None`）也走 `_merge_portfolio_holdings`，明確指定代碼時不併；新測試 `test_startup_gate_expected_codes_mirror_the_run_holdings_merge` 做過雙向 mutation（拿掉修法紅、改成無條件併入也紅）
- **Uvicorn 代理頭**：#2416 讓 `main.py`／`server.py`／`webui.py` 的 `uvicorn.run` 帶上 `uvicorn_proxy_kwargs()`，但它在 `GUARD_ENABLED` 未開時回 `{}`，NAS（反向代理後）預設行為不變
- **啟動去重的作用範圍**：只在 `python main.py --schedule` 生效；NAS compose 的 `server` 服務跑 `--serve-only`，不受影響
- **`src/AGENTS.md`** 還寫著 `codex_app_server` 走本機 Codex，已更正（commit `1addc0c5`）

## 驗證

| 項目 | 結果 |
| --- | --- |
| `ci_gate.sh syntax` / `flake8` | 綠 / 綠（0） |
| 受影響測試（上游改到的測試檔＋ import 了本輪改動模組的測試＋`test_main_portfolio.py`，共 110 檔） | 5063 passed、19 failed |
| 上述 19 個失敗 | 全在 `tests/test_api_security_guard.py`，原因皆為 `ModuleNotFoundError: No module named 'guard'`——**需安裝依賴**，不是回歸 |
| Web `npm run lint` / `tsc -b` / `npm run build` | 0 error（1 個既有 warning）/ 綠 / 綠（借主 checkout 的 `node_modules`，`package.json` 本輪未變） |
| Web 受影響 vitest（ChatPage、settings 元件、agentChatStore、api、SettingsPage、i18n） | 22 檔、439 passed |
| `scripts/check_ai_assets.py` / `tests/test_fork_infra_docs_contracts.py` | OK / 10 passed |
| 全量離線測試 `ci_gate.sh` | **未跑**（§1 要先確認）；合併前請先 `uv pip install -r requirements.txt` 裝上 `fastapi-guard` 再跑 |
| 阻斷 CI | 推分支後由 push 觸發（`chore/**` 在 `ci.yml` 的 `on:` 清單內；CI 會照 `requirements.txt` 裝 `fastapi-guard`）；排程不等結果，合併前看該 run |

## 回滾

`git revert -m 1 <merge commit>`，三個補洞 commit 可各自 `git revert`。無 schema 變更；`SCHEDULE_STARTUP_DEDUP` 只寫 `data/analysis_run_state.json`，刪檔即重置。
