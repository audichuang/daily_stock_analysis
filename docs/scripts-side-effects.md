# 腳本副作用細節

`scripts/AGENTS.md` 分類表的完整版：跑之前確認會不會連網或寫檔。

## 台股波段研究

唯讀本地 Postgres。例外:`fetch_twse_disposal_history` 連網寫 `data/twse_punish_history.csv`(不入庫);`research_macro_ladder --refresh-cache` 與 `research_pre_event_delay --fetch` 連網寫 `~/.cache/dsa/research/`(不帶時只讀快取);`verify_morning_calls` 連 TWSE／期交所抓開盤與 09:05 指數,`--append` 追加 `journal/morning-calls-outcomes.jsonl`(18:00 `daily_report.sh` 呼叫、同一天不重寫),`--append --push` 有新結果時只印 `PUSH:` 摘要、由 `daily_report.sh` 讀取後推播(腳本本身不發通知),`--brief` 只讀該檔不連網(`make morning`);`screen_tw` 的 `main()` 在基準日＝預期場次時另即時抓官方公告。`verify_swing_decisions`／`verify_media_picks` 只讀 `journal/`(後者加 Postgres 行情),不寫、不連網;沒有腳本會寫 `swing-decisions.jsonl`。`verify_media_picks --speaker-records` 輸出講者紀錄 JSON 給 `media_picks_judge`(口徑見 `journal/README.md`)。`measure_market_regime`／`measure_revenue_momentum` 的狀態與營收特徵純函式在 `src/services/tw_backtest_context.py`(與台股 prompt 共用,改量測口徑要同步那裡寫死的 CI 文案)。結論見 `docs/tw-signal-research-2026-10.md`、`docs/research/2026-10-28-macro-ladder.md`

## 媒體點名

連網(yt-dlp、NotebookLM,憑證走 Doppler `notebooklm`;PTT 直接抓網頁);**media-picks 每天建一本 NotebookLM notebook、刪 30 天前的**。只有 `tw_media_picks`／`tw_ptt_picks` 會追加 `journal/media-picks.jsonl`／`ptt-picks.jsonl`,逐字稿存 `data/media_picks/`;覆核檔與判斷檔由排程的 Claude 追加。`media_picks_brief`／`media_picks_summary` 唯讀 journal 整理事實、不下結論;`media_picks_judge` 一檔一個隔離的 `claude -p`、只印 JSON、不寫 journal。`tw_ptt_picks` 沿用 `tw_media_picks` 的 `resolve`／`snapshot`,改那兩個函式兩邊都要跑測試。**`media_picks_job.sh` 會動主 checkout 的 `develop`**(fetch＋ff-only、commit＋push 兩個 journal、寫 `logs/` 的鎖與 log、失敗推 Telegram 系統通知主題;鎖與 `--detach` 跟 `daily_report.sh` 共用函式);`--push-journal` 是排程 Claude 的 push 守門。流程、旗標與守門規則見 `docs/daily-report-ops.md`、`journal/README.md`
