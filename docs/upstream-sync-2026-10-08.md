# 上游同步记录 2026-10-08（post-v3.32.0 第四轮）

## 基线

| | |
| --- | --- |
| 上一次同步基线 | `be148f39`（`docs/upstream-sync-2026-10-03.md` 收的最后一个 commit） |
| 本次上游 HEAD | `ce364e45`（无新 tag） |
| 吸收 commit 数 | 22（全部） |
| 合并方式 | 分支 `chore/upstream-sync-2026-10-08`（自 `main` `621730c6`）`git merge upstream/main --no-ff` |
| 冲突档 | 4：`src/config.py`、`apps/dsa-web/src/App.tsx`、`apps/dsa-web/src/components/layout/SidebarNav.tsx`、`tests/test_runtime_scheduler_service.py`（`git merge-tree` 干跑与实际合并一致） |
| 新依赖 | `fxmacrodata-public-client`（GitHub release wheel，带 sha256；FXMacroData 只读工具用） |

## 吸收的上游改动

| commit | 内容 | 对本 fork 的意义 |
| --- | --- | --- |
| `ce364e45` #2376 | 规则化 ETF 双动量轮动 `--etf-rotation` | 只接受 A 股 ETF 代码；台股代码逐个拒绝并写进报告警告（非静默）。报告文案写死简体 |
| `ebab2ba9` #2304 | 数据能力中心 `/data` 页 | 新页面，台股只列出 yfinance（见「已知缺口」） |
| `280cdb66` #2387 / `40fbc67d` #2388 | 妙想（Miaoxiang）数据源 | 只服务 A 股；fork 路由表维持 `MiaoxiangFetcher: set()` |
| `61463531` #2385 | 确定性 Web 意图解析 | 目前无生产呼叫端；不识别台股代码（见「已知缺口」） |
| `139672ed` #2293 / `b210d2c6` #2297 | 自选股下一步总览、持仓风险与暴露看板 | 补 zh-TW 文案 |
| `d34e5ee9` #2379 | 共享每日排程去重（`scheduled_analysis_claim`） | 正向；workload hash 原样带 `tw,us` 与 `zh-TW` |
| `0050f83e` #2380 | AkShare 超时后台请求不再重复打 | 正向 |
| `18154989` #2336 / `1a0948a3` #2367 | FXMacroData 工具、Requesty provider | 与台股无关 |
| 选股系列 #2305 #2382 #2384 #2389 #2390 #2392 | 选股证据来源、快取新鲜度、状态失败区分 | 选股快照端点仍只收 `cn`/`us`，台股显式 422 |
| 其余 #2372 #2374 #2378 #2381 #2386 | 基本面等待计时、告警页、证据时间戳、设置页未保存草稿 | 正向 |

## 冲突裁决

| 档案 | 裁决 |
| --- | --- |
| `src/config.py` | 取上游 ETF 轮动配置区块（fork 侧为空，冲突只因相邻行），去掉一行仅含空白的行 |
| `App.tsx` | 上游改用 `createBrowserRouter` data router（`routeChildren` 阵列）；取上游结构，补回 fork 的 `RealtimeBoardPage` lazy import 与 `/board` 路由 |
| `SidebarNav.tsx` | import 取上游（拿掉 screening 状态轮询、加 `Database`／`useLocation`）＋ fork 的 `LineChart`；标题列保留 fork 的靠左 rail 版面并加上游 `shrink-0` |
| `test_runtime_scheduler_service.py` | 保留 fork 的 60 秒预算：上游把恢复阶段的超时调成 5 秒／deadline 10 秒，本 fork spawn 往返实测 3.30 秒，太紧会在负载下假红 |

### 合并时补的 fork 增量

- `apps/dsa-web/src/i18n/uiText.ts`：上游新增 58 个键只给 zh/en，`zhTW` 是严格 `Record`，`npm run build` 直接 tsc 失败；补齐繁体（资料中心、自选股下一步、设置页未保存草稿、登出提醒）
- `apps/dsa-web/src/pages/PortfolioPage.tsx`：新的 `PORTFOLIO_RISK_DASHBOARD_TEXT` 只有 zh/en，以 `language` 直接索引会 tsc 失败；补 `'zh-TW'` 区块

## 静默降级排查

逐个问上游本轮新增的市场集合／语言集合／代码正则「涵盖 `tw` 吗？涵盖 `zh-TW` 吗？」：

