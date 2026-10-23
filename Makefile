# daily_stock_analysis — 常用任务（全部以 uv 执行）
# 用法： make <target>   例如： make serve / make review-tw / make lint
#
# 说明：
# - 所有 Python 入口统一走 `uv run`，无需手动 activate venv。
# - 通知（Bark）走 Doppler 注入：Doppler 中的 BARK_URL 在运行时映射为
#   CUSTOM_WEBHOOK_URLS（daily_stock_analysis 读取的通知变量），secret 不落地 .env。

# ---- 可覆盖变量 ----
DOPPLER_PROJECT ?= shioaji
DOPPLER_CONFIG  ?= dev
HOST            ?= 0.0.0.0
PORT            ?= 8000
STOCKS          ?=
REGION          ?= tw
TOP             ?= 25
MIN_TURNOVER    ?= 2
RANK            ?= score
SLOTS           ?= 5
TSMC_CLOSE      ?= 0
# notebooklm-py CLI（media-picks 用）；不在 PATH 時指向它的 venv，例如 ~/research/notebooklm-py/.venv/bin/notebooklm
NOTEBOOKLM_BIN  ?= notebooklm

# Doppler 包裹：注入 BARK_URL 并映射为 CUSTOM_WEBHOOK_URLS；外層再疊 `finmind` 專案注入 FINMIND_TOKEN_*（台股新聞）
DOPPLER_RUN = doppler run -p finmind -c dev -- doppler run -p $(DOPPLER_PROJECT) -c $(DOPPLER_CONFIG) --

.DEFAULT_GOAL := help
.PHONY: help install serve serve-local review review-tw analyze schedule screen \
        swing morning overnight taifex media-picks measure portfolio portfolio-wf verify-decisions shadow-buy \
        test lint lint-fix format refresh-tw refresh-us daily-report daily-report-detached \
        pg-scratch pg-scratch-stop

help: ## 显示所有可用命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## 安装后端依赖（uv）
	uv pip install -r requirements.txt

# ---- 运行服务 ----
serve: ## 启动 Web/API 服务（Doppler 注入 Bark 推播）
	$(DOPPLER_RUN) bash -c 'CUSTOM_WEBHOOK_URLS="$$BARK_URL" uv run python main.py --serve-only --host $(HOST) --port $(PORT)'

serve-local: ## 启动 Web/API 服务（不含 Bark；纯本机调试）
	uv run python main.py --serve-only --host $(HOST) --port $(PORT)

# ---- 每日报告 ----
daily-report: ## 每日本机报告：更新并健检台股资料 → 自选股分析 + 大盘复盘 → Bark（任一步失败也推 Bark）
	DOPPLER_PROJECT=$(DOPPLER_PROJECT) DOPPLER_CONFIG=$(DOPPLER_CONFIG) bash scripts/daily_report.sh

daily-report-detached: ## 同上，但脱离当前 session 在背景跑完即返回（排程用；呼叫者被收掉也不中断）
	DOPPLER_PROJECT=$(DOPPLER_PROJECT) DOPPLER_CONFIG=$(DOPPLER_CONFIG) bash scripts/daily_report.sh --detach

# ---- 大盘复盘 ----
review-tw: ## 生成台股大盘复盘（Doppler 注入 Bark 推播）
	$(DOPPLER_RUN) bash -c 'CUSTOM_WEBHOOK_URLS="$$BARK_URL" MARKET_REVIEW_REGION=$(REGION) uv run python main.py --market-review'

review: ## 生成大盘复盘（默认 region，按 .env 的 MARKET_REVIEW_REGION）
	uv run python main.py --market-review

# ---- 个股分析 ----
analyze: ## 分析指定股票，例： make analyze STOCKS=2330.TW,2317.TW
	uv run python main.py --stocks "$(STOCKS)"

schedule: ## 启动定时调度模式
	uv run python main.py --schedule

# ---- 选股筛选与验证 ----
screen: ## 台股全市场量化筛选（读 market schema），同时出 markdown 与 JSON 供 agent 接手
	uv run --env-file .env python scripts/screen_tw.py --top $(TOP) \
		--min-turnover $(MIN_TURNOVER) --json .claude/reviews/screen-tw-latest.json

swing: ## 每日波段流程第 1 步：更新并健检台股资料 → 全市场筛选 → 产出候选 JSON
	uv run --env-file .env python -m market_data.cli daily
	uv run --env-file .env python -m market_data.cli health --strict
	$(MAKE) screen
	@echo ""
	@echo "候选 JSON: .claude/reviews/screen-tw-latest.json"
	@echo "下一步（第 2 层）：让 agent 执行 skill \`tw-swing-research\`，完整研究每一档候选，"
	@echo "把每檔判斷各自追加一行到 journal/swing-decisions.jsonl（進版控，當天 commit——見 journal/README.md）。"
	@echo "收盘后才有当日资料；台股 13:30 收盘、法人与融资 T+1 才补齐。"

