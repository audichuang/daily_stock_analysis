---
applyTo: "main.py,server.py,src/**/*.py,data_provider/**/*.py,api/**/*.py,bot/**/*.py,tests/**/*.py"
---

# Backend Instructions

- Preserve current pipeline boundaries and reuse existing services, repositories, schemas, and fallback logic instead of creating parallel paths.
- Changes touching config, CLI flags, schedule semantics, API behavior, auth, or report payloads must sync `.env.example` and assess Web/Desktop compatibility.
- Changes in `data_provider/` must preserve provider priority, normalization behavior, timeout/retry expectations, and graceful degradation.
- Use the fast gate `uv run ./scripts/ci_gate.sh syntax` + `uv run ./scripts/ci_gate.sh flake8` (seconds). Bare `./scripts/ci_gate.sh` is `all` and includes the full offline suite (duration varies by machine; see `tests/AGENTS.md`) — run that only before delivery. Otherwise run `uv run python -m py_compile` on changed files plus the closest deterministic tests.
- The `uv run` prefix is required locally: `ci_gate.sh` calls bare `python`, which this fork does not install globally (`python: command not found`). CI images do provide it.
- 等 CI 用 `gh-wait run <run-id> -R audichuang/daily_stock_analysis` 或 `gh-wait pr <PR 號> -R audichuang/daily_stock_analysis`（AGENTS.md §9）；以 `gh run list --branch <分支>` 找到 run，避免使用 `gh run watch`、`gh pr checks --watch` 或迴圈輪詢耗盡共用 API 額度。
- Do not let a single provider, notification channel, or optional integration failure break the main analysis flow unless the requirement explicitly demands fail-fast behavior.