- `trading_calendar.get_trading_dates`／`get_next_trading_date` 走 `MARKET_EXCHANGE`，已含 `"tw": "XTAI"`
- `data_provider/base.py` 新的 `_is_non_cn_request` 建在 fork 的 `_market_tag` 上，台股正确视为非 A 股（资金流、妙想补充都跳过）
- `scheduled_analysis_claim`、`runtime_scheduler`、告警、研究产物：没有新增市场／语言集合
- `portfolio_service` 汇总换汇走 yfinance `{from}{to}=X`，TWD 可用
- `uiText.ts` 三语键数一致（1049）

### 已知缺口（本轮不修）

1. **Web 意图解析不认台股代码**：`src/agent/web_intent_tokenizer.py` 的代码正则会把 `2330.TW` 拆成裸数字 `2330`、`00631L.TW` 拆成 `00631`＋`L`；`web_intent_types.py` 的 `Market` 枚举只有 a/hk/us，LLM 回 `"tw"` 时 `MARKET_NORMALIZE` 静默转成 `None`。目前只有测试 import 这套模组；**哪天接上 Web 问股入口前必须先补**，可复用 `name_to_code_resolver._infer_code_market`
2. **数据中心台股只列 yfinance**：`src/services/data_capability_service.py` 不知道 fork 的 MarketDB／Shioaji／TWSE fetcher，页面上台股覆盖看起来比实际薄（只影响诊断显示）
3. 设置说明 `settingsHelp.ts` 只有 zh-CN／en，新增的 `MX_*` 说明在 zh-TW 显示简体（既有缺口）；告警页新横幅写死简体

## 验证

| 项目 | 结果 |
| --- | --- |
| `ci_gate.sh syntax` / `flake8` | 绿 / 绿（0） |
| Web `npm run lint` / `npm run build` | 0 error（1 个上游既有 warning）/ 绿 |
| Web `vitest` | 107 档，1361 passed，2 skipped |
| 全量离线测试 `ci_gate.sh`（本机 Python 3.12） | 8662 passed，8 deselected，810 subtests，4 分 19 秒；前后比对正式 `dsa` schema 的 `pg_stat_user_tables` 写入计数，**完全不变** |

## 合并过程中发现的事故：测试写进正式应用库

第一次跑全量时，`tests/test_alert_worker.py` 卡在连新浪（AkShare）而被 timeout 中止。根因不在上游：本机 `.env` 的 `STORAGE_DATABASE_URL`（10-03 起指向 NAS 共用的正式 Postgres `dsa` schema）被带进 pytest 行程，而测试只把 `DATABASE_PATH` 指到暂存 SQLite——`get_db_url()` 优先用前者，于是**整批测试 fixture 写进正式库**，再读到自己写进去的 `market_light_status` 告警规则，进而真的连外。

- 写入：`alert_rules` 37、`alert_triggers` 10、`alert_cooldowns` 3、`alert_notifications` 1、`portfolio_accounts` 5、`portfolio_daily_snapshots` 5、`decision_signals` 24（id 610–633）、`decision_signal_outcomes` 24、`decision_signal_feedback` 1、`llm_usage` 81（id 5651–5731）
- 改动真实资料：`decision_signals#3`（588200）被从 `expired` 改回 `active`；另 30 笔真实信号被 `expire_due_signals` 标成 `expired`（本来就已到期，不处理）；情报模组真的跑了一次 RSS 抓取（新增 2 笔、依保留政策淘汰 5 笔 9/29 旧项，视同正常抓取，保留）
- `market` schema 没有测试写入（`DATABASE_URL` 是另一条 URL；`market_data/tests` 本来就用 rollback 保护）
- 清理：经同意，在单一 transaction 内删除上列测试资料，并以冻结的 `data/stock_analysis.db` 原值还原 `decision_signals#3`；删除前的资料已汇出成 JSON 备份（本机暂存，未入库）
- 修复：`tests/conftest.py` 在载入时把 `STORAGE_DATABASE_URL` 钉成空字串，并让 `sqlalchemy.create_engine` 拒绝 `.env` 里那条正式库 URL（挡 `patch.dict(clear=True)` 后重载 `.env` 的路径）；守门测试在 `tests/test_storage_database_url.py`，两层各自做过 mutation（拿掉即红）
- 注意：10-03 合并那轮的全量是交给 CI 跑的（CI 没有 `.env`），所以这个问题从 10-03 到今天都没有暴露

## 回滚

`git revert -m 1 <merge commit>`；新依赖 `fxmacrodata-public-client` 不移除也不影响运行。
