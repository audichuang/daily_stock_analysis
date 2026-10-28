# 選股、回測與基金

## Sub-features

- `/screening`：啟用、策略／數量、task 終態、候選展開、重整恢復與歷史 run。
- `/backtest`：報告篩選、視窗／phase、執行、結果與績效、下一交易日視角。
- `/funds`：搜尋、詳情／NAV 範圍、加入／編輯持有、重整、刪除本輪持有。
- 三條旅程的前置與終態獨立；空結果、降級與不足樣本各自記錄。

## How to get to it (user POV)

由導覽列分別進 `/screening`、`/backtest`、`/funds`。
選股頁先確認啟用狀態；回測頁頂控制篩選與執行；基金先搜尋並點一筆結果才有詳情與持有表單。
selectors 的翻譯文字取當輪 snapshot；選股策略固定入口為 `#screening-strategy`。

## Driving it with ego-browser

1. 依上層 Launch／Doctor 核對本輪 SQLite；market 存取使用已授權、DB 強制唯讀的連線。
   選股另需可用公開資料 provider／策略模型；回測需本輪分析與後續 K 棒；基金需真基金與 NAV。
   各條缺少前置時分項 blocked，不以 SQLite 假行情或 mock API 取代真資料。
2. `/screening`：必要時點啟用；選 `#screening-strategy`，在返回數量欄填小量，再點執行。
   保存 POST `/api/v1/screening/screen/tasks` 的 task ID，等 GET `/screen/tasks/{id}` 完成。
   展開候選核對代碼與理由；重整驗恢復，再點歷史 run，核對 GET `/api/v1/screening/history/{run_id}`。
   成功需候選／零候選的完整終態與同一 run ID；202 或 progress 畫面不是完成。
3. 改到選股分析跳轉時，點候選列分析按鈕，核對目標代碼與實際分析終態；
   熱點刷新與新聞查詢分開記 provider、資料時間及連網結果，不由策略結果推論它們可用。
4. `/backtest`：填股票代碼、`input[placeholder="10"]` 視窗、起訖日期 aria-label 與 phase select，
   先篩選再執行；需要本輪重算才勾強制重跑。保存 POST `/api/v1/backtest/run` 請求與回應。
   核對 processed／completed／insufficient／errors，表格與 GET `/api/v1/backtest/results` 的 ID 一致；
   績效對照 `/api/v1/backtest/performance`、`/performance/{code}`，切頁與重整後仍讀到相同結果。
5. 回測範圍含下一交易日視角時，用頁頂對應按鈕切換並核對 appliedEvalWindowDays、實際欄位與 API。
   只有今天真報告而尚無後續 K 棒時，可驗 insufficient 終態，完整報酬／命中率仍未驗證。
6. `/funds`：搜尋輸入的 aria-label／placeholder 來自 `funds.search.placeholder`；填真基金名稱或 ID、
   提交後點結果，保存 `/api/v1/funds/search`、`/{id}`；切 y1／y3／y5 等可見範圍，
   核對 `/{id}/nav?period=…` 的首尾日期、NAV 與報酬卡；all 使用 source 定義的全期請求。
7. 在基金詳情點新增持有，填 units、costTotal、asOf、platform 與本輪 note，儲存後記 holding ID。
   重整、編輯本輪持有並保存，再刪除並確認；建立為 POST `/api/v1/funds/holdings`，
   列表為 GET 同一路徑（`/{fund_id}/holdings` 是基金成分股，不是個人持倉），並核對
   PUT/DELETE `/holdings/{id}` 與本輪 SQLite 列。詳情、NAV、持有 CRUD 分別記錄結果。
8. 保存前後畫面、receipt、task／run／report／holding ID、API、DB 列與外部資料日期；
   Cleanup 後確認證據留存，未取得績效或真 NAV 的子功能保持未驗證。

## Gotchas

- Run ID 位於可折疊的「运行详情」；不以 `body.innerText` 含 Run ID 作唯一等待條件。
  實跑另發現歷史 created_at 為 UTC-naive、UI 少八小時；保留時區失敗案例，不把任務完成推成時間顯示正確。
- Backtest 結果篩選 query 是 `code`（搭配 `eval_window_days`），不是 `stock_code`；重整後重套視窗再核對。

- StockScreeningPage 的市場選項目前只有 A 股 `cn`；不能把它當成台股 `make screen` 的 UI。
  啟用會改本輪設定，執行會寫 task／screening history；provider 仍可能連外並降級。
- 回測日線取自應用 `StockDaily`；缺窗口會嘗試 provider 補資料並寫本輪 SQLite。
  `force` 不會創造尚未發生的交易日，少樣本不能宣稱策略績效成立。
- 基金 GET 詳情與建立持有都可能進 `_ensure_history`，歷史不全會嘗試回補並寫 market。
  唯讀旅程先選符合 `_history_complete` 的基金；回補被拒的 warning 要留證，不能當完整 NAV 成功。
  top holdings 另可能連鉅亨；查 NAV 成功不證明基金持股成分已驗證。
- UI source：`apps/dsa-web/src/pages/{StockScreeningPage,BacktestPage,FundsPage}.tsx`；
  API source：`apps/dsa-web/src/api/{screening,backtest,funds}.ts`、`api/v1/endpoints/{screening,backtest,funds}.py`。
  資料／寫入 source：`src/services/{screening_service,backtest_service,fund_service}.py`。
