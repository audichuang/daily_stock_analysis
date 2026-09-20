# 上游同步记录 2026-09-20（v3.32.0 → post-v3.32.0）

## 基线

| | |
| --- | --- |
| 上一次同步基线 | `089d9d26`（`docs/upstream-sync-2026-09-12.md` 收的最後一个 commit） |
| tag `v3.32.0` 实际指向 | `09fa491a`，**比基线早一个 commit**——`git log v3.32.0..upstream/main` 会回 5 笔，多出来的正是 `089d9d26`，上一轮已经合过 |
| 本次上游 HEAD | `f9e7b778`（无新 tag，`git describe` 为 `v3.32.0-5-gf9e7b778`） |
| 吸收 commit 数 | 4（全部） |
| 合并方式 | 直接在 `main`（`e321a00f`）上 `git merge upstream/main --no-ff`，未走临时分支 |
| 冲突档 | **0**（`git merge-tree --write-tree --name-only` 乾跑只回一个 tree OID，与实际合并一致） |

上一轮已经落地 `main` 且与 origin 同步，这轮乾净地叠在上面。

## 吸收的上游改动

| commit | 内容 | 对本 fork 的意义 |
| --- | --- | --- |
| `2ffe4e72` #2333 | 智能导入解 CSV 时 `utf-8` → `utf-8-sig`，吃掉 UTF-8 BOM | 纯修复，台股 CSV 从 Excel 另存时正好会带 BOM，对本 fork 是净收益 |
| `afca4fb7` #2339 | 全仓库 SerpApi 赞助链接换新地址 | 纯文档／注解 |
| `1168e316` #2338 | runtime scheduler 硬超时後扫已落库历史、推部分完成通知，`last_error` 带 `completed/pending` | 唯一有行为的一笔，见下节 |
| `f9e7b778` #2345 | AkShare 大盘涨跌统计的两个降级调用包进可强制终止的子进程超时（30s） | 只作用在 A 股 `get_market_stats`；本 fork `MARKET_REVIEW_REGION=tw,us`，台股走 `TwseFetcher`，这条路平常走不到 |

## 静默降级排查

按 `AGENTS.md` §10 的作法，逐个问上游本轮新增的共用常数／helper
「它的集合涵盖 `tw` 吗？涵盖 `zh-TW` 吗？」——**本轮一个市场集合／语言集合常数都没有新增**：

- `_AKSHARE_MARKET_STATS_CALL_TIMEOUT`：纯秒数，无市场维度；调用点在 `AkshareFetcher._fetch_a_share_market_stats` 内部，
  `get_market_stats` 的 `purpose="market_review:<region>"` 路由没有被动到。
- `src/services/analysis_timeout_partial.py`：整支自足，唯一的外部契约是
  `AnalysisHistory.code / report_type / operation_advice / sentiment_score`（本 fork 的 `src/storage.py:354` 都在）
  与 `NotificationService.send(route_type=, severity=, dedup_key=)`（`src/notification.py:2940` 支援）。
  没有市场白名单，台股代码 `2330.TW` 走的是同一条 `code` 比对。
- `DSA_TIMEOUT_PARTIAL_NOTIFY` 进 `config_registry` 的 `display_order: 13` 在 `system` 类目内不重复
  （既有的 11 / 12 本来就各有一对重复，属上游既有状态，未动）。

## 一个要记下来、本轮不改的行为差异

`build_partial_timeout_report()` 的报告正文（标题「定时分析超时（部分完成）」等）是**写死的简体字串**，
不读 `REPORT_LANGUAGE`。本 fork `REPORT_LANGUAGE=zh-TW`，所以这一份通知会是简体。

暴露面：本 fork `SCHEDULE_ENABLED=false`，Web/API runtime scheduler 不排程，
但 Web 的「立即执行」走 `RuntimeSchedulerService.run_now()` → 同一条 watchdog，
所以**硬超时（默认 2700s）後仍会推一则简体的部分完成通知到 Bark**。

不改的理由：它是上游新功能的既定文案，整支模组没有语言维度，
要做就是给它接 `L(...)` 那一套——那是一个功能决定，不是合并裁决。
要关掉推播设 `DSA_TIMEOUT_PARTIAL_NOTIFY=false` 即可（`last_error` 的 `completed/pending` 摘要仍保留）。

同理，`systemConfigI18n.ts` 没有 `DSA_TIMEOUT_PARTIAL_NOTIFY` 的中文标签——
**上游自己也没加 zh**，设定页对 zh / zh-TW / en 一律回退到英文 title，三个语系一致，不是 fork 侧的漂移。

