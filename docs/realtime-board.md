# 实时盯盘看板（Realtime Board）

Web `/board` 页面：以表格展示自选队列（watchlist）的实时报价，前端每 30 秒轮询一次并支持手动刷新。

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
- `GET /api/v1/stocks/{code}/quote`：单股行情，响应追加 `source` / `as_of` / `is_stale`（与批次一致）。

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

- **缺金钥时数据源自我停用，台股静默降级 yfinance**（行情延迟、走势 day 改用 yfinance 5m 也延迟）。`shioaji` 套件已列入 `requirements.txt`，真正的触发点是金钥没注入。可辨识的信号是 `source` 由 `shioaji` 变 `fallback`、且 `limit_up`/`limit_down` 变 `None`；**名称不会变英文**——降级路径的名称先查本 fork 的股票索引，索引里有的台股仍是中文（2026-07-25 live 对照实测），只有索引没收录的代码才会落到 Yahoo 的英文名。
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
- **指数与期货也走同一个 `snapshots()`**：加权指数 `api.Contracts.Indexs.TSE["001"]`、
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
