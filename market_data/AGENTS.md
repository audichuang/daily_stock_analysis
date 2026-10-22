# market_data — 台股行情爬取與統一 Postgres(market schema)

爬 TWSE/TPEx/MOPS 歷史寫進 Postgres `market` schema——台股歷史的**唯一資料源**(無備份,丟了只能重爬)。連線只認 `.env` 的 `DATABASE_URL`,模組不自載 `.env`,指令一律 `uv run --env-file .env …`。面板經 `data_provider/market_db_fetcher.py` 讀取。
`risk_flags.py`/`events.py` 只抓不入庫(不寫 DB、不建表),HTTP 一律走 `tw_official_http.py`(不走 `crawler.requests_get`),它**不判新鮮度**,呼叫端自己比對回應日期。`sources.py`/`crawler.py`/`financial_statement.py` 是移植來的,盡量少動。

## 寫入與 schema

- schema 只走 Alembic(`migrations/`,只管 `market` schema),不手改線上 DB。
- price 一天 TWSE+TPEx **兩市場都到才寫**——單邊寫入會讓 resume 標記該日完成、另一邊永久缺。別「順手優化」。
- price 的**截斷防護**(低於近 5 日中位數九成 → STOCK_DAY_ALL 備援 → 仍不足整天跳過)不要移除:TWSE 回過截斷但非空的回應。
- 會被官方事後修正的來源要加進 `crawl.REVISED_SOURCES`(目前是 institutional 與 institutional_tpex,T86 18:00 是初版、上櫃比照);沒列進去的會凍結在初版。
- 快照段(valuation/index/stock_info)只經 `crawl.crawl_snapshots()`;直接呼叫會丟掉列數與 `latest <date>`,那是唯一的可觀測訊號。
- `sources` 取得層失敗只印 `**WARN`、回 `None`,exit code 不反映失敗;新來源照這個契約,自動化判成敗看 stdout。
- psycopg 多列 INSERT 的 `rowcount` 不可靠(要數就 `RETURNING`);單一 INSERT 綁定參數上限 65,535,寬表要分批(`funds._chunks`)。
- `adjust` 的重建是先刪區間再寫,所以官方來源抓不齊就要 raise、離線模式要讀回既有官方列——`_fetch_by_year`、`existing_official_rows`、`infer_rows` 的 docstring 寫了不能「順手優化」掉的理由。

## 讀取語意

- `price` 是**未還原價**:算報酬/均線/乖離前一律套因子,唯一入口 `adjust.load_factors()`;休市日事件只由 `adjust.snap_events_to_sessions` 搬到下一交易日(表內日期不動)。`ex_dividend` 只有上市除權息,不是還原來源。
- `price_adjustment` 每檔每日一列,同日多事件留優先來源、**不相乘**(`merge_adjustment_rows`);改復權鏈前先想清楚。
- **`price.change` 算報酬一律不碰**(上市歷史曾無正負號、`X` 存成 0);用 `close` 自己 diff,但方向不能用 `close - lag(close)` 重算(官方比的是參考價)。
- `institutional`/`margin`/`valuation` 上市與上櫃共表,以 `market` 欄區分(**NULL = 上市**、`'tpex'` = 上櫃;上櫃法人自 2018-01-15 起)。寫入、resume、replace 的刪除與 `health` 稽核都要分市場——不分的話,上市法人每晚整日換血會連同日上櫃列一起刪(`crawl.SOURCE_MARKET`、`crawl.market_filter`;`daily` 對上櫃來源只報不擋)。**上線順序**:migration → 新程式部署到所有寫入端 → 才開始抓上櫃;舊程式看不到 `market` 欄,上櫃資料先進來的話,它的 resume／整日換血會把兩市場當同一天處理。降版在有上櫃列或集保資料時會拒絕(只有一份、無備份),回滾要先停排程、用新程式清掉上櫃列再降版、最後才退程式(`docs/tw-stock-dossier.md`);`price.market` 全為 NULL;判定下市用 `price` 最後交易日,不是「不在 `stock_info`」(它只有上市)。
- `monthly_revenue.revenue` 單位是**千元**;`crawler.crawl_monthly_report` 有存活偏誤(只列仍申報的公司),補歷史走 `cli revenue-pit`。
- `MarketDBFetcher` 只服務 `.TW`/`.TWO`;查無資料 raise `DataSourceUnavailableError` 讓 chain fallback,不回空 DataFrame。
- `market_data` 內要交易日曆一律用 `health.expected_session`/`sessions_after`/`session_before`,不 import `src.core.trading_calendar`;`health` 的函式名與簽名是 `scripts/daily_report.sh` 的契約。

## 測試

- **DB 測試一律用 `pg_conn` fixture 並自己種資料**:本機 conftest 從 `.env` 讀 `DATABASE_URL`,連的是正式庫,`pg_conn` 才保證 rollback,直接拿 `engine` 寫就是寫進正式庫。CI 是已遷移的空庫,種子用遠離真實資料的年份(1900／2099)。
- 新增表時本機 pg 測試在正式庫 migration 前必紅:先 `make pg-scratch`,照它印的 `DATABASE_URL` export 後再跑。

## 其他

- 踩雷案例、實測數字與資料語意全文:`docs/market-data-pitfalls.md`;境內基金(`funds.py`):`docs/tw-funds.md`。
- 怎麼更新/回補/稽核/跑模組測試:skill `update-market-data`。
