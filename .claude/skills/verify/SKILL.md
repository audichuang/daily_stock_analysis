---
name: verify
description: 驗證 Daily Stock Analysis 的真實 Web、API、CLI 與 iOS App（模擬器）使用者流程；在功能完成、修復驗收或需要證明測試確實執行時使用，以 ego-browser 操作畫面並保存可追溯證據。
---

# Daily Stock Analysis 驗證

規則真源是根 [AGENTS.md](../../../AGENTS.md)。先讀 [功能索引](features/README.md)，把 scope 對應到全部相關入口與子功能；全面驗證涵蓋十份 map，不以帳戶／入金或逐頁開空畫面代替。每條各記 `passed`、`failed`、`blocked`、`not-run`；缺前置仍保留該條及原因。

完成＝scope 每條都有真實動作、可核對終態或具體卡點、證據與清理。`observed` 只是待核對觀察，不能當通過。修正工具／map 後重跑受影響旅程；產品缺陷如實記錄，不改產品行為來湊通過。長期結論寫 [docs/verification.md](../../../docs/verification.md)。

## Launch

使用既有 `.venv`、uv、Node/npm、Web node_modules 與 ego-browser；launcher 使用 POSIX ps／lsof／fcntl，本輪 macOS 已測。缺相依依 AGENTS 處理。寫入只對本輪 SQLite／設定／cache；正式 NAS、裸 `make serve-local` 或 `make serve` 會碰既有環境，不能替代隔離服務。

整個目標只用一個 ego TaskSpace。先依已安裝 `ego-browser` skill 執行 `ego-browser skill`，建立或沿用本次空間，把回傳數字 id 設為 `DSA_VERIFY_SPACE`。每輪使用新證據目錄：

```bash
export DSA_VERIFY_RUN="$PWD/.claude/reviews/verification/$(date +%Y%m%d-%H%M%S)"
uv run python .claude/skills/verify/scripts/instance.py launch \
  --run-dir "$DSA_VERIFY_RUN" --space-id "$DSA_VERIFY_SPACE"
```

上式是空庫 profile：空 HOME、無市場庫與模型憑證，適合獨立帳戶／入金。分析、看板、四維度與研究需要線上 profile，改用同一 launch 命令加 `--online --symbols 2330.TW,2317.TW`；依 scope 選真代碼，不在已啟動的 run 上重複 launch。

兩種 profile 都複製當前已追蹤來源（含未提交修改）、scripts／journal／Makefile 與股票索引；新增程式先確認進 `git ls-files`。`source-hashes.json` 記身分；`runtime/source/.env` 刻意為空，阻止裸 dotenv 向上搜尋正式憑證。Vite 建置用本輪 outDir、`VITE_API_URL=''` 與同源 API，不覆蓋原 static，不自動安裝依賴。新 SQLite 由真實 DatabaseManager 初始化，uvicorn 用動態 loopback socket；預設關排程、event monitor、遠端索引與匯率更新。

線上 profile 沿用真 HOME／USER／LOGNAME 及 repo 已設定的 CLI backend 非秘密設定，fallback 留空。它使用既有 CLI 登入，CLI 自身仍可能在真 HOME 寫快取／log；不是完整 HOME 沙箱。市場 URL 只注入 child environment，不寫 env／JSON 證據，不注入 Telegram／Shioaji 憑證；日誌另作去敏核對。

線上 `runtime/verification.env` 連空白 `DATABASE_URL` 鍵也不寫：設定儲存會 `setup_env(override=True)`，空鍵會清掉程序內的市場連線。保存設定後用本輪已查得基金 ID 的 `GET /api/v1/funds/search?q=…` 真資料回應核對市場仍可讀。

市場連線有 `PGOPTIONS` 與 SQLAlchemy Engine connect guard 兩層，啟動時核對 `default_transaction_read_only`、`transaction_read_only` 都為 `on`。這保護本 profile 的預期連線，不授權任意 CLI：執行前核對 source／參數／產物位置，尤其 `--env-file`、更新、Doppler、通知、Git 寫入或自行覆寫連線設定的入口。

