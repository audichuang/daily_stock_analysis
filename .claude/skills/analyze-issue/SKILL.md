---
name: analyze-issue
description: 判断一个 GitHub Issue 是否成立、属不属于本仓库责任边界、值不值得处理。当用户要分析某个 issue 或决定要不要修它时使用。
---

# Analyze Issue

分析 GitHub Issue，判断其真实性、优先级、仓库责任边界与建议动作。

**Repository**：本 fork（`gh repo set-default --view`）。下方指令不帶 `--repo`，由 gh 的預設 repo 解析。

## Usage

```text
/analyze-issue <issue_number>
```

## Instructions

分析时使用简洁中文，优先遵循仓库根目录 `AGENTS.md`。

### Step 1: 同步基线

按 [`../shared/baseline-sync.md`](../shared/baseline-sync.md) 执行，并把结果记进输出文档的 `Evidence`。

### Step 2: 拉取 Issue 信息

```bash
gh issue view <issue_number>
gh issue view <issue_number> --comments
```

如为 bug，优先核对 issue 模板中是否提供了以下信息：

- 是否已同步到最新版本
- commit hash / 版本基线
- 运行环境与复现步骤
- 日志或报错信息

### Step 3: 回答 4 个核心问题

1. 版本是否明确
2. 问题是否真实且可验证
3. 是否属于仓库责任边界
4. 是否值得立即处理

### Step 4: 结合仓库现状做证据检查

- 阅读相关代码、配置、测试、脚本、工作流与文档
- 如果问题涉及 API、数据源 fallback、报告生成、通知发送、认证、iOS App、发布流程，明确写出影响面
- 判断是实际 bug、环境配置问题、使用方式问题、还是外部依赖问题
- 如怀疑已被修复，检查当前代码而不是只看 issue 描述

### Step 5: 形成结论

至少给出以下字段：

- `版本基线`：最新 / 非最新 / 未提供
- `是否合理`：是/否 + 理由
- `是否是 issue`：是/否 + 理由
- `是否好解决`：是/否 + 难点
- `结论`：`成立 / 部分成立 / 不成立`
- `分类`：`bug / feature / docs / question / external`
- `优先级`：`P0 / P1 / P2 / P3`
- `难度`：`easy / medium / hard`
- `建议动作`：`立即修复 / 排期修复 / 文档澄清 / 关闭`

### Step 6: 生成分析文档

保存到 `.claude/reviews/issues/issue-<number>.md`

## Output Document Format

```markdown
# Issue #<number> Analysis

**Date**: YYYY-MM-DD
**Status**: Pending Review

## Summary

- 版本基线：
- 是否合理：
- 是否是 issue：
- 是否好解决：
- 结论：
- 分类：
- 优先级：
- 难度：
- 建议动作：

## Evidence

- 代码同步基线：
- 关键 issue 信息：
- 关键代码/脚本/工作流证据：

## Impact Scope

- 受影响模块：
- 受影响运行路径（本地 / Docker / GitHub Actions / API / Web / iOS）：

## Root Cause / Main Reasoning

<根因或主要判断依据>

## Proposed Handling

<建议修复、澄清或关闭方式>

若建议后续创建 PR，给出的 PR title 建议符合 `.github/copilot-instructions.md`：使用 `<类型>: <修改内容>`，不添加 `[codex]`、`codex`、`autocode`、`copilot` 或其他工具/agent 来源前缀；该约定仅用于协作一致性提醒，不应单独作为 review process blocker。

## Risks And Rollback

- 风险点：
- 若修复，回滚方式：

## Draft Reply

<建议回复内容>
```

## 可自主执行

拉取 issue 详情与评论、阅读代码 / 配置 / 脚本 / 工作流 / 文档、生成分析文档，以及 [`../shared/baseline-sync.md`](../shared/baseline-sync.md) 允许的 fast-forward 同步。

改变远端状态或扩大范围的操作（增删标签、在 issue 下评论、关闭 issue、开始动手修复）一律先问——同一份文件的确认边界。开始修复走 skill `fix-issue`。
