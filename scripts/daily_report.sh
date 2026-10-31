#!/usr/bin/env bash
# 每日本机报告：更新台股资料 → 健检 → 自选股分析 + 大盘复盘 → Telegram（每日報告主題）。
#
# 由 `make daily-report` 调用（Orca automation 每天触发）。任何一步失败都会推一则
# 失败通知（Telegram 系統通知主題）再以非零退出——资料没更新就不出报告：无法证明新鲜的数字不如没有数字。
# 非交易日由 main.py 自己的交易日检查跳过（不带 --force-run）。
#
# 每步有 process-group 逾时（DAILY_REPORT_STEP_TIMEOUT_SECONDS，预设 5400）；前一轮的锁
# 持有者还活着且锁龄超过 DAILY_REPORT_STALE_LOCK_SECONDS（预设 10800）会推失败通知并以 1 退出。
# 两个变数只供手动覆写（本脚本不读 .env）。脚本可被 source 以载入函式（测试用），只有直接执行才跑 main。
#
# 完成标记 logs/.daily_report_last_session 记「<曆日>|<expected_session>」：同一天且同一交易场次才跳过。
# 盘中手动跑（expected=前一交易日）不会挡掉 18:00 的正式报告；台股休市日 expected 不变但曆日变了，仍会跑美股。
# 日历取不到（expected 空）永不跳过、也不写标记；DAILY_REPORT_FORCE=1 一律重跑。

# export：run_step 把 bash 函式交给子 bash 跑，notify_failure 要靠这两个变数自己组 doppler 命令
# （bash 阵列无法 export）。
export DOPPLER_PROJECT="${DOPPLER_PROJECT:-shioaji}"
export DOPPLER_CONFIG="${DOPPLER_CONFIG:-dev}"
DOPPLER_RUN=(doppler run -p "$DOPPLER_PROJECT" -c "$DOPPLER_CONFIG" --)

