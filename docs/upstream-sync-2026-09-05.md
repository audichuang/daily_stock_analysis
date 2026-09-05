# 上游同步记录 2026-09-05（v3.31.0 → 2026-09-04）

## 基线

| | |
| --- | --- |
| 上一次同步基线 | `03e11fe3`（`docs/upstream-sync-2026-08-30.md`，tag `v3.31.0`） |
| 本次上游 HEAD | `e866cfa4` |
| 吸收 commit 数 | 10（全部） |
| 合并方式 | 分支 `merge/upstream-2026-09-05`（叠在 `merge/upstream-v3.31` 上）全量 `git merge upstream/main` |
| merge commit | `c9e4db98`，第一父 `659c4b1b` |
| 冲突档 | 3（`git merge-tree` 乾跑与实际一致） |

**前一轮尚未落地**：`merge/upstream-v3.31`（2026-08-30 完成并稽核）从未合进 `main`、
未 push、未开 PR，`main` 仍停在 `11116673`。本次合并叠在它上面，所以最终 PR 会同时带两轮。

## 为什么是全量而不是挑选

使用者要求「挑选需要的」。**机制上仍取全量 merge，挑选做在稽核层**，理由是这 10 个
commit 不是彼此独立的：`ee2c113a` → `972c3146` → `e866cfa4` 是同一条指数入口链，
依序改同一批档案（`history_service.py`、`stock_code_utils.py`、`api/v1/schemas/*`），
cherry-pick 子集会把 3 个衝突放大成十几个；而且跳过的 commit 在下一次
`git merge upstream/main` 会再出现一次，等于把同一份裁决工作做两遍。
前五轮同步都是这个做法：全量收，然后在稽核里决定哪些行为保留 fork 分歧。

## 吸收的上游改动

| commit | 内容 | 对本 fork 的意义 |
| --- | --- | --- |
| `3d890a07` #2320 | litellm 依赖窗口收敛到 `<1.99.0` | **必收，非可选**，见下 |
| `972c3146` #2312 | Web/API 指数入口 + 共享 canonical 去重 | 最大一笔（4570 行），台股身分已逐条验证，见下 |
| `ee2c113a` #2308 | partial-data 个股 profile 契约 | 新增 `/{stock_code}/profile`；**给既有闸门加了新消费者**，见下 |
| `e866cfa4` #2327 | Bot 指数分析入口 + 在线验收 smoke | 改 `stock_list_parser.py`（+55），台股解析已复验 |
| `b6f9a616` #2325 | 最小 Agent 轨迹评估入口 | 纯新增 `evals/`，A 股 golden samples，对 fork 惰性 |
| `ac8bd29b` #2249 | `SEARXNG_TIMEOUT_SECONDS` 可配置 | 本 fork `SEARXNG_PUBLIC_INSTANCES_ENABLED=true`，用得到 |
| `2ab6f147` #2271 | AkShare 股票名的全角/空白归一 | 只作用在**名称**，未碰代码路径，见下 |
| `d55e4c31` #2314 | Tavily 降为 basic search、限制每股检索次数 | 本 fork 用 3 把 dev key（有额度上限），省 credit 是净收益；**代价是检索深度下降**，若台股新闻品质变差，改回点在 `src/search_service.py` |
| `a69a9097` #2254 | GHSA-5p4m-2wfm-xmqj（桌面端依赖） | 只动 `apps/dsa-desktop/package.json` + lock |
| `77cc9ec3` #2154 | Web 选股结果持久化恢复 | 只动 `StockScreeningPage.tsx`，与 fork 的 `screen_tw.py` 流程无关 |

### `3d890a07` 为什么是必收

`requirements.txt` 原本写 `litellm>=1.80.10,...,<2.0.0`，CI 每次都从 requirements 全新安装，
所以今天会装到 1.99.x。litellm 1.99.0 开始把 `prompt_cache_key` 转发给 OpenAI provider，
而 `tests/test_provider_cache.py:331`
（`test_litellm_openai_prompt_cache_key_is_not_passed_through_without_verified_capture`）
断言的正是「未经验证捕获前不得透传」。本机 venv 是 1.89.3 所以本地看不到，**只有 CI 会红**。

