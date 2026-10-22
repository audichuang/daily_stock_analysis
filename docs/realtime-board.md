# 实时盯盘看板（Realtime Board）

Web `/board` 页面：以表格展示自选队列（watchlist）的实时报价，前端每 30 秒轮询一次并支持手动刷新。

## 顯示範圍：自選／持股／全部

右上角切換（記在 localStorage `dsa.board.scope`，預設「全部」）：
- **自選**：`STOCK_LIST`（`/api/v1/stocks/watchlist`）。
- **持股**：持股帳本全部帳戶的部位（`/api/v1/portfolio/snapshot?include_realtime=false`，股數 > 0），同一代碼跨帳戶合併、成本按股數加權；「持股／損益」欄用盯盤的即時價現算未實現損益（以交易幣別計，美股是 USD），滑鼠移上去顯示所屬帳戶。賣光就自動消失，不必改 `STOCK_LIST`。
- **全部**：自選在前，再接自選裡沒有的持股，不重複。
- 帳本讀不到時只顯示自選並在標題下提示；三個來源（自選、帳本、基金）各自失敗、互不影響。
- **基金**不進報價表（一天一個淨值），在「全部」「持股」範圍的下方另列一張卡：最新淨值、淨值日（逾 10 天標黃）、持有報酬，點進 `/funds`。美股報價走 yfinance，狀態欄照舊標「延遲」。

## 四維度摘要（只限台股）

表格的「結構」欄和展開列的「四維度摘要」來自 `GET /api/v1/stocks/dossier-summary?codes=…`，實作在 `src/services/tw_stock_watch.py`。資料來源是 `tw_stock_dossier.build(branch=False)`。
- 不查富邦分點、不呼叫 LLM，每檔的資料包快取 10 分鐘；結論卡標籤每次請求都重讀解讀快取，快取期間新產生的解讀通常也會立刻出現；例外是報告頁用比看板資料包更新的資料寫出解讀（例如法人剛入庫），兩邊 `data_stamp` 對不上，要等看板資料包過期（最多 10 分鐘）加下一次刷新才出現。
- 清單改變、按「刷新」、以及每 15 分鐘（分頁在背景時跳過）重抓一次，不跟 30 秒的報價輪詢。
- 代碼不分大小寫：後端把 `codes` 一律轉大寫回傳，前端用 `normalizeStockCode` 對齊，自選清單寫成 `3324.two` 也對得上。
- 非台股或單檔讀取失敗時，回 `summary=null` 加 `error`，整批仍是 200，該欄顯示「—」。

**欄位**：
- **結構**：最新一筆 SMC 事件（BOS／ChoCH，▲ 多、▼ 空）。
- **撐／壓**：最近的支撐、壓力與現價的距離。
  - 後端只回絕對價位（現價 ±30% 內的 OB、FVG、SSL、BSL、OTE）。
  - **距離由前端用即時報價計算**（`utils/dossierLevels.ts`），沒有報價時才退回資料包的收盤價。原因是資料包每天 18:00 才更新，盤中它的價格是上一個收盤。
  - 價位區間完全在現價之下算支撐、之上算壓力；現價落在區間裡時，依多空屬性歸類，距離記為 0；距離量到近端邊。OTE 區的方向跟著最新結構事件：多方叫「OTE 多方進場區」（多頭）、空方叫「OTE 空方進場區」（空頭）；還沒有結構事件時叫「OTE 進場區」、沒有方向，不算支撐也不算壓力。

**展開列的變化提示**：每條都標日期，不寫「今天」，因為資料包是上一個交易日的資料。

| 提示 | 條件 |
|---|---|
| `10-21 BOS 轉空（1,395.0）` | 最新結構事件發生在資料基準日 |
| `10/10 9 月營收 YoY +23.2%` | 最新月營收在基準日前 7 天內公告 |
| `外資 5 日轉買 +587 張（20 日 -3,840）` | 外資 5 日與 20 日累計方向相反 |
| `千張大戶 +0.62pp（10-16）` | 集保千張大戶週變化 ≥ 0.5 個百分點 |
| `部分資料讀取失敗：估值` | 資料包某段讀取出錯（`errors`） |

**其他**：
- 這檔股票當天已經有人開過「四維度分析」（解讀已快取）時，展開列另外顯示四張結論卡的標籤。摘要端點本身不會觸發 LLM。數字核對沒過（帶 `unverified`）、核對規則版本舊（`check_version`）、或寫完之後資料又更新（`data_stamp` 對不上）的解讀都不顯示標籤，看板上沒有警示可附。
- 展開列的「四維度分析」按鈕開啟與首頁相同的報告抽屜，見 `docs/tw-stock-dossier.md`。
- `TW_LEVEL_ALERTS_ENABLED=true` 時，展開列多一顆「建立價位警報」，把畫面上的最近支撐／壓力建成價格警報。預設關閉，設計見 `docs/tw-level-alerts.md`。

