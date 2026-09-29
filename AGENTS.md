# AGENTS.md

本文件用于约束本仓库的默认开发流程，目标是减少重复沟通、减少返工，并让改动和当前项目结构保持一致。

如果本文件与仓库中的脚本、工作流、代码现状不一致，以实际可执行内容为准，并在相关改动中顺手修正文档，避免规则继续漂移。

## 1. 硬规则

- 遵循现有目录边界：
  - 后端逻辑优先放在 `src/`、`data_provider/`、`api/`、`bot/`
  - Web 前端改动在 `apps/dsa-web/`
  - 桌面端改动在 `apps/dsa-desktop/`
  - 部署与流水线改动在 `scripts/`、`.github/workflows/`、`docker/`
  - 台股波段流程的每日决策日志在 `journal/`（append-only、**进版控**，见 `journal/README.md`）；`data/`、`reports/`、`logs/` 都是 gitignore 的运行期目录，长期记录不要放那里
- 未经明确确认，不执行 `git commit`、`git tag`、`git push`。
- 同样需要先确认、不要默认执行的动作：安装或升级依赖（`uv pip install`、`npm install <pkg>`、改 `requirements.txt`）、删除文件或目录、改动 infra 与部署配置、跑全量离线测试（耗时与判定基准见 §10）。读代码、跑 §6 的快速门槛、生成分析文档属于可自主动作。
- commit message 使用英文，不添加 `Co-Authored-By`。
- 不写死密钥、账号、路径、模型名、端口或环境差异逻辑。
- 新增文件后确认 `git status` 看得到它：`.gitignore` 有 `verify_*.py`、`local/`、`run.sh` 这类宽 pattern，命中就**静默消失**（写入成功、不报错、CI 也不会说），要保留就补 `!` 例外并注明理由。踩过：`scripts/verify_swing_decisions.py` 命中 `verify_*.py`，差点没进版本库。
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
- **新测试一律做 mutation 检查**：把修法改回旧写法，测试必须立刻红；没红就是它在为别的理由通过，不算守门。同时补**反向**检查（把修法改得过头也要红），否则「只擋了正確的一半」看不出来。实测这一条抓到过三次假守门：mock 的 quote 少给 `price` 让函式提前 return、少一个 phase 的断言让过度封锁照样绿、只跑受影响档案漏掉同一 guard 在另一个测试档的另一种 mock。
- 如果一个 PR 在多轮 review 后仍持续出现同类契约漂移、重复 fallback、测试绕过真实风险层、PR body 与实际 diff 不一致等问题，维护者可以要求关闭重做，而不是继续逐点 review。
- 研究／回测类结论（超额、Sharpe、命中率、偏误上界）在写进文档前要过一轮对抗审查；**区间跨零或样本量不足时一律写 inconclusive**，不写方向性结论。被推翻的数字要在原处标明作废，不留两个版本各自流通——2026-07 的三轮审查各推翻一个 headline，其中一次把「与 0050 打平」变成「输给 0050」。

## 2. AI 协作资产治理

- `AGENTS.md` 是仓库内 AI 协作规则的唯一真源；`CLAUDE.md`（含模块级）只写一行 `@AGENTS.md` 做 import，`.github/copilot-instructions.md` 与 `.github/instructions/*.instructions.md` 是 GitHub Copilot / Coding Agent 的镜像或分层补充。**任一处与本文件冲突时，以 `AGENTS.md` 为准。**
- 上述文件的存在性、`@AGENTS.md` 写法、软链接禁令、skill frontmatter 与 `.gitignore` allowlist 已由 `scripts/check_ai_assets.py` 确定性强制（CI job `ai-governance`，阻断）；本文件不重述这些机械规则，改动治理资产后跑它即可：

```bash
uv run python scripts/check_ai_assets.py
```

- 仓库协作 skill 存放在 `.claude/skills/`（入库）；分析产物存放在 `.claude/reviews/`（默认本地产物，已 gitignore）——**长期结论必须沉澱到 `docs/*.md`**，留在 `.claude/reviews/` 等于没有交接。
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
  - `src/agent/`：tool-calling agent（多轮对话、分歧检测、事件流），由 `AGENT_MODE=true` 启用；可插拔策略定义在根目录 `strategies/*.yaml`（见 `strategies/README.md`）。多策略审议/合成/调度（`skills/deliberation|synthesis|scheduler|engine`）的证据契约与字段语义在 `docs/multi-strategy-contract.md`；问股后端由 `AGENT_BACKEND` 选择（`auto` 走 LiteLLM 路径，`codex_app_server` 走本机 Codex）
  - `data_provider/`：多数据源适配与 fallback；台股各类资料走哪条路、哪些约束不能动见 `data_provider/AGENTS.md`，**实时报价的市场覆盖、代码格式与指数代码的坑**见 `docs/realtime-board.md`
  - `market_data/`：台股行情爬取 → 统一 Postgres（market schema），细节见 `market_data/AGENTS.md`

