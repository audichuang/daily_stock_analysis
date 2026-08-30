# 上游同步记录 2026-08-30（v3.30 → v3.31.0）

## 基线

| | |
| --- | --- |
| 上一次同步基线 | `b4770225`（`docs/upstream-sync-2026-08-23.md`） |
| 本次上游 HEAD | `03e11fe3`（含 tag `v3.31.0`） |
| 吸收 commit 数 | 17 |
| 合并方式 | 分支 `merge/upstream-v3.31` 上全量 `git merge upstream/main` |
| 冲突档 | 6（`git merge-tree` 乾跑与实际一致） |

## 吸收的上游改动

| commit | 内容 | 对本 fork 的意义 |
| --- | --- | --- |
| `03e11fe3` #2250 | 美股日线路由消费各源 `*_PRIORITY` | **与 fork 增量冲突**，见下 |
| `0cf61c63` #2311 / `0b5f9a6e` #2291 | research artifact 契约 + OpenAPI 同步 | 追加字段，无兼容性破坏 |
| `86bbf015` #2310 / `0709b17e` #2289 | data capability 契约 | 纯报表 API，不是闸门 |
| `eb1333a6` #2300 | `--stocks` 一次性分析板块指数 | **在本 fork 曾整组失效**，见下 |
| `ee635a35` #2274 | 桌面端右上角更新入口 | 需补 zh-TW 6 键 |
| `e75c4bb6` #2301 | arXiv 论文链接与 citation metadata | 无 |
| `fb4735a1` #2269 | 富途 OpenD 作为港股可选实时/基本面源 | 可选，无金钥即不启用 |
| `f92ad2e7` #2272 | 分词模块 | 新增独立模块，import 乾净 |
| `1b429076` #2267 / `55ad4468` #2258 | A 股指数注册表与多源 fallback 路由 | 依赖指数注册表，见下 |
| `262cf5d5` #2255 | docs-only 变更跳过重 job | 不影响 `ai-governance`（无 `if:`，永远跑） |
| `8d5b9628` #2256 | CVE-2026-25639（前端依赖升级） | 只动 `package.json` / lock |
| `e45d5ce2` #2270 | 修复 Linux 分享图中文缺失 | 与 fork 的小红书留空裁决不冲突 |
| `5bb31392` #2219 | runtime scheduler 隔离 + portable watchdog | 与 fork 的 signal deadlock 修法正交，见下 |
| `9ab79b82` #2260 | v3.31.0 发版文档 | 无 |

## 冲突裁决（6 档）

### `api/v1/schemas/history.py`
两侧各加一个 import，取并集。

### `data_provider/realtime_types.py`
`RealtimeSource` 枚举：上游加 `FUTU`，fork 有 `SHIOAJI` / `YFINANCE`，取并集。
fork 专属字段 `limit_up` / `limit_down` 未受影响。

### `data_provider/base.py`（4 处）
三处是并集（`_futu_fundamental_fetcher` 与 `_twse_fundamental_adapter`、两个 import、
`FutuFetcher` 与 `ShioajiFetcher` 的 source 映射）。第四处见下方「保留的 fork 分歧」。

### `data_provider/yfinance_fetcher.py`（3 处）
- 门槛条件：取上游的超集（新增港股），但用 fork 的 `_is_yahoo_suffix_stock`
  （它已涵盖上游拆出的 `_is_jp_kr_suffix_stock` + `_is_tw_suffix_stock`）。
- `UnifiedRealtimeQuote` 的 `source` / `market`：**保留 fork 的 `_source_for_market()`**
  （上游硬写 `RealtimeSource.FALLBACK`，会让 us/jp/kr 的真实主来源被标成兜底），
  并接上上游新增的港股判定。市场表达式抽成 `quote_market` 局部变量算一次。
  港股不在 `_YF_PRIMARY_MARKETS`，因此仍标 `FALLBACK`，与上游同义。

### `src/core/pipeline.py`（5 处）
- 股票名称：**两个守门都要**——指数保持注册表中文名（上游 #2300），股票仍只在
  轻量名称路径没拿到有效名称时才用实时行情名兜底（fork 增量：避免台股 yfinance
  兜底的英文名覆盖本地索引中文名）。
- 两处 `_finalize_and_persist_result`（fork 的共用 finalize 阶段）对上上游的
  inline Step 7.7/Step 8：**保留 fork 的共用阶段**，把上游在那个区块里新增的两项
  增量接进去——`_append_daily_data_source(...)` 移到 finalize 之前（历史保存在
  finalize 内部，晚了就存不进去），`analysis_target` 透传进
  `_extract_decision_signal_after_history_save`（`_finalize_and_persist_result`
  因此多一个可选参数）。