## 验证

| 项目 | 结果 |
| --- | --- |
| `ci_gate.sh syntax` | 绿 |
| `ci_gate.sh flake8` | 绿（0） |
| `scripts/check_ai_assets.py` | 绿 |
| 针对性测试（上游新增 2 档 + `runtime_scheduler` / `import_parser` / `python_version_compat` / `system_config_service`） | 293 passed / 1 failed（已知 `.env` 假红，见下） |
| **全量离线测试** | 见「全量结果」 |
| Web 构建 | **未跑**：`git diff --name-only e321a00f..HEAD` 在 `apps/` 底下 0 档，上游本轮没碰前端 |
| `npm ci` | 未跑（`package.json` / lock 未变） |

### 已知假红（非本次回归）

`tests/test_system_config_service.py::SystemConfigServiceTestCase::test_get_config_defaults_public_searxng_instances_off`
——`'true' != 'false'`，`AGENTS.md` §10「第三种形状」原样重演：本机 `.env:351` 有
`SEARXNG_PUBLIC_INSTANCES_ENABLED=true`，全量里较早的测试呼叫 `load_dotenv()` 把它写进 `os.environ`。
**单跑该测试绿**（实测 1 passed）。CI 无 `.env`，那里不会红。与 09-05、09-12 两轮是同一支、同一个原因。

## 全量结果

`uv run ./scripts/ci_gate.sh`（不带参数 = all，第四阶段 `pytest -m "not network"`），
2026-09-20 21:47 → 22:43 本机执行：

```
1 failed, 7398 passed, 8 deselected, 50 warnings, 717 subtests passed in 3385.16s (0:56:25)
```

对照 09-12 那轮的 `1 failed / 7378 passed`：**passed +20**，逐档实测
（`pytest --collect-only -q`）正好对上，没有剩余项：

| 档案 | 新增 |
| --- | --- |
| `tests/test_akshare_market_stats_timeout.py`（新档） | 3 |
| `tests/test_analysis_timeout_partial_notify.py`（新档） | 16 |
| `tests/test_import_parser.py`（既有档，上游加一支 BOM 案例） | 1 |
| 合计 | **20** |

subtests 两轮都是 717，没有差额。failed 数不变、且是同一支。

两轮不是严格的 like-for-like：09-12 的 `7378` 是修掉盘别假红後的重跑值。

唯一的红就是上面那支 `.env` 泄漏假红。三步判别全部成立：

