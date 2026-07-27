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

# Doppler 包裹：注入 BARK_URL 并映射为 CUSTOM_WEBHOOK_URLS
DOPPLER_RUN = doppler run -p $(DOPPLER_PROJECT) -c $(DOPPLER_CONFIG) --

.DEFAULT_GOAL := help
.PHONY: help install serve serve-local review review-tw analyze schedule screen \
        swing overnight measure portfolio portfolio-wf verify-decisions \
        test lint lint-fix format refresh-tw refresh-us

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

swing: ## 每日波段流程第 1 步：更新台股资料 → 全市场筛选 → 产出候选 JSON（第 2 步交给 AI）
	uv run --env-file .env python -m market_data.cli daily
	$(MAKE) screen
	@echo ""
	@echo "候选 JSON: .claude/reviews/screen-tw-latest.json"
	@echo "下一步（第 2 层）：让 agent 执行 skill \`tw-swing-research\` 读这份 JSON 做事件面研究，"
	@echo "判断会追加到 journal/swing-decisions.jsonl（进版控，当天就 commit——见 journal/README.md）。"
	@echo "收盘后才有当日资料；台股 13:30 收盘、法人与融资 T+1 才补齐。"

overnight: ## 昨晚国际盘数字（道琼/标普/纳指/费半/台积电ADR/油价/汇率，给 skill Step 0a 用）
	uv run python scripts/overnight.py --tw-close $(TSMC_CLOSE)

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

# ---- 质量检查 ----
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
