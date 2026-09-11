# 上游同步记录 2026-09-12（v3.31.0 → v3.32.0）

## 基线

| | |
| --- | --- |
| 上一次同步基线 | `e866cfa4`（`docs/upstream-sync-2026-09-05.md`） |
| 本次上游 HEAD | `089d9d26`（tag `v3.32.0`） |
| 吸收 commit 数 | 3（全部） |
| 合并方式 | 分支 `merge/upstream-v3.32`，从 `main`（`cd6f6b6b`）开出，全量 `git merge upstream/main --no-ff` |
| merge commit | `8ec1bea7`，第一父 `cd6f6b6b` |
| 冲突档 | 1（`git merge-tree` 乾跑与实际一致） |
| origin 状态 | `origin/main` 与本地 `main` 完全同步（0/0），本轮云端更新只有 upstream |

与前几轮不同，**上一轮已经落地 `main` 了**（`cd6f6b6b` 是 PR #19 的 merge），
所以这轮是乾净地叠在 `main` 上，PR 只会带这一轮。

## 吸收的上游改动

| commit | 内容 | 对本 fork 的意义 |
| --- | --- | --- |
| `303f4e1c` #2332 | GitHub Actions `STOCK_LIST` 指数入口 + 入口分类重构；指数注册表 31 → 33 | 唯一有行为的一笔，见「入口分类的契约变更」 |
| `09fa491a` | 备 v3.32.0 发版（CHANGELOG 收编） | 纯文档 |
| `089d9d26` | 冷启动超时测试的同步竞态修正 | 纯测试，修的是 `test_name_to_code_resolver.py` 的 flaky |

新增的两档指数是 `sz399365`（国证粮食）与 `csi930606`（中证钢铁），两者都是 A 股指数，
与台股路径无关。

## 冲突裁决（1 档）

### `apps/dsa-web/public/stocks.index.json`

上游往这份档案追加 2 行指数；本 fork 把整份档案重写过
（台股 2124 档种子 + 美股 NASDAQ Trader 增量，相对 merge-base 是 +32898 / −23353 行）。
Git 只能报 content conflict。

**裁决：取 fork 版本，再跑一次产生器重推指数区块。**

```bash
git checkout --ours -- apps/dsa-web/public/stocks.index.json
uv run python scripts/generate_index_from_csv.py --index-only
```

`--index-only` 走 `run_index_only()`：保留全部非指数列的原顺序，剥掉旧指数列，
从**已合并的** `scripts/stock_index_seeds/index_registry.csv`（上游那 2 行在这里是
乾净合并的，无冲突）重新产生指数列并按 canonical 排序。纯本地，不连外。

验收：`git diff --numstat` = **2 insertions / 0 deletions**，两行与
`git show 089d9d26:apps/dsa-web/public/stocks.index.json` 的对应行逐字元相同，
插在同样的排序位置（`csi930606` 在 `csi930955` 前、`sz399365` 在 `sz399967` 前）。
指数列 31 → 33，总列数 41254 → 41256，fork 的台股 / 美股列一列未动。

**为什么不手动插 2 行**：手插会绕过 `validate_index_registry()` 的
identity-collision 检查（指数 canonical 撞到既有个股 / ETF key 时要拒绝），
而本 fork 的美股列有 18083 笔 `asset_type="unknown"`，正是那个检查会扫到的范围。
产生器跑过一遍等于顺便验了这一格。

其余 6 档双方都改过的档（`README.md`、`docs/CHANGELOG.md`、`docs/README_EN.md`、
`docs/full-guide.md`、`docs/full-guide_EN.md`、`main.py`）git 自动合并，
逐档比对 `git diff e866cfa4..089d9d26` 与 `git diff cd6f6b6b..8ec1bea7`，
上游新增的内容全部落地，fork 侧没有被删。

唯一没落地的是一个**删除**：上游发版时把 `[Unreleased]` 的
`<!-- 新条目格式… -->` / `<!-- 每条独立一行追加… -->` 标记对搬回段顶并删掉旧的，
auto-merge 保住了 fork 在 `[Unreleased]` 的那一份、却也留下被搬进
`## [3.32.0]` 的那一份，於是全档从 2 份变 3 份。HTML 注解无程式消费者
（`build_release_notes.py` 只读 `### 发布亮点` 且只取 `- ` 开头的行），
但它是本次合并造成的，已在後续 commit 删掉 `## [3.32.0]` 内那一对。
`[Unreleased]` 的 fork 条目被上游发版切进已发布段那一格**不动**——
前三轮合并都是同样的处理，是既定形态。

## 入口分类的契约变更（本轮唯一的行为发现）

上游 `303f4e1c` 新增 `main.py::_classify_stock_list_tokens`，把
「单一 token 不支援 → 跳过它，其余照跑」改成
**「批次里有任何一个 token 不支援 → 整轮不跑，`return 1`」**，
作用在 `--stocks` 与新增的 GitHub Actions `STOCK_LIST` 两个入口。

