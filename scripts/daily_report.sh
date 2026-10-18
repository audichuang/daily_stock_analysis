#!/usr/bin/env bash
# 每日本机报告：更新台股资料 → 健检 → 自选股分析 + 大盘复盘 → Bark。
#
# 由 `make daily-report` 调用（Orca automation 每天触发）。任何一步失败都会推一则
# Bark 失败通知再以非零退出——资料没更新就不出报告：无法证明新鲜的数字不如没有数字。
# 非交易日由 main.py 自己的交易日检查跳过（不带 --force-run）。
#
# 每步有 process-group 逾时（DAILY_REPORT_STEP_TIMEOUT_SECONDS，预设 5400）；前一轮的锁
# 持有者还活着且锁龄超过 DAILY_REPORT_STALE_LOCK_SECONDS（预设 10800）会推 Bark 并以 1 退出。
# 两个变数只供手动覆写（本脚本不读 .env）。脚本可被 source 以载入函式（测试用），只有直接执行才跑 main。

DOPPLER_PROJECT="${DOPPLER_PROJECT:-shioaji}"
DOPPLER_CONFIG="${DOPPLER_CONFIG:-dev}"
DOPPLER_RUN=(doppler run -p "$DOPPLER_PROJECT" -c "$DOPPLER_CONFIG" --)

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

# 以 perl 在独立 process group 里执行命令并计时：逾时对整个 group 先 TERM、等最多 10 秒
# 让成员退出，仍有残留再 KILL，回 124；正常结束回子行程退出码（被信号杀回 128+sig）。
# 用 perl 是因为 macOS 没有 timeout(1)；kill 整个 group 才收得掉 `uv run` 底下的孙行程。
run_with_timeout() {
  local secs="$1"; shift
  perl -e '
    my $secs = shift @ARGV;
    my $pid = fork();
    die "fork: $!\n" unless defined $pid;
    if ($pid == 0) {
      setpgrp(0, 0);
      exec @ARGV or do { print STDERR "exec @ARGV: $!\n"; exit 127 };
    }
    setpgrp($pid, $pid);    # 父子都设，避免 kill 比子行程 setpgrp 先到
    my ($done, $status) = (0, 0);
    my $reap = sub {
      return 1 if $done;
      my $r = waitpid($pid, 1);    # WNOHANG
      if ($r == $pid) { $done = 1; $status = $?; }
      return $done;
    };
    my $stop = sub {
      my $sig = shift;
      kill $sig, -$pid;
      for (1 .. 50) {
        $reap->();
        last if $done && !kill(0, -$pid);
        select(undef, undef, undef, 0.2);
      }
      kill "KILL", -$pid;
      waitpid($pid, 0) unless $done;
      $done = 1;
    };
    my $timed_out = 0;
    $SIG{ALRM} = sub { $timed_out = 1; $stop->("TERM"); };
    for my $s (qw(TERM INT HUP)) {
      $SIG{$s} = sub { $stop->($s); exit(128 + ($s eq "TERM" ? 15 : $s eq "INT" ? 2 : 1)); };
    }
    alarm int($secs);
    while (!$done) {
      last if $reap->();
      select(undef, undef, undef, 0.1);
    }
    alarm 0;
    exit 124 if $timed_out;
    exit(($status & 127) ? 128 + ($status & 127) : $status >> 8);
  ' "$secs" "$@"
}

# 距 DIR 最後修改的秒数（纯整数）。不用 `stat -f %m`：GNU stat 会把 %m 当成第二个档案，
# 并把档案系统资讯印到 stdout。
lock_age_seconds() {
  perl -e 'print time - (stat shift)[9]' "$1"
}

# 锁持有者还活着，但锁已存在超过门槛（预设 3 小时）→ 视为卡住。
lock_is_stale() {
  local age
  age=$(lock_age_seconds "$1" 2>/dev/null) || return 1
  [[ "$age" =~ ^[0-9]+$ ]] && (( age > ${DAILY_REPORT_STALE_LOCK_SECONDS:-10800} ))
}

run_step() {
  local name="$1"; shift
  local secs="${DAILY_REPORT_STEP_TIMEOUT_SECONDS:-5400}"
  local rc=0
  log "==> $name"
  if declare -F "$1" >/dev/null; then
    # bash 函式 perl exec 不了：export -f 后交给子 bash 跑；函式内用到的 say／$LOG 也要带过去。
    export -f "$1" say log
    export LOG
    run_with_timeout "$secs" bash -c '"$@"' _ "$@" >>"$LOG" 2>&1 || rc=$?
  else
    run_with_timeout "$secs" "$@" >>"$LOG" 2>&1 || rc=$?
  fi
  if (( rc == 124 )); then
    log "TIMEOUT: $name (超過 ${secs} 秒，已終止)"
    notify_failure "$name 逾時（超過 ${secs} 秒）已終止，本日報告未產出。log: $LOG"
    exit 1
  elif (( rc != 0 )); then
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

main() {
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

  mkdir -p logs
  LOG="logs/daily_report_$(date +%Y%m%d_%H%M%S).log"

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
      if lock_is_stale "$LOCK"; then
        # 持有者活着但锁龄过久：上一轮卡死了。留下本轮 log、推播，不要像以前那样静默退出。
        hours=$(( $(lock_age_seconds "$LOCK") / 3600 ))
        log "FAILED: 前一輪每日報告（pid $(cat "$LOCK/pid")）已卡住約 ${hours} 小時，本輪未執行"
        notify_failure "前一輪每日報告（pid $(cat "$LOCK/pid")）已卡住約 ${hours} 小時仍未結束，本輪未執行。log: $LOG"
        exit 1
      fi
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
  # 外層疊 Doppler `finmind` 專案：注入 FINMIND_TOKEN_*，台股個股新聞先查 FinMind。
  run_step "自選股分析 + 大盤復盤" doppler run -p finmind -c dev -- "${DOPPLER_RUN[@]}" bash -c 'CUSTOM_WEBHOOK_URLS="$BARK_URL" uv run python main.py'
  run_step "個股分析至少一檔成功" require_stock_success
  touch "$DONE_MARK"
  log "daily report done"
}

# 只有直接执行才跑 main；被 source（测试）时只载入函式。
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