## 数据来源与时效

| 市场 | 个股代码格式 | 数据源 | 时效 | 指数即时 |
| --- | --- | --- | --- | --- |
| 台股 | `.TW` / `.TWO`（4~6 位数字） | Shioaji 优先，yfinance 兜底 | Shioaji 真即时；yfinance 约延迟 15-20 分钟 | ✗ 见踩雷 |
| 美股 | 裸代码（1-5 字母，可选 `.B`） | yfinance（`get_realtime_quote` 路由） | 同 Yahoo | **✓ 走 `US_INDEX_MAPPING`** |
| 韩股 | `.KS` / `.KQ`（6 位数字） | 同上 | 同上 | ✗ 见踩雷 |
| 日股 | `.T`（4~5 位数字） | 同上 | 同上 | ✗ 见踩雷 |
| 港股 | `hk00700` → `0700.HK` | 同上 | 同上 | ✗ 见踩雷 |
| A股 | 6 位数字（`.SS`/`.SZ`/`.BJ` 自动补） | efinance／akshare 优先，yfinance 兜底 | 同各自数据源 | — |

**这张表是 2026-08-03 实测出来的，不是从代码结构推的**：`MU`／`AAPL`／`TSM`／`^SOX`／
`005930.KS`／`000660.KS` 六檔的 `price` 与 `change_pct` 都正确（误差 0.00pp）。
**但 `provider_timestamp` 与 `is_stale` 都是 `None`**
⇒ 这条路径给不出「这笔报价有多新」，盘中引用必须自己标时点。
`source` 在实测当时一律回 `fallback`；2026-08-09 起美股／日股／韩股改标 `yfinance`
（yfinance 本来就是它们的指定主来源，标成 `fallback` 会让每份分析都被判成行情降级）。
**台股刻意维持 `fallback`**——那是辨识 Shioaji 金钥没注入的信号，见下方真值表。
盘前要的**隔夜收盘＋近 5 日**仍走 `scripts/overnight.py`（需要序列，单点报价给不了）。

## 台股盘中字段（白天看盘视角，仅 Shioaji 提供）

台股看板/报价在 Shioaji 数据源下额外接出盘中当沖/隔日冲真正天天盯的字段（yfinance 兜底时这些为 `null`，前端忽略）：

| 字段 | 来源 | 看盘意义 | 可靠性 |
| --- | --- | --- | --- |
| `average_price` 均价(VWAP) | snapshot | 站上=偏多 / 跌破=偏空 的多空分界 | 全时段可靠（开盘头一两分钟量未累积前偏噪） |
| `limit_up` / `limit_down` 涨跌停价 | **自算**：昨收 ±10% 按 tick 对齐（`tw_price_limits`）；昨收缺失才退回 contract 静态值 | ±10% 板；看板算「距板% / 触及涨停 / 触及跌停」 | 全时段可靠；contract 静态值会与当日参考价脱节（实测 2330 给 2625/2155，正确是 2570/2110），所以不直接用。**触及板 ≠ 锁死**（锁板需五档佐证，本路径无五档，故只显示「触及」不显示「锁死」） |
| `best_bid`/`best_ask` (+`_volume`) 委买委卖 | snapshot | 一档排队张数 / 即时支撑压力（收盘集合竞价尤甚） | top-of-book 单档，**非五档**；集合竞价/锁板时挂量会失真 |
| `last_tick_type` 内外盘 | snapshot | 最后一笔主买(外盘,1)/主卖(内盘,2)/中性(0) | **仅最后一笔方向，非累计内外盘比**；轮询会逐笔刷掉 |
| `volume_ratio` 量比 | snapshot | 量能异动快筛 | **开盘初段（约 ~10:30 前）累计量小、偏低失真**，前端附提示 |
| `amplitude` 振幅 | 自算 (high-low)/昨收 | 当日波动幅度 | 全时段可靠 |
| `day_trade` 现股当沖资格 | contract | `Yes` 可双向当沖 / `OnlyBuy` 仅可先买 / `No` 不可当沖 | 静态合约字段，每日合约下载刷新（处置/暂停当沖会变） |

