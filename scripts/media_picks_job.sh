#!/usr/bin/env bash
# 平日 23:00 媒體點名的機械部分：同步 develop → media-picks → ptt-picks → 只 commit＋push 兩個 journal → 產摘要 JSON。
#
# 判讀（語音誤字的代號覆核、看多名單的建議）與 Telegram 摘要由 Orca 排程的 Claude 讀摘要後做，見 docs/daily-report-ops.md。
# 跟 daily_report.sh 一樣用 --detach 脫離呼叫者：Orca 收掉 agent 的 terminal 時擷取照樣跑完（2026-10-23 23:01
# Hindsight 的 repo 調查子程序繼承了 ORCA_* 環境變數，它結束時觸發 Orca 的 Stop hook，排程的 terminal 被收掉、
# 前景的 make media-picks 跟著被 SIGTERM）。也因為那時 agent 可能已經不在，任何一步失敗都由本腳本自己推通知（Telegram 系統通知主題）。
#
# log：logs/media_picks_job_<時刻>.log（--detach 會印出 `log: <路徑>`），最後一行 `media picks done` 或 `FAILED: …`；摘要：同名 .summary.json／.summary.index.md；持股清單 .holdings.json（`RESULT holdings=`，取不到記 none）。
# 可被 source 載入函式（測試用），只有直接執行才跑 main。逾時與通知共用 daily_report.sh 的函式。

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

# push_develop：每次只推已驗證的 SHA，lease 綁定同一輪驗證的 origin/develop；被拒就 fetch＋rebase、重新驗證再推一次。
# rebase 失敗要 abort，
# 不然主 checkout 卡在 rebase 中途，之後每晚都同步失敗。不加 --autostash：工作樹有未 commit 的改動時 rebase 會拒絕、
# 我們就照 fail 處理（推通知），不要偷偷替人 stash（stash 堆疊跨 worktree 共用）。
push_develop() {
  local sha origin_sha attempt
  for attempt in 1 2; do
    # 讀本地 develop 分支而不是 HEAD：呼叫端檢查完分支後，主 checkout 可能被別的 session 切走，
    # 讀 HEAD 會把別的分支的 commit 推成遠端 develop。
    sha=$(git rev-parse --verify refs/heads/develop) || return 1
    origin_sha=$(git rev-parse --verify origin/develop) || return 1
    journal_only_ahead "$origin_sha" "$sha" || return 1
    # lease 允許強推，必須另守祖先關係，避免遠端已前進時把它倒退。
    if git merge-base --is-ancestor "$origin_sha" "$sha" \
      && git_net push -q --force-with-lease="develop:${origin_sha}" origin "${sha}:refs/heads/develop"; then
      return 0
    fi
    (( attempt == 1 )) || return 1
    # 不用 pull --rebase：它在 fetch 的網路等待期間就決定好要 rebase 目前分支，主 checkout 這時被別的 session
    # 切走就會改寫別人的分支。先 fetch（網路），再做純本地的驗證，分支檢查放最後、緊接 rebase，
    # 把「檢查完到改寫」的空窗縮到只剩本地指令。要完全關掉得用獨立 checkout 或大家都遵守的鎖，不在這裡做。
    git_net fetch -q origin develop || return 1
    journal_only_ahead origin/develop refs/heads/develop || return 1
    if [[ "$(git branch --show-current)" != "develop" ]]; then
      echo "重試前發現目前不在 develop，不 rebase" >&2
      return 1
    fi
    if ! git rebase -q origin/develop >&2; then
      git rebase --abort >&2 2>/dev/null
      return 1
    fi
  done
  return 1
}

