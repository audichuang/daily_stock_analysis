#!/bin/bash
set -euo pipefail

# DSA 只用一台模擬器：fixture 測試與手動驗證共用，兩者靠不同 bundle ID 分開（見 test-ui.sh）。
DSA_SIMULATOR_NAME="DSA iPhone 18 Pro Max"

usage() {
  echo "用法：$0 <udid|up|down>" >&2
  exit 2
}

[[ $# -eq 1 ]] || usage
DSA_COMMAND="$1"
case "$DSA_COMMAND" in
  udid|up|down) ;;
  *) usage ;;
esac

DSA_DEVICE="$(xcrun simctl list devices -j | python3 -c '
import json
import sys

command, name = sys.argv[1:]
devices = [device for runtime in json.load(sys.stdin)["devices"].values() for device in runtime]
matches = [device for device in devices if device["name"] == name]
if not matches:
    raise SystemExit(f"錯誤：找不到模擬器「{name}」。")
if len(matches) > 1:
    raise SystemExit(f"錯誤：模擬器「{name}」有 {len(matches)} 台同名裝置，請確認名稱唯一。")
target = matches[0]
print(target["udid"], target["state"])
' "$DSA_COMMAND" "$DSA_SIMULATOR_NAME")"
read -r DSA_SIMULATOR_ID DSA_SIMULATOR_STATE <<< "$DSA_DEVICE"

case "$DSA_COMMAND" in
  udid)
    printf '%s\n' "$DSA_SIMULATOR_ID"
    ;;
  up)
    if [[ "$DSA_SIMULATOR_STATE" == "Shutdown" ]]; then
      xcrun simctl boot "$DSA_SIMULATOR_ID" >&2
      xcrun simctl bootstatus "$DSA_SIMULATOR_ID" -b >&2
    fi
    printf '%s\n' "$DSA_SIMULATOR_ID"
    ;;
  down)
    if [[ "$DSA_SIMULATOR_STATE" == "Booted" ]]; then
      xcrun simctl shutdown "$DSA_SIMULATOR_ID"
    fi
    ;;
esac