- Agent 路径的 `analysis_context` / `market`：保留 fork 的 artifacts 建构，
  接上上游的 `analysis_target=` 与 `market = "cn" if is_index else ...`。
- `_augment_historical_with_realtime`：**保留 fork 的「只读一次时钟」**
  （`market_now` 单次读取，供 PREMARKET 判定共用），接上上游新增的 `market` 参数
  与 `if market is None` 兜底。

### `apps/dsa-web/public/stocks.index.json`
三方比对确认是乾净并集：上游新增 31 笔 A 股指数（`sh*` / `sz*` / `csi*`），
fork 新增 9545 笔台股/美股，两侧**零重叠、零同码修改**。取 fork 全量 + 追加上游 31 笔，
canonical 唯一性已断言。

## 保留的 fork 分歧

### 美股日线首选锚定（`data_provider/base.py`）

上游 #2250 让 `source_order` 再过一次 `_order_us_sources_by_priority`，
`pin_first` 只在「指数 / Longbridge preferred」时为真。预设优先级是
**Finnhub=2 < AlphaVantage=3 < Yfinance=4**，所以普通美股那条链会被**无声重排**成
AlphaVantage 在 yfinance 之前——正是 fork 刻意排掉的形状（AlphaVantage 回未复权价
且单次上限 100 根，manager 收下非空 DataFrame、storage 按 (code, date) UPSERT，
设了金钥之後最近 100 根内的除权息会印出错的 `pct_chg`，同一天收盘价还会随执行次数变动）。

**裁决：呼叫点一律 `pin_first=True`。** 本 fork 三条链路的首选都是刻意锚定的
（指数锚 yfinance、Longbridge preferred 锚 Longbridge、普通美股锚 yfinance），
其余兜底成员仍按 `*_PRIORITY` 重排——上游「单项调整即时生效」的能力对兜底段完整保留。

| | 上游 | 本 fork |
| --- | --- | --- |
| 普通美股首选 | 按 `*_PRIORITY` 排序（预设 Finnhub） | 锚定 Yfinance |
| `YFINANCE_PRIORITY=0` | 把 yfinance 提到首位 | 本来就在首位（无差异） |
| `ALPHAVANTAGE_PRIORITY=0` | 把 AlphaVantage 提到首位 | **不生效**（首选锚定），其余段仍按优先级 |

守门：`tests/test_us_market_path.py::TestUsDailyChainPrefersYfinance`
新增 `test_priority_resort_cannot_demote_the_pinned_first_source`
（同时断言呼叫点写法与 `pin_first=False` 的反向行为）。

### 小红书品牌预设仍留空
`DEFAULT_XIAOHONGSHU_HANDLE` / `DEFAULT_XIAOHONGSHU_QR_PATH` 维持 `""`
（2026-08-23 的裁决，见该次 sync doc）。本次合并未回填。

## 找到的静默降级（1 处，已修）

### 指数注册表在本 fork **整个是空的**

上游 #2258 新增 `src/data/stock_index_loader.py::_load_active_index_rows()`，
它对**每个**索引候选（含 bundled `apps/dsa-web/public/stocks.index.json`）跑
`validate_stock_index_payload`。而该校验器的资产类型白名单是 `{stock, index, etf}`。

本 fork 的美股索引里有 **18083 笔 `asset_type="unknown"`**——这是刻意的：
`scripts/refresh_us_stock_index.py` 对官方清单查无的美股（多为 OTC）标 `unknown`
而不是留预设的 `stock`，因为留 `stock` 会让下游把它当成权威的「不是 ETF」，
於是清单外的真 ETF（Leverage Shares 那批、BLCN/KRMA/QRFT）拿不到 ETF 式检索。

结果：bundled 候选在**第一笔** US `unknown`（item 8263）被拒收，legacy `static`
候选同样被拒，注册表落到「所有指数候选均失败」的空集合。实测
`_load_active_index_rows()` 回 0 行 → `--stocks` 板块指数、CSI provider 路由、
`sh000300` 之类的输入全部失效，**只有一行 WARNING，没有任何报错**。

这是第四种形状，值得单独记住：**pre-existing 的资料偏差 + 上游新增的消费者 = 新断点**。
资料本身合并前就是这样，但合并前没人对 bundled 档跑这个校验
（`validate_stock_index_payload` 原本只用在远端快取路径，而本 fork
`STOCK_INDEX_REMOTE_UPDATE_ENABLED=false`），所以缺陷一直是潜伏的。

