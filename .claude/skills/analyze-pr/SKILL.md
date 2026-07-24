---
name: analyze-pr
description: 审查 GitHub Pull Request 的必要性、验证证据、兼容性风险与合入判定。当用户要 review 某个 PR、或判断它能不能合入时使用。
---

# Analyze PR

分析 GitHub Pull Request，评估必要性、描述完整性、验证证据、主要风险与是否可直接合入。

**Repository**: https://github.com/ZhuLinsen/daily_stock_analysis/pulls

## Usage

```text
/analyze-pr <pr_number>
```

## Instructions

分析时使用简洁中文，优先遵循仓库根目录 `AGENTS.md` 和 `.github/PULL_REQUEST_TEMPLATE.md`。

审查按这个维度顺序推进：**必要性 → 关联性（对应 issue）→ 标题建议 → 描述完整性 → 验证证据 → 实现正确性 → 合入判定**。输出文档的 `Summary` 要逐项覆盖这七个维度，缺项即视为审查未完成。

### Step 1: 同步基线

按 [`../shared/baseline-sync.md`](../shared/baseline-sync.md) 执行，并把结果记进输出文档的 `Validation Evidence`。

### Step 2: 拉取 PR 基本信息

```bash
gh pr view <pr_number> --repo ZhuLinsen/daily_stock_analysis
gh pr view <pr_number> --repo ZhuLinsen/daily_stock_analysis --comments
gh pr checks <pr_number> --repo ZhuLinsen/daily_stock_analysis
gh pr diff <pr_number> --repo ZhuLinsen/daily_stock_analysis
```

如有失败的 CI，优先查看失败日志，而不是立刻在本地重跑全部检查：

```bash
gh run view <run_id> --log-failed
```

### Step 3: 检查标题与描述完整性

先检查 PR title 是否符合 `AGENTS.md` 的非阻断建议：

- 格式应为 `<类型>: <修改内容>`，例如 `fix: 修复大盘分析历史记录丢失`
- 类型优先为 `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci`
- 不应包含 `[codex]`、`codex`、`autocode`、`copilot` 或其他工具/agent 来源前缀
- 标题应描述实际变更；若标题与 diff 不符，在描述完整性中指出，但不应单独作为 review process blocker。

对照 `.github/PULL_REQUEST_TEMPLATE.md`，确认是否覆盖：

- `PR Type`
- `Background And Problem`
- `Scope Of Change`
- `Issue Link`
- `Verification Commands And Results`
- `Visual Evidence`（仅当 PR 修改报告格式、报告渲染效果或 Web UI 界面时要求截图或替代可视证据）
- `Compatibility And Risk`
- `Rollback Plan`

若 PR 涉及第三方模型 / API 兼容语义、请求参数固定值、OpenAI-compatible 路由、YAML alias、fallback 行为或运行时配置保存 / 清理 / 迁移逻辑，还要额外检查描述里是否明确写出：

- 官方来源链接或公告
- 当前锁定依赖 / 运行时兼容范围（例如 LiteLLM 版本窗口）
- 已验证的调用链路覆盖面
- 旧配置是否会被静默改写、清空、迁移或保持不变
- 最小回滚路径（通常是 revert 本 PR）

若 PR 修改报告格式、报告渲染效果或 Web UI 界面，还要检查 `Visual Evidence` 是否附受影响报告 / 页面截图；涉及前后差异时优先检查前后对比。若无法截图，描述中应说明原因与替代可视证据。

### Step 4: 优先使用 CI / Diff 证据

- 先根据 `gh pr checks`、PR diff、现有测试与工作流日志判断问题
- 仅当 CI 未覆盖改动面、CI 结果不足以定性问题、或需要验证关键回归风险时，再补充本地最小验证
- 不要默认切换当前分支或执行 `gh pr checkout`

如果必须补本地验证，按改动面选择最接近的检查，例如：

- 后端：`uv run ./scripts/ci_gate.sh syntax` + `uv run ./scripts/ci_gate.sh flake8`（秒级快速门槛；本机必须带 `uv run`，否则 `python: command not found`）或 `uv run python -m py_compile <changed_python_files>`；**不要**在 review 场景跑不带参数的 `ci_gate.sh`，它等于 `all`、含约 30+ 分钟全量离线测试
- 前端：`cd apps/dsa-web && npm ci && npm run lint && npm run build`
- 桌面端：先构建 Web，再构建 Electron

### Step 5: 评估正确性与风险

重点检查：

- 是否解决了明确问题，且没有夹带无关改动
- 是否破坏 API / Schema / Web / Desktop 兼容性
- 是否破坏 fallback、降级路径、通知链路或发布流程
- 是否存在明显逻辑错误、异常吞没、安全问题、配置语义变化未同步文档

`fix` 类 PR 必须能回答四项：原问题、根因、修复点、回归风险。答不全即描述完整性不足。

### Step 6: 合入判定

出现以下任一项即判定为不可直接合入，并在 `Draft Review Comment` 写明卡在哪一项：

- 正确性或安全性问题
- 阻断型 CI 未通过（`ai-governance` / `backend-gate` / `docker-build`，以及前端改动触发时的 `web-gate`）
- PR 描述与实际改动内容实质性矛盾
- 缺少回滚方案
- 反复出现未收敛的契约漂移、补丁堆叠或验证证据失真——这种情况建议关闭重做，而不是继续逐点 review；作者侧的收敛程序见 skill `respond-to-review`

### Step 7: 生成评审文档

保存到 `.claude/reviews/prs/pr-<number>.md`

## Output Document Format

```markdown
# PR #<number> Analysis

**Date**: YYYY-MM-DD
**Status**: Pending Review

## Findings

- [严重级别] file:line - 问题描述

## Summary

- 必要性：
- 是否有对应 issue：
- PR 类型：
- PR title：
- description 完整性：
- 验证情况：
- 实现正确性：
- 主要风险：
- 是否可直接合入：

## Validation Evidence

- 代码同步基线：
- CI 结论：
- 本地补充验证（如有）：

## Compatibility And Risk

- API / Web / Desktop：
- 配置 / Docker / GitHub Actions：
- fallback / 通知 / 报告结构：
- 第三方依赖 / 官方约束来源：
- 运行时兼容窗口 / 已覆盖链路：
- 旧配置迁移或静默改写风险：

## Draft Review Comment

<建议评论内容>
```

## 可自主执行

拉取 PR 元数据 / diff / 评论 / CI 状态、阅读代码与模板、执行 Step 4 的最小化本地验证、生成评审文档，以及 [`../shared/baseline-sync.md`](../shared/baseline-sync.md) 允许的 fast-forward 同步。

改变远端状态的操作（发布评论、approve、request changes、merge、关闭 PR）按同一份文件的确认边界执行——一律先问。