# journal_only_ahead [BASE HEAD]：固定兩端 SHA 後，每個本地 commit 都只動 journal/ 且沒有 merge 才回 0；
# 預設讀 origin/develop..HEAD，push 時傳入該輪固定的 SHA，不讓檢查中途移動的 ref 改掉範圍。
# 原因寫 stderr。push 與 rebase 前都要過這關，不然會把人在主 checkout 留下的非 journal commit 一起推上去。
journal_only_ahead() {
  local f base head merges files
  base=$(git rev-parse -q --verify "${1:-origin/develop}^{commit}") \
    || { echo "找不到 ${1:-origin/develop}" >&2; return 1; }
  head=$(git rev-parse -q --verify "${2:-HEAD}^{commit}") || return 1
  merges=$(git rev-list --merges "${base}..${head}") || return 1
  if [[ -n "$merges" ]]; then
    echo "本地領先 origin/develop 的 commit 含 merge commit" >&2
    return 1
  fi
  files=$(git log --no-merges --no-renames --name-only --format= "${base}..${head}") || return 1
  while IFS= read -r f; do
    [[ -z "$f" || "$f" == journal/* ]] && continue
    echo "本地領先 origin/develop 的 commit 動到 journal/ 以外的檔（${f}）" >&2
    return 1
  done <<<"$files"
}

# push_journal_cli：排程的 Claude 自己 commit 完 journal（review／verdicts）後呼叫，把 push 的守門放在有測試的程式碼裡。
# 只在 develop、且領先 origin/develop 的 commit 全是 journal/ 才推（被拒就 fetch＋rebase 再推，失敗 abort rebase）。
# stdout 只印最後一行：`push ok`／`push none`（沒有領先）／`push refused: <原因>`／`push failed`；原因同時寫 stderr。0＝ok／none，1＝其餘。
push_journal_cli() {
  local branch reason
  branch=$(git branch --show-current)
  if [[ "$branch" != "develop" ]]; then
    reason="目前在 ${branch:-detached HEAD}，不是 develop"
    echo "$reason" >&2
    echo "push refused: $reason"
    return 1
  fi
  if ! reason=$(journal_only_ahead 2>&1 >/dev/null); then
    echo "$reason" >&2
    echo "push refused: $reason"
    return 1
  fi
  if [[ -z "$(git log --format=%h origin/develop..HEAD 2>/dev/null)" ]]; then
    echo "push none"
    return 0
  fi
  if push_develop; then
    echo "push ok"
  else
    echo "journal push 失敗（push 被拒且 rebase 失敗，或逾時）" >&2
    echo "push failed"
    return 1
  fi
}

# commit_journal：只 commit＋push 兩個 journal 檔；印 none（沒變更也沒有未推的 commit）／ok／fail。
# `git commit -- <檔>` 只收這兩個檔，即使 index 裡有別的暫存也不會帶進去。
# 沒有新變更但本地領先 origin/develop（上一晚 push 失敗留下的）也要推，不然永遠卡著。
# 先確認仍在 develop（人可能在 40 分鐘擷取期間切了分支）且領先的 commit 都只動 journal/，才 commit／push。
commit_journal() {
  local existing=() f changed=0 branch
  branch=$(git branch --show-current)
  if [[ "$branch" != "develop" ]]; then
    echo "主 checkout 目前在 ${branch:-detached HEAD}，不是 develop，不 commit／push" >&2
    echo fail
    return 0
  fi
  journal_only_ahead || { echo fail; return 0; }
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
  journal_only_ahead || { echo "不自動 rebase" >&2; return 1; }
  if ! git rebase -q origin/develop >&2; then
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

# capture_holdings OUT：唯讀讀應用庫的台股持股清單寫成 JSON（portfolio_codes.py）。失敗不拖垮本輪：
# 記 `RESULT holdings=none (原因)`、回 1，摘要照產、只是沒有「你的持股被點名」那一段；成功記 `RESULT holdings=<路徑>`。
# 子行程用 --env-file .env 取 STORAGE_DATABASE_URL；輸出先寫暫存檔，成功才改名，避免留下半份檔被當成有效清單。
capture_holdings() {
  local out="$1" tmp reason
  tmp="${out}.tmp"
  if run_with_timeout "${MEDIA_PICKS_HOLDINGS_TIMEOUT_SECONDS:-60}" \
      uv run --env-file .env python scripts/portfolio_codes.py >"$tmp" 2>>"$LOG"; then
    # 只留最後一行當 JSON（與 media_picks_brief 同）：import 時多印的雜訊行不該讓整份清單報廢
    tail -n 1 "$tmp" >"${tmp}.last" && mv -f "${tmp}.last" "$out"
    rm -f "$tmp"
    log "RESULT holdings=$out"
    return 0
  fi
  reason=$(tail -n 1 "$tmp" 2>/dev/null | head -c 200 | tr '\n' ' ')
  rm -f "$tmp" "${tmp}.last"
  log "RESULT holdings=none (${reason:-沒有輸出，逾時或程式失敗})"
  return 1
}

# summarize_run RUN_START SUMMARY [HOLDINGS]：RESULT since= 無條件先記（摘要失敗時 Claude 仍要用同一個值手動取證）；
# JSON 給程式切片，索引給主 agent 挑檔（單檔完整證據由子 agent 自己用 --code 取，--since 照 RESULT since= 那個值）。
# HOLDINGS 有檔才帶 --holdings（索引第一段標出被點名的持股）。
summarize_run() {
  local run_start="$1" summary="$2" holdings="${3:-}" extra=()
  [[ -n "$holdings" && -f "$holdings" ]] && extra=(--holdings "$holdings")
  log "RESULT since=$run_start"
  if uv run --no-project python scripts/media_picks_summary.py --since "$run_start" --json ${extra[@]+"${extra[@]}"} >"$summary" 2>>"$LOG" \
    && uv run --no-project python scripts/media_picks_summary.py --since "$run_start" --index ${extra[@]+"${extra[@]}"} >"${summary%.json}.index.md" 2>>"$LOG"; then
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

  # --push-journal：不取鎖、不擷取、不通知，只做 push_journal_cli（失敗由呼叫的 Claude 處理）
  if [[ "${1:-}" == "--push-journal" ]]; then
    push_journal_cli
    exit $?
  fi

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
  # 卡死的前一輪：FAILED＋通知；正常在跑：跳過但保留 log（排程的 Claude 靠它判斷）
  acquire_lock "logs/.media_picks_job.lock" 媒體點名 "${MEDIA_PICKS_STALE_LOCK_SECONDS:-10800}" 1 "媒體點名失敗 $(date +%F)"
  # 拿到鎖就先記 since：擷取中途掛掉的一輪也要讓 media_picks_summary.py --judge-since 看得到，它寫下的列才會被補判
  log "RESULT since=$run_start"

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

  # 持股清單（唯讀）：取不到只少一段，不算本輪失敗、不推通知
  local holdings="logs/media_picks_job_${run_id}.holdings.json"
  capture_holdings "$holdings" || holdings=""

  summarize_run "$run_start" "$summary" "$holdings" || problems+=("摘要產生失敗")

  if (( ${#problems[@]} > 0 )); then
    notify_failure "$(IFS='；'; echo "${problems[*]}")。log: $LOG" "媒體點名部分失敗 $(date +%F)"
  fi
  log "media picks done"
}

# 只有直接執行才跑 main；被 source（測試）時只載入函式。
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
