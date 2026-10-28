# scripts — 研究、索引、門檻與打包腳本

## 模組定位

這個目錄混了性質完全不同的腳本,動手前先認清手上這支是哪一種——副作用差很多:

| 類別 | 腳本 | 副作用 |
|---|---|---|
| 台股波段研究 | `screen_tw`、`measure_signal_forward`、`fetch_twse_disposal_history`、`measure_market_regime`、`measure_revenue_momentum`、`measure_inst_divergence`、`portfolio_walkforward`、`backtest_screen`、`research_macro_ladder`、`research_pre_event_delay`、`research_explore_queue`、`verify_swing_decisions`、`verify_media_picks`、`verify_morning_calls` | 唯讀本地 Postgres。例外:`fetch_twse_disposal_history` 連網寫 `data/twse_punish_history.csv`(不入庫);`research_macro_ladder --refresh-cache` 與 `research_pre_event_delay --fetch` 連網寫 `~/.cache/dsa/research/`(不帶時只讀快取);`verify_morning_calls` 連 TWSE／期交所抓開盤與 09:05 指數,`--append` 追加 `journal/morning-calls-outcomes.jsonl`(18:00 `daily_report.sh` 呼叫、同一天不重寫),`--append --push` 有新結果時只印 `PUSH:` 摘要、由 `daily_report.sh` 讀取後推播(腳本本身不發通知),`--brief` 只讀該檔不連網(`make morning`);`screen_tw` 的 `main()` 在基準日＝預期場次時另即時抓官方公告。`verify_swing_decisions`／`verify_media_picks` 只讀 `journal/`(後者加 Postgres 行情),不寫、不連網;沒有腳本會寫 `swing-decisions.jsonl`。`verify_media_picks --speaker-records` 輸出講者紀錄 JSON 給 `media_picks_judge`(口徑見 `journal/README.md`)。`measure_market_regime`／`measure_revenue_momentum` 的狀態與營收特徵純函式在 `src/services/tw_backtest_context.py`(與台股 prompt 共用,改量測口徑要同步那裡寫死的 CI 文案)。結論見 `docs/tw-signal-research-2026-10.md`、`docs/research/2026-10-28-macro-ladder.md` |
| 個股資料包 | `tw_stock_dossier`、`tw_stock_report`（只是 CLI 包裝，實作在 `src/services/` 同名檔，Web API 共用） | 唯讀本地 Postgres;券商分點另連網查富邦 DJ(`--no-branch` 關閉),不寫 DB |
| 每日報告回測 | `backtest_daily_report_levels`、`shadow_buy_eval` | 唯讀應用庫(報告價位;有 `STORAGE_DATABASE_URL` 就讀它,否則 `data/stock_analysis.db`;`shadow_buy_eval` 只認 `STORAGE_DATABASE_URL`/`--db`,連線設 READ ONLY,`--by-variant` 依 `dashboard.prompt_variant` 分表、未標記歸 `untagged`)與 Postgres(行情);後者寫 markdown 到 `reports/` |
| 盤前判讀多臂 | `morning_fable_arms`、`morning_pack.sh` | `morning_fable_arms` 呼叫 `claude -p`,追加進**版控的** `journal/morning-arms.jsonl`;同一 (date, model_version) 不重寫,所以手動測試會寫死當天的正式列——測試用 `--dry-run` 或 `--journal` 指到暫存檔。`morning_pack.sh` 是 `make morning` 的包裝,指令成功才發布 `reports/morning-packs/` |
| 媒體點名 | `tw_media_picks`、`tw_ptt_picks`、`media_picks_job.sh`、`media_picks_brief`、`media_picks_summary`、`media_picks_judge` | 連網(yt-dlp、NotebookLM,憑證走 Doppler `notebooklm`;PTT 直接抓網頁);**media-picks 每天建一本 NotebookLM notebook、刪 30 天前的**。只有 `tw_media_picks`／`tw_ptt_picks` 會追加 `journal/media-picks.jsonl`／`ptt-picks.jsonl`,逐字稿存 `data/media_picks/`;覆核檔與判斷檔由排程的 Claude 追加。`media_picks_brief`／`media_picks_summary` 唯讀 journal 整理事實、不下結論;`media_picks_judge` 一檔一個隔離的 `claude -p`、只印 JSON、不寫 journal。`tw_ptt_picks` 沿用 `tw_media_picks` 的 `resolve`／`snapshot`,改那兩個函式兩邊都要跑測試。**`media_picks_job.sh` 會動主 checkout 的 `develop`**(fetch＋ff-only、commit＋push 兩個 journal、寫 `logs/` 的鎖與 log、失敗推 Telegram 系統通知主題;鎖與 `--detach` 跟 `daily_report.sh` 共用函式);`--push-journal` 是排程 Claude 的 push 守門。流程、旗標與守門規則見 `docs/daily-report-ops.md`、`journal/README.md` |
| 持股清單 | `portfolio_codes` | 唯讀應用庫 portfolio,印出啟用帳戶持有的台股／ETF 代號 JSON(23:00 媒體點名標持股用;基金不在內)。**不 import `PortfolioService`／`DatabaseManager`**(其 `__init__` 會對正式庫 create_all、寫遷移紀錄、ALTER TABLE,唯讀旗標來得太晚),自己開純 SQLAlchemy 連線並設唯讀;重播數量的規則對齊 `PortfolioService._replay_account`,改那邊要回頭看這支;用 `uv run --env-file .env python scripts/portfolio_codes.py` |
| 盤前／盤中取數 | `overnight`、`taifex_positions`、`intraday_breadth`、`kr_tw_memory_watch`、`macro_brief` | 連網(yfinance／Shioaji／期交所),不寫 DB;`intraday_breadth`／`kr_tw_memory_watch` 另讀 DB;`taifex_positions` 的期貨抓取與解析共用 `market_data/taifex.py`(入庫在那邊);`overnight` 的序列清單來自 `market_data/macro.py` 的 `SERIES`(不要在腳本裡另列);`macro_brief` 唯讀 DB、不連網(資料由 daily 寫入,見 `docs/macro-data.md`) |
| 股票索引 | `fetch_tw_stock_list`、`merge_tw_into_index`、`refresh_us_stock_index`、`refresh_stock_index`、`generate_index_from_csv` | **改寫進版控的索引檔與種子 CSV** |
| 資料稽核 | `audit_market_vs_official` | 唯讀 Postgres＋連 TWSE／TPEx(每請求 ≥4 秒),結果與原始回應寫到 `--out` 目錄;判準與修法見 `docs/tw-data-integrity.md` |
| 資料庫維運 | `migrate_sqlite_to_pg`、`backfill_price_change_sign`、`migrate_storage_to_postgres` | **寫入 Postgres**;最後一支只碰 `--schema` 指定的應用庫表(分析歷史等),有 `--dry-run`,目標非空需 `--replace` |
| 通知 | `notify` | 推一則 Telegram 到指定主題(內文走 stdin);排程、`daily_report.sh`、`kr_tw_memory_watch` 都經它,`make notify` 是包好 Doppler 的入口。只有送到指定主題才印 `[notify] <主題>: 已送出` 回 0;缺憑證、缺該主題 id(否則掉進群組預設主題)、空內文、送出失敗都回 1,原因在 stderr |
| 門檻／治理／打包 | `ci_gate.sh`、`ci_test_shard`、`ci_durations_from_junit`(從 CI 的 junit artifact 重算 shard 時長表,改寫進版控的 `.github/ci-test-durations.json`)、`check_ai_assets`、`test.sh`、`build-*`、`pyinstaller_runtime_compat` | CI 與發版流程直接呼叫,檔名被測試用字串釘住 |

