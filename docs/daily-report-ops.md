# 本機排程與每日報告維運

本 fork 的 LLM 重活（盤前判讀、每日報告、持股建議、上游同步）都跑在本機，由 Orca automation 觸發；Web 服務另跑在 NAS（見 `docs/nas-deploy.md`）。每日報告怎麼讀、手動跑哪個 target，見 `docs/tw-operating-guide.md` §2.3；台股資料更新那一段（`daily` → `health --strict`）見 skill `update-market-data`。

## 通知：Telegram 群組的主題

所有推播發到 Telegram 群組「台股管家」（bot `@audi_tw_stock_bot`），依用途分主題，各主題可在手機上分開靜音。憑證與 id 在 Doppler `shioaji/dev`：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`、`TELEGRAM_TOPIC_<主題>`。

| 主題（`--topic`） | 誰會發 |
|---|---|
| 🌅 盤前判讀（`morning`） | 07:30 盤前判讀；18:00 盤前判讀回驗的摘要 |
| ⚡ 盤中提醒（`intraday`） | 10:00／13:00 持股觸發；`kr_tw_memory_watch.py`；`make serve` 的價格警報（NAS 要另設環境變數） |
| 📊 每日報告（`report`） | 18:00 `main.py` 的個股分析與大盤複盤；`make review-tw` |
| 📋 持股計畫（`plan`） | 19:00 明日持股計畫 |
| 📺 媒體點名（`media`） | 23:00 媒體點名摘要 |
| 🔧 系統通知（`system`） | 所有失敗、逾時、卡鎖、部分失敗；上游同步待審 |

- 腳本與排程一律經 `make notify TOPIC=<主題> TITLE=<標題>`（內文走 stdin）或 `scripts/notify.py`；`daily_report.sh` 的 `notify_failure BODY [TITLE] [TOPIC]` 預設 `system`，整次呼叫上限 `NOTIFY_TIMEOUT_SECONDS`（預設 60，只供手動覆寫），未送出的原因與 WARN 寫進該輪 log。
- `main.py` 走上游的通知系統，一個行程只發到一個主題（`TELEGRAM_MESSAGE_THREAD_ID`），由 Makefile／`daily_report.sh` 從 `TELEGRAM_TOPIC_*` 帶入。
- 重建群組或主題時，bot 要是**管理員**且有「管理主題」權限才能用 API 建主題；成員權限裡的「Create Topics」不夠（`createForumTopic` 會被拒）。
- 成功判準是印出 `[notify] <主題>: 已送出` 且結束碼 0；缺憑證或缺該主題的 id 一律拒送回 1（不會退到群組預設主題）。Doppler 的 `BARK_URL` 保留作回退，程式已不再讀它。

## 排程一覽

| 時間（台北） | 做什麼 | 流程正本 |
|---|---|---|
| 平日 07:30 | 盤前判讀（`make morning` 內含「昨晚媒體點名」一段：`scripts/media_picks_brief.py` 唯讀濃縮最近一輪 `media-picks-verdicts.jsonl`，持股相關、research、watch 翻轉條件；只是線索，失敗不影響 `make morning`），寫 `journal/` 兩個 jsonl；只 commit＋push 這兩個檔到 `develop`（讓預測當天進版控；git 權限見根 `AGENTS.md` §1） | skill `tw-morning-call` |
| 每日 08:30 | 上游同步：上游累積 ≥5 個未收 commit 才動手，只產出待審分支 `chore/upstream-sync-<日期>` 並推「系統通知」主題，**不碰 `develop`／`main`**；該分支合進 `develop` 前就是下一輪的鎖，排程會一直記成 skipped | skill `dsa-upstream-sync`（precheck 在它的 `scripts/`） |
| 平日 10:00／13:00 | 持股盤中對照即時價，有觸發才推「盤中提醒」主題 | skill `portfolio-check` |
| 平日 18:00 | `make daily-report-detached`（`scripts/daily_report.sh`）；資料健檢後先跑盤前判讀回驗（`scripts/verify_morning_calls.py --append`）：新結果追加到 `journal/morning-calls-outcomes.jsonl`、只 commit 這個檔再經 `media_picks_job.sh --push-journal` 守門推到 `develop`，摘要推一則「盤前判讀回驗」到「盤前判讀」主題；這一步**非致命**，失敗只記 WARN＋系統通知，不擋報告（逾時 `MORNING_VERIFY_TIMEOUT_SECONDS`，預設 900，只供手動覆寫） | 本檔下兩節；回驗欄位見 `journal/README.md` |
| 平日 19:00 | 持股：寫隔日條件式計畫（接在每日報告後） | skill `portfolio-check` |
| 平日 23:00 | 媒體點名：排程先跑 `make media-picks-detached`（`scripts/media_picks_job.sh`，脫離 session 在背景跑完）：同步 `develop`（fetch＋ff-only；上一晚 push 被拒而留下純 journal 的本地 commit 時 rebase，其餘一律失敗；git 網路呼叫各 120 秒逾時，`MEDIA_PICKS_GIT_TIMEOUT_SECONDS`）→ `make media-picks` 抓 25 個財經頻道的完整版、寫 `journal/media-picks.jsonl` → `make ptt-picks` 抓 PTT 股票板 `[標的]` 文、寫 `journal/ptt-picks.jsonl` → **只** commit＋push 這兩個檔到 `develop`（commit／push 前再確認主 checkout 仍在 `develop`、領先 `origin/develop` 的 commit 全只動 `journal/` 且無 merge，否則記 `journal push=fail` 並推系統通知，不會把人留下的其他 commit 推上去；不 autostash，工作樹有未 commit 的改動時 rebase 會拒絕、照 fail 處理） → 唯讀讀持股清單（`scripts/portfolio_codes.py`，應用庫 portfolio、逾時 60 秒 `MEDIA_PICKS_HOLDINGS_TIMEOUT_SECONDS`；寫 `logs/media_picks_job_<id>.holdings.json`，log 記 `RESULT holdings=<路徑>`；**失敗不算本輪失敗、不推通知**，記 `RESULT holdings=none (原因)` 後照常產摘要，只是少了持股那一段） → `scripts/media_picks_summary.py` 整理證據（帶 `--holdings`；腳本不下結論，多空中性都收；索引第一段是「你的持股被點名 N 檔」，有看空講者或看空 PTT 文的持股加 ⚠，判讀時優先看這段並在推播點出；「持股清單取不到」＝這輪沒標示，不要當成沒被點名）：JSON、約 20 KB 的精簡索引（給主 agent 挑檔），單一檔的完整原話、數據與之前被點名的紀錄用 `--code` 取；任一步失敗腳本自己推系統通知（agent 可能已經不在）。`--detach` 先選好 run id（環境變數 `MEDIA_PICKS_RUN_ID` 傳給子行程）並印一行 `log: logs/media_picks_job_<id>.log`，排程的 Claude 等這個確切路徑、不要找「最新的 log」（子行程建檔前那會是上一晚的）；log 內 `RESULT since=` 不論摘要成敗都會記。鎖 `logs/.media_picks_job.lock` 與每日報告共用 `acquire_lock`：持有者還活著且鎖齡超過 `MEDIA_PICKS_STALE_LOCK_SECONDS`（預設 10800）→ log `FAILED:`＋系統通知、exit 1；沒過期 → 跳過並保留 log（記「本次不重複跑」）。接著排程的 Claude 判讀：覆核代號沒把握的點名（語音誤字、全名對不到索引），結論追加到 `journal/media-picks-review.jsonl`；讀索引挑最多 8 檔，在前景跑一次 `scripts/media_picks_judge.py`（帶 `--since <RESULT since=> --log <本輪 log>`，沒帶 `--log` 下一輪就看不到這次判斷的成功／失敗紀錄）：一檔一個 `claude -p` 平行讀 `--code` 的原話與 `scripts/tw_stock_dossier.py` 的資料包（不用 Agent 工具：Orca 排程裡它在背景跑，主 agent 一結束回合等通知，Orca 就收掉 terminal，2026-10-25 實跑踩到；同理等擷取也要在前景），，逐檔判斷 `research`／`watch`／`avoid` 並寫出論點、引用數字、風險與翻案條件；主 agent 檢查格式、限 research 最多 3 檔後追加到 `journal/media-picks-verdicts.jsonl`（每列帶 `since`；起點用 `media_picks_summary.py --since <RESULT since=> --judge-since` 算，上一輪判讀中斷時會往前涵蓋；某輪只判了一部分（逾時、`ok: false`、主 agent 寫到一半被收掉）不靠腳本規則補：索引末段「前幾輪點名過、判斷檔沒有涵蓋的檔」列出每輪點名數、判斷列數，以及 `media_picks_judge.py --log <本輪 log>` 記在 log 的 `JUDGE` 判斷紀錄（判斷過卻沒寫進判斷檔的逐檔列出），完整清單用 `--unjudged`，由排程的 Claude 決定要不要把哪幾檔放進當晚的判斷、仍受 8 檔上限（補判的檔 `--code` 會附上前幾輪的舊原話與 PTT 文，逐檔判斷也會帶舊講者的過去紀錄）；push 用 `media_picks_job.sh --push-journal`，由腳本守門只推 journal commit），**先 commit 再推「媒體點名」主題**（第一行固定註明僅供參考）。一輪約 40 分鐘，`--since` 預設 4 天前（看上傳日），所以晚上傳的集數隔天會補到；`date` 是標題裡的播出日，收盤資料（`market.price`，上市上櫃都到）還沒入庫的集數印 `[defer]` 留給下一輪 | `scripts/media_picks_job.sh`、`scripts/tw_media_picks.py`、`journal/README.md` |

這些排程共用同一個主 checkout，手動作業別把它的 working tree 留在別的分支或髒狀態。

長時間的工作一律放進脫離 session 的腳本（`daily_report.sh --detach`、`media_picks_job.sh --detach`），agent 只負責啟動、等結果、判讀與回報：Orca 一判定 agent 結束就收掉 terminal，連前景與 `run_in_background` 的子行程一起砍。2026-10-23 23:01 實測：Hindsight 的 SessionStart hook 在 repo 累積約 20 個新 commit 時另起一個 `claude -p` 做 repo 結構調查，它繼承了 `ORCA_*` 環境變數，結束時觸發 Orca 的 Stop hook，排程的 terminal 被收掉、`make media-picks` 被 SIGTERM，Orca 的執行紀錄還記成那份調查的輸出。這個 repo 一天幾十個 commit，每個 Orca 排程都可能碰上，Hindsight 那端修好之前，排程 prompt 要假設 agent 隨時會被中途收掉。

## 颱風假等臨時休市

交易日曆（exchange_calendars XTAI）不知道颱風假，官方 holidaySchedule 也不會補。07:30／10:00,13:00／19:00 三個排程的 precheck 跑 `uv run --env-file .env python -m market_data.closures`（開市回 0、休市回 1），18:00 的 `daily_report.sh` 開頭也跑一次（只記錄、不擋）：

- 查人事行政總處停班停課頁（`market_data.closures.DGPA_URL`）；臺北市全體公教機關**全日或上午**停止上班就當休市（證交所休市原則；下午停班照常交易，校級／區域停班不算），記進臨時休市清單 `data/tw_adhoc_closed_dates.txt`（`TW_ADHOC_CLOSED_FILE` 可改）。頁面的「今天／明天」以頁面自己的「更新時間」為準；版面認不出來時印 WARN。
- `trading_calendar` 的 XTAI 日曆（`is_market_open`、`get_effective_trading_date`、`get_trading_dates`…）與 `health.expected_session` 都讀這份清單，所以休市當天 18:00 的 `health --strict` 不會把它當缺資料擋下、美股復盤照跑，連假後第一個交易日的盤前判讀也不會去找休市那天的資料。
- NAS 正式 Web 沒有這些排程（`data/` 是另一份 bind mount）：`trading_calendar._get_calendar("XTAI")` 會自己偵測——每個行程每小時最多一次、逾時 3 秒，只查「今天」，今天是交易日且清單沒有時呼叫 `tw_closed_reason`，偵測到就寫進該行程所在環境的清單檔；失敗只 warning。`TW_CLOSURE_AUTODETECT=false` 可關（測試預設關）。偵測是在第一次查 XTAI 日曆或呼叫 expected_session 時觸發，之後同一行程內的其他呼叫端讀檔即得。
- 頁面連不上或改版 → 只依交易日曆（fail-open，照常跑）。其他原因的臨時休市手動在清單加一行 `YYYY-MM-DD  # 原因`。
- 2026-10-23（薔琵颱風）時還沒有這個機制，是手動暫停盤中與持股計畫排程。

