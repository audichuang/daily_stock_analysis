# AGENTS.md

本文件约束本仓库的默认开发流程。与脚本、工作流、代码现状不一致时，以实际可执行内容为准，并顺手修正文档。

## 1. 硬规则

- 目录边界：后端 `src/`、`data_provider/`、`api/`、`bot/`；Web `apps/dsa-web/`；桌面端 `apps/dsa-desktop/`；部署与流水线 `scripts/`、`.github/workflows/`、`docker/`。台股波段的每日决策日志在 `journal/`（append-only、**进版控**，见 `journal/README.md`）；`data/`、`reports/`、`logs/` 是 gitignore 的运行期目录，长期记录不要放那里。
- 未经明确确认，不执行 `git commit`、`git tag`、`git push`。例外只有两个排程，都只 commit＋push 自己写的 `journal/*.jsonl` 到 `develop`（让预测当天进版控）：平日 07:30 盘前判读（`morning-calls`、`swing-decisions`）、平日 23:00 媒体点名（`media-picks`）。
- 同样要先确认：安装或升级依赖（`uv pip install`、`npm install <pkg>`、改 `requirements.txt`）、删除文件或目录、改 infra 与部署配置、跑全量离线测试。读代码、跑 §6 快速门槛、生成分析文档可自主。
- commit message 用英文，不加 `Co-Authored-By`。
- 不写死密钥、账号、路径、模型名、端口或环境差异逻辑。
- 新增文件后确认 `git status` 看得到它：`.gitignore` 有 `verify_*.py`、`local/`、`run.sh` 这类宽 pattern，命中就**静默消失**，要保留就补 `!` 例外并注明理由（踩过：`scripts/verify_swing_decisions.py`）。
- 优先复用现有模块、配置入口、脚本和测试，不新增平行实现；非当前任务需要的重构、抽象、基础设施迁移一律克制。
- 新增配置项同步 `.env.example` 与相关文档；用户可见能力、CLI/API 行为、部署方式、通知方式、报告结构变化，同步相关文档与 `docs/CHANGELOG.md`。
- `docs/CHANGELOG.md` 的 `[Unreleased]` 段用**扁平格式**：每条一行 `- [类型] 描述`，类型取 `新功能`/`改进`/`修复`/`文档`/`测试`/`chore`；**禁止在 `[Unreleased]` 内新增 `### 类目标题`**。
- `README.md` 只放首页级信息（定位、能力总览、快速开始、入口）；模块行为、配置、排障、字段契约写进对应 `docs/*.md`。改中英双语文档之一时评估另一份，未同步要在交付说明写原因。
- 本 fork **新寫的**註解、提示詞、CHANGELOG 條目用繁體中文；既有簡體不必回頭改。

## 1.2 质量底线

- **新测试一律做 mutation 检查**：把修法改回旧写法，测试必须立刻红；同时补**反向**检查（把修法改得过头也要红）。实测抓到过三次假守门（mock 让函式提前 return、少一个 phase 的断言、漏掉另一个测试档的同一 guard）。
- 研究／回测类结论（超额、Sharpe、命中率、偏误上界）写进文档前要过一轮对抗审查；**区间跨零或样本量不足一律写 inconclusive**。被推翻的数字在原处标作废。

## 2. AI 协作资产治理

- `AGENTS.md` 是 AI 协作规则唯一真源；`CLAUDE.md`（含模块级）只写一行 `@AGENTS.md`；`.github/copilot-instructions.md` 与 `.github/instructions/*.instructions.md` 是镜像，冲突时以本文件为准。机械规则由 `scripts/check_ai_assets.py` 强制（CI `ai-governance`），改治理资产后跑 `uv run python scripts/check_ai_assets.py`。
- 协作 skill 在 `.claude/skills/`（入库，多个 skill 共用的规则放 `.claude/skills/shared/`）；分析产物在 `.claude/reviews/`（gitignore）——**长期结论必须沉淀到 `docs/*.md`**。根目录 `SKILL.md` 与 `docs/openclaw-skill-integration.md` 是产品说明，不是协作规则。改 §6 门槛时同步检查各 skill 的验证步骤。

## 3. 仓库速览

完整结构问 `tree`／codegraph。`market_data/` 是台股行情爬取 → Postgres `market` schema（细节见 `market_data/AGENTS.md`）。台股分析现况（抓哪些数据、哪些护栏会改掉 LLM 结论、开关与建议值、已经研究过不要重做的问题）先读 `docs/tw-analysis-overview.md`；文件导航见 `docs/INDEX.md` 的「台股（本 fork）」，当天快照式的研究纪录放 `docs/research/`。

