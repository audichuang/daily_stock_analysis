# 告警規則與決策訊號

## Sub-features

- `/alerts`：建立規則、啟用／停用、篩選、重整持久化及刪除本輪規則。
- `/alerts` 的即時測試、背景觸發與通知送達是不同終態，各自留下證據。
- `/decision-signals`：來源報告／股票篩選、詳情、回饋、關閉、latest 與時間線。
- 重評 preview、護欄通過後持久化及 outcomes 回驗另驗；本檔沒有預設通過項。

## How to get to it (user POV)

由導覽列進 `/alerts` 或 `/decision-signals`。
告警左側是 AlertRuleForm，右側列表有測試、啟停與刪除；刪除需要確認。
訊號頁頂選股票，下方有篩選、時間線與訊號卡片；點卡片詳情後才有回饋與狀態動作。

## Driving it with ego-browser

1. 依上層 Launch／Doctor，確認所有寫入落本輪 SQLite；排程與 event monitor 保持停用。
   告警 CRUD 可從空庫開始；訊號須先由本輪真分析取得 history／signal ID。
   沒有訊號種子就記 blocked，不以直接 POST 建訊號或 SQL 注入取代分析來源。
2. 在 `/alerts` 依 snapshot 填唯一規則名稱；目標欄為
   `input[placeholder="600519 / AAPL / hk00700"]`，填帶後綴的本輪股票，例如 `2330.TW`。
   選 single_symbol、price_cross 與正數門檻，取消建立後啟用再提交；保存規則 ID。
3. 對該列依序啟用、停用，重整後用停用篩選找回同一 ID；比較 GET `/api/v1/alerts/rules`。
   API 寫入是 POST `/api/v1/alerts/rules`、`/{id}/enable`、`/{id}/disable`。
   範圍含刪除時用列內 deleteAria 對應按鈕與 ConfirmDialog，驗 DELETE `/{id}` 後列表及 DB 消失。
4. 範圍含規則測試時，點該列測試，保存 POST `/api/v1/alerts/rules/{id}/test` 的 observed value、
   status、triggered 與資料時間；同時比較 triggers／notifications 前後，區分測試與真推播。
5. 在 `/decision-signals` 用目前 snapshot 的股票代碼、來源報告 ID、狀態 aria-label 填篩選並提交。
   核對 GET `/api/v1/decision-signals` 只有符合條件的本輪列；重整後重新套條件核對同一 ID。
6. 點 `decisionSignals.viewDetailsFor` 對應 aria-label 的卡片按鈕，保存詳情；
   點有用回饋，核對 PUT `/api/v1/decision-signals/{id}/feedback` 及重開詳情後的回饋狀態。
7. 在詳情點關閉訊號並確認，核對 PATCH `/api/v1/decision-signals/{id}/status` 回 closed；
   重整後 active 篩選排除該列、closed 篩選仍讀到同 ID，SQLite 狀態一致。
8. 範圍含 latest／時間線時，從頁頂選同股票，核對 GET `/api/v1/decision-signals/latest/{code}`，
   再切 30d／90d、狀態與 profile 並查詢；保存每次結果。少於分頁樣本的入口記未驗證。
9. 需要重評時，先保存 preview 的護欄結果；只有 UI 放行且確認後才持久化。
   保存 POST `/api/v1/decision-signals/reassess` 的 persist、item ID 與 persist_status，區分新列／既有列。
10. 保存操作前後 PNG、receipt、原始去敏 API 回應及規則／訊號／回饋 DB 列；Cleanup 後核對留存。

## Gotchas

- AlertRuleService.test_rule 執行資料評估並回 dry-run 結果，不等於背景輪詢或 Telegram 送達；
  `evaluation_error`／缺資料不能當條件未觸發。資料來源不可用時保留實際失敗。
- 頁面規則與 AGENT_EVENT_ALERT_RULES_JSON 可能並存；刪除本輪 DB 規則不能證明環境規則已停用。
- 關閉訊號只改本輪追蹤狀態；正式訊號／正式報告不用來測刪除或狀態轉移。
- 真行情、通知、模型重評依該子功能前置分項驗；CRUD 成功不覆蓋這些能力。
- UI source：`pages/{AlertsPage,DecisionSignalsPage}.tsx`、
  `components/alerts/{AlertRuleForm,AlertRuleList}.tsx`、`components/decision-signals/DecisionSignalDisplay.tsx`。
  API source：`apps/dsa-web/src/api/{alerts,decisionSignals}.ts`、`api/v1/endpoints/{alerts,decision_signals}.py`；
  評估／寫入來源 `src/services/alert_service.py` 與 `src/services/decision_signal_service.py`。