`portfolio-check` 讀的個人持股計畫在 gitignore 的 `.memory/`（由 `.claude/settings.local.json` 的 `autoMemoryDirectory` 指定，兩個 Claude 帳號共用）；換機器或重建 checkout 時要一起搬。

## 每日報告的卡住防護與診斷

- 每日報告與媒體點名的鎖目錄旁各有固定的 `.guard` 檔，以 Perl 內建 `flock` 序列化建鎖、死鎖回收與釋放；此檔會保留，請勿在排程執行期間刪除。新鎖尚無 PID 時先視為忙碌，超過該排程的鎖齡門檻才回收；釋放時只清除 PID 仍屬於本輪的鎖。
- 媒體點名的兩條 journal push 入口都只推該輪驗證過的 commit SHA，並以 `--force-with-lease=develop:<已驗證的 origin SHA>` 綁定遠端狀態；另檢查祖先關係防止倒退遠端。被拒後最多 rebase 重試一次，重新擷取 SHA 並驗證，其他 session 後加的非 journal commit 不會被順帶推送。

- `scripts/daily_report.sh` 每一步（含 `llm_preflight`、`require_stock_success` 這類 bash 函式步驟）都在獨立 process group 跑，預設超過 90 分鐘（`DAILY_REPORT_STEP_TIMEOUT_SECONDS`，預設 5400）整組先 TERM、10 秒後 KILL。
- 另開 session 的本機 CLI 由 Python 登記 PGID 到每步獨立的暫存檔（內部 `_DSA_LOCAL_CLI_REGISTRY`，非使用者設定、不進 `.env.example`），啟動與登記共用 flock；逾時先封閉登記、一併終止已登記的 CLI 群組，再釋放報告鎖。
- log 印 `TIMEOUT: <step>` 並推系統通知。上一輪的鎖（`logs/.daily_report.lock`）持有者仍活著且鎖齡超過 3 小時（`DAILY_REPORT_STALE_LOCK_SECONDS`，預設 10800），下一輪會推系統通知並以 1 退出、保留本輪 log，不再靜默跳過。
- 兩個變數只供手動覆寫（腳本不讀 `.env`，不進 `.env.example`）。
- 逾時與鎖齡告警之外的卡法（例如 `notify_failure` 自己的 `uv run` 掛住）仍是靜默的：判別是 log 長時間不增長、行程還在、CPU 近 0。本機沒有 py-spy，用 `sample <pid>` 看卡在哪個系統呼叫（2026-10-12 實測卡在 AkShare 的 TLS 握手，見 `data_provider/AGENTS.md`）。

## 每日報告的完成標記

- `logs/.daily_report_last_session` 內容為 `<曆日>|<expected_session>`。`expected_session` 取 `market_data.health` 的唯一定義：交易日且過了 `SESSION_COMPLETE_AFTER`（台北）後為今天，否則為最近一個交易日；分界時間以該常數為準，這裡不抄數字。
- **同一天且同一場次**才跳過重跑。所以 `SESSION_COMPLETE_AFTER` 之前的手動跑（場次＝前一交易日）不會擋掉 18:00 的正式報告；台股休市日場次不變、但曆日變了，本機 `MARKET_REVIEW_REGION=tw,us` 的美股仍會跑（只用場次當鍵會把整輪跳掉）。
- `DAILY_REPORT_FORCE=1` 一律重跑；日曆取不到（`expected_session` 為空）時永不跳過、也不寫標記。
- 個股有失敗（但至少一檔成功）時另推一則標題「每日報告部分失敗」的系統通知列出代碼，不改變成敗判定。
