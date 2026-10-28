# 分析、任務與報告歷史

## Sub-features

- 首頁提交單股／多股分析，觀察受理、進度與最終報告。
- 大盤複盤人工入口與產生的報告。
- 歷史列表、個股歷史抽屜、時間範圍、更多紀錄、切回當前報告。
- Markdown／分享海報匯出；改到哪種匯出就驗哪種。
- 初始狀態：以上均尚未實測；沒有報告種子不能宣稱驗過歷史。

## How to get to it (user POV)

開啟本輪隔離服務的 `/`。以首頁可見表單輸入帶 `.TW`／`.TWO` 的台股代碼，
從目前 snapshot 找出分析按鈕。完成後選該報告，進個股歷史，再回到當前報告。
大盤複盤及匯出按鈕依當前頁面 snapshot 選取，不推測名稱或座標。

## Driving it with ego-browser

1. 依上層 Launch／Doctor 取得本輪 URL 與 evidence 路徑；先保存首頁 snapshot／畫面。
2. 用 `page.fill()`、`page.click()` 操作 snapshot 對應表單；保存輸入值、click receipt 與起訖時間。
   禁用內部 store setter、直接插資料或以 POST 取代這次 Web 操作。
3. 觀察真正任務終態。API 對照路徑為 `POST /api/v1/analysis/analyze`、
   `GET /api/v1/analysis/tasks`、`GET /api/v1/analysis/status/{task_id}`；路徑以當前 OpenAPI 核對。
   大盤入口是 `POST /api/v1/analysis/market-review`。保存 task／query／trace／history ID 中實際取得者。
4. 報告成功後保存可讀內容畫面；重新整理，對照 `GET /api/v1/history?stock_code=2330.TW` 與
   `GET /api/v1/history/{record_id}`，確認相同報告 ID 仍存在於本輪 SQLite。
5. 打開個股歷史抽屜，依 snapshot 操作 all／30d／90d 可見選項、載入更多與選擇歷史紀錄；
   檢查代碼、日期與報告內容跟著變動。資料不足使某入口無法驗到時，該子功能記未驗證。
6. Markdown 入口是複製到剪貼簿，點擊後核對可見成功提示，並保存畫面中可見源碼與
   `GET /api/v1/history/{record_id}/markdown` 對照；剪貼簿內容需另用平台可讀能力核對，未讀到就記未驗證。
   海報下載才先 `page.waitForEvent("download")` 再 click，同一輪 `download.saveAs()` 保存並檢視檔案。
7. 保存操作前後畫面、API response、DB 列數／ID；按上層 Cleanup 清理，確認證據仍存在。

## Gotchas

- 202 只證明受理，CLI exit 0 也可能只有模板複盤；必須核對個股成功與完整內容。
  來源：`docs/tw-operating-guide.md §2.3`、`api/v1/endpoints/analysis.py`。
- 分析會呼叫真實 LLM／資料源、寫歷史／用量，設定還可能發通知；先按本輪隔離設定核對實際邊界。
  已獲此範圍授權便繼續；未獲發訊息許可時停在送出前，不能測完才補問。
- `StockHistoryTrendDrawer.tsx` 與 `stockPoolStore.ts` 是歷史範圍及切換契約來源；
  空態截圖只證明空態，不能代替有紀錄時的切換／分頁。
- 外部生成不可用時記真實失敗原因；fixture 報告可驗渲染，但不能標分析端到端通過。
- 本地 `STORAGE_DATABASE_URL` 預設指正式庫；歷史刪除／正式重跑不能當驗證清理。
