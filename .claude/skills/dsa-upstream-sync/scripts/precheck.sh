#!/bin/bash
# Orca automation precheck（dsa 上游同步）：exit 0 才啟動 agent，非 0 記成 skipped、不花 token。
# 條件：上游 main 有 >= DSA_SYNC_MIN_COMMITS（預設 5）個 fork 還沒收的 commit，
# 且 origin 上沒有尚未合進 develop 的 chore/upstream-sync-* 分支（上一輪還在等使用者審 = 鎖）。
# ~/.config/dsa-upstream-sync/force-once 存在時略過 commit 數門檻（測試用，skill 第 0 步用完即刪）；鎖照樣檢查。
set -euo pipefail
cd "$(dirname "$0")" && cd "$(git rev-parse --show-toplevel)"
git fetch -q upstream main
git fetch -q origin --prune
min=${DSA_SYNC_MIN_COMMITS:-5}
pending=$(git rev-list --count origin/develop..upstream/main)
echo "upstream pending=$pending (min=$min)"
# origin 的 fetch refspec 只抓 main 與 develop，git branch -r 看不到 sync 分支，所以用 ls-remote 逐條判斷是否已進 develop。
inflight=""
while read -r sha ref; do
  [ -n "$sha" ] || continue
  git cat-file -e "$sha^{commit}" 2>/dev/null || git fetch -q origin "$sha"
  git merge-base --is-ancestor "$sha" origin/develop || inflight="$inflight ${ref#refs/heads/}"
done < <(git ls-remote origin 'refs/heads/chore/upstream-sync-*')
if [ -n "$inflight" ]; then
  echo "awaiting review: $inflight"
  exit 1
fi
if [ -f "$HOME/.config/dsa-upstream-sync/force-once" ]; then
  echo "force-once present"
  [ "$pending" -ge 1 ] || exit 1
  exit 0
fi
[ "$pending" -ge "$min" ] || exit 1
