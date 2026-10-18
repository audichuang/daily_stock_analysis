---
name: "update-market-data"
description: "更新/回補 market schema 的台股行情資料(price/institutional/margin/valuation/index/stock_info)：判斷該跑 daily 還是 backfill，執行後用 health 稽核確認補齊。當使用者要更新行情、或發現 market data 停更/有缺口時使用。"
---

# 行情資料更新 (Update Market Data)

`market_data` 模組的更新 runbook。爬取皆 **resume**(冪等補洞),寫外部 Postgres 的 `market` schema(連線只認 `.env` 的 `DATABASE_URL`)。事實面——檔案角色、來源上限、欄位單位、踩雷——一律以 `market_data/AGENTS.md` 為準;本技能只定「怎麼跑、跑完怎麼算數」。

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

### 2. 依落差選路徑

- **落後 ≤ 5 天(例行)** → `uv run --env-file .env python -m market_data.cli daily`(近 5 天增量,含 valuation 缺日以 BWIBBU_d 補回 + 快照 + 上月營收 + 除權息滾動窗;法人另把近期已入庫的日子重抓成證交所定版——stdout 的 `refresh institutional N/M days` 是重抓結果,`**REVISED` 表示官方改過數字並已換掉,`**WARN refresh` 表示沒抓到、保留舊資料)。
- **補特定月營收/除權息區間** → `… revenue --month YYYY-MM` / `… ex-dividend --start … --end …`(月營收上市＋上櫃各抓一份彙總報表,一邊失敗只少那一邊——看 stdout 的 `**WARN`)。
- **落後 > 5 天,或有洞** → 區間回補:
  ```
  uv run --env-file .env python -m market_data.cli backfill {price|institutional|margin} --start YYYY-MM-DD --end YYYY-MM-DD
  ```
  backfill 支援 price/institutional/margin/valuation(valuation 走 BWIBBU_d,回應日期不符請求日會 `**WARN` 拒收);index/stock_info 走 `uv run --env-file .env python -m market_data.cli snapshot`。
- **health 報 thin days(該日有列但不完整)** → 對那幾天加 `--force` 整日換血:
  `… backfill price --start <該日> --end <該日> --force`(resume 認「有列即完成」,不加 --force 補不動)。
- 區間長(數月以上)→ 背景執行(禮貌延遲會跑數小時);中斷後**重跑同指令**即 resume 續補。
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

## 別踩(細節見 `market_data/AGENTS.md`)

- **財報不在 `daily` 裡**:新季報要手動跑 `financials`(見步驟 2),別以為 `daily` 會補進財報。
- **兩市場鐵則**:price 一天要 TWSE+TPEx 都抓到才寫。別「順手優化」成單邊也寫——會讓 resume 標記該日完成、另一市場永久缺,正是 thin days 的來源。