## 進來改要遵守

- **台股波段研究的契約正本是 `docs/tw-swing-pipeline.md`,成本口徑是 `docs/tw-trading-costs.md`。**改門檻、視窗、成本之前先讀,改完同步文件裡「凍結的訊號定義」。
- **訊號定義是各寫各的,沒有共用 import,而且門檻也各存一份。**live 在 `screen_tw.py`(條件逐檔切片、門檻在 `BREAKOUT`);量測在 `measure_signal_forward.py`(整張面板 `shift`/`rolling`、門檻是它自己的 argparse 預設);`portfolio_walkforward.py` import 量測的訊號,但門檻預設與排序公式又各抄一份。**只改 `BREAKOUT` 不會讓 `make measure`／`make portfolio` 跟著變**——它們照常結束,印出來的是另一組訊號。踩過兩次口徑差(60 日高的視窗、月營收保鮮期是曆日不是交易列)。
- **`backtest_screen.py` 不是 live 策略的回測。**檔名與說明寫著 screen_tw,但它有自己的 `FACTORS`、預設跑 `momentum`,沒有 `breakout`。別拿它當凍結訊號的正本。
- **成本、稅率、滑價、年化天數一律走 `tw_trade_costs.py`**(真源在 `src/utils/`,這裡的同名檔只是 shim,因為每日報告的成本檢核也要用同一組費率),不要在腳本裡自己寫常數。個股與 ETF 的證交稅率不同,0050 基準沿用個股稅率會高估基準成本,而那個誤差方向對策略有利。
- **價格面板不要 `ffill`**:索引是多檔交易日的聯集,補出來的假 K 棒會佔掉均線視窗的一格、擠掉最舊的真 K 棒,結果不報錯但足以翻轉「已跌破／未跌破」。
- **argparse 的 help 字串裡百分號要寫成 `%%`。**裸的 `%` 會讓 `--help` 在進 `main` 之前就 `ValueError`(修過兩次)。

