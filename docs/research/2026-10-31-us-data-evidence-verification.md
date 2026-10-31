# 美股證據層驗證紀錄（2026-10-31）

本機 worktree：`feat/us-data-evidence`。開始時 HEAD 與 fetch 後的 `origin/develop` 同為 `dbf8f519ec65c8bcaad56b82cb9be811adfb5315`，`git pull --ff-only` 顯示 Already up to date。未 rebase、未 push。

環境以 `uv venv --python 3.12` 與 `uv pip install -r requirements.txt -r .github/requirements-ci.txt` 建立獨立 `.venv`，目錄不是 symlink；後續一律 `uv run --frozen`。沒有修改相依清單。

## 驗證範圍

- 真實程式＋fake 外部資料：傳統與 agent 的實際 pipeline、搜尋工具、單 agent 與多策略 stage 的訊息建構、基本面聚合、最後歷史寫入與決策訊號。DB 為 mock，寫入值在 side_effect 當下深拷貝，沒有連正式 DB、發通知或呼叫真實 LLM。
- 相容性：從修改前 HEAD 載入原始實作產生 16 組 system／user prompt 雜湊與完整結果序列化基準（`tests/fixtures/event_gap_baseline.json`）；涵蓋美股／台股、四種報告語言、關閉／未達門檻。
- 本機真實 OpenD：TCP 探測 `127.0.0.1:11111` 回 `ConnectionRefusedError`，按任務要求略過。富途實際行情權限、資金流與延遲尚未驗證，對應讀數及逾時使用 fake 驗證。
- Python 3.11：以 `ast.parse(..., feature_version=(3, 11))` 核對所有本次 Python 改動；本機執行環境仍是 3.12，不能視為 3.11 runtime 驗收。

## 正反 mutation

最終 43／43 個變異版本均以測試失敗（exit 1）攔下，逐個還原後才進下一項。紅燈不是 collect error。歷史讀取測試初版被另一條既有分數護欄掩蓋，改用原始 buy 輸入後重跑，已確認移除事件原因會紅。