## 4. 常用命令

指令清单不写在这里——`make help`、`main.py --help`、`package.json` 都拿得到，抄一份只会漂移。
**该跑哪个验证门槛见 §6**（本机默认跑快速门槛，不要默认跑全量 `pytest`）。

只记一个装不起来就整个中止、而且讯息看不出原因的坑：

```bash
pip install flake8 pytest pytest-timeout   # setup.cfg 的 addopts 带 --timeout，缺 plugin 直接中止
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

**阻断 job 只在「对 `main` 开 PR」时触发**（`ci.yml` 的 `on:` 只有 `pull_request`、**没有 `push`**），
所以**直接 push 到 `main` 的改动一次阻断 CI 都没跑过**。要在合入前验到，唯一的办法是开一个
base=main 的 PR；走直接 merge 就要自己承担这个缺口并在交付说明写明。

**当前有哪些 job、哪些阻断，一律以 `gh pr checks <pr>` 为准**——上游会改（2026-08 就把
`backend-gate` 拆成三个分片 job），这里列一份清单只会漂移。两个非阻断项**不跟着 PR 跑**：
`network-smoke`（排程，平日 02:00 UTC + 手动）与 `pr-review`（纯手动 `workflow_dispatch`，要传 `pr_number`）。

**本机 `ci_gate.sh` 与 CI 不等价**，两处差异都会让本机全绿而 CI 红：
- 相依安装只有 CI 装得起来才算数
- **CI 的 backend-tests 跑 Python 3.11，本机 venv 是 3.12**（§10）。3.12-only 语法（PEP 701 的同引号巢状
  f-string）在本机永远剖析得过——`scripts/screen_tw.py` 因此在 main 上坏了很久没人发现。已由
  `tests/test_python_version_compat.py` 挡住（它从 `ci.yml` 读版本，不写死）；但本机借不到那个版本时
  它是 **skip 不是 fail**，本机看到它绿不等于 3.11 已经剖析过。

若 PR 上已有对应 CI 结果，可直接引用 CI 结论；若 CI 未覆盖改动面，需要补充说明本地验证与缺口。

### 按改动面执行

- Python 后端改动：
  - 适用范围：`main.py`、`src/`、`data_provider/`、`api/`、`bot/`、`tests/`
  - 快速门槛（开发中默认用这个）：`uv run ./scripts/ci_gate.sh syntax` + `uv run ./scripts/ci_gate.sh flake8`（实测 0.7s / 4s）。`ci_gate.sh` 接受 phase 参数 `all|syntax|flake8|deterministic|offline-tests`
  - **本机必须带 `uv run`**：脚本内部调用裸 `python`，本 fork 无全局 python，直接跑 `./scripts/ci_gate.sh` 会 `python: command not found`；CI 环境有 python，直跑无碍
  - 交付前完整门槛：`uv run ./scripts/ci_gate.sh`（不带参数 = `all`，第四阶段是 `pytest -m "not network"` 全量；耗时与回归判定基准见 §10）
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

- **`gh pr create` 在 fork 里预设把 PR 开到上游**（`ZhuLinsen/daily_stock_analysis`）——与本节第一句「不并回上游」正好相反，而且它不会问你。先 `gh repo set-default audichuang/daily_stock_analysis`，或每次带 `--repo`。踩过：第一次开 PR 直接被上游 repo 接走，靠报错才发现。
- **同步上游用 merge、不用 rebase**（fork 已 push 上百个自有 commit，rebase 等于全部改写、只能 force push）；每轮以最近一份 `docs/upstream-sync-*.md` 为模板写纪录。其中**静默降级排查**不能省：上游新增的市场集合／语言集合常数，逐个问「涵盖 `tw` 吗？涵盖 `zh-TW` 吗？」——漏掉不会报错，台股／繁中路径只会安静地被跳过或退回简体。
- **环境用 `uv`（不用 `python -m venv`）**：建环境 `uv venv --python 3.12`，依赖 `uv pip install -r requirements.txt`，执行一律 `uv run python …`。常用任务封装在根目录 `Makefile`（`make help`）。
- **台股（`.TW` 上市 / `.TWO` 上柜）是新增重点**：必须带后缀（裸 `2330` 不进台股语义）；代码是 4~6 位数字加至多一个大写字母（`00631L`、`2887A`）。
- **TWSE/TPEx 官方端点会停止更新却照样回 200**（2026-08 实测涨跌家数端点冻结 79 天，连续 20 份复盘印同一组数字）。消费端一律比对回应自带的日期，拿不到参照就拒收——无法证明新鲜的数字不如没有数字。
- **自动补全索引**：台股全量种子在 `scripts/stock_index_seeds/stock_list_tw.csv`（`make refresh-tw` 重建）。`.env` 的 `STOCK_INDEX_REMOTE_UPDATE_ENABLED` **必须保持 `false`**——否则运行时会从上游 GitHub 拉索引、覆盖掉本地台股/美股增量（`.env.example` 示例值是上游的 `true`，勿照抄）。
- **LLM 主模型用 DeepSeek，且 `.env` 须显式设 `LITELLM_MODEL`**：否则当 shell 环境导出了 `GEMINI_API_KEY` 时，`load_dotenv` 不覆盖既有环境变量，自动推断会优先选 Gemini。**模型名以 `.env` 现值为准**（DeepSeek 停用过 `deepseek-chat`，写死在这里只会再过时一次）。
- **推理模型的 token 预算会静默吃掉整个回应**：`deepseek-v4-flash` 这类会把预算花在推理上，内容为空而 `finish_reason=length`，症状是随机「分析未成功」，**台股美股都会中**。**加预算不是可用的槓桿**——个股分析的 `max_output_tokens` 由 `analyzer.analyze()` 写死 8192，`LLM_MAX_TOKENS` 只有选股 pipeline 读得到；实测 8192 下仍约 1/3 回空。要修就换 `LITELLM_MODEL`。
- **通知用 Bark，走 Doppler 注入**：`make serve` / `make review-tw` 用 `doppler run -p shioaji -c dev` 把 Doppler 的 `BARK_URL` 映射为 `CUSTOM_WEBHOOK_URLS`（`custom_webhook_sender.py` 自动识别 `api.day.app`），secret 不落地 `.env`。**`make analyze` 不含 Doppler 包装**——要 Bark 通知需手动包：`doppler run -p shioaji -c dev -- bash -c 'CUSTOM_WEBHOOK_URLS="$BARK_URL" uv run python main.py --stocks 2330.TW'`；非交易日需加 `--force-run`。
- **全量离线测试（`uv run ./scripts/ci_gate.sh`，第四阶段 `pytest -m "not network"`）应该全绿**。耗时依机器差十几倍（实测：这台 Mac 2026-09-29 约 4 分钟、2026-09-20 另一台机器 56 分钟，测试数相当、都是单行程），别拿一个数字估另一台。别把全量当快速门槛（快速验证用受影响测试文件的子集）。
- **红了先排除四种假红，再判回归**——它们看起来跟回归一模一样：墙钟负载、离线测试连外、本机 `.env` 漏进 `os.environ`、测试吃到真实时段。第一步都是**把红的那个档单独在空机器上重跑**；每一种的特征与判别法在 `tests/AGENTS.md`。排除之后还红，就是回归，不要当 baseline 噪音放过。
- **别把两个重活并行跑**（pytest 全量 + vitest 全量）：实测 vitest 从 15 failed 变 143 failed，全部是 timeout，两份结果同时被污染。
- **「离线」测试其实会连外，是这个 repo 最贵的一类坑**（踩过一次挂 6 小时 21 分，只烧 30 秒 CPU）。止血已就位：单测有 timeout（直接打 `pytest` 是 `setup.cfg` 的 300 秒，经 `ci_gate.sh` 是 120 秒），会让它红在那个测试上并印出堆叠。另外 LiteLLM 在 import 时会去 `raw.githubusercontent.com` 抓 model cost map（有本地 fallback，不会挂）。
- **跑全量期间不要改档**：pytest 在收集期就 import 完模组，边跑边改等于验一个混合状态——踩过：改了常数之后那份「全绿」其实验的是旧值，结论作废、得整轮重跑。要改就等它跑完。
- **本机 `make serve`（port 7777）由 launchd `com.audichuang.dsa` 常驻，不要手动再起一份**：会和它抢 port，`address already in use` 后自己退出。直接改 `.env` 后要重启才生效，用 `launchctl kickstart -k gui/$(id -u)/com.audichuang.dsa`；只 kill 不可靠——plist 设 `KeepAlive.SuccessfulExit=false`，正常退出（exit 0）时 launchd 不会重拉。日志在 `logs/launchd.{out,err}.log`。
- **`--help` 不是安全探针**：`scripts/` 底下有脚本**没有 argparse**，`main()` 直接做事、把参数忽略或当成路径——`merge_tw_into_index.py` 会改写进版控的索引，`migrate_sqlite_to_pg.py` 会对 `market` schema 做 `TRUNCATE`。拿 `--help` 扫一遍会**真的执行它们**（踩过：一次扫描重写了进版控的 `stocks.index.json`）。要探能不能跑，先 `grep -c argparse`。
- **台股历史数据（行情/筹码/财报）统一在 Postgres（`market` schema），且为唯一数据源（无本地备份）**：`DATABASE_URL` 在 `.env`。爬取/数据更新（含财报季更 `financials`）/踩雷见 `market_data/AGENTS.md`。
- **台股即时看板/走势用永丰 Shioaji，缺金钥时静默降级 yfinance**（金钥同走 Doppler `shioaji/dev`）：看板照样出数据但已是延迟报价，症状是「能跑但数字不对劲」，不是报错，排查先确认金钥有没有注入。可辨识的降级信号是 `source` 由 `shioaji` 变 `fallback`；细节见 `docs/realtime-board.md`。