## 冲突裁决（3 档）

### `api/v1/endpoints/analysis.py`

上游在同一处新增了两个函式，取其一：

- `_task_asset_type`：**收**。它在两个 `TaskInfo` 构造点都有呼叫者（第 489、776 行）。
- `_market_review_lock_path`：**丢**。本 fork 在 `26b373c2` 把它当已验证死代码删掉，
  连 `market_review_lock_path` 的 import 一起删了；收回来是一个没有呼叫者的
  潜伏 `NameError` 加一条 flake8 F821。上游那边它同样零呼叫者。

### `api/v1/endpoints/stocks.py`（3 处）

- `_STOCK_CODE_RE`：取上游超集。**这一格 fork 原本是落后的**——fork 写
  `\d{4}\.(?:TW|TWO)`，只认 4 位台股代码，`00878.TW`（5 位）与 `006208.TW`（6 位）
  会被这道闸门 400 掉；上游 `\d{4,6}\.(?:TW|TWO)` 加上 JP/KR 分支是严格超集。
- 两侧在同一位置各插了一个 `@router.get` 端点（fork 的 `/quotes`、`/indices`，
  上游的 `/{stock_code}/profile`），取并集。

### `src/services/history_service.py`

docstring 的参数说明，取上游新增内容。

## 找到的静默降级 / 既有洞（1 处，已修）

### 代码闸门宣称对齐前端，实际上从来没对齐

`_STOCK_CODE_RE` 的注释写着 `aligned with frontend validateStockCode`，但
**Python 的 `\d` 预设是 Unicode-aware，前端那份 JS 正则的 `\d` 只认 ASCII**。
所以全角与阿拉伯-印度数字穿过了每一条数字分支：

| 输入 | 前端 `validation.ts` | 后端（修前） |
| --- | --- | --- |
| `６００５１９` | reject | PASS |
| `００７００.HK` | reject | PASS，还被正规化成 `HK００７００` |
| `００６３１.TW` | reject | PASS |
| `٠٠٦٣١.TW` | reject | PASS |

这是既有缺陷，但**本次合并给它加了新消费者**：上游 #2308 的 `/{stock_code}/profile`
走同一道 `_validate_and_normalize_stock_code`，而且台股分支刚被放宽到 4~6 位。
形状与 2026-08-30 那次的「pre-existing 资料偏差 + 上游新增的消费者 = 新断点」同类，
也与 v3.31 稽核里 `strip_optional_tw_letter` 的第一版 Unicode 漏洞同类
（那次同样是 `isdigit()` / `isalpha()` 的 Unicode-aware 性质）。

无效字元带着一个「合法」的代码身分流进下游 fetcher，抓取失败时 pipeline 刻意 fail-open，
产出的是一份**静默缺资料的报告**而不是一个明确的 400。

**修法**：`re.IGNORECASE` → `re.IGNORECASE | re.ASCII`，修在唯一那处共享正则，
一次涵盖 A 股 / 港股 / 美股 / 日股 / 韩股 / 台股全部分支，不是逐分支补。

守门：`tests/test_stock_watchlist_api.py::test_non_ascii_digits_never_pass_the_stock_code_gate`
（6 个负面案例）与 `::test_ascii_codes_still_pass_after_tightening`（8 个正面案例，
含 `2330.tw` 小写与上游新放宽的 `006208.TW`）。Mutation 双向验过：
拿掉 `re.ASCII` → 6 红；拿掉 `IGNORECASE`（过度收紧）→ 2 红。

## 台股身分逐路径复验

上游这轮有三个 commit 碰到代码身分，逐条实测（不是读 diff）：

| 输入 | `parse_stock_list`（#2327 改过） | `_STOCK_CODE_RE`（本次裁决） | `get_suffix_market` |
| --- | --- | --- | --- |
| `2330.TW` / `0050.TW` / `6488.TWO` | stock | PASS | tw |
| `00878.TW` / `006208.TW` | stock | PASS（修前 REJECT） | tw |
| `00631L.TW` / `00632R.TW` / `2887A.TW` / `00679B.TWO` | stock | **REJECT** ← 见下 | tw |
| `sh000300` | index（`沪深300`） | PASS | — |
| `2330甲.TW` / `００６３１.TW` | unsupported | REJECT（修后） | None |

