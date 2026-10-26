---
applyTo: "apps/dsa-web/**,apps/dsa-desktop/**,scripts/run-desktop.ps1,scripts/build-desktop*.ps1,scripts/build-*.sh,docs/desktop-package.md"
---

# Client Instructions

- Preserve the existing Vite + React web structure and Electron desktop runtime assumptions; reuse current API/state patterns instead of adding parallel client abstractions.
- If a change affects API fields, auth state, route behavior, Markdown/chart rendering, local backend startup, or report payloads, assess both Web and Desktop compatibility.
- Validate Web changes with `cd apps/dsa-web && npm ci && npm run lint && npm run build` when feasible.
- Validate Desktop changes by building Web first, then `apps/dsa-desktop`; if platform limits prevent full Electron validation, call out the exact risk in the final delivery.
- 等 CI 用 `gh-wait run <run-id> -R audichuang/daily_stock_analysis` 或 `gh-wait pr <PR 號> -R audichuang/daily_stock_analysis`（AGENTS.md §9）；以 `gh run list --branch <分支>` 找到 run，避免使用 `gh run watch`、`gh pr checks --watch` 或迴圈輪詢耗盡共用 API 額度。
