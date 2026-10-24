#!/usr/bin/env bash
# 平日 23:00 媒體點名的機械部分：同步 develop → media-picks → ptt-picks → 只 commit＋push 兩個 journal → 產摘要 JSON。
#
# 判讀（語音誤字的代號覆核、看多名單的建議）與 Bark 摘要由 Orca 排程的 Claude 讀摘要後做，見 docs/daily-report-ops.md。
# 跟 daily_report.sh 一樣用 --detach 脫離呼叫者：Orca 收掉 agent 的 terminal 時擷取照樣跑完（2026-10-23 23:01
# Hindsight 的 repo 調查子程序繼承了 ORCA_* 環境變數，它結束時觸發 Orca 的 Stop hook，排程的 terminal 被收掉、
# 前景的 make media-picks 跟著被 SIGTERM）。也因為那時 agent 可能已經不在，任何一步失敗都由本腳本自己推 Bark。
#
# log：logs/media_picks_job_<時刻>.log（--detach 會印出 `log: <路徑>`），最後一行 `media picks done` 或 `FAILED: …`；摘要：同名 .summary.json／.summary.index.md。
# 可被 source 載入函式（測試用），只有直接執行才跑 main。逾時與 Bark 共用 daily_report.sh 的函式。

# shellcheck source=scripts/daily_report.sh
. "$(dirname "${BASH_SOURCE[0]}")/daily_report.sh"

JOURNAL_FILES=(journal/media-picks.jsonl journal/ptt-picks.jsonl)

fail() {
  log "FAILED: $1"
  notify_failure "$1。log: $LOG" "媒體點名失敗 $(date +%F)"
  exit 1
}

# git 網路呼叫（fetch／pull／push）的逾時：網路卡住不能一直佔著鎖。stdout 一律導向 stderr，
# 因為 commit_journal 的 stdout 是回傳值。
git_net() {
  run_with_timeout "${MEDIA_PICKS_GIT_TIMEOUT_SECONDS:-120}" git "$@" >&2
}

# push_develop：push 被拒（別處先推了 develop）就 pull --rebase 再推一次；rebase 失敗要 abort，
# 不然主 checkout 卡在 rebase 中途，之後每晚都同步失敗。--autostash：排程的 Claude 追加的檔可能還沒 commit。
push_develop() {
  git_net push -q origin develop && return 0
  if git_net pull --rebase --autostash -q origin develop; then
    git_net push -q origin develop
    return
  fi
  git rebase --abort >&2 2>/dev/null
  return 1
}