**修法**：在 `src/services/stock_index_remote_service.py` 的白名单加入 `unknown`
——修在所有呼叫者共用的那一处，而不是绕过上游的新函式。
`unknown` 不授予任何能力：索引行必须 `asset_type == "index"` 才会被
`_extract_active_index_rows` 收下，Web 端也只认 `assetType === 'stock'`。

守门：`tests/test_stock_index_loader.py::TestBundledIndexRegistryLoadsInThisFork`
（一条端到端断言注册表非空且含 `sh000300`，一条断言 `unknown` 被放行但永远拿不到
指数身分、而真正的非法值仍被拒）。两条都过了 mutation 检查。

## 上游新测试在本 fork 的墙钟预算不足（已放宽）

`tests/test_runtime_scheduler_service.py`（上游 #2219 新增的那批）在本 fork 红：
**全量 638 个测试同跑时 5 红，单独跑剩 2 红**——这个「跑越多红越多」正是本 repo
既有的负载敏感形状，但这次底下还压着一个结构性差异。

量出来的根因：这些测试轮询的是一次 **`spawn` 往返**，子行程必须完整 import
本 fork 更重的模组图（shioaji / litellm / exchange_calendars 等）。
裸 `spawn` 往返 0.13~0.19s，带上模组图是 **3.30s（空机器实测）**，
而上游给的观察窗是 4~5s、`test_watchdog_reads_large_worker_result_before_joining`
的 worker 预算更只有 2s。所以在上游是宽裕的余量，在本 fork 是擦边或直接不够。

裁决与上一次 `test_tw_institution_report_wiring.py`（`662c2ee1`，1.5s/0.8s → 30s/15s）
同形：把**观察窗**统一放宽到 60s。放宽不减弱——迴圈一旦条件成立就退出，
真正的守门是迴圈之後那几条断言；留着 4~5s 反而让「超时」伪装成「行为错误」。
测试没变慢（`test_runtime_scheduler_service.py` 全档仍约 60s，与放宽前同量级）。

三处刻意不动，都做过 mutation 验证：

| 位置 | 为什么不动 |
| --- | --- |
| `_analysis_timeout_seconds = lambda: 1`（第一阶段） | 与 `assertIn("timed out after 1s")` 成对；放宽整条测试就不再守超时（实测改成 60 立刻红） |
| `callback_returned.wait(timeout=0.5)` | 断言的是「回调此刻没有被分析挡住」，值越大越宽松 |
| `_large_failure_spawn_runner` 的 `last_error.startswith("x")` | 这才是 watchdog 测试真正的守门（大结果在 join 之前被读走），放宽的只是它周围的预算 |

`test_blocked_scheduled_analysis_times_out_and_allows_next_run` 另外需要一处修正：
它第二阶段换成 `_successful_spawn_runner` 验「超时之後下一轮仍被允许并且跑成功」，
却沿用第一阶段的 1s 预算——在本 fork 的 3.30s 往返下成功路径**永远验不到**，
必然又超时一次。换 runner 时一并把预算放回 60s。

## 找到的 zh-TW 缺口（1 处，已修）

上游 #2300 为指数日线来源归因新增 `data_sources_label`，只加进 `zh` / `en` / `ko`，
漏了本 fork 的 `zh-TW`。这次是 fork 自己的守门测试
（`tests/test_report_language.py::ZhTWLanguageNormalizationTestCase::test_get_report_labels_zh_TW_key_count_matches_zh`）
当场抓到的——与前几次「合并後靠人肉 grep 才发现」不同，键数对齐守门这次真的生效了。
已补 `"data_sources_label": "資料來源"`。

## 查过但没问题的项目

- `MARKET_REVIEW_REGION_ORDER` / `MARKET_LIGHT_REGIONS` / `SUPPORTED_REPORT_LANGUAGES`
  / `SUPPORTED_STOCK_INDEX_MARKETS` 合并后仍含 `tw` / `zh-TW` / `TW`
- `parse_stock_list`：`2330.TW` / `0050.TW` / `6488.TWO` / `00878.TW` 都判为 `stock`，
  不会被指数注册表吃掉；`sh000300` / `000300.SH` / `csi930955` 正确判为 `index`
  （裸 `2330` → `hk2330` 是既有行为，非本次引入）
- `.github/workflows/ci.yml`：#2255 的 docs-only 跳过不影响 `ai-governance`
  （该 job 没有 `if:`），fork 的 `changes` job `permissions` 增量与 py3.11 pin 都还在
