# 上游同步记录 2026-09-29（post-v3.32.0 第二轮）

## 基线

| | |
| --- | --- |
| 上一次同步基线 | `f9e7b778`（`docs/upstream-sync-2026-09-20.md` 收的最后一个 commit） |
| 本次上游 HEAD | `d3fee51a`（无新 tag） |
| 吸收 commit 数 | 8（全部） |
| 合并方式 | 分支 `feat/tw-trade-cost-guardrail`：先 commit 工作区的交易成本检核（`4ab64999`），再 `git merge upstream/main --no-ff`（`114a70bc`） |
| 冲突档 | 4（`git merge-tree` 干跑与实际合并一致） |

## 吸收的上游改动

| commit | 内容 | 对本 fork 的意义 |
| --- | --- | --- |
| `be624edc` #2360 | 腾讯日线科创板（688/689）成交量单位是「股」，不再乘 100 | 只作用在 A 股 `TencentFetcher`；台股不走这条 |
| `d3fee51a` #2362 | AkShare 基本面（业绩预告/快报/机构持股/十大股东）按明确报告期调用、修摘要 | A 股基本面；台股基本面走 `market` schema，不受影响 |
| `92475bcf` #2361 | 桌面打包完整收集 MiniRacer，`requirements.txt` 新增 `mini-racer>=0.13.2`（非 Linux） | 本机已装 0.14.1，无需安装；`uv pip check` 全兼容 |
| `e0e0b723` #2331 | 单票决策信号复盘 `GET /api/v1/decision-signals/stocks/{code}/review`；`AGENT_MEMORY_ENABLED=true` 时注入 Agent 记忆 | 见「静默降级排查」 |
| `7ec19d73` #2351 | Multi-Agent 分阶段轨迹评估（`evals/agent_trajectory/`） | reporter，非 gate |
| `322b3674` / `c325c4ae` / `b786ac97` | 测试 fixture 对齐、文档锚点、翻译版 README 与 Anspire 链接 | 文档／测试 |

## 冲突裁决

| 档案 | 裁决 | 理由 |
| --- | --- | --- |
| `apps/dsa-web/.../AlertRuleForm.test.tsx` | 保留 fork | 上游这轮修的「告警市场只含 cn/hk/us」本 fork 早已修过，断言相同，fork 版多一段对齐后端 `MARKET_LIGHT_ALERT_REGIONS` 的注解 |
| `apps/dsa-web/.../SettingsField.test.tsx` | 保留 fork | 上游改的是硬编码描述字串；fork 版绑 `getFieldDescriptionZh('TICKFLOW_PRIORITY')` 真源，措辞再改也不会误伤 |
| `docs/README_EN.md` / `docs/README_CHT.md` | 内容取 fork、链接取上游 | 同一行：fork 改的是日/韩/台股能力边界说明，上游只把 `market-support.md` 改成 `./market-support.md` |

`docs/CHANGELOG.md` 自动合并，上游条目落在 `[Unreleased]` 中段，未搬动。

## 静默降级排查

逐个问上游本轮新增的共用常数／helper「涵盖 `tw` 吗？涵盖 `zh-TW` 吗？」——**本轮没有新增市场集合或语言集合常数**。
新增的 `frozenset` 只有 `REVIEW_WEAK_DATA_QUALITY_LEVELS = {"low", "poor"}` 与 horizon 枚举，都没有市场维度。

- 复盘接口的代码正规化复用既有 `DecisionSignalService._stock_filter_codes`，实测
  `2330.TW`、`2330.tw`→`2330.TW`、`6488.TWO`、`00631L.TW` 都落到 canonical 代码，台股可查。
- Agent 记忆注入（`base_agent.py` 的 review section）由 `AGENT_MEMORY_ENABLED` 控制，本机 `.env` 未开，
  这条路径平常走不到；注入格式是 `key=value` 英文单行，无语言维度。
- 腾讯 `_is_star_market` 判的是 `688`/`689` 前缀，只在 A 股代码路径被调用。

## 验证

| 项目 | 结果 |
| --- | --- |
| `ci_gate.sh syntax` / `flake8` | 绿 / 绿（0） |
| `scripts/check_ai_assets.py` | 绿 |
| 针对性测试（上游新增/改动的 15 档 + `python_version_compat` + 交易成本检核 2 档） | 465 passed |
| Web：`npm ci && npm run lint && npm run build` | lint 0 error / 2 warning，build 绿 |
| Web：`vitest run src/components/alerts src/components/settings` | 146 passed |
| Desktop：`npm test` | 51 passed |
| **全量离线测试** | 见「全量结果」 |

## 全量结果

`uv run ./scripts/ci_gate.sh`（all，第四阶段 `pytest -m "not network"`），2026-09-29 本机执行，跑的期间未改档、未与 vitest 并跑：

```
1 failed, 7515 passed, 8 deselected, 51 warnings, 717 subtests passed in 260.39s (0:04:20)
```

唯一的红是 09-05 / 09-12 / 09-20 三轮都出现的同一支 `.env` 泄漏假红
`tests/test_system_config_service.py::SystemConfigServiceTestCase::test_get_config_defaults_public_searxng_instances_off`：

| 步骤 | 结果 |
| --- | --- |
| 单跑该测试 | **1 passed** |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED=true` 单跑 | **1 failed**（复现；本机 `.env:351` 即为 `true`） |
| 非因果：`git diff --name-only 10fafec6..HEAD` | 没有碰 `system_config` 或 searxng 任何一档 |

CI 无 `.env`，那里不会红。subtests 717 与 09-20 相同。

## 落地方式

分支 `feat/tw-trade-cost-guardrail`，未 push。推上去走 PR（base=main）才会跑阻断 CI（CI 跑 Python 3.11）。

## 回滚

合进 `main` 之前：直接删分支即可，`main` 未动。

合进 `main` 之后，只撤上游这一批、保留交易成本检核：

```bash
git revert -m 1 <merge commit>     # 以第一父（fork 侧）为主线撤掉上游 8 个 commit
```
