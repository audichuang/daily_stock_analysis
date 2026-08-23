# market_data — 台股行情爬取與統一 Postgres(market schema)

> 共通規則見 repo 根 `AGENTS.md`,本檔只寫本模組的增量。

## 模組定位

爬取台股行情/籌碼/財報歷史,寫入外部 Postgres 的 `market` schema——台股歷史資料的**唯一資料源**(無本地備份,遺失只能從官方端點重爬)。面板經 `data_provider/market_db_fetcher.py` 讀取(priority=1,台股日線優先本地 DB,查無資料 fallback yfinance)。連線設定只有一個:`.env` 的 `DATABASE_URL`(gitignored,勿寫死)。

## 檔案角色

- `crawl.py`:orchestration(`crawl_day`/`crawl_range` 帶 resume、`daily_update` 營運入口)
- `etl.py`:中文欄位→英文 typed 轉換;財報 melt 寬表→長格式
- `writer.py`:INSERT…ON CONFLICT upsert(重爬冪等)
- `market_repo.py`:面板讀取面(`price_history`/`to_daily_frame` 等)
- `adjust.py`:重建 `price_adjustment` 前復權因子(除權息+減資+分割三來源合一);`load_factors()` 是算報酬/均線前套用因子的唯一入口
- `health.py`:完整性/新鮮度稽核(thin price days 用**局部**中位數——全域中位數會被 16 年上市家數成長稀釋;報出的日子用 `backfill --force` 修)
- `migrations/`:Alembic,只管 `market` schema(不碰 `app`/`public`)
- `sources.py`/`crawler.py`:TWSE/TPEx/MOPS 原始爬取邏輯(移植而來),盡量少動
- `financial_statement.py`:IFRS 財報 html → 寬表解析(移植而來),盡量少動

## 數據更新(操作指令)

> 完整更新流程(何時 daily、何時 backfill、跑完怎麼用 health 驗收)見 skill `update-market-data`。以下為指令速查。本模組**不自載 `.env`**(不同於面板的 load_dotenv),指令一律帶 `--env-file .env`,否則 `DATABASE_URL is not set`。

- **自動更新**:本機 crontab 每天 15:00 跑 `daily`(cron 在 repo 外,log:`logs/market_data_cron.log`)。15:00 當日法人/融資融券尚未發布,由隔日 run resume 補齊(T+1);資料停更先查 `crontab -l` 與該 log。
- 每日增量+快照:`uv run --env-file .env python -m market_data.cli daily`(近 `crawl.RECENT_SESSIONS`=5 個交易日的 price/institutional/margin,**該區間的每個曆日都補**、缺日會被連續補回 + valuation/index/stock_info 快照 + 上月營收 + 除權息滾動窗 + 近期 `price_adjustment` 復權事件重算)
  - **復權事件是 daily 的一部分,不必另跑 `adjust`**:除權息抓取與 ±`adjust.ADJUSTMENT_WINDOW_DAYS`=90 天的因子替換在同一 transaction 完成,任一官方來源失敗就整包不寫、daily 直接報錯(不留半套因子)。只有修過 price 髒日或要重建全期,才需要下面的 `adjust`。
  - **落後超過 31 個曆日會直接拒跑**(`MAX_DAILY_RECOVERY_CALENDAR_DAYS`),訊息會叫你指定區間 backfill——這是刻意的,避免無界回補偷偷跑幾小時。