- `src/scheduler.py`：上游 #2219 的 `_lifecycle_lock` 在 `Scheduler`，
  fork 的 signal deadlock 修法在 `GracefulShutdown._signal_handler`（不抢任何锁），
  两者正交，不成环
- 9 个上游新增模块 import 冒烟全绿（不再出现 `empty_news` 那种 import 即炸的语言守门）
- `requirements.txt` 零改动，无需安装新依赖

## 补齐的 i18n

`apps/dsa-web/src/i18n/uiText.ts` 的 `zhTW` 区块补 6 个 `layout.desktopUpdate*` 键
（上游 #2274 只加了 `zh` / `en`；`UiTextKey` 由 `zh` 推导且 `zhTW` 宣告为
`Record<UiTextKey, string>`，不补 tsc 直接红）。
`apps/dsa-web/src/locales/settingsHelp.ts` 只有 zh-CN / en-US 两块，
本 fork 未派生 zh-TW 版本，无对齐缺口。

## 已知缺口（未修）

`src/services/data_capability_service.py`（上游 #2289）的能力矩阵只登记上游认得的
provider，本 fork 的 `MarketDBFetcher`（台股日线 priority=1）与 `ShioajiFetcher`
（台股实时）不在其中。该服务只被 `api/v1/endpoints/data.py` 消费，是**报表而非闸门**，
不影响任何路由；台股在矩阵里已由 yfinance 覆盖，所以不会显示成「不支持」，
只是少列了两个真实来源。刻意不在本次合并扩大范围。

## 合并后的对抗稽核（6 lens / 49 agents，读取式）

合并 commit 落地后跑了一轮唯读稽核（逐冲突档复核、auto-merge 语意冲突猎杀、tw/zh-TW
覆盖重扫、指数注册表、provider 路由、测试守门品质），每条 finding 由三个不同角度的
skeptic 独立尝试反驳，2/3 存活才收下。结果：1 blocker + 2 major + 3 minor + 3 完整性缺口。

### BLOCKER：台股带字母尾的代码被合并挡死（已修）

上游 #2267 给 `DataFetcherManager.get_stock_data` 加了一道硬守门——
`parse_analysis_target` 判 `ParseStatus.UNSUPPORTED` 就直接 `raise DataFetchError`，
**在 fetcher 清单建起来之前**。fork main 上完全没有这道守门
（`git show 11116673:data_provider/base.py` 里没有任何 `ParseStatus.UNSUPPORTED`）。

台股带尾字母的代码因此全数失效：槓桿 `00631L.TW`（元大台灣50正2）、反向 `00632R.TW`、
债券 ETF `00679B.TW`、特别股 `2887A.TW`、上柜 `00675L.TWO`。

根因是三处各自要求 base 全为数字，而其中两处是**同一条规则的两份实作**：

| 位置 | 作用 |
| --- | --- |
| `market_symbol_utils.get_suffix_market` | 后缀市场判定（yfinance 路由、index loader、resolver 共用） |
| `stock_code_utils._valid_exchange_code` | 显式交易所后缀校验（parser 的 UNSUPPORTED 判定） |
| `yfinance_fetcher._is_yahoo_suffix_stock` | **手写的第三份**，`get_realtime_quote` 的门槛 |

修法：在 `market_symbol_utils` 加共用的 `strip_optional_tw_letter()`（只放行「4~6 位数字
+ 至多一个 ASCII 大写字母」，且**只限 tw**，jp/kr spec 不动），前两处调用它；第三处
**删掉手写实作**改为委派 `is_suffix_market_symbol` —— 两份同义规则注定漂移，这次就漂了：
只修前两处的话，代码能被 parse 却拿不到实时行情，症状比原本的硬 raise 更难查。

本 fork 的 `name_to_code_resolver.py` docstring 早就记录过这个缺口并判定
「为休眠 API 放宽不划算」，同时写明「真要修，改 `market_symbol_utils` 并连带验那三条路径」。
合并把它从休眠变致命，权衡因此翻转；该段 docstring 与对应的 decision-tripwire 测试
（`test_documented_gaps_stay_none`）已一并收敛成新决定，理由写在原处。

守门：`tests/test_us_market_path.py::TestTaiwanLetterSuffixedCodesSurviveTheUnsupportedGate`
（parse / suffix / yfinance / 正规化四条路径各一条，外加「不是放行任意 base」的反向断言）。
Mutation 验过四次，其中两次是分别拿掉两个半边——各自只让对应的测试红，证明三处是
独立守住的，不是靠同一条断言兜底。

### MAJOR ×2：把观察窗放宽到 60s 时，defang 了两个 `stop()` 测试（已修）

