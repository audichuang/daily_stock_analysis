# 实时盯盘看板（Realtime Board）

Web `/board` 页面：以表格展示自选队列（watchlist）的实时报价，前端每 30 秒轮询一次并支持手动刷新。

## 数据来源与时效

| 市场 | 数据源 | 时效 |
| --- | --- | --- |
| 台股（`.TW` / `.TWO`） | Shioaji 优先，yfinance 兜底 | Shioaji 真即时；yfinance 约延迟 15-20 分钟 |
| 其他（A股/港股/美股/日股/韩股） | 沿用既有 `get_realtime_quote` 路由 | 同各自既有数据源 |

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