| 步骤 | 结果 |
| --- | --- |
| 单跑该测试 | **1 passed** |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED=true` 单跑 | **1 failed**（复现全量里的那一个 `'true' != 'false'`） |
| 非因果：`git diff --name-only e321a00f..HEAD` | 合并**没有碰** `system_config` 或 searxng 任何一档 |

跑的时候 load average 1.75 / 12 核，不是 `AGENTS.md` §10 的牆钟负载形状；
也没有与 vitest 并跑。

## 落地方式

依使用者指示合进本地 `main`。**写这一段时尚未 push，之后已经推上 origin**：
`e321a00f` → `5bbd4aa6`（merge + 两笔记录 commit），再往后是 `ff3ea286`／`5712ed01`
（`health` 财报稽核）与 `726c0a38`／`ca08baf5`（本文件末尾「附：事后验证」那两个修复）。
回滚段已按这个事实改写。
本机 user unit `dsa-board` / `dsa-schedule` 跑在这个工作树上，合并验证通过後重启吃到新码。

代价同前几轮：`ci.yml` 的 `on:` 只有 `pull_request`，push 到 `main` 不触发，
所以这批改动没有在云端 CI 跑过（最明显的差异是 **CI 跑 Python 3.11、本机 3.12**，
由 `tests/test_python_version_compat.py` 确定性挡住，本轮绿）。

## 回滚

```bash
git reset --hard e321a00f          # 本次 merge commit 的第一父，即合并前的 main
git push --force-with-lease origin main
systemctl --user restart dsa-board dsa-schedule
```

**`main` 已经 push，所以回滚一定要动远端**——只做 `reset --hard` 而不推，
下一次 `git pull` 会把 merge 静默拉回来，而本机服务已经重启成旧码，
两边不一致且没有任何东西会喊。
**不要用 merge-base `089d9d26`**——它是上游 commit，与合并前的 fork 之间隔着整条台股增量。

## 附：事后验证（2026-09-20 夜，7 视角 + 对抗验证 + 实跑）

合并落地后另跑了一轮验证，问题是「更新链有没有问题、分析链有没有问题」。
方式：7 个面向的平行审查，每条 finding 再送两个不同镜头的对抗验证（预设要求推翻），
最后一个完整性批判；另外实跑真实 `daily` 更新与一次完整的 `2330.TW` 分析。

### 实跑结果

| 项目 | 结果 |
| --- | --- |
| `market_data.cli daily`（真实执行） | exit 0，快照段全部写入 |
| `market_data.cli health --strict` | exit 0，唯一非零行是 `stale financial quarters: 1 -> 2019Q4` |
| `main.py --stocks 2330.TW --force-run` | exit 0，3 分 16 秒；MarketDBFetcher(P1) 供日线 43 笔 → Shioaji 即时报价（`source=shioaji`）→ LLM 出繁中结论「觀望 / 52 / 震盪」→ 台股+美股大盘复盘各自生成并存档 → 自动回测 4/4 |
| 通知 | 未推（`skip_notification reason=not_configured`），本轮刻意不带 `CUSTOM_WEBHOOK_URLS` |

**判定：更新链 sound；分析链 sound，但抓到两个既有缺陷**（两者都不是本次合并或
`health` 改动引入的，`git diff --name-only e321a00f..c78c4364` 不含相关档案）。

### 缺陷一：台股复盘的表头指数没有场次身分（已修，`726c0a38`）

即时报价拿不到「这根 K 棒属于哪一天」，而复盘要的正是那个。两个反向失真都在磁碟上：

- 非交易日 `yfinance` 的 `hist.iloc[-1]` 回幽灵 K 棒：当晚实测
  `current=47368.04 / +0.40%`，而那份报告复盘的 2026-09-18 官方收盘是
  `47180.75 / +1.93%`——连涨跌幅量级都不对，LLM 照着写「温和上涨」，还自己在报告里
  标出「資料衝突風險：47,368.04 vs 47,180.75」。
- 14:00 排程反过来：即时源已有当日、TWSE 官方统计还停在前一场次。
  `reports/market_review_20260916.md` 标题 09-16、指数 45,848.90（09-16 正确），
  但涨跌家数 207 漲/791 跌是 **09-15** 的（该轮 log：`本地寬度 2026-09-15 vs 2026-09-14`），
  而 09-15 是跌 0.77% 的下跌日——LLM 把这个矛盾写成「收涨却普跌的背离」。

修法：`MarketAnalyzer._pin_tw_indices_to_session` 把表头加权指数换成
`market.market_index` 中**该场次**的官方 close/change/turnover（`change` 带正负号，
已逐 57 个场次对过 `close - lag(close)`）。台股限定、只改表头那一档、查无列时保留
即时值并 warning。

### 缺陷二：掉股票的那一轮，报告读起来是完整的（已修，`ca08baf5`）

`fail_count` 在 `pipeline` 算出来、写进日志，然后**没有任何消费者**；表头的档数是
`len(results)`（成功数）。2026-09-18 的排程请求 14 档，`2308.TW` 因
`deepseek-v4-flash` 连两次回非法 JSON 被丢弃，`reports/report_20260918.md` 写
「共分析 **13** 檔股票」、整份不含 `2308`，Bark 推送成功。频率：7 个排程场次约
97 次个股分析掉 1 次。

修法：从唯一的分派点 `generate_aggregate_report` 往下传 `failed_codes`，
dashboard 与 brief 两种 `REPORT_TYPE` 都在表头加「⚠️ 本輪有 N 檔未產出結果：<代码>」。
只补「说出来」这一半；LLM 那一半的杠杆是 `LITELLM_MODEL`（§10）。

### 顺带确认

- **TWSE 涨跌家数端点又冻结了**：`出表日期` 停在 2026-06-05，实测差 105 天。
  `twse_fetcher.py` 的日期比对正确拒收并退回 `tw_breadth.closing_breadth()` 本地计算
  （当晚 748 漲 / 251 跌 / 78 平）。这道门正在实际发挥作用。
- 上游 `f9e7b778` 的 AkShare 子进程超时在本 fork **走不到**：`MARKET_REVIEW_REGION=tw,us`，
  两条路由表都不会进入那两个呼叫点；spawn 本身实测可用（wrapper 开销 0.54s / 30s 预算）。
- 上游 `1168e316` 的超时部分完成通知，契约与本 fork 的实际接线逐项相符
  （`NotificationService.send` 四个 kwarg、`AnalysisHistory` 每个栏位、
  `system_error` 路由落到 Bark）；唯一差异仍是正文写死简体。