这不是静默降级，是上游刻意的契约：docstring 明写
「reject the whole run up-front … provider calls are never reached for any token
in the batch」，而且合并一起带进来的
`tests/test_main_schedule_mode.py::test_standalone_run_rejects_unsupported_stocks_token`
就是在断言「`600519,930956.CSI` → exit 1 且 `run_full_analysis` 不被呼叫」——
一个健康 token 陪着一个坏 token，整轮被拒。

`src/core/pipeline.py:3444` 那个「跳过 unsupported 目标 %r，不触发网络请求」的
per-token 过滤器还在，只是 CLI 入口再也走不到它了。

### 对本 fork 的实际影响

触发条件比「未登记 `.CSI`」宽得多，实测（合并后的树）：

| 输入 | `parse_analysis_target` | 后果 |
| --- | --- | --- |
| `2330.TW` / `2330.TWO` / `0050.TW` / `006208.TW` | stock | 正常 |
| `00631L.TW` / `00679B.TWO` / `2887A.TW` | stock | 正常 |
| `233.TW`（掉一位数） | **unsupported** | 整批拒绝 |
| `00631Ｌ.TW`（全形 Ｌ） | **unsupported** | 整批拒绝 |
| `999999.CSI` | **unsupported** | 整批拒绝 |

**合法的台股形态一个都没有被误判**——这一格是乾净的。会中的是打错字：
`make analyze STOCKS="2330.TW,2317.TW,233.TW"` 现在 0 份报告、exit 1，
合并前是 2 份报告 + 一行 warning。而且本 fork 的 `.env` 有
`MARKET_REVIEW_ENABLED=true` / `MARKET_REVIEW_REGION=tw,us`，大盘复盘与 Bark
推播挂在同一个 process 的退出码上，所以一个错字会连带把复盘与推播一起取消。

现况没有暴露面：`.env` 现有的 STOCK_LIST 每一个 token 都归类为 stock，
而 GitHub Actions 那条路本 fork 从未设过 `STOCK_LIST`
（`00-daily-analysis.yml:438` fallback 到 `600519`，也是 stock）。

**本轮未改动上游这个契约**，理由是它有明确意图与守门测试，改它是一个设计决定
而不是合并裁决。要改的话最小修法是让 `_classify_stock_list_tokens` 对齐
`pipeline.py:3444` 的 per-token skip（只有全部 token 都不支援才中止），
或退一步只豁免 Actions 分支。

## 稽核方式

合并 commit 落地后跑 6 视角平行稽核（入口分类 / 静默降级 / 指数注册表 / 合并完整性 /
测试守门 / 配置与文档），每条 finding 再送独立的对抗式验证（预设要求推翻）。
9 条 finding 进验证，**2 条存活**（就是上面那一条，被两个视角各自独立找到），
7 条被推翻，推翻理由各自都能指到行：

| 被推翻的 finding | 为什么不成立 |
| --- | --- |
| `static/stocks.index.json` 停留在 31 列 | 该档 `.gitignore:94` 不在版控，且 `npm run build` 会从 `public/` 重刷（本轮验证时已刷到 33 列）；`api/app.py` 的候选顺序前后逐字元相同 |
| 索引档有四套 precedence 规则、只有一套有守门 | 描述属实但 `git diff cd6f6b6b..8ec1bea7 -- src/data/stock_index_loader.py` 为空，纯既有 |
| CHANGELOG 的 append-marker 被上游发版切到 `[3.32.0]` 里 | `build_release_notes.py` 只读 `### 发布亮点` 且只取 `- ` 开头的行，HTML 注解与 `### 变更明细` 都读不到 |
| 上游发版把 fork 的 `[Unreleased]` 条目扫进已发布段 | 同上，无程式消费者 |
| 新的整批拒绝闸门没有台股测试覆盖 | 上游自带的 `test_main_schedule_mode.py:541` 正是在断言混合批次整轮被拒 |
| 缺 upstream-sync 记录与 CHANGELOG 条目 | fork 的惯例就是在 merge commit 的**后续 commit** 补（`c9e4db98` → `e18b740a` 等三轮都一样）；本文件即是 |
| zh-TW README 的 STOCK_LIST 说明与简中/英文漂移 | 是省略不是矛盾，且无程式消费者 |

## 验证

| 项目 | 结果 |
| --- | --- |
| `ci_gate.sh syntax` | 绿 |
| `ci_gate.sh flake8` | 绿（0） |
| `scripts/check_ai_assets.py` | 绿 |
| 针对性测试（上游改过的 4 档 + 索引相关 4 档 + 版本相容） | 465 passed |
| **全量离线测试**（`pytest -m "not network"`） | **2 failed / 7377 passed / 8 deselected / 717 subtests，58 分 40 秒** |
| `npm run lint` | 0 error（2 个既有 `react-hooks/exhaustive-deps` warning） |
| `npm run build`（`tsc -b` + vite） | 绿 |
| **vitest 全跑** | 1225 passed / 2 skipped / 103 档全绿 |
| 台股身分逐码实测 | 18 种形态，见上表 |

