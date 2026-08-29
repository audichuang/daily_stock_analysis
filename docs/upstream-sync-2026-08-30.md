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

## 回滚

`git reset --hard b4770225`（合并前的 fork main）即可完全回退；
本次所有改动都在 `merge/upstream-v3.31` 分支上，未 push、未 FF `main`。
