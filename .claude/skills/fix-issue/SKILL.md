---
name: fix-issue
description: 按 issue 分析结论实现修复，并补齐验证、风险与回滚说明。当用户要动手修某个 issue 时使用。
---

# Fix Issue

基于 issue 分析结果实现修复，并按仓库规则补齐验证、风险与回滚说明。

**Repository**: https://github.com/ZhuLinsen/daily_stock_analysis

## Usage

```text
/fix-issue <issue_number>
```

## Prerequisites

优先先完成 `/analyze-issue <issue_number>`，确保问题成立且边界清晰。

## Instructions

### Step 1: 确认分析基线

检查 `.claude/reviews/issues/issue-<number>.md` 是否存在；如果不存在，先补做 issue 分析或在本次修复中补齐最小分析结论。

### Step 2: 同步基线

按 [`../shared/baseline-sync.md`](../shared/baseline-sync.md) 执行。默认基于当前工作树做最小相关改动，保持用户当前工作状态不变；用户明确要求建分支时才动分支。

### Step 3: 实施修复

- 根据 issue 结论定位相关文件
- 优先复用现有模块、配置入口、脚本和测试
- 保持默认行为向后兼容，避免破坏 fallback / fail-open
- 如果修复涉及用户可见行为、配置语义、CLI/API、部署、通知、报告结构，要同步更新相关文档、`docs/CHANGELOG.md`、`.env.example`
- 向 `docs/CHANGELOG.md` 写入条目时，在 `[Unreleased]` 段追加一行，格式为 `- [类型] 描述`，其中 `[类型]` 从 `[新功能]/[改进]/[修复]/[文档]/[测试]/[chore]` 中按本次变更内容选择；只有修复 bug 时才使用 `[修复]`；**不要**在 `[Unreleased]` 内新增 `### 类目标题`
- `README.md` 只承载项目定位、核心能力、快速开始、主要入口、赞助/合作等首页级信息；非必要不更新 README，避免持续膨胀
- 更细的模块行为、页面交互、专题配置、排障说明、字段契约、实现语义和边界条件，优先更新对应 `docs/*.md`

### Step 4: 按改动面验证

按 `AGENTS.md` 的验证矩阵执行最接近的检查：

- 后端快速门槛：`uv run ./scripts/ci_gate.sh syntax` + `uv run ./scripts/ci_gate.sh flake8`（秒级，开发中默认用这个；本机必须带 `uv run`，否则 `python: command not found`）
- 后端完整门槛：`uv run ./scripts/ci_gate.sh`（= `all`，含全量离线测试；仅在交付前跑，耗时与判定基准见 `AGENTS.md` §10）
- 最低后端要求：`uv run python -m py_compile <changed_python_files>`
- 前端：`cd apps/dsa-web && npm ci && npm run lint && npm run build`
- 桌面端：先构建 Web，再构建桌面端

如无法完成完整验证，必须记录缺口、原因与潜在风险。

### Step 5: 更新 issue 分析文档

在 `.claude/reviews/issues/issue-<number>.md` 中补充：

```markdown
## Fix Implementation

**Date**: YYYY-MM-DD

### Changes Made

- 文件与改动点：

### Validation

- 已执行：
- 未执行：

### Risks

- 风险点：

### Rollback

- 回滚方式：
```

### Step 6: 交付说明

按 `AGENTS.md` §5 的交付六项写：改了什么 / 为什么这么改 / 验证情况 / 未验证项 / 风险点 / 回滚方式。

用户要求创建 PR 或整理 PR 描述时，PR title 按 `AGENTS.md` §1.1 的 `<类型>: <修改内容>` 格式给。

## 可自主执行

阅读与分析代码、应用与当前任务直接相关的最小修复、运行非破坏性的本地验证、更新本地 issue 分析文档，以及 [`../shared/baseline-sync.md`](../shared/baseline-sync.md) 允许的 fast-forward 同步。

其余操作（建分支、切分支、`git commit`、`git push`、创建 PR、在 issue 下回复或关闭）按同一份文件的确认边界——一律先问。

修完后收到 review 反馈要继续改时，走 skill `respond-to-review`。
