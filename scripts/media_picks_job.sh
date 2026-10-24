#!/usr/bin/env bash
# 平日 23:00 媒體點名的機械部分：同步 develop → media-picks → ptt-picks → 只 commit＋push 兩個 journal → 產摘要 JSON。
#
# 判讀（語音誤字的代號覆核、看多名單的建議）與 Bark 摘要由 Orca 排程的 Claude 讀摘要後做，見 docs/daily-report-ops.md。
# 跟 daily_report.sh 一樣用 --detach 脫離呼叫者：Orca 收掉 agent 的 terminal 時擷取照樣跑完（2026-10-23 23:01
# Hindsight 的 repo 調查子程序繼承了 ORCA_* 環境變數，它結束時觸發 Orca 的 Stop hook，排程的 terminal 被收掉、
# 前景的 make media-picks 跟著被 SIGTERM）。也因為那時 agent 可能已經不在，任何一步失敗都由本腳本自己推 Bark。
#
# log：logs/media_picks_job_<時刻>.log，最後一行 `media picks done` 或 `FAILED: …`；摘要：同名 .summary.json／.summary.md。
# 可被 source 載入函式（測試用），只有直接執行才跑 main。逾時與 Bark 共用 daily_report.sh 的函式。

# shellcheck source=scripts/daily_report.sh
. "$(dirname "${BASH_SOURCE[0]}")/daily_report.sh"

JOURNAL_FILES=(journal/media-picks.jsonl journal/ptt-picks.jsonl)

fail() {
  log "FAILED: $1"
  notify_failure "$1。log: $LOG" "媒體點名失敗 $(date +%F)"
  exit 1
}

# commit_journal：只 commit＋push 兩個 journal 檔；印 none（沒變更）／ok／fail。
# `git commit -- <檔>` 只收這兩個檔，即使 index 裡有別的暫存也不會帶進去。
commit_journal() {
  local existing=() f
  for f in "${JOURNAL_FILES[@]}"; do
    [[ -e "$f" ]] && existing+=("$f")
  done
  if (( ${#existing[@]} == 0 )) || [[ -z "$(git status --porcelain -- "${existing[@]}")" ]]; then
    echo none
    return 0
  fi
  if git add -- "${existing[@]}" \
    && git commit -q -m "journal: media picks $(date +%F)" -- "${existing[@]}" \
    && git push -q origin develop; then
    echo ok
  else
    echo fail
  fi
}

main() {
  set -uo pipefail
  cd "$(dirname "$0")/.."
  # notebooklm、yt-dlp 是 uv tool，裝在 ~/.local/bin；Orca 的 terminal 不一定帶這段 PATH
  export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"

  if [[ "${1:-}" == "--detach" ]]; then
    mkdir -p logs
    nohup perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV or die "exec: $!"' bash "$0" \
      >>logs/media_picks_launcher.log 2>&1 </dev/null &
    echo "media picks started in background (pid $!); progress: newest logs/media_picks_job_*.log"
    exit 0
  fi

  mkdir -p logs
  local run_id
  run_id=$(date +%Y%m%d_%H%M%S)
  LOG="logs/media_picks_job_${run_id}.log"
  local summary="logs/media_picks_job_${run_id}.summary.json"
  # 摘要只收本輪寫入的列；用開始時刻而不是「今天」，跨午夜的一輪才不會漏
  local run_start
  run_start=$(date +%Y-%m-%dT%H:%M:%S%z)

  LOCK="logs/.media_picks_job.lock"
  if ! mkdir "$LOCK" 2>/dev/null; then
    if kill -0 "$(cat "$LOCK/pid" 2>/dev/null)" 2>/dev/null; then
      log "另一輪媒體點名仍在執行（pid $(cat "$LOCK/pid")），本次不重複跑"
      exit 0
    fi
    rm -rf "$LOCK" && mkdir "$LOCK"   # 前一輪被砍掉留下的鎖
  fi
  echo $$ >"$LOCK/pid"
  trap 'rm -rf "$LOCK"' EXIT

  log "media picks start (log: $LOG)"
  local branch
  branch=$(git branch --show-current)
  [[ "$branch" == "develop" ]] || fail "主 checkout 目前在 ${branch:-detached HEAD}，不是 develop，未擷取"
  { git fetch -q origin && git merge --ff-only -q origin/develop; } >>"$LOG" 2>&1 \
    || fail "同步 origin/develop 失敗（fetch 或 fast-forward），未擷取"

  local media_rc=0 ptt_rc=0 push problems=()
  log "==> make media-picks"
  run_with_timeout "${MEDIA_PICKS_TIMEOUT_SECONDS:-3600}" make media-picks >>"$LOG" 2>&1 || media_rc=$?
  log "RESULT media-picks rc=$media_rc"
  (( media_rc == 124 )) && problems+=("media-picks 逾時已終止")
  (( media_rc != 0 && media_rc != 124 )) && problems+=("media-picks 全部集數失敗（rc=$media_rc）")

  log "==> make ptt-picks"
  run_with_timeout "${PTT_PICKS_TIMEOUT_SECONDS:-600}" make ptt-picks >>"$LOG" 2>&1 || ptt_rc=$?
  log "RESULT ptt-picks rc=$ptt_rc"
  (( ptt_rc != 0 )) && problems+=("ptt-picks 失敗（rc=$ptt_rc，搜尋頁抓不到或全部文章失敗）")

  push=$(commit_journal 2>>"$LOG")
  log "RESULT journal push=$push"
  [[ "$push" == "fail" ]] && problems+=("journal commit／push 失敗")

  # JSON 給程式切片、markdown 給 Claude 從頭讀（每檔講者原話＋數據＋歷史）
  if uv run --no-project python scripts/media_picks_summary.py --since "$run_start" --json >"$summary" 2>>"$LOG" \
    && uv run --no-project python scripts/media_picks_summary.py --since "$run_start" >"${summary%.json}.md" 2>>"$LOG"; then
    log "RESULT summary=$summary"
    log "RESULT summary_md=${summary%.json}.md"
  else
    problems+=("摘要產生失敗")
    log "RESULT summary=none"
  fi

  if (( ${#problems[@]} > 0 )); then
    notify_failure "$(IFS='；'; echo "${problems[*]}")。log: $LOG" "媒體點名部分失敗 $(date +%F)"
  fi
  log "media picks done"
}

# 只有直接執行才跑 main；被 source（測試）時只載入函式。
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
