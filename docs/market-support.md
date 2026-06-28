# 市场支持与边界

## 日本/韩国/台湾个股 suffix-only MVP（Issue #1718，Refs #1718）

当前阶段支持日本、韩国、台湾股票的 Yahoo Finance 后缀代码，进入既有个股分析、历史保存和基础报告展示链路。Web 自动补全内置一批常用日股/韩股种子索引；台股为全量索引（约 2100 档上市櫃个股与 ETF，来源为台湾证交所/柜买中心官方公开清单），支持按 suffix 代码、中文名称或别名搜索。未收录的标的仍可手动输入完整 suffix 代码（如 `2330.TW`）直接分析。

台股索引维护流程（需联网）：

```bash
python3 scripts/fetch_tw_stock_list.py   # 抓官方清单 -> scripts/stock_index_seeds/stock_list_tw.csv
python3 scripts/merge_tw_into_index.py   # 合并进 public/static/data-cache 三处 stocks.index.json
```

> 因 `STOCK_INDEX_REMOTE_UPDATE_ENABLED` 默认从上游拉取（不含台股）会覆盖本地缓存，启用台股全量索引的部署需将其设为 `false`。

支持格式：

- 日本：`7203.T`、`6758.T`
- 韩国 KOSPI：`005930.KS`
- 韩国 KOSDAQ：`035720.KQ`
- 台湾上市：`2330.TW`
- 台湾上柜：`6488.TWO`
- 台湾 ETF（5~6 位代码）：`00878.TW`、`006208.TW`

约束与边界：

- 手动输入裸代码时会先检索本地/远程股票池；若 `005930`、`000660` 等裸码命中 `005930.KS`、`000660.KS` 等日韩条目，则按命中的市场提交分析；若股票池未命中，仍按既有 6 位数字代码规则默认落到 A 股语义。台股四位裸码如 `2330` 暂不自动推断为台股，需输入 `2330.TW` 或 `6488.TWO`。
- 日股/韩股/台股日线和基础实时/近实时行情只走 `YfinanceFetcher`，不尝试 AkShare、Tushare、Efinance、Pytdx、Baostock 等 A 股专属数据源。
- 基本面复用既有 offshore yfinance 轻量路径；A 股专属资金流、龙虎榜、板块等能力按 `not_supported` 降级。
- 报告 Prompt 已增加日股/韩股/台股市场语义，避免套用 A 股涨跌停、北向资金、龙虎榜、融资融券等概念。
- 交易日历注册 `jp: XTKS / Asia/Tokyo`、`kr: XKRX / Asia/Seoul` 与 `tw: XTAI / Asia/Taipei`。若本地 `exchange-calendars` 版本缺少对应日历，既有 fail-open/fail-closed 语义保持不变。

不承诺项：

- 不承诺实时行情；Yahoo Finance 数据可能延迟或字段缺失。
- 不承诺完整基本面、行业/板块、市场宽度、涨跌家数或日/韩/台大盘复盘。
- 不承诺完整日/韩/台全市场股票列表；Web 自动补全当前仅覆盖仓内种子索引中的常用日韩标的，未命中时仍可手动输入 suffix 代码。
- 不补齐 Portfolio 的 JPY/KRW/TWD 汇率、成本、市值完整口径；相关字段仅放开市场类型以避免前后端校验拒绝。

回滚方式：移除 `jp/kr/tw` 市场识别、交易日历注册、YFinance 路由扩展、Web/API 类型放行、`scripts/stock_index_seeds/` 日韩种子索引，并删除本文档中的能力声明。

## 台湾个股 suffix-only MVP（Issue #1772，Refs #1772）

当前阶段支持手动输入台湾股票的 Yahoo Finance 后缀代码，进入既有个股分析、历史保存和基础报告展示链路。TWSE 上市股票使用 `.TW` 后缀，TPEx 上柜（柜买）股票使用 `.TWO` 后缀，二者折叠为同一 `tw` 市场标签。**本次覆盖市场识别（detection）、数据路由层、DecisionSignal/Portfolio/Intelligence 服务层与 API 市场枚举，以及 DecisionSignal/Portfolio 前端市场类型与筛选**；台股股票索引/种子、Web 自动补全与告警（大盘红绿灯）市场放行仍作为后续 PR。对齐 #1718 日韩 MVP 模式。

支持格式：

- 上市（TWSE）：`2330.TW`、`0050.TW`
- 上柜（TPEx / 柜买）：`6488.TWO`、`5483.TWO`
- 代码 base 为 4-6 位数字（普通股 4 位，ETF/其他至 6 位，如 `00878.TW`、`006208.TW`），较日股 `.T` 的 4-5 位更宽。

约束与边界：

- **严格 suffix-only**：裸 `2330`、`00878` 等不带后缀的代码不会进入台股语义（`detect_market` / `get_market_for_stock` 仅在显式 `.TW`/`.TWO` 后缀时返回 `tw`）。本次**不引入任何台股股票索引/种子解析**，故裸码不可能经本地/远程股票池被改写为台股 suffix；该索引解析（与 jp/kr 同款的裸码命中行为）属后续 PR。
- 台股日线和基础实时/近实时行情只走 `YfinanceFetcher`，不尝试 AkShare、Tushare、Efinance、Pytdx、Baostock 等 A 股专属数据源。
- 基本面复用既有 offshore yfinance 轻量路径；A 股专属资金流、龙虎榜、板块等能力按 `not_supported` 降级。
- 台股 valuation（PE/PB/殖利率）由 `TwseFundamentalAdapter` 用 TWSE BWIBBU_ALL（上市）+ TPEx peratio_analysis（上柜）免金钥全市场快照补全（yfinance 对台股不返回 PE/PB），在 `get_fundamental_context` 的 valuation 阶段叠加，source_chain 标记 `twse_fundamental`；全市场快照 4h TTL 缓存、fail-open，ETF 与查无代码回空。
- 台股 growth 一律附月营收 `monthly_revenue`/`monthly_revenue_yoy`/`revenue_month`（TWSE t187ap05_L 上市 + TPEx mopsfin_t187ap05_O 上柜，单位千元已转元），并在 yfinance 缺 `revenue_yoy` 时用月营收 YoY 兜底。完整季报三表（资产负债/季净利明细）仍未覆盖（需 MOPS）。
- 报告 Prompt 已增加台股市场语义（新台币、三大法人、TWSE/TPEx ±10% 涨跌停），避免套用 A 股北向资金、龙虎榜等概念。
- 交易日历注册 `tw: XTAI / Asia/Taipei`。TWSE 为 09:00–13:30 连续交易、无午休；收盘集合竞价暂不建模，与 jp/kr 一致。若本地 `exchange-calendars` 版本缺少对应日历，既有 fail-open/fail-closed 语义保持不变。
- 主要指数提供加权指数 `^TWII` 与柜买指数 `^TWOII`。

不承诺项：

- 不承诺实时行情；Yahoo Finance 数据可能延迟或字段缺失。
- 不承诺完整基本面、行业/板块、市场宽度、涨跌家数或台股大盘复盘。
- 台股股票索引/种子、Web 自动补全与告警（大盘红绿灯）市场放行仍作为后续 PR；告警 MarketRegion 与后端 market_light 仍为 cn/hk/us，未含 tw。
- 不补齐 Portfolio 的 TWD 汇率、成本、市值完整口径（属上述后续 PR 范围）。

回滚方式：移除 `tw` 市场识别、交易日历注册、YFinance 路由扩展与服务层/API 市场枚举及前端市场类型放行，并删除本文档中的能力声明。
