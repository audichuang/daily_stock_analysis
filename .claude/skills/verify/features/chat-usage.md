# 問股與用量

## Sub-features

- `/chat`：真問題、串流終態、追問上下文、新對話、切回歷史與重整持久化。
- 問股的停止、Markdown 匯出、刪除本輪 session；通知轉發另需發訊息許可。
- `/usage`：today／month／all、刷新、calls／tokens／model／近期列對照。
- 各入口分項記錄；有回答不等於有 token telemetry，沒有 telemetry 也不能推論模型沒執行。

## How to get to it (user POV)

導覽列進 `/chat`；`[data-testid="chat-workspace"]` 包含 session 側欄與輸入框。
可見問股輸入是 textarea；「開啟新對話」、session 切換／刪除及匯出以當輪 aria-label 選取。
導覽列進 `/usage`，頁頂期間按鈕與刷新更新同一份 dashboard。

## Driving it with ego-browser

1. 依上層 Launch／Doctor，核對本輪 SQLite、模型與資料邊界。
   先保存 GET `/api/v1/agent/status`、`/api/v1/agent/skills`；Chat 需要真正可用的 Agent backend。
   `codex_app_server` 要 single-agent、可用 Codex CLI／登入態；LiteLLM 要可用 tool-calling 模型。
2. 在 `[data-testid="chat-workspace"] textarea` 填唯一問題，經送出按鈕提交；
   保存 request／session ID，等待 POST `/api/v1/agent/chat/stream` 的真正完成與完整回答。
   使用涉及本輪股票的問題時，同時核對 tool 資料來源與日期；只顯示使用者訊息不算回答成功。
3. 在同一 session 追問可核對的前文內容；保存上下文回答。
   點 `chat.history.newChat` 對應按鈕，再由 `chat.history.switchTo` 對應 aria-label 切回原 session；
   重整後訊息仍在，核對 GET `/api/v1/agent/chat/sessions`、`/sessions/{id}` 的 ID／內容。
4. 範圍含取消時，在真串流中點停止；保存 POST `/api/v1/agent/chat/stream/{request_id}/cancel`，
   核對 UI 進入停止終態及保留內容，不能只以按鈕恢復可按判定。
5. 匯出使用 `chat.exportSessionHint` 或 `chat.exportMessageHint` 的按鈕；
   先建立 download 等待，再 click，於同輪保存 Markdown，核對問題、回答與非空內容。
   範圍含刪除時，只刪本輪 session 並確認，核對 DELETE `/api/v1/agent/chat/sessions/{id}` 與重整後列表。
6. 保存本輪真生成的用量證據後進 `/usage`，依序點 today／month／all 與刷新。
   保存 GET `/api/v1/usage/dashboard?period=…&limit=50`；核對區間、calls、tokens、model 與近期列。
   比對本輪 SQLite `llm_usage` 的 ID、called_at、call_type、model 與加總，重整後再次核對。
7. 保存每次 action、輸入／回答／歷史畫面、去敏 API 與 DB 列、下載檔；Cleanup 後確認仍可讀。
   問股、取消、匯出、刪除、空用量與非空用量各自記結果，少一種終態就保留未驗證。

## Gotchas

- 有對話後標頭與輸入框都顯示「傳送」；輸入框用 `loc=role:button[name='傳送']`，
  不用純文字 selector。標頭 accessible name 是「傳送到已設定的通知機器人／信箱」，本範圍不操作。
- 實跑發現「報告 ID」中的 `ID` 會被識別成第二檔美股，和 `2330.TW` 一起觸發標的澄清。
  保留原輸入作產品失敗案例；正常讀取報告另用「報告編號」，不能把澄清訊息當模型成功。

- `GENERATION_BACKEND=claude_code_cli` 服務個股／大盤生成，不能代替 Chat 的 Agent backend。
  launcher 的空 HOME／allowlist 不自帶實機 CLI 登入態；缺前置時記 blocked，憑證不落證據。
- local CLI generation 回 `usage_available=false`、`usage_source=unavailable`；
  `should_persist_usage_telemetry` 會略過此 payload，所以真生成後 `llm_usage` 仍可能完全沒有新列。
  此時期間切換與空態可驗，非空用量需要帶真 provider usage 的 Codex Chat／LiteLLM；不造 token seed。
- Chat 的「發送到已配置通知機器人／郵箱」走 POST `/api/v1/agent/chat/send`，會發訊息；
  沒有本輪發訊息許可就不點，問答與匯出仍可獨立驗證。
- UI source：`apps/dsa-web/src/pages/{ChatPage,TokenUsagePage}.tsx` 與 `src/api/{agent,usage}.ts`。
  backend source：`src/agent/{factory,codex_agent_backend}.py`、`api/v1/endpoints/{agent,usage}.py`；
  用量真源為 `src/llm/{local_cli_backend,usage}.py`、`src/analyzer.py`、`src/storage.py`。
