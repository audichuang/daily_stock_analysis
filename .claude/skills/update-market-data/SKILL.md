---
name: "update-market-data"
description: "更新/回補 market schema 的台股行情資料(price/institutional/margin/valuation/index/stock_info)：判斷該跑 daily 還是 backfill，執行後用 health 稽核確認補齊。當使用者要更新行情、或發現 market data 停更/有缺口時使用。"
---

# 行情資料更新 (Update Market Data)

`market_data` 模組的更新 runbook。爬取皆 **resume**(冪等補洞),寫外部 Postgres 的 `market` schema(連線只認 `.env` 的 `DATABASE_URL`)。事實面——來源上限、欄位單位、踩雷案例——以 `docs/market-data-pitfalls.md` 為準(改 code 的不變式在 `market_data/AGENTS.md`);本技能只定「怎麼跑、跑完怎麼算數」。

## 前置

- 在 repo 根目錄執行,`.env` 已設 `DATABASE_URL`。模組不自載 `.env`,指令一律帶 `--env-file .env`。
- **同時只跑一個爬取程序**(單一寫入者);並發會互鎖,也可能破壞「兩市場都到才寫」的規則。

## 步驟

### 1. 先稽核落差

```
uv run --env-file .env python -m market_data.health
```

輸出每表 `rows / start~end`、price/institutional/margin 的 `thin days` 與 `missing valuation dates`(窗口內除最新一日外缺估值的交易日,`--strict` 會擋;重跑 `daily` 補)(單日列數低於前後交易日局部中位數九成 = 疑似單邊市場缺漏或截斷寫入)。
**完成判準**:能說出每個資料集落後到哪一天、以及 thin days 清單。
`expected session: YYYY-MM-DD (price ✓/✗, TAIEX ✓/✗)` 那一行是絕對新鮮度(交易日 17:00 後要有當天、之前要有前一交易日,price 與 TAIEX 缺任一邊 `--strict` 就非零);✗ 表示該場次尚未入庫(未發布或被封),發布後重跑 `daily`;印 `skipped` 代表本機沒有 `exchange_calendars`、此檢查未生效。
財報看 `financial_statement` 的 `end` 與 `stale financial quarters` 那一行(它印的是會計期間 + 截止日 + 該跑的 `financials` 指令,**只報不擋**,exit code 不會反映它)。
另有三行全歷史稽核**只報不擋**:`full-history gaps <institutional|margin|valuation>`(自該表首日起 price 有而該表整天沒列的日子,附 `backfill … --delay 3` 指令;`missing_*_dates` 只看近 `RECENT_SESSIONS` 個交易日,滑出窗口的缺日只有這裡會喊)、`coverage vs price`(三張表只收上市,差距就是上櫃,設計如此)、`price_adjustment events on non-session dates`(休市日事件,讀取端已搬到下一交易日,**預期且永久,不要刪列**)。
`expected session` 印 `skipped` 時**不會**退回週一~五(否則國定假日誤擋);颱風等日曆不知道的臨時休市日 18:00 會被擋並推 Bark,刻意寧吵勿默。

### 2. 依落差選路徑

- **落後超過 31 個曆日** → `daily` 會直接拒跑(`MAX_DAILY_RECOVERY_CALENDAR_DAYS`,刻意避免無界回補偷跑幾小時),照訊息改用下面的區間 backfill。
- **落後 ≤ 5 天(例行)** → `uv run --env-file .env python -m market_data.cli daily`(近 5 天增量,含 valuation 缺日以 BWIBBU_d 補回 + 快照 + 上月營收 + 除權息滾動窗;法人另把近期已入庫的日子重抓成證交所定版——stdout 的 `refresh institutional N/M days` 是重抓結果,`**REVISED` 表示官方改過數字並已換掉,`**WARN refresh` 表示沒抓到、保留舊資料)。
- **補特定月營收/除權息區間** → `… revenue --month YYYY-MM` / `… ex-dividend --start … --end …`(月營收上市＋上櫃各抓一份彙總報表,一邊失敗只少那一邊——看 stdout 的 `**WARN`)。
- **落後 > 5 天,或有洞** → 區間回補:
  ```
  uv run --env-file .env python -m market_data.cli backfill {price|institutional|margin} --start YYYY-MM-DD --end YYYY-MM-DD
  ```
  backfill 支援 price/institutional/margin/valuation(valuation 走 BWIBBU_d,回應日期不符請求日會 `**WARN` 拒收);index/stock_info 走 `uv run --env-file .env python -m market_data.cli snapshot`。