morning: ## 每天早上一键：补资料 → 昨晚国际盘 → 期交所籌碼 → 待触发计划 → 今日候选（之后跑 skill）
	@uv run --env-file .env python -m market_data.cli daily
	@uv run --env-file .env python -m market_data.cli health --strict
	@echo "\n===== 昨晚国际盘 ====="
	@# 任一序列失敗回 1，失敗已逐列印在表裡；用 - 讓後面的期交所／待觸發計畫／候選照跑
	@-tsmc=$$(uv run --env-file .env python -c "from market_data.db import get_engine;from sqlalchemy import text;print(get_engine().connect().execute(text(\"select close from market.price where stock_id='2330' order by date desc limit 1\")).scalar() or 0)" 2>/dev/null); \
		uv run python scripts/overnight.py --tw-close $$tsmc
	@echo "\n===== 期交所籌碼（前一交易日）====="
	@# - 只吞程式崩潰：資料問題（查無資料、日期不符）腳本自己印 ⚠ 並 exit 0
	@-uv run python scripts/taifex_positions.py
	@echo "\n===== 待触发计划（已留档、未到期）====="
	@bash -o pipefail -c "uv run --env-file .env python scripts/verify_swing_decisions.py | sed -n '1,/^$$/p'"
	@echo "===== 今日候选 ====="
	@$(MAKE) --no-print-directory screen
	@echo "\n下一步：让 agent 跑 skill \`tw-swing-research\`（候选 0 档也要看上面的隔夜盘与待触发计划）"

overnight: ## 昨晚国际盘数字（道琼/标普/纳指/费半/台积电ADR/油价/汇率，给 skill Step 0a 用）
	uv run python scripts/overnight.py --tw-close $(TSMC_CLOSE)

taifex: ## 期交所外資台指期淨未平倉＋P/C 未平倉比（給 skill tw-morning-call Step 1；回應日期≠預期場次時不印數字）
	uv run python scripts/taifex_positions.py

media-picks: ## 財經電視完整版 → NotebookLM 逐字稿與點名 → 對照本地數據 → journal/media-picks.jsonl（憑證走 Doppler notebooklm）
	NOTEBOOKLM_BIN=$(NOTEBOOKLM_BIN) doppler run -p notebooklm -c prd -- uv run --env-file .env python scripts/tw_media_picks.py

ptt-picks: ## PTT 股票板 [標的] 文 → 解析多空／理由／進退場 → 對照本地數據 → journal/ptt-picks.jsonl
	uv run --env-file .env python scripts/tw_ptt_picks.py

measure: ## 量测讯号的前瞻报酬分布（事件级、区块 bootstrap；不做部位模拟）
	uv run --env-file .env python scripts/measure_signal_forward.py

portfolio: ## 组合层验证：同日资金竞争 + 持股上限 + 回撤，对照 0050（RANK=score|random）
	uv run --env-file .env python scripts/portfolio_walkforward.py --rank $(RANK) \
		--slots $(SLOTS)

portfolio-wf: ## 同上但走擴張窗选参，只计样本外（回答选参偏误有多大）
	uv run --env-file .env python scripts/portfolio_walkforward.py --walk-forward \
		--slots $(SLOTS)

verify-decisions: ## 回验 tw-swing-research 的判断（Brier + E[R|enter]−E[R|全收]）
	uv run --env-file .env python scripts/verify_swing_decisions.py

shadow-buy: ## 影子評估：被護欄壓掉的 LLM 原判買進照做的 1/2/3/5 日淨報酬 vs 0050（唯讀，輸出到 reports/）
	uv run --env-file .env python scripts/shadow_buy_eval.py

# ---- 质量检查 ----
pg-scratch: ## 本機臨時 Postgres（market schema 跑到 Alembic head），印出要 export 的 DATABASE_URL
	@scripts/pg_scratch.sh start

pg-scratch-stop: ## 停掉臨時 Postgres（scripts/pg_scratch.sh reset 連資料一起刪）
	@scripts/pg_scratch.sh stop

test: ## 运行离线测试（不含 network 标记）
	uv run python -m pytest -m "not network" -q

lint: ## ruff 静态检查（E/F/W/I，详见 pyproject）
	uv run --with ruff ruff check .

lint-fix: ## ruff 自动修复可修项
	uv run --with ruff ruff check --fix .

format: ## ruff 代码格式化
	uv run --with ruff ruff format .

# ---- 自动补全索引维护 ----
refresh-tw: ## 重抓台股官方清单并合并进自动补全索引
	uv run python scripts/fetch_tw_stock_list.py
	uv run python scripts/merge_tw_into_index.py

refresh-us: ## 从 NASDAQ Trader 官方清单增量补进美股新代码
	uv run python scripts/refresh_us_stock_index.py