`npm ci` 本轮**未执行**：合并没有动 `apps/dsa-web/package.json` 或 lock
（`git diff --name-only cd6f6b6b..8ec1bea7` 在 `apps/` 底下只有那份 index JSON），
重装依赖属于需要确认的动作，没必要为验证这一笔而做。

vitest 这次是单独跑的（pytest 全量尚未开始），103 档全绿——对照
2026-09-05 那轮与 pytest 并跑时的 2 failed，再次确认那是 `AGENTS.md` §10
记的负载形状而不是回归。

### 那 2 个 pytest 红都不是本次回归

#### 1. `.env` 泄漏假红（`AGENTS.md` §10 第三种形状，原样重演）

`tests/test_system_config_service.py::SystemConfigServiceTestCase::test_get_config_defaults_public_searxng_instances_off`
——`'true' != 'false'`。本机 `.env:351` 有 `SEARXNG_PUBLIC_INSTANCES_ENABLED=true`，
全量里任何较早的测试呼叫 `load_dotenv()` 就把它写进 `os.environ`，
之后 `SystemConfigService.get_config` 读到它当「预设」。单跑该测试**绿**。
CI 没有 `.env`，那里不会红。与 2026-09-05 那轮是同一支测试、同一个原因。

#### 2. 牆钟／盘别相依的假红（**第四种形状，本轮新发现，已修**）

`tests/test_us_market_path.py::TestRecapIsDatedByTheMarketNotTheServerClock::test_us_recap_uses_the_new_york_session_not_the_taipei_date`
——`assert spy.call_count == 1` 拿到 0。

**这一支单跑也红**，所以不是顺序敏感也不是负载敏感，看起来就像回归。
退回合并前的树实测排除：

```bash
git worktree add --detach <tmp> cd6f6b6b
cd <tmp> && uv run pytest tests/test_us_market_path.py::...::test_us_recap_uses_the_new_york_session_not_the_taipei_date
# → 一样红。合并没有碰 src/market_analyzer.py 或 tests/test_us_market_path.py
```

机制：`MarketAnalyzer._resolve_overview_date`（`src/market_analyzer.py:736`）在
`INTRADAY` / `LUNCH_BREAK` / `CLOSING_AUCTION` / `POSTMARKET` 四个 phase
**短路回 `now.date()`，根本不问 `get_effective_trading_date`**。
而这支测试只 mock 了 `get_effective_trading_date`，没有釘住 phase，
等於拿真牆钟当输入。本次跑全量时纽约是 `2026-09-11 18:22 -04:00` = `POSTMARKET`，
spy 於是一次都没被呼叫。

> 台北清晨（≈04:00~08:00，即纽约盘後）跑全量必红，其余时段必绿。
> 这正是本 fork 跑 `make morning` 的时段。

**修法**（同档 `TestCodexReviewFindings` 那两支本来就釘了 phase，只有这支漏了）：
把 `infer_market_phase` 釘成 `MarketPhase.PREMARKET`，其余不动。

Mutation 双向验过：

| 变异 | 结果 |
| --- | --- |
| 把 `_resolve_overview_date` 改回「一律用牆钟日期」（撤销修法） | **3 红**，含本支 → 它仍是真守门，不是靠别的理由绿 |
| 改成「一律问 `get_effective_trading_date`」（过度修正） | **2 红**，但接住的是同档两支 sibling，**本支自己仍绿** |
| 修完在同一个牆钟（纽约盘後）重跑整档 | **83 passed** |

`src/market_analyzer.py` 变异後逐字元还原（`git diff --stat` 为空），
**生产程式码本轮一行未改**。

反向覆盖要讲准一点：本支只守住「撤销方向」，**过度修正那一格是靠
`test_recap_date_matches_the_session_the_prices_belong_to` 与
`test_overview_date_reads_the_clock_once` 两支 sibling 接住的，本支不独立覆盖**。三支合在一起才是双向守门；
单独看这一支只擋了一半。会这样是因为本支釘的就是 `PREMARKET` 分支——
过度修正不改这个分支的结果，它没有理由红。

## 回滚

`git reset --hard cd6f6b6b`（本次 merge commit 的第一父，即合并前的 `main`）。
**不要用 merge-base `e866cfa4`**——它是一个上游 commit，与合并前的 fork 之间隔着
整条台股增量，照着跑会跑得乾乾净净、只有事后才看得出来。

或者直接不合并这个分支：本轮全部改动都在 `merge/upstream-v3.32` 上，
`main` 仍停在 `cd6f6b6b`，未 push、未开 PR。
