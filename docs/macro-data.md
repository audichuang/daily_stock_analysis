# 總經、Fed 利率預期與重大事件（market schema）

`market_data.cli daily` 每天把台股以外的「大局」數據寫進 `market` schema 三張表，`make morning` 的「大局」段（`scripts/macro_brief.py`，也可 `make macro` 單跑）從 DB 印出來，給 skill `tw-morning-call` 的大局判讀用。2026-10-26 起。

## 三張表

| 表 | 一列是什麼 | 來源 | 鍵 |
| --- | --- | --- | --- |
| `macro_series` | 一個序列一個交易日的收盤值 | yfinance 日線；2／10 年期美債另抓 FRED `fredgraph.csv`（免金鑰） | `(series_id, date)` |
| `rate_expectations` | 某天快照裡、某場 FOMC、某個結果（升 >25bp／升 25bp／不變／降 25bp／降 >25bp）的機率 | Kalshi `KXFEDDECISION` 公開 API（免金鑰） | `(snapshot_date, meeting_date, outcome)` |
| `event_calendar` | 一個事件（FOMC 決議日、watchlist 財報日） | Fed 官網 `fomccalendars.htm` ＋ Kalshi；財報走 yfinance `Ticker.calendar` | `(event_type, symbol, label)` |

序列清單只有一份：`market_data/macro.py` 的 `SERIES`。`scripts/overnight.py` 取其中 `overnight=True` 的那幾列，不另外維護。要加序列改那裡，下一次 daily 就開始累積；要補歷史跑 `cli macro --period 2y`。

## 語意與坑

- **日期是資料列自帶的交易日**，不是抓取日。期貨與匯率在台北白天抓到的最後一列是盤中值，下次抓取同日會被覆蓋；`make morning` 07:30 跑的時候美股已收盤。
- **殖利率類（`kind=yield`）單位是百分比**（4.99 = 4.99%），儀表的變化用 bp 表示。
- **機率用買賣價中點，不用 `last_price`**：最後成交可能是很久以前的。實測 2026-10-26 的 2027 年 3 月「降 25bp」最後成交 0.35，買賣價卻是 0.06／0.13。沒有賣單（ask 為 0）的結果記 `prob_mid = NULL`，儀表會標「無報價」，不當成 0。各結果是獨立合約，中點加總不一定是 100%。
- **利率預期沒有歷史快照可補**：Kalshi 只給「現在」的報價，所以 `rate_expectations` 只從開始入庫那天起累積。漏跑一天就永遠少一天，降版 migration 在表內有資料時會拒絕。
- **FOMC 決議日以 Fed 官網為準**：取每場會議的最後一天，跨月會議（`April/May` + `30-1`）取後一個月，非例會（unscheduled、notation vote）略過。Kalshi 合約收盤時間換成美東日期當交叉對照；`source` 欄是 `fed+kalshi`（一致）、`fed(kalshi不符)`、`fed`、`kalshi`（官網還沒列，`status=estimated`）。
- **財報日一律 `estimated`**：yfinance 不給確認狀態，而且實測 MSFT 2026-10-28 盤後的財報，yfinance 給的是 10-29。看到財報日要知道可能差一天。財報的 `label` 是財報日所在季度（`2026Q4`），同季改期會更新同一列；跨季改期時，同一檔未來日期、但這次沒抓到的那筆會被刪掉，已經過去的事件不刪。
- watchlist 預設 `MSFT GOOGL AMZN META AAPL NVDA TSM MU AVGO AMD ORCL TSLA`，用 `.env` 的 `MACRO_EARNINGS_WATCHLIST`（逗號分隔）覆蓋。
- 台灣法說會與央行理監事會**還沒入庫**：法說會由 `market_data/events.py` 即時抓、只出現在 screen 報告的事件日曆。

## 開關與失敗

- `MACRO_PERSIST_ENABLED`：未設＝開，設 `false` 才關。預設開，是因為會跑 `market_data.cli daily` 的只有本機的 `make morning` 和 `scripts/daily_report.sh`，NAS 不跑。
- 三段（日線、利率預期、事件）各自抓、各自交易寫入。任何一段失敗（來源掛掉、正式庫還沒跑 migration）都只印 `**WARN macro_series`／`rate_expectations`／`event_calendar`，不影響其他段和台股資料。單一序列抓不到，只會少那一列。
- 手動單跑：`uv run --env-file .env python -m market_data.cli macro [--period 2y]`，不看開關。
- `macro_brief.py` 只讀 DB、不連外。某段的表不存在或沒資料時印 `**WARN macro_brief` 並回 1；`make morning` 會忽略這個錯誤繼續跑。

## 儀表怎麼讀

腳本只列數字、不下結論，判讀規則在 skill `tw-morning-call` 的「大局」步驟。

- 序列：最新值、1週／1月／3月變化、距一年高點，以及在 MA60／MA200 之上還是之下；最新一列早於今天 5 個曆日以上標「過期」。
- Fed：最新快照裡未來 6 場會議的升息／不變／降息合計，以及一週前快照的升息機率（有一週前快照時才印）。
- 台股：加權對 MA20／60／120／240 的位置與距一年高點；外資、投信近 5／20 日的買賣超。金額是股數 × 當日收盤估算，只看方向與相對大小。
- 未來 14 天的事件（`--days` 可改）。
