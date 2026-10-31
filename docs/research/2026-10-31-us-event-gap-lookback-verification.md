# 美股事件視窗修正驗證（2026-10-31）

修正起點為 `54a4e96636d1aec0a4db7eab6b39928e971dc480`，分支維持 `feat/us-data-evidence`。fetch 後遠端基線為 `origin/develop` 的 `1b42120d9cf2217c2abe22b8bc724fc86252b8ff`；分支無法 fast-forward，依基線同步規則保留本地狀態，未 pull／rebase／push。沿用本 worktree 獨立 `.venv`，Python 與專案檢查命令以 `uv run --frozen` 執行，沒有新增依賴。

## 行為與證據

- 最近 5 個交易場次含當日，距事件日 0～4 場有效；任一收盤幅度達門檻即可，取最近事件。日線優先用 pct_chg，缺時由相鄰收盤計算；不足時保留只判當日的行為。
- 共用分流前已載入的 DB 日線。傳統、agent 的實際 pipeline 測試證明各只讀一次原有 get_data_range、不新增 get_daily_data，提示詞與落庫採同一事件日、幅度、低點、距今場次。低點缺失不拿收盤價代替，也不輸出佔位低點。
- 傳統 system／user、單 agent 與多策略 stage system 都驗明確事件事實。SUPPORTED_REPORT_LANGUAGES 的 zh／zh-TW／en／ko 逐一參數化，另驗繁中語言別名不會 KeyError。
- 既有 16 組逐字元 prompt 雜湊及完整結果基準繼續通過，基準 fixture 未修改；關閉開關時已載入歷史事件也不改提示詞。
- 本輪未呼叫真實 LLM、Tavily、OpenD、正式 DB 或通知。使用者已完成首輪真實 Tavily／audinas OpenD／Claude CLI 驗收；本輪以 fake 證明新增交易日視窗及提示詞內容。

## 新聞時效的實際行為

`SearchService._filter_news_response` 的 3 天視窗是今日與前 2 個日曆日；`_load_persisted_intelligence_context` 使用同一有效新聞天數，本地 repository 是滾動 72 小時。週五事件到週一只隔 1 個交易場次，事件仍有效，但週五文章已被搜尋排除。若本地情報也過期且沒有近期追蹤新聞或社交證據，news_evidence_present 為 false，仍強制觀望。財報事件真實存在並不保證本次有可用新聞證據。

週五到週一及距今 4 場兩個相對日期案例都實際跑過搜尋硬篩選與無新聞護欄。任一當期社交／本地情報來源仍可讓旗標為 true，旗標不保證對應同一事件。本輪沒有把事件日帶入搜尋、沒有放寬任何新聞窗口。

## Mutation

23／23 個單一變異皆以 exit 1 且測試 failed 攔下，沒有 collect error；每項之後還原來源。資料不足的當日回退、真實日線優先、正反視窗邊界及所有報告語言皆有守門。

| 變異 | 結果 | 實際定向測試 |
| --- | --- | --- |
| 退回只看當日 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_event_stays_active_on_quiet_following_session` |
| 窗口多算一場，超過 lookback 仍觸發 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_five_sessions_includes_today_and_excludes_older_event` |
| 窗口少算一場，邊界事件被漏掉 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_five_sessions_includes_today_and_excludes_older_event` |
| 用日曆天取代交易場次 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_weekend_keeps_event_active_but_friday_news_leaves_monday_window` |
| 選到最早而非最近事件 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_most_recent_event_wins_and_dates_are_sorted_and_deduplicated` |
| 缺 pct_chg 時不計算相鄰收盤變化 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_missing_pct_is_computed_from_adjacent_actual_closes` |
| 即時漲跌幅推翻已知日線收盤 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_explicit_daily_pct_precedes_close_calculation_and_realtime` |
| 把收盤價當事件低點 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_event_stays_active_on_quiet_following_session` |
| 把當日日期當成歷史事件日 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_event_stays_active_on_quiet_following_session` |
| 距事件日場次多算一場 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_event_stays_active_on_quiet_following_session` |
| 提示詞移除事件事實 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_prompt_prints_event_facts_and_omits_missing_low` |
| 低點未知仍列出佔位低點 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_prompt_prints_event_facts_and_omits_missing_low` |
| 不保存已載入的日線 | 紅，2 failed | `tests/test_event_gap_lookback.py::test_loaded_daily_history_reaches_both_pipeline_paths_without_extra_fetch` |
| 傳統流程漏傳日線 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_loaded_daily_history_reaches_both_pipeline_paths_without_extra_fetch` |
| agent 流程漏傳日線 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_loaded_daily_history_reaches_both_pipeline_paths_without_extra_fetch` |
| 忽略回看設定 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_lookback_configuration_is_loaded_from_environment` |
| 預設回看變為 6 場 | 紅，2 failed | `tests/test_event_gap_decision.py::test_event_config_reads_environment_with_safe_defaults` |
| 移除 zh 訊息 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_guard_has_message_for_every_supported_language` |
| 移除 zh-TW 訊息 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_guard_has_message_for_every_supported_language` |
| 移除 en 訊息 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_guard_has_message_for_every_supported_language` |
| 移除 ko 訊息 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_guard_has_message_for_every_supported_language` |
| 所有語言都錯用英文訊息 | 紅，3 failed | `tests/test_event_gap_lookback.py::test_guard_has_message_for_every_supported_language` |
| 估算列幅度蓋過原始收盤計算 | 紅，1 failed | `tests/test_event_gap_lookback.py::test_actual_close_calculation_precedes_estimated_today_pct` |

## 檢查結果

- 定向驗證：`417 passed, 10 warnings in 8.93s`，exit 0。
- `uv run --frozen ./scripts/ci_gate.sh syntax`：exit 0。
- `uv run --frozen ./scripts/ci_gate.sh flake8`：exit 0，critical checks 0。
- 6 個本輪 Python 改動檔以 3.11 grammar 剖析通過；全量的 `test_every_source_file_parses_under_the_ci_python[3.11]` 也通過，並未在 3.11 執行整套測試。
- 指定全量命令：`12718 passed, 129 skipped, 8 deselected, 681 warnings, 997 subtests passed in 349.39s (0:05:49)`，exit 0；本輪只執行一次，全程沒有改檔。上輪 11 項失敗檔都納入並通過；沒有需要分類為假紅的失敗。

```bash
DATABASE_URL='' STORAGE_DATABASE_URL='' LITELLM_MODE=PRODUCTION uv run --frozen ./scripts/ci_gate.sh offline-tests
```

fixture 實際呼叫的事件輸出（非真實 INTC 驗收）：

```text
事件日期：2026-10-29
事件日漲跌幅：-28.58%
事件日低點：63.2
距事件日交易場次：1
```

事件低點 63.2 來自 fake 日線，沒有用收盤 65.76 代替。上述 console 與兩條 pipeline 測試分開證明提示詞事實與持久化行為。

## 限制與回滾

新聞時效與事件視窗的落差是本輪保留的限制，未默默改搜尋。未重跑線上模型，不能由提示詞 fixture 推論真實模型一定遵循每項事件準則。OpenD 正式部署事實與升版限制依使用者提供的已實測結果更新，未更動部署。

可關閉 EVENT_GAP_DECISION_ENABLED 停用事件功能；完整回滾使用本輪新增 commit 的 revert，不重寫既有歷史報告。