## 4. 常用命令

指令清单看 `make help`、`main.py --help`、`package.json`。只记一个坑：`setup.cfg` 的 addopts 带 `--timeout`，缺 `pytest-timeout` plugin 时 pytest 直接中止、讯息看不出原因；测试工具相依在 `.github/requirements-ci.txt`。

## 5. 交付

- 命中高风险区域（配置语义、API／Schema、数据源 fallback、报告结构、认证、调度、发布流程、桌面端启动链路）时按 §7 逐项确认。
- 交付六项：改了什么 / 为什么这么改 / 验证情况 / 未验证项 / 风险点 / 回滚方式。`docs` 任务可写 `Docs only, tests not run`，但要说明是否核对了命令和文件名。

## 6. 验证矩阵

### CI

- CI 只由 push 触发（`ci.yml` 的 `on:`），PR 上的 checks 就是工作分支那次 push run：**工作分支前缀不在 `on:` 清单内就没有 CI**。
- **本机 `ci_gate.sh` 与 CI 不等价**：相依安装只有 CI 装得起来才算数；CI 的 backend-tests 跑 **Python 3.11**、本机 venv 是 3.12，3.12-only 语法（PEP 701 同引号巢状 f-string）本机永远剖析得过。`tests/test_python_version_compat.py` 挡这个，但本机借不到 CI 版本时它是 **skip 不是 fail**。

### 按改动面

- Python 后端（`main.py`、`src/`、`data_provider/`、`api/`、`bot/`、`tests/`）：
  - 快速门槛（开发中默认）：`uv run ./scripts/ci_gate.sh syntax` + `uv run ./scripts/ci_gate.sh flake8`；phase 参数 `all|syntax|flake8|deterministic|offline-tests`。
  - **本机必须带 `uv run`**：脚本内部调用裸 `python`，本 fork 无全局 python（`python: command not found`）。
  - 交付前完整门槛：`uv run ./scripts/ci_gate.sh`（＝`all`，含 `pytest -m "not network"` 全量，需先确认）；最低要求 `uv run python -m py_compile <changed_files>`。
- Web（`apps/dsa-web/`）：`cd apps/dsa-web && npm ci && npm run lint && npm run build`。
- 桌面端：先构建 Web 再构建桌面端。API／Schema／认证联动：后端验证 + 受影响客户端构建，并写明兼容性影响。
- 文档与治理文件：不强制代码测试，但要核对命令、文件名、工作流名称与仓库一致。工作流／脚本／Docker：跑最接近的本地验证，说明影响哪条流水线或部署路径。
- 没跑到的（平台限制、在线验证、Docker／Actions）在交付说明写原因。

## 7. 稳定性护栏

- 改 `.env` 语义、默认值、CLI 参数、服务启动或调度语义时，评估本地、Docker、GitHub Actions、API、Web、Desktop；新配置做到"不配置也可运行"。
- 单一数据源或通知渠道失败不拖垮整个分析流程（除非需求要求 fail-fast）。改 API／报告载荷优先追加字段、保留旧字段。

## 8. Skill 工作流

任务命中 `.claude/skills/` 的 skill 时优先按 skill 执行（靠 frontmatter `description` 触发）。开始 PR 创建／更新、PR 审查、issue 分析或修复前，先按 `.claude/skills/shared/baseline-sync.md` 同步基线。

## 9. 合入与发布

- 分支模型：工作分支 → PR 合进 **`develop`**（GitHub 预设分支，日常整合）；`main` 只代表已发版。推工作分支后用 `gh run list --branch <分支>`／`gh run watch` 确认 CI 绿，经使用者确认再合进 `develop`；交付说明引用那次 run。
- 发版：`develop` fast-forward 进 `main`、push `main`，再在 `main` 上打 annotated tag `rel-YYYY.MM.DD`（同日第二版加 `.2`）并 push tag，`ghcr-main.yml` 依 tag 建映像。不用 `v*.*.*`——那是上游的版号，会触发上游的 release／Docker Hub／桌面端 workflow。
- 打 tag 只建映像，不会部署到 NAS；部署流程见 `docs/nas-deploy.md`。

## 10. 本 fork 专属约定

> 个人 fork（`audichuang/daily_stock_analysis`），**不并回上游**。以下是从代码推断不出、任何任务都可能踩到的约定：

