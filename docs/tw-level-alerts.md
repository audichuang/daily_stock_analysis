# 台股 SMC 價位警報（設計，預設關閉）

把盯盤看板上「最近的支撐／壓力」建成價格穿越警報。價格跌破支撐或站上壓力時，推一則 Markdown 訊息。

**目前是關閉的**（`TW_LEVEL_ALERTS_ENABLED=false`）：
- 看板上不會出現按鈕。
- 端點拒絕寫入，回 409 `feature_disabled`，只能試算。
- 不會建立任何規則，也不會送任何訊息。

使用者打算先改版整套通知格式（Markdown、經 Telegram 送），所以先把功能做好，等改版後再開。

## 一則警報長這樣

標準 Markdown，由 `src/services/tw_level_alerts.py` 的 `format_level_alert_markdown()` 產生。`TelegramSender` 會把它轉成 Telegram 的格式，其他渠道照樣看得懂。以雙鴻為例：

```markdown
**🔻 雙鴻 3324.TWO 跌破多頭 OB**

現價 **1,236**（觸發價 1,240，-0.3%）
- 價位：多頭 OB 1,240~1,365（2026-10-21 的 SMC 價位）
- 結構：10-19 BOS 空（1,395）
- 下一個支撐：SSL 下方流動性 955~955（-22.7%）
- 外資 5 日轉買 +587 張（20 日 -3,840）

_SMC 價位是結構參考，不是買賣訊號；完整分析在盯盤看板的「四維度分析」。_
```

各行的來源：

| 行 | 來源 |
|---|---|
| 標題 | 規則建立時存的價位（`notification_policy.tw_level`）；跌破支撐是 🔻、站上壓力是 🔺 |
| 現價 | 警報觸發時的即時價（`observed_value`），百分比是和觸發價的差 |
| 結構、下一個價位、變化提示 | 觸發當下重新抓的看板摘要（`tw_stock_watch._one`）。抓不到時只送價位本身，不會不送 |

訊息裡**沒有連結**：目前設定裡沒有 Web 的公開網址可用。之後改版通知、加上公開網址的設定時，再補「開啟四維度報告」的連結。

## 一條規則是什麼

一檔股票最多兩條，都是既有的 `price_cross` 規則，所以觸發、冷卻、紀錄都沿用警報中心（`/alerts`）：

| 價位 | 方向 | 觸發價 |
|---|---|---|
| 最近支撐 | `below` | 支撐區間的**下緣**（整個區間都被跌破才算） |
| 最近壓力 | `above` | 壓力區間的**上緣**（整個區間都被站上才算） |

其他欄位：
- `source = "tw_levels"`，用來辨識與重建。
- `cooldown_policy = {"cooldown_seconds": 86400}`：價格在價位附近來回時，一天只推一次。
- `notification_policy.tw_level`：存價位名稱、區間、多空屬性與資料基準日，觸發時拿來組訊息。
- 名稱寫成「雙鴻 跌破多頭 OB 1,240.00」，在警報中心看得懂。

「最近的支撐／壓力」只有一份實作，就是前端的 `utils/dossierLevels.ts`（用即時價判斷）。看板把它顯示的兩個價位送到後端；後端只檢查這兩個價位確實在這檔今天的 SMC 價位清單裡（種類、上下緣都要相同），**不接受任意價格**。

## 誰建立、何時重建

- **使用者手動建立**：在看板展開列按「建立價位警報」，再按確認。
- **每次建立前，先刪掉這檔既有的 `tw_levels` 規則**。價位每天會變，留著舊價位比沒有警報更糟。
- **目前不會每天自動重建**。價位過了幾天可能已經不是最近的支撐／壓力，要自己重按一次。每晚自動重建持股的價位警報是之後的工作，到時另外決定要不要做。
- 想手動停掉：到警報中心停用或刪除名稱裡有「跌破／站上」的規則。

## 介面

- `POST /api/v1/stocks/{code}/level-alerts`
  - 請求 body：`{support, resistance, dry_run}`。`support`、`resistance` 各是看板上的一個價位（`label`、`low`、`high`、`kind`、`bias`），可以只給一個。
  - `dry_run=true`：只回傳將要建立的規則，**開關關閉時也能用**，拿來驗證設計。
  - 正式寫入：開關關閉時回 409 `feature_disabled`；價位不在今天的清單裡回 400 `level_mismatch`；非台股回 400 `unsupported_market`。
- `GET /api/v1/stocks/dossier-summary` 的回應多一個 `level_alerts_enabled`，看板據此決定要不要顯示按鈕。

## 啟用前檢查清單

照順序做，**第 5 步會開始寫正式應用庫**（NAS 共用的 `dsa` schema）：

1. **通知格式改版定案**：確認上面的訊息版型是要的。要改的話只需改 `format_level_alert_markdown()`，通用警報的格式不受影響。
2. **設定 Telegram**：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` 都要有（兩個只設一個會被設定檢查擋下）。
3. **路由**：`NOTIFICATION_ALERT_CHANNELS` 留空時，警報送到所有已設定的渠道；只想送 Telegram 就設成 `telegram`。
4. **警報輪詢要開著**：`AGENT_EVENT_MONITOR_ENABLED=true`（`AGENT_EVENT_MONITOR_INTERVAL_MINUTES` 預設 5 分鐘）。這是既有的警報中心開關，關著時規則建了也不會被檢查。
5. **開功能**：`TW_LEVEL_ALERTS_ENABLED=true`，部署到 NAS。先用 `dry_run` 確認一檔，再在看板對一檔持股真的建立。
6. **實測一次觸發**：在警報中心對剛建的規則按「測試」，或把一條規則的價格改到現價附近，確認 Telegram 收到的版型正確，再改回來。

## 程式位置

| 檔案 | 內容 |
|---|---|
| `src/services/tw_level_alerts.py` | `plan_rules`（驗證價位、組規則）、`replace_rules`（刪舊建新）、`format_level_alert_markdown`、`build_level_alert_message` |
| `src/services/alert_worker.py` | `_send_notification` 的掛鉤：只有帶 `notification_policy.tw_level` 的規則改用上面的版型，其他規則照舊 |
| `api/v1/endpoints/stocks.py` | `POST /{code}/level-alerts` |
| `apps/dsa-web/src/components/board/BoardDossier.tsx` | 「建立價位警報」按鈕（只在開關打開時出現） |
| `src/config.py`、`.env.example` | `TW_LEVEL_ALERTS_ENABLED`，預設 `false` |
