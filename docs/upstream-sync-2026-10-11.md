# 上游同步记录 2026-10-11（post-v3.32.0 第五轮）

## 基线

| | |
| --- | --- |
| 上一次同步基线 | `ce364e45`（`docs/upstream-sync-2026-10-08.md` 收的最后一个 commit） |
| 本次上游 HEAD | `c3349de4`（无新 tag） |
| 吸收 commit 数 | 1（全部；50 档，+5882／−1725） |
| 合并方式 | 分支 `chore/upstream-sync-2026-10-11`（自 `main` `f4804bf5`）`git merge upstream/main --no-ff` |
| 冲突档 | 3：`src/storage.py`、`data_provider/base.py`、`apps/dsa-web/src/pages/ChatPage.tsx`（`git merge-tree` 干跑与实际合并一致） |
| 新依赖 | 无 |

## 吸收的上游改动

| commit | 内容 | 对本 fork 的意义 |
| --- | --- | --- |
| `c3349de4` #2397 | 问股由服务端保存已确认的讨论对象（`conversation_session_states` 新增 9 栏、`state_version` CAS、会话 generation）；对象辨识从前端移到 `src/agent/chat_object_decision.py`；工具与数据入口改传已验证的 `AnalysisTarget`，报价回来的代码与目标不符就拒收；严格回测按市场身份查询 | 问股目前在本 fork 不可用（只能走 LiteLLM，金钥已失效），所以日常收益很小；但 schema 迁移与 SQLite 专用写法会**直接弄坏 Postgres 应用库的初始化**，见下节 |

## 冲突裁决

| 档案 | 裁决 |
| --- | --- |
| `src/storage.py` | 取上游抽出的 `_insert_conversation_user_turn`，但把 `sqlite_insert` 换回 fork 的 `self.upsert_insert`（方言选择），因此由 `@staticmethod` 改为实例方法（呼叫端本来就用 `self.`） |
| `data_provider/base.py` | `get_realtime_quote` 签名同时保留 fork 的 `skip_supplement` 与上游的 `analysis_target`；日股/韩股分支保留 fork 写法（台股不走 yfinance-only，走下方 Shioaji 优先分支）并接上 `target_kwargs`；台股分支的三处取数（Shioaji、yfinance 补充、yfinance 兜底）也接上 `target_kwargs`，让身份核对对台股同样生效 |
| `ChatPage.tsx` | 上游把 `extractStockCodesFromMessage`／`StockIndexItem` 从页面移除（改由服务端辨识）；保留 fork 的 `getIntlLocale` 与上游的 `useUiLanguage` |

## 合并时补的 fork 增量（Postgres 应用库）

上游只维护 SQLite；本 fork 应用库自 10-03 起在 Postgres `dsa` schema（本机报告与 NAS 共用）。逐项在本机拋弃式 PG17 上重现与验证：

1. **`conversation_session_states` 缺栏 → 初始化失败**：上游的 `_ensure_chat_session_schema` 只在 SQLite 补栏，`create_all` 不会替既有表加栏。正式库这张表只有 4 栏；不补的话 `DatabaseManager` 初始化时的 `select(ConversationSessionState)` 直接 `UndefinedColumn`，**本机每日报告与 NAS Web 都会起不来**。补了 Postgres 分支 `ALTER TABLE … ADD COLUMN IF NOT EXISTS`（9 栏，`state_version INTEGER NOT NULL DEFAULT 0`）。实测：拿掉这段就重现初始化失败；补上之后在旧表上初始化、二次初始化（幂等）、旧会话回填 generation 都正常
2. **严格回测的 `json_valid`／`json_extract`**：Postgres 没有这两个函式。改成 `backtest_repo._snapshot_market`（`@compiles`）：SQLite 编译成与上游相同的 SQL，Postgres 编译成 `CASE WHEN pg_input_is_valid(x,'json') THEN x::json #>> '{market_phase_summary,market}' END`（PG16+，正式库是 17.7）。只在参数是**栏位**时安全——参数若是常数，PG 规划期的常数折叠会先做 cast 而报错；生产路径一律传 `AnalysisHistory.context_snapshot`
3. **对象状态 CAS 在 Postgres 上会漏并发**：SQLite 靠 `BEGIN IMMEDIATE` 串行化，Postgres 预设 READ COMMITTED，「读 `state_version` → 比对 → 写」中间不锁。实测 6 条执行绪拿同一份快照同时提交，无锁时出现两条同时成功（lost update）。写入交易内读状态的 6 处改为 `session.get(…, with_for_update=True)`（SQLite 编译器会忽略），之后连跑 5 次都只有一条成功
4. Web `uiText.ts`：上游新增 5 个问股对象文案只给 zh/en，`zhTW` 是严格 `Record`，`npm run build` 直接 tsc 失败；补齐繁体