**单位（张 vs 股）**：Shioaji snapshot 的 `total_volume`（成交量）与 `buy_volume`/`sell_volume`（委买委卖一档量）原始单位都是**张**（1 张 = 1000 股）。`ShioajiFetcher._snap_to_quote` 在边界把成交量 `volume` 换算成**股**（×1000，`None` 维持 `None`），与 `UnifiedRealtimeQuote.volume` 契约、yfinance 备援及 DB 日线一致；`best_bid_volume`/`best_ask_volume` 维持**张**（API schema 已标「张」），`amount` 为元、不换算。看板「成交量」列因此是股数（比修前放大 1000 倍）。修前 `volume` 直接是张，pipeline 以它覆盖/追加日线后量比≈0.001，所有台股被判缩量。

看板展示：新增「均价」列（站上/跌破均价红绿着色）、价格列下方「距板」角标、名称旁「不可当沖／仅现沖买」示警角标（`Yes` 为常态不显示），展开列新增「盘口明细」区块（委买委卖一档+量、最后一笔内外盘、均价、涨跌停价、量比、振幅）。LLM 分析提示亦据 `day_trade` 约束：非可当沖标的不得给当沖策略。

> 注：`volume_ratio`/`amplitude` 由 Shioaji 直接提供后，`DataFetcherManager` 的字段补全（`_SUPPLEMENT_FIELDS`）不再用 yfinance 的延迟日线值覆盖这两项（仅填 Shioaji 缺的 pe/pb/市值/换手率，且只填 `None` 不覆盖）。

看板按 `source` + `is_stale` 诚实标示：

- **实时**（绿）：`source == "shioaji"` 且 `is_stale == false`
- **延迟**（琥珀）：其余有报价的情况（含 yfinance 台股）
- **不可用**（灰）：该代码取价失败（`quote == null`），不显示 0 价

## 接口

- `GET /api/v1/stocks/quotes?codes=2330.TW,2317.TW`：批次行情，返回 `{ items: [{ stock_code, quote|null, error }] }`。
  - 单个代码失败回 `quote: null, error: "no_data"`，**绝不 500 整批**。
  - 单次最多 50 个代码（超出 400），代码去重保序。
- `GET /api/v1/stocks/dossier-summary?codes=2330.TW,3324.TWO`：台股四維度摘要（批次），返回 `{ items: [{ stock_code, summary|null, error }] }`；非台股 `unsupported_market`、查無資料 `no_data`、讀取失敗 `unavailable`，整批仍 200；上限 50 個，用原始輸入計算。見上方「四維度摘要」。
- `GET /api/v1/stocks/{code}/quote`：单股行情，响应追加 `source` / `as_of` / `is_stale`（与批次一致）。
- `GET /api/v1/stocks/indices?region=tw`：盯盤上方的大盤指數條（加權 `TWII`、櫃買 `TPEX`），失敗回空列表。台股依序：
  1. **Shioaji 指數快照**（合約 `Indexs.TSE["IX0001"]`／`Indexs.OTC["IX0043"]`，不是 `001`／`101`）：盤中即時，收盤後仍是最近場次的正式收盤；兩檔都有，回應多帶 `as_of`。
  2. **本地 `market.market_index` 官方收盤**：只有加權（表內只存 TAIEX），沒有櫃買；`open`／`high`／`low` 為 `null`。
  3. **yfinance**：最後才用。`^TWII` 收盤後常是幽靈 K 棒（當日 OHLC 配前一日收盤、漲跌 0.00%，2026-10-22 實測顯示 46,292.93 而官方是 46,887.77），`^TWOII` 查無資料。
  大盤複盤走同一個入口，表頭加權指數之後仍會被釘成該場次官方收盤（`market_analyzer._pin_tw_indices_to_session`）。

## Shioaji 数据源（Phase 2）

`data_provider/shioaji_fetcher.py`，仅提供 `realtime_quote`，不参与日线/大盘统计路由。

- **金钥**：`SHIOAJI_API_KEY` / `SHIOAJI_SECRET_KEY`，由 Doppler（project `shioaji`, config `dev`）注入，不落地 `.env`。
- **自动降级**：未安装 `shioaji` 套件 / 无金钥 / 登入熔断中 → fetcher 判定不可用，台股自动走 yfinance。
- **session**：模组级持久 session（登入慢且有每日次数上限），double-checked locking 防并发双登入，登入/快照各有硬 timeout，快照不持会话锁。
- **熔断**：专属登入熔断器（连续 2 次失败熔断、冷却 900s）。熔断器仅在真正登入点交互；冷却期内每次轮询零登入，避免 relogin-storm。熔断 key 以「端到端拿到合法报价」为准（登入成功但快照空 → 不计为成功，避免假复原）。

## 走势图（折线）数据源

