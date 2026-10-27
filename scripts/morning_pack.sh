#!/usr/bin/env bash
# 用法：morning_pack.sh <pack 目錄> <指令…>
# 執行指令，stdout 經 pipe 同時 tee 到暫存檔；指令成功（結束碼 0）才發布成正式 pack：
#   <日期>.txt（台北日期；已存在則 <日期>.<HHMMSS>.txt）。失敗就刪暫存檔，不留半份。
# 結束碼一律是指令自己的（PIPESTATUS[0]）；mkdir／tee／rename 失敗只印一行 WARN，不改結束碼。
# 暫存檔副檔名是 .partial，臂腳本的 find_pack 永不選它。
dir=$1
shift
warn() { echo "WARN morning_pack: $*" >&2; }
mkdir -p "$dir" 2>/dev/null || warn "無法建立 ${dir}，這次不存 pack"
day=$(TZ=Asia/Taipei date +%F)
part="$dir/$day.$$.partial"
"$@" | tee "$part" 2>/dev/null
rc=${PIPESTATUS[0]}
if [ "$rc" -ne 0 ]; then
    rm -f "$part" 2>/dev/null
    exit "$rc"
fi
if [ -f "$part" ]; then
    final="$dir/$day.txt"
    [ -e "$final" ] && final="$dir/$day.$(TZ=Asia/Taipei date +%H%M%S).txt"
    mv -n "$part" "$final" 2>/dev/null && [ ! -e "$part" ] || { warn "無法發布 ${final}"; rm -f "$part" 2>/dev/null; }
else
    warn "暫存檔沒寫成（${part}），這次不存 pack"
fi
exit "$rc"
