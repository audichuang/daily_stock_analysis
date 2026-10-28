# 真實使用者流程驗證

專案驗證入口是 [verify skill](../.claude/skills/verify/SKILL.md)，功能範圍見 [feature map](../.claude/skills/verify/features/README.md)。它補足 lint／單測與使用者實際操作之間的證據，不把所有測試稱為端到端。

## 執行與證據

從 repo 根目錄執行；需要既有 Python `.venv`、uv、Node/npm、Web node_modules 及 ego-browser。缺相依依 `AGENTS.md` 處理，不由 helper 自動安裝。

```bash
export DSA_VERIFY_RUN="$PWD/.claude/reviews/verification/$(date +%Y%m%d-%H%M%S)"
uv run python .claude/skills/verify/scripts/instance.py launch --run-dir "$DSA_VERIFY_RUN"
uv run python .claude/skills/verify/scripts/instance.py doctor --run-dir "$DSA_VERIFY_RUN"
ego-browser skill
ego-browser nodejs < "$DSA_VERIFY_RUN/drive-portfolio.mjs"
uv run python .claude/skills/verify/scripts/instance.py cleanup --run-dir "$DSA_VERIFY_RUN"
```

已有本次目標的 TaskSpace 時，launch 加 `--space-id` 沿用它。driver 成功後結束該空間；失敗保留同一空間調查，重跑用新的 run-dir。每輪失敗也清理自己的 server/runtime，證據留下。

每個 run 保存來源 hash、HEAD／dirty／遠端基線、build 身分、隔離設定、完整 log、操作 receipt、輸入與結果 PNG／snapshot、API 回應、SQLite 備份及清理結果。PNG 要實際檢視；寫入要串起 UI、API、DB 的同一 account ID。證據在 `.claude/reviews/verification/`，不進版控；長期結論留在本文件。需要分享時先確認不含私人資料。

Launcher 複製當前已追蹤程式與股票索引到暫存來源，使用真實 `create_app`、uvicorn、空 SQLite。後端使用空 HOME／獨立 env／變數 allowlist，停用排程、通知憑證與遠端索引；前端建置明確清空 `VITE_API_URL`，指向同源 API。AkShare 暖機仍可連公開網路，寫入只落來源副本。這不是正式 NAS 或零網路環境，也不驗模型／Shioaji 登入。

## 首輪範圍與來源

整理依據是 `AGENTS.md`、`docs/tw-operating-guide.md`、`docs/daily-report-ops.md`、看板／四維度／資料中心文件、目前 routes／Makefile／測試，以及可取得對話「研究持股趨勢與年底停利策略」（thread `01a180d4-5306-7da2-820b-12335e53b66d`）。該對話要求分清帳本與自選、盤中價與昨收籌碼、資料日期與來源，已轉為證據要求；研究結論不算本輪測試。`codex-his.txt` 為空，更早對話未取得。

產生器附帶的 `../poteto-mode/references/codex-tools.md` 在本機缺少；本輪使用當前 Codex 工具與實際 `ego-browser skill` v2.1.0 指南完成操作。新 skill 本身不依賴該缺失檔案。

基線：本地 HEAD 與 `origin/develop` 均為 `96df37621ffb52340579e065c435c36b5d62fbb8`。fetch 後因既有未追蹤 `codex-his.txt`、`journal/morning-arms.jsonl`，未 pull、stash 或改動它們；另建工作分支。

## 實跑紀錄（2026-10-28）

最終完整自證在 `.claude/reviews/verification/20261028-verify-03/` 通過；保留 5 張 PNG，已檢視保存後與重整畫面。browser TaskSpace 37 已結束，PID 61465 與 port 62598 已釋放，runtime 已移除。`proof-check.json` 核對備份 SQLite 的帳戶與入金列；清理後證據仍存在。下列覆蓋不代表其他 journey 通過：

- 真實服務 journey：空帳本 → 建帳戶 `VERIFY-20261028-verify-03`（ID 1）→ 今天入金 12345 CNY → 資金流水 → reload → API/SQLite 核對 → 清理，通過。實際畫面顯示總權益／總現金 `CNY 12,345.00`；UI 呼叫本機 API 的 POST/GET 在 `server.log` 可核對。
- 隔離反向案例：父環境故意設 `VITE_API_URL=https://example.invalid`，最終 browser 仍成功操作本機 API／SQLite；`build-isolation.json` 記明實際 build 使用空值。
- 定向測試：`tests/test_analysis_history.py`、`test_notify.py`、`test_local_cli_backend.py`、`test_structured_decision_action.py`、`test_decision_signal_api.py`，**659 passed、0 skipped、8 warnings、exit 0**（pytest 33.46 秒）；命令、exit code、JUnit 與 log 在 `targeted-20261028/`。通知 transport／LLM CLI 在這些測試中有替身，不證明外部服務送達或真生成。
- 快速門檻：`scripts/check_ai_assets.py`、`ci_gate.sh syntax`、`ci_gate.sh flake8`、helper Python 編譯與 Node 語法檢查均通過；skillgenie lint 為 `0 FAIL, 0 WARN, 0 NOTE`。
- 建置失敗 cleanup：`20261028-build-failure/` 以 npm 邊界替身故意 exit 7；launcher 非零退出、沒有啟動程序、自動移除 runtime、保留 build log，再執行 cleanup 仍成功。正反 mutation（原始碼只在記憶體變異）驗證：移除失敗清理會被抓到，過度刪掉整個 run 連證據也刪掉同樣會紅，結果在 `mutation.json`。這項只驗 helper 的失敗路徑，沒有冒稱 app 測試。

建立技能時的冷讀比較涵蓋三情境：空庫 Web、缺模型／歷史前置資料、每日報告通知。未有技能時能推導大部分隔離步驟，但沒有已實跑 launcher、證據串接或共同 cleanup；新 skill 將這些步驟做成可執行 helper。這是設計審查與一條真實 journey 的自證，尚未量測跨模型觸發率。

已捕捉的失敗保留原始 log：`20261028-verify-01` 的 macOS multiprocessing 入口重入，修正 bootstrap main guard；`20261028-verify-02` 入金確實成功但 driver 等錯 `tr`，修正為實際資金流水元素。未將它們算成完整通過。

## 未驗證與後續

- 正式 NAS 的部署、容器 COPY、Doppler、認證與資料遷移沒有被本機路徑驗到。
- 台股交易、跨幣別、曝險、報告生成與歷史匯出、即時行情來源、四維度敘事、盤前／每日排程及 Telegram 送達尚未實跑。缺必要資料記 `blocked`，未選到記 `not-run`；不以 mock/空頁取代。
- feature map 索引另列未種完整 journey 的其他頁面；改到時先補 map 再跑。完整離線套件未跑，本輪只跑定向測試。
- CI `.github/workflows/ci.yml` 的 Web fixture 會攔截 API；預設 smoke 沒有密碼時真後端案例會 skip。綠燈的含義依該 run 原始輸出，不等於真報告生成／訊息送達。
- 現有後端相依、前端相依由本機提供；空機安裝、Python 3.11、正式市場資料與外部模型仍待對應環境驗證。

本次只加驗證資產與文件，回滾可 revert 此次 commit；runtime 已清理而 evidence 留在本機。沒有變更 `.env`、正式庫、排程、infra 或依賴。中英文文件索引同步加入入口；驗證細節使用本 fork 的繁體中文，沒有新增英文副本。後續用 `/maintain-verification-skill` 維護 map；新增產品行為時把旅程及證據要求一起更新。