- 稽核:`uv run --env-file .env python -m market_data.cli health --strict`(`make morning`／`make swing` 已內建;近期缺日、TAIEX/法人/融資錯位、除權息缺因子、必備表為空就回非零)。它的近期視窗與 daily **共用 `RECENT_SESSIONS`**;全歷史 thin day 只報不擋(daily 修不到的東西不該擋每天的流程)。
- 補特定月營收/除權息:`… revenue --month 2026-06`、`… ex-dividend --start … --end …`
- 區間回補:`uv run --env-file .env python -m market_data.cli backfill price --start 2026-01-01 --end 2026-01-31`
- 修 partial/髒日(health 報 thin day):同上加 `--force`(忽略 resume、抓到完整資料才整日換血;不用手動 DELETE)
- 補下市公司的月營收(修存活偏誤):`uv run --env-file .env python -m market_data.cli revenue-pit --start 2019-06-01 --end 2026-07-24 --delay 3`(先加 `--dry-run` 看缺口數與預估耗時;逐公司逐月打 MOPS,不繼續公開發行的公司探測一次就跳過剩餘月份)
- 財報季更:`uv run --env-file .env python -m market_data.cli financials --year 2026 --season 2`(下載該季 IFRS html 包 → 解析 → upsert;完整性 fail-fast:解析不足 1000 檔或 Q4 缺同年 Q3 累計都直接失敗、全季回滾、保留下載檔,不寫半套資料)
- 重建前復權因子:`uv run --env-file .env python -m market_data.cli adjust`(除權息全期 + TWTAUU 減資 + 價格推導;修過 price 髒日或補了除權息之後要重跑)
- 健康稽核:`uv run --env-file .env python -m market_data.health`
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
- **月營收彙總報表有存活偏誤,而且是靜默的**:`crawler.crawl_monthly_report` 走的 `t21sc03_<民國年>_<月>.html` 看起來是按月存檔,實際是**動態產生**的,只列出目前仍在申報的公司。實測 2020-06 那份 979 家裡完全沒有 6452 康友、2448 晶電、2456 奇力新、5305 敦南、3698 隆達——這五檔當時全部還在交易。**用它回補歷史,後來下市的公司會永久缺席**,任何「要求營收成長」的選股條件都會把負尾系統性移除。修法是 `cli revenue-pit`(走 `sources.crawl_company_monthly_revenue`,MOPS 個別公司查詢),但只補得回**仍公開發行**的公司;被吸收合併的回「該公司不繼續公開發行」(如 2448 晶電併入富采),那部分是硬邊界,只能用敏感度分析給上界(`scripts/measure_signal_forward.py --survivorship-bound`)。
- **判定「已下市」要用 `price` 表的最後交易日,不是「不在 `stock_info` 裡」**:`stock_info` 只含上市約 1,100 檔,用它判定會把全部上櫃公司都算成下市(實測 70 檔 → 973 檔)。
- **`price.change` 對上市股票沒有正負號,算任何報酬都不要碰這一欄**——用 `close` 自己 diff。TWSE `MI_INDEX` 的 `漲跌價差` 只有絕對值,方向在獨立的 `漲跌(+/-)` 欄(`+`／`-`／空=平盤／`X`=無比價);`crawler.crawl_price` 曾把那欄 `to_numeric(errors="coerce")` 成 NaN 後被 dropna-all 整欄丟掉,**2013 起到 2026-08 入庫的上市列全部只有絕對值**(2026 年至今 95,211/353,563 列與 `close - lag(close)` 反號)。上櫃走 TPEx JSON(`漲跌` 本身帶號)沒中,`market_index.change` 走 FMTQIK 也沒中——所以症狀是「同一張表上市全正、上櫃正常」,不看市場別會以為資料沒問題。爬取端已於 2026-08-23 修好,但**歷史列沒有回補**(`to_daily_frame` 改成不再讀這欄,所以正確性不依賴回補);真要回補就用 `close - lag(close)` 重算。踩過:`to_daily_frame` 舊版用 `close - change` 回推昨收,讓上市股票每個下跌日的 `pct_chg` 都變成上漲,而那個欄位會進台股個股分析的 LLM prompt。
- **openapi 端點會停止更新卻照樣回 200**,消費端一律要比對回應自帶的民國日期欄。實測 2026-08-23:`opendata/twtazu_od`(漲跌家數)的 `出表日期` 還是 `1150605`,凍結 79 天,而同一時間 `FMTQIK`／`BFI82U`／兩支 TPEx 端點都是最新交易日。`sources.crawl_price_backup` 早就有這道門(註解寫「不能拿別天的資料冒充」),`data_provider/twse_fetcher.py::_fetch_breadth` 沒有,後果是台股大盤複盤連續 20 份印同一組家數、LLM 在上面疊出虛構敘事,而 exit code 一路正常。現已加上日期比對,並在拒收時退回 `data_provider/tw_breadth.py::closing_breadth()` 由本 schema 的前復權收盤自算(上市普通股、**無漲跌停家數**;上市名單只能取 `stock_info`,因為 `price.market` 全為 NULL)。
- **`price` 是未還原價,算報酬/均線/乖離前一律先套 `market.price_adjustment`**(`adjust.load_factors()`)。不要直接拿 `ex_dividend` 當還原來源——那張表走 TWSE 的 TWT49U,**只有上市除權息**,缺三類:上櫃(TPEx)全部、股票分割(面額變更)、減資。踩過:0050 的 1:4 分割(2025-06-18,188.65→47.57)不在 `ex_dividend`,讓回測的 0050 基準在 2025 年顯示 -65.79%。
- **上櫃除權息走 TPEx 官方端點 `bulletin/exDailyQ`**(`sources.crawl_tpex_ex_dividend`,吃**西元** `startDate`/`endDate`、回應日期是民國斜線格式,自 2008-01-02 起)。找它踩過四個坑:openapi `/tpex_exright_daily` 只回當日 13 筆;`/tpex_exright_prepost` 是預告表無參考價;`bulletin/exDailyQHis` 只涵蓋民國 89/9~96/12(頁面自己註明);舊版 `exDailyQ_result.php` 忽略日期參數。**找新站端點的通法**:抓舊 php URL(會 302 到新頁),在新頁 HTML 裡 grep `action:"..."`,拼成 `https://www.tpex.org.tw/www/zh-tw/<action>`。
- **上櫃股票在接上官方端點前幾乎沒有還原過**:價格推導的門檻是單日跳空 >11%,而除息通常只跳 1~5%,所以 10,892 筆官方上櫃除權息裡只有 481 筆被推導抓到(4.4%),其餘 10,411 筆完全缺漏。對照發現推導值與官方值的相對誤差中位 1.16%、最大 9.98%,61 筆誤差 >5%。改動後上櫃小型股的歷史報酬會系統性上修,**跨越這次修復的回測數字不可互相比較**。
- `price_adjustment.source` 標可信度:`twse_twt49u`/`tpex_exdailyq`/`twse_twtauu` 官方公告值 > `verified_manual` 人工核對白名單 > `inferred_price` 價格回推。推導依據是台股 ±10% 漲跌幅限制——**這個前提只對普通股成立**,ETF/ETN/TDR 依官方規則不受限制,推導必然製造假事件。踩過:00887 在 2024-10-08、10-14 的真實 -48%/-51% 崩跌(海外休市、溢價逾 200% 的價格異常)被判成兩次 1:2 分割,把跌幅改寫成 +3%/-2%,還讓之前的歷史價全乘 0.25。現由 `is_common_stock()` 一律排除,ETF 的真分割改走 `VERIFIED_ACTIONS` 白名單(目前只有 0050 的 1:4)。
- **TDR 有四位數代號**(9103 美德醫療-DR、9105 泰金寶-DR、9110 越南控-DR、9136 巨騰-DR),光靠長度擋不掉;而 9802、9904 寶成、9921 巨大這些 9 開頭的是正常普通股,不能整段排除 9,只能用 `91` 前綴區分。
- `rebuild()` 會先 `delete ... where date >= start` 再寫入,這是真正的重建——只 upsert 的話被新邏輯否決的錯事件(如 00887 的假分割)會永久殘留,改了判斷也清不掉。
- **推導值的已知限制**:剩餘的 `inferred_price` 主要是上櫃減資(TWTAUU 僅上市,無公開的上櫃減資端點),誤差來自以開盤價回推而非官方參考價。
- **停牌 gap 規則有例外,但例外有上限**:`STALE_GAP_DAYS=14` 的用意是「長期停牌後復牌的跳空反映停牌期間的資訊,不是公司行動」,但**比例吸附到精確 1/N 或 N 倍時收錄**——減資的停止買賣窗口本來就是 2~3 週,一刀切會把最常見的上櫃減資整批漏掉(實測 gap>=14 被排除的 152 筆裡有 13 筆是精確比例,11 筆的 gap 落在 14~28 天)。**但超過 `MAX_SPLIT_GAP_DAYS=60` 一律不推導**:停牌越久,「復牌價恰好落在 1/N 附近」越可能只是真實重估碰巧撞上比例,而推導錯一筆就把該檔之前的全部歷史價乘錯。6222(停牌 195 天)、6131(328 天)因此被排除,要收得先人工對官方公告再進 `VERIFIED_ACTIONS`。
- **`infer_rows` 會多讀 60 天歷史才算 `seq`/`gap`**,事件仍只收 `>= start`。不要「順手優化」成只查 `date >= start`——那樣任何既有股票在起點後前 6 根 K 的公司行動都會被 `MIN_BARS_BEFORE` 當成「新上市」永久漏記。
- **官方來源逐年抓取,任一年失敗就 raise**(`adjust._fetch_by_year`)。舊版只在「所有年度都失敗」時回空,於是「2018 那段回 None、其他年成功」的結果仍非空,`rebuild()` 照樣先刪整段再寫入缺 2018 的資料——缺一年官方除權息足以讓那年之後所有報酬計算全錯且無聲。
- **`--no-reductions` 不是破壞性操作**:它跳過兩個需要網路的官方來源(TWTAUU 減資、TPEx 上櫃除權息),但會用 `existing_official_rows()` 把 DB 既有的那些列讀回來一起寫入。改動 `rebuild` 時不要把這條拿掉——`rebuild` 會 `delete where date >= start`,只跳過抓取而不讀回來等於清空 10,879 筆上櫃除權息。
- `price` 表 **2010 上半年混有約 1,000 檔權證**(5 位數代號;每日 2,200+ 檔 vs 2011 之後的 1,380)。權證無漲跌幅限制,納入推導會生出兩萬筆假事件,故 `adjust` 預設從 **2013** 起算。
- TWSE 各表的民國日期格式**不一致**:TWT49U 是「113年01月22日」(`_roc_to_date`),TWTAUU 是「113/01/22」(`_roc_slash_to_date`)。用錯會讓每列 parse 失敗;`parse_reduction` 因此在「全數列都失敗」時 raise 而非靜默回空。
- `valuation` 的歷史**要自己回補**:`daily` 走的 `BWIBBU_ALL` 是無 date 參數的當日快照端點,所以這張表原本只有 3 週。回補走 `backfill valuation`(`sources.crawl_valuation_day` → `BWIBBU_d?date=&selectType=ALL`),**欄位順序隨年代變**(2015 五欄、2026 八欄且殖利率排到本益比之前),故靠回應的 `fields` 動態對應——用固定索引會讓舊資料的 PE 與 PB 整欄錯位。另:PE 也可用 `price.pe_ratio`(隨 price 一起回補,2010 起,覆蓋約 57%),PB 與殖利率則只有這條路。
- **快照段(valuation/index/stock_info)一律走 `crawl.crawl_snapshots()`,不要直接呼叫那三個函式**:直接呼叫會把 upsert 列數丟棄,而那正是唯一的可觀測訊號。踩過:2026-07-28 18:10 跑 `snapshot` 全無輸出、`market_index` 停在 07-27,得讀三層原始碼才確認是 TWSE FMTQIK **當日尚未發布**(不是 IP 被封、不是端點改版,三者處置完全不同)。`crawl_snapshots` 會印 `<name> <n> rows` 並對有日期維度的兩張表加印 `latest <date>`——**列數本身不夠**,這兩個端點回近月/全市場整包,當日未發布時照樣回一樣多的列(實測 `index 18 rows` 而最新仍是 07-27)。
- **`sources` 的取得層失敗只印 WARN、不 raise**:`_openapi_json`/`_valid_rows`/`_twse_csv` 對「連線失敗或 IP 被封」「HTTP 非 200」「非 JSON」「空 list(當日未發布)」「缺欄位(端點改版)」各印一種可區分訊息,但回傳契約仍是 `None`。所以**exit code 不會反映失敗**,自動化要判成敗得看 stdout 的 `**WARN:` 或列數,別只看 `$?`。
- **TWSE 密集請求會封 IP,而且失敗是靜默的**:`requests_get` 回 None → `crawl_day` 直接跳過該日、不報錯、不影響 exit code。踩過:回補 1,600 天 valuation 只寫進 40 天就被擋,stdout 全空看起來像成功。長區間回補一律加 `--delay 3`(`crawl_range(delay=)`);被擋之後要等封鎖解除才能續跑,resume 會自動跳過已寫入的日期。現有兩道防護:`crawl_range` 只打 `market.price` 已存的**交易日**(週末與假日不發請求——2024 春節休市 2/6~2/14 就是連續 7 個平日,光靠 weekday 擋不掉),且連續零列就 raise 中止。**門檻依有沒有日曆分流**:有日曆時 `_MAX_EMPTY_STREAK`(4);`price` 自己就是日曆來源、沒有日曆可用,退回只擋週末,此時零列還有「國定假日」這個正常解釋,故門檻放寬到 `_MAX_EMPTY_STREAK_NO_CALENDAR`(10,高過最長的連續平日休市)。**過濾用的是 price 表本身**,所以 price 缺的日子其他來源也會被跳過;`daily` 的窗口是**交易日**不是曆日(從 price 取最近 N 個交易日),會在 price 補上後自然重試。
- `price.market` **全欄為 NULL**(TWSE/TPEx 在爬取端已合併,無法逐列區分上市/上櫃)。
- 面板日線仍只經 `MarketDBFetcher` 消費 `market.price`。`market_repo.institutional()` + `stock_info()` 已有消費者——台股個股報告的**三大法人歷史趨勢**(連 N 日/近 20 日累計/佔股本比)在 `analyzer._format_prompt` 即時讀本 DB 算好注入 LLM prompt(prompt-only、fail-open、不入持久化 context)。`market.monthly_revenue`/`market.valuation` 兩張表仍持續由 `daily`/`revenue` 更新入庫,但面板讀取層(`market_repo`)目前無消費者——估值/月營收數字一律走 `twse_fundamental_adapter` 即時 API,不讀本 DB(故先前的 `market_repo.valuation()`/`monthly_revenue()` 讀取函式已移除;要重新消費本 DB 再補回讀取面)。踩雷:估值/月營收數字走 `twse_fundamental_adapter` 即時 API、三大法人**當日**買賣超走網路(`TwInstitutionalFetcher`),都不是本 DB——只有三大法人**歷史趨勢**走本 DB。
- 財報季更不在 `daily` 裡,要手動跑 `financials`(發布時點與 Q4 推導前提見「數據更新」)。
- TWSE 可能回**截斷但非空**的回應(踩過:單日 price 少寫 300+ 筆且數值錯位);已寫入的髒日用 `backfill --start <該日> --end <該日> --force` 整日換血修復。
- 面板 venv 缺 `psycopg` 時 `MarketDBFetcher` 會**靜默熔斷降級 yfinance**(歷史看似正常,但可能混入非交易日的幽靈 K 棒);懷疑沒走 DB,先 `uv pip install -r requirements.txt` 再驗 `get_daily_data` 的 source。
