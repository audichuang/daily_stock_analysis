# 台股 SMC 價位警報（設計，預設關閉）

把盯盤看板上「最近的支撐／壓力」建成價格穿越警報。價格跌破支撐或站上壓力時，推一則 Markdown 訊息。

**目前是關閉的**（`TW_LEVEL_ALERTS_ENABLED=false`）：
- 看板上不會出現按鈕。
- 端點拒絕寫入，回 409 `feature_disabled`，只能試算。
- 不會建立任何規則，也不會送任何訊息；之前開著時建好的價位規則（`source=tw_levels`）警報輪詢也會跳過，關掉就真的不響。

使用者打算先改版整套通知格式（Markdown、經 Telegram 送），所以先把功能做好，等改版後再開。

## 一則警報長這樣

標準 Markdown，由 `src/services/tw_level_alerts.py` 的 `format_level_alert_markdown()` 產生。`TelegramSender` 會把它轉成 Telegram 的格式，其他渠道照樣看得懂。以雙鴻為例（2026-10-22 拿 3324.TWO 的真實摘要跑出來的輸出，資料基準日 10-21、收盤 1,375，現價假設跌到 1,236）：

```markdown
**🔻 雙鴻 3324.TWO 跌破多頭 OB**

現價 **1,236**（觸發價 1,240，-0.3%）
- 價位：多頭 OB 1,240~1,365（2026-10-21 的 SMC 價位）
- 結構：10-19 BOS 空（1,395）
- 下一個支撐：FVG 未回補 1,155~1,300（+0.0%）
- 10-21 外資 5 日轉買 +587 張（20 日 -3,840）

- 報價來源：永豐即時（Shioaji）

_SMC 價位是結構參考，不是買賣訊號；完整分析在盯盤看板的「四維度分析」。_
```

「下一個支撐」是 +0.0%：現價 1,236 落在多頭 FVG 1,155~1,300 裡面，依看板的規則（見下）算支撐、距離 0。

價位建立後這檔有除權息、分割或減資時（查 `market.price_adjustment`，資料基準日隔天到今天），訊息最上面多一行，提醒價位已經不對：

```markdown
⚠️ 價位建立後（2026-10-21）有除權息，價位基準已變動，請等盤後資料更新後在盯盤看板重建警報
```

查不到調整資料時當作沒有，照常送訊息。

同一天在盯盤看板重建也沒用：看板的價位要等盤後資料更新才會換成新基準。所以在資料基準日之後有調整事件時，看板不顯示「建立價位警報」，`POST /api/v1/stocks/{code}/level-alerts`（含 `dry_run`）回 409 `levels_stale`，見 `docs/realtime-board.md` 的四維度摘要。

各行的來源：

| 行 | 來源 |
|---|---|
| 標題 | 規則建立時存的價位（`notification_policy.tw_level`）；跌破支撐是 🔻、站上壓力是 🔺 |
| 現價 | 警報觸發時的即時價（`observed_value`），百分比是和觸發價的差 |
| 結構、下一個價位、變化提示 | 觸發當下重新抓的看板摘要（`tw_stock_watch._one`）。抓不到時只送價位本身，不會不送 |
| 下一個價位 | 和看板的 `nearestLevels` 同一套規則：區間完全在現價之下是支撐、之上是壓力；現價在區間裡時多頭區算支撐、空頭區算壓力（距離 0）；距離量到近端邊；剛觸發的那個價位本身排除 |
| 除權息提醒 | 規則存的資料基準日之後有股價調整事件時才出現 |
| 報價來源 | 這次評估實際用的報價來源（`quote.source`）。Shioaji 缺金鑰會靜默退回 yfinance，看這行才分得出來 |

規則裡存的 `notification_policy.tw_level` 欄位不合法（缺欄位、價位非正數、代碼不是台股）時，`alert_worker` 改送通用格式的警報，不會整則吞掉。

訊息裡**沒有連結**：目前設定裡沒有 Web 的公開網址可用。之後改版通知、加上公開網址的設定時，再補「開啟四維度報告」的連結。

## 一條規則是什麼

一檔股票最多兩條，都是既有的 `price_cross` 規則，所以觸發、冷卻、紀錄都沿用警報中心（`/alerts`）：

| 價位 | 方向 | 觸發價 |
|---|---|---|
| 最近支撐 | `below` | 支撐區間的**下緣**（整個區間都被跌破才算；碰到下緣即觸發） |
| 最近壓力 | `above` | 壓力區間的**上緣**（整個區間都被站上才算；碰到上緣即觸發） |

