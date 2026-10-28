# Repository Claude Skills

- [verify](verify/SKILL.md)：真實 Web/API/CLI 使用者路徑驗收，ego-browser 畫面證據、隔離資料與功能地圖；紀錄見 `docs/verification.md`。

仓库级协作 skill，属版本库资产（`.gitignore` 只放行 `.claude/skills/`；`.claude/reviews/` 是本地分析产物）。

规则真源是仓库根目录 `AGENTS.md`，本目录的 skill 与它保持一致；治理关系（`CLAUDE.md` 的 `@AGENTS.md` import 写法、镜像文件、frontmatter、gitignore allowlist）由 `scripts/check_ai_assets.py` 确定性强制，细节见 `AGENTS.md` §2。

- 每个 `SKILL.md` 必须有 YAML frontmatter 的 `name` + `description`；缺了会退化成拿 H1 当描述、实务上不会被自动触发。
- `shared/` 存放被多个 skill 指向的共用规则，本身不是 skill（没有 `SKILL.md`，不会被扫描）。