# commit_journal：只 commit＋push 兩個 journal 檔；印 none（沒變更也沒有未推的 commit）／ok／fail。
# `git commit -- <檔>` 只收這兩個檔，即使 index 裡有別的暫存也不會帶進去。
# 沒有新變更但本地領先 origin/develop（上一晚 push 失敗留下的）也要推，不然永遠卡著。
commit_journal() {
  local existing=() f changed=0
  for f in "${JOURNAL_FILES[@]}"; do
    [[ -e "$f" ]] && existing+=("$f")
  done
  if (( ${#existing[@]} > 0 )) && [[ -n "$(git status --porcelain -- "${existing[@]}")" ]]; then
    changed=1
    if ! { git add -- "${existing[@]}" \
      && git commit -q -m "journal: media picks $(date +%F)" -- "${existing[@]}"; } >&2; then
      echo fail
      return 0
    fi
  fi
  if (( ! changed )) && [[ -z "$(git log --format=%h origin/develop..HEAD 2>/dev/null)" ]]; then
    echo none
    return 0
  fi
  if push_develop; then
    echo ok
  else
    echo fail
  fi
}

# sync_develop：fetch 後 ff-only 併入 origin/develop；ff 失敗時，只有本地獨有的 commit 全部只動 journal/
# （上一晚 push 失敗留下的）才允許 rebase，其餘（含 merge commit）照舊失敗。成功回 0，原因寫 stderr。
sync_develop() {
  git_net fetch -q origin || { echo "git fetch 失敗或逾時" >&2; return 1; }
  git merge --ff-only -q origin/develop >&2 && return 0
  local f
  if [[ -n "$(git rev-list --merges origin/develop..HEAD)" ]]; then
    echo "本地有 merge commit，不自動 rebase" >&2
    return 1
  fi
  while IFS= read -r f; do
    [[ -z "$f" || "$f" == journal/* ]] && continue
    echo "本地獨有 commit 動到 journal/ 以外的檔（${f}），不自動 rebase" >&2
    return 1
  done < <(git log --no-merges --name-only --format= origin/develop..HEAD)
  if ! git rebase --autostash -q origin/develop >&2; then
    git rebase --abort >&2 2>/dev/null
    echo "rebase origin/develop 失敗，已 abort" >&2
    return 1
  fi
}

# 本輪 log 的 run id：--detach 的父行程先選好、用 MEDIA_PICKS_RUN_ID 傳進來；直接執行就自己產生。
pick_run_id() {
  echo "${MEDIA_PICKS_RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
}

# detach_media SCRIPT：脫離 session 啟動子行程，並印出確切的 log 路徑（`log: …` 一行）。
# 排程的 Claude 以前找「最新的 log」，子行程還沒建檔時找到的是上一晚那份（已含 `media picks done`）。
detach_media() {
  mkdir -p logs
  local run_id
  run_id=$(pick_run_id)
  MEDIA_PICKS_RUN_ID="$run_id" spawn_detached "$1" logs/media_picks_launcher.log
  echo "media picks started in background (pid $DETACHED_PID)"
  echo "log: logs/media_picks_job_${run_id}.log"
}

# summarize_run RUN_START SUMMARY：RESULT since= 無條件先記（摘要失敗時 Claude 仍要用同一個值手動取證）；
# JSON 給程式切片，索引給主 agent 挑檔（單檔完整證據由子 agent 自己用 --code 取，--since 照 RESULT since= 那個值）。
summarize_run() {
  local run_start="$1" summary="$2"
  log "RESULT since=$run_start"
  if uv run --no-project python scripts/media_picks_summary.py --since "$run_start" --json >"$summary" 2>>"$LOG" \
    && uv run --no-project python scripts/media_picks_summary.py --since "$run_start" --index >"${summary%.json}.index.md" 2>>"$LOG"; then
    log "RESULT summary=$summary"
    log "RESULT summary_index=${summary%.json}.index.md"
  else
    log "RESULT summary=none"
    return 1
  fi
}

main() {
  set -uo pipefail
  cd "$(dirname "$0")/.."
  # notebooklm、yt-dlp 是 uv tool，裝在 ~/.local/bin；Orca 的 terminal 不一定帶這段 PATH
  [[ -d /opt/homebrew/bin ]] && PATH="/opt/homebrew/bin:$PATH"
  export PATH="$HOME/.local/bin:$PATH"

  if [[ "${1:-}" == "--detach" ]]; then
    detach_media "$0"
    exit 0
  fi

  mkdir -p logs
  local run_id
  run_id=$(pick_run_id)
  LOG="logs/media_picks_job_${run_id}.log"
  local summary="logs/media_picks_job_${run_id}.summary.json"
  # 摘要只收本輪寫入的列；用開始時刻而不是「今天」，跨午夜的一輪才不會漏
  local run_start
  run_start=$(date +%Y-%m-%dT%H:%M:%S%z)

  # 先寫第一行 log：--detach 印出的 log 路徑從這一刻起就存在（含下面「本次不重複跑」的情況）
  log "media picks start (pid $$, log: $LOG)"
  # 卡死的前一輪：FAILED＋Bark；正常在跑：跳過但保留 log（排程的 Claude 靠它判斷）
  acquire_lock "logs/.media_picks_job.lock" 媒體點名 "${MEDIA_PICKS_STALE_LOCK_SECONDS:-10800}" 1 "媒體點名失敗 $(date +%F)"

  local branch
  branch=$(git branch --show-current)
  [[ "$branch" == "develop" ]] || fail "主 checkout 目前在 ${branch:-detached HEAD}，不是 develop，未擷取"
  sync_develop >>"$LOG" 2>&1 \
    || fail "同步 origin/develop 失敗（fetch、fast-forward 或僅 journal 的 rebase），未擷取"

  local media_rc=0 ptt_rc=0 push problems=()
  log "==> make media-picks"
  run_with_timeout "${MEDIA_PICKS_TIMEOUT_SECONDS:-3600}" make media-picks >>"$LOG" 2>&1 || media_rc=$?
  log "RESULT media-picks rc=$media_rc"
  (( media_rc == 124 )) && problems+=("media-picks 逾時已終止")
  (( media_rc != 0 && media_rc != 124 )) && problems+=("media-picks 全部集數失敗（rc=${media_rc}）")

  log "==> make ptt-picks"
  run_with_timeout "${PTT_PICKS_TIMEOUT_SECONDS:-600}" make ptt-picks >>"$LOG" 2>&1 || ptt_rc=$?
  log "RESULT ptt-picks rc=$ptt_rc"
  (( ptt_rc != 0 )) && problems+=("ptt-picks 失敗（rc=${ptt_rc}，搜尋頁抓不到或全部文章失敗）")

  push=$(commit_journal 2>>"$LOG")
  log "RESULT journal push=$push"
  [[ "$push" == "fail" ]] && problems+=("journal commit／push 失敗")

  summarize_run "$run_start" "$summary" || problems+=("摘要產生失敗")

  if (( ${#problems[@]} > 0 )); then
    notify_failure "$(IFS='；'; echo "${problems[*]}")。log: $LOG" "媒體點名部分失敗 $(date +%F)"
  fi
  log "media picks done"
}

# 只有直接執行才跑 main；被 source（測試）時只載入函式。
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