# run_step 已把 stdout 导进 $LOG，step 内只印 stdout，避免同一行写两次。
say() { printf '%s | %s\n' "$(date '+%F %T')" "$*"; }
log() { printf '%s | %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG"; }

# notify_failure BODY [TITLE] [TOPIC]：TITLE 预设「每日報告失敗」；非致命通知（如个股部分失败）传自己的标题。
# TOPIC 是 Telegram 群組的主題（scripts/notify.py 的 --topic），預設 system。
# 整次呼叫（doppler＋uv＋HTTP 重試）以 NOTIFY_TIMEOUT_SECONDS（預設 60）為上限：逾時與鎖齡告警在步驟計時之外呼叫，
# 通知卡住會讓腳本不退出、鎖也放不掉。notify.py 的輸出（含未送出的原因）寫進 $LOG。
notify_failure() {
  local body="$1" title="${2:-每日報告失敗}" topic="${3:-system}"
  local -a runner=(doppler run -p "$DOPPLER_PROJECT" -c "$DOPPLER_CONFIG" --)
  printf '%s' "$body" | run_with_timeout "${NOTIFY_TIMEOUT_SECONDS:-60}" \
    "${runner[@]}" uv run python scripts/notify.py --topic "$topic" --title "$title" >>"${LOG:-/dev/stderr}" 2>&1 \
    || log "WARN: Telegram 通知也没送出去"
}

# 以 perl 在独立 process group 里执行命令并计时：逾时对整个 group 先 TERM、等最多 10 秒
# 让成员退出，仍有残留再 KILL，回 124；正常结束回子行程退出码（被信号杀回 128+sig）。
# 用 perl 是因为 macOS 没有 timeout(1)；kill 整个 group 才收得掉 `uv run` 底下的孙行程。
# CLI 另開 session，Python 以同一把 flock 登記 PGID；終止時先封閉登記，再一併收掉。
run_with_timeout() {
  local secs="$1"; shift
  perl -e '
    use File::Temp qw(tempfile);
    use Fcntl qw(:flock);
    my ($registry, $registry_path) = tempfile("dsa-step-XXXXXX", TMPDIR => 1, UNLINK => 1);
    $registry->autoflush(1);
    print $registry "open\n";
    $ENV{_DSA_LOCAL_CLI_REGISTRY} = $registry_path;
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
      flock($registry, LOCK_EX) or die "registry lock: $!\n";
      seek($registry, 0, 0);
      my @groups = ($pid, map { chomp; /^\d+$/ ? int($_) : () } <$registry>);
      seek($registry, 0, 0);
      print $registry "closed\n";
      truncate($registry, tell($registry));
      kill $sig, -$_ for @groups;
      flock($registry, LOCK_UN);
      for (1 .. 50) {
        $reap->();
        last if $done && !grep { kill(0, -$_) } @groups;
        select(undef, undef, undef, 0.2);
      }
      kill "KILL", -$_ for @groups;
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

# 锁持有者还活着，但锁已存在超过门槛（$2 秒；缺省读 DAILY_REPORT_STALE_LOCK_SECONDS，预设 3 小时）→ 视为卡住。
lock_is_stale() {
  local age limit="${2:-${DAILY_REPORT_STALE_LOCK_SECONDS:-10800}}"
  age=$(lock_age_seconds "$1" 2>/dev/null) || return 1
  [[ "$age" =~ ^[0-9]+$ ]] && (( age > limit ))
}

# lock_transition ACTION LOCK PID STALE_SECONDS：在固定的 .guard 檔上 flock，序列化建鎖、回收與釋放。
# .guard 永不刪除，避免不同 inode 上的 flock 同時放行；鎖目錄仍供鎖齡告警與舊排程診斷使用。
# acquire 回 0＝取得、2＝忙碌（stdout 為持有者）、3＝活著但逾時、其餘＝錯誤；release 只清自己的鎖。
lock_transition() {
  perl -e '
    use strict;
    use warnings;
    use Fcntl qw(:flock);
    use File::Path qw(remove_tree);
    $SIG{__DIE__} = sub { print STDERR @_; exit 1; };
    my ($action, $lock, $pid, $limit) = @ARGV;
    open my $guard, ">>", "$lock.guard" or die "open guard: $!\n";
    flock($guard, LOCK_EX) or die "flock: $!\n";
    my $read_owner = sub {
      open my $fh, "<", "$lock/pid" or return "";
      my $owner = <$fh> // "";
      chomp $owner;
      return $owner;
    };
    # 用 remove_tree：舊版或手動留下的鎖目錄裡若有其他檔，rmdir 會失敗、整輪卡住。
    my $clear = sub {
      remove_tree($lock);
      die "remove lock: $lock\n" if -e $lock;
    };
    if ($action eq "release") {
      $clear->() if -d $lock && $read_owner->() eq $pid;
      exit 0;
    }
    if (-d $lock) {
      my $owner = $read_owner->();
      my $age = time - (stat $lock)[9];
      if ($owner =~ /^\d+$/ && $owner > 0 && (kill(0, $owner) || $!{EPERM})) {
        print $owner;
        exit($age > $limit ? 3 : 2);
      }
      # 新建目錄尚未寫 PID 時先視為持有中；超過原有鎖齡門檻才回收無主鎖。
      exit 2 if $owner eq "" && $age <= $limit;
      $clear->();
    }
    mkdir $lock or die "mkdir lock: $!\n";
    open my $fh, ">", "$lock/pid" or die "open pid: $!\n";
    print $fh "$pid\n" or die "write pid: $!\n";
    close $fh or die "close pid: $!\n";
  ' "$@"
}

release_lock() {
  lock_transition release "$LOCK" "$$" 0
}

# acquire_lock LOCK LABEL STALE_SECONDS [KEEP_LOG_ON_SKIP=0] [FAIL_TITLE]：每日報告與媒體點名共用的 mkdir 鎖。
# 活著且逾時 → FAILED＋通知、exit 1；仍在跑或剛建鎖尚無 PID → 跳過、exit 0。
# 死鎖／過期的無 PID 鎖在同一個 flock 交易內回收重建，成功後才設 EXIT trap。
acquire_lock() {
  LOCK="$1"
  local label="$2" stale_secs="$3" keep_log="${4:-0}" title="${5:-}" owner rc hours
  if owner=$(lock_transition acquire "$LOCK" "$$" "$stale_secs"); then
    trap release_lock EXIT
    return 0
  else
    rc=$?
  fi
  case "$rc" in
    2)
      log "另一輪${label}仍在執行（pid ${owner:-尚未寫入}），本次不重複跑"
      [[ "$keep_log" == "1" ]] || rm -f "$LOG"
      exit 0
      ;;
    3)
      hours=$(( $(lock_age_seconds "$LOCK") / 3600 ))
      log "FAILED: 前一輪${label}（pid ${owner}）已卡住約 ${hours} 小時，本輪未執行"
      notify_failure "前一輪${label}（pid ${owner}）已卡住約 ${hours} 小時仍未結束，本輪未執行。log: $LOG" ${title:+"$title"}
      ;;
    *)
      log "FAILED: 無法取得${label}鎖，本輪未執行"
      notify_failure "無法取得${label}鎖，本輪未執行。log: $LOG" ${title:+"$title"}
      ;;
  esac
  exit 1
}

# spawn_detached SCRIPT LAUNCHER_LOG：新 session 里跑 bash SCRIPT（不带参数），pid 放 DETACHED_PID。
# 每日报告与媒体点名的 --detach 共用；呼叫端前缀的环境变数会带进子行程。
spawn_detached() {
  nohup perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV or die "exec: $!"' bash "$1" \
    >>"$2" 2>&1 </dev/null &
  DETACHED_PID=$!
}

