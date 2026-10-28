---
name: verify
description: 驗證 Daily Stock Analysis 的真實 Web、API 與 CLI 使用者流程；在功能完成、修復驗收或需要證明測試確實執行時使用，以 ego-browser 操作畫面並保存可追溯證據。
---

# Daily Stock Analysis 驗證

規則真源是根目錄 [AGENTS.md](../../../AGENTS.md)。先讀 [功能索引](features/README.md)，按改動選 journey；每個入口分別記錄 `passed`、`failed`、`blocked`、`not-run`。完成＝選定 journey 的動作、畫面、真實副作用、清理都有證據；一條通過只證明該條。

## Launch

主要介面是 Web/API；CLI、台股資料與每日排程依功能檔另驗。使用已有 `.venv`、`uv`、Node/npm、`apps/dsa-web/node_modules`；缺相依按 AGENTS 的安裝邊界處理。不要用正式 NAS、`make serve` 或裸 `serve-local` 做寫入 smoke：本機 `.env` 指向正式 `dsa`，讀取快照也可能寫入。

從 repo 根目錄執行（每輪用新目錄）：

```bash
export DSA_VERIFY_RUN="$PWD/.claude/reviews/verification/$(date +%Y%m%d-%H%M%S)"
uv run python .claude/skills/verify/scripts/instance.py launch --run-dir "$DSA_VERIFY_RUN"
```

已有本次目標的 ego TaskSpace 時加 `--space-id <已取得的數字 id>`，整個目標沿用同一空間。

Launcher 將當前已追蹤後端原始碼及股票索引複製至 `runtime/source`，記每檔 SHA256（含未提交修改；新增程式先 `git add` 才會被複製）。使用既有 npm build，但 `--outDir` 指到本次 `runtime/web`、明確設 `VITE_API_URL=''` 保持同源 API，避免 shell 或 Vite dotenv 指到正式站；不安裝相依、不覆蓋 repo `static/`。後端空環境檔、空 HOME、環境變數 allowlist 排除正式憑證；新 SQLite 自動建立 schema，空帳戶即為此 journey 的種子。透過真實 `create_app` 與 uvicorn 啟動，動態 loopback socket 不共用 port。

就緒需 `server.log` 的 `Application startup complete`、`initial-accounts.json` 是空陣列，且下一步 Doctor 通過；只有 health 200 不足。`instance.json` 保存 URL、PID、HEAD、遠端基線、dirty 狀態、build revision/fingerprint。Web 與程式都取本次 checkout，不代表 NAS 發版。

此路徑關閉排程、索引遠端更新、認證及匯率更新。AkShare 啟動暖機仍可能連公開網路，快取只落來源副本；這不是離線測試。行情／模型／Telegram／market 資料能力尚未驗證，不可替換 mock 宣稱通過。

## Doctor

```bash
uv run python .claude/skills/verify/scripts/instance.py doctor --run-dir "$DSA_VERIFY_RUN"
```

這是唯讀檢查：核對本次 bootstrap PID、該 PID 持有的 listen port、實際 SQLite URL、排程停用、health、認證停用與 build-info 完全一致，輸出 `doctor.json`。Launch 已初始化資料庫；Doctor 不靠首次存取來建 schema。異常先跑此命令，失敗就停止 drive，查看 `server.log`，每次失敗也執行 Cleanup。

## Drive

畫面一律使用 ego-browser。先讀已安裝的 `ego-browser` skill，再執行 `ego-browser skill`，以當版 API 為準。已有已知 selectors 的 journey 使用原生 ego API；未知多步控制依 ego-jev 規則處理。首次只驗證安全且可從空資料完成的 [持股帳本](features/portfolio.md)：

```bash
ego-browser nodejs < "$DSA_VERIFY_RUN/drive-portfolio.mjs"
```

它呼叫 [portfolio.mjs](scripts/portfolio.mjs)：空帳本 → UI 建帳戶 → UI 入金 12345 CNY → 切資金流水 → 重整 → GET 核對。所有寫入經真實 UI，API 僅作第二視角。selectors 源自 `PortfolioPage.tsx`；變更時先 snapshot 核對，不以 DOM setter、store 操作或注入 SQL 取代旅程。查看產出的 PNG，確認畫面可讀及數字正確。

其餘依改動選：[分析與歷史](features/analysis-history.md)、[即時看板](features/realtime.md)、[台股資料與研究](features/research-cli.md)、[每日作業](features/daily-ops.md)。前置資料不足就保留失敗與原因，不把完整旅程降級成只驗空畫面。

## Evidence

證據在 `$DSA_VERIFY_RUN`（`.claude/reviews/verification/` 已 gitignore），Cleanup 後保留；長期摘要寫進 `docs/verification.md`，不把私人帳本、憑證或正式報告提交版控。

- 身分：HEAD、來源檔 hash、dirty 狀態、環境隔離摘要、build-info、Doctor、PID/URL、起訖時間。
- 操作：每次動作的時間與 receipt（`actions.json`）、輸入前後 PNG 與 full-page snapshot；截圖需實際檢視。單一最終截圖無法證明怎麼到達。
- 結果：真實 API response、重新整理後畫面；寫入另核對 SQLite `portfolio-rows.json` 與保留的 `application-evidence.sqlite3`。帳戶名稱／ID、現金列、日期／金額／幣別需一致。
- 測試：命令、stdout/stderr、exit code、起訖時間、collected/passed/failed/skipped 數與 JUnit。全 skip、只 collect、HTTP 202、模板報告或程序 exit 0 均不能當功能成功。
- 層級：單測、API fixture、真實本機服務、正式環境分開回報。CI 的 `web-ui-evidence-*` 目前含 API fixture；依該 run 原始輸出判定，不能推論真模型、行情或訊息送達。Mock 只用於產品已有的外部邊界，並揭露替身。

語法/lint、targeted tests 與使用者操作各自保存，完整離線套件依 AGENTS 確認後才跑；修復型 guard 測試需正反 mutation。若驗 dry-run，另比對檔案、網路、DB、git refs 的前後差異，不能信名稱。

## Cleanup

成功的 browser driver 會 `task.finish({keep: []})` 一次；失敗保留同一 TaskSpace 調查，不另開空間。放棄失敗輪次時，在同一空間完成清理並留下原因；使用者接管時遵循 ego handoff，不能強制奪回。

```bash
uv run python .claude/skills/verify/scripts/instance.py cleanup --run-dir "$DSA_VERIFY_RUN"
```

只對驗證 bootstrap 所有的 process group 發 SIGTERM，禁止依程序名稱 kill。停止後備份本次 SQLite、匯出證據列、記 AkShare 快取是否生成，刪自己的 `runtime/`。若 PID 身分或 port 有異常就保留現場調查。執行後確認 `cleanup.json`、PNG、actions、API/DB 證據仍存在；`browser-result.json`、`browser-cleanup.json` 與 DB 斷言都通過才回報 journey 完成。

## Helpers

[instance.py](scripts/instance.py) 提供上述 `launch|doctor|cleanup --run-dir`；`launch --space-id` 可重用本次 TaskSpace。[portfolio.mjs](scripts/portfolio.mjs) 只在 ego runtime 執行，入口由 launch 產生。兩者皆可執行，無額外安裝需求。helper 輸出失敗時保留 log，修正具體原因再用新 run-dir 重跑；審查／修復第三輪仍失敗依 AGENTS 收斂。

後續功能變動用 `/maintain-verification-skill` 同步 feature map；本輪覆蓋與限制見 [驗證紀錄](../../../docs/verification.md)。
