#!/usr/bin/env bash
# 每日本机报告：更新台股资料 → 健检 → 自选股分析 + 大盘复盘 → Bark。
#
# 由 `make daily-report` 调用（Orca automation 每天触发）。任何一步失败都会推一则
# Bark 失败通知再以非零退出——资料没更新就不出报告：无法证明新鲜的数字不如没有数字。
# 非交易日由 main.py 自己的交易日检查跳过（不带 --force-run）。
set -uo pipefail

cd "$(dirname "$0")/.."

# --detach：脱离呼叫者的 session / process group 后立即返回。Orca 排程叫起的 agent
# 结束一轮后，它的 terminal 会被收掉，连同背景子行程一起砍——报告不能跟着 agent 的寿命走。
if [[ "${1:-}" == "--detach" ]]; then
  mkdir -p logs
  nohup perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV or die "exec: $!"' bash "$0" \
    >>logs/daily_report_launcher.log 2>&1 </dev/null &
  echo "daily report started in background (pid $!); progress: newest logs/daily_report_*.log"
  exit 0
fi

DOPPLER_PROJECT="${DOPPLER_PROJECT:-shioaji}"
DOPPLER_CONFIG="${DOPPLER_CONFIG:-dev}"
DOPPLER_RUN=(doppler run -p "$DOPPLER_PROJECT" -c "$DOPPLER_CONFIG" --)

mkdir -p logs
LOG="logs/daily_report_$(date +%Y%m%d_%H%M%S).log"

# run_step 已把 stdout 导进 $LOG，step 内只印 stdout，避免同一行写两次。
say() { printf '%s | %s\n' "$(date '+%F %T')" "$*"; }
log() { printf '%s | %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG"; }

notify_failure() {
  local body="$1"
  local payload
  payload=$(uv run --no-project python -c \
    'import json,sys; print(json.dumps({"title": "每日報告失敗", "body": sys.argv[1], "group": "dsa"}, ensure_ascii=False))' \
    "$body" 2>/dev/null)
  "${DOPPLER_RUN[@]}" bash -c \
    'curl -sS -m 15 -X POST "$BARK_URL" -H "Content-Type: application/json; charset=utf-8" -d "$1" >/dev/null' \
    _ "$payload" || log "WARN: Bark 失败通知也没送出去"
}

run_step() {
  local name="$1"; shift
  log "==> $name"
  if ! "$@" >>"$LOG" 2>&1; then
    log "FAILED: $name"
    notify_failure "$name 失敗，本日報告未產出。log: $LOG"
    exit 1
  fi
}

# LLM 失效时 main.py 仍以 0 退出、照样推一份只有模板的复盘，所以前后各守一道：
# 分析前用 .env 设定的生成后端打一个极小请求；分析后要求至少一档个股成功（非交易日跳过除外）。
llm_preflight() {
  # 走 .env 实际设定的生成后端（GENERATION_BACKEND），与分析同一条路径。
  uv run python -c '
import sys
from src.analyzer import GeminiAnalyzer
try:
    text = GeminiAnalyzer().generate_text("只回覆 pong 这个词。", max_tokens=16)
except Exception as exc:
    print(f"LLM preflight failed: {type(exc).__name__}: {exc}"[:500])
    sys.exit(1)
if not (text or "").strip():
    print("LLM preflight failed: empty response")
    sys.exit(1)
print(f"LLM preflight ok: {text.strip()[:40]}")
'
}

require_stock_success() {
  local summary
  if grep -q '今日所有相关市场均为非交易日' "$LOG"; then
    say "非交易日，main.py 已跳過分析（不推通知）"
    return 0
  fi
  summary=$(grep -oE '成功: [0-9]+, 失败: [0-9]+' "$LOG" | tail -1)
  say "個股分析結果：${summary:-找不到彙總行}"
  [[ "$summary" =~ ^成功:\ ([0-9]+) ]] && (( BASH_REMATCH[1] > 0 ))
}

# 当天已经成功推过一份就不再跑（手动补跑与 18:00 排程撞同一天时不会推两份）；要重跑设 DAILY_REPORT_FORCE=1。
DONE_MARK="logs/.daily_report_done_$(date +%Y%m%d)"
if [[ -f "$DONE_MARK" && "${DAILY_REPORT_FORCE:-0}" != "1" ]]; then
  log "今天已產出過報告（${DONE_MARK}），本次不重複跑；要重跑請設 DAILY_REPORT_FORCE=1"
  rm -f "$LOG"
  exit 0
fi

LOCK="logs/.daily_report.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if kill -0 "$(cat "$LOCK/pid" 2>/dev/null)" 2>/dev/null; then
    log "另一輪每日報告仍在執行（pid $(cat "$LOCK/pid")），本次不重複跑"
    rm -f "$LOG"
    exit 0
  fi
  rm -rf "$LOCK" && mkdir "$LOCK"   # 前一輪被砍掉留下的鎖
fi
echo $$ >"$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

log "daily report start (log: $LOG)"
run_step "台股資料更新 (market_data daily)" uv run --env-file .env python -m market_data.cli daily
run_step "台股資料健檢 (health --strict)" uv run --env-file .env python -m market_data.cli health --strict
run_step "LLM 連線預檢" llm_preflight
run_step "自選股分析 + 大盤復盤" "${DOPPLER_RUN[@]}" bash -c 'CUSTOM_WEBHOOK_URLS="$BARK_URL" uv run python main.py'
run_step "個股分析至少一檔成功" require_stock_success
touch "$DONE_MARK"
log "daily report done"
