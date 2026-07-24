# AGENTS.md

本文件用于约束本仓库的默认开发流程，目标是减少重复沟通、减少返工，并让改动和当前项目结构保持一致。

如果本文件与仓库中的脚本、工作流、代码现状不一致，以实际可执行内容为准，并在相关改动中顺手修正文档，避免规则继续漂移。

## 1. 硬规则

- 遵循现有目录边界：
  - 后端逻辑优先放在 `src/`、`data_provider/`、`api/`、`bot/`
  - Web 前端改动在 `apps/dsa-web/`
  - 桌面端改动在 `apps/dsa-desktop/`
  - 部署与流水线改动在 `scripts/`、`.github/workflows/`、`docker/`
- 未经明确确认，不执行 `git commit`、`git tag`、`git push`。
- 同样需要先确认、不要默认执行的动作：安装或升级依赖（`uv pip install`、`npm install <pkg>`、改 `requirements.txt`）、删除文件或目录、改动 infra 与部署配置、跑全量离线测试（约 30+ 分钟，判定基准见 §10）。读代码、跑 §6 的快速门槛、生成分析文档属于可自主动作。
- commit message 使用英文，不添加 `Co-Authored-By`。
- 不写死密钥、账号、路径、模型名、端口或环境差异逻辑。
- 优先复用现有模块、配置入口、脚本和测试，不新增平行实现。
- 默认稳定性优先于“顺手优化”；非当前任务直接需要的重构、抽象和基础设施迁移一律克制。
- 新增配置项时，必须同步更新 `.env.example` 和相关文档。
- 涉及用户可见能力、CLI/API 行为、部署方式、通知方式、报告结构变化时，必须同步更新相关文档与 `docs/CHANGELOG.md`。
- 修改报告格式、报告渲染效果或 Web UI 界面时，PR 描述必须附受影响报告 / 页面截图；涉及前后差异时优先附前后对比，无法截图时说明原因与替代可视证据。
- Issue / PR 过程截图、审查截图、一次性验收截图和临时可视证据不得作为仓库文件合入；应放在 PR 描述、PR 评论、GitHub 附件、Actions artifact 或外部可访问证据链接中。产品长期文档确需保留的示意图除外，但文件名和文档语义必须脱离具体 issue / PR 编号。
- `docs/CHANGELOG.md` 的 `[Unreleased]` 段使用**扁平格式**：每条独立一行，格式为 `- [类型] 描述`，类型取值：`新功能`/`改进`/`修复`/`文档`/`测试`/`chore`；**禁止在 `[Unreleased]` 内新增 `### 类目标题`**，以减少并发 PR 的 merge 冲突。发版时由 maintainer 汇总整理成带标题的正式格式。
- `README.md` 只用于项目定位、核心能力总览、快速开始、主要入口、赞助/合作等首页级信息；非必要不更新 README，避免持续膨胀。
- 更细的模块行为、页面交互、专题配置、排障说明、字段契约、实现语义和边界条件，优先更新对应 `docs/*.md` 或专题文档，不写入 README。
- 变更中英双语文档之一时，需评估另一份是否需要同步；若未同步，交付说明里要写明原因。
- 注释、docstring、日志文案以清晰准确为准，不强制要求英文，但应与文件语境保持一致。

## 1.1 PR 标题规范（非阻断建议）

- 推荐使用 `<类型>: <修改内容>` 作为 PR 标题，例如 `fix: 修复大盘分析历史记录丢失`，优先类型为 `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci`。
- 标题应描述实际变更内容，建议不添加 `[codex]`、`codex`、`autocode`、`copilot` 或其他工具/agent 来源前缀。
- 该规范仅用于协作可读性与一致性提示，不应单独作为 review process blocker。

## 1.2 贡献质量底线

- 本仓库不接受以堆叠代码量、扩大 diff 面、补丁式响应 review 来替代真实设计收敛的 PR。
- 贡献质量以是否解决明确问题、是否最小化影响面、是否保持现有契约一致、是否覆盖真实风险路径为准；不以新增行数、文件数量、功能宣传或“看起来完整”为准。
- 请不要把本仓库当作低成本试验场、简历展示场或 contribution farming 场所。任何 PR 都必须证明作者理解当前系统契约，并完成基本自审、集成和验证。
- 使用 AI 辅助开发本身不是问题；问题是提交 AI 生成后未经人工语义审查、未验证、未收敛的代码。此类 PR 会按低质量提交处理。
- review 反馈后，不接受只在被指出的位置追加局部 patch；完整收敛程序见 skill `respond-to-review`。
- 如果一个 PR 在多轮 review 后仍持续出现同类契约漂移、重复 fallback、测试绕过真实风险层、PR body 与实际 diff 不一致等问题，维护者可以要求关闭重做，而不是继续逐点 review。