觸發條件是**碰到邊就算**：`below` 是即時價 ≤ 觸發價、`above` 是即時價 ≥ 觸發價（`AlertService` 與 `EventMonitor` 都這樣比）。觸發後進入一天的冷卻；只要價格一直停在價位外面，**冷卻過了會再推一次，每天一則**，直到價格回到價位內或規則被重建、停用。

其他欄位：
- `source = "tw_levels"`，用來辨識與重建。
- `cooldown_policy = {"cooldown_seconds": 86400}`：價格在價位附近來回時，一天只推一次。
- `notification_policy.tw_level`：存價位名稱、區間、多空屬性與資料基準日，觸發時拿來組訊息。
- 名稱寫成「雙鴻 跌破多頭 OB 1,240.00」，在警報中心看得懂。
- OTE 區的名稱帶方向：最新結構事件是多方時叫「OTE 多方進場區」（多頭、可當支撐），空方時叫「OTE 空方進場區」（空頭、可當壓力）；還沒有結構事件時叫「OTE 進場區」、沒有方向，看板不會把它當成最近的支撐或壓力，所以也建不成警報。

「最近的支撐／壓力」只有一份實作，就是前端的 `utils/dossierLevels.ts`（用即時價判斷）。看板把它顯示的兩個價位送到後端；後端只檢查這兩個價位確實在這檔今天的 SMC 價位清單裡（種類、上下緣都要相同），**不接受任意價格**。

## 誰建立、何時重建

- **使用者手動建立**：在看板展開列按「建立價位警報」，再按確認。
- **每次建立都會換掉這檔既有的 `tw_levels` 規則**。價位每天會變，留著舊價位比沒有警報更糟。
  - 替換是**單一資料庫交易**（`AlertService.replace_source_rules` → `AlertRepository.replace_rules_by_source`）：先驗證全部規則，再在同一個交易裡刪掉這檔的 `tw_levels` 規則、寫入新規則，最後才提交；提交之後不再讀資料庫，所以不會出現「規則已經換掉、API 卻回錯誤」。提交前任何一步失敗就整組回滾，舊規則原封不動，也不會有半套新規則被警報輪詢看到。只刪同一檔、同一個 `source` 的規則，手動建的或別檔的不受影響。
  - 同一檔的重建另外用鎖排隊。鎖只在單一行程內有效；多個 worker 行程同時寫時，交易仍保證不會留下半套，但兩組可能先後覆蓋。
- **目前不會每天自動重建**。價位過了幾天可能已經不是最近的支撐／壓力，要自己重按一次。每晚自動重建持股的價位警報是之後的工作，到時另外決定要不要做。
- 想手動停掉：到警報中心停用或刪除名稱裡有「跌破／站上」的規則。

## 介面

- `POST /api/v1/stocks/{code}/level-alerts`
  - 請求 body：`{support, resistance, dry_run}`。`support`、`resistance` 各是看板上的一個價位（`label`、`low`、`high`、`kind`、`bias`），可以只給一個。
  - `dry_run=true`：只回傳將要建立的規則，**開關關閉時也能用**，拿來驗證設計。
  - 錯誤碼：

    | 狀態 | `error` | 何時 |
    |---|---|---|
    | 400 | `unsupported_market` | 代碼不是 `.TW`／`.TWO` |
    | 400 | `level_mismatch` | 送來的價位不在這檔今天的 SMC 價位清單裡 |
    | 400 | `invalid_rule` | `AlertService` 拒絕建立規則（欄位驗證失敗） |
    | 404 | `not_found` | 本地行情查無此股；或後綴寫錯市場（例如 `2330.TWO`），訊息提示「2330.TWO 應為 2330.TW」 |
    | 409 | `feature_disabled` | 開關關閉時正式寫入（`dry_run` 不受限） |
    | 503 | `level_alerts_unavailable` | 讀取 SMC 價位失敗，或寫入規則時出錯（舊規則保留） |
- `GET /api/v1/stocks/dossier-summary` 的回應多一個 `level_alerts_enabled`，看板據此決定要不要顯示按鈕。

## 啟用前檢查清單

照順序做，**第 5 步會開始寫正式應用庫**（NAS 共用的 `dsa` schema）：

