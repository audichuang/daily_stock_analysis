# 總經、Fed 利率預期與重大事件（market schema）

`market_data.cli daily` 每天把台股以外的「大局」數據寫進 `market` schema 三張表，`make morning` 的「大局」段（`scripts/macro_brief.py`，也可 `make macro` 單跑）從 DB 印出來，給 skill `tw-morning-call` 的大局判讀用。2026-10-26 起。

## 三張表

| 表 | 一列是什麼 | 來源 | 鍵 |
| --- | --- | --- | --- |
| `macro_series` | 一個序列一個交易日的收盤值 | yfinance 日線；2／10 年期美債另抓 FRED `fredgraph.csv`（免金鑰） | `(series_id, date)` |
| `rate_expectations` | 某天快照裡、某場 FOMC、某個結果（升 >25bp／升 25bp／不變／降 25bp／降 >25bp）的機率 | Kalshi `KXFEDDECISION` 公開 API（免金鑰） | `(snapshot_date, meeting_date, outcome)` |
| `event_calendar` | 一個事件（FOMC 決議日、watchlist 財報日、美國經濟數據、ISM、央行理監事會） | Fed 官網 `fomccalendars.htm` ＋ Kalshi；財報走 yfinance `Ticker.calendar`；經濟數據走 FRED 行事曆（BEA、Census 備援），首發值走 ALFRED；ISM 規則推估；央行是 repo 內常數表 | `(event_type, symbol, label)` |

序列清單只有一份：`market_data/macro.py` 的 `SERIES`。`scripts/overnight.py` 取其中 `overnight=True` 的那幾列，不另外維護。要加序列改那裡，下一次 daily 就開始累積；要補歷史跑 `cli macro`。

## 語意與坑

- **日期是資料列自帶的交易日**，不是抓取日。期貨與匯率在台北白天抓到的最後一列是盤中值，下次抓取同日會被覆蓋；`make morning` 07:30 跑的時候美股已收盤。
- **存的是不做除息還原的收盤**（`auto_adjust=False`），代價是 ETF（HYG、EWT）除息日會有一個小缺口。Yahoo 的 `Close` 本身已做分割調整：股票分割後，Yahoo 會把整段歷史換成新尺度。所以 daily 每次**整段重抓近 2 年**（儀表的一年高點與 MA200 都落在這段裡），不能只抓近期，否則分割後新舊列會是兩種尺度（例：一檔 1 拆 2，舊列沒更新，就會算出假的 −50% 回撤）。2 年以前的列可能停在舊尺度，儀表不讀那段。
- **殖利率類（`kind=yield`）單位是百分比**（4.99 = 4.99%），儀表的變化用 bp 表示。
- **機率用買賣價中點，不用 `last_price`**：最後成交可能是很久以前的。實測 2026-10-26 的 2027 年 3 月「降 25bp」最後成交 0.35，買賣價卻是 0.06／0.13。沒有賣單（ask 為 0）的結果記 `prob_mid = NULL`，儀表會標「無報價」，不當成 0。各結果是獨立合約，中點加總不一定是 100%。
- **利率預期沒有歷史快照可補**：Kalshi 只給「現在」的報價，所以 `rate_expectations` 只從開始入庫那天起累積。漏跑一天就永遠少一天，降版 migration 在表內有資料時會拒絕。
- **FOMC 決議日以 Fed 官網為準**：取每場會議的最後一天，跨月會議（`April/May` + `30-1`）取後一個月，非例會（unscheduled、notation vote）略過。Kalshi 合約收盤時間換成美東日期當交叉對照；官網抓不到的那天只剩 Kalshi：不刪任何 FOMC 列，`estimated` 也不覆蓋已經 `confirmed` 的同一場會議；`source` 欄是 `fed+kalshi`（一致）、`fed(kalshi不符)`、`fed`、`kalshi`（官網還沒列，`status=estimated`）。
- **財報日一律 `estimated`**：yfinance 不給確認狀態，而且實測 MSFT 2026-10-28 盤後的財報，yfinance 給的是 10-29。看到財報日要知道可能差一天。財報的 `label` 是財報日所在季度（`2026Q4`），同季改期會更新同一列；跨季改期時，同一檔未來日期、但這次沒抓到的那筆會被刪掉，已經過去的事件不刪。
- watchlist 預設 `MSFT GOOGL AMZN META AAPL NVDA TSM MU AVGO AMD ORCL TSLA`，用 `.env` 的 `MACRO_EARNINGS_WATCHLIST`（逗號分隔）覆蓋。
- 台灣法說會**還沒入庫**：法說會由 `market_data/events.py` 即時抓、只出現在 screen 報告的事件日曆。

## 經濟數據、首發值與事件日程（2026-10-27 起）

