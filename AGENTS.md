# AGENTS.md

本文件只放全 repo 都適用、或由「動作」而非「路徑」觸發的規則。與腳本、工作流、程式現狀不一致時，以實際可執行內容為準，並順手修正文件。

## 1. 硬規則

- 台股波段的每日决策日志在 `journal/`（append-only、**进版控**，见 `journal/README.md`）；`data/`、`reports/`、`logs/` 是 gitignore 的运行期目录，长期记录不要放那里。
- `git commit`，以及 push 到自己的 `origin`（`audichuang/daily_stock_analysis`）的工作分支或 `develop`，不用再问，做完就提交推送；开 PR、CI 绿后合进 `develop` 也直接做（§9）。只有三件会公开或难以撤回的事要先确认：推到别人的上游（`upstream` = ZhuLinsen）、`git tag`、发版（push `main` 与`docs/nas-deploy.md` 的发版流程）。排程照旧自动 commit＋push 自己写的 `journal/*.jsonl` 到 `develop`；推哪些檔、何時推見 `docs/daily-report-ops.md`。
- 同样要先确认：安装或升级依赖（含改 manifest）、删除文件或目录、改 infra 与部署配置、跑全量离线测试。读代码、跑 §6 快速门槛、生成分析文档可自主。
- commit message 用英文，不加 `Co-Authored-By`；與全域規則衝突時以本檔為準（例：本 repo commit message 用英文）。
- 不写死密钥、账号、路径、模型名、端口或环境差异逻辑。
- 新增文件后确认 `git status` 看得到它：`.gitignore` 有 `verify_*.py`、`local/`、`run.sh` 这类宽 pattern，命中就**静默消失**，要保留就补 `!` 例外并注明理由（踩过：`scripts/verify_swing_decisions.py`）。
- 新增配置项同步 `.env.example` 与相关文档；用户可见能力、CLI/API 行为、部署方式、通知方式、报告结构变化，同步相关文档与 `docs/CHANGELOG.md`；新增指向正式服务的 URL／金钥，要在 `tests/conftest.py` 中和。
- `README.md` 只放首页级信息（定位、能力总览、快速开始、入口）；模块行为、配置、排障、字段契约写进对应 `docs/*.md`。
- 本 fork **新寫的**註解、提示詞、CHANGELOG 條目用繁體中文；既有簡體不必回頭改。

## 1.2 质量底线

- **测试是为了守住一个修法或 guard 时，要做 mutation 检查**（纯新增功能的 smoke／快照测试不用）：把修法改回旧写法，测试必须立刻红；同时补**反向**检查（把修法改得过头也要红）。实测抓到过三次假守门（mock 让函式提前 return、少一个 phase 的断言、漏掉另一个测试档的同一 guard）。
- **时间相关的测试用相对日期**（`now - N 天`）：写死日历日的 fixture 会在某天起必红。DB 种子相反，用远离真实资料的固定年份。
- 研究／回测类结论（超额、Sharpe、命中率、偏误上界）写进文档前要过一轮对抗审查；**区间跨零或样本量不足一律写 inconclusive**。被推翻的数字在原处标作废。

## 2. AI 协作资产

`AGENTS.md` 是规则唯一真源，`CLAUDE.md` 只写一行 `@AGENTS.md`，协作 skill 在 `.claude/skills/`；根目录 `SKILL.md` 与 `docs/openclaw-skill-integration.md` 是产品说明，不是协作规则。分析产物在 `.claude/reviews/`（gitignore），**长期结论必须沉淀到 `docs/*.md`**。改治理资产后跑 `uv run python scripts/check_ai_assets.py`；改 §6 门槛时同步检查各 skill 的验证步骤；治理文件要核对命令、文件名、工作流名称与仓库一致。

## 3. 从哪里开始

台股分析现况（抓哪些数据、哪些护栏会改掉 LLM 结论、开关与建议值、已经研究过不要重做的问题）先读 `docs/tw-analysis-overview.md`；文件导航见 `docs/INDEX.md` 的「台股（本 fork）」，当天快照式的研究纪录放 `docs/research/`。

## 5. 交付