### 部署注意

第 1 项会在新代码**第一次**连上正式库时对 `dsa.conversation_session_states` 执行 `ALTER TABLE`（只加可空栏与带预设值的栏，表目前 0 列）。这是加法式变更：仍在跑旧 digest 的 NAS 容器不读这些栏，照常运作；回滚代码也不需回滚 schema。

## 静默降级排查

- 本轮上游没有新增市场集合／语言集合常数；新的工具政策 `supported_asset_types` 按资产类型（stock／index），不按市场
- `_quote_matches_target`：台股报价的 `code` 是带后缀的 `2330.TW`／`6488.TWO`（`normalize_stock_code` 保留后缀），与 `AnalysisTarget.canonical_id` 一致，核对通过；裸 `2330` 会被拒收，但目前没有台股取数器回裸代码
- **问股对象辨识漏 `.TWO` 与带字母代码（本轮修）**：`stock_scope.extract_stock_code_spans` 的正则只认 `\d{1,6}\.TW`，`6488.TWO` 完全抓不到、`00631L.TW` 也抓不到。上游这轮把它变成对象辨识的唯一入口（前端 `chatStockCode.ts` 不再参与），所以补了 `\d{4,6}[A-Z]?\.(?:TWO|TW)`；守门测试在 `tests/test_chat_tw_identity_and_pg_compat.py`（含边界反向检查），mutation 双向已验
- `uiText.ts` 三语键数一致（1054）
- `stock_index_loader`：上游只新增问股用的名称／代码查表快取（`get_chat_stock_lookup`），远端索引更新逻辑没动，`STOCK_INDEX_REMOTE_UPDATE_ENABLED=false` 的行为不变；查表含台股名称（「台積電」→ `2330.TW`、`6488.TWO` → 環球晶）
- `history_loader`：新的 `stock_identity` 参数只在问股严格路径生效；分析主流程不传，台股日线仍走 `MarketDBFetcher` 优先

### 已知缺口（本轮不修）

1. **`stock_scope.extract_stock_codes`（旧的列表版）不认台股**：`2330.TW` 回空、`00631L.TW` 被误判成港股 `HK00631`。合并前的 `main` 就是这样（worktree 对照过），不是本轮引入；它仍被 `resolve_stock_scope` 等旧路径使用
2. **问股的操作词只有简体**：`chat_object_decision._OPERATIONS`、`stock_scope._SWITCH_PATTERN` 只认「换成／切换到／诊断」等简体，繁体「換成／切換到／診斷」不会被当成切股指令（「分析／看看／看」繁简同形不受影响）
3. 上两项都只影响 Web／Bot 问股；问股在本 fork 目前不可用（见 `AGENTS.md` §10），哪天恢复前要先补
4. 上一轮的已知缺口（Web 意图解析不认台股、数据中心台股只列 yfinance、`settingsHelp.ts` 无 zh-TW）状态不变

## 验证

| 项目 | 结果 |
| --- | --- |
| `ci_gate.sh syntax` / `flake8` | 绿 / 绿（0） |
| 受影响测试子集（上游改动的 9 个测试档 + 本机 `test_*agent*`／`*chat*`／`*tw*`／`*realtime*`／`*backtest*`／`*shioaji*` + 新增档） | 1477 passed，2 deselected |
| Web `npm run lint` / `npm run build` | 0 error（1 个上游既有 warning）/ 绿 |
| Web `vitest` | 107 档，1373 passed，2 skipped |
| Postgres 迁移与 CAS（本机拋弃式 PG17，先用合并前 `main` 建旧 schema 与旧会话） | 见上节各项 |
| 全量离线测试 | 本机未跑，交给 PR 的 CI（Python 3.11，无 `.env`） |

## 回滚

`git revert -m 1 <merge commit>`。新加的 9 栏留在 Postgres 不影响旧代码，不需要回滚 schema。