## 2. AI 协作资产治理

- `AGENTS.md` 是仓库内 AI 协作规则的唯一真源；`CLAUDE.md`（含模块级）只写一行 `@AGENTS.md` 做 import，`.github/copilot-instructions.md` 与 `.github/instructions/*.instructions.md` 是 GitHub Copilot / Coding Agent 的镜像或分层补充。**任一处与本文件冲突时，以 `AGENTS.md` 为准。**
- 上述文件的存在性、`@AGENTS.md` 写法、软链接禁令、skill frontmatter 与 `.gitignore` allowlist 已由 `scripts/check_ai_assets.py` 确定性强制（CI job `ai-governance`，阻断）；本文件不重述这些机械规则，改动治理资产后跑它即可：

```bash
uv run python scripts/check_ai_assets.py
```

- 仓库协作 skill 存放在 `.claude/skills/`（入库）；分析产物存放在 `.claude/reviews/`（默认本地产物，已 gitignore）。
- 根目录 `SKILL.md` 与 `docs/openclaw-skill-integration.md` 属于产品或外部集成说明，不是仓库协作规则真源。
- 若未来新增 `.agents/skills/` 或其他 agent 专用目录，必须先明确单一真源，再通过脚本或镜像同步；禁止手工长期维护多份同义内容。
- skill 内的命令、验证门槛与交付结构必须与本文件一致；改动 §6 验证门槛时要同步检查各 skill 的验证步骤。被多个 skill 共用的规则放 `.claude/skills/shared/`（不含 `SKILL.md`，因此不是 skill、不被扫描），各 skill 用相对路径指向，避免同一规则抄多份。

## 3. 仓库速览

- 项目定位：股票智能分析系统，覆盖 A 股、港股、美股、日股、韩股、台股。
- 主流程：抓取数据 -> 技术分析/新闻检索 -> LLM 分析 -> 生成报告 -> 通知推送。
- 关键入口：
  - `main.py`：分析任务主入口
  - `server.py`：FastAPI 服务入口
  - `apps/dsa-web/`：Web 前端（页面地图与前端约定见 `apps/dsa-web/AGENTS.md`）
  - `apps/dsa-desktop/`：Electron 桌面端
  - `.github/workflows/`：CI、发布、每日任务
- 核心职责（只列名字猜不到用途、或带额外契约的；**完整目录结构问 `tree` / codegraph，别依赖这份清单**）：
  - `src/`：`core/` 主流程编排、`services/` 业务服务、`repositories/` 数据访问三层；另有 `schemas/` 数据结构、`utils/` 通用工具、`data/` 股票索引与代码映射、`patches/` 三方库补丁
  - `src/notification_sender/`：通知渠道适配（飞书 / Discord / ntfy / 自定义 Webhook，含 Bark）；新增渠道需实现 `base.py` 的 `Sender` protocol 并在 `NotificationService._senders` 注册
  - `src/llm/`：LLM 生成后端、usage / provider 缓存，与 LLM transport 编排（`client.py::LLMClient`，backend fallback / 脱敏 / 流式；与 `GeminiAnalyzer` 的边界见该文件模块 docstring）
  - `src/agent/`：tool-calling agent（多轮对话、分歧检测、事件流），由 `AGENT_MODE=true` 启用；可插拔策略定义在根目录 `strategies/*.yaml`（见 `strategies/README.md`）
  - `data_provider/`：多数据源适配与 fallback
  - `market_data/`：台股行情爬取 → 统一 Postgres（market schema），细节见 `market_data/AGENTS.md`

## 4. 常用命令

> 常用任务已封装在根目录 `Makefile`（统一以 `uv run` 执行）：`make help` 列出全部；
> 常用如 `make serve` / `make review-tw` / `make analyze STOCKS=…` / `make test` / `make lint`。
> 以下为底层命令，CI（`ci_gate.sh`）与不使用 uv 的环境仍以此为准。
> **该跑哪个门槛见 §6**：本机开发默认用 §6 的快速门槛，不要默认跑这里的全量 `pytest`。

