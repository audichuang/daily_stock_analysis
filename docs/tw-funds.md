# 台灣境內基金：資料來源、API 與持倉

系統支援台灣境內基金（共同基金、ETF 和各級別）。功能包括淨值查詢、歷史走勢、報酬與風險、前十大持股，以及股票帳本之外的基金持倉。Web 入口是 `/funds`。

## 資料來源

| 資料 | 來源 | 可信度 | 更新 |
|---|---|---|---|
| 每日淨值 | 投信投顧公會 `nav.csv`（政府開放資料平台 dataset 11109） | 官方 | 每天，`market_data.cli daily`／`funds` |
| 基本資料（名稱、類型、ISIN、規模、成立日、配息） | 投信投顧公會基本資料 CSV（dataset 43476） | 官方 | 月更，與淨值同一輪一起抓 |
| 歷史淨值 | 鉅亨 `fund.api.cnyes.com` 的 `format=chart` | 非官方 | 第一次查詢或建立持倉時補全期；之後 `daily` 每天補近 35 天 |
| 前十大持股 | 鉅亨 `/funds/{cnyesId}/holdings` | 非官方 | 頁面開啟時即時抓，不入庫 |

- **基金主鍵是公會的「基金統編」**（`fund_id`，例如安聯台灣科技 `18480065`）。級別會在統編後加字母尾碼，例如 `00526748A`。公會檔另有「基金代號」（如 `DDO04`），但它在淨值檔裡重複了 529 次，所以不能當鍵。
- **公會淨值檔一份混有多個淨值日**。2026-10-21 23:00 實測：3,931 列是 10/20，486 列是 10/21，因為各投信公布的時間不同。入庫一律用每列自帶的日期，不用抓取日。頁面和 API 都會帶出 `nav_date`；晚上看到前一天的淨值是正常的。
- **公會檔只保留每檔最新一筆**。某天的淨值如果在下一輪抓取前就被隔天的值取代，那一天就會缺。所以只要基金已經有鉅亨對照（被查過或持有過），`daily` 會從鉅亨補近 35 天。沒被查過的基金只累積公會的每日值，歷史可能有洞，第一次打開詳情時會補齊全期。
- **鉅亨只補缺日、不覆蓋官方值**（`ON CONFLICT DO NOTHING`）。之後公會同一天的值進來會蓋掉鉅亨的值。`fund_nav.source` 標出每一筆的來源（`sitca`／`cnyes`）。
- **鉅亨代碼的對應方式**：用 ISIN 搜尋鉅亨，結果的 ISIN 要完全相符才寫進 `fund_info.cnyes_id`。鉅亨的搜尋是模糊比對，同一次搜尋會回傳別的基金。
- **鉅亨的 `tradeDate` 是淨值日的台北 00:00**。例如 1792512000 是 UTC 2026-10-20 16:00，對應公會檔 20261021 那一筆。用 UTC 取日期會讓整串早一天。

## 儲存

- `market.fund_info`、`market.fund_nav`：Alembic revision `c7d2e9f41a08`。寫入在 `market_data/funds.py`，讀取在 `market_data/market_repo.py` 的 `fund_*` 函式。
- `dsa.portfolio_fund_holdings`（應用庫，由 `create_all` 建立）：基金持倉表，只存通路、基金統編、單位數、總成本、對帳日和備註。**不存價格**，市值在讀取時用最新淨值現算。
- **基金刻意不併進股票帳本**（`portfolio_trades`）。基金代碼進了那張表，會被即時報價和每日個股分析當成 A 股代碼處理：找不到報價，而且是靜默失敗。

## 操作

```bash
# 每日（已含在 market_data.cli daily；基金段失敗只印 **WARN fund_nav，不擋股票資料與報告）
uv run --env-file .env python -m market_data.cli funds
# 補單檔歷史（不覆蓋公會值）
uv run --env-file .env python -m market_data.cli fund-history 18480065 73990253
# 新鮮度（只報不擋，health 內的一行）
uv run --env-file .env python -m market_data.cli health
```

## API（`/api/v1/funds`）

| 方法與路徑 | 說明 |
|---|---|
| `GET /search?q=&limit=` | 依名稱、投信、統編或 ISIN 搜尋；有淨值的排前面 |
| `GET /{fund_id}` | 詳情：基本資料、最新淨值與淨值日、`is_stale`（淨值日逾 10 天）、`returns`（`w1`/`m1`/`m3`/`m6`/`ytd`/`y1`/`y3`/`y5`，%）、`risk`（近一年 `max_drawdown`、`volatility`，%）。歷史少於 30 筆時先從鉅亨補；補失敗時填 `history_error`，其餘照常回 |
| `GET /{fund_id}/nav?days=` | 淨值歷史（升序） |
| `GET /{fund_id}/holdings` | 前十大持股；來源失敗時 `items=[]`、`error=source_unavailable`，找不到鉅亨對照時 `error=not_mapped`，HTTP 仍是 200 |
| `GET /holdings` | 基金持倉＋估值；缺淨值的那一筆 `market_value`／`pnl` 為 null，該幣別的合計也是 null，不會用 0 冒充 |
| `POST /holdings`、`PUT /holdings/{id}`、`DELETE /holdings/{id}` | 新增、修改、刪除持倉；同通路同基金重複時回 409 `duplicate_holding` |

錯誤碼：`fund_not_found`（404）、`fund_data_unavailable`（503，market schema 連不上或尚未遷移）。

## 已知限制

- 報酬是淨值日對淨值日計算，**未含配息**，配息型級別的報酬會被低估。期間起點取當天或之前的最後一筆淨值，跟鉅亨公布的報酬可能差幾個百分點，因為兩邊的基準日算法不同。2026-10-21 對照安聯台科：近 1 月、近 1 年完全一致，近 3 月差約 4 個百分點。
- 前十大持股是鉅亨整理的投信月報，有一到兩個月的落後；以投信公告為準。
- 境外基金（集保的境外基金資訊觀測站）不在範圍內。
- 基金沒有每日 LLM 分析。持有建議由 `portfolio-check` 結合報酬、回撤、持股重疊來判斷。