- **环境用 `uv`**：`uv venv --python 3.12`、`uv pip install -r requirements.txt`，执行一律 `uv run python …`。
- **origin 的 fetch refspec 在本机 checkout 只抓 `main` 与 `develop`**，`origin/<其他分支>` 一律不存在：看远端分支用 `git ls-remote` 或 `git fetch origin <分支>`（`FETCH_HEAD`）。同步上游走 skill `dsa-upstream-sync`（merge，不 rebase）。
- **台股代码必须带 `.TW`（上市）／`.TWO`（上柜）后缀**（裸 `2330` 不进台股语义），代码是 4~6 位数字加至多一个大写字母（`00631L`、`2887A`）。这条格式**没有单一来源**，前后端、报告渲染、索引种子脚本各有一份正则；语意真源是 `src/services/market_symbol_utils.py`，改一处要全扫（踩过：`00631L` 搜不到、海报印成 `00631`）。
- **TWSE/TPEx 官方端点会停止更新却照样回 200**（实测冻结 79 天）：消费端一律比对回应自带的日期，拿不到参照就拒收。
- **`.env` 的 `STOCK_INDEX_REMOTE_UPDATE_ENABLED` 必须保持 `false`**，否则运行时会从上游拉索引、覆盖本地台股／美股增量（`.env.example` 是上游的 `true`，勿照抄）。台股索引用 `make refresh-tw` 重建。
- **个股分析与大盘复盘走本机 Claude Code CLI**（`GENERATION_BACKEND=claude_code_cli`、`GENERATION_FALLBACK_BACKEND=` 留空），不需 API key；LiteLLM 那条在本机没有可用 key。要改回 LiteLLM 时 `.env` 须显式设 `LITELLM_MODEL`：否则 shell 导出了 `GEMINI_API_KEY` 时 `load_dotenv` 不覆盖既有变量，自动推断会选 Gemini。推理模型回空时的槓桿也是换 `LITELLM_MODEL`，不是加 token 预算（见 `src/AGENTS.md`）。
- **Bark 与台股新闻 token 走 Doppler 注入**，secret 不落地 `.env`：`make serve`／`make review-tw`／`make daily-report` 已包好；**`make analyze` 不含**——少了它不报错，只会没 Bark、台股新闻退回通用搜寻（手动包法见 `docs/tw-operating-guide.md` §2.3）。Shioaji 金钥同走 Doppler，缺了即时报价静默降级 yfinance（讯号是 `source` 变 `fallback`）。
- **应用库（分析历史、回测、决策信号、LLM 用量）是 Postgres `dsa` schema（`.env` 的 `STORAGE_DATABASE_URL`），本机报告与 NAS 正式 Web 共用**——写进去就是写正式资料。`data/stock_analysis.db` 已冻结，读它只会静默拿到旧数据。临时脚本要隔离正式库就把 `STORAGE_DATABASE_URL` 设成空字串（pytest 由 `tests/conftest.py` 守；LiteLLM import 时补回 `.env` 的坑由 `src/__init__.py` 的 `LITELLM_MODE=PRODUCTION` 守，只在经 `src` import 时生效）。
- **台股历史数据（行情／筹码／财报）在 Postgres `market` schema（`.env` 的 `DATABASE_URL`），是唯一数据源、无备份**。
- **Web 服务正式跑在 NAS**：本机 launchd `com.audichuang.dsa` 已 disable，不要重新启用（两边会同时登入 Shioaji、共用应用库）。本机排程（07:30 盘前、08:30 上游同步、18:00 每日报告、持股检查）与每日报告的逾时／锁／完成标记见 `docs/daily-report-ops.md`。
- **新增会在 serve 路径被 import 的顶层 package／资料夹，要同步 `docker/Dockerfile` 的 COPY**：惰性 import 让容器里才 `ModuleNotFoundError`，且呼叫端多半静默退回别的数据源（踩过：`market_data/`）。
- **`--help` 不是安全探针**：`scripts/` 底下有脚本没有 argparse，`main()` 直接做事（`merge_tw_into_index.py` 改写进版控的索引、`migrate_sqlite_to_pg.py` 对 `market` schema `TRUNCATE`）。要探能不能跑，先 `grep -c argparse`。
- **全量离线测试应该全绿**；红了先排除假红（负载、连外、`.env` 漏入、真实时段）再判回归，判别法在 `tests/AGENTS.md`。**跑全量期间不要改档**（pytest 收集期就 import 完模组，边跑边改验的是混合状态），也别和 vitest 全量并行。