就緒需 `server.log` 的 `Application startup complete`、`initial-accounts.json` 為空及 Doctor 通過；health 200 不是使用者功能完成。`instance.json` 保存本輪 URL／PID／build／基線，不代表 NAS 版本。

## Doctor

```bash
uv run python .claude/skills/verify/scripts/instance.py doctor --run-dir "$DSA_VERIFY_RUN"
```

核對 bootstrap 所有權與 listen port、health、build；storage／排程／市場唯讀值來自啟動時的 `effective-storage.json`，不是設定保存後即時重做 SHOW。認證期望取自本輪 `runtime/verification.env` 的 `ADMIN_AUTH_ENABLED`，不是永遠要求 false；啟用認證後重新 Doctor 應與新設定相符。異常先保存 `doctor.json`／log，停止依賴該實例的動作並調查；失敗輪也做 Cleanup。

## Drive

按索引選定的 map 逐條做真使用者操作。已知 selectors 用原生 ego API；未知多步控制依 ego-jev 規則處理。先 snapshot 核對目標，用 click／fill／select／submit；API、SQL 只作第二視角，不能以 store setter、插入報告或 mock 回應取代 UI 真生成。關閉通知 checkbox，未授權發訊息的入口保留 blocked；既有授權範圍內繼續，不重問。

報告保存／切換見 [分析與歷史](features/analysis-history.md)；看板連入的摘要／解讀見 [研究資料](features/research-cli.md)，各入口分別留證。

實際翻譯以 snapshot 為準，例如資料中心按鈕是「重新整理」。複製報告時比對主機剪貼簿與 API 內容、操作後還原原剪貼簿，不把原私人內容收進證據。分享海報 API 失敗／缺渲染器就記 blocked，不能以 ego 截圖冒充下載海報。

跨功能在 ego runtime 匯入 [browser.mjs](scripts/browser.mjs)，以本輪絕對路徑 `openRun(directory)` 取得同一 `task`／`page`：

- `act(description, operation)` 保存動作／receipt／錯誤至 `actions.jsonl`。
- `snapshot()` 回安全語意快照；密碼值遮蔽，Save login 等已知密碼管理器提示仍開啟時拒絕保存／回傳。
- `capture(name)` 保存 snapshot 與 PNG；截圖要實際檢視。
- `api(name, route, format)` 保存原始 GET 回應；JSON 是預設，dossier HTML 用 `format="text"`。
- `mark(feature, status, detail)` 追加 `coverage.jsonl`，寫入口、終態與對應 artifact 名稱。

每輪 browser 程式另存本輪目錄的新 `.mjs` 檔，再用 `ego-browser nodejs < 該檔` 執行。跨功能全部共用 TaskSpace，最後才 `task.finish({keep: []})` 一次；[portfolio.mjs](scripts/portfolio.mjs) 內建 finish，只供**單獨空庫 portfolio** scope，不能插進跨功能過程。

登入可能觸發擴充套件 iframe；禁止直接列印原始 `page.snapshot()`。提示仍開啟時先安全關閉，不儲存／更新私人密碼庫，再取得應用證據；受污染的自建證據去敏或移除，乾淨狀態另重拍。

CLI 使用相同 profile，先核對命令再執行；`exec` 本身不審查命令，也不是通用防寫沙箱：

```bash
DSA_VERIFY_PYTHON="$(uv run python -c 'import sys; print(sys.executable)')"
uv run python .claude/skills/verify/scripts/instance.py exec --run-dir "$DSA_VERIFY_RUN" \
  --record dossier-cli -- "$DSA_VERIFY_PYTHON" scripts/tw_stock_dossier.py 2330.TW --no-branch --json
```

`exec` 在來源副本執行，保存命令／起訖／exit 與合併 stdout-stderr；需要分流的命令另留各 stream。不得以 exit 0、202、pending 消失、模板報告或空態判定真生成成功；history ID、模型結果、重整持久化、來源日期及必要副作用依 map 核對。

`exec` 結束後會遮蔽本機市場 URL 與其密碼；檢視其他命令的原始錯誤前仍先去敏，不能假設第三方錯誤安全。

