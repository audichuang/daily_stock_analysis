# 即時盯盤看板

## Sub-features

- `/board` 的全部／自選／持股範圍、手動刷新、個股報價與資料時效。
- 相同股票跨自選／持股合併，持股數量、成本與損益對照。
- 展開列走勢、四維度摘要與分析入口；基金另列卡片。
- 初始狀態：均尚未實測；缺帳本／行情前置資料須分項記錄。

## How to get to it (user POV)

由導覽列進「即時看板」，或開本輪隔離 URL 的 `/board`。
右上方切換範圍，點刷新，展開股票列查看走勢、四維度資料與持股資訊。
完整行為正本：`docs/realtime-board.md`。

## Driving it with ego-browser

1. 先確認上層 Doctor；在本輪 TaskSpace 既有 Page `goto()` 到 `/board`，保存 snapshot。
2. 依 snapshot 找到範圍 `role="group"`；來源為 `RealtimeBoardPage.tsx` 的
   `aria-label={t('board.scope.label')}`，子按鈕以 `aria-pressed` 表示選中。
   使用實際翻譯名稱或當輪 ref 點全部／自選／持股，不寫 localStorage 模擬點擊。
3. 每次切換保存 action receipt 與結果列；對照 `GET /api/v1/stocks/watchlist`、
   `GET /api/v1/portfolio/snapshot?include_realtime=false` 的代碼與股數。
   有同代碼前置資料時，確認全部範圍只一列、跨帳戶持股正確合併。
4. 用 snapshot 找刷新按鈕（source：`board.refresh`），點擊後等待 loading 結束及可見報價結果；
   保存來源、報價時間、交易日／市場狀態與價格。以 response 或 DOM 可見欄位核對，不只截價格。
5. 展開一列，從新 snapshot 點走勢範圍、四維度分析；對照
   `GET /api/v1/stocks/{code}/trend?range=day|month|year` 與
   `GET /api/v1/stocks/dossier-summary?codes=…`。
   四維度抽屜的完整終態見 [research-cli.md](research-cli.md)。
6. 記錄基金卡片是否有資料、NAV 日期與 `/funds` 入口；未建基金種子記未驗證。
   留存最終畫面與 API 證據，依上層 Cleanup 收尾。

## Gotchas

- 未注入 Shioaji 金鑰會靜默改走 yfinance；`source=fallback` 及延遲標籤是合法降級，不能宣稱真即時。
- 正式 NAS 有持續 Shioaji session；本機驗證不要另外登入正式券商 session 來湊證據。
- 盤後／休市自動輪詢會按市場停抓；手動刷新仍全抓。單次刷新不能證明 30 秒輪詢或休市閘門。
- 摘要資料包快取 10 分鐘，報價與摘要基準日不同；資料日落後須原樣留證。
- 除權息後可能顯示「除權息後價位待更新」，此時撐壓距離與建立價位警報應停用。
  沒有相應市場事件樣本時，這條仍未驗證。
- 價位警報會寫帳及可能觸發通知；只有使用者已授權該動作時才測實際建立／送出。
  單純查看畫面不需為假設風險加確認。
- 缺 market DB／外部報價時應記缺前置資料，空表不證明持股合併或行情正常。
