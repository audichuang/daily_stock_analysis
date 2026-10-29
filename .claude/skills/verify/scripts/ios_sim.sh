#!/bin/bash
set -euo pipefail

usage() {
  echo "用法：$0 <udid|up|down> <fixture|manual>" >&2
  exit 2
}

[[ $# -eq 2 ]] || usage
DSA_COMMAND="$1"
case "$DSA_COMMAND" in
  udid|up|down) ;;
  *) usage ;;
esac
case "$2" in
  fixture) DSA_SIMULATOR_NAME="DSA Fixture iPhone 17" ;;
  manual) DSA_SIMULATOR_NAME="DSA iPhone 17" ;;
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
if command == "up":
    conflicts = [device for device in devices
                 if device["name"].startswith("DSA ")
                 and device["udid"] != target["udid"]
                 and device["state"] == "Booted"]
    if conflicts:
        details = "、".join("{} ({})".format(device["name"], device["udid"]) for device in conflicts)
        raise SystemExit(f"錯誤：其他 DSA 模擬器已開機：{details}")
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