1. **通知格式改版定案**：確認上面的訊息版型是要的。要改的話只需改 `format_level_alert_markdown()`，通用警報的格式不受影響。
2. **設定 Telegram**：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` 都要有（兩個只設一個會被設定檢查擋下）。
3. **路由**：`NOTIFICATION_ALERT_CHANNELS` 留空時，警報送到所有已設定的渠道；只想送 Telegram 就設成 `telegram`。
4. **警報輪詢要開著**：`AGENT_EVENT_MONITOR_ENABLED=true`（`AGENT_EVENT_MONITOR_INTERVAL_MINUTES` 預設 5 分鐘），再選一條路跑：
   - **只跑監控（NAS 用這條）**：加上 `AGENT_EVENT_MONITOR_WITHOUT_SCHEDULE=true`。API 程序啟動獨立執行緒（`alert_worker.start_alert_monitor_worker`），不依賴 `SCHEDULE_ENABLED`、不註冊每日分析，所以不會和 Mac 18:00 的每日報告重複。即時價規則只在該市場開盤時段評估（`is_market_polling_window` 且不提前放行），盤前、收盤後與假日不抓報價、不寫紀錄；觸發時還要確認報價屬於今天這一場（`quote_in_current_session`），前一場的價格不通知、不進冷卻。報價不帶時間時（yfinance，含 Shioaji 退回 yfinance），只在將要觸發那一刻多查一次最後一筆分鐘成交（`YfinanceFetcher.get_last_trade`，一般報價路徑與看板不經過），並用那筆的價格重新評估，通知也用這個價格，時間和價格才是同一筆行情；日線備援與 Stooq 則比對自帶的日期。查不到、不是今天或重新評估未觸發就不通知，計入 `last_stats.stale_quote`，開盤過多久都一樣。程序啟動時決定，改值要重啟。
   - **跟著排程器跑**：`SCHEDULE_ENABLED=true` 或 `--schedule`，代價是連帶跑每日分析。這條路維持全天評估。
   - 兩者同時開時由獨立執行緒負責，排程器不註冊監控，不會重複推播。
   - 確認有在跑：`GET /api/v1/alerts/monitor/status` 的 `running`（看實際執行緒或排程器，不是開關值）、`last_run_at`、`channels`；只開 `AGENT_EVENT_MONITOR_ENABLED` 而兩條路都沒開時，`reason` 是 `schedule_not_running`。
5. **開功能**：`TW_LEVEL_ALERTS_ENABLED=true`，部署到 NAS。先用 `dry_run` 確認一檔，再在看板對一檔持股真的建立。
6. **實測一次真的送出**：警報中心的「測試」按鈕只是試算（`POST /api/v1/alerts/rules/{id}/test` → `AlertService.test_rule`），**不會送任何訊息**，驗不到版型。要讓 worker 真的推一次：
   - 把剛建的一條價位規則的觸發價改到現價外面一點（支撐規則改成略高於現價、壓力規則改成略低於現價）。警報中心沒有編輯畫面，用 API：`PATCH /api/v1/alerts/rules/{id}`，body `{"parameters": {"direction": "below", "price": <略高於現價>}}`。只改 `parameters`，`notification_policy.tw_level` 不動，訊息版型照舊。
   - 或另建一條一次性的 `price_cross` 規則（`POST /api/v1/alerts/rules`），`notification_policy` 照抄價位規則的 `tw_level`，才會用上面的版型；不帶的話送的是通用格式。
   - 等下一輪輪詢（預設 5 分鐘）推出來，確認 Telegram 收到的版型正確。
   - 改過價格的規則已經不是真的價位，而且剛觸發過、冷卻一天：回看板對這檔重按「建立價位警報」，整組替換會把它換掉；另建的一次性規則到警報中心刪掉。

## 程式位置

| 檔案 | 內容 |
|---|---|
| `src/services/tw_level_alerts.py` | `plan_rules`（驗證價位、組規則）、`replace_rules`（單一交易整組替換、同檔加鎖）、`format_level_alert_markdown`、`build_level_alert_message`（含除權息檢查）、`valid_level_meta` |
| `src/services/alert_worker.py` | `_send_notification` 的掛鉤：只有帶合法 `notification_policy.tw_level` 的規則改用上面的版型，其他規則照舊 |
| `api/v1/endpoints/stocks.py` | `POST /{code}/level-alerts` |
| `apps/dsa-web/src/components/board/BoardDossier.tsx` | 「建立價位警報」按鈕（只在開關打開時出現） |
| `src/config.py`、`.env.example` | `TW_LEVEL_ALERTS_ENABLED`，預設 `false` |