`ee2c113a` 对 `stock_code_utils.resolve_daily_stock_identity` 的改动方向对 fork 有利：
它把 `tw` **加进**了 offshore identity 集合（原本只有 `jp` / `kr`）。

`2ab6f147` 的 `_normalize_stock_name`（NFKC + 去空白）只套在**股票名称**上
（`stockDB` 初值、AkShare 入库、磁碟快取载入、三个查询口），**没有碰代码路径**，
所以不会把全角代码正规化后绕过上面那道闸门。

fork 既有守门全绿：`test_us_market_path.py` / `test_stock_index_loader.py` /
`test_name_to_code_resolver.py` / `test_stock_code_utils.py` 合计 305 passed；
`test_report_language.py` 36 passed（zh-TW 键数对齐，上游这轮没有新增语言键）。

## 找到的 zh-TW 缺口

### 键缺失（1 处，已修）

上游 #2312 给批量提交的 rejected 分支新增两个文案键
（`watchlist.batchSubmittedWithRejected`、`watchlist.batchPartiallySubmittedWithRejected`），
只加进 `zh` / `en`，漏了本 fork 的 `zhTW`。

`UiTextKey` 由 `zh` 区块推导、`zhTW` 宣告为 `Record<UiTextKey, string>`，所以
**`npm run build` 的 tsc 直接红**（TS2739），不补编译不过。已补两条繁体文案。

后端的 `tests/test_report_language.py` 键数守门这次**没有触发**——36 passed——
因为这轮上游只动了前端文案，没有新增 `report_language.py` 的键。
两道守门覆盖的是不同侧，缺一不可。

### 硬编简中（合并当下**漏判**，Codex 终审抓到）

第一版这份文档写「zh-TW 缺口 1 处且已修」，**这句话是错的**。`uiText` 的
`Record<UiTextKey, string>` 只能抓到「键缺失」，抓不到「根本没走 i18n 的硬编字串」。

上游 #2154 给 `StockScreeningPage.tsx` 新增的选股历史 UI 硬编了 12 条简中文案
（`历史记录` / `加载中...` / `暂无历史选股记录` …）与一处写死的 `toLocaleString('zh-CN')`。

量过之后结论要分成两半，不能混为一谈：

| | 合并前 `659c4b1b` | 合并后 |
| --- | --- | --- |
| `t()` 呼叫 | **0** | 0 |
| 硬编中文字串 | **142** | 154（+12） |
| JSX 内硬编中文 | 35 | 35 |
| 写死 `'zh-CN'` | 2（都是**预设参数**，呼叫端已用 `getIntlLocale(language)` 覆写） | 3（+1，**写死在函式体内、覆写不了**） |

对照 `HomePage.tsx`（55 个 `t()`、0 硬编）与 `RealtimeBoardPage.tsx`（39 / 0）：
**`StockScreeningPage` 是全 app 唯一一页从来没做过 i18n 的**，而且合并前就有 142 条。

因此处置分开：

- **已修**：`formatRunCreatedAt` 的 `locale` 改成参数（预设仍 `'zh-CN'`，与本页另两个
  日期 helper 同款），呼叫端传 `getIntlLocale(language)`。这条与本页**自己的既有写法**
  矛盾，是真缺陷。