- 改到配置语义、API／Schema、数据源 fallback、报告结构、认证、调度或发布流程时，按 §7 逐项确认。
- 交付六项：改了什么 / 为什么这么改 / 验证情况 / 未验证项 / 风险点 / 回滚方式。`docs` 任务可写 `Docs only, tests not run`，但要说明是否核对了命令和文件名。

## 6. 验证

- 使用者路徑驗收用專案 skill `verify`（`.claude/skills/verify/SKILL.md`）；真實服務、fixture 與單測分開回報。
- Python 后端（`main.py`、`src/`、`data_provider/`、`api/`、`bot/`、`tests/`）开发中跑 `uv run ./scripts/ci_gate.sh syntax` + `uv run ./scripts/ci_gate.sh flake8`；交付前完整门槛是 `uv run ./scripts/ci_gate.sh`（含全量，§1 要先确认），最低要求 `uv run python -m py_compile <changed_files>`。
  - 全量应该全绿；跑的时候不改档（pytest 收集期就 import 完模组）、不和其他全量测试并行；红了先照 `docs/test-triage.md` 排除假红再判回归。缺 `pytest-timeout` plugin 时 pytest 直接中止、讯息看不出原因，测试工具相依在 `.github/requirements-ci.txt`。
  - **本机必须带 `uv run`**：脚本内部调用裸 `python`，全域 python 没有项目相依，不带 `uv run` 会跑错环境或缺套件。
  - **本机 `ci_gate.sh` 与 CI 不等价**：相依安装只有 CI 装得起来才算数；CI 的 backend-tests 跑 **Python 3.11**、本机 venv 是 3.12，3.12-only 语法（PEP 701 同引号巢状 f-string）本机永远剖析得过。`tests/test_python_version_compat.py` 挡这个，但本机借不到 CI 版本时它是 **skip 不是 fail**。
- 工作流／脚本／Docker：跑最接近的本地验证，说明影响哪条流水线或部署路径。
- API／Schema／认证联动：后端验证 + 受影响客户端构建，并写明兼容性影响。
- 没跑到的（平台限制、在线验证、Docker／Actions）在交付说明写原因。

## 7. 稳定性护栏

- 新配置要做到"不配置也可运行"（预设关闭或沿用旧行为）。
- 单一数据源或通知渠道失败不拖垮整个分析流程（除非需求要求 fail-fast）。
- 改 API／报告载荷优先追加字段、保留旧字段（客戶端是手動同步，舊版還會留在使用者手上）。

## 9. 合入与发布

- 分支模型：工作分支 → PR 合進 **`develop`**（GitHub 預設分支，日常整合）；`main` 只代表已發版。工作分支前綴要在 `ci.yml` 的 `on:` 清單內，否則沒有 CI，PR 上的 checks 就是那次 push run。推工作分支後用 `gh run list --branch <分支>` 找到 run，再用 `gh-wait run <run-id> -R audichuang/daily_stock_analysis`（或 `gh-wait pr <PR 號> -R …`，放背景跑）等 CI 綠，綠了就自己合進 `develop`（§1）；交付說明引用那次 run。CI 在 ttnas 上出錯先看 `docs/ci-ttnas-runner.md`。建立或更新 PR 前照 `.claude/skills/shared/baseline-sync.md` 同步基线。
- 發版（要先確認，§1）與部署流程見 `docs/nas-deploy.md`。發版用 `rel-YYYY.MM.DD` tag，不用 `v*.*.*`——那是上游的版號，會觸發上游的 release／Docker Hub／桌面端 workflow。

## 10. 本 fork 专属约定

> 个人 fork（`audichuang/daily_stock_analysis`），**不并回上游**。以下是从代码推断不出、跨模块都可能踩到的约定：