| 單一變異 | 實際結果 | 定向測試 |
| --- | --- | --- |
| 市場判定退回全域可用性 | 紅，1 failed | `tests/test_us_search_evidence.py::test_finmind_is_only_available_for_tw` |
| 過度封鎖台股 FinMind | 紅，1 failed | `tests/test_us_search_evidence.py::test_finmind_is_only_available_for_tw` |
| 傳統流程退回全域可用性 | 紅，1 failed | `tests/test_event_gap_decision.py::test_actual_pipeline_paths_use_market_availability_and_event_rules` |
| agent 計數退回全域可用性 | 紅，1 failed | `tests/test_event_gap_decision.py::test_actual_pipeline_paths_use_market_availability_and_event_rules` |
| agent 工具退回全域可用性 | 紅，1 failed | `tests/test_us_search_evidence.py::test_agent_search_tools_skip_unconfigured_market` |
| 移除同次搜尋切換 | 紅，14 failed | `tests/test_us_search_evidence.py::test_tavily_switches_key_in_same_search` |
| SDK 例外被轉成一般失敗而吞掉 | 紅，6 failed | `tests/test_us_search_evidence.py::test_tavily_real_do_search_preserves_error_classification` |
| 所有錯誤都換金鑰重試 | 紅，4 failed | `tests/test_us_search_evidence.py::test_tavily_other_errors_do_not_retry` |
| 起點固定為第一把 | 紅，1 failed | `tests/test_us_search_evidence.py::test_tavily_random_start_each_key_at_most_once` |
| 同一次搜尋重複嘗試金鑰 | 紅，1 failed | `tests/test_us_search_evidence.py::test_tavily_random_start_each_key_at_most_once` |
| 移除預期本益比 | 紅，1 failed | `tests/test_us_data_evidence.py::test_us_only_and_forward_pe_without_quote_info` |
| 證據擴大套用到非美股 | 紅，1 failed | `tests/test_us_data_evidence.py::test_us_only_and_forward_pe_without_quote_info` |
| 缺失讀數補成 0 | 紅，1 failed | `tests/test_us_data_evidence.py::test_info_missing_finite_and_actual_dates` |
| 活動窗口過寬 | 紅，1 failed | `tests/test_us_data_evidence.py::test_activity_windows_and_unknown_transactions` |
| 活動窗口過窄 | 紅，1 failed | `tests/test_us_data_evidence.py::test_activity_windows_and_unknown_transactions` |
| 未設定 OpenD 也取資料 | 紅，1 failed | `tests/test_us_data_evidence.py::test_disabled_futu_does_not_request` |
| 富途快照覆蓋已有報價欄位 | 紅，1 failed | `tests/test_us_data_evidence.py::test_futu_daily_flow_distribution_snapshot` |
| 富途證據污染 capital_flow | 紅，1 failed | `tests/test_us_data_evidence.py::test_independent_requests_keep_info_and_other_evidence` |
| 移除一秒連線探測上限 | 紅，1 failed | `tests/test_us_data_evidence.py::test_futu_disconnected_fast_failure` |
| 活動請求忽略剩餘階段預算 | 紅，1 failed | `tests/test_us_data_evidence.py::test_activity_requests_obey_remaining_stage_budget` |
| 移除傳統流程的快照補值接線 | 紅，1 failed | `tests/test_us_data_evidence.py::test_real_legacy_enrichment_supplements_only_missing_fields` |
| 事件規則永不觸發 | 紅，5 failed | `tests/test_event_gap_decision.py::test_event_gap_trigger` |
| 忽略預設關閉開關 | 紅，1 failed | `tests/test_event_gap_decision.py::test_event_gap_trigger` |
| 小幅波動也觸發 | 紅，1 failed | `tests/test_event_gap_decision.py::test_event_gap_trigger` |
| 擴大到美股／台股以外 | 紅，2 failed | `tests/test_event_gap_decision.py::test_event_gap_trigger` |
| 移除無新聞強制觀望 | 紅，4 failed | `tests/test_event_gap_decision.py::test_missing_news_hold_is_saved_after_all_other_guards` |
| 有新聞也強制觀望 | 紅，1 failed | `tests/test_event_gap_decision.py::test_structured_news_evidence_is_used_without_matching_text` |
| 改從敘述文字猜新聞證據 | 紅，4 failed | `tests/test_event_gap_decision.py::test_missing_news_hold_is_saved_after_all_other_guards` |
| 移除傳統分析 system 規則 | 紅，1 failed | `tests/test_event_gap_decision.py::test_traditional_generation_receives_event_system_and_user_rules` |
| 移除單 agent system 規則 | 紅，1 failed | `tests/test_event_gap_decision.py::test_agent_executor_event_rules_reach_system_prompt` |
| 移除多策略 stage system 規則 | 紅，1 failed | `tests/test_event_gap_decision.py::test_multistage_agents_receive_system_override_and_evidence` |
| 移除傳統 user prompt 規則 | 紅，1 failed | `tests/test_event_gap_decision.py::test_event_prompt_has_rules_and_evidence` |
| 護欄移到歷史寫入之後 | 紅，4 failed | `tests/test_event_gap_decision.py::test_missing_news_hold_is_saved_after_all_other_guards` |
| 歷史讀取忽略已套用事件護欄 | 紅，2 failed | `tests/test_event_gap_decision.py::test_history_keeps_persisted_event_watch_action` |
| 歷史讀取採用未套用的事件護欄 | 紅，1 failed | `tests/test_event_gap_decision.py::test_event_without_applied_guard_does_not_override_history_score_alignment` |