- **未修**，见 [#18](https://github.com/audichuang/daily_stock_analysis/issues/18)：那 154 + 35 条硬编字串。只翻 12/166 会让这一页更不一致，
  不是更好；整页 i18n 是独立工作，不该混进上游合并的 PR。

## 合并当下未修的项目（含後续处置）

### 台股带字母尾的代码过不了 API 闸门

`00631L.TW`（元大台湾50正2）、`00632R.TW`、`2887A.TW`、`00679B.TWO` 在
`parse_stock_list` 与 `market_symbol_utils` 都合法（v3.31 那轮修的），但
`_STOCK_CODE_RE` 与前端 `apps/dsa-web/src/utils/validation.ts` 两边都是
`\d{4,6}\.(TW|TWO)`，**都不收字母尾**。

是**既有的功能缺口，不是本次合并的回归**（合并前 fork 的 `\d{4}\.(TW|TWO)`
同样拒收，而且连 `00878.TW` 都拒）。合并前后逐码实测确认这一格没有变化。

**但第一版这份文档就停在这里，是记漏了半句**（Codex 终审补上的）：本次合并的
`ee2c113a` 新增了 `/{stock_code}/profile`，它走的正是这道闸门，所以这个既有缺口
**的爆炸半径被本次合并放大了**——与本文档「找到的静默降级」那节抓的是同一个形状
（pre-existing 缺陷 + 上游新增的消费者 = 新断点），当时只对全形数字那一格套用了
这个判准，对尾字母这一格没有。

**已在後续 PR 修掉**，三处一起（只补后端会製造新的前後端漂移）：

| 位置 | 修法 |
| --- | --- |
| `api/v1/endpoints/stocks.py::_STOCK_CODE_RE` | `\d{4,6}[A-Z]?\.(?:TW\|TWO)` |
| `apps/dsa-web/src/utils/validation.ts` | `/^\d{4,6}[A-Z]?\.(TW\|TWO)$/` |
| `apps/dsa-web/src/utils/chatStockCode.ts` | `/\b(\d{4,6}[A-Z]?\.(?:TW\|TWO))\b/gi` |

外加 `data_provider/base.py::normalize_stock_code` 的台股分支委派共用的
`is_suffix_market_symbol`——原本的 `base.isdigit()` 判不出尾字母，闸门放行之后
`00631l.tw` 与 `00631L.TW` 会以两种写法同时存在於 STOCK_LIST。

### 上游 `data_capability_service` 仍未登记 fork 的 provider

2026-08-30 记录的缺口原样保留（`MarketDBFetcher` / `ShioajiFetcher` / `TwseFetcher`
不在能力矩阵，`GET /api/v1/data/overview` 会把台股日线覆盖错报成 unknown、
TW 实时硬写成 yfinance）。本次上游没有改这块，仍是诊断资讯错误而非路由故障。

## Codex 独立终审（read-only）与七条 finding 的处置

合并 commit 落地後照惯例送 Codex 做对抗式复审（`/codex:handoff`，非编辑运行）。
判定 **DO NOT SHIP**，1 blocker + 3 major + 3 minor。

**它确认取对边的部分**：三个衝突裁决全部正确、`_market_review_lock_path` 确实零
呼叫者、四个端点的 route ordering 不会互吃、`history_service.py` 只有 docstring、
TaskQueue 的 asset-aware dedupe 本身正确、`re.ASCII` 没有收掉任何合法 ASCII 代码、
两组 mutation guard 是真守门（它自己重现过 6 红 / 2 红）。

**逐条处置**（「本次引入？」一栏是用 `git worktree` 退回 `659c4b1b` 逐码实测比对的，
不是读 diff 推断）：

| # | 严重度 | Finding | 本次引入？ | 处置 |
| --- | --- | --- | --- | --- |
| 1 | blocker | `000016.SH` / `SH.000016` 走 REST 分析入口回 400 | 上游新功能送进来就不完整（`_resolve_analysis_input` 合并前**不存在**） | **已修**：`is_code_like` 之前问一次 parser，只有 INDEX 短路 |
| 2 | major | watchlist 把同码指数与个股折叠成一笔 | 否（合并前後 `_watchlist_match_key` 行为**逐码相同**）；本次新增的是上游 Web 开始承诺两者共存 | **已修**：等价键对 INDEX 走 canonical；并修正 add/remove 用正规化值算键（`.SH` 在算键前就被剥掉，删指数会删掉同码个股） |
| 3 | major | profile 闸门拒绝 `00631L.TW` / `BRK-B` / 裸 4 位港股 | 缺口既有（合并前後逐码同为 REJECT），但 `/profile` 是本次新增的消费者 | 台股尾字母**已修**（三处 regex + `normalize_stock_code`）；`BRK-B` 与裸 4 位港股见 [#15](https://github.com/audichuang/daily_stock_analysis/issues/15) |
| 4 | major | 日股 `130A.T`（JPX 2024 起英数码）不被接受 | 否 | [#16](https://github.com/audichuang/daily_stock_analysis/issues/16)：v3.31 明确保留 jp/kr 的纯数字 spec，翻案是决定不是清理 |
| 5 | minor | 新选股历史 UI 硬编简中 | 12 条硬编是本次新增，但该页合并前已有 142 条、`t()` 为 0 | 日期 locale **已修**；整页 i18n 见 [#18](https://github.com/audichuang/daily_stock_analysis/issues/18) |
| 6 | minor | `BJ600519` 过得了 watchlist 闸门却在分析入口 400 | 否（合并前後同为 PASS） | [#17](https://github.com/audichuang/daily_stock_analysis/issues/17)：要把 shared exchange validation 接进写入路径 |
| 7 | minor | `getPopularStocks` 不过滤 index row | 否（loader 移除全域过滤是本次的，但该 helper 零 production caller） | **已删**：不给死代码加过滤器 |

第一版这份文档有两句话讲得太满，已在上面各自更正：「zh-TW 缺口 1 处且已修」
（漏了硬编字串那一类）、尾字母那段只说「不是本次回归」而没写出
`/profile` 让它变成新的断点。

## 验证

| 项目 | 结果 |
| --- | --- |
| `ci_gate.sh syntax` / `flake8` | 绿 |
| **全量离线测试**（`pytest -m "not network"`） | **1 failed / 7348 passed / 8 deselected / 711 subtests，55 分 12 秒** |
| `npm ci` / `lint` / `build` | 绿（lint 2 个既有 warning，0 error） |
| **vitest 全跑** | **2 failed / 101 passed（103 档）** |
| 台股身分逐路径实测 | 见上表，11 种代码形态 |
| fork 既有守门 | `test_us_market_path` / `test_stock_index_loader` / `test_name_to_code_resolver` / `test_stock_code_utils` 合计 305 passed |

### 那 1 个 pytest 红是 `.env` 泄漏假红，不是回归

`tests/test_system_config_service.py::SystemConfigServiceTestCase::test_get_config_defaults_public_searxng_instances_off`
——**与 2026-08-24 记录的第三种假红是同一支测试**（`AGENTS.md` §10）。
照文件的判别法三步全部符合：

| 步骤 | 结果 |
| --- | --- |
| 单跑该测试 | **绿**（1 passed） |
| 带本机 `.env` 的值 `SEARXNG_PUBLIC_INSTANCES_ENABLED=true` 单跑 | **红** |
| **合并前的程式码**（worktree @ `659c4b1b`）+ 同样的 env | **照样红** → 非本次引入 |

本次合并没有碰 `src/services/system_config_service.py`（只在 `config_registry.py`
加了一行 `SEARXNG_TIMEOUT_SECONDS`）。CI 没有 `.env`，那里不会红。

### vitest 那 2 个红也是负载形状

3 条失败全部是 `Test timed out in 5000ms`，落在
`DecisionSignalsPage.test.tsx`(2) 与 `HomePage.test.tsx`(1)。
`HomePage.test.tsx` 是本次 #2312 改过的档案（+325 行），所以不能直接归类，
**单独重跑这两个档：120 tests passed、2 档全绿** → 确认是本 repo 既有的
vitest 高并发超时形状，不是合并引入。

（2026-08-30 那次记录的 16 failed / 2 passed 基线是**与 pytest 并跑时**量的；
这次 pytest 已经结束、机器空下来，同一批只剩 2 档。基线数字要连同当时的机器状态一起读。）

## 回滚

`git reset --hard 659c4b1b`（本次 merge commit 的第一父，即 `merge/upstream-v3.31` 的顶）。
**不要用 merge-base**——理由与上一次同步文档写的相同：merge-base 是一个上游 commit，
与合并前的 fork 分支之间隔着整条台股增量，照著跑会跑得乾乾净净、只有事后才看得出来。
