# 上游同步记录 2026-10-14（post-v3.32.0 第六轮）

## 基线

| | |
| --- | --- |
| 上一次同步基线 | `c3349de4`（`docs/upstream-sync-2026-10-11.md` 收的最后一个 commit） |
| 本次上游 HEAD | `6cb86d6e`（无新 tag，`v3.32.0-45`） |
| 吸收 commit 数 | 3（全部；34 档，+995／−120） |
| 合并方式 | 分支 `chore/upstream-sync-2026-10-14`（自 `main` `2f5fe068`）`git merge upstream/main --no-ff` |
| 冲突档 | 2：`docs/README_CHT.md`、`docs/README_EN.md`（`git merge-tree` 干跑与实际合并一致） |
| 新依赖 | 无 |

## 吸收的上游改动

| commit | 内容 | 对本 fork 的意义 |
| --- | --- | --- |
| `2d306682` #2403 | Modelflare 单 Key 接入：只设 `MODELFLARE_KEY` 就自动推出 `modelflare` 渠道、默认 Base URL（`https://modelflare.dev/v1`）与模型（`openai/gpt-6.1-sol`）；后端 `Config`、生成后端状态、选股 pipeline、Web 渠道编辑器共用 `resolve_llm_channel_*`；设置页配置校验失败改显示具体栏位；README 赞助区换成 Modelflare | 只在设了 `MODELFLARE_KEY` 时生效；本 fork 生成走本机 Claude Code CLI、`.env` 无此键，行为不变（合并后实测 `generation_backend=claude_code_cli`、渠道列表与合并前相同） |
| `6cb86d6e` #2407 | 三语 README 各用对应语言的 Modelflare 横幅（新增 3 张 PNG，约 3 MB） | 仅文档 |
| `45a75388` #2399 | 设置页首次启动引导的「维护自选股」按钮滚动并聚焦到 `STOCK_LIST` 栏位 | 小改进，直接受益 |

## 冲突裁决

| 档案 | 裁决 |
| --- | --- |
| `docs/README_CHT.md`、`docs/README_EN.md` | 三处冲突（赞助横幅、AI 模型列表、推荐 Secret）都是上游把 Anspire 换成 Modelflare 的推广内容，本 fork 无立场，**冲突块一律取上游**；非冲突处的既有 fork 文字不动 |

## 静默降级排查

- 本轮上游没有新增市场集合或语言集合常数；新增的 `resolve_llm_channel_*` 只按渠道名判断，与市场／语言无关
- Web：上游没有新增 `uiText` 键，`zhTW` 严格 `Record` 不受影响（`npm run build` 通过）
- **新文案写死简体（不修，既有缺口）**：`api/error.ts` 的配置校验提示（「配置需要调整」「请填写此渠道的 API Key。」等）与 `LLMChannelEditor.tsx`／`llmProviderTemplates.ts` 的 Modelflare 文案直接写死简体，zh-TW 介面会看到简体。合并前这两档就各有 36／139 行写死的简体（同一类缺口），本轮只是多几行
- `.env.example` 的 `STOCK_INDEX_REMOTE_UPDATE_ENABLED` 等 fork 约定未被改动

## 验证

| 项目 | 结果 |
| --- | --- |
| `ci_gate.sh syntax` / `flake8` | 绿 / 绿（0） |
| 受影响测试子集（上游改动的 5 个测试档 + `test_config_env_compat`、`test_config_registry`、`test_python_version_compat`） | 489 passed |
| 本机 `.env` 载入 | `generation_backend=claude_code_cli`，渠道列表同合并前 |
| Web `npm run lint` / `npm run build` | 0 error（1 个既有 warning）/ 绿 |
| Web `vitest`（`src/api`、`src/components/settings`、`SettingsPage`） | 19 档，291 passed |
| 全量离线测试 | 本机未跑，交给 PR 的 CI（Python 3.11，无 `.env`） |

## 回滚

`git revert -m 1 <merge commit>`。无 schema 变更。
