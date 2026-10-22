# 基线同步

本文件是基线同步与 git 确认边界的单一真源，由 `.claude/skills/` 下多个 skill 指向；仓库整体规则真源是根目录 `AGENTS.md`。

PR 创建 / 更新、PR 审查、issue 分析与修复开始前都要先做一次，确保分析对象是最新基线而不是陈旧工作树。

```bash
git status --short
git fetch --all --prune
# 仅当工作区干净且当前分支可 fast-forward 时：
git pull --ff-only
```

- 工作区干净、且当前分支有可 fast-forward 的上游时，才接受 `git pull --ff-only` 的结果。
- 存在本地改动、冲突状态、未跟踪风险文件、无上游分支或无法 fast-forward 时，保持本地状态不动，改用已 fetch 的 `origin/develop`、PR head 或 GitHub diff 做分析。这种情况下不执行 `stash`、`reset` 或强制切分支。
- 在产出文档中记录三项：本地 HEAD、实际使用的远端基线、未更新本地工作树的原因（如有）。
- PR 创建 / 更新前，先说明当前分支与目标基线的差异；需要 rebase 或 merge 时请用户确认。

## git 寫操作的確認邊界

以 `AGENTS.md` §1 為準。可自主：fast-forward 同步、在本 fork 上 commit、建／切分支（不動有他人改動的工作樹）、push 工作分支、`gh pr create`、CI 綠後 merge 進 `develop`。先問：push 到別人的 repo（含上游）、`git tag`、發版。另外不要 `stash`／`reset` 掉本地既有改動（上面同步規則）。
