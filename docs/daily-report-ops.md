# 本機排程與每日報告維運

本 fork 的 LLM 重活（盤前判讀、每日報告、持股建議、上游同步）都跑在本機，由 Orca automation 觸發；Web 服務另跑在 NAS（見 `docs/nas-deploy.md`）。每日報告怎麼讀、手動跑哪個 target，見 `docs/tw-operating-guide.md` §2.3；台股資料更新那一段（`daily` → `health --strict`）見 skill `update-market-data`。

## 排程一覽

| 時間（台北） | 做什麼 | 流程正本 |
|---|---|---|
| 平日 07:30 | 盤前判讀，寫 `journal/` 兩個 jsonl；只 commit＋push 這兩個檔到 `develop`（讓預測當天進版控；git 權限見根 `AGENTS.md` §1） | skill `tw-morning-call` |
| 每日 08:30 | 上游同步：上游累積 ≥5 個未收 commit 才動手，只產出待審分支 `chore/upstream-sync-<日期>` 並推 Bark，**不碰 `develop`／`main`**；該分支合進 `develop` 前就是下一輪的鎖，排程會一直記成 skipped | skill `dsa-upstream-sync`（precheck 在它的 `scripts/`） |
| 平日 10:00／13:00 | 持股盤中對照即時價，有觸發才推 Bark | skill `portfolio-check` |
| 平日 18:00 | `make daily-report-detached`（`scripts/daily_report.sh`） | 本檔下兩節 |
| 平日 19:00 | 持股：寫隔日條件式計畫（接在每日報告後） | skill `portfolio-check` |
| 平日 23:00 | 媒體點名：`make media-picks` 抓 25 個財經頻道的完整版、寫 `journal/media-picks.jsonl`，**只** commit＋push 這個檔到 `develop`，推 Bark 摘要；一輪約 40 分鐘，`--since` 預設 4 天前（看上傳日），所以晚上傳的集數隔天會補到；`date` 是標題裡的播出日，收盤資料（`market.price`，上市上櫃都到）還沒入庫的集數印 `[defer]` 留給下一輪 | `scripts/tw_media_picks.py`、`journal/README.md` |

這些排程共用同一個主 checkout，手動作業別把它的 working tree 留在別的分支或髒狀態。

## 颱風假等臨時休市

交易日曆（exchange_calendars XTAI）不知道颱風假，官方 holidaySchedule 也不會補。07:30／10:00,13:00／19:00 三個排程的 precheck 跑 `uv run --env-file .env python -m market_data.closures`（開市回 0、休市回 1），18:00 的 `daily_report.sh` 開頭也跑一次（只記錄、不擋）：

- 查人事行政總處停班停課頁（`market_data.closures.DGPA_URL`）；臺北市全體公教機關**全日或上午**停止上班就當休市（證交所休市原則；下午停班照常交易，校級／區域停班不算），記進臨時休市清單 `data/tw_adhoc_closed_dates.txt`（`TW_ADHOC_CLOSED_FILE` 可改）。頁面的「今天／明天」以頁面自己的「更新時間」為準；版面認不出來時印 WARN。
- `trading_calendar` 的 XTAI 日曆（`is_market_open`、`get_effective_trading_date`、`get_trading_dates`…）與 `health.expected_session` 都讀這份清單，所以休市當天 18:00 的 `health --strict` 不會把它當缺資料擋下、美股復盤照跑，連假後第一個交易日的盤前判讀也不會去找休市那天的資料。
- 頁面連不上或改版 → 只依交易日曆（fail-open，照常跑）。其他原因的臨時休市手動在清單加一行 `YYYY-MM-DD  # 原因`。
- 2026-10-23（薔琵颱風）時還沒有這個機制，是手動暫停盤中與持股計畫排程。

`portfolio-check` 讀的個人持股計畫在 gitignore 的 `.memory/`（由 `.claude/settings.local.json` 的 `autoMemoryDirectory` 指定，兩個 Claude 帳號共用）；換機器或重建 checkout 時要一起搬。

## 每日報告的卡住防護與診斷

- `scripts/daily_report.sh` 每一步（含 `llm_preflight`、`require_stock_success` 這類 bash 函式步驟）都在獨立 process group 跑，預設超過 90 分鐘（`DAILY_REPORT_STEP_TIMEOUT_SECONDS`，預設 5400）整組先 TERM、10 秒後 KILL。
- 另開 session 的本機 CLI 由 Python 登記 PGID 到每步獨立的暫存檔（內部 `_DSA_LOCAL_CLI_REGISTRY`，非使用者設定、不進 `.env.example`），啟動與登記共用 flock；逾時先封閉登記、一併終止已登記的 CLI 群組，再釋放報告鎖。
- log 印 `TIMEOUT: <step>` 並推 Bark。上一輪的鎖（`logs/.daily_report.lock`）持有者仍活著且鎖齡超過 3 小時（`DAILY_REPORT_STALE_LOCK_SECONDS`，預設 10800），下一輪會推 Bark 並以 1 退出、保留本輪 log，不再靜默跳過。
- 兩個變數只供手動覆寫（腳本不讀 `.env`，不進 `.env.example`）。
- 逾時與鎖齡告警之外的卡法（例如 `notify_failure` 自己的 `uv run` 掛住）仍是靜默的：判別是 log 長時間不增長、行程還在、CPU 近 0。本機沒有 py-spy，用 `sample <pid>` 看卡在哪個系統呼叫（2026-10-12 實測卡在 AkShare 的 TLS 握手，見 `data_provider/AGENTS.md`）。

## 每日報告的完成標記

- `logs/.daily_report_last_session` 內容為 `<曆日>|<expected_session>`。`expected_session` 取 `market_data.health` 的唯一定義：交易日且過了 `SESSION_COMPLETE_AFTER`（台北）後為今天，否則為最近一個交易日；分界時間以該常數為準，這裡不抄數字。
- **同一天且同一場次**才跳過重跑。所以 `SESSION_COMPLETE_AFTER` 之前的手動跑（場次＝前一交易日）不會擋掉 18:00 的正式報告；台股休市日場次不變、但曆日變了，本機 `MARKET_REVIEW_REGION=tw,us` 的美股仍會跑（只用場次當鍵會把整輪跳掉）。
- `DAILY_REPORT_FORCE=1` 一律重跑；日曆取不到（`expected_session` 為空）時永不跳過、也不寫標記。
- 個股有失敗（但至少一檔成功）時另推一則標題「每日報告部分失敗」的 Bark 列出代碼，不改變成敗判定。