- **`FRED:ICSA`（初領失業金）進 `SERIES`**，標 `freq="weekly"`：第 4 項研究要 1967 年起的長歷史。`macro_series` 存的是 FRED 的**修訂後值**，不是首發值；週頻序列**不進儀表的日線表**（那張表的 1週／1月／3月是列數 5／21／63，套在週資料上會變成 5 週／5 個月／1 年）。`Series` 的 `freq` 有預設 `daily`。
- **`PAYEMS`、`UNRATE` 不進 `SERIES`**：月頻且會修訂，放進日線表語意會錯。它們只以**首發值**存在 `event_calendar` 的 `actual_value`。
- **`event_calendar` 追加的可空欄位**（migration `a6c1e3f5b7d9`，舊的 FOMC／財報列為 NULL）：`released_at`（公布時刻）、`series_id`、`observation_date`（參考期）、`actual_value`、`prior_value`、`actual_vintage`、`actual_source`。主鍵不變。
- **事件類型**（`symbol='US'`，`label` 是公布日 ISO，所以 FRED／BEA／Census 對同一場公布寫到同一列）：`cpi`（`CPIAUCSL`）、`nfp`（`PAYEMS`）、`unrate`（`UNRATE`，與 NFP 同日另開一列）、`retail`（`RSAFS`）、`pce`（`PCEPI`）、`claims`（`ICSA`）、`ism`（無序列）、`cbc`（`symbol='TW'`，無序列）。CPI／PCE／零售存的是**指數水準或金額水準**，不是月增率。
- **公布時間來源**：FRED `releases/calendar?rid=…&y=今年`（CPI=10、就業=50、零售 advance=9、PCE=54、初領=180）為主，HTML 用 regex 取；解析到 0 筆就印 `**WARN`。**FRED 頁面的時間是美中時間（America/Chicago），不是美東**：`7:30` ＝ 08:30 ET ＝ 夏令 12:30Z／冬令 13:30Z（與 BEA ICS 的 UTC 時間對過 PCE 10-29、11-25）。FRED 只給當年，12 月下旬的 14 天窗口會變空：PCE 用 BEA ICS（UTC 時間）、零售用 Census 行事曆（美東）補，**只在 FRED 沒有今天以後的下一筆時才補**，而且只補晚於 FRED 最後一筆的日期。FRED 請用 requests 預設 UA（帶瀏覽器 UA 實測逾時過一次，僅觀察到一次）。
- **BLS 不可用**（`bls.gov/schedule` 與 .ics 一律 403，帶完整瀏覽器標頭也一樣）；**ISM 不可機器讀取**（`ismworld.org` 回 reCAPTCHA）。所以 ISM 製造業只用規則：每月第一個美國營業日 10:00 ET（`USFederalHolidayCalendar`），`status=estimated`、`source=rule`，不刪不覆蓋 `confirmed`。規則日可能與 ISM 實際日期差一天以上，漏看就是漏看。
- **央行理監事會** `macro.CBC_BOARD_MEETINGS`（常數表，台北日期，`cbc`／`confirmed`）：**只放央行已確認的場次**，來源是 `cbc.gov.tw/tw/lp-357-1.html` 的「N 年 M 月 D 日央行理監事會後記者會」標題，該頁只列已開過的會。現有 114-09-18、114-12-18、115-03-19、115-06-18、115-09-17。**待補：115 年 12 月場次與 116 年全年**，等央行年度公告後人工加進常數表，**不得用「每季第三個週四」之類規則推算**。公布時間（會後記者會）沒有核實，`released_at` 用 16:00 台北當佔位、`time_note` 標「時間待確認」。常數表漏更新時，「今日待公布」就看不到央行。
- **首發值**：公布時間一過，daily 對 `released_at <= 現在`、有 `series_id`、`actual_value` 還是 NULL 的列向 **ALFRED** 取值（`fetch_first_release`；每次最多 60 筆、新的優先，首跑會回補年內歷史）。ALFRED 免金鑰 CSV：`alfred.stlouisfed.org/graph/alfredgraph.csv?id=…&cosd=…&vintage_date=公布日`，**參數是單數 `vintage_date`**；複數 `vintage_dates`、或對 `fredgraph.csv` 加 `vintage_date` 都會被**靜默忽略、回最新值**，所以 `parse_alfred_csv` 要求表頭後綴 `<代號>_YYYYMMDD`（例如 `ICSA_20261010`），沒有後綴就 raise。取 vintage 的最後一個 observation 當首發值、前一個當**前值（那個 vintage 裡的前值，已含當次修訂）**。ALFRED 可能比公布時間晚幾小時才收進來：公布日 vintage 的最後一筆日期若沒有比前一天 vintage 新就當作還沒收到、留 NULL，隔天再補（vintage 釘在公布日，晚抓不會拿到修訂值）。寫入 first-write-wins（`UPDATE … WHERE actual_value IS NULL`），每天重抓行事曆的 upsert 也不會洗掉它（首發欄位不在更新欄位內）。之後由 T-snapshots 的 append-only 快照補「第一次看到」的紀錄，不另發明第三種機制。`api.stlouisfed.org/fred/series/vintagedates` 要金鑰、不用。
- **改期**：FRED 行事曆某 `(event_type, 年)` 這次抓成功時，才刪掉該類型、該年度、今天以後、這次沒抓到的 label；備援與規則批次、FRED 掛掉時什麼都不刪。
- **不寫「高於／低於預期」**：沒有 PIT（當時點）共識。儀表只印首發實際值、前值與「無共識」，測試擋這幾個字。

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
- **隔夜已公布／今日待公布**（`print_release_columns`，用 `released_at`）：分界是前一台股場次 13:30 台北到次一場次 13:30 台北。已公布列印名稱、公布時間（台北／美東）、首發實際值（參考期）、前值、vintage、固定字樣「無共識」；ALFRED 還沒收到就印「首發值尚未入庫」。待公布列印時間與事件，「部位暴露」留給判讀的人寫。沒有 `released_at` 的舊列（FOMC、財報）只在下面的 14 天清單。週一早上看得到上週五晚上的 NFP。已發生的夜盤反應不算進來，只提示看『期交所籌碼』段，避免把已反應的漲跌當成可拿到的報酬。
- 未來 14 天的事件（`--days` 可改）；ISM 是規則推估日。