## Evidence

證據留在 `$DSA_VERIFY_RUN`，runtime 清理後仍保留；私人帳本、原始環境、密碼／hash／cookie／token 不提交版控。`RUN_NOTES` 可作交接索引，通過主張必須回到該 run 的 `coverage.jsonl`、原始 artifacts 與斷言；手寫筆記或過去 run 不當本次通過證據。

- 身分：來源 hash、HEAD／dirty／遠端基線、build、隔離摘要、Doctor、PID／URL、起訖時間。
- 動作：輸入／click receipt、前後 PNG／snapshot；寫入核對 UI、API、SQLite 同一實體 ID／值，重整後再讀。
- 終態：真模型 task／history／session ID、資料 source／as_of、檔案或 DB 列。模型回覆與 provider usage 各自核對，不能造 token seed。
- 測試：命令、log、exit、collected／passed／failed／skipped、JUnit；全 skip／只 collect 不算已測。
- 層級：單測、API fixture、真本機服務、正式環境分開回報；CI fixture 綠不推論模型／行情／通知送達。dry-run 另比對檔案、網路、DB、Git refs 前後狀態。

語法／lint／定向測試與真操作各自留證；全量離線套件依 AGENTS 確認後才跑。守修法的測試做正反 mutation。缺前置記 blocked 並完成不依賴它的 scope；不把 journey 改短以消除失敗。

## Cleanup

全部 browser 工作完成才 finish 同一 TaskSpace；失敗時留在同一空間調查，使用者接管依 ego handoff。保存跨功能 coverage 後執行：

```bash
uv run python .claude/skills/verify/scripts/instance.py cleanup --run-dir "$DSA_VERIFY_RUN"
```

私有 0600 `local-cli.registry` 登記本輪 CLI PGID；Cleanup 先封閉登記、清理登記群組，再停本輪 bootstrap。TERM 未退出才對仍屬本輪的群組 KILL；絕不按程序名稱 kill。PID／registry／port 異常保留 runtime，不能跳過檢查刪現場。登記格式見 [process_registry.py](scripts/process_registry.py)。

停止後 SQLite 備份為 `application-evidence.sqlite3`，帳戶／入金列匯出 `portfolio-rows.json`；其他功能所需列／cache 在刪 runtime 前另保存。最後核對 `cli-cleanup.json`、`cleanup.json`、port 釋放及全部畫面／API／DB／coverage 證據仍可讀。被殺的未完成任務標失敗／中止，不能因清理成功改標功能通過。

## Helpers

[ios_sim.sh](scripts/ios_sim.sh)：依名稱解析與啟停 DSA 唯一的模擬器（fixture 與手動共用）。

[instance.py](scripts/instance.py)：上述 `launch|doctor|cleanup|exec --run-dir`；launch 支援 `--space-id`、`--online`、`--symbols`。單獨空庫 portfolio 可用 launch 產生的 `drive-portfolio.mjs`；其他 scope 使用 `browser.mjs` 共用記錄與 TaskSpace。helper 皆可執行，錯誤先留 log，修具體原因再驗受影響路徑。

改動 helper 後執行 `uv run python .claude/skills/verify/scripts/check_helpers.py --output-dir "$DSA_VERIFY_RUN/helper-tests"`。
[check_helpers.py](scripts/check_helpers.py) 使用合成憑證／自有暫存檔，驗環境邊界與去敏；不替代真服務 journey。
瀏覽器 helper 改動另跑 `node .claude/skills/verify/scripts/check_browser.mjs --output-dir "$DSA_VERIFY_RUN/browser-helper-tests"`；
[check_browser.mjs](scripts/check_browser.mjs) 用合成 Page SDK 與自有暫存檔驗保存、遮蔽及阻擋提示，含正反 mutation。

行為回歸案例見 [evals.json](evals/evals.json)，依操作與 artifacts 評分，不比對回答措辭。後續用 `/maintain-verification-skill` 保持 map 與 source 一致；審查／修復第三輪仍有 finding 依 AGENTS 收斂。