`GET /api/v1/stocks/{code}/trend?range=day|month|year`，看板内联展开用。

- **台股 day/month 走 Shioaji `kbars`（真资料）**：day=今日分钟线、month=近 30 天分钟线 resample 成日线。
- **year 与非台股 → yfinance 日线**。

## 踩雷与限制

- **個股提示詞的量／額以報價場次對齊官方日線**：`_enhance_context` 優先讀 `provider_timestamp`，缺值時沿用市場階段與交易日 helper（抓取時間不代表成交場次）。同場次取官方值與即時值的 max，盤前與休市日也適用；新場次不與舊 K 取 max。成交量較昨日變化與提示詞成交量共用修正後的值。
- **缺金钥时数据源自我停用，台股静默降级 yfinance**（行情延迟、走势 day 改用 yfinance 5m 也延迟）。`shioaji` 套件已列入 `requirements.txt`，真正的触发点是金钥没注入。可辨识的信号是 `source` 由 `shioaji` 变 `fallback`、且 `limit_up`/`limit_down` 变 `None`；**名称不会变英文**——降级路径的名称先查本 fork 的股票索引，索引里有的台股仍是中文（2026-07-25 live 对照实测），只有索引没收录的代码才会落到 Yahoo 的英文名。
- **台股日线的权威是 `MarketDBFetcher` 的未还原列；yfinance 备援列不是纯未还原**：`YfinanceFetcher._fetch_raw_data` 对台股（`.TW`/`.TWO`）用 `auto_adjust=False`，去掉现金股利调整（否则与 MarketDB 未还原列混存会在 MA／RSI／MACD 边界出现假台阶），但 Yahoo 的 `Close` 仍含分割调整（台股股票股利在 Yahoo 多以 split 呈现），消费端须以 `data_source` 区分，不能把 yfinance 台股列当未还原价；备援路径上除权息日的 `pct_chg` 是未还原报酬。其他市场仍用还原价（`auto_adjust=True`）。
- **台股趨勢指標以前復權計算，顯示價維持未還原**：`pipeline._build_trend_input_frame`（Step 3，餵給 `StockTrendAnalyzer`）在 `_augment_historical_with_realtime` **之後**呼叫 `market_repo.front_adjust_multipliers(stock_id, df 日期)`，只對 `data_source=='MarketDBFetcher'` 的列把 OHLC 乘乘數、volume **除**同一乘數（分割前量只有分割後約 1/3，不調整會讓 `volume_ratio_5d` 把分割後五天全判放量）；`as_of`＝augment 後 df 的最大日期，所以開盤前（不追加今天）今天才生效的除息不會乘到昨天，盤中追加今天後今天的事件才作用在之前所有列，最後一根乘數恆為 1。YfinanceFetcher 列已含 Yahoo 分割調整，不再乘（只計數 WARNING）；前復權失敗 fail-open 退回未還原並 WARNING。報告、prompt 與 `context.today` 顯示的價格仍是未還原（與券商 App 一致）。6669 於 2026-09-02 1:3 分割，未還原 MA60 到 10-16 仍是 4189、還原後 2142。
- **Shioaji `kbars` 单次区间上限 30 天**（超过回 400 `Kbars date range must not exceed 30 days`），故 year 走势走 yfinance、month 取近 30 天。
- **Shioaji `snapshot.ts` / `kbars.ts` 是台北时间的裸值（非 UTC）**：必须按 `+08:00` 还原绝对时刻（见 `data_provider/shioaji_fetcher.py:_ns_to_iso`），否则 `as_of`/走势时间轴差 8 小时、`is_stale` 因 provider 时间「在未来」恒为 0（假新鲜）。
- **只有美股指数走得通实时路径。** `US_INDEX_MAPPING` 只收美股（SPX／DJI／IXIC／NDX／VIX／RUT／
  **SOX**），所以 `KS11`／`N225`／`TWII` 既不是美股指数也不是美股个股 ⇒ **落到 A 股路由**，
  连问腾讯／新浪／efinance 全失败 ⇒ **三个 fetcher 熔断 300 秒，污染後续真正的 A 股请求**（实测）。
  `HSI` 符合 1-5 字母 pattern 被判成美股个股、Yahoo 无此裸代码 ⇒ 回一个 `price=None` 的空 quote；
  `^HSI` 走到 `_convert_stock_code` 的末端 ⇒ 被转成 **`^HSI.SZ`** 当深市 A 股。
  **要国际指数请直接用 yfinance 的 `^` 符号**（`^KS11`／`^N225`／`^TWII`／`^HSI`），不要走
  `get_realtime_quote`。注意 `YfinanceFetcher.get_main_indices(market)` **能列出**各市场主要指数
  代码（us: SPX/IXIC/DJI/VIX、kr: KS11/KQ11、jp: N225、tw: TWII、hk: HSI/HSTECH/HSCEI），
  所以「repo 知道这些指数存在」与「实时路径取不到它们」是两件事，别被前者误导。
  修法是新增一张非美股指数映射，属设计决策，2026-08-03 决定先记录不修。