| 缺失的放空資料日寫成 null | 紅，1 failed | `tests/test_us_data_evidence.py::test_us_only_and_forward_pe_without_quote_info` |
| 連有效放空資料日也省略 | 紅，1 failed | `tests/test_us_data_evidence.py::test_info_missing_finite_and_actual_dates` |
| 環境專用設定漏登錄 | 紅，1 failed | `tests/test_config_registry.py::TestEnvExampleWebSettingsCoverage::test_active_env_example_keys_are_registered_or_hidden_from_web_ui` |
| AkShare 回到舊 HTTP 攔截點（防連外守門攔下） | 紅，1 failed | `tests/test_fundamental_adapter_contracts.py::test_capital_flow_real_akshare_request_uses_shenzhen_security` |
| 忽略事件環境開關 | 紅，1 failed | `tests/test_event_gap_decision.py::test_event_config_reads_environment_with_safe_defaults` |
| 事件環境開關預設誤開 | 紅，1 failed | `tests/test_event_gap_decision.py::test_event_config_reads_environment_with_safe_defaults` |
| 補上富途量比卻保留無資料描述 | 紅，1 failed | `tests/test_us_data_evidence.py::test_real_legacy_enrichment_supplements_only_missing_fields` |
| 過度清除已有量比的正常描述 | 紅，1 failed | `tests/test_us_data_evidence.py::test_real_legacy_enrichment_supplements_only_missing_fields` |

## 最終門檻

- `uv run --frozen ./scripts/ci_gate.sh syntax`：exit 0。
- `uv run --frozen ./scripts/ci_gate.sh flake8`：exit 0，critical checks 為 0。
- 最終 22 檔定向測試：`1392 passed, 46 warnings in 78.26s`，exit 0，包含所有全量失敗檔與本次新增測試。
- 本次 25 個 Python 改動檔以 Python 3.11 grammar 剖析通過；全量內既有 `test_every_source_file_parses_under_the_ci_python[3.11]` 也通過（借到 3.11 直譯器剖析全庫），並未在 3.11 執行測試套件。
- 唯一次 `DATABASE_URL='' STORAGE_DATABASE_URL='' LITELLM_MODE=PRODUCTION uv run --frozen ./scripts/ci_gate.sh offline-tests`：exit 1，`11 failed, 12669 passed, 129 skipped, 8 deselected, 681 warnings, 997 subtests passed in 442.29s`。跑全量期間沒有改檔。pytest 印出摘要後稍候才自行退出，未手動終止。
- 11 項失敗已全數修正並納入上述 1392 項定向通過：7 項搜尋 stub 缺少市場介面、1 項新環境設定未列為環境專用、3 項 AkShare 的 HTTP 測試接縫過時。未重跑第二次全量，因此不宣稱最終版本全量全綠。
- 初輪既有基本面測試曾漏 mock 新增的 yfinance 活動讀取；原全量的 AkShare 舊 mock 也漏攔公開 HTTP。兩者都已補齊隔離，AkShare 額外加 `BaseException` 防連外守門，並以移除 SDK 攔截點的 mutation 證明會紅。這些意外公開行情讀取不計入真資料驗收；正式 DB、NAS、LLM 與通知未操作。
- 富途補值後的「無資料」描述殘留也已修正；有值的量比與原描述維持原樣，正反 mutation 均會紅。

最終定向命令（環境明確清空兩個 DB URL）：

```bash
DATABASE_URL='' STORAGE_DATABASE_URL='' LITELLM_MODE=PRODUCTION uv run --frozen python -m pytest tests/test_agent_active_stock_integration.py tests/test_agent_pipeline.py tests/test_analysis_history.py tests/test_analyst_consensus.py tests/test_analyzer_news_prompt.py tests/test_config_registry.py tests/test_decision_action.py tests/test_decision_stability.py tests/test_event_gap_decision.py tests/test_fundamental_adapter_contracts.py tests/test_fundamental_context.py tests/test_futu_fetcher.py tests/test_futu_fundamental_adapter.py tests/test_notification_empty_news_disclosure.py tests/test_pipeline_finalize.py tests/test_search_tavily_provider.py tests/test_search_tools_persistence.py tests/test_structured_decision_action.py tests/test_us_data_evidence.py tests/test_us_market_path.py tests/test_us_search_evidence.py tests/test_yfinance_fundamental_adapter.py -q
```

