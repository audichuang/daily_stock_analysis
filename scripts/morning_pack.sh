#!/usr/bin/env bash
# 用法：morning_pack.sh <pack 目錄> <指令…>
# 執行指令，stdout 經 pipe 同時 tee 到暫存檔；指令成功（結束碼 0）才發布成正式 pack：
#   <日期>.txt（台北日期；已存在則 <日期>.<HHMMSS>.txt）。失敗就刪暫存檔，不留半份。
# 結束碼一律是指令自己的（PIPESTATUS[0]）；tee 寫到一半失敗（磁碟滿）不發布截斷檔，只 WARN；mkdir／tee／rename 失敗只印一行 WARN，不改結束碼。
# make 的 dry-run（make -n；MAKEFLAGS 的單字母旗標含 n）：recipe 含 $(MAKE) 的行照樣會執行，內層只印 recipe 文字、結束碼 0，
# 若發布會把那堆文字當成當天 pack 餵給臂腳本。dry-run 時照常執行指令（輸出到終端）、不發布、不建暫存檔，stderr 印一行說明。
# 暫存檔副檔名是 .partial，臂腳本的 find_pack 永不選它。
dir=$1
shift
warn() { echo "WARN morning_pack: $*" >&2; }
# MAKEFLAGS 格式（GNU make 3.81／4.x 實測）：單字母旗標集合 "nk"／"n"，或 " --no-print-directory -n"（旗標在長選項之後），
# "--" 之後是命令列變數（VAR=nnn）。只看 "--" 之前、形如 -?[a-zA-Z]+ 的 word；長選項與變數值裡的 n 不算。
make_dry_run() {
    local w
    for w in ${MAKEFLAGS-}; do
        [ "$w" = "--" ] && return 1
        [[ $w =~ ^-?[a-zA-Z]+$ && $w == *n* ]] && return 0
    done
    return 1
}
if make_dry_run; then
    echo "morning_pack: make dry-run（MAKEFLAGS=${MAKEFLAGS}），不發布 pack" >&2
    "$@"
    exit $?
fi
mkdir -p "$dir" 2>/dev/null || warn "無法建立 ${dir}，這次不存 pack"
day=$(TZ=Asia/Taipei date +%F)
part="$dir/$day.$$.partial"
"$@" | tee "$part" 2>/dev/null
st=("${PIPESTATUS[@]}")    # 必須緊接在 pipeline 之後保存
rc=${st[0]}
if [ "${st[1]:-0}" -ne 0 ]; then
    warn "tee 寫入失敗（結束碼 ${st[1]}，磁碟滿？），不發布這份 pack"
    rm -f "$part" 2>/dev/null
    exit "$rc"
fi
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