## 踩雷

- **腳本要用 `claude -p` 當獨立判斷者時,隔離照 `morning_fable_arms.call_claude`**:`--tools ""`、`--strict-mcp-config`、`--setting-sources ""`、`--settings '{"disableAllHooks":true}'`、清掉 `CLAUDE_CODE_*`／`CLAUDECODE`／`ORCA_*`、在空的暫存 cwd 跑、prompt 走 stdin(`media_picks_judge` 只做了其中一部分:沒帶 `--setting-sources`、cwd 是 `/tmp`)。不能用 `--bare`:它只認 `ANTHROPIC_API_KEY`、不讀 OAuth,本機走 OAuth 登入。不隔離會載入全域 CLAUDE.md、MCP 與 skills,子程序讀得到這個 repo。
- **點名類 journal 附的 `data` 只能用當時已公開的資料。**當天 17:00(`tw_media_picks.DATA_KNOWN`)前上傳或發文的只用前一天:收盤 13:30 就有,個股法人下午才公布。上傳時刻要用 yt-dlp 的 `timestamp` 換台北時間——`upload_date` 是 UTC 日期,而且不是每支影片都有時間戳。新增來源一律走 `data_cutoff` 這條規則,別自己判斷「盤前」。
- **`migrate_sqlite_to_pg.py` 是已完成的一次性遷移,不要再執行。**每張表各自 commit,中途失敗時前面的表已經被舊資料換掉。
- **`daily_report.sh` 被 `source` 時只載入函式、不跑 main**,`tests/test_daily_report_sh.py` 靠這點測試;不要直接執行腳本去測。逾時、鎖與完成標記的語意見 `docs/daily-report-ops.md`。
- `merge_tw_into_index.py` 目標檔不存在時只印 skip、照樣回 0。`refresh_us_stock_index.py` 有 `--dry-run`,但不加參數仍會連網並寫檔。
- 全量重生 `refresh_stock_index` 要 Tushare 匯出檔,缺檔會丟掉三萬多筆 A 股條目(台股索引用 `make refresh-tw`)。
- **回補 `price.change` 的正負號不能用 `close - lag(close)`。**官方比的是當日參考價(前收 × 復權因子),除權息日兩者方向不同;讀取視窗也要往前多取,否則每檔每年第一個交易日沒有前一列可比、被靜默跳過。
- **`pyinstaller_runtime_compat.py` 的環境變數必須在 import 時設定**,不能收進 `main()`:它是被當成 runtime hook 載入的,不走 `__main__`。收進去之後打包照樣成功,凍結後的程式才壞。
- **`exit 0` 不是正確性。**這裡踩過的缺陷幾乎都是照常結束、數字是錯的(排序分數整欄 NaN 讓 `--top N` 退化成代號最小的 N 檔;兩支回測各用不同年化天數)。驗證要看輸出內容,不是看結束碼。`test.sh` 的期望值是手寫的,也曾把缺陷釘成正確答案。