## 檔案清單

共 31 檔；沒有修改 `requirements.txt`、部署配置、Web／iOS UI 或治理規則。

| 檔案 | 變更 |
| --- | --- |
| [.env.example](../../.env.example) | 修改 |
| [data_provider/base.py](../../data_provider/base.py) | 修改 |
| [data_provider/futu_fetcher.py](../../data_provider/futu_fetcher.py) | 修改 |
| [data_provider/us_evidence.py](../../data_provider/us_evidence.py) | 新增 |
| [data_provider/yfinance_fundamental_adapter.py](../../data_provider/yfinance_fundamental_adapter.py) | 修改 |
| [docs/CHANGELOG.md](../../docs/CHANGELOG.md) | 修改 |
| [docs/INDEX.md](../../docs/INDEX.md) | 修改 |
| [docs/us-data-evidence-verification.md](2026-10-31-us-data-evidence-verification.md) | 新增 |
| [docs/us-data-sources.md](../../docs/us-data-sources.md) | 新增 |
| [src/agent/agents/base_agent.py](../../src/agent/agents/base_agent.py) | 修改 |
| [src/agent/executor.py](../../src/agent/executor.py) | 修改 |
| [src/agent/orchestrator.py](../../src/agent/orchestrator.py) | 修改 |
| [src/agent/tools/search_tools.py](../../src/agent/tools/search_tools.py) | 修改 |
| [src/analyzer.py](../../src/analyzer.py) | 修改 |
| [src/config.py](../../src/config.py) | 修改 |
| [src/core/config_registry.py](../../src/core/config_registry.py) | 修改 |
| [src/core/pipeline.py](../../src/core/pipeline.py) | 修改 |
| [src/schemas/decision_scale.py](../../src/schemas/decision_scale.py) | 修改 |
| [src/search_service.py](../../src/search_service.py) | 修改 |
| [src/services/event_gap.py](../../src/services/event_gap.py) | 新增 |
| [tests/fixtures/event_gap_baseline.json](../../tests/fixtures/event_gap_baseline.json) | 新增 |
| [tests/test_agent_active_stock_integration.py](../../tests/test_agent_active_stock_integration.py) | 修改 |
| [tests/test_analyst_consensus.py](../../tests/test_analyst_consensus.py) | 修改 |
| [tests/test_event_gap_decision.py](../../tests/test_event_gap_decision.py) | 新增 |
| [tests/test_fundamental_adapter_contracts.py](../../tests/test_fundamental_adapter_contracts.py) | 修改 |
| [tests/test_fundamental_context.py](../../tests/test_fundamental_context.py) | 修改 |
| [tests/test_notification_empty_news_disclosure.py](../../tests/test_notification_empty_news_disclosure.py) | 修改 |
| [tests/test_search_tools_persistence.py](../../tests/test_search_tools_persistence.py) | 修改 |
| [tests/test_us_data_evidence.py](../../tests/test_us_data_evidence.py) | 新增 |
| [tests/test_us_market_path.py](../../tests/test_us_market_path.py) | 修改 |
| [tests/test_us_search_evidence.py](../../tests/test_us_search_evidence.py) | 新增 |

## 限制與回滾

沒有真實 Tavily／Yahoo／LLM 整合驗收，也沒有 NAS、通知、Web 或 iOS 驗收；本次未改 UI。事件規則屬 prompt 約束，不能保證模型遵循所有估值與均線敘述，但無新聞時的結構化護欄由程式強制。富途與額外 yfinance 請求可能因既有基本面預算耗盡而省略；背景逾時工作不等於遠端請求已取消。

可關閉 `EVENT_GAP_DECISION_ENABLED` 或清空 `FUTU_OPEND_HOST` 停用對應新能力；完整回滾用本次提交的 revert。舊歷史資料不重寫。