`_blocking_spawn_runner` 自己 `sleep(10)`、`_block_with_isolated_descendant_spawn_runner`
自己与其 descendant 各 `sleep(30)` —— 全部在 60s 观察窗内自然结束，所以就算删掉
`stop()` 里的 `_terminate_analysis_process_tree(process)`，测试照样绿。

修法不是缩窗口（那会把负载假红请回来），而是把**自然寿命**拉到 180s：远超观察窗，
仍 < `setup.cfg` 的 `--timeout=300`，且相关测试的 `finally` 会 `killpg` 收尾。
正常路径（被杀）仍在 ~3.5s 内结束，测试没有变慢。
Mutation 验过：删掉终止调用，两条测试撑满 60s 后如期变红。

### MINOR（已修）

- `tests/test_us_market_path.py` 新增的 pin_first 守门，其正向断言退化：fixture 的兜底段
  本来就照 priority 排序，期望值等于输入值，一个「`pin_first=True` 就原样回传」的空实作
  也会过。Finnhub 改给 priority 7，期望值与输入顺序不同，空实作即红。
- 本文档的回滚指令原本写 `git reset --hard b4770225`，把上游 merge-base 误标成
  「合并前的 fork main」。两者相距 **128 个 fork commit**，照着跑会静默洗掉整条台股增量。
  已更正为第一父 `11116673` 并注明为什么不能用 merge-base。
- `docs/share-images.md` 称报告语言只支持 `zh|en|ko`；`.env.example` 称指数注册表只有 5 档。
  两处都已对齐实际（zh-TW、31 档）。

### 上游测试与 fork 增量的两处结构性冲突（已修，非产线缺陷）

全量离线测试暴露的两条红，都是上游新测试的假设撞上 fork 的既有增量：

- `test_pipeline_index_targets::test_v10_agent_branch_persists_and_renders_daily_source`
  把 `_build_agent_analysis_artifacts` mock 成回 `{}`。上游只把 artifacts 餵给
  `_build_analysis_context_pack_outputs`，`{}` 无害；本 fork 还把它带进共用的
  `_finalize_and_persist_result`（要 `.trend_result` / `.code` / `.metadata["query_id"]`），
  于是 `AttributeError` 被 `except` 吞掉、`_analyze_with_agent` 回 None，红的形式是
  「result is None」——看起来像行为错误。产线路径已核对无误。改成回一个真的
  `PipelineAnalysisArtifacts`，上游断言意图原样保留，且顺带验到 fork 的接线。
- `test_yfinance_hk_bare_code::test_hk_code_executes_realtime_route` 断言
  `currency == "HKD"`，但本 fork 在本地策划索引命中股名时**刻意不碰 `ticker.info`**
  （~1-3s 的 quoteSummary 调用，看板 yfinance 延迟的主因），代价就是 currency / PE / PB
  为空 —— 这个取舍在 `yfinance_fetcher.py` 里本来就写着。fork main 的门槛根本不收港股
  （直接回 None），所以合并采用上游超集是对的，分歧只在这一格。把上游那条断言**移到
  它真正可达的路径**（patch 掉本地索引、走回退路径），原测试改为断言快路径的实际行为。
  少了新增那条，「快路径生效」与「回退路径整个坏掉」在测试里长得一模一样。

### 记录但未修

- **zh-TW 分享图会以简体字形渲染。** `_poster_language` 把 zh-TW 折叠成 `zh`、
  `_poster_html_language("zh")` 回 `zh-CN`，这两步是既有的；但 #2270 **新**把
  `Noto Sans CJK SC` 绑到 `html[lang="zh-CN"]` 上，并在 Dockerfile 里让该字体确实可选中。
  所以这是「既有缺口被本次合并具体化」，不是纯 pre-existing。真要修需要三件事：
  `zh-TW` 的 html lang、对应的 `Noto Sans CJK TC` 规则、`_POSTER_TEXT` 的 zh-TW 文案块。
  刻意不在合并里顺手改。

## 回滚

`git reset --hard 11116673`（合并前的 fork main，即本次 merge commit 的第一父）即可完全回退。
**不要用 `b4770225`**——那是本次合并的 merge-base（一个上游 commit），与合并前的 fork main
之间隔着 **128 个 fork commit**，照着跑会静默洗掉整条台股增量（TWSE+TPEx 单边合计修复、
scheduler signal deadlock 修复、TWSE 端点停更时的本地涨跌家数、移除上游作者的小红书品牌等），
而且命令本身跑得干干净净、只有事后才看得出来。
本次所有改动都在 `merge/upstream-v3.31` 分支上，未 push、未 FF `main`。
