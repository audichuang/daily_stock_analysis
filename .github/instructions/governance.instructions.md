---
applyTo: "README.md,docs/**,AGENTS.md,CLAUDE.md,.github/**,.claude/skills/**,scripts/**,docker/**"
---

# Governance Instructions

- Keep commands, file paths, workflow names, config keys, release paths, and directory references aligned with the executable repository state.
- `AGENTS.md` is the canonical AI collaboration document; if its meaning changes, sync `CLAUDE.md`, `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`, and repository skills as needed.
- Root `SKILL.md` and `docs/openclaw-skill-integration.md` describe product or external integration behavior, not repository governance.
- Explain which pipeline, release path, deployment path, review automation, or governance asset is affected and what the rollback path is.
- 等待 CI 使用 `gh-wait run <run-id> -R owner/repo` 或 `gh-wait pr <number> -R owner/repo`；ETag 條件請求讓狀態未變時不扣共用 GitHub API 額度（`AGENTS.md` §9）。
- Before creating/updating PRs, PR review, or issue analysis, refresh the latest code baseline with `git fetch --all --prune`; only run `git pull --ff-only` when the worktree is clean and the current branch can fast-forward. If not, keep local state intact and record the fetched remote baseline or branch gap before proceeding. The full rules — including which git operations may run autonomously and which need confirmation — live in `.claude/skills/shared/baseline-sync.md`.
- Keep `README.md` limited to homepage-level content such as positioning, high-level capabilities, quick start, main entrypoints, and sponsorship/cooperation; put detailed behavior, configuration, troubleshooting, field contracts, and edge cases in `docs/*.md`.
- Avoid widening permissions, secret exposure, or destructive automation without a clearly documented need.
- Keep `auto-tag.yml` disabled on GitHub: this fork tags releases as `rel-YYYY.MM.DD` (`AGENTS.md` §9), and a `v*` tag triggers upstream's release, Docker Hub and desktop workflows (`.github/workflows/AGENTS.md`).
- When creating, reviewing, or suggesting PRs, prefer PR titles in `<type>: <change summary>` form and omit tool/agent source prefixes such as `[codex]`, `codex`, `autocode`, or `copilot`; treat this as non-blocking guidance, not a review hard blocker.
- If only one language version of a document is updated, explain why the counterpart was not synchronized.