- **health 報 thin days(該日有列但不完整)** → 對那幾天加 `--force` 整日換血:
  `… backfill price --start <該日> --end <該日> --force`(resume 認「有列即完成」,不加 --force 補不動)。
- 區間長(數月以上)→ 一律加 `--delay 3` 並背景執行(會跑數小時);TWSE 密集請求會**靜默**封 IP(stdout 全空像成功),連續零列達門檻 `crawl_range` 會 raise 中止——等封鎖解除後**重跑同指令**即 resume 續補。
- **valuation 的 `--force` 只有列數門檻、沒有欄位品質守門**:來源少一欄就整欄蓋成 NULL。整段 `--force` 前先備份該區間、抽一兩天試跑比對,再放全段。
- **2016-01-30、2017-06-03(補班週六)的 `thin institutional days` 是官方 T86 本身就少**,不是缺漏,別 `--force`。
- **補下市公司的月營收(修存活偏誤)** → `uv run --env-file .env python -m market_data.cli revenue-pit --start YYYY-MM-DD --end YYYY-MM-DD --delay 3`(先加 `--dry-run` 看缺口數與預估耗時)。
- **重建前復權因子** → `uv run --env-file .env python -m market_data.cli adjust`(預設 2013 起全期;`daily` 已含近期復權事件,只有修過 price 髒日、補了除權息區間或要重建全期才需要)。
- **財報落後一季以上**(monthly_revenue/financial_statement 的 end 過舊)→ 季更:
  ```
  uv run --env-file .env python -m market_data.cli financials --year YYYY --season {1..4}
  ```
  發布時點:Q1→5/15 後、Q2→8/14 後、Q3→11/14 後、Q4(年報)→隔年 3/31 後。
  下載整季 IFRS html 包(約 1-2 GB,解析+upsert 後自動清除;除錯才加 `--keep-files`)。
  Q4 單季損益由「年報累計 − DB 的 Q3 累計」推導,**跑 Q4 前確認同年 Q3 已在庫**。

### 3. 驗證

再跑 `uv run --env-file .env python -m market_data.health`。
**完成判準**:目標資料集 `end` 已推進到預期交易日,且 **price/institutional/margin 的 thin days 都沒有新增**。

## 自動更新停了

平日 18:00 由 Orca 排程跑 `make daily-report-detached`(`daily` → `health --strict` → 報告;失敗推 Bark、不出報告,log 在 `logs/daily_report_*.log`)。資料停更先查 `orca automations runs --id <id>` 與該 log,再回到步驟 1。

## 模組測試

`market_data/tests/conftest.py` 會自己從 `.env` 讀 `DATABASE_URL`——**本機連的是正式庫**(寫入走 `pg_conn` 才會 rollback);新增表或不想碰正式庫時先 `make pg-scratch`,照它印的 `DATABASE_URL` export 後再跑。免裝面板全依賴:

```
uv run --no-project --with sqlalchemy --with 'psycopg[binary]' --with pandas --with lxml --with requests --with tqdm --with pytest --with pytest-timeout python -m pytest market_data/tests/ -q -m "not network"
```

改 `-m network` 是真網路 smoke(端點活性 + 面板走 DB);「面板走 DB」那支只有本機會真的斷言(CI 排除 network、排程 network-smoke 沒有 `DATABASE_URL` 會 skip)。

## 別踩(細節見 `docs/market-data-pitfalls.md`)

- **財報不在 `daily` 裡**:新季報要手動跑 `financials`(見步驟 2),別以為 `daily` 會補進財報。
- **兩市場鐵則**:price 一天要 TWSE+TPEx 都抓到才寫。別「順手優化」成單邊也寫——會讓 resume 標記該日完成、另一市場永久缺,正是 thin days 的來源。