run_step() {
  local name="$1"; shift
  local secs="${DAILY_REPORT_STEP_TIMEOUT_SECONDS:-5400}"
  local rc=0
  log "==> $name"
  if declare -F "$1" >/dev/null; then
    # bash 函式 perl exec 不了：export -f 后交给子 bash 跑；函式内用到的 say／$LOG 也要带过去。
    export -f "$1" say log notify_failure run_with_timeout failed_codes
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

# LOG 里「[代码] 分析未成功」的代码，去重排序（pipeline.py 每档失败印一行）。
failed_codes() {
  grep -oE '\[[0-9A-Z.]+\] 分析未成功' "$1" 2>/dev/null | sed -E 's/^\[([^]]+)\].*/\1/' | sort -u
}

# 完成标记的键：「<曆日>|<expected_session>」。expected 空或格式不对（日历不可用）→ 印空，代表「不判定」。
session_key() {
  local expected="$1"
  [[ "$expected" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || return 0
  printf '%s|%s' "$(date +%Y%m%d)" "$expected"
}

# 此刻库里应有的最近交易场次（YYYY-MM-DD）；取不到印空。定义只有一份：market_data.health.expected_session。
current_expected_session() {
  uv run --env-file .env python -c \
    'from market_data.health import expected_session; s=expected_session(); print(s or "")' \
    2>/dev/null | tail -1
}

# session_already_reported MARK KEY：KEY 非空且 MARK 内容与之完全相同才回 0（该跳过）。
session_already_reported() {
  local mark="$1" key="$2"
  [[ "$key" =~ ^[0-9]{8}\|.+$ && -f "$mark" ]] || return 1
  [[ "$(cat "$mark" 2>/dev/null)" == "$key" ]]
}

require_stock_success() {
  local summary
  if grep -q '今日所有相关市场均为非交易日' "$LOG"; then
    say "非交易日，main.py 已跳過分析（不推通知）"
    return 0
  fi
  summary=$(grep -oE '成功: [0-9]+, 失败: [0-9]+' "$LOG" | tail -1)
  say "個股分析結果：${summary:-找不到彙總行}"
  [[ "$summary" =~ ^成功:\ ([0-9]+),\ 失败:\ ([0-9]+) ]] || return 1
  local ok="${BASH_REMATCH[1]}" failed="${BASH_REMATCH[2]}"
  if (( failed > 0 && ok > 0 )); then
    # 部分失败不改变成败判定（至少一档成功就算过），但要让人知道是哪几档；
    # 全军覆没由 run_step 的致命通知负责，不重复推。
    local codes
    codes=$(failed_codes "$LOG" | tr '\n' ' ')
    notify_failure "個股分析 ${failed} 檔失敗（成功 ${ok} 檔）：${codes}。log: $LOG" "每日報告部分失敗" \
      || say "WARN: 部分失敗通知沒送出去"
  fi
  (( ok > 0 ))
}

# 行事曆快取（scripts/refresh_calendar.py）：非致命，寫進與 NAS 共用的應用庫；NAS 沒開排程，靠這裡更新。
calendar_refresh() {
  local rc=0
  run_with_timeout "${CALENDAR_REFRESH_TIMEOUT_SECONDS:-600}" \
    uv run --env-file .env python scripts/refresh_calendar.py >>"$LOG" 2>&1 || rc=$?
  if (( rc != 0 )); then
    log "WARN: 行事曆更新失敗（rc=${rc}），不影響每日報告"
    notify_failure "行事曆更新失敗（rc=${rc}），每日報告照常。log: $LOG" "行事曆更新失敗" || true
  fi
  return 0
}

# 盤前判讀回驗（scripts/verify_morning_calls.py）：非致命，失敗只記 WARN 並推一則通知，不擋每日報告。
# 只 commit outcomes 檔（預測檔 morning-calls.jsonl 由 07:30 排程另外 commit，兩者分開才有防竄改保證）；
# push 走 media_picks_job.sh --push-journal 的守門：只在 develop、領先的 commit 全是 journal/ 才推。
# 要不要 commit 看 outcomes 檔的 git 狀態、不看這輪有沒有新結果：上一輪 commit 失敗留下的列，這一輪要補 commit／push。
OUTCOMES_FILE="journal/morning-calls-outcomes.jsonl"
morning_call_outcomes() {
  local out rc=0 line branch push="" pending
  out=$(run_with_timeout "${MORNING_VERIFY_TIMEOUT_SECONDS:-900}" \
    uv run --env-file .env python scripts/verify_morning_calls.py --append --push 2>&1) || rc=$?
  printf '%s\n' "$out" >>"$LOG"
  if (( rc != 0 )); then
    log "WARN: 盤前判讀回驗失敗（rc=${rc}），不影響每日報告"
    notify_failure "盤前判讀回驗失敗（rc=${rc}），每日報告照常。log: $LOG" "盤前判讀回驗失敗" || true
    return 0
  fi
  line=$(printf '%s\n' "$out" | sed -n 's/^PUSH: //p' | tail -1)
  pending=$(git status --porcelain -- "$OUTCOMES_FILE" 2>/dev/null)
  if [[ -z "$line" && -z "$pending" ]]; then
    log "盤前判讀回驗：沒有新結果"
    return 0
  fi
  branch=$(git branch --show-current)
  if [[ "$branch" != "develop" ]]; then
    push="未 commit（主 checkout 在 ${branch:-detached HEAD}）"
  elif ! { git add -- "$OUTCOMES_FILE" \
      && git commit -q -m "journal: morning call outcomes $(date +%F)" -- "$OUTCOMES_FILE"; } >>"$LOG" 2>&1; then
    push="commit 失敗（下一輪重試）"
  else
    push=$(bash scripts/media_picks_job.sh --push-journal 2>>"$LOG" | tail -1)
  fi
  log "盤前判讀回驗：${push}"
  # 摘要送盤前判讀主題；留檔（commit／push）出錯另送系統通知——盤前主題可能被靜音，故障不能只藏在摘要裡。
  if [[ -n "$line" ]]; then
    notify_failure "${line}（journal：${push}）" "盤前判讀回驗 $(date +%F)" morning || true
  fi
  if [[ "$push" != "push ok" ]]; then
    notify_failure "盤前判讀回驗結果未推上 develop：${push}。log: $LOG" "盤前判讀回驗留檔失敗" || true
  fi
}

main() {
  set -uo pipefail

  cd "$(dirname "$0")/.."

  # --detach：脱离呼叫者的 session / process group 后立即返回。Orca 排程叫起的 agent
  # 结束一轮后，它的 terminal 会被收掉，连同背景子行程一起砍——报告不能跟着 agent 的寿命走。
  if [[ "${1:-}" == "--detach" ]]; then
    mkdir -p logs
    spawn_detached "$0" logs/daily_report_launcher.log
    echo "daily report started in background (pid $DETACHED_PID); progress: newest logs/daily_report_*.log"
    exit 0
  fi

  mkdir -p logs
  LOG="logs/daily_report_$(date +%Y%m%d_%H%M%S).log"

  # 同一天且同一交易场次已成功推过一份就不再跑；要重跑设 DAILY_REPORT_FORCE=1。
  # 键含场次：盘中手动跑（场次=前一交易日）不会挡掉 18:00，台股休市日也不会连美股一起跳过。
  DONE_MARK="logs/.daily_report_last_session"
  # 颱風假：先查停班停課頁、記進臨時休市清單，expected_session 才不會把休市日當成缺資料擋下。
  uv run --env-file .env python -m market_data.closures >>"$LOG" 2>&1 || true
  SESSION_KEY=$(session_key "$(current_expected_session)")
  if [[ "${DAILY_REPORT_FORCE:-0}" != "1" ]] && session_already_reported "$DONE_MARK" "$SESSION_KEY"; then
    log "本交易場次已產出過報告（${DONE_MARK}＝${SESSION_KEY}），本次不重複跑；要重跑請設 DAILY_REPORT_FORCE=1"
    rm -f "$LOG"
    exit 0
  fi

  acquire_lock "logs/.daily_report.lock" 每日報告 "${DAILY_REPORT_STALE_LOCK_SECONDS:-10800}"

  log "daily report start (log: $LOG)"
  run_step "台股資料更新 (market_data daily)" uv run --env-file .env python -m market_data.cli daily
  run_step "台股資料健檢 (health --strict)" uv run --env-file .env python -m market_data.cli health --strict
  log "==> 盤前判讀回驗 (verify_morning_calls --append)"
  morning_call_outcomes
  calendar_refresh
  run_step "LLM 連線預檢" llm_preflight
  # 外層疊 Doppler `finmind` 專案：注入 FINMIND_TOKEN_*，台股個股新聞先查 FinMind。
  run_step "自選股分析 + 大盤復盤" doppler run -p finmind -c dev -- "${DOPPLER_RUN[@]}" bash -c 'uv run python scripts/notify.py --check --topic report && TELEGRAM_MESSAGE_THREAD_ID="$TELEGRAM_TOPIC_REPORT" uv run python main.py'
  run_step "個股分析至少一檔成功" require_stock_success
  if [[ -n "$SESSION_KEY" ]]; then
    printf '%s\n' "$SESSION_KEY" >"$DONE_MARK"
  else
    log "WARN: 取不到交易日曆（expected_session 為空），未寫完成標記"
  fi
  log "daily report done"
}

# 只有直接执行才跑 main；被 source（测试）时只载入函式。
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
