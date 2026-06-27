# 实时盯盘看板（Realtime Board）

Web `/board` 页面：以表格展示自选队列（watchlist）的实时报价，前端每 30 秒轮询一次并支持手动刷新。

## 数据来源与时效

| 市场 | 数据源 | 时效 |
| --- | --- | --- |
| 台股（`.TW` / `.TWO`） | Shioaji 优先，yfinance 兜底 | Shioaji 真即时；yfinance 约延迟 15-20 分钟 |
| 其他（A股/港股/美股/日股/韩股） | 沿用既有 `get_realtime_quote` 路由 | 同各自既有数据源 |

## 台股盘中字段（白天看盘视角，仅 Shioaji 提供）

台股看板/报价在 Shioaji 数据源下额外接出盘中当沖/隔日冲真正天天盯的字段（yfinance 兜底时这些为 `null`，前端忽略）：

| 字段 | 来源 | 看盘意义 | 可靠性 |
| --- | --- | --- | --- |
| `average_price` 均价(VWAP) | snapshot | 站上=偏多 / 跌破=偏空 的多空分界 | 全时段可靠（开盘头一两分钟量未累积前偏噪） |
| `limit_up` / `limit_down` 涨跌停价 | **contract**（开盘即定） | ±10% 板；看板算「距板% / 触及涨停 / 触及跌停」 | 全时段可靠；**触及板 ≠ 锁死**（锁板需五档佐证，本路径无五档，故只显示「触及」不显示「锁死」） |
| `best_bid`/`best_ask` (+`_volume`) 委买委卖 | snapshot | 一档排队张数 / 即时支撑压力（收盘集合竞价尤甚） | top-of-book 单档，**非五档**；集合竞价/锁板时挂量会失真 |
| `last_tick_type` 内外盘 | snapshot | 最后一笔主买(外盘,1)/主卖(内盘,2)/中性(0) | **仅最后一笔方向，非累计内外盘比**；轮询会逐笔刷掉 |
| `volume_ratio` 量比 | snapshot | 量能异动快筛 | **开盘初段（约 ~10:30 前）累计量小、偏低失真**，前端附提示 |
| `amplitude` 振幅 | 自算 (high-low)/昨收 | 当日波动幅度 | 全时段可靠 |
| `day_trade` 现股当沖资格 | contract | `Yes` 可双向当沖 / `OnlyBuy` 仅可先买 / `No` 不可当沖 | 静态合约字段，每日合约下载刷新（处置/暂停当沖会变） |

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

- **`shioaji` 是 optional 依赖**：未 `uv pip install shioaji` 或无金钥时数据源自我停用，台股**静默降级 yfinance**（行情延迟、走势 day 改用 yfinance 5m 也延迟、股票名变英文）。
- **Shioaji `kbars` 单次区间上限 30 天**（超过回 400 `Kbars date range must not exceed 30 days`），故 year 走势走 yfinance、month 取近 30 天。
- **Shioaji `snapshot.ts` / `kbars.ts` 是台北时间的裸值（非 UTC）**：必须按 `+08:00` 还原绝对时刻（见 `data_provider/shioaji_fetcher.py:_ns_to_iso`），否则 `as_of`/走势时间轴差 8 小时、`is_stale` 因 provider 时间「在未来」恒为 0（假新鲜）。

## Fallback 真值表（台股请求）

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