- **环境用 `uv`**：`uv venv --python 3.12`、`uv pip install -r requirements.txt`，执行一律 `uv run python …`。
- **origin 的 fetch refspec 在本机 checkout 只抓 `main` 与 `develop`**，`origin/<其他分支>` 一律不存在：看远端分支用 `git ls-remote` 或 `git fetch origin <分支>`（`FETCH_HEAD`）；rebase 後重推工作分支，裸 `--force-with-lease` 沒有追蹤參照會被拒，要寫成 `--force-with-lease=<分支>:<ls-remote 取的 sha>`。
- **台股代码必须带 `.TW`（上市）／`.TWO`（上柜）后缀**（裸 `2330` 不进台股语义），代码是 4~6 位数字加至多一个大写字母（`00631L`、`2887A`）。这条格式**没有单一来源**，前后端、报告渲染、索引种子脚本各有一份正则；语意真源是 `src/services/market_symbol_utils.py`，改一处要全扫（踩过：`00631L` 搜不到、海报印成 `00631`）。
- **TWSE/TPEx 官方端点会停止更新却照样回 200**（实测冻结 79 天）：消费端一律比对回应自带的日期，拿不到参照就拒收。
- **`.env` 的 `STOCK_INDEX_REMOTE_UPDATE_ENABLED` 必须保持 `false`**，否则运行时会从上游拉索引、覆盖本地台股／美股增量（`.env.example` 是上游的 `true`，勿照抄）。台股索引用 `make refresh-tw` 重建。
- **通知走 Telegram 群組的主題，憑證、主題 id 与台股新闻 token 走 Doppler 注入**，secret 不落地 `.env`：腳本與排程一律經 `make notify TOPIC=…`／`scripts/notify.py` 指定主題（主題對照見 `docs/daily-report-ops.md`），不要再直接打 Bark；`make serve`／`make review-tw`／`make daily-report` 已包好；**`make analyze` 不含**——少了它不报错，只会没通知、台股新闻退回通用搜寻（手动包法见 `docs/tw-operating-guide.md` §2.3）。Shioaji 金钥同走 Doppler，缺了即时报价静默降级 yfinance（讯号是 `source` 变 `fallback`）。
- **个股分析与大盘复盘走本机 Claude Code CLI**（`GENERATION_BACKEND=claude_code_cli`、`GENERATION_FALLBACK_BACKEND=` 留空），不需 API key；LiteLLM 那条在本机没有可用 key。要改回 LiteLLM 时 `.env` 须显式设 `LITELLM_MODEL`：否则 shell 导出了 `GEMINI_API_KEY` 时 `load_dotenv` 不覆盖既有变量，自动推断会选 Gemini。推理模型回空时的槓桿也是换 `LITELLM_MODEL`，不是加 token 预算（见 `src/AGENTS.md`）。
- **应用库（分析历史、回测、决策信号、LLM 用量）是 Postgres `dsa` schema（`.env` 的 `STORAGE_DATABASE_URL`），本机报告与 NAS 正式 Web 共用**——写进去就是写正式资料。`data/stock_analysis.db` 已冻结，读它只会静默拿到旧数据。临时脚本要隔离正式库就把 `STORAGE_DATABASE_URL` 设成空字串（pytest 由 `tests/conftest.py` 守；LiteLLM import 时补回 `.env` 的坑由 `src/__init__.py` 的 `LITELLM_MODE=PRODUCTION` 守，只在经 `src` import 时生效）。
- **台股历史数据（行情／筹码／财报）在 Postgres `market` schema（`.env` 的 `DATABASE_URL`），是唯一数据源、无备份**。查询前先读 `market_data/AGENTS.md` 的「读取语意」（未还原价、快照选定、单位）。
- **Web 服务正式跑在 NAS**：本机 launchd `com.audichuang.dsa` 已 disable，不要重新启用（两边会同时登入 Shioaji、共用应用库）。排程时间与每日报告的逾时／锁／完成标记见 `docs/daily-report-ops.md`。
- **新增会在 serve 路径被 import 的顶层 package／资料夹，要同步 `docker/Dockerfile` 的 COPY**：惰性 import 让容器里才 `ModuleNotFoundError`，且呼叫端多半静默退回别的数据源（踩过：`market_data/`）。
- **`--help` 不是安全探针**：`scripts/` 底下有脚本没有 argparse，`main()` 直接做事（`merge_tw_into_index.py` 改写进版控的索引、`migrate_sqlite_to_pg.py` 对 `market` schema `TRUNCATE`）。要探能不能跑，先 `grep -c argparse`。