### 运行应用

```bash
python main.py
python main.py --debug
python main.py --dry-run
python main.py --stocks 600519,hk00700,AAPL
python main.py --market-review
python main.py --schedule
python main.py --serve
python main.py --serve-only
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### 后端验证

```bash
pip install -r requirements.txt
pip install flake8 pytest
./scripts/ci_gate.sh
python -m pytest -m "not network"
python -m py_compile <changed_python_files>
```

### Web / Desktop

```bash
cd apps/dsa-web
npm ci
npm run lint
npm run build

cd ../dsa-desktop
npm install
npm run build
```

### PR / CI 证据

```bash
gh pr view <pr_number>
gh pr checks <pr_number>
gh run view <run_id> --log-failed
```

## 5. 默认工作流

1. 判断任务类型：`fix / feat / refactor / docs / chore / test / review`。
2. 识别改动边界：后端 / API / Web / Desktop / Workflow / Docs / AI 协作资产。
3. 判断是否命中高风险区域：配置语义、API / Schema、数据源 fallback、报告结构、认证、调度、发布流程、桌面端启动链路——命中时按 §7 的护栏逐项确认。
4. 改完按 §6 验证矩阵执行检查。
5. 交付六项：
   - 改了什么
   - 为什么这么改
   - 验证情况
   - 未验证项
   - 风险点
   - 回滚方式

## 6. 验证矩阵

### CI 覆盖原则

当前仓库 CI 主要包含：

| 检查项 | 来源 | 说明 | 是否阻断 |
| --- | --- | --- | --- |
| `ai-governance` | `.github/workflows/ci.yml` | 校验 `AGENTS.md` / `CLAUDE.md` / `.github` 指令 / `.claude/skills` 关系 | 是 |
| `backend-gate` | `.github/workflows/ci.yml` | 执行 `./scripts/ci_gate.sh` | 是 |
| `docker-build` | `.github/workflows/ci.yml` | Docker 构建与关键模块导入 smoke | 是 |
| `web-gate` | `.github/workflows/ci.yml` | 前端改动时执行 `npm run lint` + `npm run build` | 是（触发时） |
| `network-smoke` | `.github/workflows/network-smoke.yml` | `pytest -m network` + `scripts/test.sh quick` | 否，观测项 |
| `pr-review` | `.github/workflows/pr-review.yml` | PR 静态检查 + AI 审查 + 自动标签 | 否，辅助项 |

若 PR 上已有对应 CI 结果，可直接引用 CI 结论；若 CI 未覆盖改动面，或本地与 CI 环境差异较大，需要补充说明本地验证与缺口。

### 按改动面执行

- Python 后端改动：
  - 适用范围：`main.py`、`src/`、`data_provider/`、`api/`、`bot/`、`tests/`
  - 快速门槛（开发中默认用这个）：`uv run ./scripts/ci_gate.sh syntax` + `uv run ./scripts/ci_gate.sh flake8`（实测 0.7s / 4s）。`ci_gate.sh` 接受 phase 参数 `all|syntax|flake8|deterministic|offline-tests`
  - **本机必须带 `uv run`**：脚本内部调用裸 `python`，本 fork 无全局 python，直接跑 `./scripts/ci_gate.sh` 会 `python: command not found`；CI 环境有 python，直跑无碍
  - 交付前完整门槛：`uv run ./scripts/ci_gate.sh`（不带参数 = `all`，第四阶段是 `pytest -m "not network"` 全量，约 30+ 分钟；回归判定基准见 §10）
  - 最低要求：`uv run python -m py_compile <changed_python_files>`
  - 若影响 API、任务编排、报告生成、通知发送、数据源 fallback、认证、调度，交付说明中要写明是否覆盖了对应路径。

- Web 前端改动：
  - 适用范围：`apps/dsa-web/`
  - 默认执行：`cd apps/dsa-web && npm ci && npm run lint && npm run build`
  - 若涉及 API 联调、路由、状态管理、Markdown/图表渲染或认证状态，交付说明中要明确说明联动面和未覆盖风险。

- 桌面端改动：
  - 适用范围：`apps/dsa-desktop/`、`scripts/run-desktop.ps1`、`scripts/build-desktop*.ps1`、`scripts/build-*.sh`、`docs/desktop-package.md`
  - 默认执行：先构建 Web，再构建桌面端
  - 如受平台限制未能完整验证，需要明确说明是否验证了 Web 构建产物、Electron 构建以及 Release 工作流影响。

- API / Schema / 认证联动改动：
  - 适用范围：`api/**`、`src/schemas/**`、`src/services/**`、`apps/dsa-web/**`、`apps/dsa-desktop/**`
  - 至少覆盖对应后端验证 + 受影响客户端构建验证。
  - 若涉及登录、Cookie、会话、轮询状态、字段增删或枚举变化，必须明确写出兼容性影响。

- 文档与治理文件改动：
  - 适用范围：`README.md`、`docs/**`、`AGENTS.md`、`.github/copilot-instructions.md`、`.github/instructions/**`、`.claude/skills/**`
  - 不强制代码测试。
  - 需确认命令、配置项、文件名、工作流名称与实际仓库一致。
  - 改动 AI 协作治理资产时，执行 `uv run python scripts/check_ai_assets.py`。

- 工作流 / 脚本 / Docker 改动：
  - 适用范围：`.github/**`、`scripts/**`、`docker/**`
  - 运行最接近改动面的本地验证。
  - 交付时说明影响了哪条流水线、发布路径或部署路径。
  - 若未执行 Docker / GitHub Actions 相关验证，明确说明原因与潜在风险。

- 网络或三方依赖相关改动：
  - 先跑离线或确定性检查。
  - 优先确认 timeout、retry、fallback、异常文案、降级路径是否仍然成立。
  - 若未执行在线验证，必须明确写出原因。

## 7. 稳定性护栏

- 配置与运行入口：
  - 修改 `.env` 语义、默认值、CLI 参数、服务启动方式、调度语义时，要同时评估本地运行、Docker、GitHub Actions、API、Web、Desktop 的影响。
  - 新配置优先做到“不配置也可运行，配置后增强能力”，避免叠加开关和互斥模式。

- 数据源与 fallback：
  - 修改 `data_provider/` 时，要关注数据源优先级、失败降级、字段标准化、缓存与超时策略。
  - 单一数据源失败不应拖垮整个分析流程，除非需求明确要求 fail-fast。

- API / Web / Desktop 兼容：
  - 改 API / Schema / 认证 / 报告载荷时，要同时检查后端、Web、Desktop 的兼容性。
  - 默认优先追加字段、保留旧字段或提供兼容层，避免无提示破坏现有客户端。

- 报告 / Prompt / 通知：
  - 修改报告结构、Prompt、提取器、通知模板、机器人链路时，要检查上游输入与下游消费方是否仍兼容。
  - 单一通知渠道失败不应拖垮整个分析主流程，除非需求明确要求 fail-fast。
  - 修改 `src/services/image_stock_extractor.py` 中 `EXTRACT_PROMPT` 时，要在 PR 描述中附完整最新 prompt。

- 工作流 / 发布 / 打包：
  - 修改自动 tag、Release、Docker 发布、日常分析或桌面端打包流程时，要评估触发条件、产物路径、权限边界和回滚方式。
  - 自动 tag 默认保持 opt-in：只有 commit title 含 `#patch`、`#minor`、`#major` 才触发版本号更新，除非需求明确要求改变发布策略。

## 8. Issue / PR / Skill 工作流

- issue 分析、PR 审查、issue 修复、review 反馈收敛已有对应 skill（`.claude/skills/`，靠 frontmatter `description` 自动触发；此处不逐一列名，以目录为准）。任务命中时优先按 skill 执行，产物保存到 `.claude/reviews/`。
- 开始 PR 创建 / 更新、PR 审查、issue 分析或修复前，先按 `.claude/skills/shared/baseline-sync.md` 同步基线；哪些 git 操作可自主、哪些必须先问，同样以该文件为准。
- PR 审查的维度顺序、合入阻断条件与 `fix` 类 PR 的四项要求在 skill `analyze-pr` 内；收到 review 反馈后的收敛程序在 skill `respond-to-review`。
- skill 默认优先读取 CI / 工作流证据，再决定是否补本地验证。

## 9. 交付与发布

- 默认交付结构见 §5 的交付六项（改了什么 / 为什么这么改 / 验证情况 / 未验证项 / 风险点 / 回滚方式）。
- 如果是 `docs` 任务，可直接写：`Docs only, tests not run`，但仍需说明是否核对了命令和文件名。
- 自动 tag 默认不触发，只有 commit title 包含 `#patch`、`#minor`、`#major` 才会触发版本号更新。
- 手动打 tag 必须使用 annotated tag。
- 用户可见变更优先通过 PR 合入，并补齐 label 与验证说明。

## 10. 本 fork 专属约定（与上游的增量）

> 本仓库是个人 fork（`audichuang/daily_stock_analysis`），**不并回上游**，可按本 fork 需要自由演进。以下是上游没有、且从代码/工具推断不出的约定与踩雷：

- **环境用 `uv`（不用 `python -m venv`）**：建环境 `uv venv --python 3.12`，依赖 `uv pip install -r requirements.txt`，执行一律 `uv run python …`。常用任务封装在根目录 `Makefile`（`make help`）。
- **台股（`.TW` 上市 / `.TWO` 上柜）是新增重点**：个股走 yfinance；支持 4~6 位代码（含 5~6 位 ETF）。
- **台股大盘复盘市场数据走 TWSE/TPEx 官方 OpenAPI（免 key）**：见 `data_provider/twse_fetcher.py`。涨跌家数仅上市口径（上柜无公开端点），成交额与三大法人为上市+上柜合计；`get_market_stats` 按 `purpose="market_review:<region>"` 路由（A 股统计源限 cn、TwseFetcher 限 tw）。
- **自动补全索引**：台股全量种子在 `scripts/stock_index_seeds/stock_list_tw.csv`（`make refresh-tw` 重建）。`.env` 的 `STOCK_INDEX_REMOTE_UPDATE_ENABLED` **必须保持 `false`**——否则运行时会从上游 GitHub 拉索引、覆盖掉本地台股/美股增量（`.env.example` 示例值是上游的 `true`，勿照抄）。
- **LLM 主模型用 DeepSeek**：`.env` 须**显式**设 `LITELLM_MODEL=deepseek/deepseek-chat`。否则当 shell 环境导出了 `GEMINI_API_KEY` 时，`load_dotenv` 不覆盖既有环境变量，自动推断会优先选 Gemini。
- **通知用 Bark，走 Doppler 注入**：`make serve` / `make review-tw` 用 `doppler run -p shioaji -c dev` 把 Doppler 的 `BARK_URL` 映射为 `CUSTOM_WEBHOOK_URLS`（`custom_webhook_sender.py` 自动识别 `api.day.app`），secret 不落地 `.env`。**`make analyze` 不含 Doppler 包装**——要 Bark 通知需手动包：`doppler run -p shioaji -c dev -- bash -c 'CUSTOM_WEBHOOK_URLS="$BARK_URL" uv run python main.py --stocks 2330.TW'`；非交易日需加 `--force-run`。
- **全量离线测试（`pytest -m "not network"`）约 30+ 分钟**，且 main 上存在少量既有失败与顺序敏感 flaky（单独跑绿、全量跑偶红）；回归判定用「相对 baseline 的差集」，不要求绝对全绿，也不要把全量当快速门槛（快速验证用受影响测试文件的子集）。
- **台股历史数据（行情/筹码/财报）统一在 Postgres（`market` schema），且为唯一数据源（无本地备份）**：`DATABASE_URL` 在 `.env`。台股日线优先走 `MarketDBFetcher`（本地 DB，priority=1），无数据 fallback yfinance。爬取/数据更新（含财报季更 `financials`）/踩雷见 `market_data/AGENTS.md`。
- **台股即时看板/走势用永丰 Shioaji**：`shioaji` 已列入 `requirements.txt`（不需手动安装）。真正的降级触发点是**缺金钥**（同走 Doppler `shioaji/dev` 的 `SHIOAJI_API_KEY`/`SHIOAJI_SECRET_KEY`）——此时**静默降级 yfinance**，看板照样出数据但已是延迟报价、名称变英文。实际踩过：症状是「能跑但数字不对劲」，不是报错，排查先确认金钥有没有注入。看板/批次行情/走势/fallback/Shioaji session 与 ts 时区、kbars 30 天上限等细节见 `docs/realtime-board.md`。
