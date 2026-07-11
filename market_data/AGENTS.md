# market_data — 台股行情爬取與統一 Postgres(market schema)

> 共通規則見 repo 根 `AGENTS.md`,本檔只寫本模組的增量。

## 模組定位

爬取台股行情/籌碼/財報歷史,寫入外部 Postgres 的 `market` schema——台股歷史資料的**唯一資料源**(無本地備份,遺失只能從官方端點重爬)。面板經 `data_provider/market_db_fetcher.py` 讀取(priority=1,台股日線優先本地 DB,查無資料 fallback yfinance)。連線設定只有一個:`.env` 的 `DATABASE_URL`(gitignored,勿寫死)。

## 檔案角色

- `crawl.py`:orchestration(`crawl_day`/`crawl_range` 帶 resume、`daily_update` 營運入口)
- `etl.py`:中文欄位→英文 typed 轉換;財報 melt 寬表→長格式
- `writer.py`:INSERT…ON CONFLICT upsert(重爬冪等)
- `market_repo.py`:面板讀取面(`price_history`/`to_daily_frame` 等)
- `health.py`:完整性/新鮮度稽核(thin price days 用**局部**中位數——全域中位數會被 16 年上市家數成長稀釋;報出的日子用 `backfill --force` 修)
- `migrations/`:Alembic,只管 `market` schema(不碰 `app`/`public`)
- `sources.py`/`crawler.py`:TWSE/TPEx/MOPS 原始爬取邏輯(移植而來),盡量少動
- `financial_statement.py`:IFRS 財報 html → 寬表解析(移植而來),盡量少動

## 數據更新(操作指令)

> 完整更新流程(何時 daily、何時 backfill、跑完怎麼用 health 驗收)見 skill `update-market-data`。以下為指令速查。

- 每日增量+快照:`uv run python -m market_data.cli daily`(近 5 天 price/institutional/margin + valuation/index/stock_info 快照 + 上月營收 + 除權息滾動窗;停跑超過 5 天要用 backfill 補洞)
- 補特定月營收/除權息:`… revenue --month 2026-06`、`… ex-dividend --start … --end …`
- 區間回補:`uv run python -m market_data.cli backfill price --start 2026-01-01 --end 2026-01-31`
- 修 partial/髒日(health 報 thin day):同上加 `--force`(忽略 resume、抓到完整資料才整日換血;不用手動 DELETE)
- 財報季更:`uv run python -m market_data.cli financials --year 2026 --season 2`(下載該季 IFRS html 包 → 解析 → upsert;完整性 fail-fast:解析不足 1000 檔或 Q4 缺同年 Q3 累計都直接失敗、全季回滾、保留下載檔,不寫半套資料)
- 健康稽核:`uv run python -m market_data.health`
- 模組測試(免裝面板全依賴):
  `export $(grep '^DATABASE_URL=' .env | xargs) && uv run --no-project --with sqlalchemy --with 'psycopg[binary]' --with pandas --with lxml --with requests --with tqdm --with pytest python -m pytest market_data/tests/ -q -m "not network"`
- 真網路 smoke(端點活性 + 面板走 DB 驗證,CI network-smoke 也跑):同上指令改 `-m network`

## 進來改要遵守

- schema 變更一律走 Alembic migration,不手改線上 DB。
- price 一天必須 TWSE+TPEx **兩市場都抓到才寫**(單邊寫入會讓 resume 標記該日完成、另一邊永久缺)——不要「順手優化」成單邊也寫。
- price 有**截斷防護**:單日合計低於附近 5 個交易日中位數九成(優先取之前的日期,無則取之後——倒序/空庫 bootstrap 也有基準;全空庫第一天無防護),先試 STOCK_DAY_ALL 備援(僅最新交易日、全列同日才收、缺本益比欄以 coalesce 保留舊值),仍不足整天跳過等 resume 重試——別移除這道門(TWSE 回過截斷但非空的回應)。
- `MarketDBFetcher` 只准服務 `.TW`/`.TWO`;查無資料要 raise `DataSourceUnavailableError` 讓 chain fallback,不要回空 DataFrame。

## 踩雷

- `monthly_revenue.revenue` 單位是**千元**(MOPS 原始單位);對照 `twse_fundamental_adapter` 是 `*1000` 轉元後才用。
- `monthly_revenue` **僅上市(sii)口徑**(歷史與現行皆同,上櫃全缺);要雙市場月營收請用 `twse_fundamental_adapter` 的即時快照。
- `price.market` **全欄為 NULL**(TWSE/TPEx 在爬取端已合併,無法逐列區分上市/上櫃)。
- 面板日線仍只經 `MarketDBFetcher` 消費 `market.price`。`market_repo.institutional()` + `stock_info()` 已有消費者——台股個股報告的**三大法人歷史趨勢**(連 N 日/近 20 日累計/佔股本比)在 `analyzer._format_prompt` 即時讀本 DB 算好注入 LLM prompt(prompt-only、fail-open、不入持久化 context);`monthly_revenue`/`valuation` 讀取函式仍無消費者。踩雷:估值/月營收數字走 `twse_fundamental_adapter` 即時 API、三大法人**當日**買賣超走網路(`TwInstitutionalFetcher`),都不是本 DB——只有三大法人**歷史趨勢**走本 DB。
- 財報季更不在 `daily` 裡,要手動跑 `financials`(發布時點與 Q4 推導前提見「數據更新」)。
- TWSE 可能回**截斷但非空**的回應(踩過:單日 price 少寫 300+ 筆且數值錯位);已寫入的髒日用 `backfill --start <該日> --end <該日> --force` 整日換血修復。
- 面板 venv 缺 `psycopg` 時 `MarketDBFetcher` 會**靜默熔斷降級 yfinance**(歷史看似正常,但可能混入非交易日的幽靈 K 棒);懷疑沒走 DB,先 `uv pip install -r requirements.txt` 再驗 `get_daily_data` 的 source。