- **`api.snapshots()` 回的是 `builtins.Snapshot`，没有 `_asdict()`**：用 `dict(s)` 转。写
  `dict(s._asdict())` 会 `AttributeError`，若外面包了 `except` 就变成整批静默回空——2026-08-03
  踩过，表格印出表头後一列资料都没有。安全写法 `dict(s._asdict()) if hasattr(s, "_asdict") else dict(s)`。
  另 `json.dumps` 会因 `tick_type`／`change_type` 是 enum 而炸（`default=str` 挡不住），先把 value 全 `str()`。
- **`limit_up`／`limit_down` 在 contract 上，不在 snapshot 上**：要判涨跌停得先留
  `getattr(api.Contracts.Stocks[code], "limit_up", None)`，再和 snapshot 的 `close` 比。
- **「涨停锁死」的可判条件是 `close == limit_up` 且 `sell_volume == 0`**（一档委卖挂量归零）。
  这是「现在下单买不到」的直接证据，比涨幅百分比有用得多：2026-08-03 华邦电锁 143，
  委买排队 **13,533 张**、委卖 **0 张**。锁板时 `buy_price`／`sell_price` 会同时回 `0.0`，
  别拿它们当报价。本路径无五档，所以只能说「锁死」不能量化排队深度以外的结构。
- **指数与期货也走同一个 `snapshots()`**：加权指数 `api.Contracts.Indexs.TSE["IX0001"]`（不是 `001`，見上方大盤指數條）、
  台指期近月 `api.Contracts.Futures.TXF["TXFR1"]`。盘中要算「现货 vs 期货逆价差」两个一起抓即可。
  盘中即时 breadth 的现成工具见 `scripts/intraday_breadth.py`。
- **日線歷史落後已收盤場次會標 STALE**：台股分析前，`pipeline._get_analysis_context_with_market_fallback`（一般分析與 Agent pack 兩個呼叫點共用）用 `trading_calendar.count_missing_sessions` 算 DB 最後一根日 K 到「最近已收盤場次」之間缺幾個交易日。容忍規則：effective 日就是市場今天（剛收盤、當日爬取尚未跑）容忍 1 場，其餘容忍 0 場；超過就在 context 寫 `daily_history_stale = {last_date, expected, missing_sessions}` 並印 WARNING，`analysis_context_builder` 把 `daily_bars` block 與 `today` item 標 `STALE`（`missing_reason=daily_history_stale`），沿用既有「STALE 不得給高信心」規則。**只降信心、不擋分析**。已知誤標：停牌股（最後一根本來就舊）會長期標 STALE；颱風等臨時休市 XTAI 日曆不知道，休市隔天可能誤標一次。日曆不可用時不標也不拋出。

## Fallback 真值表（台股请求）

表中的「yfinance」指实际供数的来源；API 回应里 `source` 栏位的值是 `fallback`，不是 `yfinance`
（`yfinance` 这个值只给美股／日股／韩股用）。

| 状态 | UI source | staleness |
| --- | --- | --- |
| 未安装 shioaji / 无金钥 | yfinance | 延迟 |
| 有金钥、首次请求 | shioaji | 实时 |
| session 已死 | 本次 yfinance，下次重连回 shioaji | 本次延迟 |
| 重连失败 / 登入日上限（熔断 OPEN） | yfinance（冷却期零登入） | 延迟 |
| Shioaji 部分字段缺失 | shioaji（yfinance 补字段） | 实时 |
| 登入成功但快照空（午休/收盘无 tick） | yfinance | 延迟 |
| 两者皆失败 | 该列「不可用」 | — |
| `ENABLE_REALTIME_QUOTE=false` | 全部不可用 | — |

## 验证

```bash
make serve   # Doppler 注入金钥
curl 'http://127.0.0.1:8000/api/v1/stocks/quotes?codes=2330.TW,2317.TW'
# Phase 2 盘中确认 Shioaji 生效（source 应为 shioaji）：
doppler run -p shioaji -c dev -- uv run python -c \
  "from data_provider.base import DataFetcherManager as M; q=M().get_realtime_quote('2330.TW'); print(q.source, q.provider_timestamp, q.is_stale)"
```
